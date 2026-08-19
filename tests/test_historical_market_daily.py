from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from leopard_project.historical_market_daily import (
    backfill_market_history,
    backfill_selected_market_history,
    expected_latest_completed_trading_day,
    market_core_symbols,
    refresh_market_history_to_latest_completed,
)
from leopard_project.security_proxy_daily import market_core_security_symbols
from leopard_project.providers.sina_public_daily import SinaDailyBar
from leopard_project.web.database import create_session_factory
from leopard_project.web.models import LiveMarketAnchorDaily, SecurityProxyDaily


class Provider:
    provider_key = "sina_public_daily_http"
    def __init__(self): self.calls = []
    def fetch_history(self, symbol, *, days, allow_network=False):
        assert allow_network is True and days == 20
        self.calls.append(symbol)
        return tuple(SinaDailyBar(date(2026, 7, 1).fromordinal(date(2026, 7, 1).toordinal() + index), Decimal(10 + index), Decimal(11 + index), Decimal(9 + index), Decimal(10 + index), Decimal(100)) for index in range(20))


def sessions(tmp_path):
    return create_session_factory(f"sqlite:///{tmp_path / 'history.sqlite3'}")


def test_backfill_uses_exact_fixed_universe_and_existing_tables(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("leopard_project.historical_market_daily.market_core_symbols", lambda: ("sh000001", "sz300308"))
    provider = Provider(); factory = sessions(tmp_path)
    with factory() as session:
        summary = backfill_market_history(session, provider=provider, days=20, enable_provider=True)
        anchors = session.scalars(select(LiveMarketAnchorDaily).order_by(LiveMarketAnchorDaily.trading_date)).all()
        proxies = session.scalars(select(SecurityProxyDaily).order_by(SecurityProxyDaily.trading_date)).all()
    assert provider.calls == ["sh000001", "sz300308"]
    assert summary.inserted == 39 and summary.conflicts == 0
    assert len(anchors) == 19 and anchors[0].pct_change != 0
    assert len(proxies) == 20 and {row.source for row in proxies} == {"sina_public_daily_http"}


def test_backfill_is_idempotent_and_never_silently_overwrites_conflicts(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("leopard_project.historical_market_daily.market_core_symbols", lambda: ("sz300308",))
    provider = Provider(); factory = sessions(tmp_path)
    with factory() as session:
        first = backfill_market_history(session, provider=provider, days=20, enable_provider=True)
        second = backfill_market_history(session, provider=provider, days=20, enable_provider=True)
        row = session.scalar(select(SecurityProxyDaily).where(SecurityProxyDaily.trading_date == date(2026, 7, 1)))
        assert row is not None
        row.close = Decimal("99"); session.commit()
        third = backfill_market_history(session, provider=provider, days=20, enable_provider=True)
    assert first.inserted == 20 and second.inserted == 0 and second.skip_existing_same == 20
    assert third.conflicts == 1 and third.inserted == 0


def test_backfill_replaces_a_conflict_only_after_explicit_opt_in(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("leopard_project.historical_market_daily.market_core_symbols", lambda: ("sz300308",))
    provider = Provider(); factory = sessions(tmp_path)
    with factory() as session:
        backfill_market_history(session, provider=provider, days=20, enable_provider=True)
        row = session.scalar(select(SecurityProxyDaily).where(SecurityProxyDaily.trading_date == date(2026, 7, 1)))
        assert row is not None
        row.close = Decimal("99"); session.commit()
        summary = backfill_market_history(session, provider=provider, days=20, enable_provider=True, replace=True)
        repaired = session.scalar(select(SecurityProxyDaily).where(SecurityProxyDaily.trading_date == date(2026, 7, 1)))
    assert summary.replaced == 1
    assert repaired is not None and repaired.close == Decimal("10")


def test_backfill_requires_explicit_provider_enablement(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("leopard_project.historical_market_daily.market_core_symbols", lambda: ("sz300308",))
    with sessions(tmp_path)() as session, pytest.raises(PermissionError):
        backfill_market_history(session, provider=Provider(), days=20)


def test_backfill_excludes_same_day_intraday_bar_until_after_close(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("leopard_project.historical_market_daily.market_core_symbols", lambda: ("sz300308",))
    provider = Provider(); factory = sessions(tmp_path)
    with factory() as session:
        summary = backfill_market_history(
            session, provider=provider, days=20, enable_provider=True,
            now=datetime(2026, 7, 20, 14, 0),
        )
    assert summary.inserted == 0
    assert summary.provider_failures == {"sz300308": "insufficient_completed_history"}


def test_market_core_symbols_is_shanghai_plus_broad_anchors_and_fixed_proxies() -> None:
    values = market_core_symbols()
    assert values[:5] == ("sh000001", "sh510050", "sh510300", "sh588000", "sz159915")
    assert len(values) == len(set(values)) == len(market_core_security_symbols()) + 1


def test_expected_latest_completed_day_20260819_is_20260818() -> None:
    assert expected_latest_completed_trading_day(datetime(2026, 8, 19, 10, 0)) == date(2026, 8, 18)


def test_refresh_fills_only_expected_market_day_and_is_idempotent(tmp_path, monkeypatch) -> None:
    expected = date(2026, 8, 18)
    monkeypatch.setattr("leopard_project.historical_market_daily.market_core_symbols", lambda: ("sh000001", "sz300308"))

    class RefreshProvider:
        provider_key = "sina_public_daily_http"
        def __init__(self): self.calls = []
        def fetch_history(self, symbol, *, days, allow_network=False):
            assert days == 20 and allow_network is True
            self.calls.append(symbol)
            return (
                SinaDailyBar(date(2026, 8, 17), Decimal("10"), Decimal("11"), Decimal("9"), Decimal("10"), Decimal("100")),
                SinaDailyBar(expected, Decimal("11"), Decimal("12"), Decimal("10"), Decimal("11"), Decimal("100")),
                SinaDailyBar(date(2026, 8, 19), Decimal("12"), Decimal("13"), Decimal("11"), Decimal("12"), Decimal("100")),
            )

    provider = RefreshProvider(); factory = sessions(tmp_path)
    with factory() as session:
        # The refresh is independent of Report Facts: no report exists in this
        # database while the Market Core exact-date rows are populated.
        assert session.execute(text("SELECT COUNT(*) FROM reports")).scalar_one() == 0
        first = refresh_market_history_to_latest_completed(
            session, provider=provider, enable_provider=True, now=datetime(2026, 8, 19, 10, 0),
        )
        second = refresh_market_history_to_latest_completed(
            session, provider=provider, enable_provider=True, now=datetime(2026, 8, 19, 10, 0),
        )
        assert session.scalar(select(LiveMarketAnchorDaily).where(LiveMarketAnchorDaily.trading_date == expected)) is not None
        assert session.scalar(select(SecurityProxyDaily).where(SecurityProxyDaily.trading_date == expected)) is not None
        assert session.scalar(select(LiveMarketAnchorDaily).where(LiveMarketAnchorDaily.trading_date == date(2026, 8, 19))) is None
        assert session.scalar(select(SecurityProxyDaily).where(SecurityProxyDaily.trading_date == date(2026, 8, 19))) is None
    assert first.expected_latest_completed_trading_day == expected and first.inserted == 2 and first.conflicts == 0
    assert second.inserted == 0 and second.skip_existing_same == 2 and second.conflicts == 0


class PacedProvider:
    provider_key = "sina_public_daily_http"

    def __init__(self, *, limited_symbol: str | None = None) -> None:
        self.calls: list[str] = []
        self.limited_symbol = limited_symbol

    def fetch_history(self, symbol, *, days, allow_network=False):
        assert days == 45 and allow_network is True
        self.calls.append(symbol)
        if symbol == self.limited_symbol:
            from leopard_project.providers.sina_public_daily import SinaDailyError
            raise SinaDailyError("http_456")
        return tuple(SinaDailyBar(date(2026, 7, 1).fromordinal(date(2026, 7, 1).toordinal() + index), Decimal(10 + index), Decimal(11 + index), Decimal(9 + index), Decimal(10 + index), Decimal(100)) for index in range(50))


def test_selected_backfill_fetches_each_missing_symbol_once_and_is_idempotent(tmp_path) -> None:
    provider = PacedProvider(); factory = sessions(tmp_path)
    with factory() as session:
        first = backfill_selected_market_history(session, provider=provider, symbols=("sz300308",), days=45, enable_provider=True, now=datetime(2026, 8, 19, 10, 0))
        second = backfill_selected_market_history(session, provider=provider, symbols=("sz300308",), days=45, enable_provider=True, now=datetime(2026, 8, 19, 10, 0))
    assert provider.calls == ["sz300308"]
    assert first.inserted == 49 and first.conflicts == 0
    assert second.inserted == 0 and second.completed_symbols == 1 and second.remaining_symbols == 0


def test_selected_backfill_is_paced_and_stops_on_http_456_without_retry(tmp_path) -> None:
    sleeps: list[float] = []; checkpoints: list[tuple[str, str]] = []
    provider = PacedProvider(limited_symbol="sz300502")
    with sessions(tmp_path)() as session:
        result = backfill_selected_market_history(
            session, provider=provider, symbols=("sz300308", "sz300502", "sz300394"), days=45,
            enable_provider=True, paced_seconds=3, sleep=sleeps.append, checkpoint=lambda symbol, status: checkpoints.append((symbol, status)), now=datetime(2026, 8, 19, 10, 0),
        )
    assert provider.calls == ["sz300308", "sz300502"] and sleeps == [3]
    assert result.blocked_symbol == "sz300502" and result.provider_failures == {"sz300502": "http_456"}
    assert checkpoints == [("sz300308", "completed"), ("sz300502", "http_456")]


def test_selected_backfill_resume_preflight_skips_completed_symbol(tmp_path) -> None:
    factory = sessions(tmp_path)
    with factory() as session:
        first_provider = PacedProvider(limited_symbol="sz300502")
        first = backfill_selected_market_history(session, provider=first_provider, symbols=("sz300308", "sz300502"), days=45, enable_provider=True, now=datetime(2026, 8, 19, 10, 0))
        resumed_provider = PacedProvider()
        resumed = backfill_selected_market_history(session, provider=resumed_provider, symbols=("sz300308", "sz300502"), days=45, enable_provider=True, now=datetime(2026, 8, 19, 10, 0))
    assert first.blocked_symbol == "sz300502"
    assert resumed_provider.calls == ["sz300502"]
    assert resumed.completed_symbols == 2 and resumed.remaining_symbols == 0
