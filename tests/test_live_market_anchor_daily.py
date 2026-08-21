from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from leopard_project.live_market_anchor_daily import (
    LiveMarketAnchorDailyCaptureError,
    capture_live_market_anchor_daily,
    defense_line_trend,
    next_controlled_cn_a_trading_day,
    recent_defense_line_validations,
)
from leopard_project.providers.tencent_standard_quote import TencentQuoteBatch, TencentQuoteErrorCode
from leopard_project.trading_calendar import CalendarEvaluation, CalendarStatus
from leopard_project.web.database import create_session_factory
from leopard_project.web.models import LiveMarketAnchorDaily, Report, ReportStatus


SHANGHAI = ZoneInfo("Asia/Shanghai")
DAY = date(2026, 8, 11)
NOW = datetime(2026, 8, 11, 15, 20, tzinfo=SHANGHAI)


class FakeProvider:
    def __init__(self, quote: object | None, failure: TencentQuoteErrorCode | None = None) -> None:
        self.quote, self.failure, self.calls = quote, failure, []

    def fetch_batch(self, symbols, *, allow_network: bool = False):
        assert allow_network is True
        self.calls.append(tuple(symbols))
        return TencentQuoteBatch(
            () if self.quote is None else (self.quote,),
            {} if self.failure is None else {"sh000001": self.failure},
            1,
        )


def quote(*, current: object = "3851.20", timestamp: datetime = NOW, high: object = "3860", low: object = "3830"):
    return SimpleNamespace(
        requested_symbol="sh000001", current=current, pre_close="3842.12", pct_change="0.24",
        quote_datetime=timestamp, high=high, low=low,
    )


def sessions(tmp_path):
    return create_session_factory(f"sqlite:///{tmp_path / 'anchor.sqlite3'}")


def capture(session, provider: FakeProvider, *, now: datetime = NOW):
    return capture_live_market_anchor_daily(
        session, target_trading_date=DAY, provider=provider, now=lambda: now, enable_provider=True,
    )


def report(report_date: date, *, market_path: str = "攻防线3844点；站上3844点观察宽度。", core_view: str = "") -> Report:
    return Report(
        title=f"{report_date.isoformat()} report", report_date=report_date, created_by="test",
        status=ReportStatus.PUBLISHED.value, is_current=True, market_path=market_path, core_view=core_view,
    )


def daily(day: date, close: str) -> LiveMarketAnchorDaily:
    return LiveMarketAnchorDaily(
        symbol="sh000001", trading_date=day, close=Decimal(close), pre_close=Decimal("3840"), pct_change=Decimal("0.1"),
        high=Decimal("3900"), low=Decimal("3800"), quote_datetime=datetime.combine(day, datetime.min.time(), SHANGHAI),
        fetched_at=NOW, source="test",
    )


