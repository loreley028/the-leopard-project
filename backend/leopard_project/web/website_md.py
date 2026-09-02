from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from leopard_project.config import load_seed_bundle
from leopard_project.report_registry import ReportObject, load_report_registry

from .models import (
    PathHistoryImport,
    Report,
    ReportDay,
    ReportStatus,
    ReportSection,
    SectorAssessment,
    SectorMention,
    SectorPathEntry,
    SectorPathHistoryEntry,
)
from .repository import ReportRepository
from .services import ReportService, WebDomainError


SUPPORTED_SCHEMA = "leopard-website-md"
SUPPORTED_SCHEMA_VERSION = "1.0"
STATUS_TO_CODE = {
    "不碰": "avoid",
    "强观": "strong_watch",
    "观察": "watch",
    "弱观": "weak_watch",
    "转持": "turn_hold",
    "持有": "hold",
    "转弱": "turn_weak",
    "离场": "exit",
    "未提": "not_mentioned",
}
FORBIDDEN_MARKET_KEYS = {
    "current_price",
    "latest_price",
    "daily_pct_change",
    "pct_change",
    "quote_time",
    "quote_timestamp",
    "market_timestamp",
    "security_code",
}


def _plain(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _required_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WebDomainError("invalid_website_md", f"{label} 必须是结构化对象", 422)
    return {str(key): _plain(item) for key, item in value.items()}


def _required_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise WebDomainError("invalid_website_md", f"{label} 必须是列表", 422)
    return [_plain(item) for item in value]


def _number(value: Any, label: str) -> float:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise WebDomainError("invalid_website_md", f"{label} 必须是有效数值", 422) from exc
    if not result.is_finite() or result <= 0:
        raise WebDomainError("invalid_website_md", f"{label} 必须是正数", 422)
    return float(result)


def _integer(value: Any, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise WebDomainError("invalid_website_md", f"{label} 必须是整数", 422) from exc
    return result


def _normalized_name(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _find_forbidden_market_keys(value: Any, prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            location = f"{prefix}.{key_text}" if prefix else key_text
            if key_text in FORBIDDEN_MARKET_KEYS:
                found.append(location)
            found.extend(_find_forbidden_market_keys(item, location))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_find_forbidden_market_keys(item, f"{prefix}[{index}]"))
    return found


@dataclass(frozen=True)
class WebsiteMdDocument:
    raw_text: str
    sha256: str
    metadata: dict[str, Any]
    report_opinions: dict[str, Any]
    defense: dict[str, Any]
    topics: list[dict[str, Any]]
    sector_updates: list[dict[str, Any]]
    unmentioned_sectors: list[str]
    major_changes: list[str]
    core_conclusion: str
    sector_candidates: list[Any]
    structure_changes: list[Any]
    calendar_markers: list[dict[str, Any]]
    checks: dict[str, Any]
    resolved_sector_keys: dict[str, str]

    @property
    def report_date(self) -> date:
        return date.fromisoformat(str(self.metadata["report_date"]))

    @property
    def primary_line(self) -> float:
        return _number(self.defense.get("primary_line"), "primary_line")

    @property
    def previous_line(self) -> float:
        return _number(self.defense.get("previous_line"), "previous_line")

    def validation_payload(self) -> dict[str, Any]:
        return {
            "schema": self.metadata["schema"],
            "schema_version": self.metadata["schema_version"],
            "report_date": self.report_date.isoformat(),
            "display_row_count": _integer(self.metadata["display_row_count"], "display_row_count"),
            "active_object_count": _integer(self.metadata["active_object_count"], "active_object_count"),
            "updated_sector_count": len(self.sector_updates),
            "unmentioned_sector_count": len(self.unmentioned_sectors),
            "updated_plus_unmentioned": len(self.sector_updates) + len(self.unmentioned_sectors),
            "unknown_sector_count": 0,
            "duplicate_sector_count": 0,
            "validation_status": "valid",
        }

    def structured_payload(self) -> dict[str, Any]:
        return {
            "report_metadata": self.metadata,
            "report_opinions": self.report_opinions,
            "defense": self.defense,
            "dynamic_topics": self.topics,
            "sector_updates": self.sector_updates,
            "unmentioned_sectors": self.unmentioned_sectors,
            "major_changes": self.major_changes,
            "core_conclusion": self.core_conclusion,
            "sector_candidates": self.sector_candidates,
            "structure_changes": self.structure_changes,
            "calendar_markers": self.calendar_markers,
        }


def parse_website_md(payload: bytes, filename: str) -> WebsiteMdDocument:
    if not filename.lower().endswith(".md"):
        raise WebDomainError("invalid_website_md_type", "网站结构化文件必须是 .md", 422)
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WebDomainError("invalid_website_md_encoding", "网站 MD 必须使用 UTF-8 编码", 422) from exc
    if len(payload) > 2_000_000:
        raise WebDomainError("website_md_too_large", "网站 MD 超过 2MB 限制", 413)

    front_match = re.match(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", text, re.S)
    if not front_match:
        raise WebDomainError("invalid_website_md", "网站 MD 缺少 YAML front matter", 422)
    try:
        metadata = _required_mapping(yaml.safe_load(front_match.group(1)), "front matter")
    except yaml.YAMLError as exc:
        raise WebDomainError("invalid_website_md", "网站 MD front matter 不是有效 YAML", 422) from exc

    blocks: dict[str, Any] = {}
    for block_match in re.finditer(r"```ya?ml\s*\n(.*?)\n```", text[front_match.end():], re.S | re.I):
        try:
            block = yaml.safe_load(block_match.group(1))
        except yaml.YAMLError as exc:
            raise WebDomainError("invalid_website_md", "网站 MD 含无效 YAML 数据块", 422) from exc
        if not isinstance(block, dict):
            raise WebDomainError("invalid_website_md", "网站 MD 的 YAML 数据块必须是对象", 422)
        for key, value in block.items():
            key_text = str(key)
            if key_text in blocks:
                raise WebDomainError("duplicate_website_md_field", f"网站 MD 字段重复：{key_text}", 422)
            blocks[key_text] = _plain(value)

    if metadata.get("schema") != SUPPORTED_SCHEMA or str(metadata.get("schema_version")) != SUPPORTED_SCHEMA_VERSION:
        raise WebDomainError("unsupported_website_md_schema", "仅支持 leopard-website-md 1.0", 422)
    try:
        report_date = date.fromisoformat(str(metadata["report_date"]))
    except (KeyError, ValueError) as exc:
        raise WebDomainError("invalid_website_md", "report_date 必须是 YYYY-MM-DD", 422) from exc
    if not report_date:
        raise WebDomainError("invalid_website_md", "report_date 不能为空", 422)

    required_opinions = ("market_nature", "core_view", "position_discipline", "next_day_script", "core_classification")
    report_opinions = {key: blocks.get(key) for key in required_opinions}
    if any(not isinstance(value, str) or not value.strip() for value in report_opinions.values()):
        raise WebDomainError("invalid_website_md", "报告级观点字段不完整", 422)
    defense_keys = (
        "primary_line", "previous_line", "effective_from", "stand_above_condition",
        "break_below_condition", "validation_condition", "source_summary",
    )
    defense = {key: blocks.get(key) for key in defense_keys}
    _number(defense["primary_line"], "primary_line")
    _number(defense["previous_line"], "previous_line")
    for key in defense_keys[2:]:
        if not isinstance(defense[key], str) or not str(defense[key]).strip():
            raise WebDomainError("invalid_website_md", f"攻防线字段缺失：{key}", 422)

    topics = [_required_mapping(item, "dynamic topic") for item in _required_list(blocks.get("topics"), "topics")]
    sector_updates = [_required_mapping(item, "sector update") for item in _required_list(blocks.get("sector_updates"), "sector_updates")]
    unmentioned = [str(item).strip() for item in _required_list(blocks.get("unmentioned_sectors"), "unmentioned_sectors")]
    major_changes = [str(item) for item in _required_list(blocks.get("major_changes"), "major_changes")]
    core_conclusion = blocks.get("core_conclusion")
    if not isinstance(core_conclusion, str) or not core_conclusion.strip():
        raise WebDomainError("invalid_website_md", "core_conclusion 不能为空", 422)
    sector_candidates = _required_list(blocks.get("sector_candidates"), "sector_candidates")
    structure_changes = _required_list(blocks.get("structure_changes"), "structure_changes")
    calendar_markers = [_required_mapping(item, "calendar marker") for item in _required_list(blocks.get("calendar_markers"), "calendar_markers")]
    checks = _required_mapping(blocks.get("checks"), "checks")

    registry = load_report_registry()
    active = [item for item in registry if item.lifecycle == "active"]
    by_name = {_normalized_name(item.sector_name): item for item in active}
    resolved: dict[str, str] = {}
    unknown: list[str] = []
    duplicate: list[str] = []
    ordered_names = [str(item.get("sector") or "").strip() for item in sector_updates] + unmentioned
    seen: set[str] = set()
    for name in ordered_names:
        item = by_name.get(_normalized_name(name))
        if item is None:
            unknown.append(name)
            continue
        if item.sector_key in seen:
            duplicate.append(name)
            continue
        seen.add(item.sector_key)
        resolved[name] = item.sector_key
    if unknown:
        raise WebDomainError("unknown_website_md_sector", f"网站 MD 含未知板块：{'、'.join(unknown)}", 422)
    if duplicate:
        raise WebDomainError("duplicate_website_md_sector", f"网站 MD 含重复板块：{'、'.join(duplicate)}", 422)

    expected_keys = {item.sector_key for item in active}
    missing_keys = expected_keys - seen
    if missing_keys:
        missing_names = [item.sector_name for item in active if item.sector_key in missing_keys]
        raise WebDomainError("website_md_sector_coverage_mismatch", f"网站 MD 未覆盖 active 对象：{'、'.join(missing_names)}", 422)
    declared_display = _integer(metadata.get("display_row_count"), "display_row_count")
    declared_active = _integer(metadata.get("active_object_count"), "active_object_count")
    if declared_display != len(registry) or declared_active != len(active):
        raise WebDomainError("website_md_registry_count_mismatch", "网站 MD 的显示/active 对象数与当前 registry 不一致", 422)
    if len(sector_updates) + len(unmentioned) != len(active):
        raise WebDomainError("website_md_sector_count_mismatch", "updated + unmentioned 必须等于 active object count", 422)

    required_update_fields = {
        "sector", "group", "path_mark", "previous_effective_status", "previous_effective_date",
        "effective_status", "evidence", "condition", "qualification", "change_type",
    }
    for item in sector_updates:
        missing = [key for key in required_update_fields if item.get(key) in {None, ""}]
        if missing:
            raise WebDomainError("invalid_website_md", f"板块 {item.get('sector') or '未知'} 缺少字段：{','.join(missing)}", 422)
        if item["path_mark"] not in STATUS_TO_CODE or item["effective_status"] not in STATUS_TO_CODE:
            raise WebDomainError("unknown_path_status", f"板块 {item['sector']} 含未知状态", 422)
        if STATUS_TO_CODE[item["path_mark"]] == "not_mentioned":
            raise WebDomainError("invalid_website_md", f"板块更新 {item['sector']} 不得使用未提", 422)
        report_object = by_name[_normalized_name(str(item["sector"]))]
        if str(item["group"]).strip() != report_object.group_name:
            raise WebDomainError("website_md_sector_group_mismatch", f"板块 {item['sector']} 的分组与 registry 不一致", 422)
    for marker in calendar_markers:
        try:
            date.fromisoformat(str(marker.get("date")))
        except ValueError as exc:
            raise WebDomainError("invalid_website_md", "calendar marker 日期无效", 422) from exc
        if marker.get("mark") != "休":
            raise WebDomainError("unsupported_calendar_marker", "1.0 仅支持显示标记“休”", 422)

    structured = {**metadata, **blocks}
    forbidden = _find_forbidden_market_keys(structured)
    if forbidden:
        raise WebDomainError("website_md_contains_market_data", f"网站 MD 不得包含实时行情字段：{','.join(forbidden)}", 422)

    return WebsiteMdDocument(
        raw_text=text,
        sha256=hashlib.sha256(payload).hexdigest(),
        metadata=metadata,
        report_opinions=report_opinions,
        defense=defense,
        topics=topics,
        sector_updates=sector_updates,
        unmentioned_sectors=unmentioned,
        major_changes=major_changes,
        core_conclusion=core_conclusion,
        sector_candidates=sector_candidates,
        structure_changes=structure_changes,
        calendar_markers=calendar_markers,
        checks=checks,
        resolved_sector_keys=resolved,
    )


class WebsiteMdImportService:
    def __init__(self, session: Session, report_service: ReportService):
        self.session = session
        self.report_service = report_service
        self.repo = ReportRepository(session)

    def apply(self, report: Report, document: WebsiteMdDocument, filename: str, actor: str) -> Report:
        if report.status == "published":
            raise WebDomainError("published_report_read_only", "已发布报告不能覆盖导入", 409)
        self.report_service.transition(report, ReportStatus.PARSING)
        self.session.flush()

        registry = load_report_registry()
        registry_by_key = {item.sector_key: item for item in registry}
        active_keys = {item.sector_key for item in registry if item.lifecycle == "active"}
        updates_by_key = {
            document.resolved_sector_keys[str(item["sector"])]: item
            for item in document.sector_updates
        }
        unmentioned_keys = {document.resolved_sector_keys[name] for name in document.unmentioned_sectors}
        status_by_key = {
            **{key: STATUS_TO_CODE[str(item["path_mark"])] for key, item in updates_by_key.items()},
            **{key: "not_mentioned" for key in unmentioned_keys},
        }

        report_date = document.report_date
        report.report_date = report_date
        report.candidate_report_date = report_date
        report.detected_report_date = report_date
        report.report_date_confirmed = True
        report.report_date_source = "pdf_title_and_website_md"
        report.report_date_confidence = "high"
        report.title = f"大盘猎豹 {report_date.year}年{report_date.month}月{report_date.day}日直播总结"
        report.template_version = "MD1.0"
        prior_versions = self.repo.reports_on(report_date, exclude_id=report.id)
        report.revision_number = max((item.revision_number for item in prior_versions), default=0) + 1
        report.replaces_report_id = prior_versions[0].id if prior_versions else None
        report.core_view = str(document.report_opinions["core_view"])
        report.market_path = str(document.report_opinions["next_day_script"])
        report.risk_warning = str(document.report_opinions["position_discipline"])
        report.focus_sectors_json = json.dumps(list(updates_by_key), ensure_ascii=False)
        report.raw_text = document.raw_text
        report.parse_note = "网站 MD 1.0 已作为结构化主数据源；PDF 仅用于展示、留档与人工核验。"
        report.interpretation_status = "ready"
        report.enhanced_status = "ready"
        report.enhanced_revision_number += 1

        source_summary = str(document.defense["source_summary"])
        metadata = {
            "source_kind": "website_md",
            "quality_status": "verified_structure",
            "attention_items": [],
            "field_provenance": {
                "core_view": self._provenance(document.report_opinions["core_view"], "报告级观点.core_view"),
                "market_path": self._provenance(document.report_opinions["next_day_script"], "报告级观点.next_day_script"),
                "risk_warning": self._provenance(document.report_opinions["position_discipline"], "报告级观点.position_discipline"),
            },
            "defense_lines": {
                "primary_defense_line": document.primary_line,
                "secondary_defense_line": document.previous_line,
                "stand_above_condition": document.defense["stand_above_condition"],
                "break_below_condition": document.defense["break_below_condition"],
                "validation_condition": document.defense["validation_condition"],
                "source_summary": source_summary,
                "candidates": [
                    {"value": document.primary_line, "role": "primary", "source_text": source_summary, "source_section": "猎豹攻防点", "confidence": "high"},
                    {"value": document.previous_line, "role": "secondary_previous", "source_text": source_summary, "source_section": "猎豹攻防点", "confidence": "high"},
                ],
            },
            "mapping_summary": {
                "updated_sector_count": len(document.sector_updates),
                "unmentioned_sector_count": len(document.unmentioned_sectors),
                "active_object_count": len(active_keys),
                "unknown_sector_count": 0,
                "duplicate_sector_count": 0,
            },
            "quality_summary": {
                "assessment_rows": len(active_keys),
                "assessment_verified": len(active_keys),
                "assessment_needs_attention": 0,
                "assessment_blocking": 0,
            },
            "website_md": {
                "filename": filename,
                "sha256": document.sha256,
                "validation": document.validation_payload(),
                "structured_content": document.structured_payload(),
                "checks_declared_untrusted": document.checks,
                "history_mode": "daily_increment_only",
                "pdf_history_matrix_parsed": False,
            },
        }
        report.interpretation_meta_json = json.dumps(metadata, ensure_ascii=False)

        report.sections.clear()
        report.mentions.clear()
        self.session.flush()
        report.sections.extend(self._sections(report.id, document))
        report.mentions.extend(self._mentions(report.id, updates_by_key, registry_by_key))

        for existing in list(self.session.scalars(select(SectorPathEntry).where(SectorPathEntry.report_id == report.id))):
            self.session.delete(existing)
        for existing in list(self.session.scalars(select(SectorAssessment).where(SectorAssessment.report_id == report.id))):
            self.session.delete(existing)
        self.session.flush()

        base_keys = {item.sector_key for item in load_seed_bundle().sectors}
        for report_object in registry:
            status = status_by_key.get(report_object.sector_key, "not_mentioned")
            update = updates_by_key.get(report_object.sector_key)
            explicit = update is not None and report_object.sector_key in active_keys
            source = self._source_reference(update, report_object) if update else ""
            if report_object.sector_key in base_keys:
                self.session.add(SectorPathEntry(
                    report_id=report.id,
                    sector_key=report_object.sector_key,
                    sector_name=report_object.sector_name,
                    path_status=status,
                    explicitly_mentioned=explicit,
                    judgement_summary=str(update.get("evidence") or "") if update else "",
                    source_text_reference=source,
                    confidence="high" if report_object.sector_key in active_keys else "low",
                    validation_flags_json="[]",
                    quality_status="verified_structure" if report_object.sector_key in active_keys else "not_applicable",
                    review_status="confirmed" if report_object.sector_key in active_keys else "not_applicable",
                    revision_id="website-md-1.0",
                ))
            self.session.add(SectorAssessment(
                report_id=report.id,
                sector_key=report_object.sector_key,
                sector_name=report_object.sector_name,
                current_path_status=status,
                explicitly_mentioned=explicit,
                recent_path_summary=str(update.get("change_type") or "") if update else "本期未明确提及",
                current_judgement=(
                    f"{update.get('qualification')} · {update.get('effective_status')}" if update else ""
                ),
                main_basis=str(update.get("evidence") or "") if update else "",
                observation_condition=str(update.get("condition") or "") if update else "",
                source_section="网站MD·当日板块更新" if update else "网站MD·本场未更新板块",
                source_text_reference=source,
                extraction_method="website_md_v1" if report_object.sector_key in active_keys else "not_applicable",
                source_text_excerpt=source,
                confidence="high" if report_object.sector_key in active_keys else "low",
                validation_flags_json="[]",
                quality_status="verified_structure" if report_object.sector_key in active_keys else "not_applicable",
                review_status="confirmed" if report_object.sector_key in active_keys else "not_applicable",
                revision_id="website-md-1.0",
            ))

        self.report_service.transition(report, ReportStatus.NEEDS_REVIEW)
        self.repo.audit(actor, "website_md_imported", "report", report.id, {
            "website_md_sha256": document.sha256,
            "report_date": report_date.isoformat(),
            "updated_sector_count": len(document.sector_updates),
            "unmentioned_sector_count": len(document.unmentioned_sectors),
            "active_object_count": len(active_keys),
            "pdf_history_matrix_parsed": False,
        })
        self.session.commit()
        return self.repo.by_id(report.id) or report

    def stage_incremental_history(self, report: Report, document: WebsiteMdDocument, actor: str) -> dict[str, int]:
        if not report.report_date or not report.file:
            raise WebDomainError("website_md_report_incomplete", "报告日期或 PDF 身份缺失", 409)
        registry = {item.sector_key: item for item in load_report_registry() if item.lifecycle == "active"}
        statuses = {
            **{
                document.resolved_sector_keys[str(item["sector"])]: STATUS_TO_CODE[str(item["path_mark"])]
                for item in document.sector_updates
            },
            **{document.resolved_sector_keys[name]: "not_mentioned" for name in document.unmentioned_sectors},
        }
        inserted = unchanged = 0
        for sector_key, report_object in registry.items():
            status = statuses[sector_key]
            existing = self.session.scalar(select(SectorPathHistoryEntry).where(
                SectorPathHistoryEntry.sector_key == sector_key,
                SectorPathHistoryEntry.path_report_date == report.report_date,
            ))
            if existing is not None:
                if existing.source_report_id == report.id and existing.path_status == status:
                    unchanged += 1
                    continue
                raise WebDomainError("canonical_history_conflict", f"{report_object.sector_name} 当日路径已存在不同来源", 409)
            self.session.add(SectorPathHistoryEntry(
                sector_key=sector_key,
                sector_name=report_object.sector_name,
                path_report_date=report.report_date,
                path_status=status,
                source_report_id=report.id,
                detail_report_id=report.id,
                market_as_of_date=None,
                frozen_daily_pct_change=None,
                market_data_status="unavailable",
                source_pdf_sha256=report.file.sha256,
                template_version=report.template_version,
                source_kind="website_md_incremental",
            ))
            inserted += 1

        prior_import = self.session.scalar(select(PathHistoryImport).where(PathHistoryImport.source_report_id == report.id))
        if prior_import is None:
            self.session.add(PathHistoryImport(
                source_report_id=report.id,
                source_pdf_sha256=report.file.sha256,
                template_version=report.template_version,
                date_count=1,
                sector_count=len(registry),
                inserted_count=inserted,
                unchanged_count=unchanged,
                difference_count=0,
                status="verified_incremental_md",
                differences_json="[]",
            ))
        self._stage_calendar_markers(report, document, actor)
        metadata = json.loads(report.interpretation_meta_json or "{}")
        metadata["ingestion_summary"] = {
            "publication": "published",
            "report_date": report.report_date.isoformat(),
            "template_version": report.template_version,
            "structured_source": "website_md",
            "defense_lines": metadata.get("defense_lines", {}),
            "history_increment": {
                "active_objects": len(registry),
                "inserted_cells": inserted,
                "verified_same_cells": unchanged,
                "conflicts": 0,
                "pdf_history_matrix_parsed": False,
            },
            "manual_review": "not_required",
        }
        report.interpretation_meta_json = json.dumps(metadata, ensure_ascii=False)
        self.repo.audit(actor, "website_md_incremental_history_staged", "report", report.id, {
            "inserted_cells": inserted,
            "unchanged_cells": unchanged,
            "source_kind": "website_md_incremental",
        })
        self.session.flush()
        return {"inserted": inserted, "unchanged": unchanged}

    def _stage_calendar_markers(self, report: Report, document: WebsiteMdDocument, actor: str) -> None:
        for marker in document.calendar_markers:
            marker_date = date.fromisoformat(str(marker["date"]))
            conflicting_report = self.session.scalar(select(Report).where(
                Report.report_date == marker_date,
                Report.status == "published",
                Report.is_current.is_(True),
            ))
            if conflicting_report is not None:
                raise WebDomainError("calendar_marker_report_conflict", f"{marker_date} 已有正式报告，不能标记为休", 409)
            record = self.session.scalar(select(ReportDay).where(ReportDay.report_date == marker_date))
            if record is None:
                record = ReportDay(report_date=marker_date)
                self.session.add(record)
            elif record.state not in {"pending_upload", "no_live", "skipped"}:
                raise WebDomainError("calendar_marker_state_conflict", f"{marker_date} 日历状态冲突", 409)
            record.state = "no_live"
            record.skip_reason = str(marker.get("reason") or "网站MD日历标记")[:1000]
            record.confirmed_by = actor
            record.updated_at = datetime.now(timezone.utc)

    @staticmethod
    def _provenance(value: Any, field: str) -> dict[str, Any]:
        return {
            "extracted_value": value,
            "extraction_method": "website_md_v1",
            "source_page": None,
            "source_text_range": None,
            "source_reference": f"网站MD·{field}",
            "source_text_excerpt": str(value)[:500],
            "confidence": "high",
            "validation_flags": [],
            "manually_modified": False,
        }

    @staticmethod
    def _source_reference(update: dict[str, Any] | None, report_object: ReportObject) -> str:
        if update is None:
            return ""
        return (
            f"网站MD·当日板块更新·{report_object.sector_name}｜"
            f"路径={update.get('path_mark')}｜依据={update.get('evidence')}｜条件={update.get('condition')}"
        )

    @staticmethod
    def _sections(report_id: str, document: WebsiteMdDocument) -> list[ReportSection]:
        payloads = [
            ("report_opinions", "报告级观点", document.report_opinions),
            ("defense_line", "猎豹攻防点", document.defense),
            ("dynamic_topics", "动态主题", document.topics),
            ("sector_updates", "当日板块更新", document.sector_updates),
            ("unmentioned_sectors", "本场未更新板块", document.unmentioned_sectors),
            ("major_changes", "主要变化", document.major_changes),
            ("core_conclusion", "核心结论", document.core_conclusion),
            ("structure_candidates", "新板块与结构候选", {
                "sector_candidates": document.sector_candidates,
                "structure_changes": document.structure_changes,
            }),
            ("calendar_markers", "历史日历标记", document.calendar_markers),
        ]
        return [ReportSection(
            report_id=report_id,
            section_type=section_type,
            heading=heading,
            raw_text=json.dumps(payload, ensure_ascii=False),
            extraction_status="website_md_v1",
        ) for section_type, heading, payload in payloads]

    @staticmethod
    def _mentions(
        report_id: str,
        updates_by_key: dict[str, dict[str, Any]],
        registry_by_key: dict[str, ReportObject],
    ) -> list[SectorMention]:
        return [SectorMention(
            report_id=report_id,
            sector_key=sector_key,
            sector_name=registry_by_key[sector_key].sector_name,
            summary=str(update["evidence"]),
            source_text=WebsiteMdImportService._source_reference(update, registry_by_key[sector_key]),
            extraction_status="website_md_v1",
        ) for sector_key, update in updates_by_key.items()]
