from datetime import date, timedelta
from types import SimpleNamespace

from leopard_project.dormant_sectors import classify_dormant_sector


def _days(count: int = 20) -> list[date]:
    start = date(2026, 7, 20)
    return [start + timedelta(days=index) for index in range(count)]


def _entry(day: date, status: str) -> SimpleNamespace:
    return SimpleNamespace(path_report_date=day, path_status=status)


def test_dormant_requires_ten_actual_overlays_and_all_unmentioned(monkeypatch) -> None:
    days = _days()
    monkeypatch.setattr("leopard_project.dormant_sectors.report_market_date", lambda value: value)
    evidence = classify_dormant_sector([_entry(day, "not_mentioned") for day in days[:10]], days)
    assert evidence.is_dormant is True and evidence.overlay_count == 10


def test_dormant_ignores_no_report_days_and_rejects_insufficient_coverage(monkeypatch) -> None:
    days = _days()
    monkeypatch.setattr("leopard_project.dormant_sectors.report_market_date", lambda value: value)
    evidence = classify_dormant_sector([_entry(day, "not_mentioned") for day in days[:9]], days)
    assert evidence.is_dormant is False and evidence.overlay_count == 9


def test_any_explicit_status_in_controlled_window_prevents_dormant(monkeypatch) -> None:
    days = _days()
    monkeypatch.setattr("leopard_project.dormant_sectors.report_market_date", lambda value: value)
    entries = [_entry(day, "not_mentioned") for day in days[:10]]
    entries[-1] = _entry(days[9], "hold")
    assert classify_dormant_sector(entries, days).is_dormant is False


def test_calendar_mapping_is_allowed_but_no_data_fallback_is_not(monkeypatch) -> None:
    days = _days()
    report_day = date(2026, 8, 2)
    monkeypatch.setattr("leopard_project.dormant_sectors.report_market_date", lambda value: days[-1] if value == report_day else value)
    evidence = classify_dormant_sector([_entry(report_day, "not_mentioned") for _ in range(10)], days)
    assert evidence.overlay_count == 10 and evidence.markers == ("not_mentioned",) * 10
