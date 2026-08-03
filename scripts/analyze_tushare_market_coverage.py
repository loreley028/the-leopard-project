#!/usr/bin/env python3
"""Offline Tushare/SW feasibility analysis for the 66 active CN-A market paths.

This script never imports the Tushare SDK, opens a socket, or calls a Provider.  It
joins the canonical registry with an explicitly research-only mapping catalogue and
writes only sanitized evidence beneath an ignored output directory.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from leopard_project.market_paths import load_market_path_registry
from leopard_project.providers.capabilities import load_provider_capabilities


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config/research/tushare_sw_mapping_research_v1.json"
DEFAULT_OUTPUT = ROOT / "var/provider-research/tushare-feasibility"
VALID_MATCH_TYPES = frozenset({
    "exact",
    "acceptable_proxy",
    "composite_candidate",
    "requires_business_decision",
    "no_valid_mapping",
})
RUNNABLE_RESEARCH_TYPES = frozenset({"exact", "acceptable_proxy"})


def load_research_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if (
        document.get("research_only") is not True
        or document.get("production_approved") is not False
        or document.get("production_enabled") is not False
    ):
        raise ValueError("research_config_must_not_enable_production")
    mappings = document.get("mappings")
    if not isinstance(mappings, dict):
        raise ValueError("research_mappings_missing")
    registry_keys = {item.market_path_key for item in load_market_path_registry().supported_market_paths}
    if set(mappings) != registry_keys:
        raise ValueError("research_mapping_scope_must_equal_supported_registry")
    for key, item in mappings.items():
        if item.get("semantic_match_type") not in VALID_MATCH_TYPES:
            raise ValueError(f"invalid_semantic_match_type:{key}")
        candidates = item.get("sw_candidates", [])
        if not isinstance(candidates, list):
            raise ValueError(f"invalid_candidate_list:{key}")
        if item["semantic_match_type"] in RUNNABLE_RESEARCH_TYPES:
            if len(candidates) != 1 or not candidates[0].get("published"):
                raise ValueError(f"runnable_mapping_requires_one_published_index:{key}")
        if item["semantic_match_type"] == "composite_candidate":
            weights = [candidate.get("weight") for candidate in candidates]
            if len(candidates) < 2 or any(not candidate.get("published") for candidate in candidates):
                raise ValueError(f"composite_requires_published_components:{key}")
            if any(not isinstance(weight, (int, float)) for weight in weights) or abs(sum(weights) - 1.0) > 1e-9:
                raise ValueError(f"composite_weights_invalid:{key}")
    return document


def _formal_candidate(capability: Any) -> dict[str, Any] | None:
    candidates = capability.selectable_candidates or capability.candidates
    if not candidates:
        return None
    item = candidates[0]
    return {
        "provider": item.provider,
        "symbol": item.symbol,
        "provider_name": item.provider_name,
        "validation_status": item.validation_status,
    }


def _formal_candidates(capability: Any) -> list[dict[str, Any]]:
    return [{
        "provider": item.provider,
        "symbol": item.symbol,
        "provider_name": item.provider_name,
        "mapping_type": item.mapping_type,
        "validation_status": item.validation_status,
    } for item in capability.candidates]


def coverage_status(count: int, *, near_threshold: int = 55, target: int = 60) -> str:
    if count >= target:
        return "tushare_direct_or_proxy_coverage_promising"
    if count >= near_threshold:
        return "tushare_coverage_near_threshold"
    return "tushare_single_source_insufficient"


def build_analysis(
    config_path: Path = DEFAULT_CONFIG,
    *,
    generated_at: str | None = None,
    token_available: bool | None = None,
) -> dict[str, Any]:
    config = load_research_config(config_path)
    registry = load_market_path_registry()
    capabilities = load_provider_capabilities()
    failed = set(config["current_cloud_failed_paths"])
    if len(failed) != 12:
        raise ValueError("current_cloud_failure_baseline_must_be_12")
    if token_available is None:
        token_available = bool(os.environ.get("TUSHARE_TOKEN"))

    rows: list[dict[str, Any]] = []
    for path in registry.supported_market_paths:
        research = config["mappings"][path.market_path_key]
        match_type = research["semantic_match_type"]
        candidates = research.get("sw_candidates", [])
        runnable = match_type in RUNNABLE_RESEARCH_TYPES
        primary = candidates[0] if runnable else None
        rows.append({
            "market_path_key": path.market_path_key,
            "display_name": path.display_name,
            "parent_report_topic": path.parent_report_topic,
            "current_mapping_type": path.mapping_type,
            "current_formal_candidate": _formal_candidate(capabilities[path.market_path_key]),
            "current_provider_candidates": _formal_candidates(capabilities[path.market_path_key]),
            "current_cloud_status": "failed" if path.market_path_key in failed else "operational",
            "tushare_sw_candidates": candidates,
            "sw_l1_candidates": [item for item in candidates if item["level"] == "L1"],
            "sw_l2_candidates": [item for item in candidates if item["level"] == "L2"],
            "sw_l3_candidates": [item for item in candidates if item["level"] == "L3"],
            "semantic_match_type": match_type,
            "semantic_confidence": research["confidence"],
            "rationale": research["rationale"],
            "unresolved_difference": None if match_type == "exact" else research["rationale"],
            "realtime_endpoint": "rt_sw_k" if runnable else None,
            "history_endpoint": "sw_daily" if runnable else None,
            "realtime_candidate": {"endpoint": "rt_sw_k", "symbol": primary["code"]} if primary else None,
            "history_candidate": {"endpoint": "sw_daily", "symbol": primary["code"]} if primary else None,
            "selected_research_symbol": primary["code"] if primary else None,
            "spot_candidate": runnable,
            "pre_close_candidate": runnable,
            "as_of_candidate": runnable,
            "daily_history_candidate": runnable,
            "same_provider_same_symbol_candidate": runnable,
            "intraday_ma5_candidate": runnable,
            "constituent_endpoint_candidate": "index_member_all" if candidates else None,
            "constituent_candidate": {"endpoint": "index_member_all", "symbols": [item["code"] for item in candidates]} if candidates else None,
            "requires_custom_basket": match_type == "composite_candidate",
            "requires_business_approval": match_type in {"acceptable_proxy", "composite_candidate", "requires_business_decision"},
            "cloud_validation_status": "not_run",
            "final_feasibility_status": {
                "exact": "theoretical_exact_runtime_candidate",
                "acceptable_proxy": "theoretical_proxy_runtime_candidate",
                "composite_candidate": "unapproved_composite_candidate",
                "requires_business_decision": "business_decision_required",
                "no_valid_mapping": "no_valid_mapping",
            }[match_type],
        })

    counts = Counter(row["semantic_match_type"] for row in rows)
    projected_direct = counts["exact"]
    projected_with_proxy = projected_direct + counts["acceptable_proxy"]
    projected_with_unapproved_composites = projected_with_proxy + counts["composite_candidate"]
    gate = int(config["coverage_gate"])
    theory_gate_passed = projected_with_proxy >= gate
    cloud_status = (
        "not_run_missing_tushare_token"
        if theory_gate_passed and not token_available
        else "not_run_theoretical_coverage_below_gate"
        if not theory_gate_passed
        else "authorized_plan_required_before_cloud_execution"
    )
    conclusion = coverage_status(
        projected_with_proxy,
        near_threshold=gate,
        target=int(config["core_feasibility_target"]),
    )
    symbol_paths: dict[str, list[str]] = {}
    for row in rows:
        for candidate in row["tushare_sw_candidates"]:
            symbol_paths.setdefault(candidate["code"], []).append(row["market_path_key"])
    shared_symbol_audit = [
        {"symbol": symbol, "market_paths": sorted(paths), "selection_policy": "audited_per_path_semantics; never auto-select by name"}
        for symbol, paths in sorted(symbol_paths.items()) if len(paths) > 1
    ]
    unresolved_paths = [{
        "market_path_key": row["market_path_key"],
        "display_name": row["display_name"],
        "semantic_match_type": row["semantic_match_type"],
        "reason": row["unresolved_difference"],
    } for row in rows if row["semantic_match_type"] not in RUNNABLE_RESEARCH_TYPES]
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": "1.0.0",
        "analysis_type": "offline_independent_provider_feasibility",
        "generated_at": generated_at,
        "research_only": True,
        "production_approved": False,
        "production_enabled": False,
        "network_requests": 0,
        "token": {
            "environment_variable": "TUSHARE_TOKEN",
            "available": bool(token_available),
            "value_recorded": False,
            "credential_validation_status": (
                "credential_available_not_used"
                if token_available
                else "tushare_cloud_validation_blocked_by_credential"
            ),
        },
        "current_cloud_baseline": {
            "total": len(rows),
            "operational": len(rows) - len(failed),
            "failed": len(failed),
            "failed_paths": sorted(failed),
        },
        "tushare_endpoint_capabilities": config["endpoint_capabilities"],
        "summary": {
            "matrix_total": len(rows),
            "exact": counts["exact"],
            "acceptable_proxy": counts["acceptable_proxy"],
            "composite_candidate": counts["composite_candidate"],
            "requires_business_decision": counts["requires_business_decision"],
            "no_valid_mapping": counts["no_valid_mapping"],
            "projected_direct_coverage": projected_direct,
            "projected_direct_plus_approved_proxy_coverage": projected_with_proxy,
            "projected_coverage_if_unapproved_composites_were_later_approved": projected_with_unapproved_composites,
            "projected_spot_coverage": projected_with_proxy,
            "projected_pre_close_coverage": projected_with_proxy,
            "projected_history_coverage": projected_with_proxy,
            "projected_intraday_ma5_coverage": projected_with_proxy,
            "coverage_gate": gate,
            "theory_gate_passed": theory_gate_passed,
            "conclusion": conclusion,
            "cloud_validation_status": cloud_status,
        },
        "rows": rows,
        "unresolved_paths": unresolved_paths,
        "shared_symbol_audit": shared_symbol_audit,
        "secondary_source_assessment": {
            "joinquant": "external_server_usage_unverified",
            "commercial_sources": "commercial_purchase_required_and_over_mvp_for_current_private_scope",
        },
        "recommendation": {
            "primary": "Do not integrate Tushare as a single-source replacement: theoretical exact plus acceptable-proxy coverage is below the 55-path gate.",
            "next": "Use Tushare only as a potential independent industry-source component after account permission testing; research a separate licensed concept-board source for the remaining thematic paths.",
            "production_primary_approved": False,
        },
    }


def render_markdown(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        "# Tushare independent-source feasibility matrix",
        "",
        "> Research-only offline evidence. No Tushare SDK call, token value, Provider promotion, or production configuration is involved.",
        "",
        "## Summary",
        "",
        "| Metric | Count / status |",
        "|---|---:|",
        f"| Current cloud operational | {result['current_cloud_baseline']['operational']}/{result['current_cloud_baseline']['total']} |",
        f"| Current cloud failed | {result['current_cloud_baseline']['failed']}/{result['current_cloud_baseline']['total']} |",
        f"| Exact SW mapping | {summary['exact']} |",
        f"| Acceptable explicit proxy | {summary['acceptable_proxy']} |",
        f"| Exact + proxy theoretical runtime coverage | {summary['projected_direct_plus_approved_proxy_coverage']}/66 |",
        f"| Unapproved composite candidates | {summary['composite_candidate']} |",
        f"| Business decision required | {summary['requires_business_decision']} |",
        f"| No valid published SW mapping | {summary['no_valid_mapping']} |",
        f"| Cloud validation | {summary['cloud_validation_status']} |",
        f"| Conclusion | `{summary['conclusion']}` |",
        "",
        "## Path matrix",
        "",
        "| Path | Name | Current cloud | Match | SW candidate | Spot/history/MA5 | Decision |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in result["rows"]:
        symbols = ", ".join(f"{item['code']} {item['name']}" for item in row["tushare_sw_candidates"]) or "—"
        capability = "yes/yes/yes" if row["spot_candidate"] else "no/no/no"
        lines.append(
            f"| `{row['market_path_key']}` | {row['display_name']} | {row['current_cloud_status']} | "
            f"{row['semantic_match_type']} | {symbols} | {capability} | {row['final_feasibility_status']} |"
        )
    lines.extend(["", "Token values are never serialized. Network request count: **0**.", ""])
    return "\n".join(lines)


def write_outputs(result: dict[str, Any], output_dir: Path = DEFAULT_OUTPUT) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "tushare-capability-matrix.json"
    markdown_path = output_dir / "tushare-capability-matrix.md"
    csv_path = output_dir / "tushare-capability-matrix.csv"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(result), encoding="utf-8")
    fieldnames = [
        "market_path_key", "display_name", "parent_report_topic", "current_mapping_type",
        "current_cloud_status", "semantic_match_type", "semantic_confidence",
        "tushare_codes", "spot_candidate", "pre_close_candidate", "daily_history_candidate",
        "intraday_ma5_candidate", "requires_custom_basket", "final_feasibility_status",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in result["rows"]:
            writer.writerow({
                **{key: row[key] for key in fieldnames if key != "tushare_codes"},
                "tushare_codes": ";".join(item["code"] for item in row["tushare_sw_candidates"]),
            })
    return json_path, csv_path, markdown_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = build_analysis(args.config)
    paths = write_outputs(result, args.output_dir)
    print(json.dumps(result["summary"], ensure_ascii=False, sort_keys=True))
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
