from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path

import pytest

from leopard_project.security_proxy_dynamic_selection import (
    SecurityProxyDynamicSelectionError, SecurityProxyDynamicSelectionService, SecurityProxySelectionPreference, SecurityProxySelectionSnapshotStore, load_selection_preferences,
)
from leopard_project.security_proxy_eod import SHANGHAI, SecurityProxyEodRecord
from leopard_project.security_proxy_eod_selection import SecurityProxyCandidate, load_security_proxy_candidate_pool


DAY = date(2026, 8, 5)


def record(symbol: str, day: date, *, low: str = "9", close: str = "10", amount: str | None = "100") -> SecurityProxyEodRecord:
    return SecurityProxyEodRecord(symbol, symbol, day, Decimal("10"), Decimal("12"), Decimal(low), Decimal(close), Decimal(amount) if amount else None, datetime(day.year, day.month, day.day, 15, 1, tzinfo=SHANGHAI), datetime.now(timezone.utc), completeness_status="complete" if amount else "partial_amount_missing")


def history(symbol: str, *, amount: str = "100", rebound: bool = False) -> list[SecurityProxyEodRecord]:
    previous: list[date] = []
    cursor = DAY - timedelta(days=1)
    while len(previous) < 19:
        if cursor.weekday() < 5: previous.append(cursor)
        cursor -= timedelta(days=1)
    days = list(reversed(previous)) + [DAY]
    return [record(symbol, day, low="5" if rebound and i == 0 else "9", close="10" if i < len(days) - 1 else "12", amount=amount) for i, day in enumerate(days)]


def test_preferences_cover_exactly_the_approved_paths_and_keep_manual_contracts() -> None:
    preferences = {item.market_path_key: item for item in load_selection_preferences()}
    assert len(preferences) == 11
    assert preferences["cpo"].required_symbols == ("sz300308", "sz300502", "sz300394")
    assert preferences["innovative_drug_medicine"].required_symbols == ("sh603259", "sz300760")
    assert preferences["semiconductor"].excluded_symbols == ("sz300474",)
    assert preferences["cpo"].curated_etf_symbol == "sh515880"
    assert preferences["commercial_space"].curated_etf_symbol is None
    assert all(item.curated_etf_replaceable for item in preferences.values())


def test_curated_etf_and_required_leaders_work_without_aum_or_history() -> None:
    service = SecurityProxyDynamicSelectionService(now=lambda: datetime(2026, 8, 5, tzinfo=timezone.utc))
    cpo = next(item for item in service.build(DAY, [record("sz300308", DAY), record("sz300502", DAY), record("sz300394", DAY)]) if item.market_path_key == "cpo")
    assert [item.symbol for item in cpo.selected_instruments] == ["sz300308", "sz300502", "sz300394", "sh515880"]
    assert all("required_manual" in item.selection_reasons for item in cpo.selected_instruments[:3])
    assert cpo.selected_instruments[-1].selection_reasons == ("curated_observation_etf",)
    assert cpo.selected_instruments[-1].selection_source == "curated_configuration"


def test_twenty_day_low_rebound_turnover_and_dedup_are_deterministic() -> None:
    service = SecurityProxyDynamicSelectionService(now=lambda: datetime(2026, 8, 5, tzinfo=timezone.utc))
    values = history("sh600111", amount="500", rebound=True) + history("sz000831", amount="100") + history("sz000970", amount="800")
    rare = next(item for item in service.build(DAY, values) if item.market_path_key == "rare_earth")
    selected = {item.symbol: item for item in rare.selected_instruments}
    assert selected["sh516780"].selection_reasons == ("curated_observation_etf",)
    assert "approved_large_cap_candidate" in selected["sh600111"].selection_reasons
    assert "fastest_20d_rebound" in selected["sh600111"].selection_reasons
    assert "highest_latest_turnover" in selected["sz000970"].selection_reasons


def test_insufficient_history_keeps_manual_list_with_explicit_warning() -> None:
    service = SecurityProxyDynamicSelectionService(now=lambda: datetime(2026, 8, 5, tzinfo=timezone.utc))
    rare = next(item for item in service.build(DAY, [record("sh600111", DAY), record("sz000831", DAY), record("sz000970", DAY)]) if item.market_path_key == "rare_earth")
    assert any(value.startswith("insufficient_fastest_20d_rebound") for value in rare.warnings)
    assert [item.symbol for item in rare.selected_instruments][:2] == ["sh516780", "sh600111"]


def test_snapshot_is_atomic_immutable_and_only_effective_next_trading_day(tmp_path: Path) -> None:
    service = SecurityProxyDynamicSelectionService(now=lambda: datetime(2026, 8, 5, tzinfo=timezone.utc))
    snapshots = service.build(DAY, [record("sz300308", DAY), record("sz300502", DAY), record("sz300394", DAY)])
    store = SecurityProxySelectionSnapshotStore(tmp_path)
    path = store.write(calculation_date=DAY, snapshots=snapshots)
    assert path.exists() and not store.latest_effective_for(DAY)
    assert "cpo" in store.latest_effective_for(date(2026, 8, 6))
    with pytest.raises(FileExistsError): store.write(calculation_date=DAY, snapshots=snapshots)


