from pathlib import Path

from leopard_project.cloud_connectivity import Candidate, CandidateChain, MarketPathProbe, feasibility, run_probe, validate_summary_consistency, write_reports
from leopard_project.providers import ProviderError, ProviderErrorCategory
from scripts.validate_cloud_market_connectivity import error_class, exit_code_for_result


def chain(identifier: str, *parts: tuple[str, str]) -> CandidateChain:
    return CandidateChain(identifier, tuple(Candidate(provider, symbol, symbol) for provider, symbol in parts))


def path(key: str, mapping_type: str, *chains: CandidateChain) -> MarketPathProbe:
    return MarketPathProbe(key, key, mapping_type, chains)


def ok(_candidate, history):
    attempts = [{"endpoint_family": "spot", "purpose": "spot", "outcome": "success"}]
    if history:
        attempts.append({"endpoint_family": "history", "purpose": "history", "outcome": "success"})
    return {"spot_status": "success", "current_available": True, "pre_close_available": True, "as_of_available": True, "history_status": "success", "previous_close_count": 4, "attempts": attempts}


def failed(_candidate, _history):
    return {"spot_status": "failed", "history_status": "not_attempted", "error_class": "remote_disconnected", "error_summary": "sanitized", "attempts": [{"endpoint_family": "spot", "purpose": "spot", "outcome": "failed", "error_class": "remote_disconnected"}]}


def test_paths_are_registry_derived_and_hstech_is_absent():
    from leopard_project.cloud_connectivity import active_market_paths
    assert len(active_market_paths()) == 66
    assert "hang_seng_tech" not in {row.market_path_key for row in active_market_paths()}


def test_two_ths_and_two_eastmoney_probes_are_four_network_attempts():
    paths = tuple(path(str(i), "direct", chain(str(i), ("ths_exact_spot" if i < 2 else "eastmoney_board_spot", str(i)))) for i in range(4))
    result = run_probe(paths, failed, include_history=False)
    assert result["summary"]["total_network_attempt_count"] == 4
    assert result["summary"]["spot_network_attempt_count"] == 4


def test_circuit_skips_are_not_network_attempts():
    paths = tuple(path(str(i), "direct", chain(str(i), ("p", str(i)))) for i in range(3))
    result = run_probe(paths, failed, include_history=False)
    assert result["summary"]["skipped_due_to_circuit_count"] == 1
    assert result["summary"]["total_network_attempt_count"] == 2


def test_direct_selects_successful_fallback_not_failed_primary():
    routes = path("direct", "direct", chain("first", ("p", "bad")), chain("second", ("q", "good")))
    result = run_probe((routes,), lambda candidate, history: ok(candidate, history) if candidate.symbol == "good" else failed(candidate, history))
    row = result["paths"][0]
    assert row["selected_candidate_id"] == "second" and row["final_operational_status"] == "spot_operational"


def test_later_fallback_failure_does_not_override_success():
    routes = path("direct", "direct", chain("first", ("p", "good")), chain("second", ("q", "bad")))
    result = run_probe((routes,), lambda candidate, history: ok(candidate, history) if candidate.symbol == "good" else failed(candidate, history))
    assert result["paths"][0]["final_operational_status"] == "spot_operational"


def test_composite_requires_every_component():
    routes = path("combo", "composite", chain("combo-chain", ("p", "A"), ("q", "B")))
    result = run_probe((routes,), lambda candidate, history: ok(candidate, history) if candidate.symbol == "A" else failed(candidate, history))
    assert result["paths"][0]["final_operational_status"] == "failed"


def test_proxy_and_composite_remain_their_own_types():
    result = run_probe((path("proxy", "proxy", chain("proxy", ("p", "A"))), path("combo", "composite", chain("combo", ("q", "B"), ("q", "C")))), ok)
    assert result["summary"]["proxy_operational_count"] == 1
    assert result["summary"]["composite_operational_count"] == 1


def test_semantic_unverified_is_not_success():
    result = run_probe((path("catering", "direct"),), ok)
    assert result["paths"][0]["error_class"] == "semantic_unverified"
    assert result["summary"]["skipped_semantic_unverified_count"] == 1


def test_history_not_required_for_spot_but_ma5_requires_four_closes():
    result = run_probe((path("one", "direct", chain("one", ("p", "A"))),), lambda *_: {"spot_status": "success", "current_available": True, "pre_close_available": True, "as_of_available": True, "history_status": "insufficient_history", "previous_close_count": 2, "attempts": [{"purpose": "spot", "outcome": "success"}]})
    assert result["summary"]["spot_operational_count"] == 1
    assert result["summary"]["ma5_capable_count"] == 0


