from __future__ import annotations

import json
from datetime import datetime, timezone
from http.client import RemoteDisconnected

import pytest

from leopard_project.config import load_seed_bundle
from leopard_project.providers import EastmoneyBoardSpotProvider, ProviderError
from leopard_project.providers import eastmoney_spot


def payload(rows: list[dict]) -> bytes:
    return json.dumps({"data": {"diff": rows}}, ensure_ascii=False).encode()


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
        return next(documents)

    mapping = next(item for item in load_seed_bundle().mappings if item.sector_key == "semiconductor")
    provider = EastmoneyBoardSpotProvider(transport=transport)
    bar = provider.fetch_intraday_snapshot(mapping, datetime(2026, 7, 28, 5, 14, 15, tzinfo=timezone.utc))
    assert (bar.symbol, bar.symbol_name, bar.trade_date.isoformat()) == ("BK1036", "半导体", "2026-07-28")
    assert (str(bar.close), str(bar.pre_close), str(bar.pct_change)) == ("2564.28", "2675.21", "-4.15")
    assert bar.volume and bar.amount and bar.source_payload_hash
    provider.fetch_intraday_snapshot(mapping, datetime(2026, 7, 28, 5, 15, tzinfo=timezone.utc))
    assert len(calls) == provider.request_count == 2


def test_eastmoney_spot_cache_expires_at_next_server_cycle() -> None:
    calls: list[str] = []

    def transport(url: str, _timeout: float) -> bytes:
        calls.append(url)
        return payload([{
            "f2": 2564.28, "f3": -4.15, "f5": 33550000, "f6": 27040000000,
            "f12": "BK1036", "f14": "半导体", "f15": 2675.09, "f16": 2543.61,
            "f17": 2611.05, "f18": 2675.21,
        }]) if len(calls) % 2 else payload([])

    mapping = next(item for item in load_seed_bundle().mappings if item.sector_key == "semiconductor")
    provider = EastmoneyBoardSpotProvider(transport=transport)
    provider.fetch_intraday_snapshot(mapping, datetime(2026, 7, 28, 5, 14, tzinfo=timezone.utc))
    provider.begin_cycle()
    provider.fetch_intraday_snapshot(mapping, datetime(2026, 7, 28, 5, 19, tzinfo=timezone.utc))
    assert len(calls) == 4 and provider.request_count == 2


def test_eastmoney_spot_rejects_unmapped_custom_composite() -> None:
    mapping = next(item for item in load_seed_bundle().mappings if item.primary_symbol.startswith("CUSTOM_"))
    provider = EastmoneyBoardSpotProvider(transport=lambda *_: payload([]))
    with pytest.raises(ProviderError, match="custom composite"):
        provider.fetch_intraday_snapshot(mapping, datetime(2026, 7, 28, 5, 14, tzinfo=timezone.utc))


def test_eastmoney_transport_classifies_remote_disconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    def disconnect(*_args: object, **_kwargs: object) -> object:
        raise RemoteDisconnected("closed")

    monkeypatch.setattr(eastmoney_spot, "urlopen", disconnect)
    with pytest.raises(ProviderError, match="spot request failed") as caught:
        eastmoney_spot._transport("https://example.invalid", 1)
    assert caught.value.retryable is True
