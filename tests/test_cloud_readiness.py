from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from leopard_project.config import load_seed_bundle
from leopard_project.market_paths import load_market_path_registry
from leopard_project.providers.capabilities import provider_capability_summary
from leopard_project.models import DailyBar, DataStatus, LiquidityStatus, Market
from leopard_project.trading_calendar import CalendarRuleSet, CalendarStatus, evaluate_cn_a_day
from leopard_project.web.database import create_session_factory
from leopard_project.web.intraday import (
    IntradayRefreshCoordinator,
    market_phase,
    market_phase_detail,
    market_session,
    recover_stale_refresh_sessions,
)
from leopard_project.web.market_automation import EodBackfillCoordinator
from leopard_project.web.market_ingestion import refresh_real_market
from leopard_project.web.models import IntradayRefreshSession, MarketAutomationControl, MarketRefreshItem, SectorDailyBar
from leopard_project.web.write_coordination import SQLiteWriteLockExhausted, coordinated_write


def bar(symbol: str, day: date) -> DailyBar:
    return DailyBar(
        symbol=symbol, symbol_name=symbol, market=Market.CN_A, trade_date=day,
        open=Decimal("100"), high=Decimal("103"), low=Decimal("99"),
        close=Decimal("102"), pre_close=Decimal("100"), change=Decimal("2"),
        pct_change=Decimal("2"), volume=Decimal("1200"), amount=None,
        turnover_rate=None, liquidity_status=LiquidityStatus.PARTIAL,
        provider="controlled_test", fetched_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        source_payload_hash=(symbol * 64)[:64], data_status=DataStatus.NORMAL,
    )


def stored(sector_key: str, day: date) -> SectorDailyBar:
    return SectorDailyBar(
        sector_key=sector_key, trade_date=day, open=100, high=103, low=99,
        close=102, pre_close=100, daily_pct_change=2, volume=1200, amount=None,
        turnover_rate=None, liquidity_status="partial", eod_status="complete_eod",
        data_source="controlled_test", provider_role="diagnostic_provider",
        fetched_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        source_response_hash=(sector_key * 64)[:64],
    )


def test_annual_calendar_rules_and_unknown_states(tmp_path: Path) -> None:
    rules = CalendarRuleSet.from_file()
    expected = {
        date(2026, 7, 29): CalendarStatus.TRADING_DAY,
        date(2026, 7, 30): CalendarStatus.TRADING_DAY,
        date(2026, 7, 31): CalendarStatus.TRADING_DAY,
        date(2026, 8, 1): CalendarStatus.CONFIRMED_NON_TRADING_DAY,
        date(2026, 8, 2): CalendarStatus.CONFIRMED_NON_TRADING_DAY,
        date(2026, 9, 25): CalendarStatus.CONFIRMED_NON_TRADING_DAY,
        date(2026, 9, 26): CalendarStatus.CONFIRMED_NON_TRADING_DAY,
        date(2026, 9, 27): CalendarStatus.CONFIRMED_NON_TRADING_DAY,
        date(2026, 9, 28): CalendarStatus.TRADING_DAY,
        date(2026, 10, 1): CalendarStatus.CONFIRMED_NON_TRADING_DAY,
        date(2026, 10, 7): CalendarStatus.CONFIRMED_NON_TRADING_DAY,
        date(2026, 10, 8): CalendarStatus.TRADING_DAY,
        date(2026, 6, 19): CalendarStatus.CONFIRMED_NON_TRADING_DAY,
    }
    for day, status in expected.items():
        assert rules.evaluate(day).status == status
    assert rules.evaluate(date(2027, 1, 1)).status == CalendarStatus.OUT_OF_RANGE
    missing = evaluate_cn_a_day(date(2026, 7, 30), tmp_path / "missing.json")
    assert missing.status == CalendarStatus.UNAVAILABLE and missing.reason == "calendar_source_unavailable"
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("{}", encoding="utf-8")
    invalid = evaluate_cn_a_day(date(2026, 7, 30), invalid_path)
    assert invalid.status == CalendarStatus.UNAVAILABLE and invalid.reason == "calendar_rule_invalid"
    assert rules.metadata(date(2026, 12, 5))["calendar_warning"] == "calendar_coverage_expiring"


def test_scheduler_distinguishes_calendar_errors_from_holidays() -> None:
    assert market_phase(datetime(2026, 7, 30, 2, tzinfo=timezone.utc)) == "intraday_open"
    assert market_session(datetime(2026, 7, 30, 2, tzinfo=timezone.utc)) == "open"
    assert market_phase_detail(datetime(2026, 8, 1, 2, tzinfo=timezone.utc)) == "non_trading_day"
    assert market_phase(datetime(2027, 1, 4, 2, tzinfo=timezone.utc)) == "calendar_error"
    assert market_phase_detail(datetime(2027, 1, 4, 2, tzinfo=timezone.utc)) == "calendar_out_of_range"
    assert market_session(datetime(2027, 1, 4, 2, tzinfo=timezone.utc)) == "calendar_error"


