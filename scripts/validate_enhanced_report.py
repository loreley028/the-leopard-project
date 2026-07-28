from __future__ import annotations

import json
from pathlib import Path

from leopard_project.config import load_seed_bundle
from run_enhanced_demo import build_demo_documents


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    statuses = json.loads((ROOT / "config/sector_path_status_v1.json").read_text(encoding="utf-8"))
    expected = {"avoid", "strong_watch", "watch", "weak_watch", "turn_hold", "hold", "turn_weak", "exit", "not_mentioned"}
    actual = {item["code"] for item in statuses["statuses"]}
    fixture = json.loads((ROOT / "tests/fixtures/enhanced_reports_v1.json").read_text(encoding="utf-8"))
    demo_documents = build_demo_documents(fixture, load_seed_bundle().sectors)
    policy = json.loads((ROOT / "config/enhanced_report_policy_v1.json").read_text(encoding="utf-8"))
    documents = (
        "enhanced-report-product.md", "report-market-date-contract.md", "sector-path-status.md",
        "history-path-matrix.md", "sector-market-metrics.md", "report-market-snapshot.md",
        "manual-market-refresh.md", "report-comparison.md", "intraday-market-data.md",
    )
    results = {
        "path_status_contract": actual == expected and len(statuses["statuses"]) == 9,
        "fixture_reports": len(fixture["reports"]) >= 4,
        "fidelity_fixture_reports": len(demo_documents) == 20 and all(len(item["statuses"]) == 16 for item in demo_documents),
        "fidelity_skips_friday_saturday": all(__import__("datetime").date.fromisoformat(item["report_date"]).weekday() not in {4, 5} for item in demo_documents),
        "sunday_fixture": any(item["report_date"] in {"2026-07-12", "2026-07-19"} for item in fixture["reports"]),
        "weekday_fixtures": sum(item["report_date"] in {"2026-07-13", "2026-07-14", "2026-07-16"} for item in fixture["reports"]) >= 3,
        "status_coverage": {"hold", "watch", "turn_hold", "turn_weak", "exit", "not_mentioned"} <= {status for item in fixture["reports"] for status in item["statuses"].values()},
        "support_scope": policy["catalog_count"] == 66 and policy["supported_sector_count"] == 65 and policy["unsupported_sector_keys"] == ["hang_seng_tech"],
        "research_only": policy["market_data_role"] == "best_effort_research_source" and policy["automatic_scheduler"] is True,
        "no_external_llm": policy["external_llm_enabled"] is False,
        "snapshot_immutable": policy["report_snapshot_immutable_after_publish"] is True,
        "documents": all((ROOT / "docs" / name).is_file() for name in documents) and all((ROOT / "docs" / name).is_file() for name in ("pdf-parse-quality-gate.md", "viewer-acceptance-fidelity.md")),
    }
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
