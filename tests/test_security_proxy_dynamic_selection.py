from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from leopard_project.security_proxy_dynamic_selection import (
    SecurityProxyDynamicSelectionError, SecurityProxyDynamicSelectionService, SecurityProxySelectionSnapshotStore,
    load_selection_preferences,
)
from leopard_project.security_proxy_eod import SHANGHAI, SecurityProxyEodRecord


DAY = date(2026, 8, 5)


def record(symbol: str, day: date, *, low: str = "9", close: str = "10", amount: str | None = "100") -> SecurityProxyEodRecord:
    return SecurityProxyEodRecord(symbol, symbol, day, Decimal("10"), Decimal("12"), Decimal(low), Decimal(close), Decimal(amount) if amount else None, datetime(day.year, day.month, day.day, 15, 1, tzinfo=SHANGHAI), datetime.now(timezone.utc), completeness_status="complete" if amount else "partial_amount_missing")


def history(symbol: str, *, amount: str = "100", rebound: bool = False) -> list[SecurityProxyEodRecord]:
    previous: list[date] = []
    cursor = DAY - timedelta(days=1)
    while len(previous) < 19:
        if cursor.weekday() < 5: previous.append(cursor)
        cursor -= timedelta(days=1)
    days = list(reversed(previous)) + [DAY]
    return [record(symbol, day, low="5" if rebound and i == 0 else "9", close="10" if i < len(days) - 1 else "12", amount=amount) for i, day in enumerate(days)]


def test_preferences_cover_exactly_the_approved_paths_and_keep_manual_contracts() -> None:
    preferences = {item.market_path_key: item for item in load_selection_preferences()}
    assert len(preferences) == 11
    assert preferences["cpo"].required_symbols == ("sz300308", "sz300502", "sz300394")
    assert preferences["innovative_drug_medicine"].required_symbols == ("sh603259", "sz300760")
    assert preferences["semiconductor"].excluded_symbols == ("sz300474",)


def test_manual_etf_and_leaders_work_without_aum_or_market_cap() -> None:
    service = SecurityProxyDynamicSelectionService(now=lambda: datetime(2026, 8, 5, tzinfo=timezone.utc))
    cpo = next(item for item in service.build(DAY, [record("sz300308", DAY), record("sz300502", DAY), record("sz300394", DAY)]) if item.market_path_key == "cpo")
    assert [item.symbol for item in cpo.selected_instruments] == ["sz300308", "sz300502", "sz300394", "sh515880"]
    assert all("required_manual" in item.selection_reasons for item in cpo.selected_instruments[:3])
    assert cpo.selected_instruments[-1].selection_reasons == ("preferred_etf",)


def test_twenty_day_low_rebound_turnover_and_dedup_are_deterministic() -> None:
    service = SecurityProxyDynamicSelectionService(now=lambda: datetime(2026, 8, 5, tzinfo=timezone.utc))
    values = history("sh600111", amount="500", rebound=True) + history("sz000831", amount="100") + history("sz000970", amount="800")
    rare = next(item for item in service.build(DAY, values) if item.market_path_key == "rare_earth")
    selected = {item.symbol: item for item in rare.selected_instruments}
    assert selected["sh516780"].selection_reasons == ("preferred_etf",)
    assert "preferred_large_cap" in selected["sh600111"].selection_reasons
    assert "fastest_rebound" in selected["sh600111"].selection_reasons
    assert "highest_turnover" in selected["sz000970"].selection_reasons


def test_insufficient_history_keeps_manual_list_with_explicit_warning() -> None:
    service = SecurityProxyDynamicSelectionService(now=lambda: datetime(2026, 8, 5, tzinfo=timezone.utc))
    rare = next(item for item in service.build(DAY, [record("sh600111", DAY), record("sz000831", DAY), record("sz000970", DAY)]) if item.market_path_key == "rare_earth")
    assert any(value.startswith("insufficient_fastest_rebound") for value in rare.warnings)
    assert [item.symbol for item in rare.selected_instruments][:2] == ["sh516780", "sh600111"]


def test_snapshot_is_atomic_immutable_and_only_effective_next_trading_day(tmp_path: Path) -> None:
    service = SecurityProxyDynamicSelectionService(now=lambda: datetime(2026, 8, 5, tzinfo=timezone.utc))
    snapshots = service.build(DAY, [record("sz300308", DAY), record("sz300502", DAY), record("sz300394", DAY)])
    store = SecurityProxySelectionSnapshotStore(tmp_path)
    path = store.write(calculation_date=DAY, snapshots=snapshots)
    assert path.exists() and not store.latest_effective_for(DAY)
    assert "cpo" in store.latest_effective_for(date(2026, 8, 6))
    with pytest.raises(FileExistsError): store.write(calculation_date=DAY, snapshots=snapshots)


def test_duplicate_history_fails_closed() -> None:
    service = SecurityProxyDynamicSelectionService()
    with pytest.raises(SecurityProxyDynamicSelectionError, match="duplicate"):
        service.build(DAY, [record("sh600111", DAY), record("sh600111", DAY)])
