from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import date, datetime, time as clock_time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, sessionmaker

from leopard_project.config import CONFIG_DIR, load_seed_bundle
from leopard_project.models import DailyBar, Market
from leopard_project.providers import EastmoneyBoardSpotProvider

from .models import (
    IntradayRefreshSession,
    MarketRefreshItem,
    MarketRefreshRun,
    SectorIntradaySnapshot,
)


POLICY_PATH = CONFIG_DIR / "intraday_market_policy_v1.json"
CALENDAR_PATH = CONFIG_DIR / "enhanced_demo_calendar_v1.json"


def intraday_policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def controlled_trading_dates() -> set[date]:
    document = json.loads(CALENDAR_PATH.read_text(encoding="utf-8"))
    return {date.fromisoformat(value) for value in document["trading_dates"]}


def _parse_time(value: str) -> clock_time:
    hour, minute = (int(part) for part in value.split(":"))
    return clock_time(hour, minute)


def market_phase(now: datetime, policy: dict | None = None, trading_dates: set[date] | None = None) -> str:
    policy = policy or intraday_policy()
    timezone_name = policy["timezone"]
    local = now.astimezone(ZoneInfo(timezone_name))
    controlled = trading_dates if trading_dates is not None else controlled_trading_dates()
    if local.date() not in controlled:
        return "market_closed"
    current = local.time().replace(tzinfo=None)
    morning = policy["morning_session"]
    afternoon = policy["afternoon_session"]
    market_break = policy["market_break"]
    if _parse_time(morning["start"]) <= current < _parse_time(morning["end"]):
        return "intraday_open"
    if _parse_time(market_break["start"]) <= current < _parse_time(market_break["end"]):
        return "market_break"
    if _parse_time(afternoon["start"]) <= current < _parse_time(afternoon["end"]):
        return "intraday_open"
    return "market_closed"


def market_phase_detail(now: datetime, policy: dict | None = None, trading_dates: set[date] | None = None) -> str:
    policy = policy or intraday_policy()
    local = now.astimezone(ZoneInfo(policy["timezone"]))
    controlled = trading_dates if trading_dates is not None else controlled_trading_dates()
    if local.date() not in controlled:
        return "non_trading_day"
    current = local.time().replace(tzinfo=None)
    if current < _parse_time(policy["morning_session"]["start"]):
        return "before_open"
    if current >= _parse_time(policy["afternoon_session"]["end"]):
        return "after_close"
    return market_phase(now, policy, controlled)


def resolve_intraday_data_status(
    *, phase: str, snapshot: dict | None, latest_result: str | None,
    now: datetime, stale_after_minutes: int, unsupported: bool = False,
) -> str:
    """Single status contract shared by all Viewer/Admin payloads."""
    if unsupported:
        return "unsupported"
    if phase == "market_break":
        return "market_break"
    if phase == "market_closed":
        return "market_closed"
    if latest_result == "provider_failed":
        return "provider_failed"
    if snapshot is None:
        return "provider_failed"
    observed = datetime.fromisoformat(snapshot.get("observed_at_iso") or snapshot["observed_at"])
    age_minutes = (now - observed.astimezone(timezone.utc)).total_seconds() / 60
    return "intraday_stale" if age_minutes > stale_after_minutes else "intraday_fresh"


IntradayFetcher = Callable[[str, object, datetime], DailyBar]


