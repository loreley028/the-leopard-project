from __future__ import annotations

from leopard_project.report_registry import load_report_registry
from leopard_project.web.enhanced import effective_statuses


def test_full_registry_has_74_display_rows_and_71_active_objects() -> None:
    registry = load_report_registry()
    assert len(registry) == 74
    assert sum(item.lifecycle == "active" for item in registry) == 71
    assert sum(item.lifecycle == "historical_carry" for item in registry) == 3


def test_split_v29_report_rows_are_active_without_market_mappings() -> None:
    by_key = {item.sector_key: item for item in load_report_registry()}
    for key in ("computer_equipment", "innovative_drug", "medical_biology", "battery", "lithium_battery", "photovoltaic", "energy_storage", "nuclear_power"):
        assert by_key[key].lifecycle == "active"
        assert by_key[key].market_sector_key is None
    for key in ("innovative_drug_medicine", "battery_lithium", "photovoltaic_energy_storage"):
        assert by_key[key].lifecycle == "historical_carry"


def test_daily_marker_and_effective_status_stay_distinct() -> None:
    markers = ["hold", "not_mentioned", "not_mentioned", "watch"]
    assert effective_statuses(markers) == ["hold", "hold", "hold", "watch"]
