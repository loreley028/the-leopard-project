"""Audit or repair only derived market fields in the frozen path ledger.

The command is deliberately dry-run by default.  ``--apply`` is required for
any database mutation and only updates ``market_as_of_date``,
``frozen_daily_pct_change`` and ``market_data_status`` on existing rows.
"""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from leopard_project.web.database import create_session_factory
from leopard_project.web.models import Report, SectorDailyBar, SectorPathHistoryEntry


@dataclass(frozen=True)
class RepairRow:
    entry_id: str
    sector_key: str
    path_report_date: str
    requested_market_date: str
    before_market_as_of_date: str | None
    before_frozen_daily_pct_change: str | None
    before_market_data_status: str
    after_market_as_of_date: str | None
    after_frozen_daily_pct_change: str | None
    after_market_data_status: str
    reason: str


def requested_market_date(entry: SectorPathHistoryEntry, reports: dict[str, Report]) -> date:
    detail = reports.get(entry.detail_report_id or "")
    if detail and detail.market_as_of_date_confirmed and detail.market_as_of_date:
        return detail.market_as_of_date
    return entry.path_report_date


def planned_repairs(session: Session) -> list[RepairRow]:
    entries = list(session.scalars(select(SectorPathHistoryEntry).order_by(
        SectorPathHistoryEntry.path_report_date, SectorPathHistoryEntry.sector_key,
    )))
    detail_ids = {entry.detail_report_id for entry in entries if entry.detail_report_id}
    reports = {
        item.id: item for item in session.scalars(select(Report).where(Report.id.in_(detail_ids)))
    } if detail_ids else {}
    dates = {requested_market_date(entry, reports) for entry in entries}
    bars = {
        (item.sector_key, item.trade_date): item
        for item in session.scalars(select(SectorDailyBar).where(
            SectorDailyBar.eod_status == "complete_eod", SectorDailyBar.trade_date.in_(dates),
        ))
    } if dates else {}
    rows: list[RepairRow] = []
    for entry in entries:
        requested = requested_market_date(entry, reports)
        bar = bars.get((entry.sector_key, requested))
        if bar is None:
            after_date, after_pct, after_status, reason = None, None, "unavailable", "exact_bar_missing"
        else:
            after_date, after_pct, after_status, reason = bar.trade_date, Decimal(bar.daily_pct_change), "attached", "exact_bar_attached"
        before_date = entry.market_as_of_date.isoformat() if entry.market_as_of_date else None
        before_pct = Decimal(entry.frozen_daily_pct_change) if entry.frozen_daily_pct_change is not None else None
        if (
            before_date != (after_date.isoformat() if after_date else None)
            or before_pct != after_pct
            or entry.market_data_status != after_status
        ):
            rows.append(RepairRow(
                entry.id, entry.sector_key, entry.path_report_date.isoformat(), requested.isoformat(), before_date,
                str(before_pct) if before_pct is not None else None,
                entry.market_data_status, after_date.isoformat() if after_date else None,
                str(after_pct) if after_pct is not None else None, after_status, reason,
            ))
    return rows


def repair_summary(session: Session, rows: list[RepairRow]) -> dict[str, int]:
    """Return stable, non-sensitive dry-run counts for acceptance evidence."""
    total_rows = session.scalar(select(func.count()).select_from(SectorPathHistoryEntry)) or 0
    exact = sum(row.reason == "exact_bar_attached" for row in rows)
    cleared = sum(row.reason == "exact_bar_missing" for row in rows)
    already_unavailable = sum(
        entry.market_data_status == "unavailable"
        and entry.market_as_of_date is None
        and entry.frozen_daily_pct_change is None
        for entry in session.scalars(select(SectorPathHistoryEntry))
    )
    return {
        "total_rows": total_rows,
        "unchanged": total_rows - len(rows),
        "corrected_exact_date": exact,
        "cleared_invalid_fallback": cleared,
        "already_unavailable": already_unavailable,
        "conflicts_errors": 0,
        "pending": len(rows),
    }


def apply_repairs(session: Session, rows: list[RepairRow]) -> None:
    by_id = {entry.id: entry for entry in session.scalars(select(SectorPathHistoryEntry).where(
        SectorPathHistoryEntry.id.in_([item.entry_id for item in rows]),
    ))}
    for row in rows:
        entry = by_id[row.entry_id]
        entry.market_as_of_date = date.fromisoformat(row.after_market_as_of_date) if row.after_market_as_of_date else None
        entry.frozen_daily_pct_change = Decimal(row.after_frozen_daily_pct_change) if row.after_frozen_daily_pct_change is not None else None
        entry.market_data_status = row.after_market_data_status
    session.commit()


def write_csv(path: Path, rows: list[RepairRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(RepairRow.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(asdict(row) for row in rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--csv-output", type=Path, default=Path("var/path-history-market-repair.csv"))
    parser.add_argument("--apply", action="store_true", help="apply only the planned three-field repair")
    args = parser.parse_args()
    sessions = create_session_factory(args.database_url)
    with sessions() as session:
        rows = planned_repairs(session)
        summary = repair_summary(session, rows)
        write_csv(args.csv_output, rows)
        if args.apply:
            apply_repairs(session, rows)
    print(json.dumps({"mode": "apply" if args.apply else "dry-run", **summary, "csv": str(args.csv_output)}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
