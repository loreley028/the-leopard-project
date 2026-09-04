"""Pure effective-strategy projection of persisted Report Facts.

This is intentionally separate from report-calendar metadata and objective
market data.  A no-live calendar entry never reaches this module because it
has no report fact to project.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable, Iterable

from leopard_project.trading_calendar import next_controlled_trading_day


@dataclass(frozen=True)
class ReportStrategyFact:
    report_id: str
    report_date: date
    reported_status: str
    explicitly_mentioned: bool


@dataclass(frozen=True)
class EffectiveStrategy:
    effective_status: str | None
    source_report_id: str | None
    source_report_date: date | None
    effective_from: date | None
    display_signal: str | None
    derived_from_transition: bool


def effective_strategy_for_trading_day(
    facts: Iterable[ReportStrategyFact],
    trading_day: date,
    *,
    next_trading_day: Callable[[date], date | None] = next_controlled_trading_day,
) -> EffectiveStrategy:
    """Project persisted explicit report facts to one controlled trading day.

    ``turn_hold`` remains a report-local transition signal only on its first
    effective controlled day.  Its enduring effective state is ``hold``.
    Later reports that do not explicitly mention the sector retain the last
    explicit source and therefore cannot refresh provenance.
    """
    active: EffectiveStrategy | None = None
    for fact in sorted(facts, key=lambda item: (item.report_date, item.report_id)):
        effective_from = next_trading_day(fact.report_date)
        if effective_from is None or effective_from > trading_day:
            continue
        if not fact.explicitly_mentioned or fact.reported_status == "not_mentioned":
            continue
        effective_status = "hold" if fact.reported_status == "turn_hold" else fact.reported_status
        active = EffectiveStrategy(
            effective_status=effective_status,
            source_report_id=fact.report_id,
            source_report_date=fact.report_date,
            effective_from=effective_from,
            display_signal=fact.reported_status if effective_from == trading_day else None,
            derived_from_transition=fact.reported_status == "turn_hold",
        )
    return active or EffectiveStrategy(None, None, None, None, None, False)
