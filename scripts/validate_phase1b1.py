from __future__ import annotations

import json
from datetime import date

from leopard_project.config import PROJECT_ROOT
from leopard_project.eod import FixtureTradingCalendar, load_eod_policy
from leopard_project.provider_lineage import IndependenceStatus, compare_lineages, lineage_by_name
from leopard_project.reconciliation import ReconciliationStatus, load_reconciliation_policy
from leopard_project.support import build_collection_plan, load_support_policy


def main() -> int:
    support = load_support_policy()
    eod = load_eod_policy()
    calendar = FixtureTradingCalendar.from_file()
    reconciliation = load_reconciliation_policy()
    public = lineage_by_name("ths_public_validation")
    akshare = lineage_by_name("akshare_ths_research")
    summary = json.loads(
        (PROJECT_ROOT / "data/reconciliation-validation/reconciliation_summary.json").read_text(encoding="utf-8")
    )
    details = json.loads(
        (PROJECT_ROOT / "data/reconciliation-validation/reconciliation_details.json").read_text(encoding="utf-8")
    )
    plan = build_collection_plan(date(2026, 7, 21))
    assertions = {
        "current_report_and_market_path_scope": (
            support["total_business_sectors"] == 66
            and support["supported_market_sectors"] == 66
            and len(support["unsupported_sectors"]) == 1
        ),
        "dynamic_denominator": support["collection_denominator"] == len(plan.tasks) == 66,
        "hstech_excluded": all(task.sector_key != "hang_seng_tech" for task in plan.tasks),
        "safe_accept_after_configured": eod.safe_accept_after == "16:30",
        "cn_a_calendar_only": calendar.market.value == "CN_A" and not eod.production_calendar_approved,
        "amount_optional": "amount" in eod.optional_fields and "amount" not in eod.minimum_required_fields,
        "thresholds_validation_only": reconciliation.validation_only and not reconciliation.production_thresholds_approved,
        "all_reconciliation_statuses_supported": set(ReconciliationStatus) == {
            ReconciliationStatus.MATCHED, ReconciliationStatus.ACCEPTABLE_DIFFERENCE,
            ReconciliationStatus.MATERIAL_DIFFERENCE, ReconciliationStatus.SOURCE_NOT_INDEPENDENT,
            ReconciliationStatus.ONE_SOURCE_MISSING, ReconciliationStatus.BOTH_SOURCES_MISSING,
            ReconciliationStatus.INTRADAY_EXCLUDED, ReconciliationStatus.STALE_SOURCE,
            ReconciliationStatus.FUTURE_SNAPSHOT, ReconciliationStatus.FIELD_MISSING,
            ReconciliationStatus.CALENDAR_MISMATCH, ReconciliationStatus.PROVIDER_FAILED,
            ReconciliationStatus.MANUAL_REVIEW,
        },
        "akshare_role_research": akshare.provider_role == "research_provider",
        "shared_upstream_verified": (
            compare_lineages(public, akshare) == IndependenceStatus.SHARED_UPSTREAM
            and public.endpoint_host == akshare.endpoint_host == "d.10jqka.com.cn"
        ),
        "historical_replay_exactly_65": summary["plan_sector_count"] == 65 and len(details["records"]) == 65,
        "three_intraday_reclassified": summary["intraday_snapshot_count"] == 3,
        "no_independent_secondary": (
            summary["provider_b_success_count"] == 0
            and summary["provider_b_live_status"] == "blocked_by_dependency_network"
            and summary["independent_secondary_source_available"] is False
        ),
        "no_hstech_reconciliation": all(row["sector_key"] != "hang_seng_tech" for row in details["records"]),
        "no_production_primary": (
            support["production_primary_approved"] is False
            and summary["production_primary_approved"] is False
        ),
    }
    failed = [name for name, passed in assertions.items() if not passed]
    print(json.dumps({"checks": assertions, "passed": not failed}, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
