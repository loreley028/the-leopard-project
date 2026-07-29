from __future__ import annotations

import json
from pathlib import Path

from leopard_project.config import load_seed_bundle


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    schedule = json.loads((ROOT / "config/report_schedule_policy_v1.json").read_text(encoding="utf-8"))
    upload = json.loads((ROOT / "config/pdf_upload_policy_v1.json").read_text(encoding="utf-8"))
    ui_policy = json.loads((ROOT / "config/ui_dependency_policy_v1.json").read_text(encoding="utf-8"))
    support = json.loads((ROOT / "config/system_support_policy_v1.json").read_text(encoding="utf-8"))
    intraday = json.loads((ROOT / "config/intraday_market_policy_v1.json").read_text(encoding="utf-8"))
    intraday_mappings = json.loads((ROOT / "config/intraday_provider_mappings_v1.json").read_text(encoding="utf-8"))
    visibility = json.loads((ROOT / "config/sector_visibility_policy_v1.json").read_text(encoding="utf-8"))
    holding = json.loads((ROOT / "config/holding_interval_policy_v1.json").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    app = (ROOT / "backend/leopard_project/web/app.py").read_text(encoding="utf-8")
    enhanced_routes = (ROOT / "backend/leopard_project/web/enhanced_routes.py").read_text(encoding="utf-8")
    expected_routes = (
        "/api/v1/auth/login", "/api/v1/auth/logout", "/api/v1/auth/me",
        "/api/v1/reports", "/api/v1/reports/latest", "/api/v1/reports/{report_id}",
        "/api/v1/sectors", "/api/v1/sectors/{sector_key}",
        "/api/v1/admin/reports", "/api/v1/admin/reports/{report_id}",
        "/api/v1/admin/reports/{report_id}/parse", "/api/v1/admin/reports/{report_id}/ready",
        "/api/v1/admin/reports/{report_id}/publish", "/api/v1/admin/reports/{report_id}/withdraw",
        "/api/v1/admin/unmapped-terms/{term_id}/resolve",
    )
    components = (
        "IslandShell", "IslandHeader", "IslandNav", "IslandCard", "IslandButton", "IslandTag",
        "IslandStatusBadge", "IslandEmptyState", "IslandDialog", "IslandTable", "IslandField",
        "IslandUploadZone", "IslandTimeline", "IslandSelect",
    )
    checks = {
        "catalog_66": len(load_seed_bundle().sectors) == 66,
        "support_65_1_65": [support["supported_market_sectors"], support["unsupported_sector_count"], support["collection_denominator"]] == [65, 1, 65],
        "hstech_stays_unsupported": support["unsupported_sectors"][0]["sector_key"] == "hang_seng_tech",
        "pdf_independent": support["pdf_report_independence"]["independent"] is True,
        "schedule_timezone": schedule["timezone"] == "Asia/Shanghai",
        "schedule_sun_thu": schedule["expected_upload_weekdays"] == ["SUNDAY", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY"],
        "friday_saturday_normal": schedule["no_report_expected_weekdays"] == ["FRIDAY", "SATURDAY"] and schedule["missing_report_alert_enabled"] is False,
        "report_date_confirmation": schedule["upload_time_is_report_date"] is False
        and schedule["automatic_report_date_detection"] is True
        and schedule["report_date_requires_confirmation"] is False
        and schedule["report_date_confirmation_required_for"] == ["low", "conflict"],
        "local_pdf_only": upload["external_ai_enabled"] is False and upload["external_links_followed"] is False,
        "sqlite_and_upload_ignored": "var/uploads/" in (ROOT / ".gitignore").read_text() and "var/*.sqlite3" in (ROOT / ".gitignore").read_text(),
        "all_api_routes": all(route in app for route in expected_routes),
        "all_island_components": all((ROOT / f"frontend/src/components/island/{name}.tsx").is_file() for name in components),
        "react_vite_typescript": all(name in package.get("dependencies", {}) | package.get("devDependencies", {}) for name in ("react", "react-dom", "vite", "typescript")),
        "animal_library_exact": package.get("dependencies", {}).get("animal-island-ui") == "1.3.0",
        "ui_noncommercial_gate": ui_policy["usage_scope"] == "private_noncommercial_research" and ui_policy["usage_is_commercial"] is False and ui_policy["approved_for_current_scope"] is True and ui_policy["commercialization_review_required"] is True,
        "ui_attribution_present": (ROOT / "THIRD_PARTY_NOTICES.md").is_file() and (ROOT / "docs/ui-license-assessment.md").is_file(),
        "fixture_demo_available": (ROOT / "tests/fixtures/sample_report_fixture.pdf").is_file() and (ROOT / "scripts/run_phase2a0_demo.py").is_file(),
        "ci_retains_history": all(name in workflow for name in ("validate_phase0.py", "validate_phase1a.py", "validate_phase1b0.py", "validate_phase1b1.py")),
        "ci_has_frontend": all(name in workflow for name in ("npm ci", "npm run lint", "npm run typecheck", "npm run test", "npm run build")),
        "production_primary_false": support["production_primary_approved"] is False,
        "intraday_five_minute_server_cache": intraday["refresh_interval_minutes"] == 5
        and intraday["max_concurrency"] == 1
        and intraday["viewer_provider_access"] is False,
        "intraday_safe_auto_start": intraday["auto_start"] is True
        and intraday["stop_at_market_close"] is True
        and intraday["production_approved"] is False,
        "intraday_research_chain": intraday["provider"] == "research_intraday_chain"
        and intraday["provider_role"] == "research_provider"
        and intraday["candidate_evaluations"][0]["result"] == "local_live_validated"
        and all(symbol in intraday["candidate_evaluations"][0]["lineage"] for symbol in ("886050", "881158", "881173")),
        "intraday_exact_mappings": {
            item["sector_key"]: item["provider_symbol"] for item in intraday_mappings["mappings"]
        } == {"computing_power_rental": "886050", "retail": "881158", "small_appliances": "881173"}
        and all(item["review_status"].startswith("confirmed_") for item in intraday_mappings["mappings"]),
        "intraday_routes": all(route in enhanced_routes for route in (
            "/api/v1/market/intraday/status", "/api/v1/market/intraday/sectors",
            "/api/v1/admin/market/intraday/start", "/api/v1/admin/market/intraday/pause",
            "/api/v1/admin/market/intraday/refresh-now",
        )),
        "intraday_documented": (ROOT / "docs/intraday-market-data.md").is_file(),
        "intraday_status_centralized": intraday["status_resolver"] == "centralized_v1",
        "holding_interval_contract": holding["strict_allowed_statuses"] == ["turn_hold", "hold"]
        and "strong_watch" in holding["broad_allowed_statuses"] and holding["formal_return_source"] == "complete_eod",
        "visibility_contract": visibility["consecutive_not_mentioned_threshold"] == 10
        and visibility["protect_active_broad_holding"] is True and visibility["allow_admin_pin"] is True,
        "acceptance_docs_present": all((ROOT / f"docs/{name}").is_file() for name in (
            "holding-intervals.md", "sector-visibility.md", "intraday-provider-evaluation.md",
        )),
    }
    result = {"checks": checks, "passed": all(checks.values())}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
