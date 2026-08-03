#!/usr/bin/env python3
"""Offline audit of official THS board identities versus provider accessibility.

This research tool reads the canonical registry and existing capability evidence.
It neither calls 10jqka nor imports a live Provider, and it never writes a
database or modifies the formal mapping/candidate configuration.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from leopard_project.market_paths import load_market_path_registry
from leopard_project.providers.capabilities import load_provider_capabilities


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config/research/ths_official_board_mapping_audit_v1.json"
DEFAULT_OUTPUT = ROOT / "var/provider-research/ths-public-board-audit"
REGISTRY_PATH = ROOT / "config/market_path_registry_v1.json"
CAPABILITY_PATH = ROOT / "config/provider_capability_matrix_v2.json"
VALID_STATUSES = frozenset({
    "ths_exact_board_exists", "ths_acceptable_proxy_exists", "ths_composite_required",
    "ths_board_code_needs_correction", "no_suitable_ths_board", "requires_business_decision",
})


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("audit_config_must_be_an_object")
    return value


def load_audit_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    config = _load(path)
    if (
        config.get("research_only") is not True
        or config.get("production_approved") is not False
        or config.get("provider_integration_started") is not False
    ):
        raise ValueError("audit_must_remain_research_only")
    prefixes = config.get("canonical_board_prefixes")
    if not isinstance(prefixes, dict) or not prefixes:
        raise ValueError("board_prefix_rules_missing")
    access_paths = config.get("public_access_paths")
    if not isinstance(access_paths, list) or not access_paths:
        raise ValueError("public_access_paths_missing")
    ids = [item.get("access_path_id") for item in access_paths]
    if len(ids) != len(set(ids)):
        raise ValueError("public_access_path_ids_must_be_unique")
    for item in access_paths:
        if any(item.get(field) is not False for field in ("requires_login", "requires_cookie", "requires_token")):
            raise ValueError(f"public_path_must_not_require_auth:{item.get('access_path_id')}")
        if item.get("public_get") is not True:
            raise ValueError(f"public_path_must_use_anonymous_get:{item.get('access_path_id')}")
    policy = config.get("cloud_probe_policy")
    if not isinstance(policy, dict) or policy.get("concurrency") != 1 or policy.get("retries") != 0:
        raise ValueError("cloud_probe_must_be_serial_without_retry")
    if policy.get("maximum_requests_per_path_symbol") != 1:
        raise ValueError("cloud_probe_request_bound_invalid")
    corrections = config.get("code_corrections", {})
    if not isinstance(corrections, dict):
        raise ValueError("code_corrections_must_be_object")
    for key, correction in corrections.items():
        if not isinstance(correction, dict) or not correction.get("correct_symbol") or not correction.get("correct_name"):
            raise ValueError(f"code_correction_invalid:{key}")
    return config


def board_type(symbol: str, prefixes: dict[str, str]) -> str:
    if "+" in symbol:
        return "composite_components"
    return prefixes.get(symbol[:3], "other")


def _ths_candidates(capability: Any) -> list[dict[str, Any]]:
    return [{
        "provider": candidate.provider,
        "symbol": candidate.symbol,
        "provider_name": candidate.provider_name,
        "mapping_type": candidate.mapping_type,
        "exact_mapping": candidate.exact_mapping,
        "validation_status": candidate.validation_status,
    } for candidate in capability.candidates if candidate.provider == "ths_exact_spot"]


def _public_page_url(symbol: str, access_paths: list[dict[str, Any]]) -> str | None:
    detail = next((item for item in access_paths if item["access_path_id"] == "ths_detail_html"), None)
    if detail is None or "+" in symbol or not symbol.isdigit():
        return None
    return str(detail["url_template"]).format(symbol=symbol)


def build_audit(config_path: Path = DEFAULT_CONFIG, *, generated_at: str | None = None) -> dict[str, Any]:
    config = load_audit_config(config_path)
    registry = load_market_path_registry()
    capabilities = load_provider_capabilities()
    rows: list[dict[str, Any]] = []
    for path in registry.supported_market_paths:
        capability = capabilities[path.market_path_key]
        candidates = _ths_candidates(capability)
        candidate = candidates[0] if len(candidates) == 1 else None
        mapping_type = capability.mapping_type
        correction = config.get("code_corrections", {}).get(path.market_path_key)
        if correction is not None:
            status = "ths_board_code_needs_correction"
            issue = "mapping_problem"
            board_exists = True
            symbol, board_name = correction["correct_symbol"], correction["correct_name"]
        elif candidate is None:
            status = "no_suitable_ths_board"
            issue = "semantic_coverage_gap"
            board_exists = False
            symbol, board_name = None, None
        elif mapping_type == "composite":
            status = "ths_composite_required"
            issue = "composite_definition_required"
            board_exists = True
            symbol, board_name = candidate["symbol"], candidate["provider_name"]
        elif mapping_type == "proxy":
            status = "ths_acceptable_proxy_exists"
            issue = "provider_access_problem"
            board_exists = True
            symbol, board_name = candidate["symbol"], candidate["provider_name"]
        else:
            status = "ths_exact_board_exists"
            issue = "provider_access_problem"
            board_exists = True
            symbol, board_name = candidate["symbol"], candidate["provider_name"]
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid_audit_status:{path.market_path_key}")
        special = config.get("known_semantic_rules", {}).get(path.market_path_key, {})
        if special and correction is None and special.get("expected_status") != status:
            raise ValueError(f"special_semantic_rule_mismatch:{path.market_path_key}")
        if special and symbol and special.get("expected_symbol") not in (None, symbol):
            raise ValueError(f"special_symbol_mismatch:{path.market_path_key}")
        rows.append({
            "market_path_key": path.market_path_key,
            "display_name": path.display_name,
            "current_provider": capability.primary_provider,
            "current_symbol": symbol,
            "current_mapping_type": mapping_type,
            "current_semantic_name": capability.display_name,
            "ths_official_board_exists": board_exists,
            "ths_official_board_name": board_name,
            "ths_official_board_code": symbol,
            "ths_board_type": board_type(symbol, config["canonical_board_prefixes"]) if symbol else None,
            "ths_candidates": candidates,
            "public_page_url": _public_page_url(symbol, config["public_access_paths"]) if symbol else None,
            "public_page_status": "public_url_template_known" if symbol and "+" not in symbol else "not_a_single_board_page",
            "is_exact": status == "ths_exact_board_exists",
            "is_acceptable_proxy": status == "ths_acceptable_proxy_exists",
            "requires_composite": status == "ths_composite_required",
            "current_project_code_incorrect": status == "ths_board_code_needs_correction",
            "problem_class": issue,
            "evidence_summary": (
                "Existing formal capability matrix contains one exact THS candidate and a public detail URL template; "
                "access failure must be diagnosed independently from board existence."
                if board_exists else
                "No exact THS candidate is present in the formal capability matrix; prohibited substitutes remain excluded."
            ),
            "final_research_status": status,
            "basket_candidate": status == "no_suitable_ths_board",
            "prohibited_substitutes": special.get("prohibited_substitutes", []),
        })
    if len(rows) != len(registry.supported_market_paths) or len({row["market_path_key"] for row in rows}) != len(rows):
        raise ValueError("audit_scope_must_match_supported_registry")
    counts = Counter(row["final_research_status"] for row in rows)
    public_paths = config["public_access_paths"]
    return {
        "schema_version": "1.0.0",
        "analysis_type": "offline_ths_official_board_mapping_audit",
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "production_approved": False,
        "provider_integration_started": False,
        "network_requests": 0,
        "token_accessed": False,
        "cookie_used": False,
        "formal_registry_modified": False,
        "formal_candidate_chain_modified": False,
        "evidence_hashes": {
            "registry_sha256": _sha256(REGISTRY_PATH),
            "capability_sha256": _sha256(CAPABILITY_PATH),
            "audit_config_sha256": _sha256(config_path),
        },
        "summary": {
            "active_market_paths": len(rows),
            "ths_exact_board_exists": counts["ths_exact_board_exists"],
            "ths_acceptable_proxy_exists": counts["ths_acceptable_proxy_exists"],
            "ths_composite_required": counts["ths_composite_required"],
            "ths_board_code_needs_correction": counts["ths_board_code_needs_correction"],
            "no_suitable_ths_board": counts["no_suitable_ths_board"],
            "requires_business_decision": counts["requires_business_decision"],
            "single_official_ths_board_paths": counts["ths_exact_board_exists"] + counts["ths_acceptable_proxy_exists"],
            "paths_with_existing_ths_semantics_including_composites": len(rows) - counts["no_suitable_ths_board"],
            "genuine_semantic_gap_count": counts["no_suitable_ths_board"],
            "basket_candidate_paths": [row["market_path_key"] for row in rows if row["basket_candidate"]],
            "provider_access_problem_count": sum(row["problem_class"] == "provider_access_problem" for row in rows),
            "mapping_problem_count": sum(row["problem_class"] == "mapping_problem" for row in rows),
        },
        "rows": rows,
        "public_access_paths": public_paths,
        "existing_ths_detail_audit": {
            "endpoint_family": "q_10jqka_thshy_detail",
            "url_template": "https://q.10jqka.com.cn/thshy/detail/code/{symbol}/",
            "current_adapter_dependency": "all existing ths_exact_spot detail requests use this same family",
            "current_fields_parser": ["current", "pre_close", "open", "low", "high", "volume", "amount"],
            "as_of_parser": "not_source_derived_in_existing_adapter",
            "http_401_behavior": "existing shared transport maps unhandled HTTP 401 to generic network; independent probe must classify it as http_401",
            "board_existence_conflation": "A 401/access failure cannot establish that a board or its code does not exist.",
        },
        "recommendation": {
            "today": "Do not perform live acceptance after close. Run only the next-session five-path isolated probe.",
            "next_market_session": "Probe ths_detail_html once per dynamically selected representative; expand only if at least four of five return current, pre_close and source as_of.",
            "production_provider_changed": False,
        },
    }


def render_markdown(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        "# THS official board mapping audit",
        "",
        "> Research-only, offline mapping audit. No THS request, Cookie, Token, Provider integration or formal configuration change occurs in this analysis.",
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "|---|---:|",
        f"| Active market paths | {summary['active_market_paths']} |",
        f"| Exact THS board exists | {summary['ths_exact_board_exists']} |",
        f"| Acceptable THS proxy exists | {summary['ths_acceptable_proxy_exists']} |",
        f"| Composite required | {summary['ths_composite_required']} |",
        f"| Code correction | {summary['ths_board_code_needs_correction']} |",
        f"| Genuine semantic gap | {summary['genuine_semantic_gap_count']} |",
        f"| Existing THS semantics including composites | {summary['paths_with_existing_ths_semantics_including_composites']} |",
        "",
        "## Paths",
        "",
        "| Path | THS board | Code | Type | Result | Problem class |",
        "|---|---|---|---|---|---|",
    ]
    for row in result["rows"]:
        lines.append(
            f"| `{row['market_path_key']}` | {row['ths_official_board_name'] or '—'} | "
            f"{row['ths_official_board_code'] or '—'} | {row['ths_board_type'] or '—'} | "
            f"{row['final_research_status']} | {row['problem_class']} |"
        )
    lines.extend(["", "## Anonymous public paths", "", "| Path | Current | Pre-close | Source as-of | History | Recommendation |", "|---|---|---|---|---|---|"])
    for path in result["public_access_paths"]:
        lines.append(
            f"| `{path['access_path_id']}` | {path['current_candidate']} | {path['pre_close_candidate']} | "
            f"{path['as_of_candidate']} | {path['history_candidate']} | {path['recommendation']} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_outputs(result: dict[str, Any], output_dir: Path = DEFAULT_OUTPUT) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "ths-official-board-audit.json"
    csv_path = output_dir / "ths-official-board-audit.csv"
    markdown_path = output_dir / "ths-official-board-audit.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(result), encoding="utf-8")
    fields = ["market_path_key", "display_name", "current_provider", "current_symbol", "current_mapping_type", "ths_official_board_name", "ths_official_board_code", "ths_board_type", "is_exact", "is_acceptable_proxy", "requires_composite", "current_project_code_incorrect", "problem_class", "final_research_status", "basket_candidate"]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows([{field: row[field] for field in fields} for row in result["rows"]])
    return json_path, csv_path, markdown_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = build_audit(args.config)
    for path in write_outputs(result, args.output_dir):
        print(path)
    print(json.dumps(result["summary"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
