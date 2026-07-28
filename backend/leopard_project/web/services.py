from __future__ import annotations

import hashlib
import json
import re
from difflib import SequenceMatcher, get_close_matches
from dataclasses import dataclass
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path, PurePath
from typing import Any
from uuid import uuid4

from pypdf import PdfReader

from leopard_project.config import CONFIG_DIR, load_seed_bundle, normalize_alias

from .models import ALLOWED_TRANSITIONS, Report, ReportFile, ReportSection, ReportStatus, SectorMention, UnmappedTerm
from .repository import ReportRepository


class WebDomainError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class UploadPolicy:
    max_file_size_bytes: int
    allowed_mime_types: frozenset[str]
    required_header: bytes

    @classmethod
    def load(cls) -> "UploadPolicy":
        data = json.loads((CONFIG_DIR / "pdf_upload_policy_v1.json").read_text(encoding="utf-8"))
        return cls(data["max_file_size_bytes"], frozenset(data["allowed_mime_types"]), data["required_file_header"].encode())


def validate_pdf(filename: str, content_type: str, payload: bytes, policy: UploadPolicy) -> None:
    if "/" in filename or "\\" in filename or PurePath(filename).name != filename or any(part == ".." for part in PurePath(filename).parts):
        raise WebDomainError("unsafe_filename", "The uploaded filename is not safe")
    if not filename.lower().endswith(".pdf") or content_type not in policy.allowed_mime_types:
        raise WebDomainError("invalid_pdf_type", "Only application/pdf files are accepted")
    if not payload.startswith(policy.required_header):
        raise WebDomainError("invalid_pdf_header", "The file does not contain a PDF header")
    if len(payload) > policy.max_file_size_bytes:
        raise WebDomainError("pdf_too_large", "The PDF exceeds the configured size limit", 413)


def extract_text_layer(payload: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(payload), strict=False)
        extracted = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
        if extracted:
            return extracted
    except Exception:
        pass
    decoded = payload.decode("utf-8", errors="ignore")
    marker = re.search(r"%LEOPARD_TEXT_BEGIN\s*(.*?)\s*%LEOPARD_TEXT_END", decoded, re.S)
    if marker:
        return marker.group(1).replace("\\n", "\n").strip()
    strings = re.findall(r"\((.*?)(?<!\\)\)\s*Tj", decoded, re.S)
    return "\n".join(value.replace("\\(", "(").replace("\\)", ")") for value in strings).strip()


def extract_layout_text(payload: bytes) -> str:
    """Extract page-aware layout text for deterministic table recovery."""
    try:
        reader = PdfReader(BytesIO(payload), strict=False)
        pages: list[str] = []
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                page_text = page.extract_text(extraction_mode="layout") or ""
            except TypeError:
                page_text = page.extract_text() or ""
            pages.append(f"[[LEOPARD_PAGE:{page_number}]]\n{page_text}")
        return "\n".join(pages).strip()
    except Exception:
        return ""


def extract_positioned_pages(payload: bytes) -> list[dict[str, Any]]:
    """Return page-local text fragments with PDF coordinates; no OCR or network."""
    try:
        reader = PdfReader(BytesIO(payload), strict=False)
    except Exception:
        return []
    pages: list[dict[str, Any]] = []
    for page_number, page in enumerate(reader.pages, start=1):
        fragments: list[dict[str, Any]] = []

        def visitor(text: str, _cm: Any, tm: Any, _font: Any, font_size: float) -> None:
            compact = _compact(text)
            if compact:
                fragments.append({
                    "x": float(tm[4]),
                    "y": float(tm[5]),
                    "font_size": float(font_size),
                    "text": compact,
                })

        try:
            page.extract_text(visitor_text=visitor)
        except Exception:
            return []
        pages.append({"page": page_number, "items": fragments})
    return pages


HEADING_PREFIX = r"(?:第?[一二三四五六七八九十百\d]+[、.．]\s*)?"
STATUS_LABELS = ("不碰", "强观", "观察", "弱观", "转持", "持有", "转弱", "离场", "未提")
STATUS_TO_CODE = {
    "不碰": "avoid", "强观": "strong_watch", "观察": "watch", "弱观": "weak_watch",
    "转持": "turn_hold", "持有": "hold", "转弱": "turn_weak", "离场": "exit", "未提": "not_mentioned",
}


def _compact(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _explicit_field(text: str, labels: tuple[str, ...]) -> tuple[str, tuple[int, int] | None]:
    alternatives = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"(?m)^\s*{HEADING_PREFIX}(?:{alternatives})\s*[：:]\s*(.+)$", text)
    return (_compact(match.group(1)), match.span(1)) if match else ("", None)


def _bounded_field(
    text: str,
    labels: tuple[str, ...],
    stop_labels: tuple[str, ...],
    *,
    max_chars: int = 1400,
) -> tuple[str, tuple[int, int] | None]:
    alternatives = "|".join(re.escape(label) for label in labels)
    stops = "|".join(re.escape(label) for label in stop_labels)
    match = re.search(
        rf"(?ms)^\s*{HEADING_PREFIX}(?:{alternatives})\s*(?:[：:]|\n)\s*(.+?)(?=^\s*{HEADING_PREFIX}(?:{stops})\s*(?:[：:]|\n)|\Z)",
        text,
    )
    if not match:
        return "", None
    value = _compact(match.group(1))[:max_chars].strip()
    return value, (match.start(1), match.start(1) + len(value))


def _source_page(text: str, start: int) -> int:
    controlled_markers = [int(value) for value in re.findall(r"\[\[LEOPARD_PAGE:(\d+)\]\]", text[:start])]
    if controlled_markers:
        return controlled_markers[-1]
    page_markers = [int(value) for value in re.findall(r"第\s*(\d+)\s*页", text[:start])]
    return page_markers[-1] if page_markers else 1


def _date_matches(value: str) -> list[date]:
    found: list[date] = []
    for match in re.finditer(r"(20\d{2})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})\s*日?", value):
        try:
            found.append(date(*map(int, match.groups())))
        except ValueError:
            continue
    return found


