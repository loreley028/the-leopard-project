from __future__ import annotations

from datetime import date
from pathlib import Path
import csv

from leopard_project.history_matrix_ordering import write_history_matrix_order_review
from leopard_project.report_registry import load_report_registry, reader_report_registry
from leopard_project.sector_lifecycle import parent_status_lineage_for_child
from leopard_project.security_proxy_observation import load_security_proxy_registry
from leopard_project.web.market_core import MarketCoreReadService
from leopard_project.web.database import create_session_factory
from leopard_project.web.enhanced import EnhancedReportService, effective_statuses, holding_interval_policy
from leopard_project.web.models import SectorPathHistoryEntry


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


def test_reader_registry_hides_historical_parents_but_keeps_active_children() -> None:
    keys = {item.sector_key for item in reader_report_registry()}
    assert len(keys) == 71
    assert not {"innovative_drug_medicine", "battery_lithium", "photovoltaic_energy_storage"} & keys
    assert {"innovative_drug", "medical_biology", "battery", "lithium_battery", "photovoltaic", "energy_storage"} <= keys


def test_reader_history_matrix_order_is_manual_static_and_places_cpo_before_mlcc(tmp_path: Path) -> None:
    reader = reader_report_registry()
    hardware = [item.sector_key for item in reader if item.group_order == 1]
    assert hardware.index("cpo") < hardware.index("mlcc")
    assert [item.within_group_order for item in (item for item in reader if item.group_order == 1)] == list(range(1, len(hardware) + 1))
    output = write_history_matrix_order_review(tmp_path / "history_matrix_order_review.csv", load_report_registry())
    with output.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 71
    cpo = next(item for item in rows if item["sector_key"] == "cpo")
    mlcc = next(item for item in rows if item["sector_key"] == "mlcc")
    assert (cpo["manual_order"], cpo["rationale_short"]) == ("2", "主线高频")
    assert int(cpo["manual_order"]) < int(mlcc["manual_order"])


def test_history_matrix_and_board_research_share_sector_order() -> None:
    reader_keys = [item.sector_key for item in reader_report_registry()]
    service = MarketCoreReadService(provider=None, live_anchor=None, registry=load_security_proxy_registry())  # type: ignore[arg-type]
    matrix_keys = [item.market_path_key for item in service._matrix_definitions()]
    assert matrix_keys == [item for item in reader_keys if item in set(matrix_keys)]
    assert matrix_keys.index("cpo") < matrix_keys.index("mlcc")


def test_split_lineage_uses_versioned_pre_split_status_only_dates() -> None:
    assert parent_status_lineage_for_child("battery").effective_report_date == date(2026, 7, 30)  # type: ignore[union-attr]
    assert parent_status_lineage_for_child("medical_biology").parent_sector_key == "innovative_drug_medicine"  # type: ignore[union-attr]
    assert parent_status_lineage_for_child("cpo") is None


def test_broad_holding_contract_keeps_turn_weak_but_ends_on_watch_or_worse() -> None:
    policy = holding_interval_policy()
    assert "turn_weak" in policy["broad_allowed"]
    assert "turn_weak" not in policy["broad_end"]
    assert policy["broad_end"] == {"watch", "weak_watch", "exit", "avoid"}


def test_pre_split_parent_status_is_available_to_child_without_parent_market_facts(tmp_path: Path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'split-lineage.sqlite3'}")
    with sessions() as session:
        session.add_all([
            SectorPathHistoryEntry(
                sector_key="battery_lithium", sector_name="电池/锂电池", path_report_date=date(2026, 7, 29), path_status="turn_hold",
                source_report_id="parent-source", detail_report_id=None, market_as_of_date=date(2026, 7, 29), frozen_daily_pct_change=1.25,
                market_data_status="complete", source_pdf_sha256="a" * 64,
            ),
            SectorPathHistoryEntry(
                sector_key="battery", sector_name="电池", path_report_date=date(2026, 7, 30), path_status="hold",
                source_report_id="child-source", detail_report_id=None, market_as_of_date=date(2026, 7, 30), frozen_daily_pct_change=2.0,
                market_data_status="complete", source_pdf_sha256="b" * 64,
            ),
        ])
        session.commit()
        entries = list(reversed(EnhancedReportService(session).path_history("battery")))
    assert [(item.path_report_date, item.path_status) for item in entries] == [(date(2026, 7, 29), "turn_hold"), (date(2026, 7, 30), "hold")]
    inherited = entries[0]
    assert inherited.inherited_from_sector_key == "battery_lithium"
    assert inherited.market_as_of_date is None
    assert inherited.frozen_daily_pct_change is None
    assert inherited.detail_report_id is None


def test_daily_marker_and_effective_status_stay_distinct() -> None:
    markers = ["hold", "not_mentioned", "not_mentioned", "watch"]
    assert effective_statuses(markers) == ["hold", "hold", "hold", "watch"]
