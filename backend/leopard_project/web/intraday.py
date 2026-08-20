from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import date, datetime, time as clock_time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, sessionmaker

from leopard_project.config import CONFIG_DIR, load_seed_bundle
from leopard_project.market_paths import load_market_path_registry, market_path_mapping
from leopard_project.models import DailyBar, Market
from leopard_project.providers import ProviderError, ResearchIntradayProviderChain
from leopard_project.trading_calendar import CalendarStatus, evaluate_cn_a_day, load_calendar

from .models import (
    IntradayRefreshSession,
    MarketAutomationControl,
    MarketRefreshItem,
    MarketRefreshRun,
    SectorIntradaySnapshot,
    SectorProviderNativeClose,
)
from .write_coordination import BACKGROUND_WRITE_LOCK, coordinated_write


POLICY_PATH = CONFIG_DIR / "intraday_market_policy_v1.json"


def intraday_policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def controlled_trading_dates() -> set[date]:
    calendar = load_calendar()
    if calendar is None:
        raise ValueError("calendar_source_unavailable")
    return calendar.trading_dates()


def calendar_status(day: date, trading_dates: set[date] | None = None) -> CalendarStatus:
    if trading_dates is not None:
        return CalendarStatus.TRADING_DAY if day in trading_dates else CalendarStatus.CONFIRMED_NON_TRADING_DAY
    return evaluate_cn_a_day(day).status


def _parse_time(value: str) -> clock_time:
    hour, minute = (int(part) for part in value.split(":"))
    return clock_time(hour, minute)


def market_phase(now: datetime, policy: dict | None = None, trading_dates: set[date] | None = None) -> str:
    policy = policy or intraday_policy()
    timezone_name = policy["timezone"]
    local = now.astimezone(ZoneInfo(timezone_name))
    status = calendar_status(local.date(), trading_dates)
    if status in {CalendarStatus.OUT_OF_RANGE, CalendarStatus.UNAVAILABLE}:
        return "calendar_error"
    if status == CalendarStatus.CONFIRMED_NON_TRADING_DAY:
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
    evaluation = evaluate_cn_a_day(local.date()) if trading_dates is None else None
    status = evaluation.status if evaluation is not None else calendar_status(local.date(), trading_dates)
    if status == CalendarStatus.OUT_OF_RANGE:
        return "calendar_out_of_range"
    if status == CalendarStatus.UNAVAILABLE:
        return evaluation.reason or "calendar_source_unavailable"
    if status == CalendarStatus.CONFIRMED_NON_TRADING_DAY:
        return "non_trading_day"
    current = local.time().replace(tzinfo=None)
    if current < _parse_time(policy["morning_session"]["start"]):
        return "before_open"
    if current >= _parse_time(policy["afternoon_session"]["end"]):
        return "after_close"
    return market_phase(now, policy, trading_dates)


def market_session(now: datetime, policy: dict | None = None, trading_dates: set[date] | None = None) -> str:
    """Expose the user-facing five-state session contract without weakening fail-closed checks."""
    phase = market_phase(now, policy, trading_dates)
    detail = market_phase_detail(now, policy, trading_dates)
    if detail in {"calendar_out_of_range", "calendar_source_unavailable", "calendar_rule_invalid"}:
        return "calendar_error"
    if detail == "non_trading_day":
        return "non_trading_day"
    if detail == "before_open":
        return "pre_open"
    if phase == "intraday_open":
        return "open"
    if phase == "market_break":
        return "market_break"
    return "closed"


def resolve_intraday_data_status(
    *, phase: str, snapshot: dict | None, latest_result: str | None,
    now: datetime, stale_after_minutes: int, unsupported: bool = False,
) -> str:
    """Single status contract shared by all Viewer/Admin payloads."""
    if unsupported:
        return "unsupported"
    if phase == "calendar_error":
        return "calendar_error"
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


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def recover_stale_refresh_sessions(sessions: sessionmaker[Session], now: datetime) -> int:
    """Keep audit history while terminating leases that cannot belong to a live process."""
    def recover() -> int:
        recovered = 0
        with sessions() as session:
            rows = list(session.scalars(select(IntradayRefreshSession).where(IntradayRefreshSession.status == "running")))
            for row in rows:
                if row.lease_expires_at is None or _aware(row.lease_expires_at) <= now.astimezone(timezone.utc):
                    row.status = "interrupted"
                    row.finished_at = now
                    row.terminal_reason = "stale_lease_recovery" if row.lease_expires_at else "process_restart"
                    row.next_refresh_at = None
                    recovered += 1
            if recovered:
                session.commit()
        return recovered

    return coordinated_write(recover)


