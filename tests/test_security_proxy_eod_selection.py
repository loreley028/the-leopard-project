from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from leopard_project.config import CONFIG_DIR
from leopard_project.security_proxy_eod_selection import (
    DISCLOSURE, SecurityProxyCandidate, SecurityProxyCandidateMetrics, SecurityProxyCandidatePool,
    SecurityProxyDailySelection, SecurityProxyEodBar, SecurityProxyEodSelectionService,
    SecurityProxyEtfAum, SecurityProxyExcludedInstrument, SecurityProxySelectedInstrument,
    SecurityProxySelectionError, SecurityProxySelectionPolicy, compare_selections,
    load_security_proxy_candidate_pool, selection_to_dict, validate_security_proxy_candidate_pool,
)


AS_OF = date(2026, 8, 3)
POLICY = SecurityProxySelectionPolicy("test", 20, 60)


def candidate(symbol: str, *, name: str | None = None, kind: str = "stock", enabled: bool = True, priority: int = 1) -> SecurityProxyCandidate:
    return SecurityProxyCandidate(symbol, name or symbol, kind, "candidate", "manually approved test candidate", "partial", kind == "stock", kind == "stock", kind == "stock", enabled, priority)


def pool(*, mode: str = "auto", maximum_leaders: int = 3, stocks: tuple[SecurityProxyCandidate, ...] = (), etfs: tuple[SecurityProxyCandidate, ...] = (), required: tuple[str, ...] = (), excluded: tuple[SecurityProxyExcludedInstrument, ...] = ()) -> SecurityProxyCandidatePool:
    return SecurityProxyCandidatePool("test_path", "Test", "test-pool", mode, 1 if etfs else 0, maximum_leaders, etfs, stocks, required, excluded, ("largest_market_cap", "fastest_rebound", "highest_turnover"), AS_OF, False)


def bars(symbol: str, *, close: int = 100, low: int = 80, amount: int = 100, cap: int = 100, missing: str | None = None) -> list[SecurityProxyEodBar]:
    dates: list[date] = []
    current = AS_OF
    while len(dates) < 20:
        if current.weekday() < 5: dates.append(current)
        current = date.fromordinal(current.toordinal() - 1)
    values = []
    for index, day in enumerate(reversed(dates)):
        values.append(SecurityProxyEodBar(symbol, day, Decimal(str(close - 1 + index / 100)) if missing != "close" else None, Decimal(str(low if index == 0 else close - 2)) if missing != "low" else None, Decimal(str(amount + index)) if missing != "amount" else None, Decimal(str(cap)) if missing != "cap" else None))
    assert values[-1].trade_date == AS_OF
    return values


def service(item: SecurityProxyCandidatePool) -> SecurityProxyEodSelectionService:
    return SecurityProxyEodSelectionService(policy=POLICY, pools=(item,), now=lambda: datetime(2026, 8, 4, tzinfo=timezone.utc))


def select(item: SecurityProxyCandidatePool, data: dict[str, list[SecurityProxyEodBar]], *, aums: dict[str, SecurityProxyEtfAum] | None = None, previous: SecurityProxyDailySelection | None = None):
    return service(item).select("test_path", selection_date=AS_OF, data_as_of=AS_OF, eod_bars=data, etf_aums=aums or {}, previous=previous)[0]


def test_checked_in_candidate_pool_is_versioned_manual_and_only_covers_approved_registry() -> None:
    policy, pools = load_security_proxy_candidate_pool()
    assert policy.lookback_trading_days == 20 and len(pools) == 11
    assert {item.market_path_key for item in pools} == {"cpo", "commercial_space", "computing_power_rental", "liquid_cooling", "ai_applications", "internet_finance", "optical_fiber_theme", "rare_earth", "innovative_drug_medicine", "semiconductor", "hotel"}
    assert next(item for item in pools if item.market_path_key == "cpo").required_instruments == ("sz300308", "sz300502", "sz300394")
    innovative = next(item for item in pools if item.market_path_key == "innovative_drug_medicine")
    assert innovative.selection_mode == "hybrid" and innovative.required_instruments == ("sh603259", "sz300760")
    assert "current" not in Path(CONFIG_DIR / "security_proxy_candidate_pool_v1.json").read_text(encoding="utf-8")


def test_candidate_pool_rejects_price_fields_and_registry_scope_expansion() -> None:
    document = json.loads((CONFIG_DIR / "security_proxy_candidate_pool_v1.json").read_text(encoding="utf-8"))
    document["paths"][0]["stock_candidates"][0]["current"] = "10"
    with pytest.raises(SecurityProxySelectionError, match="quote or price"):
        validate_security_proxy_candidate_pool(document)


