#!/usr/bin/env python3
"""Evaluate Tushare theme-basket feasibility without credentials or network I/O.

The analysis joins the canonical 66-path registry, the prior SW mapping spike and
an explicitly research-only basket catalogue.  It does not read environment
variables, import a Tushare client, open a socket, call a Provider or touch a
database.  Outputs are sanitized research evidence under an ignored directory.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from leopard_project.market_paths import load_market_path_registry


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config/research/tushare_theme_basket_research_v1.json"
DEFAULT_BASELINE = ROOT / "config/research/tushare_sw_mapping_research_v1.json"
REGISTRY_PATH = ROOT / "config/market_path_registry_v1.json"
FORMAL_CAPABILITY_PATH = ROOT / "config/provider_capability_matrix_v2.json"
DEFAULT_OUTPUT = ROOT / "var/provider-research/tushare-theme-baskets"
RUNNABLE_BASELINE_TYPES = frozenset({"exact", "acceptable_proxy"})
THEME_STATUSES = frozenset({
    "custom_basket_promising",
    "custom_basket_possible_with_caveats",
    "requires_user_decision",
    "unsuitable_for_custom_basket",
})
COUNTABLE_PROMISING_STATUS = "custom_basket_promising"
COUNTABLE_MAXIMUM_STATUSES = frozenset({
    "custom_basket_promising",
    "custom_basket_possible_with_caveats",
})


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def coverage_status(count: int, *, near_threshold: int = 55, target: int = 60) -> str:
    if count >= target:
        return "tushare_single_authenticated_channel_promising"
    if count >= near_threshold:
        return "tushare_channel_near_threshold"
    return "tushare_channel_still_insufficient"


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"json_document_must_be_object:{path.name}")
    return value


def load_research_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    document = _load_json(path)
    if (
        document.get("research_only") is not True
        or document.get("production_approved") is not False
        or document.get("production_enabled") is not False
        or document.get("provider_integration_started") is not False
        or document.get("requires_user_approval") is not True
    ):
        raise ValueError("theme_basket_config_must_remain_research_only")

    policy = document.get("basket_policy")
    if not isinstance(policy, dict) or policy.get("mapping_type") != "custom_basket":
        raise ValueError("custom_basket_policy_missing")
    if policy.get("recommended_mvp_weighting") != "equal_weight":
        raise ValueError("custom_basket_mvp_must_be_equal_weight")
    if policy.get("minimum_valid_constituent_count", 0) < 5:
        raise ValueError("custom_basket_minimum_constituents_too_low")
    if policy.get("maximum_single_stock_weight", 1) > 0.2:
        raise ValueError("custom_basket_weight_cap_too_high")

    composites = document.get("composites")
    themes = document.get("theme_paths")
    if not isinstance(composites, dict) or not isinstance(themes, dict):
        raise ValueError("research_path_sections_missing")
    for key, composite in composites.items():
        if composite.get("production_approved") is not False or composite.get("requires_user_approval") is not True:
            raise ValueError(f"composite_must_remain_unapproved:{key}")
        components = composite.get("components", [])
        weights = [component.get("weight") for component in components]
        if len(components) < 2 or any(not isinstance(weight, (int, float)) for weight in weights):
            raise ValueError(f"composite_components_invalid:{key}")
        if abs(sum(weights) - 1.0) > 1e-9:
            raise ValueError(f"composite_weights_invalid:{key}")
        if any(component.get("provider") != "tushare_sw" for component in components):
            raise ValueError(f"composite_cross_provider_not_allowed:{key}")

    display_suffix = str(policy["display_suffix"])
    for key, theme in themes.items():
        if theme.get("mapping_type") != "custom_basket":
            raise ValueError(f"theme_mapping_type_invalid:{key}")
        if not str(theme.get("display_name", "")).endswith(display_suffix):
            raise ValueError(f"custom_basket_disclosure_missing:{key}")
        status = theme.get("final_research_status")
        if status not in THEME_STATUSES:
            raise ValueError(f"theme_status_invalid:{key}")
        candidates = [
            candidate
            for source in ("ths_candidates", "dc_candidates", "tdx_candidates")
            for candidate in theme.get(source, [])
            if candidate.get("eligible")
        ]
        if status == COUNTABLE_PROMISING_STATUS:
            if theme.get("semantic_confidence") != "high":
                raise ValueError(f"promising_basket_requires_high_confidence:{key}")
            if not candidates or not all(candidate.get("membership_verified") for candidate in candidates):
                raise ValueError(f"promising_basket_requires_verified_membership:{key}")
            if any((candidate.get("constituent_count") or 0) < policy["minimum_valid_constituent_count"] for candidate in candidates):
                raise ValueError(f"promising_basket_constituent_count_too_low:{key}")
    return document


def _candidate_counts(themes: dict[str, Any]) -> dict[str, int]:
    return {
        provider: sum(
            bool(candidate.get("eligible"))
            for theme in themes.values()
            for candidate in theme[f"{provider}_candidates"]
        )
        for provider in ("ths", "dc", "tdx")
    }


def _theme_row(key: str, theme: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    candidates = []
    for provider in ("ths", "dc", "tdx"):
        for candidate in theme[f"{provider}_candidates"]:
            candidates.append({"catalogue": provider, **candidate})
    membership_verified = any(
        candidate["eligible"] and candidate["membership_verified"]
        for candidate in candidates
    )
    source_catalogue = {
        "ths_member": "ths", "dc_member": "dc", "tdx_member": "tdx",
    }.get(theme["recommended_membership_source"])
    source_candidate = next(
        (candidate for candidate in candidates if candidate["catalogue"] == source_catalogue and candidate["eligible"]),
        None,
    )
    basket_definition = {
        "canonical_market_path": key,
        "membership_source": theme["recommended_membership_source"],
        "source_concept_name": source_candidate["name"] if source_candidate else None,
        "source_concept_code": source_candidate["code"] if source_candidate else None,
        "membership_as_of": source_candidate["membership_as_of"] if source_candidate else None,
        "constituent_inclusion_rule": policy["constituent_inclusion_rule"],
        "constituent_exclusion_rule": policy["constituent_exclusion_rule"],
        "weighting_method": theme["recommended_weighting"],
        "weighting_candidates": policy["weighting_candidates"],
        "rebalance_frequency": policy["rebalance_frequency"],
        "missing_quote_policy": policy["missing_quote_policy"],
        "suspended_stock_policy": policy["suspended_stock_policy"],
        "st_stock_policy": policy["st_stock_policy"],
        "newly_listed_stock_policy": policy["newly_listed_stock_policy"],
        "minimum_valid_constituent_count": theme["minimum_valid_constituent_count"],
        "maximum_single_stock_weight": policy["maximum_single_stock_weight"],
        "current_calculation": policy["current_calculation"],
        "pre_close_calculation": policy["pre_close_calculation"],
        "history_calculation": policy["history_calculation"],
        "ma5_calculation": policy["ma5_calculation"],
        "lineage": policy["lineage"],
        "display_disclosure": policy["display_disclosure"],
    }
    return {
        "market_path_key": key,
        "display_name": theme["display_name"],
        "research_mapping_type": theme["mapping_type"],
        "final_research_status": theme["final_research_status"],
        "recommended_membership_source": theme["recommended_membership_source"],
        "recommended_weighting": theme["recommended_weighting"],
        "semantic_confidence": theme["semantic_confidence"],
        "membership_verified": membership_verified,
        "candidate_count": len(candidates),
        "eligible_candidate_count": sum(candidate["eligible"] for candidate in candidates),
        "candidates": candidates,
        "name_match": theme["name_match"],
        "semantic_match": theme["semantic_match"],
        "concentration": theme["concentration"],
        "stability": theme["stability"],
        "unrelated_stock_risk": theme["unrelated_stock_risk"],
        "unresolved_risk": theme["unresolved_risk"],
        "basket_definition": basket_definition,
        "counted_in_promising_coverage": theme["final_research_status"] == COUNTABLE_PROMISING_STATUS,
        "counted_in_maximum_research_coverage": theme["final_research_status"] in COUNTABLE_MAXIMUM_STATUSES,
        "production_approved": False,
    }


def build_analysis(
    config_path: Path = DEFAULT_CONFIG,
    baseline_path: Path = DEFAULT_BASELINE,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = load_research_config(config_path)
    baseline = _load_json(baseline_path)
    registry = load_market_path_registry()
    registry_keys = {item.market_path_key for item in registry.supported_market_paths}
    baseline_mappings = baseline.get("mappings", {})
    if set(baseline_mappings) != registry_keys:
        raise ValueError("baseline_scope_must_equal_supported_registry")

    runnable_keys = {
        key for key, row in baseline_mappings.items()
        if row["semantic_match_type"] in RUNNABLE_BASELINE_TYPES
    }
    composite_keys = set(config["composites"])
    theme_keys = set(config["theme_paths"])
    unresolved_keys = registry_keys - runnable_keys
    if composite_keys & theme_keys or composite_keys | theme_keys != unresolved_keys:
        raise ValueError("research_scope_must_partition_baseline_unresolved_paths")

    baseline_counts = Counter(row["semantic_match_type"] for row in baseline_mappings.values())
    official_and_proxy = len(runnable_keys)
    pending_composites = len(composite_keys)
    theme_rows = [
        _theme_row(key, config["theme_paths"][key], config["basket_policy"])
        for key in sorted(theme_keys)
    ]
    theme_status_counts = Counter(row["final_research_status"] for row in theme_rows)
    promising = theme_status_counts[COUNTABLE_PROMISING_STATUS]
    possible_with_caveats = theme_status_counts["custom_basket_possible_with_caveats"]
    after_composites = official_and_proxy + pending_composites
    promising_coverage = after_composites + promising
    maximum_research_coverage = after_composites + promising + possible_with_caveats
    remaining_unresolved_paths = [
        row["market_path_key"] for row in theme_rows
        if not row["counted_in_promising_coverage"]
    ]
    target = int(config["coverage_target"])

    candidate_counts = _candidate_counts(config["theme_paths"])
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": "1.0.0",
        "analysis_type": "offline_tushare_theme_basket_feasibility",
        "generated_at": generated_at,
        "research_only": True,
        "production_approved": False,
        "production_enabled": False,
        "provider_integration_started": False,
        "network_requests": 0,
        "token_accessed": False,
        "database_accessed": False,
        "formal_provider_modified": False,
        "formal_registry_modified": False,
        "evidence_hashes": {
            "market_path_registry_sha256": _sha256(REGISTRY_PATH),
            "formal_provider_capability_sha256": _sha256(FORMAL_CAPABILITY_PATH),
            "baseline_research_sha256": _sha256(baseline_path),
            "theme_research_sha256": _sha256(config_path),
        },
        "summary": {
            "matrix_total": len(registry_keys),
            "official_exact": baseline_counts["exact"],
            "acceptable_proxy": baseline_counts["acceptable_proxy"],
            "official_and_proxy_coverage": official_and_proxy,
            "pending_composites": pending_composites,
            "coverage_if_composites_approved": after_composites,
            "theme_paths": len(theme_rows),
            "custom_basket_promising": promising,
            "custom_basket_possible_with_caveats": possible_with_caveats,
            "no_verified_membership": theme_status_counts["no_verified_membership"],
            "requires_user_decision": theme_status_counts["requires_user_decision"],
            "unsuitable_for_custom_basket": theme_status_counts["unsuitable_for_custom_basket"],
            "promising_theoretical_coverage": promising_coverage,
            "official_only_coverage": official_and_proxy,
            "official_plus_composite_coverage": after_composites,
            "official_plus_composite_plus_promising_baskets": promising_coverage,
            "maximum_research_coverage": maximum_research_coverage,
            "remaining_unresolved_under_promising_gate": len(registry_keys) - promising_coverage,
            "remaining_unresolved_at_maximum_research_case": len(registry_keys) - maximum_research_coverage,
            "coverage_target": target,
            "meets_target_under_promising_gate": promising_coverage >= target,
            "maximum_case_meets_target": maximum_research_coverage >= target,
            "conclusion": coverage_status(promising_coverage, target=target),
            "next_decision": "additional_source_or_business_decision_required",
        },
        "candidate_catalogue_counts": candidate_counts,
        "priority_authenticated_validation_paths": config["priority_validation_paths"],
        "basket_policy": config["basket_policy"],
        "composites": config["composites"],
        "theme_paths": theme_rows,
        "remaining_unresolved_paths": remaining_unresolved_paths,
        "permissions": config["permissions"],
        "licensing_questions": config["licensing_questions"],
        "decision": {
            "tushare_single_channel_reaches_60_with_verified_evidence": False,
            "reason": "No theme membership snapshot was authenticated in this deliberately offline spike, so zero custom baskets qualify as promising.",
            "maximum_case_is_not_production_coverage": True,
            "production_primary_approved": False,
        },
    }


def render_markdown(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        "# Tushare theme-basket feasibility evidence",
        "",
        "> Offline research only. No Token, network request, Provider integration, registry change or production approval is involved.",
        "",
        "## Coverage",
        "",
        "| Metric | Result |",
        "|---|---:|",
        f"| Canonical supported paths | {summary['matrix_total']} |",
        f"| Official exact | {summary['official_exact']} |",
        f"| Acceptable explicit proxy | {summary['acceptable_proxy']} |",
        f"| Exact + proxy | {summary['official_and_proxy_coverage']} |",
        f"| Pending transparent composites | {summary['pending_composites']} |",
        f"| Coverage if composites are approved | {summary['coverage_if_composites_approved']} |",
        f"| Promising custom baskets | {summary['custom_basket_promising']} |",
        f"| Promising theoretical coverage | {summary['promising_theoretical_coverage']} |",
        f"| Caveat-only baskets | {summary['custom_basket_possible_with_caveats']} |",
        f"| Maximum research case (not production coverage) | {summary['maximum_research_coverage']} |",
        f"| Target | {summary['coverage_target']} |",
        f"| Conclusion | `{summary['conclusion']}` |",
        "",
        "## Theme paths",
        "",
        "| Path | Display | Status | Eligible catalogue candidates | Membership verified | Counted in promising coverage |",
        "|---|---|---|---:|---|---|",
    ]
    for row in result["theme_paths"]:
        lines.append(
            f"| `{row['market_path_key']}` | {row['display_name']} | {row['final_research_status']} | "
            f"{row['eligible_candidate_count']} | {str(row['membership_verified']).lower()} | "
            f"{str(row['counted_in_promising_coverage']).lower()} |"
        )
    lines.extend([
        "",
        "The nine caveat-only baskets require an authenticated, dated membership snapshot and constituent-quality audit before promotion. "
        "The maximum research case must not be described as validated or production-ready.",
        "",
        f"Network requests: **{result['network_requests']}**. Token accessed: **{str(result['token_accessed']).lower()}**.",
        "",
    ])
    return "\n".join(lines)


def write_outputs(result: dict[str, Any], output_dir: Path = DEFAULT_OUTPUT) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "tushare-theme-basket-coverage.json"
    csv_path = output_dir / "tushare-theme-basket-coverage.csv"
    markdown_path = output_dir / "tushare-theme-basket-coverage.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(result), encoding="utf-8")
    fieldnames = [
        "market_path_key", "display_name", "research_mapping_type", "final_research_status",
        "recommended_membership_source", "recommended_weighting", "semantic_confidence",
        "membership_verified", "eligible_candidate_count", "candidate_codes",
        "counted_in_promising_coverage", "counted_in_maximum_research_coverage",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in result["theme_paths"]:
            writer.writerow({
                **{field: row[field] for field in fieldnames if field != "candidate_codes"},
                "candidate_codes": ";".join(candidate["code"] for candidate in row["candidates"]),
            })
    return json_path, csv_path, markdown_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = build_analysis(args.config, args.baseline)
    paths = write_outputs(result, args.output_dir)
    print(json.dumps(result["summary"], ensure_ascii=False, sort_keys=True))
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