class IntradayRefreshCoordinator:
    """One process-wide refresh loop with Admin pause/resume controls.

    The app may safely start a new process-local session from versioned policy;
    no timer state is restored from SQLite and overlapping cycles are rejected.
    """

    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        now: Callable[[], datetime] | None = None,
        fetcher: IntradayFetcher | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.sessions = sessions
        self.policy = intraday_policy()
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._uses_default_fetcher = fetcher is None
        self._fetcher = fetcher or self._provider_fetch
        self._provider = EastmoneyBoardSpotProvider()
        self._sleep = sleep
        self._enabled = False
        self._running_cycle = False
        self._session_id: str | None = None
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._last_runtime_error: str | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _provider_fetch(self, sector_key: str, mapping: object, observed_at: datetime) -> DailyBar:
        return self._provider.fetch_intraday_snapshot(mapping, observed_at)

    def start(self, actor: str) -> dict:
        with self._lock:
            if self._enabled:
                return self.status()
            self._enabled = True
            now = self._now()
            with self.sessions() as session:
                record = IntradayRefreshSession(
                    status="running",
                    refresh_interval_minutes=self.policy["refresh_interval_minutes"],
                    provider_role=self.policy["provider_role"],
                    started_by=actor,
                    started_at=now,
                    next_refresh_at=now,
                )
                session.add(record)
                session.commit()
                self._session_id = record.id
            self._schedule(0.05)
        return self.status()

    def pause(self) -> dict:
        with self._lock:
            self._enabled = False
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            if self._session_id:
                with self.sessions() as session:
                    record = session.get(IntradayRefreshSession, self._session_id)
                    if record:
                        record.status = "paused"
                        record.paused_at = self._now()
                        record.next_refresh_at = None
                        session.commit()
        return self.status()

    def shutdown(self) -> None:
        self.pause()

    def _schedule(self, seconds: float) -> None:
        if not self._enabled:
            return
        self._timer = threading.Timer(seconds, self._timer_cycle)
        self._timer.daemon = True
        self._timer.start()

    def _timer_cycle(self) -> None:
        started = self._now()
        try:
            result = self.refresh_once()
            if result.get("status") == "market_closed" and self.policy.get("stop_at_market_close"):
                self.pause()
            self._last_runtime_error = None
        except Exception as exc:
            # A transient local lock or Provider error must not kill the
            # process-wide timer. The next controlled interval retries.
            self._last_runtime_error = type(exc).__name__
        finally:
            if self._enabled:
                elapsed = max(0.0, (self._now() - started).total_seconds())
                interval = float(self.policy["refresh_interval_minutes"] * 60)
                self._schedule(max(0.05, interval - elapsed))

    def refresh_now(self) -> dict:
        return self.refresh_once()

    def refresh_once(self) -> dict:
        with self._lock:
            if self._running_cycle:
                return {"status": "cycle_already_running", "provider_requests": 0}
            self._running_cycle = True
        try:
            now = self._now()
            phase = market_phase(now, self.policy)
            if phase != "intraday_open":
                return {"status": phase, "provider_requests": 0, "trade_date": now.astimezone(ZoneInfo(self.policy["timezone"])).date().isoformat()}
            return self._execute_cycle(now)
        finally:
            with self._lock:
                self._running_cycle = False

    def _execute_cycle(self, now: datetime) -> dict:
        if self._uses_default_fetcher:
            self._provider.begin_cycle()
        bundle = load_seed_bundle()
        mappings = {item.sector_key: item for item in bundle.mappings}
        sectors = [item for item in bundle.sectors if item.sector_key != "hang_seng_tech"]
        # Provider I/O must happen before opening a SQLite write transaction.
        # Otherwise a slow public endpoint can block login/Admin writes for the
        # whole network timeout window even though Viewer reads use only cache.
        fetched: list[tuple[object, DailyBar | None, str | None]] = []
        for index, sector in enumerate(sectors):
            try:
                bar = self._fetcher(sector.sector_key, mappings[sector.sector_key], now)
                if bar.trade_date != now.astimezone(ZoneInfo(self.policy["timezone"])).date():
                    raise ValueError("stale_snapshot")
                fetched.append((sector, bar, None))
            except Exception as exc:  # one Provider failure must not abort the cycle
                fetched.append((sector, None, type(exc).__name__))
            if index < len(sectors) - 1 and self.policy["request_spacing_seconds"] > 0:
                self._sleep(float(self.policy["request_spacing_seconds"]))

        with self.sessions() as session:
            run = MarketRefreshRun(
                mode="intraday_refresh", provider_role=self.policy["provider_role"],
                requested_count=len(sectors), requested_by="intraday_session", status="running", started_at=now,
            )
            session.add(run)
            session.flush()
            for sector, bar, failure in fetched:
                if bar is not None:
                    session.add(SectorIntradaySnapshot(
                        sector_key=sector.sector_key,
                        trade_date=bar.trade_date,
                        observed_at=now,
                        index_value=bar.close,
                        pre_close=bar.pre_close,
                        pct_change=bar.pct_change,
                        volume=bar.volume,
                        amount=bar.amount,
                        provider=bar.provider,
                        provider_role=self.policy["provider_role"],
                        data_status="intraday_fresh",
                        response_hash=bar.source_payload_hash,
                        fetched_at=bar.fetched_at,
                        refresh_run_id=run.id,
                    ))
                    run.success_count += 1
                    run.intraday_count += 1
                    session.add(MarketRefreshItem(run_id=run.id, sector_key=sector.sector_key, status="intraday_fresh", trade_date=bar.trade_date, detail="server_cache"))
                else:
                    run.failure_count += 1
                    session.add(MarketRefreshItem(run_id=run.id, sector_key=sector.sector_key, status="provider_failed", detail=failure or "ProviderError"))
                session.flush()
            run.unsupported_count = 1
            run.status = "completed_with_failures" if run.failure_count else "completed"
            run.finished_at = self._now()
            cutoff = now.date() - timedelta(days=int(self.policy["retain_snapshot_days"]))
            for old in session.scalars(select(SectorIntradaySnapshot).where(SectorIntradaySnapshot.trade_date < cutoff)):
                session.delete(old)
            if self._session_id:
                record = session.get(IntradayRefreshSession, self._session_id)
                if record:
                    record.last_refresh_at = run.finished_at
                    record.next_refresh_at = now + timedelta(minutes=self.policy["refresh_interval_minutes"])
            session.commit()
            return {
                "run_id": run.id, "status": run.status,
                "provider_requests": self._provider.request_count if self._uses_default_fetcher else len(sectors),
                "success_count": run.success_count, "failure_count": run.failure_count,
                "stale_count": run.stale_count, "unsupported_count": run.unsupported_count,
            }

    def status(self) -> dict:
        now = self._now()
        local_trade_date = now.astimezone(ZoneInfo(self.policy["timezone"])).date().isoformat()
        with self.sessions() as session:
            record = session.get(IntradayRefreshSession, self._session_id) if self._session_id else None
            latest_run = session.scalar(select(MarketRefreshRun).where(MarketRefreshRun.mode == "intraday_refresh").order_by(desc(MarketRefreshRun.started_at)))
            latest_snapshot = session.scalar(select(SectorIntradaySnapshot).order_by(desc(SectorIntradaySnapshot.observed_at)))
            def display(value: datetime | None) -> str | None:
                if value is None:
                    return None
                aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
                return aware.astimezone(ZoneInfo(self.policy["timezone"])).strftime("%m/%d %H:%M")

            return {
                "session_status": "running" if self._enabled else "paused",
                "market_phase": market_phase(now, self.policy),
                "market_phase_detail": market_phase_detail(now, self.policy),
                "intraday_trade_date": local_trade_date,
                "refresh_interval_minutes": self.policy["refresh_interval_minutes"],
                "provider": self.policy["provider"],
                "provider_role": self.policy["provider_role"],
                "production_primary": None,
                "production_primary_approved": False,
                "research_notice": "研究辅助数据，非生产级行情服务。",
                "last_refresh_at": display(record.last_refresh_at) if record else None,
                "last_attempt_at": display(latest_run.started_at) if latest_run else None,
                "next_refresh_at": display(record.next_refresh_at) if record else None,
                "latest_snapshot_at": display(latest_snapshot.observed_at) if latest_snapshot else None,
                "last_refresh_at_iso": record.last_refresh_at.isoformat() if record and record.last_refresh_at else None,
                "last_attempt_at_iso": latest_run.started_at.isoformat() if latest_run else None,
                "next_refresh_at_iso": record.next_refresh_at.isoformat() if record and record.next_refresh_at else None,
                "latest_snapshot_at_iso": latest_snapshot.observed_at.isoformat() if latest_snapshot else None,
                "success_count": latest_run.success_count if latest_run else 0,
                "failure_count": latest_run.failure_count if latest_run else 0,
                "stale_count": latest_run.stale_count if latest_run else 0,
                "unsupported_count": 1,
                "viewer_provider_access": False,
                "auto_start": bool(self.policy["auto_start"]),
                "last_runtime_error": self._last_runtime_error,
            }