def test_nineteen_stale_sessions_recover_once_and_live_lease_survives(tmp_path: Path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'sessions.sqlite3'}")
    now = datetime(2026, 7, 30, 1, 0, tzinfo=timezone.utc)
    with sessions() as session:
        session.add_all(IntradayRefreshSession(
            status="running", started_by="old", started_at=now - timedelta(days=1),
            refresh_interval_minutes=5, provider_role="research_provider",
        ) for _ in range(19))
        session.add(IntradayRefreshSession(
            status="running", started_by="current", started_at=now,
            heartbeat_at=now, lease_expires_at=now + timedelta(minutes=10),
            owner_instance_id="live", refresh_interval_minutes=5,
            provider_role="research_provider",
        ))
        session.commit()
    assert recover_stale_refresh_sessions(sessions, now) == 19
    assert recover_stale_refresh_sessions(sessions, now) == 0
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(IntradayRefreshSession).where(IntradayRefreshSession.status == "interrupted")) == 19
        live = session.scalar(select(IntradayRefreshSession).where(IntradayRefreshSession.owner_instance_id == "live"))
        assert live and live.status == "running"
        assert all(row.finished_at and row.terminal_reason for row in session.scalars(select(IntradayRefreshSession).where(IntradayRefreshSession.status == "interrupted")))


def test_duplicate_scheduler_lease_is_prevented(tmp_path: Path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'lease.sqlite3'}")
    now = datetime(2026, 7, 30, 4, 0, tzinfo=timezone.utc)
    first = IntradayRefreshCoordinator(sessions, now=lambda: now, fetcher=lambda key, _mapping, _at: bar(key, date(2026, 7, 30)))
    second = IntradayRefreshCoordinator(sessions, now=lambda: now, fetcher=lambda key, _mapping, _at: bar(key, date(2026, 7, 30)))
    first.start("system_auto_resume")
    result = second.start("system_auto_resume")
    assert result["start_result"] == "duplicate_scheduler_prevented"
    first.shutdown()


def test_sqlite_wal_is_idempotent_and_backup_restores(tmp_path: Path) -> None:
    path = tmp_path / "wal.sqlite3"
    sessions = create_session_factory(f"sqlite:///{path}")
    create_session_factory(f"sqlite:///{path}")
    with sessions() as session:
        session.add(MarketAutomationControl(control_key="intraday", admin_paused=False))
        session.commit()
    source = sqlite3.connect(path)
    assert source.execute("pragma journal_mode").fetchone()[0] == "wal"
    with sessions() as session:
        assert session.connection().exec_driver_sql("pragma busy_timeout").scalar_one() == 10000
    restored = sqlite3.connect(tmp_path / "restored.sqlite3")
    source.backup(restored)
    assert restored.execute("pragma integrity_check").fetchone()[0] == "ok"
    source.close(); restored.close()


class PublicationProvider:
    def __init__(self) -> None:
        self.published = False
        self.calls: list[str] = []

    def historical_daily_bars(self, symbol: str, _start: date, end: date, _market: Market):
        self.calls.append(symbol)
        return [bar(symbol, end if self.published else end - timedelta(days=1))]


def test_eod_pending_publication_then_gap_only_completion(tmp_path: Path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'eod.sqlite3'}")
    supported = list(load_market_path_registry().supported_market_paths)
    with sessions() as session:
        session.add_all(stored(sector.market_path_key, date(2026, 7, 29)) for sector in supported)
        session.add(stored("catering", date(2026, 7, 30)))
        session.commit()
    provider = PublicationProvider()
    coordinator = EodBackfillCoordinator(
        sessions, now=lambda: datetime(2026, 7, 30, 8, 0, tzinfo=timezone.utc),
        provider_factory=lambda: provider,
    )
    coordinator._schedule_retry = lambda _delay: None
    first = coordinator.run_if_needed()
    assert first["status"] == "pending_retry"
    operational = provider_capability_summary()["operational_coverage"]
    assert first["requested_count"] == first["failure_count"] == operational
    with sessions() as session:
        items = list(session.scalars(select(MarketRefreshItem).where(MarketRefreshItem.expected_trade_date == date(2026, 7, 30))))
        assert len(items) == operational and all(item.status == "pending_publication" and item.attempt_number == 1 for item in items)
    provider.published = True
    provider.calls.clear()
    second = coordinator.run_if_needed()
    assert second["status"] == "complete"
    assert second["requested_count"] == second["success_count"] == operational
    assert len(provider.calls) >= operational and "HSTECH" not in provider.calls
    assert coordinator.status()["missing_sector_count"] == 0


