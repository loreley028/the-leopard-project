from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from leopard_project.web.database import create_session_factory
from leopard_project.web.models import Report, SectorDailyBar, SectorPathHistoryEntry
from scripts.repair_path_history_market_fields import apply_repairs, planned_repairs, repair_summary, write_csv


def _report(identifier: str, report_date: date, market_date: date | None = None) -> Report:
    return Report(
        id=identifier, title=identifier, report_date=report_date, candidate_report_date=report_date,
        report_date_confirmed=True, market_as_of_date=market_date, market_as_of_date_confirmed=market_date is not None,
        detected_report_date=report_date, report_date_source="test", report_date_confidence="high",
        status="published", interpretation_status="ready", core_view="", market_path="", risk_warning="",
        focus_sectors_json="[]", created_by="test",
    )


def _bar(sector_key: str, day: date, pct: str) -> SectorDailyBar:
    return SectorDailyBar(
        sector_key=sector_key, trade_date=day, close=Decimal("100"), pre_close=Decimal("99"),
        daily_pct_change=Decimal(pct), volume=Decimal("1"), amount=None, eod_status="complete_eod",
        data_source="test", provider_role="research_provider", fetched_at=datetime.now(timezone.utc), source_response_hash="a" * 64,
    )


def _entry(identifier: str, day: date, *, detail_report_id: str | None = None) -> SectorPathHistoryEntry:
    return SectorPathHistoryEntry(
        id=identifier, sector_key="semiconductor", sector_name="半导体", path_report_date=day,
        path_status="watch", source_report_id="source", detail_report_id=detail_report_id,
        market_as_of_date=date(2026, 7, 28), frozen_daily_pct_change=Decimal("9.9"),
        market_data_status="attached", source_pdf_sha256="b" * 64,
    )


def test_repair_dry_run_is_non_mutating_and_apply_uses_exact_date_only(tmp_path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'repair.sqlite3'}")
    with sessions() as session:
        session.add_all([
            _report("detail", date(2026, 8, 10), date(2026, 8, 7)),
            _entry("exact", date(2026, 8, 10), detail_report_id="detail"),
            _entry("missing", date(2026, 8, 11)),
            _bar("semiconductor", date(2026, 8, 7), "1.25"),
            # This tempting earlier bar must not backfill the 8/11 entry.
            _bar("semiconductor", date(2026, 8, 10), "2.5"),
        ])
        session.commit()
        rows = planned_repairs(session)
        assert {row.entry_id for row in rows} == {"exact", "missing"}
        exact = next(row for row in rows if row.entry_id == "exact")
        missing = next(row for row in rows if row.entry_id == "missing")
        assert exact.after_market_as_of_date == "2026-08-07"
        assert exact.after_frozen_daily_pct_change == 1.25
        assert missing.after_market_as_of_date is None and missing.after_market_data_status == "unavailable"
        assert session.get(SectorPathHistoryEntry, "missing").market_as_of_date == date(2026, 7, 28)
        output = tmp_path / "repair.csv"
        write_csv(output, rows)
        assert output.read_text(encoding="utf-8").splitlines()[0].startswith("entry_id,")
        assert repair_summary(session, rows) == {
            "total_rows": 2,
            "unchanged": 0,
            "corrected_exact_date": 1,
            "cleared_invalid_fallback": 1,
            "already_unavailable": 0,
            "conflicts_errors": 0,
            "pending": 2,
        }
        apply_repairs(session, rows)
        assert session.get(SectorPathHistoryEntry, "exact").market_as_of_date == date(2026, 8, 7)
        repaired_missing = session.get(SectorPathHistoryEntry, "missing")
        assert repaired_missing.market_as_of_date is None
        assert repaired_missing.frozen_daily_pct_change is None
        assert repaired_missing.market_data_status == "unavailable"
        assert planned_repairs(session) == []
        assert repair_summary(session, []) == {
            "total_rows": 2,
            "unchanged": 2,
            "corrected_exact_date": 0,
            "cleared_invalid_fallback": 0,
            "already_unavailable": 1,
            "conflicts_errors": 0,
            "pending": 0,
        }
