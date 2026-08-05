"""Default-disabled daily pipeline for the isolated security-proxy data lane."""
from __future__ import annotations

import threading
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable

from .providers.tencent_standard_quote import TencentStandardSecurityQuoteProvider
from .security_proxy_dynamic_selection import SecurityProxyDynamicSelectionService, SecurityProxySelectionSnapshotStore
from .security_proxy_eod import SHANGHAI, SecurityProxyEodCaptureService, SecurityProxyEodError, SecurityProxyEodFileStore, validate_capture_date


PIPELINE_SAFE_TIME = time(15, 20)


class SecurityProxyDailyPipeline:
    """One idempotent, file-only post-close run; no formal SQLite is involved."""

    def __init__(self, *, eod_root: Path = Path("var/security-proxy-eod"), selection_root: Path = Path("var/security-proxy-selections"), provider: TencentStandardSecurityQuoteProvider | None = None, now: Callable[[], datetime] | None = None) -> None:
        self.store = SecurityProxyEodFileStore(eod_root)
        self.selection_store = SecurityProxySelectionSnapshotStore(selection_root)
        self.provider = provider or TencentStandardSecurityQuoteProvider()
        self.now = now or (lambda: datetime.now(SHANGHAI))
        self._lock = threading.Lock()

    def run_once(self, *, enable_provider: bool = False) -> dict[str, object]:
        if not enable_provider:
            return {"status": "scheduler_disabled", "provider_called": False, "database_written": False}
        if not self._lock.acquire(blocking=False):
            return {"status": "pipeline_already_running", "provider_called": False, "database_written": False}
        try:
            local = self.now().astimezone(SHANGHAI)
            validate_capture_date(local.date())
            if local.timetz().replace(tzinfo=None) < PIPELINE_SAFE_TIME:
                return {"status": "market_not_closed", "provider_called": False, "database_written": False}
            if self.selection_store.day_path(local.date()).exists():
                return {"status": "already_completed", "provider_called": False, "database_written": False}
            if self.store.day_path(local.date()).exists():
                # A manually verified same-day file must never be overwritten
                # merely because the dynamic-selection pipeline is enabled.
                capture_records = tuple(row for row in self.store.records() if row.trading_date == local.date())
                capture_failures: dict[str, str] = {}
                provider_called = False
            else:
                capture = SecurityProxyEodCaptureService(self.provider, self.store, now=self.now).capture(local.date(), enable_provider=True)
                capture_records, capture_failures, provider_called = capture.records, capture.failures, True
            selections = SecurityProxyDynamicSelectionService(now=self.now).build(local.date(), self.store.records())
            required_failures = [warning for selection in selections for warning in selection.warnings if warning.startswith("required_latest_eod_missing:")]
            if required_failures:
                return {"status": "required_capture_failed", "warnings": required_failures, "provider_called": provider_called, "database_written": False}
            path = self.selection_store.write(calculation_date=local.date(), snapshots=selections)
            return {"status": "completed", "capture_records": len(capture_records), "capture_failures": capture_failures, "selection_path": str(path), "effective_from": selections[0].effective_from_trading_date.isoformat(), "provider_called": provider_called, "database_written": False}
        except SecurityProxyEodError as exc:
            return {"status": exc.code, "provider_called": False, "database_written": False}
        finally:
            self._lock.release()


class SecurityProxyDailyPipelineCoordinator:
    """Single-process timer using the existing application's in-process model.

    It is constructed only when the explicit feature flag is true.  The
    ordinary EOD backfill remains untouched, and this coordinator writes only
    its separate file lane.
    """

    def __init__(self, pipeline: SecurityProxyDailyPipeline, *, now: Callable[[], datetime] | None = None) -> None:
        self.pipeline, self.now = pipeline, now or pipeline.now
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._enabled = False
        self.last_result: dict[str, object] | None = None

    def start(self) -> None:
        with self._lock:
            if self._enabled: return
            self._enabled = True
            self._schedule_next()

    def _schedule_next(self) -> None:
        current = self.now().astimezone(SHANGHAI)
        target = datetime.combine(current.date(), PIPELINE_SAFE_TIME, tzinfo=SHANGHAI)
        if current >= target: target += timedelta(days=1)
        self._timer = threading.Timer(max(1.0, (target - current).total_seconds()), self._run_and_schedule)
        self._timer.daemon = True; self._timer.start()

    def _run_and_schedule(self) -> None:
        if not self._enabled: return
        self.last_result = self.pipeline.run_once(enable_provider=True)
        with self._lock:
            if self._enabled: self._schedule_next()

    def shutdown(self) -> None:
        with self._lock:
            self._enabled = False
            if self._timer: self._timer.cancel(); self._timer = None
