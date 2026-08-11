"""Explicit, fixed-registry daily-close capture for proxy observations."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Callable, Iterable, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .indicators import distance_from_average, moving_average
from .providers.tencent_standard_quote import TencentStandardSecurityQuoteProvider
from .security_proxy_observation import SecurityProxyDefinition, load_security_proxy_registry
from .trading_calendar import CalendarStatus, evaluate_cn_a_day
from .web.models import SecurityProxyDaily


SHANGHAI = ZoneInfo("Asia/Shanghai")
CAPTURE_AFTER = time(15, 10)
SOURCE = TencentStandardSecurityQuoteProvider.provider_key


class SecurityProxyDailyCaptureError(ValueError):
    """A fail-closed capture-window error raised before any Provider request."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SecurityProxyDailyCaptureSummary:
    target_trading_date: date
    candidate_count: int
    requested_count: int
    inserted_count: int
    already_exists_count: int
    invalid_count: int
    provider_batch_count: int
    failures: dict[str, str]


@dataclass(frozen=True)
class SecurityProxyRecentClose:
    trading_date: date
    close: Decimal
    change_pct_from_previous_close: Decimal | None


@dataclass(frozen=True)
class SecurityProxyTrendMetrics:
    recent_closes: tuple[SecurityProxyRecentClose, ...]
    ma5: Decimal | None
    ma10: Decimal | None
    ma20: Decimal | None
    distance_to_ma5_pct: Decimal | None
    distance_to_ma10_pct: Decimal | None
    distance_to_ma20_pct: Decimal | None


def fixed_proxy_symbols(registry: Sequence[SecurityProxyDefinition] | None = None) -> tuple[str, ...]:
    """Use only enabled instruments in the versioned fixed proxy registry."""

    entries = registry or load_security_proxy_registry()
    return tuple(dict.fromkeys(
        item.symbol
        for path in entries
        for item in path.instruments
        if item.enabled
    ))


def _shanghai(value: datetime) -> datetime | None:
    if value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(SHANGHAI)


def _finite_decimal(value: object, *, positive: bool = False, non_negative: bool = False) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        decimal = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not decimal.is_finite() or (positive and decimal <= 0) or (non_negative and decimal < 0):
        return None
    return decimal


def _capture_window(target_trading_date: date, now: datetime) -> datetime:
    evaluation = evaluate_cn_a_day(target_trading_date)
    if evaluation.status == CalendarStatus.UNAVAILABLE:
        raise SecurityProxyDailyCaptureError("calendar_unavailable")
    if evaluation.status == CalendarStatus.OUT_OF_RANGE:
        raise SecurityProxyDailyCaptureError("calendar_out_of_range")
    if evaluation.status != CalendarStatus.TRADING_DAY:
        raise SecurityProxyDailyCaptureError("non_trading_day")
    local = _shanghai(now)
    if local is None:
        raise SecurityProxyDailyCaptureError("naive_capture_time")
    if local.date() != target_trading_date or local.time().replace(tzinfo=None) < CAPTURE_AFTER:
        raise SecurityProxyDailyCaptureError("market_not_closed")
    return local


def _existing_symbols(session: Session, symbols: Iterable[str], day: date) -> set[str]:
    requested = tuple(symbols)
    if not requested:
        return set()
    return set(session.scalars(select(SecurityProxyDaily.symbol).where(
        SecurityProxyDaily.symbol.in_(requested), SecurityProxyDaily.trading_date == day,
    )))


def _daily_row(quote: object, *, target_trading_date: date, fetched_at: datetime) -> tuple[dict[str, object] | None, str | None]:
    symbol = str(getattr(quote, "requested_symbol", ""))
    close = _finite_decimal(getattr(quote, "current", None), positive=True)
    if close is None:
        return None, "invalid_close"
    quote_datetime = getattr(quote, "quote_datetime", None)
    if not isinstance(quote_datetime, datetime):
        return None, "quote_missing"
    quote_local = _shanghai(quote_datetime)
    if quote_local is None:
        return None, "naive_quote_datetime"
    if quote_local.date() != target_trading_date:
        return None, "quote_date_mismatch"
    open_ = _finite_decimal(getattr(quote, "open", None), positive=True)
    high = _finite_decimal(getattr(quote, "high", None), positive=True)
    low = _finite_decimal(getattr(quote, "low", None), positive=True)
    if open_ is not None and high is not None and low is not None and not (low <= open_ <= high and low <= close <= high):
        open_ = high = low = None
    return {
        "symbol": symbol,
        "trading_date": target_trading_date,
        "close": close,
        "open": open_,
        "high": high,
        "low": low,
        "amount_yuan": _finite_decimal(getattr(quote, "amount_yuan", None), non_negative=True),
        "quote_datetime": quote_local,
        "fetched_at": fetched_at,
        "source": SOURCE,
    }, None


