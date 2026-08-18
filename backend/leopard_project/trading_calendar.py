from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from pathlib import Path

from .config import CONFIG_DIR


RULES_PATH = CONFIG_DIR / "cn_a_trading_calendar_rules_2026.json"


class CalendarStatus(StrEnum):
    TRADING_DAY = "trading_day"
    CONFIRMED_NON_TRADING_DAY = "confirmed_non_trading_day"
    OUT_OF_RANGE = "calendar_out_of_range"
    UNAVAILABLE = "calendar_unavailable"


@dataclass(frozen=True)
class CalendarEvaluation:
    day: date
    status: CalendarStatus
    source: str | None
    coverage_start: date | None
    coverage_end: date | None
    reason: str | None = None


@dataclass(frozen=True)
class CalendarRuleSet:
    market: str
    year: int
    source: str
    source_version: str
    coverage_start: date
    coverage_end: date
    holiday_ranges: tuple[tuple[date, date], ...]
    closed_overrides: frozenset[date]
    open_overrides: frozenset[date]
    maintenance_notice_days: int

    @classmethod
    def from_file(cls, path: Path = RULES_PATH) -> "CalendarRuleSet":
        document = json.loads(path.read_text(encoding="utf-8"))
        ranges = tuple(
            (date.fromisoformat(item["start"]), date.fromisoformat(item["end"]))
            for item in document["holiday_ranges"]
        )
        rules = cls(
            market=document["market"],
            year=int(document["year"]),
            source=document["source"],
            source_version=document["source_version"],
            coverage_start=date.fromisoformat(document["coverage_start"]),
            coverage_end=date.fromisoformat(document["coverage_end"]),
            holiday_ranges=ranges,
            closed_overrides=frozenset(date.fromisoformat(value) for value in document["closed_overrides"]),
            open_overrides=frozenset(date.fromisoformat(value) for value in document["open_overrides"]),
            maintenance_notice_days=int(document.get("maintenance_notice_days", 30)),
        )
        rules.validate()
        return rules

    def validate(self) -> None:
        if self.coverage_start > self.coverage_end:
            raise ValueError("calendar_rule_invalid: coverage is reversed")
        if self.closed_overrides & self.open_overrides:
            raise ValueError("calendar_rule_invalid: override conflict")
        previous_end: date | None = None
        for start, end in sorted(self.holiday_ranges):
            if start > end or start < self.coverage_start or end > self.coverage_end:
                raise ValueError("calendar_rule_invalid: invalid holiday range")
            if previous_end is not None and start <= previous_end:
                raise ValueError("calendar_rule_invalid: overlapping holiday ranges")
            previous_end = end

    def evaluate(self, day: date) -> CalendarEvaluation:
        if day < self.coverage_start or day > self.coverage_end:
            return CalendarEvaluation(day, CalendarStatus.OUT_OF_RANGE, self.source, self.coverage_start, self.coverage_end)
        if day in self.open_overrides:
            return CalendarEvaluation(day, CalendarStatus.TRADING_DAY, self.source, self.coverage_start, self.coverage_end, "open_override")
        if day.weekday() >= 5:
            return CalendarEvaluation(day, CalendarStatus.CONFIRMED_NON_TRADING_DAY, self.source, self.coverage_start, self.coverage_end, "weekend")
        if any(start <= day <= end for start, end in self.holiday_ranges):
            return CalendarEvaluation(day, CalendarStatus.CONFIRMED_NON_TRADING_DAY, self.source, self.coverage_start, self.coverage_end, "official_holiday")
        if day in self.closed_overrides:
            return CalendarEvaluation(day, CalendarStatus.CONFIRMED_NON_TRADING_DAY, self.source, self.coverage_start, self.coverage_end, "closed_override")
        return CalendarEvaluation(day, CalendarStatus.TRADING_DAY, self.source, self.coverage_start, self.coverage_end)

    def trading_dates(self) -> set[date]:
        current = self.coverage_start
        result: set[date] = set()
        while current <= self.coverage_end:
            if self.evaluate(current).status == CalendarStatus.TRADING_DAY:
                result.add(current)
            current += timedelta(days=1)
        return result

    def metadata(self, today: date) -> dict[str, object]:
        evaluation = self.evaluate(today)
        days_remaining = (self.coverage_end - today).days
        return {
            "calendar_coverage_start": self.coverage_start.isoformat(),
            "calendar_coverage_end": self.coverage_end.isoformat(),
            "calendar_source": self.source,
            "calendar_source_version": self.source_version,
            "calendar_status": evaluation.status.value,
            "calendar_warning": "calendar_coverage_expiring" if 0 <= days_remaining <= self.maintenance_notice_days else None,
            "calendar_days_remaining": days_remaining,
        }


def load_calendar(path: Path = RULES_PATH) -> CalendarRuleSet | None:
    try:
        return CalendarRuleSet.from_file(path)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def evaluate_cn_a_day(day: date, path: Path = RULES_PATH) -> CalendarEvaluation:
    try:
        rules = CalendarRuleSet.from_file(path)
    except OSError:
        return CalendarEvaluation(day, CalendarStatus.UNAVAILABLE, None, None, None, "calendar_source_unavailable")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return CalendarEvaluation(day, CalendarStatus.UNAVAILABLE, None, None, None, "calendar_rule_invalid")
    return rules.evaluate(day)


def report_market_date(day: date, path: Path = RULES_PATH) -> date | None:
    """Return the one controlled market date associated with a report date.

    A report published on a controlled trading day uses that same day.  A
    weekend or exchange holiday report is intentionally paired with the prior
    *controlled* trading day.  This is calendar semantics, not a data lookup
    fallback: callers must still require an exact market record for the
    returned date and must not search backwards again when it is absent.
    """
    rules = load_calendar(path)
    if rules is None:
        return None
    evaluation = rules.evaluate(day)
    if evaluation.status == CalendarStatus.TRADING_DAY:
        return day
    if evaluation.status != CalendarStatus.CONFIRMED_NON_TRADING_DAY:
        return None
    return max((candidate for candidate in rules.trading_dates() if candidate < day), default=None)
