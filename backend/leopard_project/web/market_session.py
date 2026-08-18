"""Reader-facing CN-A quote display semantics.

Freshness remains strict while continuous trading is under way.  During the
scheduled lunch break and after close, however, an otherwise valid quote from
the current controlled trading day is the honest "latest today" observation,
not an outage or a completed-EOD substitute.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from leopard_project.trading_calendar import CalendarStatus, load_calendar


SHANGHAI = ZoneInfo("Asia/Shanghai")
LIVE_FRESHNESS = timedelta(minutes=15)


@dataclass(frozen=True)
class QuoteDisplayDecision:
    status: str
    freshness: str
    display_mode: str
    session_state: str
    error_code: str | None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def cn_a_session_state(now: datetime) -> str:
    local = _aware(now).astimezone(SHANGHAI)
    calendar = load_calendar()
    if calendar is None or calendar.evaluate(local.date()).status != CalendarStatus.TRADING_DAY:
        return "non_trading_day"
    current = local.timetz().replace(tzinfo=None)
    if time(9, 30) <= current < time(11, 30) or time(13, 0) <= current < time(15, 0):
        return "continuous"
    if time(11, 30) <= current < time(13, 0):
        return "lunch_break"
    if current >= time(15, 0):
        return "after_close"
    return "before_open"


def reader_quote_display(*, quote_available: bool, quote_datetime: datetime | None, current: object | None, now: datetime) -> QuoteDisplayDecision:
    """Fail closed only when a same-day session exception is not justified."""
    session_state = cn_a_session_state(now)
    if not quote_available or quote_datetime is None or current is None:
        return QuoteDisplayDecision("unavailable", "unavailable", "unavailable", session_state, "provider_unavailable")
    local_now = _aware(now).astimezone(SHANGHAI)
    local_quote = _aware(quote_datetime).astimezone(SHANGHAI)
    age = local_now - local_quote
    if timedelta(0) <= age <= LIVE_FRESHNESS:
        return QuoteDisplayDecision("available", "fresh", "live", session_state, None)
    if local_quote.date() == local_now.date() and session_state in {"lunch_break", "after_close"}:
        return QuoteDisplayDecision("available", "session_latest", "same_day_session_latest", session_state, None)
    return QuoteDisplayDecision("unavailable", "stale", "unavailable", session_state, "stale_quote")
