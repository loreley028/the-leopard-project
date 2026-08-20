"""Independent, host-scheduled Market Core completed-history advancement."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .broad_market_anchors import load_broad_market_anchors
from .historical_market_daily import (
    SHANGHAI_COMPOSITE_SYMBOL,
    expected_latest_completed_trading_day,
    refresh_market_history_to_latest_completed,
)
from .live_market_anchor_daily import capture_live_market_anchor_daily
from .providers.sina_public_daily import SinaPublicDailyMarketProvider
from .providers.tencent_standard_quote import TencentStandardSecurityQuoteProvider
from .security_proxy_daily import capture_fixed_security_proxy_daily, market_core_security_symbols
from .trading_calendar import CalendarStatus, evaluate_cn_a_day
from .web.models import LiveMarketAnchorDaily, MarketDailyAdvanceRun, SecurityProxyDaily


SHANGHAI = ZoneInfo("Asia/Shanghai")
COMPLETE_AFTER = time(15, 10)
AdvanceMode = Literal["advance", "reconcile"]


@dataclass(frozen=True)
class MarketCoverage:
    expected_trading_date: date
    total_symbols: int
    ready_symbols: int
    missing_symbols: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.missing_symbols


@dataclass(frozen=True)
class DailyMarketAdvanceSummary:
    mode: AdvanceMode
    expected_trading_date: date
    primary_capture_attempted: bool
    tencent_inserted: int
    historical_inserted: int
    skip_existing_same: int
    conflicts: int
    provider_failures: dict[str, str]
    coverage: MarketCoverage
    run_id: str

    @property
    def complete(self) -> bool:
        return self.coverage.complete and self.conflicts == 0


def market_core_symbols() -> tuple[str, ...]:
    return (SHANGHAI_COMPOSITE_SYMBOL, *market_core_security_symbols())


def _local(value: datetime) -> datetime:
    return value.astimezone(SHANGHAI) if value.tzinfo is not None else value.replace(tzinfo=SHANGHAI)


def market_coverage(session: Session, *, expected: date) -> MarketCoverage:
    symbols = market_core_symbols()
    security_symbols = tuple(symbol for symbol in symbols if symbol != SHANGHAI_COMPOSITE_SYMBOL)
    present_security = set(session.scalars(select(SecurityProxyDaily.symbol).where(
        SecurityProxyDaily.trading_date == expected,
        SecurityProxyDaily.symbol.in_(security_symbols),
    )))
    anchor_present = session.scalar(select(LiveMarketAnchorDaily.id).where(
        LiveMarketAnchorDaily.symbol == SHANGHAI_COMPOSITE_SYMBOL,
        LiveMarketAnchorDaily.trading_date == expected,
    )) is not None
    missing = tuple(symbol for symbol in symbols if (
        not anchor_present if symbol == SHANGHAI_COMPOSITE_SYMBOL else symbol not in present_security
    ))
    return MarketCoverage(expected, len(symbols), len(symbols) - len(missing), missing)


def next_market_advance_schedule(now: datetime) -> dict[str, str] | None:
    """Return the next controlled-calendar host schedule without writing state."""

    local = _local(now)
    slots = ((time(9, 10), "reconcile"), (time(15, 20), "advance"), (time(15, 40), "reconcile"))
    for offset in range(370):
        candidate_day = local.date() + timedelta(days=offset)
        if evaluate_cn_a_day(candidate_day).status != CalendarStatus.TRADING_DAY:
            continue
        for clock, mode in slots:
            candidate = datetime.combine(candidate_day, clock, SHANGHAI)
            if candidate > local:
                return {"at": candidate.isoformat(), "mode": mode}
    return None


def market_freshness_status(session: Session, *, now: datetime) -> dict[str, object]:
    expected = expected_latest_completed_trading_day(now)
    coverage = market_coverage(session, expected=expected)
    broad_symbols = tuple(item.symbol for item in load_broad_market_anchors())
    broad_ready = len(set(broad_symbols) - set(coverage.missing_symbols))
    latest_advance = session.scalar(select(MarketDailyAdvanceRun).where(
        MarketDailyAdvanceRun.mode == "advance",
    ).order_by(MarketDailyAdvanceRun.finished_at.desc(), MarketDailyAdvanceRun.started_at.desc()))
    latest_reconcile = session.scalar(select(MarketDailyAdvanceRun).where(
        MarketDailyAdvanceRun.mode == "reconcile",
    ).order_by(MarketDailyAdvanceRun.finished_at.desc(), MarketDailyAdvanceRun.started_at.desc()))
    return {
        "expected_latest_completed": expected.isoformat(),
        "shanghai": "fresh" if SHANGHAI_COMPOSITE_SYMBOL not in coverage.missing_symbols else "stale_history",
        "broad": {"through_expected": broad_ready, "required": len(broad_symbols)},
        "market_core": {
            "through_expected": coverage.ready_symbols,
            "required": coverage.total_symbols,
            "missing_symbols": list(coverage.missing_symbols),
        },
        "last_daily_advance": latest_advance.finished_at.isoformat() if latest_advance and latest_advance.finished_at else None,
        "last_reconciliation": latest_reconcile.finished_at.isoformat() if latest_reconcile and latest_reconcile.finished_at else None,
        "next_scheduled": next_market_advance_schedule(now),
    }


def advance_market_core(
    session: Session,
    *,
    mode: AdvanceMode,
    now: datetime,
    tencent_provider: TencentStandardSecurityQuoteProvider | object | None = None,
    sina_provider: SinaPublicDailyMarketProvider | object | None = None,
    enable_tencent_provider: bool = False,
    enable_sina_provider: bool = False,
) -> DailyMarketAdvanceSummary:
    """Advance only the expected completed date; Reader requests never call this."""

    local = _local(now)
    expected = expected_latest_completed_trading_day(local)
    run = MarketDailyAdvanceRun(mode=mode, expected_trading_date=expected, total_symbols=len(market_core_symbols()))
    session.add(run)
    session.commit()
    primary_attempted = False
    tencent_inserted = historical_inserted = skipped = conflicts = 0
    failures: dict[str, str] = {}

    if mode == "advance" and expected == local.date() and local.time().replace(tzinfo=None) >= COMPLETE_AFTER:
        primary_attempted = True
        if not enable_tencent_provider:
            failures["tencent"] = "provider_not_enabled"
        else:
            provider = tencent_provider or TencentStandardSecurityQuoteProvider()
            try:
                anchor = capture_live_market_anchor_daily(
                    session, target_trading_date=expected, provider=provider, now=lambda: local, enable_provider=True,
                )
                tencent_inserted += anchor.inserted_count
                if anchor.error_code:
                    failures[SHANGHAI_COMPOSITE_SYMBOL] = anchor.error_code
                proxies = capture_fixed_security_proxy_daily(
                    session, target_trading_date=expected, provider=provider, now=lambda: local, enable_provider=True,
                )
                tencent_inserted += proxies.inserted_count
                failures.update(proxies.failures)
            except Exception as exc:  # The reconciliation remains fail-closed and records the real class.
                failures["tencent"] = str(getattr(exc, "code", type(exc).__name__))

    before_repair = market_coverage(session, expected=expected)
    if before_repair.missing_symbols:
        if not enable_sina_provider:
            failures.setdefault("sina", "provider_not_enabled")
        else:
            repair = refresh_market_history_to_latest_completed(
                session,
                provider=sina_provider or SinaPublicDailyMarketProvider(),
                enable_provider=True,
                now=local,
                symbols=before_repair.missing_symbols,
                stop_on_rate_limit=True,
            )
            historical_inserted += repair.inserted
            skipped += repair.skip_existing_same
            conflicts += repair.conflicts
            failures.update(repair.provider_failures)

    coverage = market_coverage(session, expected=expected)
    run.ready_symbols = coverage.ready_symbols
    run.missing_symbols = len(coverage.missing_symbols)
    run.conflicts = conflicts
    run.status = "success" if coverage.complete and conflicts == 0 else "incomplete"
    run.finished_at = local
    run.detail_json = json.dumps({
        "primary_capture_attempted": primary_attempted,
        "tencent_inserted": tencent_inserted,
        "historical_inserted": historical_inserted,
        "skip_existing_same": skipped,
        "conflicts": conflicts,
        "provider_failures": failures,
        "missing_symbols": coverage.missing_symbols,
    }, ensure_ascii=False, sort_keys=True)
    session.commit()
    return DailyMarketAdvanceSummary(
        mode, expected, primary_attempted, tencent_inserted, historical_inserted, skipped,
        conflicts, failures, coverage, run.id,
    )
