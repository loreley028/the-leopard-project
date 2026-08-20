from __future__ import annotations

from collections import Counter

from leopard_project.config import CONFIG_DIR
from leopard_project.sector_security_composition_audit import build_composition_audit, write_composition_audit


def test_full_composition_audit_has_exactly_71_active_objects_and_preserves_registry(tmp_path) -> None:
    registry = CONFIG_DIR / "security_proxy_registry_v1.json"
    before = registry.read_bytes()
    details, summaries, reuse = build_composition_audit(latest_completed_date="2026-08-20")
    assert registry.read_bytes() == before
    assert len(summaries) == 71
    assert len({item["sector_key"] for item in summaries}) == 71
    assert len(details) >= 71 and reuse
    assert Counter(item["composition_pattern"] for item in summaries)["UNAVAILABLE"] == 2
    cpo = next(item for item in summaries if item["sector_key"] == "cpo")
    assert cpo["matrix_current_primary"] == "515880.SH"
    assert cpo["matrix_current_stock"] == "300308.SZ"


def test_composition_summary_and_reuse_export_match_detail_rows(tmp_path) -> None:
    details, summaries, reuse = build_composition_audit(latest_completed_date="2026-08-20")
    assert sum(int(item["total_security_count"]) for item in summaries) == len(details)
    assert max(int(item["used_by_sector_count"]) for item in reuse) >= 2
    paths = write_composition_audit(tmp_path, latest_completed_date="2026-08-20")
    assert all(path.exists() and path.read_text(encoding="utf-8-sig").splitlines()[0] for path in paths)