def test_eod_retry_budget_is_finite(tmp_path: Path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'eod-exhausted.sqlite3'}")
    provider = PublicationProvider()
    with sessions() as session:
        session.add(MarketRefreshItem(
            run_id="historical-run", sector_key="semiconductor", status="pending_publication",
            expected_trade_date=date(2026, 7, 30), attempt_number=4,
        ))
        session.commit()
    coordinator = EodBackfillCoordinator(
        sessions, now=lambda: datetime(2026, 7, 30, 8, 0, tzinfo=timezone.utc),
        provider_factory=lambda: provider,
    )
    result = coordinator.run_if_needed()
    assert result["status"] == "retry_exhausted"
    assert result["requested_count"] == 0
    assert provider.calls == []


def test_eod_gap_only_never_re_requests_completed_sectors(tmp_path: Path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'eod-gap-only.sqlite3'}")
    supported = list(load_market_path_registry().supported_market_paths)
    with sessions() as session:
        session.add_all(
            stored(sector.market_path_key, date(2026, 7, 30))
            for sector in supported
            if sector.market_path_key != "semiconductor"
        )
        session.commit()
    provider = PublicationProvider()
    provider.published = True
    coordinator = EodBackfillCoordinator(
        sessions, now=lambda: datetime(2026, 7, 30, 8, 0, tzinfo=timezone.utc),
        provider_factory=lambda: provider,
    )
    result = coordinator.run_if_needed()
    assert result["status"] == "complete"
    assert result["requested_count"] == result["success_count"] == 1
    assert provider.calls == ["881121"]
    provider.calls.clear()
    assert coordinator.run_if_needed()["status"] == "up_to_date"
    assert provider.calls == []


def test_eod_provider_failure_is_not_misclassified_as_pending_publication(tmp_path: Path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'eod-provider-failed.sqlite3'}")

    class InvalidProvider:
        def historical_daily_bars(self, *_args, **_kwargs):
            from leopard_project.providers import ProviderError, ProviderErrorCategory
            raise ProviderError(ProviderErrorCategory.INVALID_SYMBOL, "invalid", retryable=False)

    with sessions() as session:
        run = refresh_real_market(
            session,
            "test",
            sector_keys=["semiconductor"],
            as_of=date(2026, 7, 30),
            provider=InvalidProvider(),
            allowed_trade_dates={date(2026, 7, 30)},
            attempt_number=1,
            next_retry_at=datetime(2026, 7, 30, 8, 25, tzinfo=timezone.utc),
        )
        item = session.scalar(select(MarketRefreshItem).where(MarketRefreshItem.run_id == run.id))
    assert run.status == "partial_failure"
    assert item and item.status == "provider_failed"
    assert item.error_code == "invalid_symbol" and item.next_retry_at is None


def test_eod_provider_io_allows_concurrent_admin_write(tmp_path: Path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'nonblocking.sqlite3'}")
    wrote = False

    class ConcurrentProvider:
        def historical_daily_bars(self, symbol: str, _start: date, end: date, _market: Market):
            nonlocal wrote
            if not wrote:
                with sessions() as other:
                    other.add(MarketAutomationControl(control_key="intraday", admin_paused=True))
                    other.commit()
                wrote = True
            return [bar(symbol, end)]

    with sessions() as session:
        result = refresh_real_market(session, "test", sector_keys=["semiconductor"], as_of=date(2026, 7, 30), provider=ConcurrentProvider())
    assert result.status == "complete" and wrote


def test_sqlite_lock_retry_is_bounded_exponential_and_never_swallows_errors() -> None:
    attempts = 0
    delays: list[float] = []

    def eventually_succeeds() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OperationalError("commit", {}, Exception("database is locked"))
        return "written"

    assert coordinated_write(eventually_succeeds, sleep=delays.append) == "written"
    assert attempts == 3 and delays == [0.05, 0.1]

    def always_locked() -> None:
        raise OperationalError("commit", {}, Exception("database is locked"))

    try:
        coordinated_write(always_locked, attempts=2, sleep=lambda _delay: None)
    except SQLiteWriteLockExhausted as exc:
        assert "after_2_attempts" in str(exc)
    else:
        raise AssertionError("lock exhaustion must be explicit")

    original = OperationalError("select", {}, Exception("disk I/O error"))
    try:
        coordinated_write(lambda: (_ for _ in ()).throw(original))
    except OperationalError as exc:
        assert exc is original
    else:
        raise AssertionError("non-lock database errors must propagate")
