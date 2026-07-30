from __future__ import annotations

from datetime import datetime, timezone

import pytest

from leopard_project.config import load_seed_bundle
from leopard_project.market_paths import load_market_path_registry, market_path_mapping
from leopard_project.models import DataStatus
from leopard_project.providers import ProviderError, ThsExactSpotProvider
from leopard_project.providers.capabilities import load_provider_capabilities, provider_capability_summary
from tests.test_intraday_provider_chain import detail_html, history_callback


NOW = datetime(2026, 7, 29, 2, 0, tzinfo=timezone.utc)


def test_report_topics_remain_frozen_while_active_market_paths_split() -> None:
    bundle = load_seed_bundle()
    registry = load_market_path_registry(bundle)
    report_keys = {item.sector_key for item in bundle.sectors}
    market_keys = {item.market_path_key for item in registry.market_paths}
    assert len(report_keys) == registry.report_topic_count == 66
    assert "hotel_catering" in report_keys
    assert "hotel" not in report_keys and "catering" not in report_keys
    assert "hotel_catering" not in market_keys
    assert {"hotel", "catering"} <= market_keys
    assert len(registry.supported_market_paths) == 66
    assert len(registry.unsupported_market_paths) == 1
    assert registry.unsupported_market_paths[0].market_path_key == "hang_seng_tech"


def test_capability_classification_is_dynamic_and_fail_closed() -> None:
    rows = load_provider_capabilities()
    summary = provider_capability_summary(rows)
    assert summary == {
        "matrix_total": 66,
        "validated_direct": 61,
        "validated_proxy": 1,
        "validated_composite": 3,
        "operational_coverage": 65,
        "unverified": 1,
        "no_mapping": 1,
        "spot_complete": 65,
        "history_complete": 65,
        "ma5_capable": 65,
    }
    assert rows["hotel"].selectable_candidates[0].provider_name == "旅游及酒店"
    assert rows["hotel"].selectable_candidates[0].symbol == "881160"
    assert rows["hotel"].mapping_type == "proxy"
    assert rows["catering"].mapping_type == "direct"
    assert not rows["catering"].selectable_candidates


def test_881160_requires_official_name_and_is_an_explicit_hotel_proxy() -> None:
    payload = detail_html("旅游及酒店", "881160")
    parsed = ThsExactSpotProvider._parse_detail(payload, name="旅游及酒店", symbol="881160")
    assert parsed["current"] > 0 and parsed["pre_close"] > 0
    with pytest.raises(ProviderError, match="fields are unavailable"):
        ThsExactSpotProvider._parse_detail(payload, name="酒店餐饮", symbol="881160")

    path = next(item for item in load_market_path_registry().market_paths if item.market_path_key == "hotel")
    mapping = market_path_mapping(path)

    def transport(url: str, _timeout: float) -> bytes:
        return payload if "q.10jqka.com.cn" in url else history_callback("881160")

    bar = ThsExactSpotProvider(transport=transport).fetch_intraday_snapshot(mapping, NOW)
    assert bar.data_status == DataStatus.PROXY
    assert bar.provider_symbol == "881160"
    assert "canonical_market_path=hotel" in (bar.lineage or "")
    assert "provider_name=旅游及酒店" in (bar.lineage or "")
    assert "same_provider_same_symbol=true" in (bar.lineage or "")


def test_composite_uses_unchanged_components_and_same_synthetic_symbol_history() -> None:
    rows = load_provider_capabilities()
    capability = rows["food_beverage"]
    candidate = capability.selectable_candidates[0]
    assert [(row["symbol"], row["weight"]) for row in candidate.components] == [
        ("881134", 0.5),
        ("881133", 0.5),
    ]
    path = next(item for item in load_market_path_registry().market_paths if item.market_path_key == "food_beverage")
    mapping = market_path_mapping(path).model_copy(update={"primary_symbol": candidate.symbol})

    def transport(url: str, _timeout: float) -> bytes:
        symbol = "881134" if "881134" in url else "881133"
        name = "食品加工制造" if symbol == "881134" else "饮料制造"
        return detail_html(name, symbol) if "q.10jqka.com.cn" in url else history_callback(symbol)

    bar = ThsExactSpotProvider(transport=transport).fetch_intraday_snapshot(mapping, NOW)
    assert bar.provider_symbol == candidate.symbol == "881134+881133"
    assert len(bar.provider_native_history) == 4
    assert all(item.provider == bar.provider for item in bar.provider_native_history)
    assert all(item.provider_symbol == candidate.symbol for item in bar.provider_native_history)
    assert "mapping_type=composite" in (bar.lineage or "")
    assert "fail_closed=true" in (bar.lineage or "")


def test_catering_has_no_silent_food_or_prepared_food_substitution() -> None:
    row = load_provider_capabilities()["catering"]
    serialized = " ".join((row.display_name, row.primary_provider, *(item.provider_name for item in row.candidates)))
    assert "食品饮料" not in serialized
    assert "预制菜" not in serialized
    assert "旅游" not in serialized
    assert "酒店" not in serialized