def calculate_intraday_ma5(current_value: Decimal, previous_complete_closes: list[Decimal]) -> tuple[Decimal, Decimal] | None:
    """Pure arithmetic helper; callers must validate Provider-native lineage first."""
    if len(previous_complete_closes) != 4 or any(value <= 0 for value in previous_complete_closes) or current_value <= 0:
        return None
    average = (current_value + sum(previous_complete_closes, Decimal("0"))) / Decimal("5")
    return average, (current_value / average - Decimal("1")) * Decimal("100")


def provider_native_history_status(bar: DailyBar) -> str:
    """Classify Provider-native history without consulting formal EOD data."""
    provider_symbol = bar.provider_symbol or bar.symbol
    history = tuple(sorted(bar.provider_native_history, key=lambda item: item.trade_date))
    if bar.provider_native_history_status != "complete" or len(history) != 4:
        return bar.provider_native_history_status if bar.provider_native_history_status != "complete" else "insufficient"
    if len({item.trade_date for item in history}) != 4 or any(item.trade_date >= bar.trade_date for item in history):
        return "invalid_dates"
    expected_days = sorted(day for day in controlled_trading_dates() if day < bar.trade_date)[-4:]
    if [item.trade_date for item in history] != expected_days:
        return "invalid_dates"
    if any(item.provider != bar.provider for item in history):
        return "provider_mismatch"
    if any(item.provider_symbol != provider_symbol for item in history):
        return "symbol_mismatch"
    latest_close = history[-1].close
    if latest_close <= 0 or abs(bar.pre_close / latest_close - Decimal("1")) > Decimal("0.005"):
        return "series_scale_mismatch"
    return "complete"


def calculate_provider_native_intraday_ma5(bar: DailyBar) -> tuple[Decimal, Decimal] | None:
    """Fail closed unless current and all four closes share Provider, symbol and scale."""
    if provider_native_history_status(bar) != "complete":
        return None
    history = tuple(sorted(bar.provider_native_history, key=lambda item: item.trade_date))
    return calculate_intraday_ma5(bar.close, [item.close for item in history])


