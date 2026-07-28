from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from leopard_project.config import load_seed_bundle

from .models import (
    PathHistoryImport,
    Report,
    ReportSectorMarketSnapshot,
    SectorDailyBar,
    SectorPathHistoryEntry,
)


def matrix_dates(report_date: date, raw_dates: list[str]) -> list[date]:
    """Resolve M/DD matrix headers against the known final report date.

    The matrix is chronological and may cross a year boundary.  Resolving from
    the final report backwards avoids interpreting a historical month as a
    future date.
    """

    if not raw_dates:
        return []
    resolved_reversed: list[date] = []
    year = report_date.year
    next_month = report_date.month
    for raw in reversed(raw_dates):
        month_text, day_text = raw.split("/", 1)
        month, day = int(month_text), int(day_text)
        if month > next_month:
            year -= 1
        resolved_reversed.append(date(year, month, day))
        next_month = month
    return list(reversed(resolved_reversed))


def _snapshot_payload(row: ReportSectorMarketSnapshot | None) -> tuple[date | None, float | None, str]:
    if row is None:
        return None, None, "unavailable"
    payload = json.loads(row.snapshot_json or "{}")
    return row.market_as_of_date, payload.get("daily_pct_change"), "eod_complete"


@dataclass(frozen=True)
class PathHistorySyncResult:
    date_count: int
    sector_count: int
    inserted_count: int
    unchanged_count: int
    difference_count: int
    status: str
    differences: list[dict[str, Any]]


def sync_path_history(session: Session, report: Report) -> PathHistorySyncResult:
    metadata = json.loads(report.interpretation_meta_json or "{}")
    matrix = metadata.get("pdf_history_matrix") or {}
    raw_dates = list(matrix.get("dates") or [])
    rows = list(matrix.get("rows") or [])
    bundle = load_seed_bundle()
    valid_sectors = {item.sector_key: item for item in bundle.sectors}
    if not report.report_date or len(rows) != len(valid_sectors) or not raw_dates:
        return PathHistorySyncResult(len(raw_dates), len(rows), 0, 0, 0, "not_reliable", [])
    by_sector = {item.get("sector_key"): item for item in rows}
    if set(by_sector) != set(valid_sectors) or any(len(item.get("statuses") or []) != len(raw_dates) for item in rows):
        return PathHistorySyncResult(len(raw_dates), len(rows), 0, 0, 0, "not_reliable", [])

    resolved_dates = matrix_dates(report.report_date, raw_dates)
    detailed_reports = {
        item.report_date: item
        for item in session.scalars(select(Report).where(Report.report_date.in_(resolved_dates), Report.is_current.is_(True)))
        if item.report_date
    }
    snapshots = {
        (item.report_id, item.sector_key): item
        for item in session.scalars(select(ReportSectorMarketSnapshot).where(
            ReportSectorMarketSnapshot.report_id.in_([item.id for item in detailed_reports.values()])
        ))
    } if detailed_reports else {}
    market_rows: dict[str, list[SectorDailyBar]] = {}
    for bar in session.scalars(select(SectorDailyBar).where(
        SectorDailyBar.eod_status == "complete_eod",
        SectorDailyBar.trade_date <= max(resolved_dates),
    ).order_by(SectorDailyBar.trade_date)):
        market_rows.setdefault(bar.sector_key, []).append(bar)

    existing = {
        (item.sector_key, item.path_report_date): item
        for item in session.scalars(select(SectorPathHistoryEntry).where(
            SectorPathHistoryEntry.path_report_date.in_(resolved_dates)
        ))
    }
    inserted = unchanged = 0
    differences: list[dict[str, Any]] = []
    source_hash = report.file.sha256 if report.file else ""
    valid_statuses = {"avoid", "strong_watch", "watch", "weak_watch", "turn_hold", "hold", "turn_weak", "exit", "not_mentioned"}
    for sector_key, sector in valid_sectors.items():
        statuses = by_sector[sector_key]["statuses"]
        for path_date, status in zip(resolved_dates, statuses):
            if status not in valid_statuses:
                differences.append({"sector_key": sector_key, "report_date": path_date.isoformat(), "reason": "unknown_status", "new_status": status})
                continue
            current = existing.get((sector_key, path_date))
            detail = detailed_reports.get(path_date)
            snapshot = snapshots.get((detail.id, sector_key)) if detail else None
            market_date, daily_pct, market_status = _snapshot_payload(snapshot)
            if snapshot is None:
                bar = next((item for item in reversed(market_rows.get(sector_key, [])) if item.trade_date <= path_date), None)
                if bar is not None:
                    market_date = bar.trade_date
                    daily_pct = float(bar.daily_pct_change)
                    market_status = "eod_complete"
            if current is not None:
                if current.path_status != status:
                    differences.append({
                        "sector_key": sector_key,
                        "sector_name": sector.sector_name,
                        "report_date": path_date.isoformat(),
                        "old_status": current.path_status,
                        "new_status": status,
                    })
                    continue
                if detail and current.detail_report_id is None:
                    current.detail_report_id = detail.id
                unchanged += 1
                continue
            session.add(SectorPathHistoryEntry(
                sector_key=sector_key,
                sector_name=sector.sector_name,
                path_report_date=path_date,
                path_status=status,
                source_report_id=report.id,
                detail_report_id=detail.id if detail else None,
                market_as_of_date=market_date,
                frozen_daily_pct_change=daily_pct,
                market_data_status=market_status,
                source_pdf_sha256=source_hash,
                template_version=report.template_version,
            ))
            inserted += 1

    difference_count = len(differences)
    status = "initialized" if not existing else "appended" if inserted else "unchanged"
    if difference_count:
        status = "needs_attention" if difference_count <= 10 else "blocking_difference"
    audit = session.scalar(select(PathHistoryImport).where(PathHistoryImport.source_report_id == report.id))
    if audit is None:
        session.add(PathHistoryImport(
            source_report_id=report.id,
            source_pdf_sha256=source_hash,
            template_version=report.template_version,
            date_count=len(resolved_dates),
            sector_count=len(rows),
            inserted_count=inserted,
            unchanged_count=unchanged,
            difference_count=difference_count,
            status=status,
            differences_json=json.dumps(differences, ensure_ascii=False),
        ))
    session.commit()
    return PathHistorySyncResult(len(resolved_dates), len(rows), inserted, unchanged, difference_count, status, differences)


