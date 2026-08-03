from __future__ import annotations

import csv
import copy
import importlib.util
import json
import os
from pathlib import Path
import socket

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts/analyze_tushare_theme_basket_coverage.py"
CONFIG_PATH = ROOT / "config/research/tushare_theme_basket_research_v1.json"
SPEC = importlib.util.spec_from_file_location("tushare_theme_basket_coverage", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.fixture(scope="module")
def analysis() -> dict:
    return MODULE.build_analysis(generated_at="2026-08-03T00:00:00+00:00")


def _write_config(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "research.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def test_registry_total_is_dynamic_and_hstech_excluded(analysis: dict) -> None:
    from leopard_project.market_paths import load_market_path_registry

    registry = load_market_path_registry()
    assert analysis["summary"]["matrix_total"] == len(registry.supported_market_paths) == 66
    assert [path.market_path_key for path in registry.unsupported_market_paths] == ["hang_seng_tech"]
    assert "hang_seng_tech" not in {row["market_path_key"] for row in analysis["theme_paths"]}


def test_prior_official_baseline_is_unchanged(analysis: dict) -> None:
    summary = analysis["summary"]
    assert summary["official_exact"] == 45
    assert summary["acceptable_proxy"] == 7
    assert summary["official_and_proxy_coverage"] == 52


def test_three_composites_are_pending_and_not_production(analysis: dict) -> None:
    assert analysis["summary"]["pending_composites"] == 3
    assert set(analysis["composites"]) == {
        "food_beverage", "photovoltaic_energy_storage", "oil_petrochemical",
    }
    assert all(item["requires_user_approval"] is True for item in analysis["composites"].values())
    assert all(item["production_approved"] is False for item in analysis["composites"].values())


def test_composite_components_and_weights_are_transparent(analysis: dict) -> None:
    for composite in analysis["composites"].values():
        assert len(composite["components"]) == 2
        assert sum(item["weight"] for item in composite["components"]) == pytest.approx(1.0)
        assert {item["provider"] for item in composite["components"]} == {"tushare_sw"}
        assert [algorithm["name"] for algorithm in composite["algorithms"]] == [
            "equal_weight_index_return", "fixed_explicit_business_weight",
        ]
        assert composite["component_overlap"] == "unverified_without_constituent_snapshot"


def test_composites_raise_theoretical_count_to_55_only_if_approved(analysis: dict) -> None:
    summary = analysis["summary"]
    assert summary["coverage_if_composites_approved"] == 55
    assert summary["promising_theoretical_coverage"] == 55


def test_theme_scope_partitions_all_remaining_paths(analysis: dict) -> None:
    assert analysis["summary"]["theme_paths"] == 11
    assert len(analysis["theme_paths"]) == 11
    assert len({row["market_path_key"] for row in analysis["theme_paths"]}) == 11
    assert 52 + 3 + 11 == analysis["summary"]["matrix_total"]
    assert set(analysis["composites"]).isdisjoint({row["market_path_key"] for row in analysis["theme_paths"]})


def test_custom_baskets_are_never_mislabeled_as_direct(analysis: dict) -> None:
    assert all(row["research_mapping_type"] == "custom_basket" for row in analysis["theme_paths"])
    assert all(row["display_name"].endswith("（自定义篮子）") for row in analysis["theme_paths"])
    assert all(row["production_approved"] is False for row in analysis["theme_paths"])
    assert analysis["production_enabled"] is False


def test_each_basket_materializes_the_full_research_definition(analysis: dict) -> None:
    required = {
        "canonical_market_path", "membership_source", "source_concept_name", "source_concept_code",
        "membership_as_of", "constituent_inclusion_rule", "constituent_exclusion_rule",
        "weighting_method", "weighting_candidates", "rebalance_frequency", "missing_quote_policy",
        "suspended_stock_policy", "st_stock_policy", "newly_listed_stock_policy",
        "minimum_valid_constituent_count", "maximum_single_stock_weight", "current_calculation",
        "pre_close_calculation", "history_calculation", "ma5_calculation", "lineage", "display_disclosure",
    }
    for row in analysis["theme_paths"]:
        assert set(row["basket_definition"]) == required
        assert row["basket_definition"]["canonical_market_path"] == row["market_path_key"]


def test_offline_unverified_membership_is_not_counted_promising(analysis: dict) -> None:
    assert analysis["summary"]["custom_basket_promising"] == 0
    assert all(row["membership_verified"] is False for row in analysis["theme_paths"])
    assert not any(row["counted_in_promising_coverage"] for row in analysis["theme_paths"])


def test_unverified_membership_cannot_be_configured_as_promising(tmp_path: Path) -> None:
    document = copy.deepcopy(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    document["theme_paths"]["cpo"]["final_research_status"] = "custom_basket_promising"
    with pytest.raises(ValueError, match="promising_basket_requires_verified_membership:cpo"):
        MODULE.load_research_config(_write_config(tmp_path, document))


def test_low_semantic_confidence_cannot_be_configured_as_promising(tmp_path: Path) -> None:
    document = copy.deepcopy(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    cpo = document["theme_paths"]["cpo"]
    cpo["final_research_status"] = "custom_basket_promising"
    cpo["semantic_confidence"] = "medium"
    for source in ("ths_candidates", "dc_candidates"):
        for candidate in cpo[source]:
            candidate["membership_verified"] = True
            candidate["constituent_count"] = 10
    with pytest.raises(ValueError, match="promising_basket_requires_high_confidence:cpo"):
        MODULE.load_research_config(_write_config(tmp_path, document))


def test_caveat_baskets_are_separate_from_validated_coverage(analysis: dict) -> None:
    summary = analysis["summary"]
    assert summary["custom_basket_possible_with_caveats"] == 9
    assert summary["maximum_research_coverage"] == 64
    assert summary["maximum_case_meets_target"] is True
    assert analysis["decision"]["maximum_case_is_not_production_coverage"] is True


def test_innovative_drug_requires_scope_decision(analysis: dict) -> None:
    row = {item["market_path_key"]: item for item in analysis["theme_paths"]}["innovative_drug_medicine"]
    assert row["final_research_status"] == "requires_user_decision"
    assert row["semantic_match"] == "requires_scope_choice"


def test_catering_rejects_hotel_and_food_substitution(analysis: dict) -> None:
    row = {item["market_path_key"]: item for item in analysis["theme_paths"]}["catering"]
    assert row["final_research_status"] == "unsuitable_for_custom_basket"
    assert row["eligible_candidate_count"] == 0
    assert row["candidates"][0]["code"] == "880423.TDX"
    assert row["candidates"][0]["name"] == "酒店餐饮"
    assert row["candidates"][0]["eligible"] is False
    assert "hotel_substitution_prohibited" == row["unrelated_stock_risk"]


def test_commercial_space_is_not_replaced_by_broad_military(analysis: dict) -> None:
    row = {item["market_path_key"]: item for item in analysis["theme_paths"]}["commercial_space"]
    assert row["unrelated_stock_risk"] == "military_substitution_prohibited"
    assert {item["name"] for item in row["candidates"]} == {"商业航天"}


def test_cpo_is_not_replaced_by_broad_communication(analysis: dict) -> None:
    row = {item["market_path_key"]: item for item in analysis["theme_paths"]}["cpo"]
    assert {item["name"] for item in row["candidates"]} == {"CPO", "共封装光学(CPO)"}
    assert all("通信" not in item["name"] for item in row["candidates"])


def test_candidate_catalogue_counts_are_deterministic(analysis: dict) -> None:
    assert analysis["candidate_catalogue_counts"] == {"ths": 10, "dc": 9, "tdx": 0}


def test_priority_validation_list_is_bounded_and_explicit(analysis: dict) -> None:
    assert analysis["priority_authenticated_validation_paths"] == [
        "cpo", "liquid_cooling", "glass_substrate", "ai_applications", "commercial_space",
    ]


def test_equal_weight_policy_and_safety_limits_are_fixed(analysis: dict) -> None:
    policy = analysis["basket_policy"]
    assert policy["recommended_mvp_weighting"] == "equal_weight"
    assert policy["minimum_valid_constituent_count"] == 5
    assert policy["maximum_single_stock_weight"] == pytest.approx(0.2)
    assert policy["rebalance_frequency"] == "monthly_first_trading_day"
    assert policy["missing_quote_policy"].startswith("fail_closed")


def test_coverage_thresholds() -> None:
    assert MODULE.coverage_status(60) == "tushare_single_authenticated_channel_promising"
    assert MODULE.coverage_status(59) == "tushare_channel_near_threshold"
    assert MODULE.coverage_status(55) == "tushare_channel_near_threshold"
    assert MODULE.coverage_status(54) == "tushare_channel_still_insufficient"


def test_final_result_is_near_threshold_not_promising(analysis: dict) -> None:
    summary = analysis["summary"]
    assert summary["meets_target_under_promising_gate"] is False
    assert summary["conclusion"] == "tushare_channel_near_threshold"
    assert summary["next_decision"] == "additional_source_or_business_decision_required"
    assert analysis["decision"]["tushare_single_channel_reaches_60_with_verified_evidence"] is False
    assert summary["official_only_coverage"] == 52
    assert summary["official_plus_composite_coverage"] == 55
    assert summary["official_plus_composite_plus_promising_baskets"] == 55
    assert len(analysis["remaining_unresolved_paths"]) == 11


def test_analysis_never_reads_token_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("offline spike attempted environment access")

    monkeypatch.setattr(type(os.environ), "get", forbidden)
    result = MODULE.build_analysis(generated_at="fixed")
    assert result["token_accessed"] is False


def test_analysis_never_opens_network_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("offline spike attempted network access")

    monkeypatch.setattr(socket, "socket", forbidden)
    result = MODULE.build_analysis(generated_at="fixed")
    assert result["network_requests"] == 0


def test_formal_registry_and_provider_files_are_not_modified() -> None:
    before = {
        "registry": MODULE._sha256(MODULE.REGISTRY_PATH),
        "capability": MODULE._sha256(MODULE.FORMAL_CAPABILITY_PATH),
    }
    result = MODULE.build_analysis(generated_at="fixed")
    after = {
        "registry": MODULE._sha256(MODULE.REGISTRY_PATH),
        "capability": MODULE._sha256(MODULE.FORMAL_CAPABILITY_PATH),
    }
    assert before == after
    assert result["formal_registry_modified"] is False
    assert result["formal_provider_modified"] is False
    assert result["provider_integration_started"] is False


def test_analyzer_has_no_database_or_provider_integration() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    lowered = source.lower()
    assert "sqlite" not in lowered
    assert "create_engine" not in lowered
    assert "load_provider_capabilities" not in source
    assert "TUSHARE_TOKEN" not in source
    assert "os.environ" not in source


def test_permissions_do_not_claim_display_rights(analysis: dict) -> None:
    permissions = analysis["permissions"]
    assert permissions["subject_to_provider_confirmation"] is True
    assert len(permissions["interfaces"]) >= 8
    assert all(item["display_permission"] == "unknown_provider_confirmation_required" for item in permissions["interfaces"])
    assert len(analysis["licensing_questions"]) == 12


def test_estimated_cost_excludes_points_and_display_license(analysis: dict) -> None:
    permissions = analysis["permissions"]
    assert permissions["estimated_monthly_direct_permission_cost_cny"] == 400
    assert "excludes points" in permissions["estimated_monthly_direct_permission_cost_basis"]
    assert "does not list an exact 6000-point package price" in permissions["one_time_or_points_requirements"]


def test_json_csv_and_markdown_outputs_are_consistent(tmp_path: Path, analysis: dict) -> None:
    json_path, csv_path, markdown_path = MODULE.write_outputs(analysis, tmp_path)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert len(rows) == payload["summary"]["theme_paths"] == 11
    assert sum(row["final_research_status"] == "custom_basket_possible_with_caveats" for row in rows) == 9
    assert f"| Promising theoretical coverage | {payload['summary']['promising_theoretical_coverage']} |" in markdown
    assert f"| Conclusion | `{payload['summary']['conclusion']}` |" in markdown
    assert "Network requests: **0**" in markdown
    assert "Token accessed: **false**" in markdown


def test_analysis_is_deterministic_except_explicit_timestamp() -> None:
    first = MODULE.build_analysis(generated_at="fixed")
    second = MODULE.build_analysis(generated_at="fixed")
    assert first == second
