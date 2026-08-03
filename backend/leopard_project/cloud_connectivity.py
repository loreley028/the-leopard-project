"""Database-free, low-rate accounting for the cloud connectivity diagnostic.

This module deliberately separates a provider/symbol *candidate* from a
business *market path*.  A direct or proxy path can select one successful
candidate; a composite path can select only a candidate whose components all
succeed.  That distinction prevents a later fallback failure from changing a
previously successful result.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Callable

from .market_paths import load_market_path_registry
from .providers.capabilities import load_provider_capabilities


SYSTEM_FAILURES = frozenset({"http_401", "http_403", "http_429", "remote_disconnected", "empty_reply", "connection_reset", "dns_error", "tls_error", "timeout"})


@dataclass(frozen=True)
class Candidate:
    provider: str
    symbol: str
    provider_name: str


@dataclass(frozen=True)
class CandidateChain:
    """One legal alternative. Composite chains require every component."""
    candidate_id: str
    components: tuple[Candidate, ...]


@dataclass(frozen=True)
class MarketPathProbe:
    market_path_key: str
    display_name: str
    mapping_type: str
    candidate_chains: tuple[CandidateChain, ...]

    @property
    def candidates(self) -> tuple[Candidate, ...]:
        """Compatibility/readability view; not used for path aggregation."""
        return tuple(component for chain in self.candidate_chains for component in chain.components)


def _candidate_chain(capability_candidate: object, index: int) -> CandidateChain:
    components = getattr(capability_candidate, "components") or ({"symbol": getattr(capability_candidate, "symbol"), "provider_name": getattr(capability_candidate, "provider_name")},)
    provider = str(getattr(capability_candidate, "provider"))
    candidate = tuple(Candidate(provider, str(item["symbol"]), str(item["provider_name"])) for item in components)
    return CandidateChain(f"{provider}:{getattr(capability_candidate, 'symbol')}:{index}", candidate)


def active_market_paths() -> tuple[MarketPathProbe, ...]:
    """Read current registry/matrix only; never retain a handwritten list."""
    capabilities, registry = load_provider_capabilities(), load_market_path_registry()
    return tuple(
        MarketPathProbe(path.market_path_key, path.display_name, capabilities[path.market_path_key].mapping_type,
                        tuple(_candidate_chain(candidate, index) for index, candidate in enumerate(capabilities[path.market_path_key].candidates)))
        for path in registry.supported_market_paths
    )


def feasibility(spot_count: int) -> str:
    return "cloud_market_connectivity_core_feasible" if spot_count >= 60 else "cloud_market_connectivity_partial" if spot_count >= 55 else "cloud_market_connectivity_insufficient"


def _audit_attempts(candidate: Candidate, raw: dict, counter: list[int]) -> list[dict]:
    """Normalize only sanitized per-network-attempt facts supplied by adapter."""
    attempts = list(raw.get("attempts") or ())
    if not attempts and raw.get("network_attempted"):
        attempts = [{"endpoint_family": "spot", "purpose": "spot", "outcome": "success" if raw.get("spot_status") == "success" else "failed", "error_class": raw.get("error_class")}]
    normalized = []
    for attempt in attempts:
        counter[0] += 1
        normalized.append({
            "request_id": f"request-{counter[0]:04d}", "provider": candidate.provider,
            "endpoint_family": str(attempt.get("endpoint_family", "spot")), "symbol": candidate.symbol,
            "purpose": str(attempt.get("purpose", "spot")), "started_at": attempt.get("started_at"),
            "finished_at": attempt.get("finished_at"), "outcome": str(attempt.get("outcome", "failed")),
            "error_class": attempt.get("error_class"), "retry_of": attempt.get("retry_of"),
            "reused_as_candidate_result": bool(attempt.get("reused_as_candidate_result", False)),
        })
    return normalized


def _candidate_result(candidate: Candidate, raw: dict, attempts: list[dict]) -> dict:
    return {"candidate_key": f"{candidate.provider}:{candidate.symbol}", "provider": candidate.provider, "symbol": candidate.symbol,
            "provider_name": candidate.provider_name, "spot_status": raw.get("spot_status", "failed"),
            "history_status": raw.get("history_status", "not_attempted"), "previous_close_count": int(raw.get("previous_close_count", 0)),
            "error_class": raw.get("error_class"), "error_summary": raw.get("error_summary"),
            "request_ids": [item["request_id"] for item in attempts], "attempts": attempts}


def _chain_result(chain: CandidateChain, symbol_results: dict[tuple[str, str], dict]) -> dict:
    components = [symbol_results[(item.provider, item.symbol)] for item in chain.components]
    spot_ok = bool(components) and all(item["spot_status"] == "success" for item in components)
    history_ok = spot_ok and all(item["history_status"] == "success" and item["previous_close_count"] >= 4 for item in components)
    first_failure = next((item for item in components if item["spot_status"] != "success"), None)
    return {"candidate_id": chain.candidate_id, "components": components, "spot_ok": spot_ok, "history_ok": history_ok,
            "error_class": None if spot_ok else (first_failure or {}).get("error_class"),
            "error_summary": None if spot_ok else (first_failure or {}).get("error_summary")}


def _path_result(path: MarketPathProbe, symbol_results: dict[tuple[str, str], dict]) -> dict:
    if not path.candidate_chains:
        return {"market_path_key": path.market_path_key, "display_name": path.display_name, "mapping_type": path.mapping_type,
                "candidate_results": [], "selected_candidate_id": None, "spot_status": "semantic_unverified", "history_status": "not_attempted",
                "previous_close_count": 0, "same_provider_same_symbol": False, "ma5_capable": False,
                "final_operational_status": "failed", "error_class": "semantic_unverified", "error_summary": "no legal candidate"}
    alternatives = [_chain_result(chain, symbol_results) for chain in path.candidate_chains]
    selected = next((item for item in alternatives if item["spot_ok"]), None)
    if selected:
        components = selected["components"]
        history_ok = selected["history_ok"]
        return {"market_path_key": path.market_path_key, "display_name": path.display_name, "mapping_type": path.mapping_type,
                "candidate_results": alternatives, "selected_candidate_id": selected["candidate_id"], "components": components,
                "component_count": len(components), "spot_status": "success", "history_status": "success" if history_ok else "insufficient_history",
                "previous_close_count": min(item["previous_close_count"] for item in components), "same_provider_same_symbol": history_ok,
                "ma5_capable": history_ok, "final_operational_status": "spot_operational", "error_class": None, "error_summary": None}
    failed = alternatives[0]
    return {"market_path_key": path.market_path_key, "display_name": path.display_name, "mapping_type": path.mapping_type,
            "candidate_results": alternatives, "selected_candidate_id": None, "components": failed["components"], "component_count": len(failed["components"]),
            "spot_status": "failed", "history_status": "not_attempted", "previous_close_count": 0, "same_provider_same_symbol": False,
            "ma5_capable": False, "final_operational_status": "failed", "error_class": failed["error_class"], "error_summary": failed["error_summary"]}


def validate_summary_consistency(result: dict) -> list[str]:
    """Return sanitized violations; callers must reject an invalid result."""
    summary, paths, audit = result["summary"], result["paths"], result["attempt_audit"]
    errors: list[str] = []
    if summary["active_market_paths"] != len(paths) or summary["evaluated_market_path_count"] != len(paths): errors.append("market_path_count_mismatch")
    ids = [item["request_id"] for item in audit]
    if len(ids) != len(set(ids)): errors.append("request_id_not_unique")
    if any(item["outcome"] == "skipped" for item in audit): errors.append("skipped_request_in_audit")
    if summary["total_network_attempt_count"] != len(audit): errors.append("network_attempt_count_mismatch")
    if summary["operational_market_path_count"] != sum(row["final_operational_status"] == "spot_operational" for row in paths): errors.append("operational_count_mismatch")
    if summary["failed_market_path_count"] != sum(row["final_operational_status"] == "failed" for row in paths): errors.append("failed_count_mismatch")
    valid_ids = set(ids)
    for row in paths:
        candidate_ids = {candidate["candidate_id"] for candidate in row.get("candidate_results", [])}
        if row["final_operational_status"] == "spot_operational" and (not row.get("selected_candidate_id") or row["selected_candidate_id"] not in candidate_ids or row["spot_status"] != "success"): errors.append(f"invalid_success:{row['market_path_key']}")
        for candidate in row.get("candidate_results", []):
            for component in candidate.get("components", []):
                if not set(component.get("request_ids", [])).issubset(valid_ids): errors.append(f"invalid_candidate_request:{row['market_path_key']}")
    return errors


def run_probe(paths: tuple[MarketPathProbe, ...], probe: Callable[[Candidate, bool], dict], *, include_history: bool = True) -> dict:
    """Low-rate candidate probe with explicit network accounting and circuit skips."""
    unique = {(candidate.provider, candidate.symbol): candidate for path in paths for candidate in path.candidates}
    symbol_results: dict[tuple[str, str], dict] = {}
    audit: list[dict] = []; request_sequence = [0]; provider_failures: dict[str, int] = {}; systemic: set[str] = set()
    skipped_circuit = 0; started = monotonic()
    for key, candidate in unique.items():
        if candidate.provider in systemic:
            skipped_circuit += 1
            symbol_results[key] = _candidate_result(candidate, {"spot_status": "skipped_provider_systemic_failure", "history_status": "not_attempted", "error_class": "skipped_provider_systemic_failure"}, [])
            continue
        raw = probe(candidate, include_history)
        attempts = _audit_attempts(candidate, raw, request_sequence); audit.extend(attempts)
        item = _candidate_result(candidate, raw, attempts); symbol_results[key] = item
        if item["spot_status"] != "success" and item["error_class"] in SYSTEM_FAILURES:
            provider_failures[candidate.provider] = provider_failures.get(candidate.provider, 0) + 1
            if provider_failures[candidate.provider] >= 2: systemic.add(candidate.provider)
    rows = [_path_result(path, symbol_results) for path in paths]
    operational = sum(row["final_operational_status"] == "spot_operational" for row in rows)
    counts = {"provider_probe_attempt_count": len(audit), "spot_network_attempt_count": sum(item["purpose"] == "spot" for item in audit),
              "spot_retry_attempt_count": sum(item["purpose"] == "spot_retry" for item in audit), "history_network_attempt_count": sum(item["purpose"] == "history" for item in audit)}
    counts["total_network_attempt_count"] = counts["spot_network_attempt_count"] + counts["spot_retry_attempt_count"] + counts["history_network_attempt_count"]
    summary = {"active_market_paths": len(paths), "supported_denominator": len(paths), "unsupported_count": len(load_market_path_registry().unsupported_market_paths),
               "evaluated_market_path_count": len(rows), "operational_market_path_count": operational, "failed_market_path_count": len(rows) - operational,
               "spot_operational_count": operational, "spot_failed_count": len(rows) - operational, "spot_operational_rate": operational / len(rows) if rows else 0,
               "history_complete_count": sum(row["history_status"] == "success" for row in rows), "ma5_capable_count": sum(row["ma5_capable"] for row in rows),
               "direct_operational_count": sum(row["mapping_type"] == "direct" and row["final_operational_status"] == "spot_operational" for row in rows),
               "proxy_operational_count": sum(row["mapping_type"] == "proxy" and row["final_operational_status"] == "spot_operational" for row in rows),
               "composite_operational_count": sum(row["mapping_type"] == "composite" and row["final_operational_status"] == "spot_operational" for row in rows),
               "skipped_due_to_circuit_count": skipped_circuit, "skipped_semantic_unverified_count": sum(not path.candidate_chains for path in paths),
               "unique_candidate_count": len(unique), "systemic_failure_providers": sorted(systemic), **counts,
               "total_duration_ms": round((monotonic() - started) * 1000), "feasibility": feasibility(operational)}
    result = {"summary": summary, "paths": rows, "candidate_results": list(symbol_results.values()), "attempt_audit": audit}
    result["consistency_errors"] = validate_summary_consistency(result)
    result["probe_status"] = "probe_result_valid" if not result["consistency_errors"] else "probe_result_invalid"
    return result


def write_reports(result: dict, output_dir: Path, stem: str) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path, csv_path, markdown_path = (output_dir / f"{stem}.{suffix}" for suffix in ("json", "csv", "md"))
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = ["market_path_key", "display_name", "mapping_type", "selected_candidate_id", "spot_status", "history_status", "previous_close_count", "same_provider_same_symbol", "ma5_capable", "final_operational_status", "error_class", "error_summary"]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows({key: row.get(key) for key in fields} for row in result["paths"])
    summary = result["summary"]
    markdown_path.write_text("# Cloud market connectivity probe\n\n" + "\n".join(f"- {key}: {value}" for key, value in summary.items()) + f"\n- probe_status: {result['probe_status']}\n", encoding="utf-8")
    return json_path, csv_path, markdown_path
