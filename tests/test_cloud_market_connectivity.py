from pathlib import Path

from leopard_project.cloud_connectivity import Candidate, MarketPathProbe, feasibility, run_probe, write_reports
from leopard_project.providers import ProviderError, ProviderErrorCategory
from scripts.validate_cloud_market_connectivity import error_class


def ok(candidate, history): return {"spot_status": "success", "history_status": "success" if history else "not_attempted", "previous_close_count": 4, "request_count": 1}
def failed(_candidate, _history): return {"spot_status": "failed", "history_status": "not_attempted", "error_class": "remote_disconnected", "error_summary": "sanitized", "request_count": 1}


def test_paths_are_registry_derived_and_hstech_is_absent():
    from leopard_project.cloud_connectivity import active_market_paths
    assert len(active_market_paths()) == 66
    assert "hang_seng_tech" not in {row.market_path_key for row in active_market_paths()}


def test_deduplicates_symbols_and_maps_composite_components():
    paths = (MarketPathProbe("one", "One", "direct", (Candidate("p", "A", "a"),)), MarketPathProbe("two", "Two", "composite", (Candidate("p", "A", "a"), Candidate("p", "B", "b"))))
    result = run_probe(paths, ok)
    assert result["summary"]["total_request_count"] == 2
    assert result["summary"]["spot_operational_count"] == 2


def test_single_failure_continues_and_two_systemic_failures_short_circuit_provider():
    paths = tuple(MarketPathProbe(str(index), str(index), "direct", (Candidate("p", str(index), str(index)),)) for index in range(3))
    result = run_probe(paths, failed)
    assert result["paths"][2]["spot_status"] == "skipped_provider_systemic_failure"
    assert result["summary"]["systemic_failure_providers"] == ["p"]


def test_feasibility_bands():
    assert feasibility(60).endswith("core_feasible")
    assert feasibility(55).endswith("partial")
    assert feasibility(54).endswith("insufficient")


def test_history_is_not_required_for_spot_feasibility():
    path = (MarketPathProbe("one", "One", "proxy", (Candidate("p", "A", "a"),)),)
    result = run_probe(path, lambda _candidate, _history: {"spot_status": "success", "history_status": "insufficient_history", "previous_close_count": 2, "request_count": 1})
    assert result["summary"]["spot_operational_count"] == 1
    assert result["summary"]["ma5_capable_count"] == 0


def test_unverified_path_is_preserved_not_silently_removed():
    result = run_probe((MarketPathProbe("catering", "餐饮", "direct", ()),), ok)
    assert result["paths"][0]["error_class"] == "semantic_unverified"
    assert result["summary"]["spot_failed_count"] == 1


def test_error_classification_is_specific():
    assert error_class(ProviderError(ProviderErrorCategory.AUTHENTICATION, "x", retryable=False)) == "http_401"
    assert error_class(ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "x", retryable=False)) == "parse_error"


def test_json_csv_and_markdown_are_written_without_raw_response(tmp_path: Path):
    result = run_probe((MarketPathProbe("one", "One", "direct", (Candidate("p", "A", "a"),)),), ok)
    outputs = write_reports(result, tmp_path, "probe")
    assert [path.suffix for path in outputs] == [".json", ".csv", ".md"]
    assert all(path.exists() for path in outputs)