def test_schema_is_separate_from_proxy_daily_and_rejects_duplicate_day(tmp_path) -> None:
    factory = sessions(tmp_path)
    assert {"live_market_anchor_daily", "security_proxy_daily"} <= set(inspect(factory.kw["bind"]).get_table_names())
    with factory() as session:
        session.add(daily(DAY, "3850")); session.commit()
        session.add(daily(DAY, "3860"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_capture_requires_explicit_enablement_and_post_close_window(tmp_path) -> None:
    factory = sessions(tmp_path); provider = FakeProvider(quote())
    with factory() as session, pytest.raises(PermissionError):
        capture_live_market_anchor_daily(session, target_trading_date=DAY, provider=provider, now=lambda: NOW)
    with factory() as session, pytest.raises(LiveMarketAnchorDailyCaptureError, match="market_not_closed"):
        capture(session, provider, now=datetime(2026, 8, 11, 15, 9, tzinfo=SHANGHAI))
    assert provider.calls == []


def test_capture_rejects_calendar_failure_before_provider(monkeypatch, tmp_path) -> None:
    import leopard_project.live_market_anchor_daily as module
    monkeypatch.setattr(module, "evaluate_cn_a_day", lambda day: CalendarEvaluation(day, CalendarStatus.UNAVAILABLE, None, None, None))
    factory = sessions(tmp_path); provider = FakeProvider(quote())
    with factory() as session, pytest.raises(LiveMarketAnchorDailyCaptureError, match="calendar_unavailable"):
        capture(session, provider)
    assert provider.calls == []


def test_capture_uses_one_exact_symbol_and_persists_completed_quote_only(tmp_path) -> None:
    factory = sessions(tmp_path); provider = FakeProvider(quote())
    with factory() as session:
        summary = capture(session, provider)
        row = session.scalar(select(LiveMarketAnchorDaily))
        assert summary.inserted_count == 1 and summary.provider_request_count == 1 and provider.calls == [("sh000001",)]
        assert row is not None and row.trading_date == DAY and Decimal(str(row.close)) == Decimal("3851.20")
        assert row.source == "tencent_standard_security_quote" and row.quote_datetime.date() == DAY


@pytest.mark.parametrize("kwargs, error", [
    ({"current": "0"}, "invalid_quote_fields"),
    ({"timestamp": datetime(2026, 8, 10, 15, 20, tzinfo=SHANGHAI)}, "quote_date_mismatch"),
    ({"timestamp": datetime(2026, 8, 11, 15, 20)}, "naive_quote_datetime"),
])
def test_invalid_quote_never_writes(kwargs, error, tmp_path) -> None:
    factory = sessions(tmp_path)
    with factory() as session:
        summary = capture(session, FakeProvider(quote(**kwargs)))
        assert summary.inserted_count == 0 and summary.error_code == error
        assert session.query(LiveMarketAnchorDaily).count() == 0


def test_existing_daily_row_is_never_overwritten_or_refetched(tmp_path) -> None:
    factory = sessions(tmp_path); provider = FakeProvider(quote(current="3900"))
    with factory() as session:
        session.add(daily(DAY, "3850")); session.commit()
        summary = capture(session, provider)
        preserved = session.scalar(select(LiveMarketAnchorDaily))
        assert summary.already_exists_count == 1 and summary.provider_request_count == 0 and provider.calls == []
        assert Decimal(str(preserved.close)) == Decimal("3850")


def test_next_controlled_day_uses_calendar_for_normal_friday_and_holiday() -> None:
    assert next_controlled_cn_a_trading_day(date(2026, 8, 10)) == date(2026, 8, 11)
    assert next_controlled_cn_a_trading_day(date(2026, 8, 7)) == date(2026, 8, 10)
    assert next_controlled_cn_a_trading_day(date(2026, 9, 30)) == date(2026, 10, 8)


def test_validation_matches_previous_report_to_next_actual_close_and_never_same_day(tmp_path) -> None:
    factory = sessions(tmp_path)
    with factory() as session:
        session.add(report(date(2026, 8, 10)))
        session.add(daily(date(2026, 8, 10), "3900"))
        session.add(daily(date(2026, 8, 11), "3851"))
        session.commit()
        rows = recent_defense_line_validations(session)
    assert len(rows) == 1
    assert rows[0]["trading_date"] == "2026-08-11" and rows[0]["source_report_date"] == "2026-08-10"
    assert rows[0]["index_close"] == 3851.0 and rows[0]["distance_points"] == 7.0
    assert rows[0]["close_position"] == "close_above_defense_line"


def test_validation_uses_parser_verified_primary_line_when_narrative_has_two_levels(tmp_path) -> None:
    factory = sessions(tmp_path)
    with factory() as session:
        item = report(date(2026, 8, 10), market_path="核心线由3847.09上移至3864.27")
        item.interpretation_meta_json = '{"defense_lines":{"primary_defense_line":3864.27}}'
        session.add(item)
        session.add(daily(date(2026, 8, 11), "3865"))
        session.commit()
        rows = recent_defense_line_validations(session)
    assert rows[0]["defense_line_value"] == 3864.27


def test_validation_skips_missing_defense_missing_close_and_uses_newest_report_for_one_trade_day(tmp_path) -> None:
    factory = sessions(tmp_path)
    with factory() as session:
        session.add(report(date(2026, 8, 7), market_path="无明确点位"))
        session.add(report(date(2026, 8, 8), market_path="攻防线3800点"))
        session.add(report(date(2026, 8, 9), market_path="攻防线3844点"))
        session.add(daily(date(2026, 8, 10), "3844"))
        session.commit()
        rows = recent_defense_line_validations(session)
    assert len(rows) == 1 and rows[0]["source_report_date"] == "2026-08-09"
    assert rows[0]["close_position"] == "close_at_defense_line" and rows[0]["distance_pct"] == 0.0


def test_validation_returns_latest_ten_in_descending_trade_day_order(tmp_path, monkeypatch) -> None:
    import leopard_project.live_market_anchor_daily as module
    factory = sessions(tmp_path)
    start = date(2026, 1, 1)
    monkeypatch.setattr(module, "next_controlled_cn_a_trading_day", lambda value: value)
    with factory() as session:
        for offset in range(12):
            day = date.fromordinal(start.toordinal() + offset)
            session.add(report(day))
            session.add(daily(day, str(3844 + offset)))
        session.commit()
        rows = recent_defense_line_validations(session)
    assert len(rows) == 10
    assert [item["trading_date"] for item in rows] == sorted((item["trading_date"] for item in rows), reverse=True)
    assert rows[0]["trading_date"] == "2026-01-12" and rows[-1]["trading_date"] == "2026-01-03"


def test_defense_trend_uses_completed_axis_and_the_same_verification_ledger_as_the_table(tmp_path, monkeypatch) -> None:
    import leopard_project.live_market_anchor_daily as module
    factory = sessions(tmp_path)
    start = date(2026, 1, 1)
    monkeypatch.setattr(module, "next_controlled_cn_a_trading_day", lambda value: value)
    with factory() as session:
        session.add(report(start, market_path="攻防线3800点"))
        for offset in range(4):
            day = date.fromordinal(start.toordinal() + offset)
            session.add(daily(day, str(3800 + offset)))
        session.commit()
        rows = defense_line_trend(session, limit=4)
        table_rows = recent_defense_line_validations(session, limit=10)
    assert [item["trading_date"] for item in rows] == ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]
    assert all(item["available"] is True for item in rows)
    assert [item["distance_points"] for item in rows] == [0.0, 1.0, 2.0, 3.0]
    assert [item["trading_date"] for item in table_rows] == [
        "2026-01-04", "2026-01-03", "2026-01-02", "2026-01-01",
    ]
    assert all(item["data_mode"] == "completed_eod" for item in rows)


def test_defense_trend_keeps_pre_source_completed_days_unavailable(tmp_path, monkeypatch) -> None:
    import leopard_project.live_market_anchor_daily as module
    factory = sessions(tmp_path)
    start = date(2026, 1, 1)
    monkeypatch.setattr(module, "next_controlled_cn_a_trading_day", lambda value: value)
    with factory() as session:
        session.add(report(date(2026, 1, 3), market_path="攻防线3800点"))
        for offset in range(4):
            day = date.fromordinal(start.toordinal() + offset)
            session.add(daily(day, str(3800 + offset)))
        session.commit()
        rows = defense_line_trend(session, limit=4)
    assert [item["available"] for item in rows] == [False, False, True, True]
    assert [item["trading_date"] for item in rows if not item["available"]] == ["2026-01-01", "2026-01-02"]
    assert all(item["defense_line_value"] is None for item in rows[:2])


def test_validation_is_descriptive_only_without_prediction_or_effectiveness_score(tmp_path) -> None:
    factory = sessions(tmp_path)
    with factory() as session:
        assert recent_defense_line_validations(session) == []
    assert not any("score" in name or "success" in name or "prediction" in name for name in dir(__import__("leopard_project.live_market_anchor_daily", fromlist=["*"])))
