from __future__ import annotations

import importlib.util
import csv
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts/analyze_tushare_market_coverage.py"
SPEC = importlib.util.spec_from_file_location("tushare_market_coverage", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.fixture(scope="module")
def analysis() -> dict:
    return MODULE.build_analysis(
        generated_at="2026-08-03T00:00:00+00:00",
        token_available=False,
    )


def test_research_mapping_scope_is_exactly_66_supported_paths(analysis: dict) -> None:
    from leopard_project.market_paths import load_market_path_registry

    supported_count = len(load_market_path_registry().supported_market_paths)
    assert analysis["summary"]["matrix_total"] == 66
    assert analysis["summary"]["matrix_total"] == supported_count
    assert len(analysis["rows"]) == 66
    assert len({row["market_path_key"] for row in analysis["rows"]}) == 66
    assert "hang_seng_tech" not in {row["market_path_key"] for row in analysis["rows"]}


def test_hstech_remains_the_only_unsupported_registry_path() -> None:
    from leopard_project.market_paths import load_market_path_registry

    unsupported = load_market_path_registry().unsupported_market_paths
    assert [item.market_path_key for item in unsupported] == ["hang_seng_tech"]


def test_semantic_classification_is_mutually_exclusive_and_complete(analysis: dict) -> None:
    summary = analysis["summary"]
    assert summary["exact"] == 45
    assert summary["acceptable_proxy"] == 7
    assert summary["composite_candidate"] == 3
    assert summary["requires_business_decision"] == 2
    assert summary["no_valid_mapping"] == 9
    assert sum(summary[key] for key in (
        "exact", "acceptable_proxy", "composite_candidate",
        "requires_business_decision", "no_valid_mapping",
    )) == 66


def test_theoretical_coverage_fails_closed_below_cloud_gate(analysis: dict) -> None:
    summary = analysis["summary"]
    assert summary["projected_direct_coverage"] == 45
    assert summary["projected_direct_plus_approved_proxy_coverage"] == 52
    assert summary["projected_coverage_if_unapproved_composites_were_later_approved"] == 55
    assert summary["theory_gate_passed"] is False
    assert summary["conclusion"] == "tushare_single_source_insufficient"
    assert summary["cloud_validation_status"] == "not_run_theoretical_coverage_below_gate"
    assert analysis["network_requests"] == 0


def test_current_cloud_baseline_preserves_54_operational_and_12_failed(analysis: dict) -> None:
    baseline = analysis["current_cloud_baseline"]
    assert baseline["total"] == 66
    assert baseline["operational"] == 54
    assert baseline["failed"] == 12
    assert "catering" in baseline["failed_paths"]
    assert "real_estate" in baseline["failed_paths"]


def test_token_value_is_never_serialized(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "must-never-appear-in-output"
    monkeypatch.setenv("TUSHARE_TOKEN", secret)
    result = MODULE.build_analysis(generated_at="fixed")
    serialized = json.dumps(result, ensure_ascii=False)
    assert result["token"] == {
        "environment_variable": "TUSHARE_TOKEN",
        "available": True,
        "value_recorded": False,
        "credential_validation_status": "credential_available_not_used",
    }
    assert secret not in serialized
    assert result["summary"]["cloud_validation_status"] == "not_run_theoretical_coverage_below_gate"


def test_missing_token_has_explicit_credential_block_status(analysis: dict) -> None:
    assert analysis["token"]["available"] is False
    assert analysis["token"]["credential_validation_status"] == "tushare_cloud_validation_blocked_by_credential"


def test_analysis_never_opens_a_network_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("offline feasibility analysis attempted network access")

    monkeypatch.setattr("socket.socket", forbidden)
    result = MODULE.build_analysis(generated_at="fixed", token_available=True)
    assert result["network_requests"] == 0


def test_catering_and_unpublished_rare_earth_fail_closed(analysis: dict) -> None:
    rows = {row["market_path_key"]: row for row in analysis["rows"]}
    for key in ("catering", "rare_earth"):
        row = rows[key]
        assert row["semantic_match_type"] == "no_valid_mapping"
        assert row["selected_research_symbol"] is None
        assert row["spot_candidate"] is False
        assert row["intraday_ma5_candidate"] is False
        assert row["tushare_sw_candidates"][0]["published"] is False


def test_gold_concept_is_not_conflated_with_precious_metals(analysis: dict) -> None:
    rows = {row["market_path_key"]: row for row in analysis["rows"]}
    gold = rows["gold_concept"]
    precious = rows["precious_metals"]
    assert gold["semantic_match_type"] == "acceptable_proxy"
    assert gold["selected_research_symbol"] == "850531.SI"
    assert precious["semantic_match_type"] == "exact"
    assert precious["selected_research_symbol"] == "801053.SI"
    assert gold["selected_research_symbol"] != precious["selected_research_symbol"]


def test_composites_remain_unapproved_and_preserve_weight_sum(analysis: dict) -> None:
    rows = {row["market_path_key"]: row for row in analysis["rows"]}
    for key in ("food_beverage", "photovoltaic_energy_storage", "oil_petrochemical"):
        row = rows[key]
        assert row["semantic_match_type"] == "composite_candidate"
        assert row["requires_custom_basket"] is True
        assert row["spot_candidate"] is False
        assert sum(item["weight"] for item in row["tushare_sw_candidates"]) == pytest.approx(1.0)


def test_name_similarity_does_not_promote_non_exact_paths(analysis: dict) -> None:
    rows = {row["market_path_key"]: row for row in analysis["rows"]}
    assert rows["advanced_packaging"]["semantic_match_type"] == "acceptable_proxy"
    assert rows["optical_fiber_theme"]["semantic_match_type"] == "requires_business_decision"
    assert rows["commercial_space"]["semantic_match_type"] == "no_valid_mapping"


def test_shared_sw_symbol_usage_has_explicit_audit(analysis: dict) -> None:
    audit = {row["symbol"]: row for row in analysis["shared_symbol_audit"]}
    assert audit["801737.SI"]["market_paths"] == ["battery_lithium", "photovoltaic_energy_storage"]
    assert "never auto-select" in audit["801737.SI"]["selection_policy"]


def test_multiple_candidates_are_not_auto_selected(analysis: dict) -> None:
    rows = {row["market_path_key"]: row for row in analysis["rows"]}
    innovative = rows["innovative_drug_medicine"]
    assert len(innovative["tushare_sw_candidates"]) == 2
    assert innovative["selected_research_symbol"] is None
    assert innovative["final_feasibility_status"] == "business_decision_required"


def test_research_mapping_cannot_enter_formal_candidate_chain() -> None:
    from leopard_project.providers.capabilities import load_provider_capabilities

    config = MODULE.load_research_config()
    formal_before = load_provider_capabilities()
    MODULE.build_analysis(generated_at="fixed", token_available=False)
    formal_after = load_provider_capabilities()
    assert config["research_only"] is True
    assert config["production_approved"] is False
    assert config["production_enabled"] is False
    assert formal_after == formal_before
    assert all(candidate.provider != "tushare" for row in formal_after.values() for candidate in row.candidates)


def test_analyzer_has_no_database_integration() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8").lower()
    assert "sqlite" not in source
    assert "sessionlocal" not in source
    assert "create_engine" not in source


@pytest.mark.parametrize(("count", "expected"), [
    (60, "tushare_direct_or_proxy_coverage_promising"),
    (59, "tushare_coverage_near_threshold"),
    (55, "tushare_coverage_near_threshold"),
    (54, "tushare_single_source_insufficient"),
])
def test_coverage_thresholds(count: int, expected: str) -> None:
    assert MODULE.coverage_status(count) == expected


def test_unresolved_path_list_is_complete_and_auditable(analysis: dict) -> None:
    unresolved = analysis["unresolved_paths"]
    assert len(unresolved) == 14
    assert {row["market_path_key"] for row in unresolved} == {
        row["market_path_key"] for row in analysis["rows"]
        if row["semantic_match_type"] not in {"exact", "acceptable_proxy"}
    }
    assert all(row["reason"] for row in unresolved)


def test_output_is_research_only_and_does_not_promote_provider(tmp_path: Path, analysis: dict) -> None:
    json_path, csv_path, markdown_path = MODULE.write_outputs(analysis, tmp_path)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["research_only"] is True
    assert payload["production_enabled"] is False
    assert payload["recommendation"]["production_primary_approved"] is False
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "Network request count: **0**" in markdown
    assert "Token values are never serialized" in markdown
    assert "must-never-appear" not in json_path.read_text(encoding="utf-8")

    with csv_path.open(encoding="utf-8", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert len(csv_rows) == payload["summary"]["matrix_total"]
    assert sum(row["semantic_match_type"] == "exact" for row in csv_rows) == payload["summary"]["exact"]
    assert f"| Exact SW mapping | {payload['summary']['exact']} |" in markdown
    assert f"| Conclusion | `{payload['summary']['conclusion']}` |" in markdown
