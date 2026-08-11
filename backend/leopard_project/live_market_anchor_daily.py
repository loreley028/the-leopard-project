"""Explicit post-close daily capture and read model for the Shanghai market anchor.

The report itself remains the sole source of each defense line.  This module
only records a completed ``sh000001`` quote after close, then compares that
actual next controlled CN-A trading-day close with a prior published report's
explicit defense line.  It has no scheduler, startup hook, or report write.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Callable
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .providers.tencent_standard_quote import TencentStandardSecurityQuoteProvider
from .trading_calendar import CalendarStatus, evaluate_cn_a_day
from .web.live_market_anchor import SHANGHAI_COMPOSITE_NAME, SHANGHAI_COMPOSITE_SYMBOL, structure_leopard_defense_line
from .web.models import LiveMarketAnchorDaily, Report, ReportStatus


SHANGHAI = ZoneInfo("Asia/Shanghai")
CAPTURE_AFTER = time(15, 10)
SOURCE = TencentStandardSecurityQuoteProvider.provider_key


class LiveMarketAnchorDailyCaptureError(ValueError):
    """Fail closed before a post-close Provider request."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class LiveMarketAnchorDailyCaptureSummary:
    target_trading_date: date
    requested_count: int
    inserted_count: int
    already_exists_count: int
    invalid_count: int
    provider_request_count: int
    error_code: str | None


def _shanghai(value: datetime) -> datetime | None:
    if value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(SHANGHAI)


def _decimal(value: object, *, positive: bool = False) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not result.is_finite() or (positive and result <= 0):
        return None
    return result


def _capture_window(target_trading_date: date, now: datetime) -> datetime:
    evaluation = evaluate_cn_a_day(target_trading_date)
    if evaluation.status == CalendarStatus.UNAVAILABLE:
        raise LiveMarketAnchorDailyCaptureError("calendar_unavailable")
    if evaluation.status == CalendarStatus.OUT_OF_RANGE:
        raise LiveMarketAnchorDailyCaptureError("calendar_out_of_range")
    if evaluation.status != CalendarStatus.TRADING_DAY:
        raise LiveMarketAnchorDailyCaptureError("non_trading_day")
    local = _shanghai(now)
    if local is None:
        raise LiveMarketAnchorDailyCaptureError("naive_capture_time")
    if local.date() != target_trading_date or local.time().replace(tzinfo=None) < CAPTURE_AFTER:
        raise LiveMarketAnchorDailyCaptureError("market_not_closed")
    return local


def _record_from_quote(quote: object, *, target_trading_date: date, fetched_at: datetime) -> tuple[dict[str, object] | None, str | None]:
    if getattr(quote, "requested_symbol", None) != SHANGHAI_COMPOSITE_SYMBOL:
        return None, "symbol_mismatch"
    close = _decimal(getattr(quote, "current", None), positive=True)
    pre_close = _decimal(getattr(quote, "pre_close", None), positive=True)
    pct_change = _decimal(getattr(quote, "pct_change", None))
    quote_datetime = getattr(quote, "quote_datetime", None)
    if close is None or pre_close is None or pct_change is None:
        return None, "invalid_quote_fields"
    if not isinstance(quote_datetime, datetime):
        return None, "quote_missing"
    local_quote = _shanghai(quote_datetime)
    if local_quote is None:
        return None, "naive_quote_datetime"
    if local_quote.date() != target_trading_date:
        return None, "quote_date_mismatch"
    high, low = _decimal(getattr(quote, "high", None), positive=True), _decimal(getattr(quote, "low", None), positive=True)
    if high is not None and low is not None and not (low <= close <= high):
        high = low = None
    return {
        "symbol": SHANGHAI_COMPOSITE_SYMBOL,
        "trading_date": target_trading_date,
        "close": close,
        "pre_close": pre_close,
        "pct_change": pct_change,
        "high": high,
        "low": low,
        "quote_datetime": local_quote,
        "fetched_at": fetched_at,
        "source": SOURCE,
    }, None


