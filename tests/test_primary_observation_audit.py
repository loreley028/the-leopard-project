from __future__ import annotations

from collections import Counter

from leopard_project.config import CONFIG_DIR
from leopard_project.primary_observation_audit import build_primary_observation_audit


def test_mapping_audit_contains_71_active_objects() -> None:
    rows = build_primary_observation_audit(latest_completed_date="2026-08-18")
    assert len(rows) == 71
    assert len({row.sector_key for row in rows}) == 71


def test_mapping_audit_contains_69_mapped_2_unavailable() -> None:
    rows = build_primary_observation_audit(latest_completed_date="2026-08-18")
    assert Counter(row.market_status for row in rows) == {"ready": 69, "unavailable": 2}
    unavailable = {row.sector_key for row in rows if row.market_status == "unavailable"}
    assert unavailable == {"glass_substrate", "hang_seng_tech"}


def test_mapping_audit_does_not_mutate_registry() -> None:
    registry = CONFIG_DIR / "security_proxy_registry_v1.json"
    before = registry.read_bytes()
    build_primary_observation_audit(latest_completed_date="2026-08-18")
    assert registry.read_bytes() == before
