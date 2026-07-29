from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from leopard_project.config import load_seed_bundle
from leopard_project.providers import ProviderError, ResearchIntradayProviderChain, ThsExactSpotProvider


def detail_html(name: str, symbol: str) -> bytes:
    return f"""
    <html><body><h3>{name}{symbol}</h3><strong>1265.88</strong><span>43.63</span><span>3.57%</span>
    <dl><dt>今开</dt><dd>1216.19</dd><dt>昨收</dt><dd>1222.25</dd>
    <dt>最低</dt><dd>1213.88</dd><dt>最高</dt><dd>1265.88</dd>
    <dt>成交量(万手)</dt><dd>5649.89</dd><dt>成交额(亿)</dt><dd>1010.78</dd></dl></body></html>
    """.encode()


def history_callback(symbol: str) -> bytes:
    data = ";".join([
        "20260722,1180,1190,1170,1185,1,1",
        "20260723,1185,1200,1180,1195,1,1",
        "20260724,1195,1210,1190,1205,1,1",
        "20260728,1205,1225,1200,1222.25,1,1",
    ])
    return f"callback({json.dumps({'data': data})})".encode()


def test_ths_exact_provider_uses_exact_code_and_same_symbol_history() -> None:
    calls: list[str] = []

    def transport(url: str, _timeout: float) -> bytes:
        calls.append(url)
        return detail_html("算力租赁", "886050") if "q.10jqka.com.cn" in url else history_callback("886050")

    mapping = next(item for item in load_seed_bundle().mappings if item.sector_key == "computing_power_rental")
    bar = ThsExactSpotProvider(transport=transport).fetch_intraday_snapshot(
        mapping, datetime(2026, 7, 29, 2, 0, tzinfo=timezone.utc),
    )
    assert bar.provider == "ths_exact_spot"
    assert bar.provider_symbol == bar.symbol == "886050"
    assert bar.symbol_name == "算力租赁"
    assert len(bar.provider_native_history) == 4
    assert all(item.provider == bar.provider and item.provider_symbol == bar.provider_symbol for item in bar.provider_native_history)
    assert all("886050" in url for url in calls)


def test_ths_exact_mapping_fails_closed_for_unlisted_or_conflicting_sector() -> None:
    mapping = next(item for item in load_seed_bundle().mappings if item.sector_key == "cpo")
    with pytest.raises(ProviderError, match="unavailable"):
        ThsExactSpotProvider(transport=lambda *_: b"").fetch_intraday_snapshot(
            mapping, datetime(2026, 7, 29, 2, 0, tzinfo=timezone.utc),
        )


def test_targeted_mappings_are_explicit_and_not_fuzzy_eastmoney_candidates() -> None:
    provider = ThsExactSpotProvider(transport=lambda *_: b"")
    expected = {
        "computing_power_rental": ("886050", "算力租赁"),
        "retail": ("881158", "零售"),
        "small_appliances": ("881173", "小家电"),
    }
    for sector_key, (symbol, name) in expected.items():
        item = provider._mappings[sector_key]
        assert item["provider_symbol"] == symbol
        assert item["provider_name"] == name
        assert item["mapping_confidence"] == "high"
    assert ResearchIntradayProviderChain.ths_exact_sector_keys == set(expected)