def detect_report_date(text: str, filename: str) -> dict[str, Any]:
    title_region = "\n".join(text.splitlines()[:20])
    title_dates = _date_matches(title_region)
    body_dates = _date_matches(text)
    filename_dates = _date_matches(filename)
    unique_title = sorted(set(title_dates))
    if len(unique_title) == 1:
        chosen = unique_title[0]
        conflict = bool(filename_dates and chosen not in filename_dates)
        return {
            "value": chosen,
            "source": "pdf_title" if not conflict else "date_conflict",
            "confidence": "high" if not conflict else "low",
            "conflict": conflict,
        }
    if filename_dates:
        unique_filename = sorted(set(filename_dates))
        return {
            "value": unique_filename[0],
            "source": "filename" if len(unique_filename) == 1 else "date_conflict",
            "confidence": "medium" if len(unique_filename) == 1 else "low",
            "conflict": len(unique_filename) != 1,
        }
    month_day = re.search(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*日", filename)
    years = sorted({item.year for item in body_dates})
    if month_day and len(years) == 1:
        try:
            return {
                "value": date(years[0], int(month_day.group(1)), int(month_day.group(2))),
                "source": "filename_cross_checked",
                "confidence": "medium",
                "conflict": False,
            }
        except ValueError:
            pass
    unique_body = sorted(set(body_dates))
    if len(unique_body) == 1:
        return {"value": unique_body[0], "source": "pdf_body", "confidence": "high", "conflict": False}
    return {
        "value": unique_body[-1] if unique_body else None,
        "source": "date_conflict" if unique_body else "unavailable",
        "confidence": "low",
        "conflict": len(unique_body) > 1,
    }


def _report_title(text: str) -> tuple[str, tuple[int, int] | None]:
    explicit, span = _explicit_field(text, ("报告标题",))
    if explicit:
        return explicit, span
    match = re.search(
        r"(?m)^\s*(大盘猎豹\s*20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\s*直播总结[^\n]*)$",
        text,
    )
    if match:
        return _compact(match.group(1)), match.span(1)
    lines = [line.strip() for line in text.splitlines() if line.strip() and not re.fullmatch(r"第\s*\d+\s*页", line.strip())]
    return (lines[0][:300], (0, len(lines[0]))) if lines else ("待复核报告", None)


def _main_fields(text: str) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    core_match = re.search(
        r"(?ms)^\s*(?:核心定性|核心观点|核心结论)\s*[：:]\s*(.+?)(?=^\s*(?:行情结论|大盘结论|数据与历史说明|一[、.．]))",
        text,
    )
    core = _compact(core_match.group(1)) if core_match else ""
    core_span = core_match.span(1) if core_match else None
    if not core:
        core, core_span = _explicit_field(text, ("核心定性", "核心观点", "核心结论"))
    if not core:
        core, core_span = _bounded_field(
            text,
            ("核心结论速览",),
            ("一、当日行情定性", "一、当日行情复盘", "行情结论", "核心定性"),
            max_chars=1000,
        )
    market_match = re.search(
        r"(?ms)^\s*(?:行情结论|大盘结论|大盘路径|指数路径)\s*[：:]\s*(.+?)(?=^\s*(?:数据与历史说明|一[、.．]|二[、.．]|风险提示))",
        text,
    )
    market = _compact(market_match.group(1)) if market_match else ""
    market_span = market_match.span(1) if market_match else None
    if not market:
        market, market_span = _explicit_field(text, ("行情结论", "大盘结论", "大盘路径", "指数路径"))
    if not market:
        market, market_span = _bounded_field(
            text,
            ("核心攻防线",),
            ("仓位纪律", "板块主线", "核心定性", "风险提示"),
            max_chars=700,
        )
    risk, risk_span = _explicit_field(text, ("风险提示", "风险点"))
    if not risk:
        risk_match = re.search(
            r"(?ms)^\s*五[、.．]\s*次日验证与两个操作风险\s*(.+?)(?=^\s*(?:第\s*\d+\s*页\s*)?六[、.．]\s*板块历史路径图)",
            text,
        )
        if risk_match:
            risk = _compact(risk_match.group(1))
            risk_span = risk_match.span(1)
    if not risk:
        risk, risk_span = _bounded_field(
            text,
            ("次日验证与两个操作风险", "操作风险"),
            ("板块历史路径图", "板块观点详细汇总"),
            max_chars=1000,
        )
    if not risk:
        risk = "本报告未单列风险提示。"
    fields = {"core_view": core, "market_path": market, "risk_warning": risk}
    provenance: dict[str, dict[str, Any]] = {}
    for key, span in (("core_view", core_span), ("market_path", market_span), ("risk_warning", risk_span)):
        provenance[key] = {
            "extracted_value": fields[key],
            "extraction_method": "pdf_text_layer" if span else "explicit_absence_notice",
            "source_page": _source_page(text, span[0]) if span else None,
            "source_text_range": list(span) if span else None,
            "source_reference": f"第{_source_page(text, span[0])}页·{key}" if span else "PDF未单列该字段",
            "source_text_excerpt": text[span[0]:span[1]].strip()[:500] if span else fields[key],
            "confidence": "high" if span else "medium",
            "validation_flags": [] if span else ["explicit_absence_notice"],
            "manually_modified": False,
        }
    return fields, provenance


def _split_basis_condition(value: str) -> tuple[str, str]:
    value = _compact(value)
    candidates = list(re.finditer(
        r"(?:^|[。；])\s*(下一交易日|等待|继续等待|未给出|若|只有|后续以|本场未给|需等待)",
        value,
    ))
    if not candidates:
        return value, "本报告未单列观察条件。"
    split_at = candidates[-1].start(1)
    if split_at < max(8, len(value) // 4):
        split_at = candidates[0].start(1)
    return value[:split_at].strip() or value, value[split_at:].strip() or "本报告未单列观察条件。"


def _normalized_sector_token(value: str) -> str:
    return re.sub(r"[\s/／、·]+", "", value).lower()


def _sector_from_fragment(fragment: str) -> Any | None:
    token = _normalized_sector_token(fragment)
    if len(token) < 2 or token in {"板块", "历史路径", "主要依据", "观察条件"}:
        return None
    sectors = load_seed_bundle().sectors
    exact = [item for item in sectors if _normalized_sector_token(item.sector_name) == token]
    if len(exact) == 1:
        return exact[0]
    prefix = [
        item for item in sectors
        if _normalized_sector_token(item.sector_name).startswith(token)
        or token.startswith(_normalized_sector_token(item.sector_name))
    ]
    if not prefix:
        return None
    prefix.sort(key=lambda item: len(_normalized_sector_token(item.sector_name)), reverse=True)
    longest = len(_normalized_sector_token(prefix[0].sector_name))
    best = [item for item in prefix if len(_normalized_sector_token(item.sector_name)) == longest]
    return best[0] if len(best) == 1 else None


def _spaced_label_start(line: str, label: str) -> int:
    match = re.search(r"\s*".join(map(re.escape, label)), line)
    return match.start() if match else -1


def _assessment_quality(record: dict[str, Any]) -> tuple[str, str, list[str]]:
    flags: list[str] = []
    for field in ("recent_path_summary", "current_judgement", "main_basis", "observation_condition"):
        if not record.get(field, "").strip():
            flags.append(f"missing_{field}")
    if not record.get("source_page"):
        flags.append("missing_source_page")
    if record.get("source_text_start") is None or record.get("source_text_end") is None:
        flags.append("missing_source_range")
    combined = f"{record.get('main_basis', '')} {record.get('observation_condition', '')}"
    status_count = len(re.findall("|".join(STATUS_LABELS), combined))
    if status_count >= 7:
        flags.append("abnormal_status_sequence")
    if len(record.get("current_judgement", "")) > 160 or len(record.get("main_basis", "")) > 650 or len(record.get("observation_condition", "")) > 500:
        flags.append("field_length_outlier")
    normalized_combined = _normalized_sector_token(combined)
    other_names = {
        item.sector_name
        for item in load_seed_bundle().sectors
        if item.sector_key != record.get("sector_key")
        and len(_normalized_sector_token(item.sector_name)) >= 3
        and _normalized_sector_token(item.sector_name) in normalized_combined
    }
    contextual_technology_cross_reference = (
        record.get("sector_key") == "electronic_components"
        and other_names <= {"CPO", "PCB"}
    )
    if len(other_names) >= 2 and not contextual_technology_cross_reference:
        flags.append("multiple_other_sector_names")
    blocking_flags = {"abnormal_status_sequence", "field_length_outlier", "multiple_other_sector_names", "crossed_sector_boundary", "conflicting_status"}
    if blocking_flags.intersection(flags):
        return "blocking_parse_error", "low", flags
    if flags:
        return "needs_attention", "medium", flags
    return "verified_structure", "high", flags


def _validate_assessment_set(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply cross-row checks that a single-cell quality pass cannot see."""
    by_sector: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_sector.setdefault(record["sector_key"], []).append(record)
    for rows in by_sector.values():
        if len({row.get("path_status") for row in rows}) > 1:
            for row in rows:
                row["validation_flags"] = sorted(set(row.get("validation_flags", []) + ["conflicting_status"]))
                row["quality_status"], row["confidence"] = "blocking_parse_error", "low"
    combined_values: list[str] = []
    for record in records:
        combined_values.append(_compact(f"{record.get('main_basis', '')} {record.get('observation_condition', '')}"))
    for index in range(1, len(records)):
        left, right = combined_values[index - 1:index + 1]
        if min(len(left), len(right)) >= 60 and SequenceMatcher(None, left, right).ratio() >= 0.97:
            for record in records[index - 1:index + 1]:
                record["validation_flags"] = sorted(set(record.get("validation_flags", []) + ["adjacent_content_highly_repeated"]))
                if record.get("quality_status") == "verified_structure":
                    record["quality_status"], record["confidence"] = "needs_attention", "medium"
    for value in {item for item in combined_values if combined_values.count(item) >= 4 and len(item) >= 30}:
        for index, record in enumerate(records):
            if combined_values[index] == value:
                record["validation_flags"] = sorted(set(record.get("validation_flags", []) + ["template_repetition"]))
                record["quality_status"], record["confidence"] = "blocking_parse_error", "low"
    return records


def _finalize_layout_assessment(row: dict[str, Any]) -> dict[str, Any] | None:
    status_text = _compact(" ".join(row["status_parts"]))
    status_labels = re.findall("|".join(STATUS_LABELS), status_text)
    status_label = status_labels[0] if len(set(status_labels)) == 1 else ""
    record: dict[str, Any] = {
        "sector_key": row["sector"].sector_key,
        "sector_name": row["sector"].sector_name,
        "path_status": STATUS_TO_CODE.get(status_label, ""),
        "recent_path_summary": _compact(" ".join(row["history_parts"])),
        "current_judgement": status_label,
        "main_basis": _compact(" ".join(row["basis_parts"])),
        "observation_condition": _compact(" ".join(row["condition_parts"])),
        "source_section": "板块观点详细汇总",
        "source_page": row["source_page"],
        "source_text_start": row["source_start"],
        "source_text_end": row["source_end"],
        "source_text_reference": _compact(" ".join(row["raw_lines"])),
        "source_text_excerpt": _compact(" ".join(row["raw_lines"]))[:900],
        "source_reference": f"第{row['source_page']}页·板块观点详细汇总·{row['sector'].sector_name}表格行",
        "extraction_method": "pdf_layout_table_columns",
        "manually_modified": False,
    }
    if not record["path_status"]:
        record.setdefault("validation_flags", []).append("missing_or_conflicting_current_status")
    quality, confidence, flags = _assessment_quality(record)
    if not record["path_status"]:
        flags.append("conflicting_status")
        quality, confidence = "blocking_parse_error", "low"
    record["quality_status"] = quality
    record["confidence"] = confidence
    record["validation_flags"] = sorted(set(flags))
    return record


def _positioned_groups(items: list[dict[str, Any]]) -> dict[float, list[dict[str, Any]]]:
    groups: dict[float, list[dict[str, Any]]] = {}
    for item in items:
        # LibreOffice can place fragments from one visual row 0.25pt apart
        # (notably "7/26" and "判断"). Group to the nearest point so a
        # single table header/cell is not split into unrelated rows.
        groups.setdefault(round(float(item["y"])), []).append(item)
    for group in groups.values():
        group.sort(key=lambda value: float(value["x"]))
    return groups


def _assessment_column_boundaries(items: list[dict[str, Any]]) -> tuple[float, float, float, float] | None:
    def label_center(group: list[dict[str, Any]], label: str) -> float | None:
        """Locate a header label even when the PDF splits it into glyph runs."""
        ordered = sorted(group, key=lambda item: float(item["x"]))
        fragments = [re.sub(r"\s+", "", item["text"]) for item in ordered]
        joined = "".join(fragments)
        start = joined.find(label)
        if start < 0:
            return None
        end = start + len(label)
        positions: list[float] = []
        cursor = 0
        for item, fragment in zip(ordered, fragments, strict=True):
            fragment_end = cursor + len(fragment)
            if fragment_end > start and cursor < end:
                positions.append(float(item["x"]))
            cursor = fragment_end
        return sum(positions) / len(positions) if positions else None

    for group in _positioned_groups(items).values():
        joined = "".join(re.sub(r"\s+", "", item["text"]) for item in group)
        if not all(label in joined for label in ("板块", "历史路径", "判断", "主要依据", "观察条件")):
            continue
        sector_x = label_center(group, "板块")
        history_x = label_center(group, "历史路径")
        status_x = label_center(group, "判断")
        basis_x = label_center(group, "主要依据")
        condition_x = label_center(group, "观察条件")
        if None not in {sector_x, history_x, status_x, basis_x, condition_x}:
            return (
                (float(sector_x) + float(history_x)) / 2,
                float(status_x) - 20,
                (float(status_x) + float(basis_x)) / 2,
                (float(basis_x) + float(condition_x)) / 2,
            )
    return None


def _positioned_sector_centers(items: list[dict[str, Any]], sector_boundary: float) -> list[tuple[float, Any]]:
    centers: list[tuple[float, Any]] = []
    grouped = _positioned_groups(items)
    ordered_y = sorted(grouped, reverse=True)
    for index, y in enumerate(ordered_y):
        group = grouped[y]
        fragment = "".join(item["text"] for item in group if float(item["x"]) < sector_boundary)
        sector = _sector_from_fragment(fragment)
        if sector is None and fragment.strip():
            continuation = "".join(
                item["text"]
                for lower_y in ordered_y[index + 1:]
                if y - lower_y <= 12
                for item in grouped[lower_y]
                if float(item["x"]) < sector_boundary
            )
            sector = _sector_from_fragment(fragment + continuation)
        if sector is not None:
            centers.append((y, sector))
    return sorted(centers, key=lambda value: value[0], reverse=True)


def _cell_text(items: list[dict[str, Any]], lower_y: float, upper_y: float, lower_x: float, upper_x: float | None) -> str:
    selected = [
        item for item in items
        if lower_y < float(item["y"]) <= upper_y
        and float(item["x"]) >= lower_x
        and (upper_x is None or float(item["x"]) < upper_x)
        and float(item.get("font_size", 8.0)) <= 8.1
    ]
    lines: dict[float, list[dict[str, Any]]] = {}
    for item in selected:
        lines.setdefault(round(float(item["y"]), 1), []).append(item)
    rebuilt: list[str] = []
    for y in sorted(lines, reverse=True):
        lines[y].sort(key=lambda item: float(item["x"]))
        rebuilt.append("".join(item["text"] for item in lines[y]))
    return _compact("".join(rebuilt))


def _parse_positioned_assessments(positioned_pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for page in positioned_pages:
        page_number = int(page["page"])
        if page_number < 6:
            continue
        items = page["items"]
        boundaries = _assessment_column_boundaries(items)
        if boundaries is None:
            continue
        sector_bound, history_bound, status_bound, basis_bound = boundaries
        centers = _positioned_sector_centers(items, sector_bound)
        for index, (center_y, sector) in enumerate(centers):
            if index:
                upper_y = (centers[index - 1][0] + center_y) / 2
            elif index + 1 < len(centers):
                upper_y = center_y + (center_y - centers[index + 1][0]) / 2
            else:
                upper_y = center_y + 25
            if index + 1 < len(centers):
                lower_y = (center_y + centers[index + 1][0]) / 2
            elif index:
                lower_y = center_y - (centers[index - 1][0] - center_y) / 2
            else:
                lower_y = center_y - 25
            history = _cell_text(items, lower_y, upper_y, sector_bound, history_bound)
            status_text = _cell_text(items, lower_y, upper_y, history_bound, status_bound)
            basis = _cell_text(items, lower_y, upper_y, status_bound, basis_bound)
            condition = _cell_text(items, lower_y, upper_y, basis_bound, None)
            status_labels = re.findall("|".join(STATUS_LABELS), status_text)
            status_label = status_labels[0] if len(set(status_labels)) == 1 else ""
            # A sector name outside a five-column table (notably the B3
            # not-updated paragraph) is not a detailed assessment row. The
            # explicit judgement cell is the row's authority and is required.
            if not status_label:
                continue
            row_items = [item for item in items if lower_y < float(item["y"]) <= upper_y]
            row_items.sort(key=lambda item: (-float(item["y"]), float(item["x"])))
            excerpt = _compact(" ".join(item["text"] for item in row_items))
            record: dict[str, Any] = {
                "sector_key": sector.sector_key,
                "sector_name": sector.sector_name,
                "path_status": STATUS_TO_CODE.get(status_label, ""),
                "recent_path_summary": history,
                "current_judgement": status_label,
                "main_basis": basis,
                "observation_condition": condition,
                "source_section": "板块观点详细汇总",
                "source_page": page_number,
                "source_text_start": int(lower_y * 1000),
                "source_text_end": int(upper_y * 1000),
                "source_text_reference": excerpt,
                "source_text_excerpt": excerpt[:900],
                "source_reference": f"第{page_number}页·板块观点详细汇总·{sector.sector_name}表格行·Y{lower_y:.1f}-{upper_y:.1f}",
                "extraction_method": "pdf_positioned_table_cells",
                "manually_modified": False,
            }
            quality, confidence, flags = _assessment_quality(record)
            record["quality_status"] = quality
            record["confidence"] = confidence
            record["validation_flags"] = sorted(set(flags))
            records.append(record)
    unique = {record["sector_key"]: record for record in records}
    return sorted(unique.values(), key=lambda record: next(item.overall_order for item in load_seed_bundle().sectors if item.sector_key == record["sector_key"]))


def _parse_layout_assessments(layout_text: str) -> list[dict[str, Any]]:
    if "板块观点" not in _normalized_sector_token(layout_text) or "详细汇总" not in _normalized_sector_token(layout_text):
        return []
    records: list[dict[str, Any]] = []
    active = False
    current_page: int | None = None
    header: tuple[int, int, int, int] | None = None
    current: dict[str, Any] | None = None
    offset = 0

    def flush() -> None:
        nonlocal current
        if current is not None:
            record = _finalize_layout_assessment(current)
            if record is not None:
                records.append(record)
        current = None

    for raw_line in layout_text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        marker = re.match(r"\[\[LEOPARD_PAGE:(\d+)\]\]", line)
        if marker:
            flush()
            current_page = int(marker.group(1))
            header = None
            offset += len(raw_line)
            continue
        compact_line = _normalized_sector_token(line)
        if "板块观点详细汇总" in compact_line:
            active = True
            offset += len(raw_line)
            continue
        if active and (compact_line.startswith("八、") or compact_line.startswith("8、") or compact_line.startswith("本场未更新")):
            flush()
            break
        if not active:
            offset += len(raw_line)
            continue
        if re.match(r"^B\d+[.．]", line.strip()):
            flush()
            header = None
            offset += len(raw_line)
            continue
        if all(label in compact_line for label in ("板块", "历史路径", "判断", "主要依据", "观察条件")):
            flush()
            history_start = _spaced_label_start(line, "历史路径")
            status_match = re.search(r"\d{1,2}\s*/\s*\d{1,2}\s*判\s*断", line)
            basis_start = _spaced_label_start(line, "主要依据")
            condition_start = _spaced_label_start(line, "观察条件")
            if history_start >= 0 and status_match and basis_start > status_match.start() and condition_start > basis_start:
                header = (history_start, status_match.start(), basis_start, condition_start)
            offset += len(raw_line)
            continue
        if header is None or current_page is None or not line.strip():
            offset += len(raw_line)
            continue
        history_start, status_start, basis_start, condition_start = header
        sector_fragment = line[:history_start].strip()
        sector = _sector_from_fragment(sector_fragment)
        if sector is not None:
            flush()
            current = {
                "sector": sector,
                "source_page": current_page,
                "source_start": offset,
                "source_end": offset + len(raw_line),
                "history_parts": [], "status_parts": [], "basis_parts": [], "condition_parts": [], "raw_lines": [],
            }
        if current is not None:
            current["source_end"] = offset + len(raw_line)
            current["history_parts"].append(line[history_start:status_start].strip())
            current["status_parts"].append(line[status_start:basis_start].strip())
            current["basis_parts"].append(line[basis_start:condition_start].strip())
            current["condition_parts"].append(line[condition_start:].strip())
            current["raw_lines"].append(line.strip())
        offset += len(raw_line)
    flush()
    unique: dict[str, dict[str, Any]] = {}
    for record in records:
        previous = unique.get(record["sector_key"])
        if previous is not None:
            previous["validation_flags"] = sorted(set(previous["validation_flags"] + ["duplicate_sector_row"]))
            previous["quality_status"] = "blocking_parse_error"
            previous["confidence"] = "low"
            continue
        unique[record["sector_key"]] = record
    ordered = sorted(unique.values(), key=lambda item: next(s.overall_order for s in load_seed_bundle().sectors if s.sector_key == item["sector_key"]))
    for left, right in zip(ordered, ordered[1:]):
        for field in ("main_basis", "observation_condition"):
            a, b = left[field], right[field]
            if min(len(a), len(b)) >= 60 and SequenceMatcher(None, a, b).ratio() >= 0.94:
                for record in (left, right):
                    record["validation_flags"] = sorted(set(record["validation_flags"] + [f"adjacent_{field}_highly_repeated"]))
                    record["quality_status"] = "needs_attention"
                    record["confidence"] = "medium"
    return ordered


def _parse_positioned_history_matrix(positioned_pages: list[dict[str, Any]]) -> dict[str, Any]:
    dates: list[str] = []
    rows: dict[str, dict[str, Any]] = {}
    bundle = load_seed_bundle()
    for page in positioned_pages:
        page_number = int(page["page"])
        if page_number not in {3, 4, 5}:
            continue
        items = page["items"]
        header_dates: list[tuple[float, str]] = []
        sector_x: float | None = None
        for group in _positioned_groups(items).values():
            group_dates = [
                (float(item["x"]), re.sub(r"\s+", "", item["text"]))
                for item in group
                if re.fullmatch(r"\d{1,2}\s*/\s*\d{2}", item["text"])
            ]
            if len(group_dates) >= 20:
                header_dates = sorted(group_dates)
                sector_item = next((item for item in group if item["text"] == "板块"), None)
                sector_x = float(sector_item["x"]) if sector_item else 35.0
                break
        if not header_dates or sector_x is None:
            continue
        page_dates = [value for _, value in header_dates]
        if len(page_dates) > len(dates):
            dates = page_dates
        first_date_x = header_dates[0][0]
        sector_boundary = (sector_x + first_date_x) / 2
        centers = _positioned_sector_centers(items, sector_boundary)
        for index, (center_y, sector) in enumerate(centers):
            if index:
                upper_y = (centers[index - 1][0] + center_y) / 2
            elif index + 1 < len(centers):
                upper_y = center_y + (center_y - centers[index + 1][0]) / 2
            else:
                upper_y = center_y + 12
            if index + 1 < len(centers):
                lower_y = (center_y + centers[index + 1][0]) / 2
            elif index:
                lower_y = center_y - (centers[index - 1][0] - center_y) / 2
            else:
                lower_y = center_y - 12
            status_items = [
                item for item in items
                if lower_y < float(item["y"]) <= upper_y
                and float(item["x"]) >= sector_boundary
                and item["text"] in STATUS_TO_CODE
            ]
            status_items.sort(key=lambda item: float(item["x"]))
            if len(status_items) != len(page_dates):
                continue
            rows[sector.sector_key] = {
                "sector_key": sector.sector_key,
                "sector_name": sector.sector_name,
                "group_name": sector.category_level_1,
                "source_page": page_number,
                "statuses": [STATUS_TO_CODE[item["text"]] for item in status_items],
            }
    ordered = [rows[item.sector_key] for item in sorted(bundle.sectors, key=lambda item: item.overall_order) if item.sector_key in rows]
    return {
        "dates": dates,
        "rows": ordered,
        "row_count": len(ordered),
        "quality_status": "verified_structure" if len(ordered) == 66 and len(dates) >= 20 else "needs_attention",
    }


def parse_pdf_history_matrix(layout_text: str, positioned_pages: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    positioned: dict[str, Any] = {"rows": []}
    if positioned_pages:
        positioned = _parse_positioned_history_matrix(positioned_pages)
    if "板块历史路径图" not in _normalized_sector_token(layout_text):
        return positioned if positioned.get("rows") else {"dates": [], "rows": [], "quality_status": "needs_attention"}
    active = False
    current_page: int | None = None
    dates: list[str] = []
    rows: dict[str, dict[str, Any]] = {}
    bundle = load_seed_bundle()
    sector_by_key = {item.sector_key: item for item in bundle.sectors}
    status_pattern = re.compile("|".join(STATUS_LABELS))
    for line in layout_text.splitlines():
        marker = re.match(r"\[\[LEOPARD_PAGE:(\d+)\]\]", line)
        if marker:
            current_page = int(marker.group(1))
            continue
        compact_line = _normalized_sector_token(line)
        if "板块历史路径图" in compact_line:
            active = True
            continue
        if active and "板块观点详细汇总" in compact_line:
            break
        if not active:
            continue
        found_dates = re.findall(r"\d{1,2}\s*/\s*\d{2}", line)
        if len(found_dates) >= 20 and len(found_dates) > len(dates):
            dates = [re.sub(r"\s+", "", value) for value in found_dates]
        statuses = status_pattern.findall(line)
        if not dates or len(statuses) < len(dates):
            continue
        first_status = status_pattern.search(line)
        if first_status is None:
            continue
        sector = _sector_from_fragment(line[:first_status.start()].strip())
        if sector is None:
            continue
        selected = statuses[-len(dates):]
        rows[sector.sector_key] = {
            "sector_key": sector.sector_key,
            "sector_name": sector.sector_name,
            "group_name": sector.category_level_1,
            "source_page": current_page,
            "statuses": [STATUS_TO_CODE[value] for value in selected],
        }
    ordered = [rows[item.sector_key] for item in sorted(bundle.sectors, key=lambda item: item.overall_order) if item.sector_key in rows]
    layout = {
        "dates": dates,
        "rows": ordered,
        "row_count": len(ordered),
        "quality_status": "verified_structure" if len(ordered) == 66 and len(dates) >= 20 else "needs_attention",
    }
    # A partial coordinate extraction must not shadow a complete layout-table
    # extraction. This occurs when matrix labels share nearly identical
    # baselines or a sector name is split into glyph fragments.
    return layout if len(layout["rows"]) >= len(positioned.get("rows", [])) else positioned


def compare_frozen_history(
    frozen: dict[str, Any],
    incoming: dict[str, Any],
    *,
    through: str | None = None,
) -> dict[str, Any]:
    """Compare immutable historical cells without treating the appended date as frozen."""
    frozen_dates = list(frozen.get("dates") or [])
    incoming_dates = list(incoming.get("dates") or [])
    if not frozen_dates:
        return {"status": "no_frozen_history", "differences": []}
    if through:
        month, day = (int(value) for value in through[-5:].split("-"))
        frozen_indexes = [
            index for index, value in enumerate(frozen_dates)
            if tuple(map(int, value.split("/"))) <= (month, day)
        ]
    else:
        frozen_indexes = list(range(max(0, len(frozen_dates) - 1)))
    incoming_index = {value: index for index, value in enumerate(incoming_dates)}
    frozen_rows = {item.get("sector_key"): item for item in frozen.get("rows") or []}
    incoming_rows = {item.get("sector_key"): item for item in incoming.get("rows") or []}
    differences: list[dict[str, Any]] = []
    for sector_key, frozen_row in frozen_rows.items():
        incoming_row = incoming_rows.get(sector_key)
        if incoming_row is None:
            differences.append({"sector_key": sector_key, "reason": "sector_missing"})
            continue
        frozen_statuses = frozen_row.get("statuses") or []
        incoming_statuses = incoming_row.get("statuses") or []
        for frozen_index in frozen_indexes:
            raw_date = frozen_dates[frozen_index]
            if raw_date not in incoming_index:
                differences.append({"sector_key": sector_key, "date": raw_date, "reason": "date_missing"})
                continue
            before = frozen_statuses[frozen_index]
            after = incoming_statuses[incoming_index[raw_date]]
            if before != after:
                differences.append({
                    "sector_key": sector_key,
                    "date": raw_date,
                    "before": before,
                    "after": after,
                    "reason": "status_changed",
                })
    return {
        "status": "matched_append_only" if not differences else "frozen_history_changed",
        "differences": differences,
        "checked_dates": [frozen_dates[index] for index in frozen_indexes],
        "appended_dates": [value for value in incoming_dates if value not in frozen_dates],
    }


def parse_v23_assessments(
    text: str,
    layout_text: str = "",
    positioned_pages: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    positioned_records = _parse_positioned_assessments(positioned_pages or [])
    if positioned_records:
        return _validate_assessment_set(positioned_records)
    layout_records = _parse_layout_assessments(layout_text) if layout_text else []
    if layout_records:
        return _validate_assessment_set(layout_records)
    heading = re.search(r"板块观点详细汇总", text)
    if not heading:
        return []
    block = text[heading.end():]
    bundle = load_seed_bundle()
    sector_by_name = {item.sector_name: item for item in bundle.sectors}
    raw_lines = block.splitlines(keepends=True)
    lines = [_compact(line) for line in raw_lines]
    line_offsets: list[int] = []
    running_offset = heading.end()
    for raw_line in raw_lines:
        line_offsets.append(running_offset)
        running_offset += len(raw_line)
    rows: list[tuple[int, str]] = [
        (index, line) for index, line in enumerate(lines) if line in sector_by_name
    ]
    output: list[dict[str, str]] = []
    for row_index, (start, sector_name) in enumerate(rows):
        end = rows[row_index + 1][0] if row_index + 1 < len(rows) else len(lines)
        segment = [
            line for line in lines[start + 1:end]
            if line
            and not re.fullmatch(r"第\s*\d+\s*页", line)
            and not line.startswith("板块 历史路径")
            and not re.match(r"B\d+[.．]", line)
        ]
        status_index = -1
        status_label = ""
        inline_after_status = ""
        for index, line in enumerate(segment):
            match = re.match(rf"^({'|'.join(STATUS_LABELS)})(?:\s+(.+))?$", line)
            if match and (index > 0 or "→" in " ".join(segment[:index + 1])):
                status_index = index
                status_label = match.group(1)
                inline_after_status = match.group(2) or ""
                break
        if status_index < 0:
            continue
        history = _compact(" ".join(segment[:status_index]))
        remainder = _compact(" ".join(([inline_after_status] if inline_after_status else []) + segment[status_index + 1:]))
        basis, condition = _split_basis_condition(remainder)
        sector = sector_by_name[sector_name]
        source_start = line_offsets[start] if start < len(line_offsets) else None
        source_end = line_offsets[end] if end < len(line_offsets) else len(text)
        record: dict[str, Any] = {
            "sector_key": sector.sector_key,
            "sector_name": sector.sector_name,
            "path_status": STATUS_TO_CODE[status_label],
            "recent_path_summary": history or "本报告未单列最近转折。",
            "current_judgement": status_label,
            "main_basis": basis or "本报告未单列主要依据。",
            "observation_condition": condition,
            "source_text_reference": _compact(" ".join([sector_name, *segment])),
            "source_section": "板块观点详细汇总",
            "source_page": _source_page(text, heading.end()),
            "source_text_start": source_start,
            "source_text_end": source_end,
            "source_text_excerpt": _compact(" ".join([sector_name, *segment]))[:900],
            "source_reference": f"第{_source_page(text, source_start or heading.end())}页·板块观点详细汇总·{sector.sector_name}文本行",
            "extraction_method": "pdf_text_bounded_table_row",
            "manually_modified": False,
        }
        quality, confidence, flags = _assessment_quality(record)
        record["quality_status"] = quality
        record["confidence"] = confidence
        record["validation_flags"] = sorted(set(flags))
        output.append(record)
    return _validate_assessment_set(output)


def parse_report_text(
    text: str,
    report_id: str,
    filename: str = "",
    layout_text: str = "",
    positioned_pages: list[dict[str, Any]] | None = None,
) -> tuple[dict, list[ReportSection], list[SectorMention], list[UnmappedTerm]]:
    title, title_span = _report_title(text)
    date_result = detect_report_date(text, filename)
    main_fields, provenance = _main_fields(text)
    provenance["title"] = {
        "extracted_value": title,
        "extraction_method": "pdf_text_layer",
        "source_page": _source_page(text, title_span[0]) if title_span else None,
        "source_text_range": list(title_span) if title_span else None,
        "source_reference": f"第{_source_page(text, title_span[0])}页·报告标题" if title_span else "无法定位",
        "source_text_excerpt": text[title_span[0]:title_span[1]].strip()[:500] if title_span else title,
        "confidence": "high" if title != "待复核报告" else "low",
        "validation_flags": [] if title_span else ["missing_source_range"],
        "manually_modified": False,
    }
    provenance["report_date"] = {
        "extracted_value": date_result["value"].isoformat() if date_result["value"] else None,
        "extraction_method": date_result["source"],
        "source_page": 1 if date_result["source"].startswith("pdf_") else None,
        "source_text_range": None,
        "source_reference": "PDF标题或正文日期" if date_result["source"].startswith("pdf_") else date_result["source"],
        "source_text_excerpt": date_result["value"].isoformat() if date_result["value"] else "",
        "confidence": date_result["confidence"],
        "validation_flags": ["date_conflict"] if date_result["conflict"] else [],
        "manually_modified": False,
    }
    assessments = parse_v23_assessments(text, layout_text, positioned_pages)
    history_matrix = parse_pdf_history_matrix(layout_text, positioned_pages) if layout_text else {"dates": [], "rows": [], "quality_status": "needs_attention"}
    history_latest = {
        item["sector_key"]: item["statuses"][-1]
        for item in history_matrix.get("rows", [])
        if item.get("statuses")
    }
    for assessment in assessments:
        matrix_status = history_latest.get(assessment["sector_key"])
        if matrix_status and assessment.get("path_status") and matrix_status != assessment["path_status"]:
            assessment["validation_flags"] = sorted(set(assessment.get("validation_flags", []) + ["current_matrix_status_mismatch"]))
            assessment["quality_status"] = "needs_attention"
            assessment["confidence"] = "medium"
    bundle = load_seed_bundle()
    sector_by_key = {item.sector_key: item for item in bundle.sectors}
    assessment_by_key = {item["sector_key"]: item for item in assessments}
    focus_region_match = re.search(r"(?ms)^\s*板块主线\s*(.+?)(?=^\s*核心定性[：:]|\Z)", text)
    explicit_focus, _ = _explicit_field(text, ("重点板块",))
    focus_region = focus_region_match.group(1) if focus_region_match else explicit_focus
    focus_keys = {
        sector.sector_key for sector in bundle.sectors
        if sector.sector_name in focus_region
    }
    for alias in bundle.aliases:
        if alias.confirmed and alias.alias in focus_region:
            focus_keys.add(alias.sector_key)
    mention_keys = set(assessment_by_key) | focus_keys
    mentions: list[SectorMention] = []
    for sector_key in sorted(mention_keys, key=lambda key: sector_by_key[key].overall_order):
        sector = sector_by_key[sector_key]
        assessment = assessment_by_key.get(sector_key)
        simple_summary, _ = _explicit_field(text, (sector.sector_name,))
        summary = assessment["current_judgement"] if assessment else simple_summary or _compact(focus_region)[:500]
        source_text = assessment["source_text_reference"] if assessment else simple_summary or focus_region
        mentions.append(SectorMention(
            report_id=report_id,
            sector_key=sector.sector_key,
            sector_name=sector.sector_name,
            summary=summary,
            source_text=source_text,
            extraction_status=assessment.get("quality_status", "confirmed") if assessment else "confirmed",
        ))
    terms: list[UnmappedTerm] = []
    for raw in re.findall(r"(?m)^未映射[：:]\s*(.+)$", text):
        for term in [item.strip() for item in re.split(r"[,，、]", raw) if item.strip()]:
            if normalize_alias(term, bundle) is None:
                terms.append(UnmappedTerm(report_id=report_id, term=term, source_text=raw))
    probable_terms: list[UnmappedTerm] = []
    known_names = [item.sector_name for item in bundle.sectors]
    for raw in re.findall(r"(?m)^可能板块[：:]\s*(.+)$", text):
        for term in [item.strip() for item in re.split(r"[,，、]", raw) if item.strip()]:
            if normalize_alias(term, bundle) is not None:
                continue
            candidate = next(iter(get_close_matches(term, known_names, n=1, cutoff=0.45)), "")
            probable_terms.append(UnmappedTerm(
                report_id=report_id,
                term=term,
                source_text=f"{raw}；候选：{candidate or '无'}",
                status="probable",
            ))
    terms.extend(probable_terms)
    attention: list[dict[str, Any]] = []
    compact_document = re.sub(r"\s+", "", text)
    v24_signature = (
        "本场未更新" in text
        and len(history_matrix.get("dates", [])) >= 35
        and "只新增7/27" in compact_document
    )
    template_version = (
        "V2.4" if re.search(r"V\s*2[.]4", text, re.I) or v24_signature
        else "V2.3.1" if re.search(r"V\s*2[.]3[.]1", text, re.I)
        else "V2.3" if re.search(r"V\s*2[.]3", text, re.I)
        else "unknown"
    )
    if template_version == "unknown" and "板块观点详细汇总" in text:
        attention.append({"kind": "unknown_template", "severity": "warning", "message": "未识别规范版本文字；已按结构兼容模式解析"})
    if date_result["confidence"] == "low":
        attention.append({"kind": "report_date", "severity": "blocking", "message": "需要确认报告日期"})
    for key, label in (("core_view", "核心观点"), ("market_path", "大盘路径")):
        if not main_fields[key]:
            attention.append({"kind": key, "severity": "warning", "message": f"{label}未可靠识别"})
    attention.extend(
        {"kind": "unmapped", "severity": "blocking", "message": f"无法映射板块：{term.term}", "term": term.term}
        for term in terms if term.status == "unresolved"
    )
    attention.extend(
        {"kind": "probable", "severity": "warning", "message": f"高概率板块映射需要检查：{term.term}", "term": term.term}
        for term in terms if term.status == "probable"
    )
    if "板块观点详细汇总" in text and not assessments:
        attention.append({
            "kind": "detailed_assessment_table",
            "severity": "blocking",
            "message": "板块观点详细汇总无法可靠恢复，已阻止发布",
            "validation_flags": ["no_reliable_assessment_rows"],
        })
    for assessment in assessments:
        if assessment.get("quality_status") == "verified_structure":
            continue
        attention.append({
            "kind": "assessment_parse_quality",
            "severity": "blocking" if assessment.get("quality_status") == "blocking_parse_error" else "warning",
            "message": f"{assessment['sector_name']}表格行存在解析异常，需要核对原PDF",
            "sector_key": assessment["sector_key"],
            "source_page": assessment.get("source_page"),
            "validation_flags": assessment.get("validation_flags", []),
        })
    history_section_present = "板块历史路径图" in text
    if history_section_present and history_matrix.get("quality_status") != "verified_structure":
        recovered_rows = history_matrix.get("row_count", 0)
        attention.append({
            "kind": "history_matrix_quality",
            "severity": "warning" if recovered_rows >= 65 else "blocking",
            "message": f"历史路径矩阵仅可靠恢复{recovered_rows}/66个板块",
            "validation_flags": ["history_matrix_incomplete"],
        })
    parse_quality_status = (
        "blocking_parse_error"
        if any(item.get("severity") == "blocking" and item.get("kind") in {"detailed_assessment_table", "assessment_parse_quality", "history_matrix_quality"} for item in attention)
        else "needs_attention"
        if any(item.get("kind") == "assessment_parse_quality" for item in attention)
        else "verified_structure"
    )
    freeze_match = re.search(r"历史(?:观点)?冻结至\s*(\d{1,2})\s*/\s*(\d{1,2})", compact_document)
    append_match = re.search(r"只新增\s*(\d{1,2})\s*/\s*(\d{1,2})", compact_document)
    report_year = date_result["value"].year if date_result["value"] else None
    freeze_through = (
        date(report_year, int(freeze_match.group(1)), int(freeze_match.group(2))).isoformat()
        if freeze_match and report_year else None
    )
    appended_date = (
        date(report_year, int(append_match.group(1)), int(append_match.group(2))).isoformat()
        if append_match and report_year else None
    )
    fields = {
        "title": title,
        "candidate_report_date": date_result["value"],
        "detected_report_date": date_result["value"],
        "report_date_source": date_result["source"],
        "report_date_confidence": date_result["confidence"],
        **main_fields,
        "focus_sectors": [sector_by_key[key].sector_name for key in sorted(focus_keys, key=lambda key: sector_by_key[key].overall_order)],
        "interpretation_meta": {
            "template_version": template_version,
            "history_freeze": {
                "through": freeze_through,
                "appended_report_date": appended_date or (date_result["value"].isoformat() if date_result["value"] else None),
                "mode": "freeze_and_append" if append_match else "full_snapshot",
            },
            "field_provenance": provenance,
            "attention_items": attention,
            "assessment_records": assessments,
            "pdf_history_matrix": history_matrix,
            "quality_status": parse_quality_status,
            "quality_summary": {
                "report_structure": parse_quality_status,
                "history_matrix": history_matrix.get("quality_status", "needs_attention") if history_section_present else "not_present",
                "history_matrix_rows": history_matrix.get("row_count", 0),
                "assessment_rows": len(assessments),
                "assessment_verified": sum(item.get("quality_status") == "verified_structure" for item in assessments),
                "assessment_needs_attention": sum(item.get("quality_status") == "needs_attention" for item in assessments),
                "assessment_blocking": sum(item.get("quality_status") == "blocking_parse_error" for item in assessments),
            },
            "mapping_summary": {
                "confirmed": len(mentions),
                "probable": len(probable_terms),
                "unmapped": sum(term.status == "unresolved" for term in terms),
                "conflict": 0,
            },
            "external_llm_calls": 0,
            "ocr_used": False,
        },
    }
    sections = [
        ReportSection(
            report_id=report_id,
            section_type=key,
            heading=label,
            raw_text=fields[key] or "无法确认",
            extraction_status="explicit" if fields[key] else "unconfirmed",
        )
        for key, label in (("core_view", "核心观点"), ("market_path", "大盘路径"), ("risk_warning", "风险提示"))
    ]
    return fields, sections, mentions, terms


class ReportService:
    def __init__(self, repository: ReportRepository, upload_dir: Path, policy: UploadPolicy | None = None) -> None:
        self.repo = repository
        self.upload_dir = upload_dir
        self.policy = policy or UploadPolicy.load()

    def upload(self, filename: str, content_type: str, payload: bytes, actor: str) -> tuple[Report, bool]:
        validate_pdf(filename, content_type, payload, self.policy)
        digest = hashlib.sha256(payload).hexdigest()
        existing = self.repo.by_sha256(digest)
        if existing:
            return existing, True
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        storage_name = f"{uuid4().hex}.pdf"
        (self.upload_dir / storage_name).write_bytes(payload)
        report = Report(created_by=actor, interpretation_status="uploading")
        report_file = ReportFile(
            sha256=digest,
            original_filename=filename,
            storage_filename=storage_name,
            content_type=content_type,
            size_bytes=len(payload),
        )
        created = self.repo.create(report, report_file)
        self.repo.audit(actor, "report_uploaded", "report", created.id, {"sha256": digest, "duplicate": False})
        self.repo.commit()
        return created, False

    def transition(self, report: Report, target: ReportStatus) -> None:
        current = ReportStatus(report.status)
        if target not in ALLOWED_TRANSITIONS[current]:
            raise WebDomainError("invalid_report_transition", f"Cannot transition {current.value} to {target.value}", 409)
        report.status = target.value
        report.updated_at = datetime.now(timezone.utc)

    def parse(self, report: Report, actor: str) -> Report:
        report_id = report.id
        if report.status != ReportStatus.PARSING.value:
            self.transition(report, ReportStatus.PARSING)
        report.interpretation_status = "interpreting"
        self.repo.commit()
        try:
            payload = (self.upload_dir / report.file.storage_filename).read_bytes()
            text = extract_text_layer(payload)
            layout_text = extract_layout_text(payload)
            positioned_pages = extract_positioned_pages(payload)
            if not text:
                raise WebDomainError("pdf_text_unavailable", "No reliable PDF text layer was extracted", 422)
            fields, sections, mentions, terms = parse_report_text(
                text,
                report.id,
                report.file.original_filename,
                layout_text=layout_text,
                positioned_pages=positioned_pages,
            )
            report.raw_text = text
            report.title = fields["title"]
            report.candidate_report_date = fields["candidate_report_date"]
            report.detected_report_date = fields["detected_report_date"]
            report.report_date_source = fields["report_date_source"]
            report.report_date_confidence = fields["report_date_confidence"]
            if fields["candidate_report_date"] and fields["report_date_confidence"] in {"high", "medium"}:
                report.report_date = fields["candidate_report_date"]
            metadata = fields["interpretation_meta"]
            report.template_version = metadata.get("template_version", "unknown")
            if report.report_date:
                prior_versions = self.repo.reports_on(report.report_date, exclude_id=report.id)
                report.revision_number = max((item.revision_number for item in prior_versions), default=0) + 1
                if prior_versions:
                    report.replaces_report_id = prior_versions[0].id
            report.candidate_market_as_of_date = self._market_date_candidate(report.report_date)
            report.core_view = fields["core_view"]
            report.market_path = fields["market_path"]
            report.risk_warning = fields["risk_warning"]
            report.focus_sectors_json = json.dumps(fields["focus_sectors"], ensure_ascii=False)
            freeze = metadata.setdefault("history_freeze", {})
            prior_report = next((
                item for item in self.repo.list_reports(published_only=True)
                if item.id != report.id and item.report_date and report.report_date and item.report_date <= report.report_date
            ), None)
            if prior_report is None:
                freeze.update({
                    "initialized_from_latest_full_pdf": True,
                    "initialization_report_id": report.id,
                    "initialization_file_sha256": report.file.sha256 if report.file else None,
                })
            else:
                prior_metadata = json.loads(prior_report.interpretation_meta_json or "{}")
                validation = compare_frozen_history(
                    prior_metadata.get("pdf_history_matrix") or {},
                    metadata.get("pdf_history_matrix") or {},
                    through=freeze.get("through"),
                )
                freeze["validation"] = validation
                freeze["frozen_source_report_id"] = prior_report.id
                if validation["status"] == "frozen_history_changed":
                    metadata.setdefault("attention_items", []).append({
                        "kind": "history_rewrite",
                        "severity": "blocking",
                        "message": "新PDF改写了已冻结的历史路径，禁止静默覆盖",
                        "differences": validation["differences"],
                    })
                    metadata["quality_status"] = "blocking_parse_error"
            report.interpretation_meta_json = json.dumps(metadata, ensure_ascii=False)
            attention = fields["interpretation_meta"]["attention_items"]
            report.interpretation_status = "needs_attention" if attention else "ready"
            report.parse_note = "PDF文本层已自动解读；仅异常项需要人工确认。"
            self.transition(report, ReportStatus.NEEDS_REVIEW)
            self.repo.replace_parse_results(report, sections, mentions, terms)
            self.repo.audit(actor, "report_interpreted", "report", report.id, {
                "external_ai": False,
                "ocr": False,
                "attention_count": len(attention),
                "report_date_confidence": report.report_date_confidence,
            })
            self.repo.commit()
            return self.repo.by_id(report.id)  # type: ignore[return-value]
        except Exception as exc:
            self.repo.session.rollback()
            report = self.repo.by_id(report_id) or report
            report.status = ReportStatus.PARSE_FAILED.value
            report.interpretation_status = "failed"
            report.parse_note = "Local parsing failed; the original file was retained."
            self.repo.audit(actor, "report_parse_failed", "report", report.id, {"error_type": type(exc).__name__})
            self.repo.commit()
            if isinstance(exc, WebDomainError):
                raise
            raise WebDomainError("pdf_parse_failed", "The PDF could not be parsed locally", 422) from exc

    def patch(self, report: Report, changes: dict, actor: str) -> Report:
        if report.status == ReportStatus.PUBLISHED.value:
            self.repo.revision(report, actor)
        for field in (
            "title", "report_date", "report_date_confirmed", "market_as_of_date",
            "market_as_of_date_confirmed", "core_view", "market_path", "risk_warning",
        ):
            if field in changes and changes[field] is not None:
                setattr(report, field, changes[field])
        if changes.get("focus_sectors") is not None:
            report.focus_sectors_json = json.dumps(changes["focus_sectors"], ensure_ascii=False)
        if changes.get("report_date_confirmed"):
            report.report_date_confirmed_by_user = True
            report.report_date_confidence = "high"
        self._refresh_attention(report)
        report.updated_at = datetime.now(timezone.utc)
        self.repo.audit(actor, "report_updated", "report", report.id, {"fields": sorted(changes)})
        self.repo.commit()
        return self.repo.by_id(report.id)  # type: ignore[return-value]

    def ready(self, report: Report, actor: str) -> Report:
        if not report.report_date or (
            not report.report_date_confirmed
            and not report.report_date_confirmed_by_user
            and report.report_date_confidence != "high"
        ):
            raise WebDomainError("report_date_confirmation_required", "Administrator confirmation of report date is required", 409)
        if any(term.status == "unresolved" for term in report.unmapped_terms):
            raise WebDomainError("unmapped_terms_unresolved", "Resolve unmapped terms before publishing", 409)
        metadata = json.loads(report.interpretation_meta_json or "{}")
        if metadata.get("quality_status") == "blocking_parse_error" or any(
            item.get("severity") == "blocking"
            for item in metadata.get("attention_items", [])
        ):
            raise WebDomainError("blocking_parse_error", "存在阻塞级解析异常，必须先核对并修正", 409)
        self.transition(report, ReportStatus.READY_TO_PUBLISH)
        self.repo.audit(actor, "report_ready", "report", report.id)
        self.repo.commit()
        return report

    def publish(self, report: Report, actor: str, *, confirm_warnings: bool = False, warning_note: str = "") -> Report:
        if report.status == ReportStatus.PUBLISHED.value:
            return report
        warnings = self._validate_publishable(report)
        if warnings and not confirm_warnings:
            raise WebDomainError("publish_warning_confirmation_required", "存在普通提醒，请确认已查看后再发布", 409)
        if report.status == ReportStatus.NEEDS_REVIEW.value:
            self.transition(report, ReportStatus.READY_TO_PUBLISH)
            self.repo.audit(actor, "report_ready", "report", report.id, {"automatic_from_interpretation": True})
        self.transition(report, ReportStatus.PUBLISHED)
        if report.report_date:
            for prior in self.repo.reports_on(report.report_date, exclude_id=report.id):
                prior.is_current = False
        report.is_current = True
        report.published_at = datetime.now(timezone.utc)
        report.published_by = actor
        self.repo.publish_event(report, "published", actor)
        self.repo.audit(actor, "report_published", "report", report.id, {
            "warnings_confirmed": bool(warnings), "warning_note": warning_note, "warnings": warnings,
        })
        self.repo.commit()
        return report

    def _market_date_candidate(self, report_date: date | None) -> date | None:
        if report_date is None:
            return None
        calendar_path = CONFIG_DIR / "enhanced_demo_calendar_v1.json"
        if not calendar_path.exists():
            return None
        calendar = json.loads(calendar_path.read_text(encoding="utf-8"))
        covered = {date.fromisoformat(value) for value in calendar["trading_dates"] + calendar["non_trading_dates"]}
        if report_date not in covered:
            return None
        trading = sorted(date.fromisoformat(value) for value in calendar["trading_dates"])
        eligible = [value for value in trading if value <= report_date]
        return eligible[-1] if eligible else None

    def _refresh_attention(self, report: Report) -> None:
        metadata = json.loads(report.interpretation_meta_json or "{}")
        attention = list(metadata.get("attention_items", []))
        if report.report_date_confirmed_by_user:
            attention = [item for item in attention if item.get("kind") != "report_date"]
        metadata["attention_items"] = attention
        report.interpretation_meta_json = json.dumps(metadata, ensure_ascii=False)
        report.interpretation_status = "needs_attention" if attention else "ready"

    def _validate_publishable(self, report: Report) -> list[dict[str, Any]]:
        if not report.file or not (self.upload_dir / report.file.storage_filename).exists():
            raise WebDomainError("source_pdf_unavailable", "原始PDF不可访问", 409)
        if not report.report_date or (
            report.report_date_confidence != "high"
            and not report.report_date_confirmed_by_user
            and not report.report_date_confirmed
        ):
            raise WebDomainError("report_date_confirmation_required", "低置信度报告日期需要人工确认", 409)
        if not report.title.strip() or report.title == "待复核报告":
            raise WebDomainError("report_title_required", "报告标题不能为空", 409)
        if not report.core_view.strip() and not report.market_path.strip():
            raise WebDomainError("report_content_required", "核心观点或主要正文至少需要一项", 409)
        unresolved = [term for term in report.unmapped_terms if term.status == "unresolved"]
        if len(unresolved) > 5:
            raise WebDomainError("unmapped_terms_unresolved", "存在大量未映射板块，可能不是目标直播报告", 409)
        metadata = json.loads(report.interpretation_meta_json or "{}")
        if metadata.get("quality_status") == "blocking_parse_error" or any(
            item.get("severity") == "blocking"
            for item in metadata.get("attention_items", [])
        ):
            raise WebDomainError("blocking_parse_error", "存在阻塞级解析异常，必须先核对并修正", 409)
        if report.status not in {ReportStatus.NEEDS_REVIEW.value, ReportStatus.READY_TO_PUBLISH.value}:
            raise WebDomainError("interpretation_not_ready", "报告尚未完成解读", 409)
        warnings = [item for item in metadata.get("attention_items", []) if item.get("severity") != "blocking"]
        if unresolved:
            warnings.append({"kind": "unmapped_alias", "severity": "needs_attention", "terms": [item.term for item in unresolved]})
        return warnings

    def withdraw(self, report: Report, actor: str, reason: str) -> Report:
        self.transition(report, ReportStatus.WITHDRAWN)
        report.withdrawn_at = datetime.now(timezone.utc)
        report.withdrawal_reason = reason
        self.repo.publish_event(report, "withdrawn", actor, reason)
        self.repo.audit(actor, "report_withdrawn", "report", report.id, {"reason": reason})
        self.repo.commit()
        return report

    def resolve_term(self, term: UnmappedTerm, sector_key: str, actor: str) -> UnmappedTerm:
        bundle = load_seed_bundle()
        sector = next((item for item in bundle.sectors if item.sector_key == sector_key), None)
        if sector is None:
            raise WebDomainError("unknown_sector", "The target sector does not exist", 404)
        term.status = "resolved"
        term.resolved_sector_key = sector_key
        term.resolved_by = actor
        term.resolved_at = datetime.now(timezone.utc)
        self.repo.audit(actor, "unmapped_term_resolved", "unmapped_term", term.id, {"sector_key": sector_key})
        self.repo.commit()
        return term
