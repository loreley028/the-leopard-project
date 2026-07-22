from __future__ import annotations

import json

from leopard_project.config import CONFIG_DIR, PROJECT_ROOT


def main() -> int:
    policy = json.loads((CONFIG_DIR / "provider_policy_phase1a_v1.json").read_text(encoding="utf-8"))
    coverage = json.loads((PROJECT_ROOT / "data/provider-validation/coverage.json").read_text(encoding="utf-8"))
    summary = coverage["summary"]
    classifications = summary["exclusive_classifications"]
    hotel = next(row for row in coverage["results"] if row["sector_key"] == "hotel_catering")
    glass = next(row for row in coverage["results"] if row["sector_key"] == "glass_substrate")
    hstech = next(row for row in coverage["results"] if row["sector_key"] == "hang_seng_tech")
    assertions = {
        "exclusive_total_66": sum(classifications.values()) == 66 == summary["exclusive_classification_total"],
        "all_results_classified_once": len(coverage["results"]) == 66,
        "production_primary_not_approved": policy["production_primary_approved"] is False,
        "provider_roles_fixed": set(policy["provider_roles"].values()) == {"candidate_primary", "diagnostic_provider"},
        "amount_optional": policy["liquidity_policy"]["amount_required"] is False,
        "hotel_proxy_881160": hotel["provider_symbol"] == "881160" and hotel["primary_classification"] == "proxy_only" and hotel["data_status"] == "proxy",
        "glass_is_short_history": glass["original_mapping"] == "886111" and glass["primary_classification"] == "direct_short_history",
        "hstech_canonical_and_provider_symbols": hstech["canonical_symbol"] == "HSTECH" and hstech["provider_symbol"] == "HS2083",
        "hstech_snapshot_guard_active": "snapshot_anomaly" in hstech and hstech["eligible_for_normal_write"] is True,
        "tushare_hstech_symbol": policy["symbol_mappings"]["HSTECH"]["tushare_ths_daily"] == "HKTECH",
    }
    failed = [name for name, passed in assertions.items() if not passed]
    print(json.dumps({"checks": assertions, "passed": not failed}, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
