from __future__ import annotations

import threading
from datetime import date, datetime, time, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, sessionmaker

from leopard_project.config import load_seed_bundle
from leopard_project.providers import ThsPublicValidationProvider

from .intraday import controlled_trading_dates
from .market_ingestion import refresh_real_market
from .models import MarketRefreshItem, MarketRefreshRun, SectorDailyBar


SHANGHAI = ZoneInfo("Asia/Shanghai")


def expected_latest_complete_trade_date(
    now: datetime,
    trading_dates: set[date] | None = None,
    safe_after: time = time(15, 30),
) -> date | None:
    controlled = trading_dates if trading_dates is not None else controlled_trading_dates()
    local = now.astimezone(SHANGHAI)
    eligible = [day for day in controlled if day < local.date() or (day == local.date() and local.time().replace(tzinfo=None) >= safe_after)]
    return max(eligible) if eligible else None


class EodBackfillCoordinator:
    """Single-process, gap-only EOD backfill with an observable status."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        now: Callable[[], datetime] | None = None,
        provider_factory: Callable[[], ThsPublicValidationProvider] | None = None,
    ) -> None:
        self.sessions = sessions
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._provider_factory = provider_factory or (lambda: ThsPublicValidationProvider(minimum_interval=0.45))
        self._lock = threading.Lock()
        self._running = False
        self._last_error: str | None = None

    def _missing(self, session: Session, expected: date | None) -> tuple[list[str], list[str]]:
        if expected is None:
            return [], []
        trading = sorted(day for day in controlled_trading_dates() if day <= expected)
        missing_by_sector: dict[str, list[date]] = {}
        for sector in load_seed_bundle().sectors:
            if sector.sector_key == "hang_seng_tech":
                continue
            existing = set(session.scalars(select(SectorDailyBar.trade_date).where(
                SectorDailyBar.sector_key == sector.sector_key,
                SectorDailyBar.eod_status == "complete_eod",
            )))
            # Backfill only the maintained history window.  An empty database
            # starts at the single expected date; once history exists, an
            # interior gap after its first stored date is never hidden merely
            # because a later date succeeded.
            first = min(existing) if existing else expected
            missing = [day for day in trading if first <= day <= expected and day not in existing]
            if missing:
                missing_by_sector[sector.sector_key] = missing
        return sorted(missing_by_sector), sorted({day.isoformat() for values in missing_by_sector.values() for day in values})

    def status(self) -> dict:
        expected = expected_latest_complete_trade_date(self._now())
        with self.sessions() as session:
            latest = session.scalar(select(func.max(SectorDailyBar.trade_date)).where(SectorDailyBar.eod_status == "complete_eod"))
            missing_sectors, missing_dates = self._missing(session, expected)
            latest_run = session.scalar(select(MarketRefreshRun).where(
                MarketRefreshRun.mode.in_(("automatic_eod_backfill", "manual_real_refresh")),
            ).order_by(desc(MarketRefreshRun.started_at)))
            failed_provider = None
            if latest_run and latest_run.failure_count:
                failed_provider = "ths_public_validation"
            retry_at = latest_run.started_at if latest_run else None
            if retry_at is not None:
                aware = retry_at if retry_at.tzinfo else retry_at.replace(tzinfo=timezone.utc)
                retry_display = aware.astimezone(SHANGHAI).strftime("%m/%d %H:%M")
            else:
                retry_display = None
            return {
                "expected_latest_complete_trade_date": expected.isoformat() if expected else None,
                "latest_complete_trade_date": latest.isoformat() if latest else None,
                "missing_dates": missing_dates,
                "missing_sector_count": len(missing_sectors),
                "failed_provider": failed_provider,
                "last_retry_at": retry_display,
                "last_retry_at_iso": retry_at.isoformat() if retry_at else None,
                "backfill_running": self._running,
                "last_error": self._last_error,
                "automatic_backfill": True,
            }

    def run_if_needed(self, actor: str = "automatic_eod_backfill") -> dict:
        if not self._lock.acquire(blocking=False):
            return {"status": "backfill_already_running"}
        self._running = True
        try:
            expected = expected_latest_complete_trade_date(self._now())
            with self.sessions() as session:
                sector_keys, missing_dates = self._missing(session, expected)
                if expected is None or not sector_keys:
                    return {"status": "up_to_date", "expected_trade_date": expected.isoformat() if expected else None, "missing_dates": []}
                run = refresh_real_market(
                    session, actor, sector_keys=sector_keys, as_of=expected,
                    provider=self._provider_factory(), mode="automatic_eod_backfill",
                    allowed_trade_dates={date.fromisoformat(value) for value in missing_dates},
                )
                return {
                    "status": run.status, "run_id": run.id,
                    "expected_trade_date": expected.isoformat(), "missing_dates": missing_dates,
                    "requested_count": run.requested_count, "success_count": run.success_count,
                    "failure_count": run.failure_count,
                }
        except Exception as exc:
            self._last_error = type(exc).__name__
            return {"status": "backfill_failed", "error": self._last_error}
        finally:
            self._running = False
            self._lock.release()

    def run_async_if_needed(self) -> None:
        thread = threading.Thread(target=self.run_if_needed, name="leopard-eod-gap-backfill", daemon=True)
        thread.start()
