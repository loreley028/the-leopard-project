from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from leopard_project.historical_market_daily import backfill_market_history, market_core_symbols
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


def test_market_core_symbols_is_shanghai_plus_23_fixed_proxies() -> None:
    values = market_core_symbols()
    assert values[0] == "sh000001" and len(values) == len(set(values)) == 24
