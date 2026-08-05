from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest

from leopard_project.config import CONFIG_DIR
from leopard_project.providers.tencent_standard_quote import TencentStandardSecurityQuoteProvider, load_tencent_quote_config
from leopard_project.security_proxy_observation import (
    APPROVED, FIXED_DISCLOSURE, SecurityProxyObservationService, SecurityProxyRegistryError,
    load_security_proxy_registry, validate_security_proxy_registry,
)


NOW = datetime.fromisoformat("2026-08-04T14:40:00+08:00")


def registry_document() -> dict:
    return json.loads((CONFIG_DIR / "security_proxy_registry_v1.json").read_text(encoding="utf-8"))


def wire_record(symbol: str, *, current: str = "10.02") -> str:
    values = [""] * 88
    values[1], values[2], values[3], values[4], values[30], values[31], values[32], values[35] = symbol, symbol[2:], current, "10.00", "20260804143930", str(float(current) - 10), str((float(current) / 10 - 1) * 100), f"{current}/1/1"
    return f'v_{symbol}="{"~".join(values)}";'


def service(payload: bytes, *, calls: list[str] | None = None) -> SecurityProxyObservationService:
    config = load_tencent_quote_config()
    provider = TencentStandardSecurityQuoteProvider(transport=lambda url, _timeout: (calls.append(url) if calls is not None else None) or payload, config=config, now=lambda: NOW)
    return SecurityProxyObservationService(provider=provider, now=lambda: NOW)


def test_registry_has_default_disabled_11_approved_and_two_explicit_gaps() -> None:
    document, paths = registry_document(), load_security_proxy_registry()
    assert document["default_enabled"] is False and len([item for item in paths if item.status == APPROVED]) == 11
    assert {item.market_path_key for item in paths if item.status != APPROVED} == {"glass_substrate", "catering"}
    assert all(not item.production_enabled and item.official_board_preferred and item.fallback_only for item in paths)


def test_cpo_mapping_and_all_path_proxy_limits() -> None:
    paths = {item.market_path_key: item for item in load_security_proxy_registry()}
    cpo = paths["cpo"]
    assert [item.symbol for item in cpo.etf_proxies] == ["sh515880"]
    assert [item.symbol for item in cpo.leader_proxies] == ["sz300308", "sz300502", "sz300394"]
    for item in paths.values():
        assert len(item.etf_proxies) <= 1 and len(item.leader_proxies) <= (3 if item.priority_theme else 1)
        assert item.disclosure


def test_static_observation_lists_are_fixed_and_innovative_medicine_has_four_instruments() -> None:
    paths = {item.market_path_key: item for item in load_security_proxy_registry()}
    expected = {
        "commercial_space": ["sh600118"], "computing_power_rental": ["sh516510", "sz300442"],
        "liquid_cooling": ["sz002837"], "ai_applications": ["sz159819", "sz002230"],
        "internet_finance": ["sz159851", "sz300033"], "optical_fiber_theme": ["sh515880", "sh600487"],
        "rare_earth": ["sh516780", "sh600111"], "semiconductor": ["sz159995", "sh688981"],
        "hotel": ["sz159766", "sh600754"],
    }
    assert [item.symbol for item in paths["innovative_drug_medicine"].instruments] == ["sz159992", "sh600276", "sh603259", "sz300760"]
    assert [item.proxy_role for item in paths["innovative_drug_medicine"].instruments] == ["etf", "leader", "leader", "leader"]
    assert all([item.symbol for item in paths[key].instruments] == symbols for key, symbols in expected.items())


@pytest.mark.parametrize("mutation", ["compact", "duplicate_symbol", "duplicate_order", "no_reliable_instrument"])
def test_registry_rejects_invalid_symbols_and_structure(mutation: str) -> None:
    document = registry_document()
    cpo = document["paths"][0]
    if mutation == "compact": cpo["etf_proxies"][0]["symbol"] = "s_sh515880"
    elif mutation == "duplicate_symbol": cpo["leader_proxies"][0]["symbol"] = "sh515880"
    elif mutation == "duplicate_order": cpo["leader_proxies"][0]["display_order"] = 1
    else: document["paths"][-1]["leader_proxies"] = [deepcopy(cpo["leader_proxies"][0])]
    with pytest.raises(SecurityProxyRegistryError): validate_security_proxy_registry(document)


