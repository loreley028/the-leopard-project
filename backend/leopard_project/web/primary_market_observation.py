"""Reader-facing fixed primary market observations.

This module deliberately reads only the versioned proxy registry and completed
``security_proxy_daily`` rows.  It never selects a security from performance,
falls back to a different symbol, or derives a sector-level return.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from leopard_project.indicators import distance_from_average, moving_average
from leopard_project.security_proxy_observation import SecurityProxyDefinition

from .models import SecurityProxyDaily


def _float(value: Decimal | float | None) -> float | None:
    return float(value) if value is not None else None


def _pct(close: Decimal, previous: Decimal | None) -> float | None:
    return float((close / previous - Decimal("1")) * Decimal("100")) if previous and previous > 0 else None


def _row_payload(row: SecurityProxyDaily, previous: Decimal | None) -> dict:
    close = Decimal(str(row.close))
    return {
        "trading_date": row.trading_date.isoformat(),
        "close": float(close),
        "daily_pct_change": _pct(close, previous),
    }


def primary_history(session: Session, definition: SecurityProxyDefinition, *, limit: int = 10) -> dict | None:
    """Return one stable symbol's completed history, metrics, and identity.

    The extra preceding row permits a truthful change percentage for the first
    displayed day.  Fewer than ten real dates remain truthful rather than being
    padded.  MA windows use the same fixed symbol and completed closes only.
    """
    primary = definition.primary_observation
    if primary is None:
        return None
    rows = tuple(reversed(session.scalars(select(SecurityProxyDaily).where(
        SecurityProxyDaily.symbol == primary.symbol,
    ).order_by(desc(SecurityProxyDaily.trading_date)).limit(max(21, limit + 1))).all()))
    if not rows:
        return {
            "symbol": primary.symbol, "name": primary.security_name, "security_code": primary.reader_code, "role": primary.proxy_role,
            "date_axis_kind": "market_trading_day",
            "trade_date": None, "close": None, "daily_pct_change": None, "return_10d": None,
            "history": [], "history_days": 0, "ma5": None, "ma10": None, "ma20": None,
            "close_vs_ma5_pct": None, "close_vs_ma10_pct": None, "close_vs_ma20_pct": None,
        }
    previous: Decimal | None = None
    payload = []
    for row in rows:
        payload.append(_row_payload(row, previous))
        previous = Decimal(str(row.close))
    history = payload[-limit:]
    closes = tuple(Decimal(str(item["close"])) for item in payload)
    current = closes[-1]
    ma5, ma10, ma20 = (moving_average(closes, window) for window in (5, 10, 20))
    return {
        "symbol": primary.symbol, "name": primary.security_name, "security_code": primary.reader_code, "role": primary.proxy_role,
        "date_axis_kind": "market_trading_day",
        "trade_date": rows[-1].trading_date.isoformat(), "close": float(current),
        "daily_pct_change": history[-1]["daily_pct_change"],
        "return_10d": _pct(Decimal(str(history[-1]["close"])), Decimal(str(history[0]["close"]))) if len(history) >= 2 else None,
        "history": history, "history_days": len(history),
        "ma5": _float(ma5), "ma10": _float(ma10), "ma20": _float(ma20),
        "close_vs_ma5_pct": _float(distance_from_average(current, ma5)),
        "close_vs_ma10_pct": _float(distance_from_average(current, ma10)),
        "close_vs_ma20_pct": _float(distance_from_average(current, ma20)),
    }


def primary_for_exact_date(session: Session, definition: SecurityProxyDefinition, trading_date: date) -> dict | None:
    """Return an exact-date row for the fixed primary; never look nearby."""
    primary = definition.primary_observation
    if primary is None:
        return None
    row = session.scalar(select(SecurityProxyDaily).where(
        SecurityProxyDaily.symbol == primary.symbol,
        SecurityProxyDaily.trading_date == trading_date,
    ))
    if row is None:
        return None
    previous = session.scalar(select(SecurityProxyDaily).where(
        SecurityProxyDaily.symbol == primary.symbol,
        SecurityProxyDaily.trading_date < trading_date,
    ).order_by(desc(SecurityProxyDaily.trading_date)).limit(1))
    return {
        "symbol": primary.symbol, "name": primary.security_name, "role": primary.proxy_role,
        "trading_date": row.trading_date.isoformat(), "close": float(row.close),
        "pct_change": _pct(Decimal(str(row.close)), Decimal(str(previous.close)) if previous else None),
    }
