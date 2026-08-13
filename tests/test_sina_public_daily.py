from __future__ import annotations

import json
from datetime import date

import pytest

from leopard_project.providers.sina_public_daily import SinaDailyError, SinaPublicDailyMarketProvider


def payload(rows: list[dict]) -> bytes:
    return json.dumps(rows).encode("utf-8")


def rows() -> list[dict]:
    return [
        {"day": "2026-08-10", "open": "10", "high": "11", "low": "9", "close": "10.5", "volume": "100"},
        {"day": "2026-08-11", "open": "10.6", "high": "12", "low": "10", "close": "11", "volume": "120"},
        {"day": "2026-08-12", "open": "11", "high": "12", "low": "10.8", "close": "11.5", "volume": "140"},
        {"day": "2026-08-13", "open": "11.5", "high": "12.5", "low": "11", "close": "12", "volume": "160"},
    ]


def test_sina_daily_provider_parses_unadjusted_ascending_bars() -> None:
    provider = SinaPublicDailyMarketProvider(transport=lambda _url, _timeout: payload(rows()))
    result = provider.fetch_history("sz300308", days=20, allow_network=True)
    assert [row.trading_date for row in result] == sorted(row.trading_date for row in result)
    assert result[-1].close == 12 and result[-1].volume == 160
    assert provider.provider_key == "sina_public_daily_http"
    assert provider.price_adjustment_policy == "unadjusted_daily_bar"


def test_sina_daily_provider_is_explicit_and_fixed_symbol_only() -> None:
    provider = SinaPublicDailyMarketProvider(transport=lambda _url, _timeout: payload(rows()))
    with pytest.raises(PermissionError):
        provider.fetch_history("sz300308", days=20)
    with pytest.raises(ValueError):
        provider.fetch_history("600000", days=20, allow_network=True)


@pytest.mark.parametrize("broken", [
    [{"day": "2026-08-09", "open": "10", "high": "11", "low": "9", "close": "10", "volume": "1"}],
    [{"day": "2026-08-10", "open": "12", "high": "11", "low": "9", "close": "10", "volume": "1"}],
    rows() + [rows()[-1]],
])
def test_sina_daily_provider_rejects_non_trading_invalid_and_duplicate_dates(broken: list[dict]) -> None:
    provider = SinaPublicDailyMarketProvider(transport=lambda _url, _timeout: payload(broken))
    with pytest.raises(SinaDailyError):
        provider.fetch_history("sz300308", days=20, allow_network=True)


def test_sina_daily_provider_does_not_accept_future_provider_payload(monkeypatch) -> None:
    provider = SinaPublicDailyMarketProvider(transport=lambda _url, _timeout: payload(rows()))
    monkeypatch.setattr("leopard_project.providers.sina_public_daily.evaluate_cn_a_day", lambda _day: type("Day", (), {"status": "future"})())
    with pytest.raises(SinaDailyError, match="invalid_daily_structure"):
        provider.fetch_history("sz300308", days=20, allow_network=True)
