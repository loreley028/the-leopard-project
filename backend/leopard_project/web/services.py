from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path, PurePath
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


def _field(text: str, label: str) -> str:
    match = re.search(rf"^{re.escape(label)}[：:]\s*(.+)$", text, re.M)
    return match.group(1).strip() if match else ""


def _candidate_date(text: str) -> date | None:
    match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?", text)
    return date(*map(int, match.groups())) if match else None


def parse_report_text(text: str, report_id: str) -> tuple[dict, list[ReportSection], list[SectorMention], list[UnmappedTerm]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    title = _field(text, "报告标题") or (lines[0] if lines else "待复核报告")
    fields = {
        "title": title,
        "candidate_report_date": _candidate_date(text),
        "core_view": _field(text, "核心观点"),
        "market_path": _field(text, "大盘路径"),
        "risk_warning": _field(text, "风险提示"),
        "focus_sectors": [item.strip() for item in re.split(r"[,，、]", _field(text, "重点板块")) if item.strip()],
    }
    sections = [
        ReportSection(report_id=report_id, section_type=key, heading=label, raw_text=fields[key] or "无法确认", extraction_status="explicit" if fields[key] else "unconfirmed")
        for key, label in (("core_view", "核心观点"), ("market_path", "大盘路径"), ("risk_warning", "风险提示"))
    ]
    bundle = load_seed_bundle()
    mentions: list[SectorMention] = []
    seen: set[str] = set()
    for sector in bundle.sectors:
        if sector.sector_name in text:
            seen.add(sector.sector_key)
            summary = _field(text, sector.sector_name) or f"PDF明确提及{sector.sector_name}，具体表述需人工复核。"
            mentions.append(SectorMention(report_id=report_id, sector_key=sector.sector_key, sector_name=sector.sector_name, summary=summary, source_text=summary))
    for alias in bundle.aliases:
        if alias.confirmed and alias.alias in text and alias.sector_key not in seen:
            sector = next(item for item in bundle.sectors if item.sector_key == alias.sector_key)
            seen.add(alias.sector_key)
            mentions.append(SectorMention(report_id=report_id, sector_key=sector.sector_key, sector_name=sector.sector_name, summary=f"通过已确认别名“{alias.alias}”映射，需人工复核。", source_text=alias.alias))
    terms: list[UnmappedTerm] = []
    for raw in re.findall(r"^未映射[：:]\s*(.+)$", text, re.M):
        for term in [item.strip() for item in re.split(r"[,，、]", raw) if item.strip()]:
            if normalize_alias(term, bundle) is None:
                terms.append(UnmappedTerm(report_id=report_id, term=term, source_text=raw))
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
        report = Report(created_by=actor)
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
        self.transition(report, ReportStatus.PARSING)
        self.repo.commit()
        try:
            payload = (self.upload_dir / report.file.storage_filename).read_bytes()
            text = extract_text_layer(payload)
            if not text:
                raise WebDomainError("pdf_text_unavailable", "No reliable PDF text layer was extracted", 422)
            fields, sections, mentions, terms = parse_report_text(text, report.id)
            report.raw_text = text
            report.title = fields["title"]
            report.candidate_report_date = fields["candidate_report_date"]
            report.core_view = fields["core_view"]
            report.market_path = fields["market_path"]
            report.risk_warning = fields["risk_warning"]
            report.focus_sectors_json = json.dumps(fields["focus_sectors"], ensure_ascii=False)
            report.parse_note = "Local text-layer extraction; administrator review required."
            self.transition(report, ReportStatus.NEEDS_REVIEW)
            self.repo.replace_parse_results(report, sections, mentions, terms)
            self.repo.audit(actor, "report_parsed", "report", report.id, {"external_ai": False})
            self.repo.commit()
            return self.repo.by_id(report.id)  # type: ignore[return-value]
        except Exception as exc:
            report.status = ReportStatus.PARSE_FAILED.value
            report.parse_note = "Local parsing failed; the original file was retained."
            self.repo.audit(actor, "report_parse_failed", "report", report.id, {"error_type": type(exc).__name__})
            self.repo.commit()
            if isinstance(exc, WebDomainError):
                raise
            raise WebDomainError("pdf_parse_failed", "The PDF could not be parsed locally", 422) from exc

    def patch(self, report: Report, changes: dict, actor: str) -> Report:
        if report.status == ReportStatus.PUBLISHED.value:
            self.repo.revision(report, actor)
        for field in ("title", "report_date", "report_date_confirmed", "core_view", "market_path", "risk_warning"):
            if field in changes and changes[field] is not None:
                setattr(report, field, changes[field])
        if changes.get("focus_sectors") is not None:
            report.focus_sectors_json = json.dumps(changes["focus_sectors"], ensure_ascii=False)
        report.updated_at = datetime.now(timezone.utc)
        self.repo.audit(actor, "report_updated", "report", report.id, {"fields": sorted(changes)})
        self.repo.commit()
        return self.repo.by_id(report.id)  # type: ignore[return-value]

    def ready(self, report: Report, actor: str) -> Report:
        if not report.report_date_confirmed or not report.report_date:
            raise WebDomainError("report_date_confirmation_required", "Administrator confirmation of report date is required", 409)
        if any(term.status == "unresolved" for term in report.unmapped_terms):
            raise WebDomainError("unmapped_terms_unresolved", "Resolve unmapped terms before publishing", 409)
        self.transition(report, ReportStatus.READY_TO_PUBLISH)
        self.repo.audit(actor, "report_ready", "report", report.id)
        self.repo.commit()
        return report

    def publish(self, report: Report, actor: str) -> Report:
        if report.status == ReportStatus.PUBLISHED.value:
            return report
        self.transition(report, ReportStatus.PUBLISHED)
        report.published_at = datetime.now(timezone.utc)
        report.published_by = actor
        self.repo.publish_event(report, "published", actor)
        self.repo.audit(actor, "report_published", "report", report.id)
        self.repo.commit()
        return report

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
