from __future__ import annotations

import json
from datetime import date

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, selectinload

from .models import AuditEvent, PublishEvent, Report, ReportFile, ReportRevision, ReportSection, SectorMention, UnmappedTerm


REPORT_LOADS = (
    selectinload(Report.file),
    selectinload(Report.sections),
    selectinload(Report.mentions),
    selectinload(Report.unmapped_terms),
)


class ReportRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def by_id(self, report_id: str) -> Report | None:
        return self.session.scalar(select(Report).where(Report.id == report_id).options(*REPORT_LOADS))

    def by_sha256(self, sha256: str) -> Report | None:
        return self.session.scalar(
            select(Report).join(ReportFile).where(ReportFile.sha256 == sha256).options(*REPORT_LOADS)
        )

    def list_reports(self, *, published_only: bool = False) -> list[Report]:
        query = select(Report).options(*REPORT_LOADS)
        if published_only:
            query = query.where(Report.status == "published", Report.is_current.is_(True))
        return list(self.session.scalars(query.order_by(desc(Report.report_date), desc(Report.created_at))).unique())

    def reports_on(self, report_date: date, *, exclude_id: str | None = None) -> list[Report]:
        query = select(Report).where(Report.report_date == report_date).options(*REPORT_LOADS)
        if exclude_id:
            query = query.where(Report.id != exclude_id)
        return list(self.session.scalars(query.order_by(desc(Report.revision_number))).unique())

    def create(self, report: Report, report_file: ReportFile) -> Report:
        report.file = report_file
        self.session.add(report)
        self.session.commit()
        return self.by_id(report.id)  # type: ignore[return-value]

    def replace_parse_results(
        self,
        report: Report,
        sections: list[ReportSection],
        mentions: list[SectorMention],
        terms: list[UnmappedTerm],
    ) -> None:
        report.sections.clear()
        report.mentions.clear()
        report.unmapped_terms.clear()
        self.session.flush()
        report.sections.extend(sections)
        report.mentions.extend(mentions)
        report.unmapped_terms.extend(terms)
        self.session.commit()

    def revision(self, report: Report, actor: str) -> None:
        next_number = (self.session.scalar(select(func.count()).select_from(ReportRevision).where(ReportRevision.report_id == report.id)) or 0) + 1
        snapshot = {
            "title": report.title,
            "report_date": report.report_date.isoformat() if report.report_date else None,
            "core_view": report.core_view,
            "market_path": report.market_path,
            "risk_warning": report.risk_warning,
            "focus_sectors": json.loads(report.focus_sectors_json),
        }
        self.session.add(ReportRevision(report_id=report.id, revision_number=next_number, changed_by=actor, snapshot_json=json.dumps(snapshot, ensure_ascii=False)))

    def audit(self, actor: str, action: str, entity_type: str, entity_id: str, details: dict | None = None) -> None:
        self.session.add(AuditEvent(actor=actor, action=action, entity_type=entity_type, entity_id=entity_id, details_json=json.dumps(details or {}, ensure_ascii=False)))

    def publish_event(self, report: Report, event_type: str, actor: str, reason: str | None = None) -> None:
        self.session.add(PublishEvent(report_id=report.id, event_type=event_type, actor=actor, reason=reason))

    def latest_mentions(self) -> dict[str, SectorMention]:
        result: dict[str, SectorMention] = {}
        for report in self.list_reports(published_only=True):
            for mention in report.mentions:
                result.setdefault(mention.sector_key, mention)
        return result

    def sector_timeline(self, sector_key: str) -> list[tuple[Report, SectorMention]]:
        rows: list[tuple[Report, SectorMention]] = []
        for report in self.list_reports(published_only=True):
            mention = next((item for item in report.mentions if item.sector_key == sector_key), None)
            if mention:
                rows.append((report, mention))
        return rows

    def get_unmapped(self, term_id: str) -> UnmappedTerm | None:
        return self.session.get(UnmappedTerm, term_id)

    def commit(self) -> None:
        self.session.commit()
