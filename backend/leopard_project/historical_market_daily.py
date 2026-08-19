"""Exact-date backfill of the standalone Market Core daily tables."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .live_market_anchor_daily import SHANGHAI_COMPOSITE_SYMBOL
from .providers.sina_public_daily import SinaDailyBar, SinaPublicDailyMarketProvider
from .security_proxy_daily import market_core_security_symbols
from .trading_calendar import load_calendar
from .web.models import LiveMarketAnchorDaily, SecurityProxyDaily


SHANGHAI = ZoneInfo("Asia/Shanghai")
COMPLETE_AFTER = time(15, 10)


@dataclass(frozen=True)
class HistoricalBackfillSummary:
    requested_symbols: int
    inserted: int
    skip_existing_same: int
    conflicts: int
    replaced: int
    provider_failures: dict[str, str]


@dataclass(frozen=True)
class MarketHistoryRefreshSummary:
    expected_latest_completed_trading_day: date
    requested_symbols: int
    inserted: int
    skip_existing_same: int
    conflicts: int
    provider_failures: dict[str, str]


def market_core_symbols() -> tuple[str, ...]:
    return tuple(dict.fromkeys((
        SHANGHAI_COMPOSITE_SYMBOL,
        *market_core_security_symbols(),
    )))


def expected_latest_completed_trading_day(now: datetime) -> date:
    """Return the exact latest CN-A completed date from the controlled calendar.

    Before the close buffer, the current trading day is deliberately excluded.
    This calculation is Market Core only: it never reads reports, PDFs or
    report dates.
    """

    calendar = load_calendar()
    if calendar is None:
        raise ValueError("calendar_unavailable")
    local = now.astimezone(SHANGHAI) if now.tzinfo is not None else now.replace(tzinfo=SHANGHAI)
    cutoff = local.date() if local.time().replace(tzinfo=None) >= COMPLETE_AFTER else local.date() - timedelta(days=1)
    return max((day for day in calendar.trading_dates() if day <= cutoff), default=None) or _raise_no_completed_day()


def _raise_no_completed_day() -> date:
    raise ValueError("no_completed_trading_day")


def _close_matches(left: Decimal, right: Decimal) -> bool:
    tolerance = Decimal("0.005") if max(left, right) < Decimal("10") else Decimal("0.01")
    return abs(left - right) <= tolerance


def _eod_datetime(day) -> datetime:
    return datetime.combine(day, time(15, 0), SHANGHAI)


def _completed_bars(bars: tuple[SinaDailyBar, ...], now: datetime) -> tuple[SinaDailyBar, ...]:
    """Never let a same-day intraday bar enter completed-market history."""

    local = now.astimezone(SHANGHAI) if now.tzinfo is not None else now.replace(tzinfo=SHANGHAI)
    return tuple(
        bar for bar in bars
        if bar.trading_date < local.date() or (bar.trading_date == local.date() and local.time().replace(tzinfo=None) >= COMPLETE_AFTER)
    )


def _insert_anchor(session: Session, bar: SinaDailyBar, *, previous: Decimal | None, replace: bool) -> str:
    existing = session.scalar(select(LiveMarketAnchorDaily).where(
        LiveMarketAnchorDaily.symbol == SHANGHAI_COMPOSITE_SYMBOL,
        LiveMarketAnchorDaily.trading_date == bar.trading_date,
    ))
    if existing is not None:
        if _close_matches(Decimal(str(existing.close)), bar.close):
            return "skip_existing_same"
        if not replace or previous is None:
            return "conflict"
        existing.close = bar.close
        existing.pre_close = previous
        existing.pct_change = (bar.close / previous - Decimal("1")) * Decimal("100")
        existing.high = bar.high
        existing.low = bar.low
        existing.quote_datetime = _eod_datetime(bar.trading_date)
        existing.fetched_at = datetime.now(SHANGHAI)
        existing.source = SinaPublicDailyMarketProvider.provider_key
        return "replaced"
    if previous is None:
        return "no_previous_close"
    session.add(LiveMarketAnchorDaily(
        symbol=SHANGHAI_COMPOSITE_SYMBOL, trading_date=bar.trading_date, close=bar.close,
        pre_close=previous, pct_change=(bar.close / previous - Decimal("1")) * Decimal("100"),
        high=bar.high, low=bar.low, quote_datetime=_eod_datetime(bar.trading_date),
        fetched_at=datetime.now(SHANGHAI), source=SinaPublicDailyMarketProvider.provider_key,
    ))
    return "inserted"


def _insert_proxy(session: Session, symbol: str, bar: SinaDailyBar, *, replace: bool) -> str:
    existing = session.scalar(select(SecurityProxyDaily).where(
        SecurityProxyDaily.symbol == symbol, SecurityProxyDaily.trading_date == bar.trading_date,
    ))
    if existing is not None:
        if _close_matches(Decimal(str(existing.close)), bar.close):
            return "skip_existing_same"
        if not replace:
            return "conflict"
        existing.close = bar.close
        existing.open = bar.open
        existing.high = bar.high
        existing.low = bar.low
        existing.amount_yuan = None
        existing.quote_datetime = _eod_datetime(bar.trading_date)
        existing.fetched_at = datetime.now(SHANGHAI)
        existing.source = SinaPublicDailyMarketProvider.provider_key
        return "replaced"
    session.add(SecurityProxyDaily(
        symbol=symbol, trading_date=bar.trading_date, close=bar.close, open=bar.open, high=bar.high, low=bar.low,
        amount_yuan=None, quote_datetime=_eod_datetime(bar.trading_date), fetched_at=datetime.now(SHANGHAI),
        source=SinaPublicDailyMarketProvider.provider_key,
    ))
    return "inserted"


def backfill_market_history(
    session: Session,
    *,
    provider: SinaPublicDailyMarketProvider,
    days: int = 30,
    enable_provider: bool = False,
    replace: bool = False,
    now: datetime | None = None,
) -> HistoricalBackfillSummary:
    """Backfill only fixed registry symbols plus Shanghai; default never overwrites."""

    if not enable_provider:
        raise PermissionError("explicit historical Provider enablement is required")
    inserted = skipped = conflicts = replaced = 0
    failures: dict[str, str] = {}
    observed_at = now or datetime.now(SHANGHAI)
    for symbol in market_core_symbols():
        try:
            bars = _completed_bars(provider.fetch_history(symbol, days=days, allow_network=True), observed_at)
        except Exception as exc:
            failures[symbol] = getattr(exc, "code", type(exc).__name__)
            continue
        if len(bars) < 20:
            failures[symbol] = "insufficient_completed_history"
            continue
        previous: Decimal | None = None
        for bar in bars:
            result = (
                _insert_anchor(session, bar, previous=previous, replace=replace)
                if symbol == SHANGHAI_COMPOSITE_SYMBOL
                else _insert_proxy(session, symbol, bar, replace=replace)
            )
            previous = bar.close
            inserted += result == "inserted"
            skipped += result == "skip_existing_same"
            conflicts += result == "conflict"
            replaced += result == "replaced"
        session.commit()
    return HistoricalBackfillSummary(len(market_core_symbols()), inserted, skipped, conflicts, replaced, failures)


def refresh_market_history_to_latest_completed(
    session: Session,
    *,
    provider: SinaPublicDailyMarketProvider,
    enable_provider: bool = False,
    now: datetime | None = None,
) -> MarketHistoryRefreshSummary:
    """Fill only the exact latest completed Market Core day, fail-closed.

    This explicit preview/acceptance operation does not create a scheduler and
    does not depend on report upload.  Existing values are compared against
    the source, conflicts are reported without replacement, and no earlier or
    later date is written.
    """

    if not enable_provider:
        raise PermissionError("explicit historical Provider enablement is required")
    observed_at = now or datetime.now(SHANGHAI)
    expected = expected_latest_completed_trading_day(observed_at)
    inserted = skipped = conflicts = 0
    failures: dict[str, str] = {}
    for symbol in market_core_symbols():
        try:
            bars = provider.fetch_history(symbol, days=20, allow_network=True)
        except Exception as exc:
            failures[symbol] = getattr(exc, "code", type(exc).__name__)
            continue
        target_index = next((index for index, bar in enumerate(bars) if bar.trading_date == expected), None)
        if target_index is None:
            failures[symbol] = "expected_completed_date_missing"
            continue
        bar = bars[target_index]
        result = (
            _insert_anchor(session, bar, previous=bars[target_index - 1].close if target_index else None, replace=False)
            if symbol == SHANGHAI_COMPOSITE_SYMBOL
            else _insert_proxy(session, symbol, bar, replace=False)
        )
        if result == "no_previous_close":
            failures[symbol] = "previous_close_missing"
        else:
            inserted += result == "inserted"
            skipped += result == "skip_existing_same"
            conflicts += result == "conflict"
        session.commit()
    return MarketHistoryRefreshSummary(expected, len(market_core_symbols()), inserted, skipped, conflicts, failures)
