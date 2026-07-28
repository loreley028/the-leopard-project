from __future__ import annotations

import json
from datetime import date

from leopard_project.config import PROJECT_ROOT, load_seed_bundle
from scripts.run_enhanced_demo import build_demo_documents


def test_twenty_report_fidelity_fixture_is_deterministic_and_skips_friday_saturday() -> None:
    fixture = json.loads((PROJECT_ROOT / "tests/fixtures/enhanced_reports_v1.json").read_text(encoding="utf-8"))
    documents = build_demo_documents(fixture, load_seed_bundle().sectors)
    assert documents == build_demo_documents(fixture, load_seed_bundle().sectors)
    assert len(documents) == 20
    assert all(date.fromisoformat(item["report_date"]).weekday() not in {4, 5} for item in documents)
    assert all(len(item["statuses"]) == 16 for item in documents)
    assert all(item["market_as_of_date"] <= item["report_date"] for item in documents)
