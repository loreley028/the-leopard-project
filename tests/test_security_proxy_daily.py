from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from leopard_project.providers.tencent_standard_quote import TencentQuoteBatch, TencentQuoteErrorCode
from leopard_project.security_proxy_daily import (
    SecurityProxyDailyCaptureError,
    build_security_proxy_trend_metrics,
    capture_fixed_security_proxy_daily,
    fixed_proxy_symbols,
    get_security_proxy_daily_history,
)
from leopard_project.security_proxy_observation import load_security_proxy_registry
from leopard_project.trading_calendar import CalendarEvaluation, CalendarStatus
from leopard_project.web.database import create_session_factory
from leopard_project.web.models import SecurityProxyDaily


SHANGHAI = ZoneInfo("Asia/Shanghai")
DAY = date(2026, 8, 5)
NOW = datetime(2026, 8, 5, 15, 20, tzinfo=SHANGHAI)


class FakeProvider:
    max_batch_size = 20

    def __init__(self, quotes: dict[str, object], failures: dict[str, TencentQuoteErrorCode] | None = None) -> None:
        self.quotes, self.failures, self.calls = quotes, failures or {}, []

    def fetch_batch(self, symbols, *, allow_network: bool = False):
        assert allow_network is True
        requested = tuple(symbols)
        self.calls.append(requested)
        return TencentQuoteBatch(tuple(self.quotes[symbol] for symbol in requested if symbol in self.quotes), {
            symbol: error for symbol, error in self.failures.items() if symbol in requested
        }, 1)


def quote(symbol: str, *, current: object = "10.20", timestamp: datetime = NOW, open_: object = "10", high: object = "11", low: object = "9", amount: object = "10000"):
    return SimpleNamespace(
        requested_symbol=symbol, current=current, quote_datetime=timestamp,
        open=open_, high=high, low=low, amount_yuan=amount,
    )


def registry(symbols: tuple[str, ...]):
    instrument = lambda symbol: SimpleNamespace(symbol=symbol, enabled=True)
    return (SimpleNamespace(instruments=tuple(instrument(symbol) for symbol in symbols)),)


def sessions(tmp_path):
    return create_session_factory(f"sqlite:///{tmp_path / 'proxy-history.sqlite3'}")


def capture(session, symbols: tuple[str, ...], provider: FakeProvider, *, now: datetime = NOW):
    return capture_fixed_security_proxy_daily(
        session, target_trading_date=DAY, provider=provider, now=lambda: now,
        registry=registry(symbols), enable_provider=True,
    )