def ensure_latest_path_history(session: Session, through: date | None = None) -> PathHistorySyncResult | None:
    query = select(Report).where(Report.status == "published", Report.is_current.is_(True))
    if through is not None:
        query = query.where(Report.report_date <= through)
    reports = list(session.scalars(query.order_by(desc(Report.report_date))))
    source = next((item for item in reports if len((json.loads(item.interpretation_meta_json or "{}").get("pdf_history_matrix") or {}).get("rows") or []) == 66), None)
    return sync_path_history(session, source) if source else None


def audit_frozen_path_history(session: Session, report: Report) -> list[dict[str, Any]]:
    """Compare a newly parsed matrix with frozen rows without mutating them."""

    metadata = json.loads(report.interpretation_meta_json or "{}")
    matrix = metadata.get("pdf_history_matrix") or {}
    raw_dates = list(matrix.get("dates") or [])
    rows = list(matrix.get("rows") or [])
    if not report.report_date or not raw_dates or len(rows) != 66:
        return []
    resolved_dates = matrix_dates(report.report_date, raw_dates)
    existing = {
        (item.sector_key, item.path_report_date): item.path_status
        for item in session.scalars(select(SectorPathHistoryEntry).where(
            SectorPathHistoryEntry.path_report_date.in_(resolved_dates)
        ))
    }
    differences: list[dict[str, Any]] = []
    for row in rows:
        for path_date, status in zip(resolved_dates, row.get("statuses") or []):
            old = existing.get((row.get("sector_key"), path_date))
            if old is not None and old != status:
                differences.append({
                    "sector_key": row.get("sector_key"), "sector_name": row.get("sector_name"),
                    "report_date": path_date.isoformat(), "old_status": old, "new_status": status,
                })
    return differences
