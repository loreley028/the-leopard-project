from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from sqlalchemy import text

from leopard_project.daily_market_advance import advance_market_core, market_freshness_status
from leopard_project.providers.sina_public_daily import SinaDailyBar, SinaDailyError
from leopard_project.providers.tencent_standard_quote import StandardSecurityQuote, TencentQuoteBatch, TencentQuoteErrorCode
from leopard_project.web.database import create_session_factory


SHANGHAI = ZoneInfo("Asia/Shanghai")
DAY = date(2026, 8, 12)
AFTER_CLOSE = datetime(2026, 8, 12, 15, 20, tzinfo=SHANGHAI)
NEXT_MORNING = datetime(2026, 8, 13, 9, 10, tzinfo=SHANGHAI)


def sessions(tmp_path):
    return create_session_factory(f"sqlite:///{tmp_path / 'daily-advance.sqlite3'}")


def quote(symbol: str) -> StandardSecurityQuote:
    return StandardSecurityQuote(
        requested_symbol=symbol, name=symbol, symbol=symbol[2:], current=Decimal("10.20"),
        pre_close=Decimal("10.00"), quote_datetime=AFTER_CLOSE, change=Decimal("0.20"),
        pct_change=Decimal("2.00"), response_field_count=88, payload_sha256="test",
        open=Decimal("10.00"), high=Decimal("10.30"), low=Decimal("9.90"), amount_yuan=Decimal("100000"),
    )


class TencentProvider:
    max_batch_size = 20

    def __init__(self, quotes: dict[str, StandardSecurityQuote], failures: dict[str, TencentQuoteErrorCode] | None = None) -> None:
        self.quotes = quotes
        self.failures = failures or {}
        self.calls: list[tuple[str, ...]] = []

    def fetch_batch(self, symbols, *, allow_network=False):
        assert allow_network is True
        requested = tuple(symbols)
        self.calls.append(requested)
        return TencentQuoteBatch(
            tuple(self.quotes[symbol] for symbol in requested if symbol in self.quotes),
            {symbol: error for symbol, error in self.failures.items() if symbol in requested}, 1,
        )


class SinaProvider:
    provider_key = "sina_public_daily_http"

    def __init__(self, *, limited: bool = False) -> None:
        self.limited = limited
        self.calls: list[str] = []

    def fetch_history(self, symbol, *, days, allow_network=False):
        assert days == 20 and allow_network is True
        self.calls.append(symbol)
        if self.limited:
            raise SinaDailyError("http_456")
        previous = DAY - timedelta(days=1)
        return (
            SinaDailyBar(previous, Decimal("10"), Decimal("11"), Decimal("9"), Decimal("10"), Decimal("100")),
            SinaDailyBar(DAY, Decimal("10.1"), Decimal("10.3"), Decimal("10"), Decimal("10.2"), Decimal("100")),
        )


def narrow_universe(monkeypatch) -> tuple[str, ...]:
    symbols = ("sz300308", "sz300502")
    monkeypatch.setattr("leopard_project.security_proxy_daily.market_core_security_symbols", lambda registry=None: symbols)
    monkeypatch.setattr("leopard_project.daily_market_advance.market_core_symbols", lambda: ("sh000001", *symbols))
    return symbols


def test_post_close_advance_uses_tencent_then_repairs_only_the_missing_exact_date_without_pdf(tmp_path, monkeypatch) -> None:
    symbols = narrow_universe(monkeypatch)
    tencent = TencentProvider(
        {"sh000001": quote("sh000001"), "sz300308": quote("sz300308")},
        {"sz300502": TencentQuoteErrorCode.EMPTY_REPLY},
    )
    sina = SinaProvider()
    with sessions(tmp_path)() as session:
        assert session.execute(text("SELECT COUNT(*) FROM reports")).scalar_one() == 0
        result = advance_market_core(
            session, mode="advance", now=AFTER_CLOSE, tencent_provider=tencent, sina_provider=sina,
            enable_tencent_provider=True, enable_sina_provider=True,
        )
        assert result.complete is True
        assert result.expected_trading_date == DAY
        assert result.tencent_inserted == 2 and result.historical_inserted == 1
        assert sina.calls == ["sz300502"]
        assert result.coverage.ready_symbols == 3
        status = market_freshness_status(session, now=NEXT_MORNING)
        assert status["market_core"] == {"through_expected": 3, "required": 3, "missing_symbols": []}
        assert session.execute(text("SELECT COUNT(*) FROM reports")).scalar_one() == 0

    with sessions(tmp_path)() as session:
        second = advance_market_core(
            session, mode="reconcile", now=NEXT_MORNING, sina_provider=sina, enable_sina_provider=True,
        )
    assert second.complete is True and second.primary_capture_attempted is False
    assert sina.calls == ["sz300502"]
    assert tencent.calls == [("sh000001",), symbols]


def test_missed_capture_reconcile_stops_on_sina_456_without_retry_or_overwrite(tmp_path, monkeypatch) -> None:
    narrow_universe(monkeypatch)
    sina = SinaProvider(limited=True)
    with sessions(tmp_path)() as session:
        result = advance_market_core(
            session, mode="reconcile", now=datetime(2026, 8, 12, 15, 40, tzinfo=SHANGHAI),
            sina_provider=sina, enable_sina_provider=True,
        )
        assert result.complete is False
        assert result.coverage.missing_symbols == ("sh000001", "sz300308", "sz300502")
        assert result.provider_failures == {"sh000001": "http_456"}
        assert result.historical_inserted == 0 and result.conflicts == 0
    assert sina.calls == ["sh000001"]


def test_advance_is_time_controlled_not_specific_to_a_calendar_date(tmp_path, monkeypatch) -> None:
    narrow_universe(monkeypatch)
    tencent = TencentProvider({symbol: quote(symbol) for symbol in ("sh000001", "sz300308", "sz300502")})
    with sessions(tmp_path)() as session:
        result = advance_market_core(
            session, mode="advance", now=AFTER_CLOSE, tencent_provider=tencent,
            enable_tencent_provider=True,
        )
    assert result.primary_capture_attempted is True and result.complete is True