def capture_fixed_security_proxy_daily(
    session: Session,
    *,
    target_trading_date: date,
    provider: TencentStandardSecurityQuoteProvider,
    now: Callable[[], datetime],
    registry: Sequence[SecurityProxyDefinition] | None = None,
    enable_provider: bool = False,
) -> SecurityProxyDailyCaptureSummary:
    """Explicitly capture one post-close daily row per fixed proxy security."""

    if not enable_provider:
        raise PermissionError("explicit provider enablement is required")
    fetched_at = _capture_window(target_trading_date, now())
    symbols = fixed_proxy_symbols(registry)
    existing = _existing_symbols(session, symbols, target_trading_date)
    requested = tuple(symbol for symbol in symbols if symbol not in existing)
    failures: dict[str, str] = {}
    inserted = invalid = batches = 0
    for offset in range(0, len(requested), provider.max_batch_size):
        batch = provider.fetch_batch(requested[offset:offset + provider.max_batch_size], allow_network=True)
        batches += batch.request_count
        failures.update({symbol: error.value for symbol, error in batch.failures.items()})
        for quote in batch.quotes:
            row, error = _daily_row(quote, target_trading_date=target_trading_date, fetched_at=fetched_at)
            if error:
                failures[quote.requested_symbol] = error
                invalid += 1
                continue
            assert row is not None
            session.add(SecurityProxyDaily(**row))
            inserted += 1
    session.commit()
    return SecurityProxyDailyCaptureSummary(
        target_trading_date, len(symbols), len(requested), inserted, len(symbols) - len(requested),
        len(failures), batches, failures,
    )


def get_security_proxy_daily_history(session: Session, symbol: str, *, limit: int = 20) -> tuple[SecurityProxyDaily, ...]:
    if limit < 1 or limit > 20:
        raise ValueError("limit must be between 1 and 20")
    rows = tuple(session.scalars(select(SecurityProxyDaily).where(
        SecurityProxyDaily.symbol == symbol,
    ).order_by(SecurityProxyDaily.trading_date.desc()).limit(limit)))
    return tuple(reversed(rows))


def get_security_proxy_daily_histories(
    session: Session,
    symbols: Iterable[str],
    *,
    limit: int = 20,
) -> dict[str, tuple[SecurityProxyDaily, ...]]:
    """Read recent completed closes for several fixed symbols in one query."""

    if limit < 1 or limit > 20:
        raise ValueError("limit must be between 1 and 20")
    requested = tuple(dict.fromkeys(symbols))
    if not requested:
        return {}
    rows = session.scalars(select(SecurityProxyDaily).where(
        SecurityProxyDaily.symbol.in_(requested),
    ).order_by(SecurityProxyDaily.symbol, SecurityProxyDaily.trading_date.desc()))
    grouped: dict[str, list[SecurityProxyDaily]] = {symbol: [] for symbol in requested}
    for row in rows:
        if len(grouped[row.symbol]) < limit:
            grouped[row.symbol].append(row)
    return {symbol: tuple(reversed(items)) for symbol, items in grouped.items()}


def build_security_proxy_trend_metrics(history: Iterable[object], current_price: object) -> SecurityProxyTrendMetrics:
    """Build MA data from completed daily closes; never use current in an MA."""

    by_day: dict[date, Decimal] = {}
    for row in history:
        day = getattr(row, "trading_date", None)
        close = _finite_decimal(getattr(row, "close", None), positive=True)
        if not isinstance(day, date) or close is None:
            continue
        if day in by_day:
            raise ValueError("duplicate_security_proxy_daily_date")
        by_day[day] = close
    ordered_days = tuple(sorted(by_day))
    closes = tuple(by_day[day] for day in ordered_days)
    ma5, ma10, ma20 = (moving_average(closes, window) for window in (5, 10, 20))
    current = _finite_decimal(current_price, positive=True)
    first_recent_index = max(0, len(ordered_days) - 10)
    recent_closes = tuple(
        SecurityProxyRecentClose(
            trading_date=day,
            close=by_day[day],
            change_pct_from_previous_close=(by_day[day] / by_day[ordered_days[index - 1]] - Decimal("1")) * Decimal("100") if index else None,
        )
        for index, day in enumerate(ordered_days[first_recent_index:], start=first_recent_index)
    )
    return SecurityProxyTrendMetrics(
        recent_closes, ma5, ma10, ma20,
        distance_from_average(current, ma5) if current is not None else None,
        distance_from_average(current, ma10) if current is not None else None,
        distance_from_average(current, ma20) if current is not None else None,
    )
