from __future__ import annotations

import copy
import csv
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts/analyze_ths_official_board_mapping.py"
CONFIG_PATH = ROOT / "config/research/ths_official_board_mapping_audit_v1.json"
SPEC = importlib.util.spec_from_file_location("ths_mapping_audit", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.fixture(scope="module")
def audit() -> dict:
    return MODULE.build_audit(generated_at="2026-08-03T00:00:00+00:00")


def _write_config(tmp_path: Path, value: dict) -> Path:
    path = tmp_path / "audit.json"
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def test_scope_is_dynamically_derived_from_active_registry(audit: dict) -> None:
    from leopard_project.market_paths import load_market_path_registry

    expected = len(load_market_path_registry().supported_market_paths)
    assert audit["summary"]["active_market_paths"] == expected == 66
    assert len(audit["rows"]) == expected
    assert len({row["market_path_key"] for row in audit["rows"]}) == expected
    assert "hang_seng_tech" not in {row["market_path_key"] for row in audit["rows"]}


def test_counts_are_complete_and_mutually_exclusive(audit: dict) -> None:
    summary = audit["summary"]
    assert summary["ths_exact_board_exists"] == 61
    assert summary["ths_acceptable_proxy_exists"] == 1
    assert summary["ths_composite_required"] == 3
    assert summary["ths_board_code_needs_correction"] == 0
    assert summary["no_suitable_ths_board"] == 1
    assert sum(summary[key] for key in (
        "ths_exact_board_exists", "ths_acceptable_proxy_exists", "ths_composite_required",
        "ths_board_code_needs_correction", "no_suitable_ths_board", "requires_business_decision",
    )) == summary["active_market_paths"]


def test_tushare_absence_is_not_used_as_ths_absence(audit: dict) -> None:
    rows = {row["market_path_key"]: row for row in audit["rows"]}
    assert rows["cpo"]["final_research_status"] == "ths_exact_board_exists"
    assert rows["commercial_space"]["final_research_status"] == "ths_exact_board_exists"
    assert audit["summary"]["paths_with_existing_ths_semantics_including_composites"] == 65


def test_cpo_identity_is_exact_and_not_a_basket(audit: dict) -> None:
    row = next(item for item in audit["rows"] if item["market_path_key"] == "cpo")
    assert (row["ths_official_board_name"], row["ths_official_board_code"]) == ("共封装光学(CPO)", "886033")
    assert row["basket_candidate"] is False
    assert row["prohibited_substitutes"] == ["通信设备", "通信服务"]


def test_commercial_space_identity_is_exact_and_not_a_basket(audit: dict) -> None:
    row = next(item for item in audit["rows"] if item["market_path_key"] == "commercial_space")
    assert (row["ths_official_board_name"], row["ths_official_board_code"]) == ("商业航天", "886078")
    assert row["basket_candidate"] is False
    assert "军工" in row["prohibited_substitutes"]


def test_priority_theme_paths_remain_official_ths_boards(audit: dict) -> None:
    rows = {row["market_path_key"]: row for row in audit["rows"]}
    expected = {
        "computing_power_rental": "886050", "liquid_cooling": "886044",
        "glass_substrate": "886111", "ai_applications": "886108",
        "internet_finance": "885456", "optical_fiber_theme": "886084",
        "rare_earth": "885343", "innovative_drug_medicine": "886015",
    }
    assert {key: rows[key]["ths_official_board_code"] for key in expected} == expected
    assert all(rows[key]["basket_candidate"] is False for key in expected)


def test_catering_is_only_genuine_semantic_gap_and_rejects_substitutes(audit: dict) -> None:
    row = next(item for item in audit["rows"] if item["market_path_key"] == "catering")
    assert row["final_research_status"] == "no_suitable_ths_board"
    assert row["problem_class"] == "semantic_coverage_gap"
    assert row["basket_candidate"] is True
    assert audit["summary"]["basket_candidate_paths"] == ["catering"]
    assert {"酒店", "旅游", "食品"} <= set(row["prohibited_substitutes"])


def test_existing_single_board_access_failure_is_not_a_semantic_gap(audit: dict) -> None:
    row = next(item for item in audit["rows"] if item["market_path_key"] == "semiconductor")
    assert row["final_research_status"] == "ths_exact_board_exists"
    assert row["problem_class"] == "provider_access_problem"
    assert row["basket_candidate"] is False


def test_composites_are_separate_from_single_board_and_basket_counts(audit: dict) -> None:
    rows = {row["market_path_key"]: row for row in audit["rows"]}
    for key in ("food_beverage", "photovoltaic_energy_storage", "oil_petrochemical"):
        assert rows[key]["final_research_status"] == "ths_composite_required"
        assert rows[key]["requires_composite"] is True
        assert rows[key]["basket_candidate"] is False


def test_code_correction_is_classified_as_mapping_problem(tmp_path: Path) -> None:
    config = copy.deepcopy(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    config["code_corrections"] = {"cpo": {"correct_symbol": "886033", "correct_name": "共封装光学(CPO)"}}
    result = MODULE.build_audit(_write_config(tmp_path, config), generated_at="fixed")
    row = next(item for item in result["rows"] if item["market_path_key"] == "cpo")
    assert row["final_research_status"] == "ths_board_code_needs_correction"
    assert row["problem_class"] == "mapping_problem"


def test_public_paths_require_no_cookie_or_token(audit: dict) -> None:
    paths = audit["public_access_paths"]
    assert all(item["requires_login"] is False for item in paths)
    assert all(item["requires_cookie"] is False for item in paths)
    assert all(item["requires_token"] is False for item in paths)
    assert all(item["public_get"] is True for item in paths)


def test_detail_and_chart_paths_have_separate_field_contracts(audit: dict) -> None:
    paths = {item["access_path_id"]: item for item in audit["public_access_paths"]}
    assert paths["ths_detail_html"]["current_candidate"] is True
    assert paths["ths_detail_html"]["pre_close_candidate"] is True
    assert paths["ths_detail_html"]["as_of_candidate"] is False
    assert paths["ths_board_daily_chart"]["history_candidate"] is True
    assert paths["ths_board_daily_chart"]["recommendation"] == "insufficient_fields"


def test_current_detail_endpoint_audit_is_explicit(audit: dict) -> None:
    endpoint = audit["existing_ths_detail_audit"]
    assert endpoint["endpoint_family"] == "q_10jqka_thshy_detail"
    assert endpoint["as_of_parser"] == "not_source_derived_in_existing_adapter"
    assert "http_401" in endpoint["http_401_behavior"]
    assert "cannot establish" in endpoint["board_existence_conflation"]


def test_research_flags_and_no_formal_side_effects(audit: dict) -> None:
    assert audit["research_only"] is True
    assert audit["production_approved"] is False
    assert audit["provider_integration_started"] is False
    assert audit["formal_registry_modified"] is False
    assert audit["formal_candidate_chain_modified"] is False
    assert audit["token_accessed"] is False
    assert audit["network_requests"] == 0


def test_audit_output_formats_are_consistent(tmp_path: Path, audit: dict) -> None:
    json_path, csv_path, markdown_path = MODULE.write_outputs(audit, tmp_path)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert len(rows) == payload["summary"]["active_market_paths"]
    assert sum(row["basket_candidate"] == "True" for row in rows) == 1
    assert f"| Genuine semantic gap | {payload['summary']['genuine_semantic_gap_count']} |" in markdown


def test_audit_does_not_import_live_provider_or_database() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8").lower()
    assert "sqlite" not in source
    assert "urlopen" not in source
    assert "ths_exact_spot" in source  # Evidence identifier only, not a Provider import.
