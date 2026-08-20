"""Read-only Viewer composition and process-local cache for security proxies."""
from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable, Iterable

from sqlalchemy.orm import Session, sessionmaker

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
    def __init__(self, *, observation_service: SecurityProxyObservationService, enabled: bool = False, cache: SecurityProxyViewerCache | None = None, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.observation_service, self.enabled, self.cache, self.now = observation_service, enabled, cache or SecurityProxyViewerCache(), now

    def observe(
        self,
        availability: OfficialBoardAvailability,
        *,
        session: Session | None = None,
        session_factory: sessionmaker[Session] | None = None,
    ) -> dict:
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
        # Fetching a live quote may take seconds.  Never hold a SQLite
        # connection during that network phase; open a short session only
        # after the cache/provider work has completed.
        symbols = tuple(item.symbol for item in observation.instruments)
        if session is not None:
            histories = get_security_proxy_daily_histories(session, symbols)
        elif session_factory is not None:
            with session_factory() as history_session:
                histories = get_security_proxy_daily_histories(history_session, symbols)
        else:
            histories = {}
        instruments = [self._instrument_payload(item, histories.get(item.symbol, ())) for item in observation.instruments]
        completed_eod = any(item["data_mode"] == "completed_eod" for item in instruments)
        live = any(item["data_mode"] == "live" for item in instruments)
        status = "available" if live else "completed_eod" if completed_eod else observation.status
        return {**base, "viewer_source_mode": "security_proxy", "fallback_reason": availability.reason or availability.status, "disclosure": DISCLAIMER, "security_proxy": {"display_label": "代理观察", "status": status, "recommended_display_mode": observation.recommended_display_mode, "instruments": instruments, "cache_hit": cache_hit, "quote_datetime": observation.quote_datetime.isoformat() if observation.quote_datetime else None}}

    @staticmethod
    def _completed_eod_payload(item: object, history: tuple[object, ...]) -> dict | None:
        """Use an already captured close only when the live quote is unusable.

        The resulting value is explicitly labelled ``completed_eod``.  It is
        not a live substitute and it never causes a provider call or a write.
        """
        if not history:
            return None
        latest = history[-1]
        close = Decimal(str(latest.close))
        previous = Decimal(str(history[-2].close)) if len(history) > 1 else None
        change = close - previous if previous is not None else None
        pct_change = ((close / previous) - Decimal("1")) * Decimal("100") if previous and previous > 0 else None
        quote_datetime = getattr(latest, "quote_datetime", None) or getattr(latest, "fetched_at", None)
        return {
            "current": str(close), "pre_close": str(previous) if previous is not None else None,
            "change": str(change) if change is not None else None,
            "pct_change": str(pct_change) if pct_change is not None else None,
            "quote_datetime": quote_datetime.isoformat() if quote_datetime else None,
            "quote_status": "completed_eod", "error_class": None, "data_mode": "completed_eod",
        }

    def _instrument_payload(self, item: object, history: tuple[object, ...]) -> dict:
        quote_time = getattr(item, "quote_datetime", None)
        now = self.now()
        if now.tzinfo is None:
            # The app's default clock is UTC.  Tests and explicit callers may
            # provide a naive value, which therefore follows the same contract
            # instead of silently treating Shanghai wall-clock time as UTC.
            now = now.replace(tzinfo=timezone.utc)
        fresh_quote = isinstance(quote_time, datetime) and quote_time.tzinfo is not None and now.astimezone(timezone.utc) - quote_time.astimezone(timezone.utc) <= timedelta(minutes=15)
        live_available = getattr(item, "quote_status") == "available" and getattr(item, "current") is not None and fresh_quote
        quote = {
            "current": str(item.current) if live_available else None,
            "pre_close": str(item.pre_close) if live_available and item.pre_close is not None else None,
            "change": str(item.change) if live_available and item.change is not None else None,
            "pct_change": str(item.pct_change) if live_available and item.pct_change is not None else None,
            "quote_datetime": item.quote_datetime.isoformat() if live_available and item.quote_datetime else None,
            "quote_status": "available" if live_available else "unavailable",
            "error_class": item.error_class if live_available else ("stale_quote" if getattr(item, "quote_status") == "available" else item.error_class),
            "data_mode": "live" if live_available else "unavailable",
        }
        if not live_available:
            quote.update(self._completed_eod_payload(item, history) or {})
        current = Decimal(str(quote["current"])) if quote["current"] is not None else None
        return {
            "symbol": item.symbol, "security_name": item.security_name, "proxy_role": item.proxy_role,
            "coverage_type": item.coverage_type, **quote,
            **self._trend_payload(history, current),
        }

    @staticmethod
    def _trend_payload(history: Iterable[object], current: object) -> dict:
        metrics = build_security_proxy_trend_metrics(history, current)
        return {
            "recent_closes": [
                {
                    "trading_date": item.trading_date.isoformat(),
                    "close": float(item.close),
                    "change_pct_from_previous_close": float(item.change_pct_from_previous_close) if item.change_pct_from_previous_close is not None else None,
                }
                for item in metrics.recent_closes
            ],
            "ma5": float(metrics.ma5) if metrics.ma5 is not None else None,
            "ma10": float(metrics.ma10) if metrics.ma10 is not None else None,
            "ma20": float(metrics.ma20) if metrics.ma20 is not None else None,
            "distance_to_ma5_pct": float(metrics.distance_to_ma5_pct) if metrics.distance_to_ma5_pct is not None else None,
            "distance_to_ma10_pct": float(metrics.distance_to_ma10_pct) if metrics.distance_to_ma10_pct is not None else None,
            "distance_to_ma20_pct": float(metrics.distance_to_ma20_pct) if metrics.distance_to_ma20_pct is not None else None,
        }
