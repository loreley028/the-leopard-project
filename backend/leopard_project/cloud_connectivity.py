"""Database-free, low-rate connectivity accounting for cloud-only diagnostics."""
from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from time import monotonic
from typing import Callable

from .market_paths import load_market_path_registry
from .providers.capabilities import load_provider_capabilities


@dataclass(frozen=True)
class Candidate:
    provider: str
    symbol: str
    provider_name: str


@dataclass(frozen=True)
class MarketPathProbe:
    market_path_key: str
    display_name: str
    mapping_type: str
    candidates: tuple[Candidate, ...]


def active_market_paths() -> tuple[MarketPathProbe, ...]:
    """Read the current registry and matrix; never retain a hand-written list."""
    capabilities = load_provider_capabilities()
    registry = load_market_path_registry()
    output: list[MarketPathProbe] = []
    for path in registry.supported_market_paths:
        capability = capabilities[path.market_path_key]
        candidates: list[Candidate] = []
        for candidate in capability.candidates:
            components = candidate.components or ({"symbol": candidate.symbol, "provider_name": candidate.provider_name},)
            candidates.extend(Candidate(candidate.provider, str(part["symbol"]), str(part["provider_name"])) for part in components)
        output.append(MarketPathProbe(path.market_path_key, path.display_name, capability.mapping_type, tuple(candidates)))
    return tuple(output)


def feasibility(spot_count: int) -> str:
    return "cloud_market_connectivity_core_feasible" if spot_count >= 60 else "cloud_market_connectivity_partial" if spot_count >= 55 else "cloud_market_connectivity_insufficient"


def run_probe(
    paths: tuple[MarketPathProbe, ...],
    probe: Callable[[Candidate, bool], dict],
    *,
    include_history: bool = True,
) -> dict:
    """Probe one Provider/symbol at a time and stop a systemically failing Provider.

    `probe` returns only de-sensitized facts. It must not write a database.
    """
    unique = {(candidate.provider, candidate.symbol): candidate for path in paths for candidate in path.candidates}
    symbol_results: dict[tuple[str, str], dict] = {}
    provider_failures: dict[str, int] = {}
    systemic: set[str] = set()
    request_count = 0
    started = monotonic()
    for key, candidate in unique.items():
        if candidate.provider in systemic:
            symbol_results[key] = {"provider": candidate.provider, "symbol": candidate.symbol, "spot_status": "skipped_provider_systemic_failure", "history_status": "not_attempted", "error_class": "skipped_provider_systemic_failure"}
            continue
        result = probe(candidate, include_history)
        request_count += int(result.get("request_count", 0))
        result = {"provider": candidate.provider, "symbol": candidate.symbol, **result}
        symbol_results[key] = result
        if result.get("spot_status") != "success" and result.get("error_class") in {"http_401", "remote_disconnected", "empty_reply", "connection_reset", "dns_error", "tls_error"}:
            provider_failures[candidate.provider] = provider_failures.get(candidate.provider, 0) + 1
            if provider_failures[candidate.provider] >= 2:
                systemic.add(candidate.provider)
    rows = []
    for path in paths:
        components = [symbol_results[(item.provider, item.symbol)] for item in path.candidates]
        spot_ok = bool(components) and all(item.get("spot_status") == "success" for item in components)
        history_ok = spot_ok and all(item.get("history_status") == "success" for item in components)
        rows.append({
            "market_path_key": path.market_path_key, "display_name": path.display_name, "mapping_type": path.mapping_type,
            "component_count": len(components), "components": components, "spot_status": "success" if spot_ok else (components[0].get("spot_status") if components else "semantic_unverified"),
            "history_status": "success" if history_ok else ("not_attempted" if not spot_ok else "insufficient_history"),
            "previous_close_count": min((int(item.get("previous_close_count", 0)) for item in components), default=0),
            "same_provider_same_symbol": history_ok, "ma5_capable": history_ok,
            "final_operational_status": "spot_operational" if spot_ok else "failed",
            "error_class": None if spot_ok else (components[0].get("error_class") if components else "semantic_unverified"),
            "error_summary": None if spot_ok else (components[0].get("error_summary") if components else "no approved or candidate symbol"),
        })
    spot_count = sum(row["spot_status"] == "success" for row in rows)
    summary = {
        "active_market_paths": len(paths), "supported_denominator": len(paths), "unsupported_count": len(load_market_path_registry().unsupported_market_paths),
        "spot_operational_count": spot_count, "spot_failed_count": len(rows) - spot_count, "spot_operational_rate": spot_count / len(rows) if rows else 0,
        "history_complete_count": sum(row["history_status"] == "success" for row in rows), "ma5_capable_count": sum(row["ma5_capable"] for row in rows),
        "direct_operational_count": sum(row["mapping_type"] == "direct" and row["spot_status"] == "success" for row in rows),
        "proxy_operational_count": sum(row["mapping_type"] == "proxy" and row["spot_status"] == "success" for row in rows),
        "composite_operational_count": sum(row["mapping_type"] == "composite" and row["spot_status"] == "success" for row in rows),
        "systemic_failure_providers": sorted(systemic), "total_request_count": request_count,
        "total_duration_ms": round((monotonic() - started) * 1000), "feasibility": feasibility(spot_count),
    }
    return {"summary": summary, "paths": rows, "symbols": list(symbol_results.values())}


def write_reports(result: dict, output_dir: Path, stem: str) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path, csv_path, markdown_path = (output_dir / f"{stem}.{suffix}" for suffix in ("json", "csv", "md"))
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = ["market_path_key", "display_name", "mapping_type", "spot_status", "history_status", "previous_close_count", "same_provider_same_symbol", "ma5_capable", "final_operational_status", "error_class", "error_summary"]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows({key: row.get(key) for key in fields} for row in result["paths"])
    summary = result["summary"]
    markdown_path.write_text("# Cloud market connectivity probe\n\n" + "\n".join(f"- {key}: {value}" for key, value in summary.items()) + "\n", encoding="utf-8")
    return json_path, csv_path, markdown_path
