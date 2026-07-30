from __future__ import annotations

from datetime import date, timedelta

from leopard_project.trading_calendar import CalendarRuleSet, CalendarStatus


def main() -> None:
    rules = CalendarRuleSet.from_file()
    rules.validate()
    expected = {
        date(2026, 7, 29): CalendarStatus.TRADING_DAY,
        date(2026, 7, 30): CalendarStatus.TRADING_DAY,
        date(2026, 7, 31): CalendarStatus.TRADING_DAY,
        date(2026, 8, 1): CalendarStatus.CONFIRMED_NON_TRADING_DAY,
        date(2026, 8, 2): CalendarStatus.CONFIRMED_NON_TRADING_DAY,
        date(2026, 9, 25): CalendarStatus.CONFIRMED_NON_TRADING_DAY,
        date(2026, 9, 26): CalendarStatus.CONFIRMED_NON_TRADING_DAY,
        date(2026, 9, 27): CalendarStatus.CONFIRMED_NON_TRADING_DAY,
        date(2026, 9, 28): CalendarStatus.TRADING_DAY,
        date(2026, 10, 1): CalendarStatus.CONFIRMED_NON_TRADING_DAY,
        date(2026, 10, 7): CalendarStatus.CONFIRMED_NON_TRADING_DAY,
        date(2026, 10, 8): CalendarStatus.TRADING_DAY,
    }
    for day, status in expected.items():
        assert rules.evaluate(day).status == status, (day, rules.evaluate(day).status)
    current = rules.coverage_start
    while current <= rules.coverage_end:
        result = rules.evaluate(current)
        assert result.status in {CalendarStatus.TRADING_DAY, CalendarStatus.CONFIRMED_NON_TRADING_DAY}
        current += timedelta(days=1)
    assert rules.evaluate(rules.coverage_end + timedelta(days=1)).status == CalendarStatus.OUT_OF_RANGE
    today = date.today()
    assert rules.evaluate(today).status not in {CalendarStatus.OUT_OF_RANGE, CalendarStatus.UNAVAILABLE}, (
        f"current date {today} is outside controlled coverage"
    )
    for offset in range(31):
        day = today + timedelta(days=offset)
        assert rules.evaluate(day).status in {CalendarStatus.TRADING_DAY, CalendarStatus.CONFIRMED_NON_TRADING_DAY}, (
            f"calendar has no explicit status for {day}"
        )
    print(f"Trading calendar valid: {rules.coverage_start}..{rules.coverage_end}; {len(rules.trading_dates())} trading days")


if __name__ == "__main__":
    main()
