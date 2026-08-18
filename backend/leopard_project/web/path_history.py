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


def _exact_market_payload(
    *,
    requested_market_date: date,
    snapshot: ReportSectorMarketSnapshot | None,
    bar: SectorDailyBar | None,
) -> tuple[date | None, float | None, str]:
    """Return only a fact whose date exactly matches the requested date.

    A report may explicitly bind a non-trading report date to a prior trading
    date.  That explicit binding is the requested date; a legacy ``last
    known`` bar is never an acceptable substitute.
    """
    if snapshot is not None:
        market_date, daily_pct, status = _snapshot_payload(snapshot)
        if market_date == requested_market_date:
            return market_date, daily_pct, status
        return None, None, "unavailable"
    if bar is not None and bar.trade_date == requested_market_date:
        return bar.trade_date, float(bar.daily_pct_change), "eod_complete"
    return None, None, "unavailable"


@dataclass(frozen=True)
class PathHistorySyncResult:
    date_count: int
    sector_count: int
    inserted_count: int
    unchanged_count: int
    difference_count: int
    status: str
    differences: list[dict[str, Any]]


def sync_path_history(session: Session, report: Report, *, commit: bool = True) -> PathHistorySyncResult:
    """Reconcile the derived canonical ledger from formal PDF matrices.

    A matrix stored on a report is an immutable report-local snapshot.  The
    ledger is a different, derived projection: a newer formal complete matrix
    is authoritative for an already represented historical cell.  Resolving
    all published sources on every sync makes that policy import-order
    independent and never imports market facts from a PDF.
    """
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
    valid_statuses = {"avoid", "strong_watch", "watch", "weak_watch", "turn_hold", "hold", "turn_weak", "exit", "not_mentioned"}
    authority_reports = list(session.scalars(
        select(Report)
        .where(Report.status == "published", Report.is_current.is_(True))
        .order_by(Report.report_date, Report.created_at, Report.id)
    ))
    # The caller publishes immediately before syncing but has not committed
    # yet. Include it explicitly instead of relying on autoflush behavior.
    if report not in authority_reports:
        authority_reports.append(report)
    authority_reports.sort(key=lambda item: (item.report_date or date.min, item.created_at, item.id))
    canonical_cells: dict[tuple[str, date], tuple[str, Report]] = {}
    for source in authority_reports:
        source_metadata = json.loads(source.interpretation_meta_json or "{}")
        source_matrix = source_metadata.get("pdf_history_matrix") or {}
        source_dates = list(source_matrix.get("dates") or [])
        source_rows = list(source_matrix.get("rows") or [])
        if (
            not source.report_date
            or (source_matrix.get("quality_status") != "verified_structure" and source.id != report.id)
            or len(source_rows) != len(valid_sectors)
            or not source_dates
        ):
            continue
        source_by_sector = {item.get("sector_key"): item for item in source_rows}
        if set(source_by_sector) != set(valid_sectors):
            continue
        source_resolved_dates = matrix_dates(source.report_date, source_dates)
        if any(len(item.get("statuses") or []) != len(source_resolved_dates) for item in source_rows):
            continue
        for sector_key, source_row in source_by_sector.items():
            for path_date, status in zip(source_resolved_dates, source_row.get("statuses") or []):
                if status != "blank" and status in valid_statuses:
                    # Sorted later reports intentionally replace earlier
                    # report-local snapshots for the same historical cell.
                    canonical_cells[(sector_key, path_date)] = (status, source)
    if not canonical_cells:
        return PathHistorySyncResult(len(resolved_dates), len(rows), 0, 0, 0, "not_reliable", [])

    canonical_dates = {path_date for _, path_date in canonical_cells}
    detailed_reports = {
        item.report_date: item
        for item in session.scalars(select(Report).where(Report.report_date.in_(canonical_dates), Report.is_current.is_(True)))
        if item.report_date
    }
    snapshots = {
        (item.report_id, item.sector_key): item
        for item in session.scalars(select(ReportSectorMarketSnapshot).where(
            ReportSectorMarketSnapshot.report_id.in_([item.id for item in detailed_reports.values()])
        ))
    } if detailed_reports else {}
    # A path cell may only carry an objectively observed market value for its
    # own requested market date.  Do not turn the last known close into a
    # surrogate quote for a later report/path date: that would permanently
    # contaminate the frozen path ledger.
    requested_market_dates = {
        item.market_as_of_date if item.market_as_of_date_confirmed and item.market_as_of_date else item.report_date
        for item in detailed_reports.values()
        if item.report_date
    } | canonical_dates
    market_rows: dict[tuple[str, date], SectorDailyBar] = {}
    for bar in session.scalars(select(SectorDailyBar).where(
        SectorDailyBar.eod_status == "complete_eod",
        SectorDailyBar.trade_date.in_(requested_market_dates),
    ).order_by(SectorDailyBar.trade_date)):
        market_rows[(bar.sector_key, bar.trade_date)] = bar

    existing = {
        (item.sector_key, item.path_report_date): item
        for item in session.scalars(select(SectorPathHistoryEntry).where(
            SectorPathHistoryEntry.path_report_date.in_(canonical_dates)
        ))
    }
    inserted = unchanged = 0
    differences: list[dict[str, Any]] = []
    superseded: list[dict[str, Any]] = []
    for (sector_key, path_date), (status, source) in sorted(canonical_cells.items(), key=lambda item: (item[0][1], item[0][0])):
        sector = valid_sectors[sector_key]
        current = existing.get((sector_key, path_date))
        detail = detailed_reports.get(path_date)
        requested_market_date = (
            detail.market_as_of_date
            if detail and detail.market_as_of_date_confirmed and detail.market_as_of_date
            else path_date
        )
        snapshot = snapshots.get((detail.id, sector_key)) if detail else None
        market_date, daily_pct, market_status = _exact_market_payload(
            requested_market_date=requested_market_date,
            snapshot=snapshot,
            bar=market_rows.get((sector_key, requested_market_date)),
        )
        if current is not None:
            if current.path_status != status:
                if current.source_report_id == source.id:
                    differences.append({
                        "sector_key": sector_key,
                        "sector_name": sector.sector_name,
                        "report_date": path_date.isoformat(),
                        "reason": "same_source_snapshot_changed",
                        "old_status": current.path_status,
                        "new_status": status,
                        "source_report_id": source.id,
                    })
                    continue
                superseded.append({
                    "report_date": path_date.isoformat(),
                    "sector_key": sector_key,
                    "sector_name": sector.sector_name,
                    "old_value": current.path_status,
                    "old_source_report_id": current.source_report_id,
                    "old_source_pdf_sha256": current.source_pdf_sha256,
                    "new_value": status,
                    "canonical_source_report_id": source.id,
                    "canonical_source_pdf_sha256": source.file.sha256 if source.file else "",
                    "resolution_reason": "newer_formal_history_baseline",
                })
                current.path_status = status
            current.source_report_id = source.id
            current.source_pdf_sha256 = source.file.sha256 if source.file else ""
            current.template_version = source.template_version
            current.source_kind = "newer_formal_history_baseline"
            if detail and current.detail_report_id is None:
                current.detail_report_id = detail.id
            unchanged += 1
            continue
        session.add(SectorPathHistoryEntry(
            sector_key=sector_key,
            sector_name=sector.sector_name,
            path_report_date=path_date,
            path_status=status,
            source_report_id=source.id,
            detail_report_id=detail.id if detail else None,
            market_as_of_date=market_date,
            frozen_daily_pct_change=daily_pct,
            market_data_status=market_status,
            source_pdf_sha256=source.file.sha256 if source.file else "",
            template_version=source.template_version,
            source_kind="newer_formal_history_baseline",
        ))
        inserted += 1

    difference_count = len(differences)
    status = "initialized" if not existing else "appended" if inserted else "verified_same"
    if superseded:
        status = "canonical_reconciled"
    if difference_count:
        status = "needs_attention" if difference_count <= 10 else "blocking_difference"
    audit = session.scalar(select(PathHistoryImport).where(PathHistoryImport.source_report_id == report.id))
    if audit is None:
        session.add(PathHistoryImport(
            source_report_id=report.id,
            source_pdf_sha256=report.file.sha256 if report.file else "",
            template_version=report.template_version,
            date_count=len(resolved_dates),
            sector_count=len(rows),
            inserted_count=inserted,
            unchanged_count=unchanged,
            difference_count=difference_count,
            status=status,
            differences_json=json.dumps([*differences, *superseded], ensure_ascii=False),
        ))
    else:
        audit.inserted_count = inserted
        audit.unchanged_count = unchanged
        audit.difference_count = difference_count
        audit.status = status
        audit.differences_json = json.dumps([*differences, *superseded], ensure_ascii=False)
    if commit:
        session.commit()
    return PathHistorySyncResult(len(resolved_dates), len(rows), inserted, unchanged, difference_count, status, [*differences, *superseded])


