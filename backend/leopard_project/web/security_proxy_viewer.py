"""Read-only Viewer composition and process-local cache for security proxies."""
from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Callable, Iterable

from leopard_project.security_proxy_observation import SecurityProxyObservationService
from leopard_project.security_proxy_dynamic_selection import SecurityProxySelectionSnapshotStore


DISCLAIMER = "代理证券用于观察主题相关标的表现，不代表官方板块指数或完整行业表现。"


@dataclass(frozen=True)
class OfficialBoardAvailability:
    market_path_key: str
    available: bool
    fresh: bool
    status: str
    reason: str | None
    quote_datetime: str | None


class SecurityProxyViewerCache:
    def __init__(self, *, ttl_seconds: int = 300, error_ttl_seconds: int = 30, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl_seconds, self.error_ttl_seconds, self.clock = ttl_seconds, error_ttl_seconds, clock
        self._values: dict[tuple[str, ...], tuple[float, tuple]] = {}
        self._locks: dict[tuple[str, ...], threading.Lock] = {}
        self._guard = threading.Lock()

    def get_or_fetch(self, key: tuple[str, ...], fetcher: Callable[[], tuple]) -> tuple[tuple, bool]:
        now = self.clock(); cached = self._values.get(key)
        if cached and cached[0] > now: return cached[1], True
        with self._guard: lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            now = self.clock(); cached = self._values.get(key)
            if cached and cached[0] > now: return cached[1], True
            value = fetcher(); has_available = any(item.status in {"available", "partial"} for item in value)
            self._values[key] = (now + (self.ttl_seconds if has_available else self.error_ttl_seconds), value)
            return value, False


class SecurityProxyViewerService:
    """Only this service decides fallback; callers never supply a security code."""
    def __init__(self, *, observation_service: SecurityProxyObservationService, enabled: bool = False, dynamic_selection_enabled: bool = False, selection_store: SecurityProxySelectionSnapshotStore | None = None, cache: SecurityProxyViewerCache | None = None, now: Callable[[], datetime] = datetime.now) -> None:
        self.observation_service, self.enabled, self.dynamic_selection_enabled, self.selection_store, self.cache, self.now = observation_service, enabled, dynamic_selection_enabled, selection_store or SecurityProxySelectionSnapshotStore(), cache or SecurityProxyViewerCache(), now

    def observe(self, availability: OfficialBoardAvailability) -> dict:
        base = {"market_path_key": availability.market_path_key, "official_board": asdict(availability), "security_proxy": None, "fallback_reason": None, "disclosure": None, "selection_mode": "unavailable", "selection_calculation_date": None, "selection_effective_date": None, "selection_policy_version": None, "selection_warnings": [], "generated_at": self.now().isoformat()}
        if availability.available and availability.fresh:
            return {**base, "viewer_source_mode": "official_board", "selection_mode": "official_board"}
        if not self.enabled:
            return {**base, "viewer_source_mode": "unavailable", "fallback_reason": "security_proxy_viewer_disabled"}
        definition = next((item for item in self.observation_service.registry if item.market_path_key == availability.market_path_key), None)
        if definition is None:
            return {**base, "viewer_source_mode": "unavailable", "fallback_reason": "not_found"}
        if definition.status != "approved_fallback":
            return {**base, "viewer_source_mode": "unavailable", "fallback_reason": "no_reliable_security_proxy", "disclosure": definition.disclosure}
        dynamic = None
        if self.dynamic_selection_enabled:
            try: dynamic = self.selection_store.latest_effective_for(self.now().date()).get(availability.market_path_key)
            except Exception: dynamic = None
        if dynamic is not None:
            key = ("dynamic", availability.market_path_key, dynamic.calculation_trading_date.isoformat(), *(item.symbol for item in dynamic.selected_instruments))
            observations, cache_hit = self.cache.get_or_fetch(key, lambda: (self.observation_service.observe_selected(availability.market_path_key, definition.display_name, dynamic.selected_instruments),))
            selection_mode, meta = "dynamic_eod_snapshot", {"selection_calculation_date": dynamic.calculation_trading_date.isoformat(), "selection_effective_date": dynamic.effective_from_trading_date.isoformat(), "selection_policy_version": dynamic.policy_version, "selection_warnings": list(dynamic.warnings)}
        else:
            key = tuple(sorted(item.symbol for item in definition.instruments if item.enabled))
            observations, cache_hit = self.cache.get_or_fetch(key, lambda: self.observation_service.observe([availability.market_path_key], enable_provider=True))
            selection_mode, meta = "static_approved_registry", {}
        observation = observations[0]
        instruments = [{
            "symbol": item.symbol, "security_name": item.security_name, "proxy_role": item.proxy_role,
            "coverage_type": item.coverage_type, "current": str(item.current) if item.current is not None else None,
            "pre_close": str(item.pre_close) if item.pre_close is not None else None, "change": str(item.change) if item.change is not None else None,
            "pct_change": str(item.pct_change) if item.pct_change is not None else None,
            "quote_datetime": item.quote_datetime.isoformat() if item.quote_datetime else None,
            "quote_status": item.quote_status, "error_class": item.error_class,
        } for item in observation.instruments]
        return {**base, **meta, "viewer_source_mode": "security_proxy", "selection_mode": selection_mode, "fallback_reason": availability.reason or availability.status, "disclosure": DISCLAIMER, "security_proxy": {"display_label": "代理观察", "status": observation.status, "recommended_display_mode": observation.recommended_display_mode, "instruments": instruments, "cache_hit": cache_hit, "quote_datetime": observation.quote_datetime.isoformat() if observation.quote_datetime else None}}