def test_etf_uses_largest_fresh_aum_and_missing_aum_fails_closed() -> None:
    first, second = candidate("sh510001", kind="etf"), candidate("sh510002", kind="etf", priority=2)
    item = pool(etfs=(first, second))
    aums = {first.symbol: SecurityProxyEtfAum(first.symbol, Decimal("10"), AS_OF, "fixture", "partial"), second.symbol: SecurityProxyEtfAum(second.symbol, Decimal("20"), AS_OF, "fixture", "partial")}
    result = select(item, {}, aums=aums)
    assert result.selected_etf and result.selected_etf.symbol == second.symbol and result.selected_etf.selection_reasons == ("largest_aum",)
    missing = select(item, {}, aums={})
    assert missing.selected_etf is None and "no_eligible_etf" in missing.warnings


def test_stale_aum_is_warned_and_only_retains_previous_etf() -> None:
    etf = candidate("sh510001", kind="etf")
    item = pool(etfs=(etf,))
    fresh = select(item, {}, aums={etf.symbol: SecurityProxyEtfAum(etf.symbol, Decimal("10"), AS_OF, "fixture", "partial")})
    stale = SecurityProxyEtfAum(etf.symbol, Decimal("10"), date(2026, 5, 1), "fixture", "partial")
    result = select(item, {}, aums={etf.symbol: stale}, previous=fresh)
    assert result.selected_etf and result.selected_etf.selection_source == "previous_stale"
    assert any(value.startswith("aum_stale") for value in result.warnings)


def test_slots_use_complete_eod_metrics_and_candidate_pool_only() -> None:
    alpha, beta, gamma = candidate("sh600001"), candidate("sh600002", priority=2), candidate("sh600003", priority=3)
    item = pool(stocks=(alpha, beta, gamma))
    result = select(item, {alpha.symbol: bars(alpha.symbol, close=120, low=100, amount=200, cap=900), beta.symbol: bars(beta.symbol, close=140, low=70, amount=100, cap=500), gamma.symbol: bars(gamma.symbol, close=100, low=90, amount=800, cap=400), "sh600999": bars("sh600999", cap=999999, amount=999999)})
    reasons = {row.symbol: row.selection_reasons for row in result.selected_leaders}
    assert set(reasons) == {alpha.symbol, beta.symbol, gamma.symbol}
    assert "largest_market_cap" in reasons[alpha.symbol] and "fastest_rebound" in reasons[beta.symbol] and "highest_turnover" in reasons[gamma.symbol]


@pytest.mark.parametrize("missing, slot", [("close", "fastest_rebound"), ("low", "fastest_rebound"), ("cap", "largest_market_cap"), ("amount", "highest_turnover")])
def test_missing_required_eod_metric_excludes_only_its_slot(missing: str, slot: str) -> None:
    alpha, beta = candidate("sh600001"), candidate("sh600002", priority=2)
    item = replace(pool(stocks=(alpha, beta), maximum_leaders=1), auto_fill_rules=(slot,))
    result = select(item, {alpha.symbol: bars(alpha.symbol, missing=missing), beta.symbol: bars(beta.symbol, cap=200, amount=200, close=120, low=70)})
    assert result.selected_leaders[0].symbol == beta.symbol and result.selected_leaders[0].selection_reasons == (slot,)


def test_dedup_keeps_multiple_reasons_and_backfills_next_candidate() -> None:
    alpha, beta, gamma = candidate("sh600001"), candidate("sh600002", priority=2), candidate("sh600003", priority=3)
    item = pool(stocks=(alpha, beta, gamma))
    result = select(item, {alpha.symbol: bars(alpha.symbol, close=200, low=50, amount=900, cap=900), beta.symbol: bars(beta.symbol, close=140, low=100, amount=500, cap=500), gamma.symbol: bars(gamma.symbol, close=120, low=110, amount=300, cap=300)})
    assert [row.symbol for row in result.selected_leaders] == [alpha.symbol, beta.symbol, gamma.symbol]
    assert result.selected_leaders[0].selection_reasons == ("largest_market_cap", "fastest_rebound", "highest_turnover")


def test_required_excluded_manual_and_hybrid_rules_are_fail_closed() -> None:
    core, optional, blocked = candidate("sh600001"), candidate("sh600002", priority=2), candidate("sh600003", priority=3)
    data = {core.symbol: bars(core.symbol, cap=1, amount=1), optional.symbol: bars(optional.symbol, cap=100, amount=100), blocked.symbol: bars(blocked.symbol, cap=999, amount=999)}
    manual = pool(mode="manual", maximum_leaders=2, stocks=(core, optional), required=(core.symbol,))
    manual_result = select(manual, data)
    assert [row.symbol for row in manual_result.selected_leaders] == [core.symbol] and manual_result.selected_leaders[0].display_reason == "固定核心观察"
    hybrid = pool(mode="hybrid", maximum_leaders=2, stocks=(core, optional, blocked), required=(core.symbol,), excluded=(SecurityProxyExcludedInstrument(blocked.symbol, "product exclusion"),))
    hybrid_result = select(hybrid, data)
    assert [row.symbol for row in hybrid_result.selected_leaders] == [core.symbol, optional.symbol]
    assert all(row.symbol != blocked.symbol for row in hybrid_result.selected_leaders)