def test_schema_has_simple_fixed_proxy_daily_table_and_unique_constraint(tmp_path) -> None:
    factory = sessions(tmp_path)
    tables = inspect(factory.kw["bind"]).get_table_names()
    assert "security_proxy_daily" in tables
    with factory() as session:
        session.add(SecurityProxyDaily(symbol="sh510300", trading_date=DAY, close=Decimal("10"), fetched_at=NOW, source="test"))
        session.commit()
        session.add(SecurityProxyDaily(symbol="sh510300", trading_date=DAY, close=Decimal("11"), fetched_at=NOW, source="test"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_fixed_registry_is_the_only_deduplicated_symbol_source() -> None:
    symbols = fixed_proxy_symbols()
    assert len(symbols) == len(set(symbols)) == 23
    assert "sh515880" in symbols and "glass_substrate" not in symbols and "catering" not in symbols


def test_capture_writes_numeric_string_close_and_optional_field_failures_become_null(tmp_path) -> None:
    factory = sessions(tmp_path)
    provider = FakeProvider({"sh510300": quote("sh510300", current="10.20", open_="broken", high="11", low="9", amount="nan")})
    with factory() as session:
        summary = capture(session, ("sh510300",), provider)
        row = session.get(SecurityProxyDaily, session.scalar(select(SecurityProxyDaily.id)))
        assert summary.inserted_count == 1 and row is not None
        assert Decimal(str(row.close)) == Decimal("10.20")
        assert row.open is None and row.amount_yuan is None and Decimal(str(row.high)) == Decimal("11")


@pytest.mark.parametrize("value", [None, "bad", "0", "-1", "NaN"])
def test_invalid_close_never_writes(value, tmp_path) -> None:
    factory = sessions(tmp_path)
    with factory() as session:
        summary = capture(session, ("sh510300",), FakeProvider({"sh510300": quote("sh510300", current=value)}))
        assert summary.inserted_count == 0 and summary.failures == {"sh510300": "invalid_close"}
        assert session.query(SecurityProxyDaily).count() == 0


def test_quote_time_mismatch_and_naive_time_are_rejected_without_writes(tmp_path) -> None:
    factory = sessions(tmp_path)
    cases = {
        "sh510300": quote("sh510300", timestamp=datetime(2026, 8, 4, 15, 20, tzinfo=SHANGHAI)),
        "sz300308": quote("sz300308", timestamp=datetime(2026, 8, 5, 15, 20)),
    }
    with factory() as session:
        summary = capture(session, tuple(cases), FakeProvider(cases))
        assert summary.inserted_count == 0
        assert summary.failures == {"sh510300": "quote_date_mismatch", "sz300308": "naive_quote_datetime"}


@pytest.mark.parametrize("target,now,expected", [
    (date(2026, 8, 1), NOW, "non_trading_day"),
    (DAY, datetime(2026, 8, 5, 15, 9, tzinfo=SHANGHAI), "market_not_closed"),
])
def test_capture_window_stops_before_provider(target, now, expected, tmp_path) -> None:
    factory = sessions(tmp_path); provider = FakeProvider({"sh510300": quote("sh510300")})
    with factory() as session, pytest.raises(SecurityProxyDailyCaptureError, match=expected):
        capture_fixed_security_proxy_daily(session, target_trading_date=target, provider=provider, now=lambda: now, registry=registry(("sh510300",)), enable_provider=True)
    assert provider.calls == []


def test_calendar_unavailable_stops_before_provider(monkeypatch, tmp_path) -> None:
    import leopard_project.security_proxy_daily as module
    monkeypatch.setattr(module, "evaluate_cn_a_day", lambda _day: CalendarEvaluation(DAY, CalendarStatus.UNAVAILABLE, None, None, None))
    factory = sessions(tmp_path); provider = FakeProvider({"sh510300": quote("sh510300")})
    with factory() as session, pytest.raises(SecurityProxyDailyCaptureError, match="calendar_unavailable"):
        capture(session, ("sh510300",), provider)
    assert provider.calls == []


def test_capture_batches_deduplicates_and_already_exists_does_not_overwrite(tmp_path) -> None:
    symbols = tuple(f"sh{index:06d}" for index in range(1, 22))
    factory = sessions(tmp_path)
    provider = FakeProvider({symbol: quote(symbol) for symbol in symbols})
    with factory() as session:
        session.add(SecurityProxyDaily(symbol=symbols[0], trading_date=DAY, close=Decimal("7"), fetched_at=NOW, source="test")); session.commit()
        summary = capture(session, symbols + (symbols[1],), provider)
        assert [len(batch) for batch in provider.calls] == [20]
        assert summary.candidate_count == 21 and summary.requested_count == 20 and summary.already_exists_count == 1
        assert summary.inserted_count == 20
        preserved = session.scalar(select(SecurityProxyDaily).where(SecurityProxyDaily.symbol == symbols[0]))
        assert Decimal(str(preserved.close)) == Decimal("7")
    provider = FakeProvider({symbol: quote(symbol) for symbol in symbols})
    with factory() as session:
        summary = capture(session, tuple(f"sz{index:06d}" for index in range(1, 22)), FakeProvider({f"sz{index:06d}": quote(f"sz{index:06d}") for index in range(1, 22)}))
        assert summary.provider_batch_count == 2


def test_partial_provider_failure_keeps_other_valid_rows(tmp_path) -> None:
    factory = sessions(tmp_path)
    provider = FakeProvider({"sh510300": quote("sh510300")}, {"sz300308": TencentQuoteErrorCode.EMPTY_REPLY})
    with factory() as session:
        summary = capture(session, ("sh510300", "sz300308"), provider)
        assert summary.inserted_count == 1 and summary.failures == {"sz300308": "empty_reply"}


@pytest.mark.parametrize("count, expected_ma5, expected_ma10, expected_ma20", [
    (1, None, None, None), (4, None, None, None), (5, Decimal("3"), None, None),
    (9, Decimal("7"), None, None), (10, Decimal("8"), Decimal("5.5"), None),
    (19, Decimal("17"), Decimal("14.5"), None), (20, Decimal("18"), Decimal("15.5"), Decimal("10.5")),
    (21, Decimal("19"), Decimal("16.5"), Decimal("11.5")),
])
def test_trend_metrics_use_only_completed_daily_closes(count, expected_ma5, expected_ma10, expected_ma20) -> None:
    history = [SimpleNamespace(trading_date=date(2026, 1, 1).fromordinal(date(2026, 1, 1).toordinal() + index), close=Decimal(index + 1)) for index in range(count)]
    metrics = build_security_proxy_trend_metrics(history, Decimal(count + 1))
    assert (metrics.ma5, metrics.ma10, metrics.ma20) == (expected_ma5, expected_ma10, expected_ma20)
    assert len(metrics.recent_closes) == min(count, 5)
    assert tuple(item.trading_date for item in metrics.recent_closes) == tuple(sorted(item.trading_date for item in metrics.recent_closes))
    if expected_ma5 is not None:
        assert metrics.distance_to_ma5_pct == (Decimal(count + 1) / expected_ma5 - 1) * 100


def test_history_read_is_ascending_limited_to_twenty_and_invalid_current_has_no_distance(tmp_path) -> None:
    factory = sessions(tmp_path)
    with factory() as session:
        for index in range(21):
            session.add(SecurityProxyDaily(symbol="sh510300", trading_date=date(2026, 1, 1).fromordinal(date(2026, 1, 1).toordinal() + index), close=Decimal(index + 1), fetched_at=NOW, source="test"))
        session.commit()
        history = get_security_proxy_daily_history(session, "sh510300")
        assert len(history) == 20 and history[0].trading_date < history[-1].trading_date
        metrics = build_security_proxy_trend_metrics(history, "invalid")
        assert metrics.ma20 == Decimal("11.5") and metrics.distance_to_ma5_pct is None


def test_history_helper_excludes_missing_close_and_rejects_duplicate_dates() -> None:
    day = date(2026, 8, 1)
    metrics = build_security_proxy_trend_metrics([
        SimpleNamespace(trading_date=day, close=None), SimpleNamespace(trading_date=date(2026, 8, 2), close="10"),
    ], "11")
    assert len(metrics.recent_closes) == 1 and metrics.ma5 is None
    with pytest.raises(ValueError, match="duplicate"):
        build_security_proxy_trend_metrics([SimpleNamespace(trading_date=day, close="10"), SimpleNamespace(trading_date=day, close="11")], "12")


def test_history_foundation_has_no_aggregate_contract() -> None:
    metrics = build_security_proxy_trend_metrics([], None)
    assert not any(hasattr(metrics, field) for field in ("aggregate_pct_change", "average_return", "weighted_return", "synthetic_index"))
