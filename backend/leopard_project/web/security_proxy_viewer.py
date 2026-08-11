"""Read-only Viewer composition and process-local cache for security proxies."""
from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Callable, Iterable

from sqlalchemy.orm import Session

from leopard_project.security_proxy_daily import build_security_proxy_trend_metrics, get_security_proxy_daily_histories
from leopard_project.security_proxy_observation import SecurityProxyObservationService


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
    def __init__(self, *, observation_service: SecurityProxyObservationService, enabled: bool = False, cache: SecurityProxyViewerCache | None = None, now: Callable[[], datetime] = datetime.now) -> None:
        self.observation_service, self.enabled, self.cache, self.now = observation_service, enabled, cache or SecurityProxyViewerCache(), now

    def observe(self, availability: OfficialBoardAvailability, *, session: Session | None = None) -> dict:
        base = {"market_path_key": availability.market_path_key, "official_board": asdict(availability), "security_proxy": None, "fallback_reason": None, "disclosure": None, "generated_at": self.now().isoformat()}
        if availability.available and availability.fresh:
            return {**base, "viewer_source_mode": "official_board"}
        if not self.enabled:
            return {**base, "viewer_source_mode": "unavailable", "fallback_reason": "security_proxy_viewer_disabled"}
        definition = next((item for item in self.observation_service.registry if item.market_path_key == availability.market_path_key), None)
        if definition is None:
            return {**base, "viewer_source_mode": "unavailable", "fallback_reason": "not_found"}
        if definition.status != "approved_fallback":
            return {**base, "viewer_source_mode": "unavailable", "fallback_reason": "no_reliable_security_proxy", "disclosure": definition.disclosure}
        key = tuple(sorted(item.symbol for item in definition.instruments if item.enabled))
        observations, cache_hit = self.cache.get_or_fetch(key, lambda: self.observation_service.observe([availability.market_path_key], enable_provider=True))
        observation = observations[0]
        histories = get_security_proxy_daily_histories(session, (item.symbol for item in observation.instruments)) if session else {}
        instruments = [{
            "symbol": item.symbol, "security_name": item.security_name, "proxy_role": item.proxy_role,
            "coverage_type": item.coverage_type, "current": str(item.current) if item.current is not None else None,
            "pre_close": str(item.pre_close) if item.pre_close is not None else None, "change": str(item.change) if item.change is not None else None,
            "pct_change": str(item.pct_change) if item.pct_change is not None else None,
            "quote_datetime": item.quote_datetime.isoformat() if item.quote_datetime else None,
            "quote_status": item.quote_status, "error_class": item.error_class,
            **self._trend_payload(histories.get(item.symbol, ()), item.current),
        } for item in observation.instruments]
        return {**base, "viewer_source_mode": "security_proxy", "fallback_reason": availability.reason or availability.status, "disclosure": DISCLAIMER, "security_proxy": {"display_label": "代理观察", "status": observation.status, "recommended_display_mode": observation.recommended_display_mode, "instruments": instruments, "cache_hit": cache_hit, "quote_datetime": observation.quote_datetime.isoformat() if observation.quote_datetime else None}}

    @staticmethod
    def _trend_payload(history: Iterable[object], current: object) -> dict:
        metrics = build_security_proxy_trend_metrics(history, current)
        return {
            "recent_closes": [
                {"trading_date": item.trading_date.isoformat(), "close": float(item.close)}
                for item in metrics.recent_closes
            ],
            "ma5": float(metrics.ma5) if metrics.ma5 is not None else None,
            "ma10": float(metrics.ma10) if metrics.ma10 is not None else None,
            "ma20": float(metrics.ma20) if metrics.ma20 is not None else None,
            "distance_to_ma5_pct": float(metrics.distance_to_ma5_pct) if metrics.distance_to_ma5_pct is not None else None,
            "distance_to_ma10_pct": float(metrics.distance_to_ma10_pct) if metrics.distance_to_ma10_pct is not None else None,
            "distance_to_ma20_pct": float(metrics.distance_to_ma20_pct) if metrics.distance_to_ma20_pct is not None else None,
        }
