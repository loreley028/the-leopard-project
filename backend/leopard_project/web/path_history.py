from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from leopard_project.config import load_seed_bundle
from leopard_project.report_registry import ReportObject, load_report_registry
from leopard_project.sector_lifecycle import is_active_report_object_on

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


def _matrix_report_rows(matrix: dict[str, Any], objects: dict[str, ReportObject]) -> dict[str, dict[str, Any]]:
    """Lift a parsed matrix into the independent Report registry.

    Legacy PDFs provide the configured 66 market-topic rows.  V2.9 additionally
    exposes native split rows in ``display_rows``.  Both forms are retained as
    Report facts; only the former may have a market helper mapping.
    """
    rows: dict[str, dict[str, Any]] = {}
    for row in matrix.get("rows") or []:
        key = row.get("sector_key")
        if key in objects:
            rows[str(key)] = row
    for row in matrix.get("display_rows") or []:
        key = row.get("report_sector_key")
        if key in objects and key not in rows:
            rows[str(key)] = {
                "sector_key": key,
                "sector_name": objects[str(key)].sector_name,
                "statuses": list(row.get("statuses") or []),
                "source_page": row.get("source_page"),
                "source_display_rows": [row.get("display_name")],
            }
    return rows


@dataclass(frozen=True)
class PathHistorySyncResult:
    date_count: int
    sector_count: int
    inserted_count: int
    unchanged_count: int
    difference_count: int
    status: str
    differences: list[dict[str, Any]]