def capture_live_market_anchor_daily(
    session: Session,
    *,
    target_trading_date: date,
    provider: TencentStandardSecurityQuoteProvider,
    now: Callable[[], datetime],
    enable_provider: bool = False,
) -> LiveMarketAnchorDailyCaptureSummary:
    """Capture exactly one completed Shanghai Composite quote when explicitly run."""

    if not enable_provider:
        raise PermissionError("explicit provider enablement is required")
    fetched_at = _capture_window(target_trading_date, now())
    existing = session.scalar(select(LiveMarketAnchorDaily).where(
        LiveMarketAnchorDaily.symbol == SHANGHAI_COMPOSITE_SYMBOL,
        LiveMarketAnchorDaily.trading_date == target_trading_date,
    ))
    if existing is not None:
        return LiveMarketAnchorDailyCaptureSummary(target_trading_date, 0, 0, 1, 0, 0, None)
    batch = provider.fetch_batch((SHANGHAI_COMPOSITE_SYMBOL,), allow_network=True)
    if not batch.quotes:
        failure = batch.failures.get(SHANGHAI_COMPOSITE_SYMBOL)
        return LiveMarketAnchorDailyCaptureSummary(
            target_trading_date, 1, 0, 0, 1, batch.request_count,
            failure.value if failure is not None else "provider_unavailable",
        )
    row, error = _record_from_quote(batch.quotes[0], target_trading_date=target_trading_date, fetched_at=fetched_at)
    if error is not None:
        return LiveMarketAnchorDailyCaptureSummary(target_trading_date, 1, 0, 0, 1, batch.request_count, error)
    assert row is not None
    session.add(LiveMarketAnchorDaily(**row))
    session.commit()
    return LiveMarketAnchorDailyCaptureSummary(target_trading_date, 1, 1, 0, 0, batch.request_count, None)


def next_controlled_cn_a_trading_day(report_date: date) -> date | None:
    """Return the next calendar-confirmed CN-A trading day after a report date."""

    candidate = report_date + timedelta(days=1)
    for _ in range(370):
        evaluation = evaluate_cn_a_day(candidate)
        if evaluation.status == CalendarStatus.TRADING_DAY:
            return candidate
        if evaluation.status in {CalendarStatus.UNAVAILABLE, CalendarStatus.OUT_OF_RANGE}:
            return None
        candidate += timedelta(days=1)
    return None


def recent_defense_line_validations(session: Session, *, limit: int = 10) -> list[dict[str, object]]:
    """Return actual next-trading-day closes for prior explicit report lines.

    Multiple non-trading-day reports can target the same controlled day.  The
    newest current published report wins for that day, so one actual close is
    never represented as competing validation rows.
    """

    if limit < 1 or limit > 10:
        raise ValueError("limit must be between 1 and 10")
    reports = session.scalars(select(Report).where(
        Report.status == ReportStatus.PUBLISHED.value,
        Report.is_current.is_(True),
        Report.report_date.is_not(None),
    ).order_by(Report.report_date.desc(), Report.published_at.desc())).all()
    closes = {
        item.trading_date: item
        for item in session.scalars(select(LiveMarketAnchorDaily).where(
            LiveMarketAnchorDaily.symbol == SHANGHAI_COMPOSITE_SYMBOL,
        ))
    }
    result: list[dict[str, object]] = []
    seen_trade_days: set[date] = set()
    for report in reports:
        assert report.report_date is not None
        defense = structure_leopard_defense_line(report.market_path, report.core_view)
        if defense.value is None:
            continue
        trading_date = next_controlled_cn_a_trading_day(report.report_date)
        if trading_date is None or trading_date in seen_trade_days:
            continue
        close = closes.get(trading_date)
        if close is None:
            continue
        seen_trade_days.add(trading_date)
        close_value = Decimal(str(close.close))
        distance = close_value - defense.value
        result.append({
            "trading_date": trading_date.isoformat(),
            "source_report_id": report.id,
            "source_report_date": report.report_date.isoformat(),
            "defense_line_value": float(defense.value),
            "index_name": SHANGHAI_COMPOSITE_NAME,
            "index_close": float(close_value),
            "distance_points": float(distance),
            "distance_pct": float((close_value / defense.value - Decimal("1")) * Decimal("100")),
            "close_position": "close_above_defense_line" if distance > 0 else "close_below_defense_line" if distance < 0 else "close_at_defense_line",
        })
    return sorted(result, key=lambda item: str(item["trading_date"]), reverse=True)[:limit]