def provider_failure_contract(exc: Exception) -> tuple[str, str]:
    """Return an Admin-safe failure without serializing arbitrary exception data."""
    if isinstance(exc, ProviderError):
        return exc.category.value, str(exc)
    if isinstance(exc, ValueError) and str(exc) in {"stale_snapshot", "inconsistent_pct_change"}:
        return str(exc), str(exc)
    if isinstance(exc, TimeoutError):
        return "timeout", "Provider request timed out"
    return "provider_error", "Provider request failed"


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
        self._provider = ResearchIntradayProviderChain(sessions=sessions)
        self._sleep = sleep
        self._enabled = False
        self._running_cycle = False
        self._session_id: str | None = None
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._last_runtime_error: str | None = None
        self._instance_id = uuid4().hex
        self._lease_seconds = max(600, int(self.policy["refresh_interval_minutes"]) * 120)
        self._recovered_sessions = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _provider_fetch(self, sector_key: str, mapping: object, observed_at: datetime) -> DailyBar:
        return self._provider.fetch_intraday_snapshot(mapping, observed_at)

    def start(self, actor: str) -> dict:
        with self._lock:
            if self._enabled:
                return self.status()
            now = self._now()
            self._recovered_sessions += recover_stale_refresh_sessions(self.sessions, now)
            with BACKGROUND_WRITE_LOCK, self.sessions() as session:
                control = session.get(MarketAutomationControl, "intraday")
                if control and control.admin_paused and actor == "system_auto_resume":
                    return self.status()
                active = session.scalar(select(IntradayRefreshSession).where(
                    IntradayRefreshSession.status == "running",
                    IntradayRefreshSession.lease_expires_at > now,
                ))
                if active and active.owner_instance_id != self._instance_id:
                    self._last_runtime_error = "duplicate_scheduler_prevented"
                    return {**self.status(), "start_result": "duplicate_scheduler_prevented"}
                if actor != "system_auto_resume":
                    if control is None:
                        control = MarketAutomationControl(control_key="intraday")
                        session.add(control)
                    control.admin_paused = False
                    control.changed_by = actor
                    control.changed_at = self._now()
                    session.commit()
            self._enabled = True
            with BACKGROUND_WRITE_LOCK, self.sessions() as session:
                record = IntradayRefreshSession(
                    status="running",
                    refresh_interval_minutes=self.policy["refresh_interval_minutes"],
                    provider_role=self.policy["provider_role"],
                    started_by=actor,
                    started_at=now,
                    next_refresh_at=now,
                    heartbeat_at=now,
                    lease_expires_at=now + timedelta(seconds=self._lease_seconds),
                    owner_instance_id=self._instance_id,
                )
                session.add(record)
                session.commit()
                self._session_id = record.id
            self._schedule(self._startup_delay_seconds(now))
        return self.status()

    def pause(self, actor: str | None = None, *, persistent: bool = False) -> dict:
        with self._lock:
            self._enabled = False
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            if self._session_id:
                with BACKGROUND_WRITE_LOCK, self.sessions() as session:
                    record = session.get(IntradayRefreshSession, self._session_id)
                    if record:
                        record.status = "cancelled"
                        record.paused_at = self._now()
                        record.finished_at = self._now()
                        record.terminal_reason = "admin_pause" if persistent else "process_shutdown"
                        record.next_refresh_at = None
                        session.commit()
            if persistent:
                with BACKGROUND_WRITE_LOCK, self.sessions() as session:
                    control = session.get(MarketAutomationControl, "intraday")
                    if control is None:
                        control = MarketAutomationControl(control_key="intraday")
                        session.add(control)
                    control.admin_paused = True
                    control.changed_by = actor
                    control.changed_at = self._now()
                    session.commit()
        return self.status()

    def shutdown(self) -> None:
        self.pause(persistent=False)

    def _startup_delay_seconds(self, now: datetime) -> float:
        """Refresh stale/missing open-market cache immediately; reuse a fresh complete run."""
        if market_phase(now, self.policy) != "intraday_open":
            return min(60.0, float(self.policy["refresh_interval_minutes"] * 60))
        with self.sessions() as session:
            latest_run = session.scalar(
                select(MarketRefreshRun)
                .where(MarketRefreshRun.mode == "intraday_refresh")
                .order_by(desc(MarketRefreshRun.started_at))
            )
            latest_snapshot = session.scalar(select(SectorIntradaySnapshot).order_by(desc(SectorIntradaySnapshot.observed_at)))
            expected = len(load_market_path_registry().supported_market_paths)
            if not latest_run or latest_run.success_count != expected or not latest_snapshot:
                return 0.05
            observed = latest_snapshot.observed_at
            observed = observed if observed.tzinfo else observed.replace(tzinfo=timezone.utc)
            local_now = now.astimezone(ZoneInfo(self.policy["timezone"]))
            if latest_snapshot.trade_date != local_now.date():
                return 0.05
            interval = float(self.policy["refresh_interval_minutes"] * 60)
            age = max(0.0, (now - observed.astimezone(timezone.utc)).total_seconds())
            return 0.05 if age >= interval else max(0.05, interval - age)

    def _schedule(self, seconds: float) -> None:
        if not self._enabled:
            return
        if self._session_id:
            with BACKGROUND_WRITE_LOCK, self.sessions() as session:
                record = session.get(IntradayRefreshSession, self._session_id)
                if record:
                    record.next_refresh_at = self._now() + timedelta(seconds=seconds)
                    record.heartbeat_at = self._now()
                    record.lease_expires_at = self._now() + timedelta(seconds=self._lease_seconds)
                    session.commit()
        self._timer = threading.Timer(seconds, self._timer_cycle)
        self._timer.daemon = True
        self._timer.start()

    def _timer_cycle(self) -> None:
        started = self._now()
        try:
            result = self.refresh_once()
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
                detail = market_phase_detail(now, self.policy)
                if detail in {"calendar_out_of_range", "calendar_source_unavailable", "calendar_rule_invalid"}:
                    self._last_runtime_error = detail
                    return {
                        "status": detail,
                        "error_code": detail,
                        "provider_requests": 0,
                        "trade_date": now.astimezone(ZoneInfo(self.policy["timezone"])).date().isoformat(),
                    }
                status = "pre_open" if detail == "before_open" else "non_trading_day" if detail == "non_trading_day" else phase
                return {"status": status, "provider_requests": 0, "trade_date": now.astimezone(ZoneInfo(self.policy["timezone"])).date().isoformat()}
            return self._execute_cycle(now)
        finally:
            with self._lock:
                self._running_cycle = False

    def _execute_cycle(self, now: datetime) -> dict:
        if self._uses_default_fetcher:
            self._provider.begin_cycle()
        bundle = load_seed_bundle()
        registry = load_market_path_registry(bundle)
        paths = list(registry.supported_market_paths)
        mappings = {item.market_path_key: market_path_mapping(item, bundle) for item in paths}
        # Provider I/O must happen before opening a SQLite write transaction.
        # Otherwise a slow public endpoint can block login/Admin writes for the
        # whole network timeout window even though Viewer reads use only cache.
        fetched: list[tuple[object, DailyBar | None, str | None, str | None]] = []
        for index, path in enumerate(paths):
            try:
                bar = self._fetcher(path.market_path_key, mappings[path.market_path_key], now)
                if bar.trade_date != now.astimezone(ZoneInfo(self.policy["timezone"])).date():
                    raise ValueError("stale_snapshot")
                expected_pct = (bar.close / bar.pre_close - Decimal("1")) * Decimal("100")
                if abs(expected_pct - bar.pct_change) > Decimal("0.06"):
                    raise ValueError("inconsistent_pct_change")
                fetched.append((path, bar, None, None))
            except Exception as exc:  # one Provider failure must not abort the cycle
                error_code, error_message = provider_failure_contract(exc)
                fetched.append((path, None, error_code, error_message))
            if index < len(paths) - 1 and self.policy["request_spacing_seconds"] > 0:
                self._sleep(float(self.policy["request_spacing_seconds"]))

        with BACKGROUND_WRITE_LOCK, self.sessions() as session:
            run = MarketRefreshRun(
                mode="intraday_refresh", provider_role=self.policy["provider_role"],
                requested_count=len(paths), requested_by="intraday_session", status="running", started_at=now,
            )
            session.add(run)
            session.flush()
            for path, bar, error_code, error_message in fetched:
                if bar is not None:
                    provider_symbol = bar.provider_symbol or bar.symbol
                    native_status = provider_native_history_status(bar)
                    intraday_ma = calculate_provider_native_intraday_ma5(bar)
                    for native in bar.provider_native_history if native_status == "complete" else ():
                        existing = session.scalar(select(SectorProviderNativeClose).where(
                            SectorProviderNativeClose.sector_key == path.market_path_key,
                            SectorProviderNativeClose.provider == native.provider,
                            SectorProviderNativeClose.provider_symbol == native.provider_symbol,
                            SectorProviderNativeClose.trade_date == native.trade_date,
                        ))
                        if existing is None:
                            session.add(SectorProviderNativeClose(
                                sector_key=path.market_path_key, provider=native.provider,
                                provider_symbol=native.provider_symbol, trade_date=native.trade_date,
                                close=native.close, source_response_hash=native.source_payload_hash,
                                lineage=native.lineage, fetched_at=bar.fetched_at,
                            ))
                    session.add(SectorIntradaySnapshot(
                        sector_key=path.market_path_key,
                        trade_date=bar.trade_date,
                        observed_at=now,
                        index_value=bar.close,
                        pre_close=bar.pre_close,
                        pct_change=bar.pct_change,
                        volume=bar.volume,
                        amount=bar.amount,
                        provider=bar.provider,
                        provider_symbol=provider_symbol,
                        provider_role=self.policy["provider_role"],
                        lineage=bar.lineage or bar.provider,
                        source_status="available",
                        freshness_status="intraday_fresh",
                        intraday_ma5=intraday_ma[0] if intraday_ma else None,
                        intraday_vs_ma5=intraday_ma[1] if intraday_ma else None,
                        native_history_status=native_status,
                        data_status="intraday_fresh",
                        response_hash=bar.source_payload_hash,
                        fetched_at=bar.fetched_at,
                        refresh_run_id=run.id,
                    ))
                    run.success_count += 1
                    run.intraday_count += 1
                    session.add(MarketRefreshItem(
                        run_id=run.id, sector_key=path.market_path_key, status="intraday_fresh",
                        trade_date=bar.trade_date, provider=bar.provider,
                        provider_symbol=provider_symbol,
                        lineage=bar.lineage or bar.provider, detail="server_cache",
                    ))
                else:
                    run.failure_count += 1
                    session.add(MarketRefreshItem(
                        run_id=run.id, sector_key=path.market_path_key, status="provider_failed",
                        provider=self.policy["provider"], error_code=error_code or "provider_error",
                        error_message=error_message or "Provider request failed", detail="provider_failed",
                    ))
                session.flush()
            run.unsupported_count = len(registry.unsupported_market_paths)
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
                    record.heartbeat_at = run.finished_at
                    record.lease_expires_at = run.finished_at + timedelta(seconds=self._lease_seconds)
            session.commit()
            return {
                "run_id": run.id, "status": run.status,
                "provider_requests": self._provider.request_count if self._uses_default_fetcher else len(paths),
                "success_count": run.success_count, "failure_count": run.failure_count,
                "stale_count": run.stale_count, "unsupported_count": run.unsupported_count,
                **self._provider.cycle_stats,
            }

    def status(self, session: Session | None = None) -> dict:
        """Return runtime facts with one short-lived database session.

        Reader routes already have a request session.  Reusing it prevents a
        status read from opening a nested provider-health session for every
        request.  Background and Admin callers still receive the same payload
        with an independently scoped session.
        """
        now = self._now()
        local_trade_date = now.astimezone(ZoneInfo(self.policy["timezone"])).date().isoformat()
        rules = load_calendar()
        calendar_meta = rules.metadata(date.fromisoformat(local_trade_date)) if rules else {
            "calendar_coverage_start": None,
            "calendar_coverage_end": None,
            "calendar_source": None,
            "calendar_source_version": None,
            "calendar_status": "calendar_unavailable",
            "calendar_warning": "calendar_source_unavailable",
            "calendar_days_remaining": None,
        }
        def payload(active_session: Session) -> dict:
            control = active_session.get(MarketAutomationControl, "intraday")
            record = active_session.get(IntradayRefreshSession, self._session_id) if self._session_id else None
            latest_run = active_session.scalar(select(MarketRefreshRun).where(MarketRefreshRun.mode == "intraday_refresh").order_by(desc(MarketRefreshRun.started_at)))
            latest_snapshot = active_session.scalar(select(SectorIntradaySnapshot).order_by(desc(SectorIntradaySnapshot.observed_at)))
            def display(value: datetime | None) -> str | None:
                if value is None:
                    return None
                aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
                return aware.astimezone(ZoneInfo(self.policy["timezone"])).strftime("%m/%d %H:%M")

            return {
                "session_status": "running" if self._enabled else "paused",
                "admin_paused": bool(control and control.admin_paused),
                "scheduler_registered": self._enabled,
                "market_phase": market_phase(now, self.policy),
                "market_phase_detail": market_phase_detail(now, self.policy),
                "market_session": market_session(now, self.policy),
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
                "supported_market_path_count": len(load_market_path_registry().supported_market_paths),
                "unsupported_count": len(load_market_path_registry().unsupported_market_paths),
                "viewer_provider_access": False,
                "auto_start": bool(self.policy["auto_start"]),
                "last_runtime_error": self._last_runtime_error,
                "recovered_stale_sessions": self._recovered_sessions,
                "owner_instance_id": self._instance_id,
                "provider_health": self._provider.health_rows(active_session),
                "provider_cycle_stats": self._provider.cycle_stats,
                **calendar_meta,
            }

        if session is not None:
            return payload(session)
        with self.sessions() as active_session:
            return payload(active_session)

    def provider_health(self) -> list[dict]:
        return self._provider.health_rows()

    def probe_provider(self, provider_key: str) -> dict:
        bundle = load_seed_bundle()
        mappings = {item.sector_key: item for item in bundle.mappings}
        return self._provider.probe_provider(provider_key, mappings, self._now())