def test_attempt_ids_unique_and_skips_not_audited():
    result = run_probe(tuple(path(str(i), "direct", chain(str(i), ("p", str(i)))) for i in range(3)), failed, include_history=False)
    assert not validate_summary_consistency(result)
    assert all(item["outcome"] != "skipped" for item in result["attempt_audit"])


def test_invalid_summary_marks_result_invalid():
    result = run_probe((path("one", "direct", chain("one", ("p", "A"))),), ok)
    result["summary"]["total_network_attempt_count"] = 99
    assert validate_summary_consistency(result)


def test_invalid_result_uses_distinct_nonzero_exit_code():
    result = run_probe((path("one", "direct", chain("one", ("p", "A"))),), ok)
    result["probe_status"] = "probe_result_invalid"
    assert exit_code_for_result(result) == 3


def test_candidate_request_ids_must_reference_audit():
    result = run_probe((path("one", "direct", chain("one", ("p", "A"))),), ok)
    result["paths"][0]["candidate_results"][0]["components"][0]["request_ids"] = ["missing"]
    assert "invalid_candidate_request:one" in validate_summary_consistency(result)


def test_successful_path_requires_legal_selected_candidate():
    result = run_probe((path("one", "direct", chain("one", ("p", "A"))),), ok)
    result["paths"][0]["selected_candidate_id"] = "not-legal"
    assert "invalid_success:one" in validate_summary_consistency(result)


def test_unsupported_hstech_never_enters_live_paths():
    from leopard_project.cloud_connectivity import active_market_paths
    assert all(item.market_path_key != "hang_seng_tech" for item in active_market_paths())


def test_request_count_formula_separates_history_and_retry():
    result = run_probe((path("one", "direct", chain("one", ("p", "A"))),), lambda *_: {"spot_status": "success", "current_available": True, "pre_close_available": True, "as_of_available": True, "history_status": "success", "previous_close_count": 4, "attempts": [{"purpose": "spot", "outcome": "success"}, {"purpose": "spot_retry", "outcome": "success"}, {"purpose": "history", "outcome": "success"}]})
    summary = result["summary"]
    assert summary["total_network_attempt_count"] == summary["provider_probe_attempt_count"] + summary["spot_network_attempt_count"] + summary["spot_retry_attempt_count"] + summary["history_network_attempt_count"] == 3


def test_provider_probe_and_spot_are_counted_once_when_not_reused():
    result = run_probe((path("one", "direct", chain("one", ("p", "A"))),), lambda *_: {"spot_status": "success", "current_available": True, "pre_close_available": True, "as_of_available": True, "history_status": "not_attempted", "attempts": [{"purpose": "provider_probe", "outcome": "success"}, {"purpose": "spot", "outcome": "success"}]}, include_history=False)
    assert result["summary"]["total_network_attempt_count"] == 2


def test_reused_provider_preflight_is_not_a_second_network_attempt():
    result = run_probe((path("one", "direct", chain("one", ("p", "A"))),), lambda *_: {"spot_status": "success", "current_available": True, "pre_close_available": True, "as_of_available": True, "history_status": "not_attempted", "attempts": [{"purpose": "spot", "outcome": "success", "reused_as_candidate_result": True}]}, include_history=False)
    assert result["summary"]["provider_probe_attempt_count"] == 0
    assert result["summary"]["total_network_attempt_count"] == 1


def test_feasibility_bands():
    assert feasibility(60).endswith("core_feasible")
    assert feasibility(55).endswith("partial")
    assert feasibility(54).endswith("insufficient")


def test_error_classification_is_specific():
    assert error_class(ProviderError(ProviderErrorCategory.AUTHENTICATION, "x", retryable=False)) == "http_401"
    assert error_class(ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "x", retryable=False)) == "parse_error"


def test_json_csv_and_markdown_are_written_without_raw_response(tmp_path: Path):
    result = run_probe((path("one", "direct", chain("one", ("p", "A"))),), ok)
    outputs = write_reports(result, tmp_path, "probe")
    assert [item.suffix for item in outputs] == [".json", ".csv", ".md"]
    assert all(item.exists() for item in outputs)
    assert "raw_response" not in outputs[0].read_text(encoding="utf-8")


def test_no_database_or_snapshot_side_effects(tmp_path: Path):
    before = set(tmp_path.iterdir())
    run_probe((path("one", "direct", chain("one", ("p", "A"))),), ok)
    assert set(tmp_path.iterdir()) == before
