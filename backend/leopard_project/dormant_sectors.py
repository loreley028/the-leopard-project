"""Reader-only dormant-sector classification from authoritative Report facts.

Market performance and missing-report dates deliberately do not influence this
classification.  A sector is dormant only when enough actual report overlays
within the controlled completed-day window all say ``not_mentioned``.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from leopard_project.trading_calendar import report_market_date


DORMANT_WINDOW_TRADING_DAYS = 20
MINIMUM_REPORT_OVERLAYS = 10


@dataclass(frozen=True)
class DormantSectorEvidence:
    is_dormant: bool
    overlay_count: int
    markers: tuple[str, ...]
    window_start: date | None
    window_end: date | None


def classify_dormant_sector(
    entries: Iterable[object],
    completed_trading_days: Iterable[date],
    *,
    window_size: int = DORMANT_WINDOW_TRADING_DAYS,
    minimum_overlays: int = MINIMUM_REPORT_OVERLAYS,
) -> DormantSectorEvidence:
    """Classify one active Report Object without inventing report coverage.

    ``entries`` need only expose ``path_report_date`` and ``path_status``.  A
    report date is first mapped by the controlled calendar; absent report days
    produce no entry and therefore cannot be counted as ``not_mentioned``.
    """
    dates = tuple(sorted(dict.fromkeys(completed_trading_days)))[-window_size:]
    if not dates:
        return DormantSectorEvidence(False, 0, (), None, None)
    date_set = set(dates)
    markers = tuple(
        str(entry.path_status)
        for entry in entries
        if report_market_date(entry.path_report_date) in date_set
    )
    return DormantSectorEvidence(
        is_dormant=len(markers) >= minimum_overlays and all(marker == "not_mentioned" for marker in markers),
        overlay_count=len(markers),
        markers=markers,
        window_start=dates[0],
        window_end=dates[-1],
    )