def test_default_disabled_service_never_calls_provider() -> None:
    calls: list[str] = []
    observations = service(b"unexpected", calls=calls).observe(["cpo", "glass_substrate"])
    assert calls == [] and observations[0].status == "disabled" and observations[1].status == "not_configured"


def test_explicit_observation_deduplicates_shared_symbol_and_keeps_independent_quotes() -> None:
    calls: list[str] = []
    symbols = ["sh515880", "sz300308", "sz300502", "sz300394", "sh600487"]
    payload = "\n".join(wire_record(symbol) for symbol in symbols).encode("gbk")
    observations = service(payload, calls=calls).observe(["cpo", "optical_fiber_theme"], enable_provider=True)
    assert len(calls) == 1 and calls[0].count("sh515880") == 1
    assert observations[0].status == observations[1].status == "available"
    assert all(item.current is not None for row in observations for item in row.instruments)
    assert not hasattr(observations[0], "aggregate_pct_change") and not hasattr(observations[0], "synthetic_market_return")


def test_innovative_medicine_returns_four_independent_instruments_without_aggregate() -> None:
    symbols = ["sz159992", "sh600276", "sh603259", "sz300760"]
    observation = service("\n".join(wire_record(symbol) for symbol in symbols).encode("gbk")).observe(["innovative_drug_medicine"], enable_provider=True)[0]
    assert [item.symbol for item in observation.instruments] == symbols
    assert [item.proxy_role for item in observation.instruments] == ["etf", "leader", "leader", "leader"]
    assert all(item.current is not None for item in observation.instruments)
    assert not hasattr(observation, "aggregate_pct_change") and not hasattr(observation, "average_return") and not hasattr(observation, "weighted_return")
    assert "非板块指数" in observation.disclosure and FIXED_DISCLOSURE in registry_document()["disclosure"]


def test_single_failure_partial_and_all_failure_unavailable_without_zero_fill() -> None:
    single = service(wire_record("sh515880").encode("gbk")).observe(["cpo"], enable_provider=True)[0]
    assert single.status == "partial" and single.instruments[0].quote_status == "available"
    assert all(item.current is None for item in single.instruments[1:])
    empty = service(b"").observe(["liquid_cooling"], enable_provider=True)[0]
    assert empty.status == "unavailable" and empty.instruments[0].current is None and empty.instruments[0].error_class == "empty_reply"


def test_etf_or_leader_failure_does_not_block_the_other_instrument() -> None:
    only_leader = service(wire_record("sh600111").encode("gbk")).observe(["rare_earth"], enable_provider=True)[0]
    only_etf = service(wire_record("sh516780").encode("gbk")).observe(["rare_earth"], enable_provider=True)[0]
    assert only_leader.status == only_etf.status == "partial"
    assert {item.quote_status for item in only_leader.instruments} == {"available", "unavailable"}


def test_stale_quote_is_exposed_as_unavailable() -> None:
    stale = wire_record("sz002837").replace("20260804143930", "20260804130000").encode("gbk")
    observation = service(stale).observe(["liquid_cooling"], enable_provider=True)[0]
    assert observation.status == "unavailable" and observation.instruments[0].error_class == "stale_quote"


def test_registry_does_not_modify_official_market_registry_or_expose_runtime_integrations() -> None:
    registry = (CONFIG_DIR / "market_path_registry_v1.json").read_text(encoding="utf-8")
    source = Path("backend/leopard_project/security_proxy_observation.py").read_text(encoding="utf-8")
    assert "security_proxy" not in registry
    assert "Scheduler" in source and "database" in source and "API" in source and "UI" in source
    assert FIXED_DISCLOSURE in registry_document()["disclosure"]
