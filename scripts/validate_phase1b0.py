from __future__ import annotations

import json
from datetime import date

from leopard_project.config import PROJECT_ROOT, load_seed_bundle
from leopard_project.models import DataStatus, SupportStatus
from leopard_project.support import build_collection_plan, load_support_policy, validate_support_policy


def main() -> int:
    policy = load_support_policy()
    validate_support_policy(policy)
    plan = build_collection_plan(date.today())
    coverage_path = PROJECT_ROOT / "data/provider-selection/coverage_65.json"
    comparison_path = PROJECT_ROOT / "data/provider-selection/provider_comparison.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8")) if coverage_path.exists() else None
    comparison = json.loads(comparison_path.read_text(encoding="utf-8")) if comparison_path.exists() else None
    unsupported = plan.unsupported_sectors[0]
    assertions = {
        "business_catalog_66": len(load_seed_bundle().sectors) == plan.total_business_sectors == 66,
        "supported_65": len(plan.tasks) == plan.supported_market_sectors == 65,
        "unsupported_1": len(plan.unsupported_sectors) == 1,
        "hstech_unsupported": unsupported.sector_key == "hang_seng_tech" and unsupported.support_status == SupportStatus.UNSUPPORTED and unsupported.data_status == DataStatus.UNSUPPORTED,
        "collection_denominator_65": plan.collection_denominator == 65,
        "no_hstech_provider_request": all(task.sector_key != "hang_seng_tech" for task in plan.tasks),
        "hotel_proxy": next(task for task in plan.tasks if task.sector_key == "hotel_catering").data_status == DataStatus.PROXY,
        "glass_short_history": next(task for task in plan.tasks if task.sector_key == "glass_substrate").data_status == DataStatus.SHORT_HISTORY,
        "three_custom_composites": sum(task.mapping_type == "custom_composite" for task in plan.tasks) == 3,
        "pdf_independent": bool(policy["pdf_report_independence"]["independent"]),
        "no_production_provider": policy["production_primary_approved"] is False and policy["production_fallback_approved"] is False,
        "coverage_65_present": coverage is not None and coverage["summary"]["supported_sector_count"] == 65,
        "comparison_present": comparison is not None and comparison["production_primary_approved"] is False,
    }
    failed = [name for name, passed in assertions.items() if not passed]
    print(json.dumps({"checks": assertions, "passed": not failed}, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
