from __future__ import annotations

import json
from datetime import datetime, timezone
from http.client import RemoteDisconnected

import pytest

from leopard_project.config import load_seed_bundle
from leopard_project.providers import EastmoneyBoardSpotProvider, ProviderError
from leopard_project.providers import eastmoney_spot
from leopard_project.providers.base import ProviderErrorCategory


def payload(rows: list[dict]) -> bytes:
    return json.dumps({"data": {"diff": rows}}, ensure_ascii=False).encode()


def history_payload(symbol: str, closes: tuple[int, int, int, int] = (96, 97, 98, 100)) -> bytes:
    rows = [f"2026-07-{day},{close},{close},{close},{close},1,1,0,0,0,0" for day, close in zip((22, 23, 24, 27), closes, strict=True)]
    return json.dumps({"data": {"code": symbol, "name": symbol, "klines": rows}}).encode()


def test_eastmoney_spot_uses_two_request_cache_and_real_fields() -> None:
    calls: list[str] = []
    documents = iter([
        payload([{
            "f2": 2564.28, "f3": -4.15, "f4": -110.93, "f5": 33550000, "f6": 27040000000,
            "f12": "BK1036", "f14": "半导体", "f15": 2675.09, "f16": 2543.61,
            "f17": 2611.05, "f18": 2675.21,
        }]),
        payload([]),
    ])

    def transport(url: str, _timeout: float) -> bytes:
        calls.append(url)
        if "kline/get" in url:
            return history_payload("BK1036", (2600, 2620, 2650, 2675))
        return next(documents)

    mapping = next(item for item in load_seed_bundle().mappings if item.sector_key == "semiconductor")
    provider = EastmoneyBoardSpotProvider(transport=transport)
    bar = provider.fetch_intraday_snapshot(mapping, datetime(2026, 7, 28, 5, 14, 15, tzinfo=timezone.utc))
    assert (bar.symbol, bar.symbol_name, bar.trade_date.isoformat()) == ("BK1036", "半导体", "2026-07-28")
    assert (str(bar.close), str(bar.pre_close), str(bar.pct_change)) == ("2564.28", "2675.21", "-4.15")
    assert bar.volume and bar.amount and bar.source_payload_hash
    provider.fetch_intraday_snapshot(mapping, datetime(2026, 7, 28, 5, 15, tzinfo=timezone.utc))
    assert len(calls) == provider.request_count == 3
    assert len(bar.provider_native_history) == 4
    assert bar.provider_native_history_status == "complete"


def test_eastmoney_spot_cache_expires_at_next_server_cycle() -> None:
    calls: list[str] = []
    spot_calls = 0

    def transport(url: str, _timeout: float) -> bytes:
        nonlocal spot_calls
        calls.append(url)
        if "kline/get" in url:
            return history_payload("BK1036", (2600, 2620, 2650, 2675))
        spot_calls += 1
        return payload([{
            "f2": 2564.28, "f3": -4.15, "f5": 33550000, "f6": 27040000000,
            "f12": "BK1036", "f14": "半导体", "f15": 2675.09, "f16": 2543.61,
            "f17": 2611.05, "f18": 2675.21,
        }]) if spot_calls % 2 else payload([])

    mapping = next(item for item in load_seed_bundle().mappings if item.sector_key == "semiconductor")
    provider = EastmoneyBoardSpotProvider(transport=transport)
    provider.fetch_intraday_snapshot(mapping, datetime(2026, 7, 28, 5, 14, tzinfo=timezone.utc))
    provider.begin_cycle()
    provider.fetch_intraday_snapshot(mapping, datetime(2026, 7, 28, 5, 19, tzinfo=timezone.utc))
    assert len(calls) == 5 and provider.request_count == 2


def test_eastmoney_spot_builds_custom_composite_from_real_components() -> None:
    documents = iter([
        payload([
            {"f2": 102, "f3": 2, "f5": 1000, "f6": 2000, "f12": "BK1001", "f14": "食品加工制造", "f15": 103, "f16": 99, "f17": 100, "f18": 100},
            {"f2": 99, "f3": -1, "f5": 1200, "f6": 2200, "f12": "BK1002", "f14": "饮料制造", "f15": 101, "f16": 98, "f17": 100, "f18": 100},
        ]),
        payload([]),
    ])
    mapping = next(item for item in load_seed_bundle().mappings if item.sector_key == "food_beverage")
    def transport(url: str, _timeout: float) -> bytes:
        if "kline/get" in url:
            symbol = "BK1001" if "BK1001" in url else "BK1002"
            return history_payload(symbol)
        return next(documents)

    provider = EastmoneyBoardSpotProvider(transport=transport)
    bar = provider.fetch_intraday_snapshot(mapping, datetime(2026, 7, 28, 5, 14, tzinfo=timezone.utc))
    assert bar.symbol == "CUSTOM_FOOD_BEVERAGE"
    assert bar.close == 1005 and bar.pre_close == 1000 and bar.pct_change == pytest.approx(0.5)
    assert bar.provider_symbol == "BK1001+BK1002"
    assert bar.lineage and "881134->BK1001" in bar.lineage