def sync_path_history(
    session: Session,
    report: Report,
    *,
    commit: bool = True,
    allow_same_source_reconciliation: bool = False,
) -> PathHistorySyncResult:
    """Reconcile the derived canonical ledger from formal PDF matrices.

    A matrix stored on a report is an immutable report-local snapshot.  A
    report date's own formal PDF is always the primary source for that day's
    marker.  Later complete matrices are useful continuity evidence, but they
    never silently rewrite an earlier report fact.  The sole exception is an
    explicit, structured history correction recorded by a later formal PDF.

    Resolving every published source on each sync keeps the result import-order
    independent while preserving the separation between report facts and
    objective market facts.
    """
    metadata = json.loads(report.interpretation_meta_json or "{}")
    matrix = metadata.get("pdf_history_matrix") or {}
    raw_dates = list(matrix.get("dates") or [])
    rows = list(matrix.get("rows") or [])
    report_objects = {item.sector_key: item for item in load_report_registry()}
    base_keys = {item.sector_key for item in load_seed_bundle().sectors}
    local_rows = _matrix_report_rows(matrix, report_objects)
    if not report.report_date or not base_keys.issubset(local_rows) or not raw_dates:
        return PathHistorySyncResult(len(raw_dates), len(rows), 0, 0, 0, "not_reliable", [])
    if any(len(item.get("statuses") or []) != len(raw_dates) for item in local_rows.values()):
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
    canonical_cells: dict[tuple[str, date], tuple[str, Report, str]] = {}
    source_cells: list[tuple[str, date, str, Report]] = []
    for source in authority_reports:
        source_metadata = json.loads(source.interpretation_meta_json or "{}")
        source_matrix = source_metadata.get("pdf_history_matrix") or {}
        source_dates = list(source_matrix.get("dates") or [])
        source_rows = list(source_matrix.get("rows") or [])
        if (
            not source.report_date
            or (source_matrix.get("quality_status") != "verified_structure" and source.id != report.id)
            or not source_dates
        ):
            continue
        source_by_sector = _matrix_report_rows(source_matrix, report_objects)
        if not base_keys.issubset(source_by_sector):
            continue
        source_resolved_dates = matrix_dates(source.report_date, source_dates)
        if any(len(item.get("statuses") or []) != len(source_resolved_dates) for item in source_rows):
            continue
        for sector_key, source_row in source_by_sector.items():
            for path_date, status in zip(source_resolved_dates, source_row.get("statuses") or []):
                if (
                    status != "blank"
                    and status in valid_statuses
                    and is_active_report_object_on(sector_key, path_date)
                ):
                    source_cells.append((sector_key, path_date, status, source))
    # First source wins for a date whose own PDF is absent.  A formal PDF for
    # that exact report date always takes precedence.  This means the order in
    # which historical files happen to be uploaded cannot affect report facts.
    for sector_key, path_date, status, source in source_cells:
        key = (sector_key, path_date)
        existing = canonical_cells.get(key)
        source_kind = "report_local_pdf" if source.report_date == path_date else "historical_consistency_reference"
        if existing is None or (source.report_date == path_date and existing[1].report_date != path_date):
            canonical_cells[key] = (status, source, source_kind)

    # A correction is intentionally opt-in.  Parsers do not infer it from a
    # later matrix mismatch; publishers must carry structured correction
    # evidence, which makes each revised historical fact auditable.
    corrections: list[tuple[str, date, str, Report]] = []
    for source in authority_reports:
        source_metadata = json.loads(source.interpretation_meta_json or "{}")
        for correction in source_metadata.get("history_corrections", []):
            try:
                sector_key = str(correction["sector_key"])
                path_date = date.fromisoformat(str(correction["report_date"]))
                status = str(correction["path_status"])
            except (KeyError, TypeError, ValueError):
                continue
            if (
                sector_key in report_objects
                and status in valid_statuses
                and correction.get("source_evidence")
                and is_active_report_object_on(sector_key, path_date)
            ):
                corrections.append((sector_key, path_date, status, source))
    for sector_key, path_date, status, source in corrections:
        canonical_cells[(sector_key, path_date)] = (status, source, "explicit_history_correction")
    if not canonical_cells:
        return PathHistorySyncResult(len(resolved_dates), len(rows), 0, 0, 0, "not_reliable", [])

    # Preserve an explicit audit trail even when an earlier snapshot never
    # became the ledger value (for example, importing an older PDF after an
    # already-published newer baseline).  The audit is report-fact-only.
    historical_discrepancies = [
        {
            "report_date": path_date.isoformat(),
            "sector_key": sector_key,
            "sector_name": report_objects[sector_key].sector_name,
            "old_value": status,
            "old_source_report_id": source.id,
            "old_source_pdf_sha256": source.file.sha256 if source.file else "",
            "reference_value": status,
            "canonical_source_report_id": canonical_source.id,
            "canonical_source_pdf_sha256": canonical_source.file.sha256 if canonical_source.file else "",
            "resolution_reason": "historical_consistency_reference_only",
        }
        for sector_key, path_date, status, source in source_cells
        for canonical_status, canonical_source, canonical_kind in [canonical_cells[(sector_key, path_date)]]
        if source.id != canonical_source.id and status != canonical_status
    ]

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
    for (sector_key, path_date), (status, source, source_kind) in sorted(canonical_cells.items(), key=lambda item: (item[0][1], item[0][0])):
        sector = report_objects[sector_key]
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
            bar=market_rows.get((sector.market_sector_key, requested_market_date)) if sector.market_sector_key else None,
        )
        if current is not None:
            if current.path_status != status:
                if current.source_report_id == source.id:
                    if not allow_same_source_reconciliation:
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
                        "resolution_reason": "same_source_authoritative_pdf_reparse",
                    })
                    current.path_status = status
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
                    "resolution_reason": "report_local_fact_reconciled",
                })
                current.path_status = status
            current.source_report_id = source.id
            current.source_pdf_sha256 = source.file.sha256 if source.file else ""
            current.template_version = source.template_version
            current.source_kind = source_kind
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
            source_kind=source_kind,
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
            differences_json=json.dumps([*differences, *historical_discrepancies, *superseded], ensure_ascii=False),
        ))
    else:
        audit.inserted_count = inserted
        audit.unchanged_count = unchanged
        audit.difference_count = difference_count
        audit.status = status
        audit.differences_json = json.dumps([*differences, *historical_discrepancies, *superseded], ensure_ascii=False)
    if commit:
        session.commit()
    return PathHistorySyncResult(
        len(resolved_dates), len(rows), inserted, unchanged, difference_count, status,
        [*differences, *historical_discrepancies, *superseded],
    )


def ensure_latest_path_history(session: Session, through: date | None = None) -> PathHistorySyncResult | None:
    query = select(Report).where(Report.status == "published", Report.is_current.is_(True))
    if through is not None:
        query = query.where(Report.report_date <= through)
    reports = list(session.scalars(query.order_by(desc(Report.report_date))))
    source = next((item for item in reports if (json.loads(item.interpretation_meta_json or "{}").get("pdf_history_matrix") or {}).get("quality_status") == "verified_structure"), None)
    return sync_path_history(session, source) if source else None


def audit_frozen_path_history(session: Session, report: Report) -> list[dict[str, Any]]:
    """Keep alternative SHA files for the same report date fail-closed.

    Cross-date differences are continuity evidence only. A same-date
    alternative has no authority and must be reviewed fail-closed.
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