def ensure_latest_path_history(session: Session, through: date | None = None) -> PathHistorySyncResult | None:
    query = select(Report).where(Report.status == "published", Report.is_current.is_(True))
    if through is not None:
        query = query.where(Report.report_date <= through)
    reports = list(session.scalars(query.order_by(desc(Report.report_date))))
    source = next((item for item in reports if (json.loads(item.interpretation_meta_json or "{}").get("pdf_history_matrix") or {}).get("quality_status") == "verified_structure"), None)
    return sync_path_history(session, source) if source else None


def audit_frozen_path_history(session: Session, report: Report) -> list[dict[str, Any]]:
    """Keep alternative SHA files for the same report date fail-closed.

    Cross-date differences are intentional report-history reconciliation. A
    same-date alternative has no newer-date authority and must be reviewed.
    """
    if not report.report_date or not report.file:
        return []
    conflicts: list[dict[str, Any]] = []
    for existing in session.scalars(select(Report).where(
        Report.report_date == report.report_date,
        Report.status == "published",
        Report.is_current.is_(True),
        Report.id != report.id,
    )):
        if existing.file and existing.file.sha256 != report.file.sha256:
            conflicts.append({
                "reason": "same_date_different_sha",
                "report_date": report.report_date.isoformat(),
                "existing_report_id": existing.id,
                "existing_sha256": existing.file.sha256,
                "incoming_report_id": report.id,
                "incoming_sha256": report.file.sha256,
            })
    return conflicts