def test_duplicate_history_fails_closed() -> None:
    service = SecurityProxyDynamicSelectionService()
    with pytest.raises(SecurityProxyDynamicSelectionError, match="duplicate"):
        service.build(DAY, [record("sh600111", DAY), record("sh600111", DAY)])


def custom_etf_service(*, curated: str | None, caps=None):
    _, pools = load_security_proxy_candidate_pool(); base = next(item for item in pools if item.market_path_key == "cpo")
    first = base.etf_candidates[0]
    second = replace(first, symbol="sh510300", security_name="沪深300ETF", display_priority=2)
    stocks = tuple(replace(item, enabled=False) for item in base.stock_candidates)
    pool = replace(base, etf_candidates=(first, second), stock_candidates=stocks, required_instruments=(), maximum_leaders=0)
    preference = SecurityProxySelectionPreference(
        market_path_key="cpo", enabled=True, required_symbols=(),
        eligible_etf_symbols=(first.symbol, second.symbol), eligible_large_cap_symbols=(),
        auto_rebound_slots=0, auto_turnover_slots=0, excluded_symbols=(),
        approval_note="test", approved_at=DAY, policy_version="test",
        curated_etf_symbol=curated, curated_etf_note="test" if curated else None,
    )
    return SecurityProxyDynamicSelectionService(preferences=(preference,), pools=(pool,), verified_market_caps=caps, now=lambda: datetime(2026, 8, 5, tzinfo=timezone.utc)), first, second


def test_etf_uses_exact_curated_symbol_and_never_compares_aum_or_turnover() -> None:
    service, first, second = custom_etf_service(curated="sh510300")
    result = service.build(DAY, []) [0]
    assert result.selected_instruments[0].symbol == second.symbol
    assert result.selected_instruments[0].selection_reasons == ("curated_observation_etf",)
    assert "aum" not in str(result).lower() and "liquidity" not in str(result).lower()


def test_legacy_eligible_config_is_readable_but_does_not_force_an_etf(tmp_path: Path) -> None:
    service, _first, _second = custom_etf_service(curated=None)
    assert service.build(DAY, [])[0].selected_instruments == ()
    document = json.loads(Path("config/security_proxy_selection_preferences_v1.json").read_text(encoding="utf-8"))
    for path in document["paths"]:
        path.pop("curated_etf_symbol", None)
        path.pop("curated_etf_note", None)
        path.pop("curated_etf_reviewed_at", None)
        path.pop("curated_etf_coverage", None)
        path.pop("curated_etf_replaceable", None)
        path["preferred_etf_symbols"] = path.pop("eligible_etf_symbols")
        path["preferred_large_cap_symbols"] = path.pop("eligible_large_cap_symbols")
    legacy = tmp_path / "legacy.json"; legacy.write_text(json.dumps(document), encoding="utf-8")
    assert all(item.migration_warnings for item in load_selection_preferences(legacy))


def test_curated_symbol_must_be_an_approved_etf(tmp_path: Path) -> None:
    document = json.loads(Path("config/security_proxy_selection_preferences_v1.json").read_text(encoding="utf-8"))
    next(path for path in document["paths"] if path["market_path_key"] == "cpo")["curated_etf_symbol"] = "sz300308"
    invalid = tmp_path / "invalid-curated.json"; invalid.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(SecurityProxyDynamicSelectionError, match="curated ETF"):
        load_selection_preferences(invalid)


def test_curated_etf_is_available_with_one_day_or_partial_history() -> None:
    service, first, second = custom_etf_service(curated="sh510300")
    complete = history(first.symbol, amount="300") + history(second.symbol, amount="100")
    assert service.build(DAY, complete)[0].selected_instruments[0].symbol == second.symbol
    partial = [record(second.symbol, DAY - timedelta(days=index), amount="300") for index in range(5)]
    partial_result = service.build(DAY, partial)[0]
    assert partial_result.selected_instruments[0].symbol == second.symbol
    one_day = service.build(DAY, [record(second.symbol, DAY, amount="999")])[0]
    assert one_day.selected_instruments[0].symbol == second.symbol
    assert not any("liquidity" in warning or "aum" in warning for warning in one_day.warnings)


def test_large_cap_uses_verified_metric_then_approved_candidates_without_rank_claims() -> None:
    _, pools = load_security_proxy_candidate_pool(); base = next(item for item in pools if item.market_path_key == "rare_earth")
    preference = next(item for item in load_selection_preferences() if item.market_path_key == "rare_earth")
    caps = {"sh600111": Decimal("100"), "sz000831": Decimal("200")}
    ranked = SecurityProxyDynamicSelectionService(preferences=(preference,), pools=(base,), verified_market_caps=caps).build(DAY, [record("sh600111", DAY), record("sz000831", DAY), record("sz000970", DAY)])[0]
    choices = {item.symbol: item.selection_reasons for item in ranked.selected_instruments}
    assert "highest_verified_market_cap" in choices["sz000831"] and "second_verified_market_cap" in choices["sh600111"]
    fallback = SecurityProxyDynamicSelectionService(preferences=(preference,), pools=(base,)).build(DAY, [record("sh600111", DAY), record("sz000831", DAY), record("sz000970", DAY)])[0]
    reasons = {item.symbol: item.selection_reasons for item in fallback.selected_instruments}
    assert "approved_large_cap_candidate" in reasons["sh600111"] and "largest_market_cap" not in str(reasons)