def test_required_instrument_is_not_replaced_when_its_eod_input_is_incomplete() -> None:
    core, optional = candidate("sh600001"), candidate("sh600002", priority=2)
    item = pool(mode="hybrid", maximum_leaders=2, stocks=(core, optional), required=(core.symbol,))
    result = select(item, {core.symbol: bars(core.symbol, missing="close"), optional.symbol: bars(optional.symbol, cap=100, amount=100)})
    assert result.selected_leaders[0].symbol == core.symbol and result.selected_leaders[0].selection_source == "manual_required"
    assert result.status == "partial" and f"required_instrument_eod_incomplete:{core.symbol}" in result.warnings


def test_eod_symbol_mismatch_and_duplicate_date_fail_closed() -> None:
    alpha = candidate("sh600001")
    item = pool(stocks=(alpha,), maximum_leaders=1)
    mismatched = bars("sh600002")
    with pytest.raises(SecurityProxySelectionError, match="does not match"):
        select(item, {alpha.symbol: mismatched})
    duplicate = bars(alpha.symbol) + [bars(alpha.symbol)[-1]]
    with pytest.raises(SecurityProxySelectionError, match="duplicate"):
        select(item, {alpha.symbol: duplicate})


def test_cpo_and_innovative_manual_contracts_are_preserved() -> None:
    _, pools = load_security_proxy_candidate_pool()
    cpo = next(item for item in pools if item.market_path_key == "cpo")
    innovative = next(item for item in pools if item.market_path_key == "innovative_drug_medicine")
    cpo_result, _ = SecurityProxyEodSelectionService(now=lambda: datetime.now(timezone.utc)).select("cpo", selection_date=AS_OF, data_as_of=AS_OF, eod_bars={item.symbol: bars(item.symbol, cap=1, amount=1) for item in cpo.stock_candidates}, etf_aums={"sh515880": SecurityProxyEtfAum("sh515880", Decimal("10"), AS_OF, "fixture", "partial")})
    assert [row.symbol for row in cpo_result.selected_leaders] == list(cpo.required_instruments)
    assert all(row.selection_source == "manual_required" for row in cpo_result.selected_leaders)
    innovative_result, _ = SecurityProxyEodSelectionService(now=lambda: datetime.now(timezone.utc)).select("innovative_drug_medicine", selection_date=AS_OF, data_as_of=AS_OF, eod_bars={item.symbol: bars(item.symbol, cap=index + 1, amount=index + 1) for index, item in enumerate(innovative.stock_candidates)}, etf_aums={"sz159992": SecurityProxyEtfAum("sz159992", Decimal("10"), AS_OF, "fixture", "partial")})
    assert [row.symbol for row in innovative_result.selected_leaders[:2]] == ["sh603259", "sz300760"] and len(innovative_result.selected_leaders) == 3


def test_tie_break_and_repeat_results_are_deterministic() -> None:
    alpha, beta = candidate("sh600002"), candidate("sh600001", priority=2)
    item = pool(stocks=(alpha, beta), maximum_leaders=1)
    values = {alpha.symbol: bars(alpha.symbol, cap=100, amount=100), beta.symbol: bars(beta.symbol, cap=100, amount=100)}
    first, second = select(item, values), select(item, values)
    assert first.selected_leaders[0].symbol == "sh600001" and selection_to_dict(first) == selection_to_dict(second)


def test_selection_comparison_and_serialization_contain_auditable_versions_without_aggregate_return() -> None:
    alpha = candidate("sh600001")
    item = pool(stocks=(alpha,), maximum_leaders=1)
    current = select(item, {alpha.symbol: bars(alpha.symbol)})
    comparison = compare_selections(current, None)
    serialized = json.dumps({"selection": selection_to_dict(current), "comparison": selection_to_dict(comparison)}, ensure_ascii=False)
    assert current.candidate_pool_version == "test-pool" and current.policy_version == "test"
    assert current.selected_leaders[0].metrics_as_of == AS_OF and comparison.added_symbols == (alpha.symbol,)
    assert "aggregate_pct_change" not in serialized and "synthetic_index" not in serialized and "weighted_return" not in serialized


def test_selection_is_explicit_and_has_no_provider_scheduler_database_or_viewer_dependency() -> None:
    source = Path("backend/leopard_project/security_proxy_eod_selection.py").read_text(encoding="utf-8").lower()
    assert "tencent" not in source and "sqlalchemy" not in source and "from .providers" not in source and "from .web" not in source
    assert DISCLOSURE in source