def test_hotel_catering_intraday_lineage_is_explicit_proxy() -> None:
    documents = iter([
        payload([{"f2": 102, "f3": 2, "f5": 1000, "f6": 2000, "f12": "BK1271", "f14": "酒店餐饮", "f15": 103, "f16": 99, "f17": 100, "f18": 100}]),
        payload([]),
    ])
    mapping = next(item for item in load_seed_bundle().mappings if item.sector_key == "hotel_catering")
    provider = EastmoneyBoardSpotProvider(
        transport=lambda url, _timeout: history_payload("BK1271") if "kline/get" in url else next(documents)
    )
    bar = provider.fetch_intraday_snapshot(mapping, datetime(2026, 7, 30, 2, 0, tzinfo=timezone.utc))
    assert bar.data_status.value == "proxy"
    assert bar.lineage
    for value in (
        "canonical_sector=酒店餐饮", "mapping_type=proxy", "proxy_symbol=881160",
        "provider=eastmoney_board_spot", "provider_symbol=BK1271",
        "provider_name=酒店餐饮", "rationale=", "as_of=", "source_status=available",
    ):
        assert value in bar.lineage


def test_eastmoney_spot_paginates_beyond_first_hundred_rows() -> None:
    first_page = [{
        "f2": 101, "f3": 1, "f5": 1, "f6": 1, "f12": f"BK{i:04d}", "f14": f"占位板块{i}",
        "f15": 102, "f16": 99, "f17": 100, "f18": 100,
    } for i in range(100)]
    documents = iter([
        payload(first_page),
        payload([{"f2": 102, "f3": 2, "f5": 1, "f6": 1, "f12": "BK1036", "f14": "半导体", "f15": 103, "f16": 99, "f17": 100, "f18": 100}]),
        payload([]),
    ])
    mapping = next(item for item in load_seed_bundle().mappings if item.sector_key == "semiconductor")
    provider = EastmoneyBoardSpotProvider(
        transport=lambda url, _timeout: history_payload("BK1036") if "kline/get" in url else next(documents)
    )
    assert provider.fetch_intraday_snapshot(mapping, datetime(2026, 7, 28, 5, 14, tzinfo=timezone.utc)).symbol == "BK1036"
    assert provider.request_count == 4


def test_eastmoney_spot_uses_only_explicit_taxonomy_translations() -> None:
    assert EastmoneyBoardSpotProvider.provider_name_candidates["cpo"] == ("CPO概念",)
    assert EastmoneyBoardSpotProvider.provider_name_candidates["securities"] == ("证券Ⅱ",)
    assert "computing_power_rental" not in EastmoneyBoardSpotProvider.provider_name_candidates
    assert "retail" not in EastmoneyBoardSpotProvider.provider_name_candidates
    assert EastmoneyBoardSpotProvider.component_candidates["881160"] == (2, ("酒店餐饮",))


def test_eastmoney_transport_classifies_remote_disconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    def disconnect(*_args: object, **_kwargs: object) -> object:
        raise RemoteDisconnected("closed")

    monkeypatch.setattr(eastmoney_spot, "urlopen", disconnect)
    with pytest.raises(ProviderError, match="spot request failed") as caught:
        eastmoney_spot._transport("https://example.invalid", 1)
    assert caught.value.retryable is True


def test_eastmoney_native_history_uses_bounded_backoff_for_retryable_failures() -> None:
    attempts = 0
    delays: list[float] = []

    def transport(_url: str, _timeout: float) -> bytes:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ProviderError(ProviderErrorCategory.RATE_LIMIT, "limited", retryable=True)
        return history_payload("BK1036")

    provider = EastmoneyBoardSpotProvider(transport=transport, sleeper=delays.append)
    history, status, error = provider._safe_native_history("BK1036", datetime(2026, 7, 28).date())
    assert status == "complete" and error is None and len(history) == 4
    assert attempts == 3 and delays == [0.75, 1.5]
