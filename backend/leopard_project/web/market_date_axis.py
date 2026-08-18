"""Controlled Market Core date axes for Reader objective-market views.

Report dates are deliberately absent here. Readers may layer report facts on
top of these dates, but reports and frozen paths never decide which completed
market days exist.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from leopard_project.trading_calendar import load_calendar

from .models import LiveMarketAnchorDaily, SecurityProxyDaily


def market_core_completed_dates(session: Session) -> tuple[date, ...]:
    """Return controlled dates in the coverage interval of Market Core rows."""
    calendar = load_calendar()
    if calendar is None:
        return ()
    bounds = (
        session.scalar(select(func.min(LiveMarketAnchorDaily.trading_date))),
        session.scalar(select(func.max(LiveMarketAnchorDaily.trading_date))),
        session.scalar(select(func.min(SecurityProxyDaily.trading_date))),
        session.scalar(select(func.max(SecurityProxyDaily.trading_date))),
    )
    present = tuple(item for item in bounds if item is not None)
    if not present:
        return ()
    first, latest = min(present), max(present)
    return tuple(day for day in sorted(calendar.trading_dates()) if first <= day <= latest)
