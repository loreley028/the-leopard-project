"""Standalone, report-independent Market Core read model.

This module intentionally knows only about a single Shanghai index, the
versioned fixed-security registry, completed EOD rows, and Tencent's standard
security quote contract.  It must never query or receive a report identifier,
PDF, sector assessment, path entry, or defense line.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Callable, Iterable

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from leopard_project.indicators import distance_from_average, moving_average
from leopard_project.providers.tencent_standard_quote import TencentQuoteError, TencentQuoteErrorCode, TencentStandardSecurityQuoteProvider
from leopard_project.security_proxy_daily import get_security_proxy_daily_histories
from leopard_project.security_proxy_observation import APPROVED, SecurityProxyDefinition, SecurityProxyInstrument, load_security_proxy_registry
from leopard_project.broad_market_anchors import BroadMarketAnchor, load_broad_market_anchors
from leopard_project.report_registry import load_report_registry

from .live_market_anchor import LiveShanghaiMarketAnchorService, SHANGHAI_COMPOSITE_NAME, SHANGHAI_COMPOSITE_SYMBOL
from .models import LiveMarketAnchorDaily
from .market_date_axis import market_core_completed_dates
from .market_session import cn_a_session_state, reader_quote_display
from .security_proxy_viewer import SecurityProxyViewerCache


@dataclass(frozen=True)
class _CachedProxyBatch:
    quotes: dict[str, object]
    failures: dict[str, str]
    provider_request_count: int
    status: str
    server_received_at: datetime


def _as_float(value: object | None) -> float | None:
    return float(value) if value is not None else None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class MarketCoreReadService:
    """One read model for objective index and fixed-security facts.

    A request can choose only an approved registry key (or ``all``); symbols
    are always server-side.  The cache key is the sorted fixed symbol set, so
    duplicate viewers share one in-flight Tencent request.
    """

    def __init__(
        self,
        *,
        provider: TencentStandardSecurityQuoteProvider,
        live_anchor: LiveShanghaiMarketAnchorService,
        enabled: bool = False,
        registry: tuple[SecurityProxyDefinition, ...] | None = None,
        cache: SecurityProxyViewerCache | None = None,
        current_snapshot_cache: SecurityProxyViewerCache | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.provider = provider
        self.live_anchor = live_anchor
        self.enabled = enabled
        self.registry = registry or load_security_proxy_registry()
        self.cache = cache or SecurityProxyViewerCache()
        # The full Reader matrix deliberately refreshes less often than the
        # Shanghai hero.  It remains process-local, single-flight, and never
        # carries a database session across Tencent network I/O.
        self.current_snapshot_cache = current_snapshot_cache or SecurityProxyViewerCache(ttl_seconds=60, error_ttl_seconds=30)
        self.now = now

    @staticmethod
    def _coverage(rows: Iterable[object]) -> dict:
        items = tuple(rows)
        days = tuple(getattr(item, "trading_date") for item in items)
        return {
            "available_days": len(days),
            "first_date": days[0].isoformat() if days else None,
            "latest_date": days[-1].isoformat() if days else None,
            "missing_dates": [],
        }

    @staticmethod
    def _history_row(row: object, previous_close: Decimal | None = None) -> dict:
        close = Decimal(str(getattr(row, "close")))
        stored_previous = getattr(row, "pre_close", None)
        previous = Decimal(str(stored_previous)) if stored_previous is not None else previous_close
        pct_change = float((close / previous - Decimal("1")) * Decimal("100")) if previous and previous > 0 else _as_float(getattr(row, "pct_change", None))
        return {
            "trading_date": getattr(row, "trading_date").isoformat(),
            "close": float(close),
            "pct_change": pct_change,
            "quote_datetime": getattr(row, "quote_datetime", None).isoformat() if getattr(row, "quote_datetime", None) else None,
            "captured_at": getattr(row, "fetched_at", None).isoformat() if getattr(row, "fetched_at", None) else None,
            "source": getattr(row, "source", None),
            "data_mode": "completed_eod",
        }

    @staticmethod
    def _history_rows(rows: tuple[object, ...]) -> list[dict]:
        previous: Decimal | None = None
        payload: list[dict] = []
        for row in rows:
            payload.append(MarketCoreReadService._history_row(row, previous))
            previous = Decimal(str(getattr(row, "close")))
        return payload

    @staticmethod
    def _latest_completed(rows: tuple[object, ...]) -> dict | None:
        return MarketCoreReadService._history_rows(rows)[-1] if rows else None

    @staticmethod
    def _objective_averages(rows: tuple[object, ...], current: object | None) -> dict:
        closes = tuple(Decimal(str(getattr(row, "close"))) for row in rows)
        current_decimal = Decimal(str(current)) if current is not None else None
        result: dict[str, float | None] = {}
        for window in (5, 10, 20):
            average = moving_average(closes, window)
            result[f"ma{window}"] = _as_float(average)
            result[f"distance_to_ma{window}_pct"] = _as_float(distance_from_average(current_decimal, average)) if current_decimal is not None else None
        return result

    def shanghai(self, session: Session, *, limit: int = 20) -> dict:
        if limit < 1 or limit > 20:
            raise ValueError("limit must be between 1 and 20")
        live = self.live_anchor.observe_objective()
        # Fetch outside the SQLite read lifetime.  A slow live provider must
        # not keep a request connection checked out while it responds.
        rows = tuple(reversed(session.scalars(select(LiveMarketAnchorDaily).where(
            LiveMarketAnchorDaily.symbol == SHANGHAI_COMPOSITE_SYMBOL,
        ).order_by(desc(LiveMarketAnchorDaily.trading_date)).limit(limit)).all()))
        quote_time = datetime.fromisoformat(live["quote_datetime"]) if live.get("quote_datetime") else None
        now = _aware(self.now())
        display = reader_quote_display(
            quote_available=live.get("quote_status") == "available",
            quote_datetime=quote_time,
            current=live.get("current"),
            now=now,
        )
        live_payload = {
            "status": display.status,
            "symbol": SHANGHAI_COMPOSITE_SYMBOL,
            "name": live.get("index_name", SHANGHAI_COMPOSITE_NAME),
            "current": live.get("current") if display.status == "available" else None,
            "pre_close": live.get("pre_close") if display.status == "available" else None,
            "pct_change": live.get("pct_change") if display.status == "available" else None,
            "quote_datetime": live.get("quote_datetime") if display.status == "available" else None,
            "server_received_at": live.get("server_received_at") if display.status == "available" else None,
            "freshness": display.freshness,
            "display_mode": display.display_mode,
            "session_state": display.session_state,
            "provider": live.get("provider"),
            "error_code": display.error_code if live.get("quote_status") == "available" else live.get("error_code"),
            "cache_hit": live.get("cache_hit", False),
        }
        current = live_payload["current"] if live_payload["current"] is not None else (rows[-1].close if rows else None)
        return {
            "market_core": "standalone_objective", "symbol": SHANGHAI_COMPOSITE_SYMBOL,
            "date_axis_kind": "market_trading_day",
            "name": SHANGHAI_COMPOSITE_NAME, "live": live_payload,
            "latest_completed": self._latest_completed(rows),
            "history": self._history_rows(rows),
            "coverage": self._coverage(rows),
            "indicators": self._objective_averages(rows, current),
        }

    def _definitions(self, proxy_set: str) -> tuple[SecurityProxyDefinition, ...]:
        approved = tuple(item for item in self.registry if item.status == APPROVED)
        if proxy_set == "all":
            return approved
        found = next((item for item in approved if item.market_path_key == proxy_set), None)
        if found is None:
            raise KeyError(proxy_set)
        return (found,)

    def _current_instruments(self, scope: str) -> tuple[SecurityProxyInstrument | BroadMarketAnchor, ...]:
        """Resolve a constrained Reader scope to configured, server-side symbols."""
        if scope == "overview":
            return (BroadMarketAnchor(
                symbol=SHANGHAI_COMPOSITE_SYMBOL, exchange="sh", security_code="000001",
                security_name=SHANGHAI_COMPOSITE_NAME, display_order=0, enabled=True,
            ), *load_broad_market_anchors())
        if scope == "matrix":
            definitions = self._matrix_definitions()
            return tuple(item for definition in definitions for item in definition.instruments if item.enabled)
        definitions = self._definitions(scope)
        return tuple(item for definition in definitions for item in definition.instruments if item.enabled)

    def _matrix_definitions(self) -> tuple[SecurityProxyDefinition, ...]:
        """Return the configured active Reader universe in report order."""
        by_key = {item.market_path_key: item for item in self.registry}
        return tuple(by_key[item.sector_key] for item in load_report_registry() if item.lifecycle == "active" and item.sector_key in by_key)

    def current_quotes(self, *, scope: str) -> dict:
        """Serve one short-lived, single-flight quote batch for an approved scope.

        The overview contains Shanghai plus the four configured broad ETFs; a
        sector scope contains only that sector's fixed proxy securities.  No
        history, report, or caller-provided symbol enters this route.
        """
        instruments = self._current_instruments(scope)
        symbols = tuple(dict.fromkeys(item.symbol for item in instruments))
        cache_key = ("market_core_current", scope, *symbols)
        cache = self.current_snapshot_cache if scope == "matrix" else self.cache
        cached, cache_hit = cache.get_or_fetch(cache_key, lambda: (self._fetch_quotes(symbols),))
        batch = cached[0]
        now = _aware(self.now())
        payload = {
            "market_core": "standalone_objective",
            "scope": scope,
            "session_state": cn_a_session_state(now),
            "provider": self.provider.provider_key,
            "cache_hit": cache_hit,
            "provider_request_count": batch.provider_request_count if not cache_hit else 0,
            "quotes": [self._current_quote_payload(item, batch, now) for item in instruments],
        }
        if scope == "matrix":
            payload.update({
                "snapshot_ttl_seconds": self.current_snapshot_cache.ttl_seconds,
                "sectors": self._matrix_current_sectors(batch, now),
            })
        return payload

    def _matrix_current_sectors(self, batch: _CachedProxyBatch, now: datetime) -> list[dict]:
        sectors: list[dict] = []
        for definition in self._matrix_definitions():
            primary = definition.primary_observation
            stock = primary if primary and primary.proxy_role == "leader" else next(
                (item for item in definition.leader_proxies if item.enabled), None,
            )
            visible = tuple(item for item in (primary, stock) if item is not None)
            # A single-stock observation is intentionally shown only once.
            visible = tuple(dict.fromkeys(visible))
            quotes = [self._current_quote_payload(item, batch, now) for item in visible]
            quote_times = [item["quote_datetime"] for item in quotes if item["quote_datetime"]]
            sectors.append({
                "sector_key": definition.market_path_key,
                "sector_name": definition.display_name,
                "market_status": "available" if definition.status == APPROVED else "unavailable",
                "market_session": cn_a_session_state(now),
                "quote_time": max(quote_times) if quote_times else None,
                "instruments": quotes,
            })
        return sectors

    def _fetch_quotes(self, symbols: tuple[str, ...]) -> _CachedProxyBatch:
        received = _aware(self.now())
        if not self.enabled:
            return _CachedProxyBatch({}, {symbol: "market_core_disabled" for symbol in symbols}, 0, "unavailable", received)
        quotes: dict[str, object] = {}
        failures: dict[str, str] = {}
        requests = 0
        for offset in range(0, len(symbols), self.provider.max_batch_size):
            requested = symbols[offset:offset + self.provider.max_batch_size]
            try:
                batch = self.provider.fetch_batch(requested, allow_network=True)
            except TencentQuoteError as exc:
                failures.update({symbol: exc.code.value for symbol in requested})
                continue
            except Exception:
                failures.update({symbol: "provider_unavailable" for symbol in requested})
                continue
            requests += batch.request_count
            quotes.update({quote.requested_symbol: quote for quote in batch.quotes})
            failures.update({symbol: code.value for symbol, code in batch.failures.items()})
        status = "available" if quotes else "unavailable"
        return _CachedProxyBatch(quotes, failures, requests, status, received)

    def proxies(self, session: Session, *, proxy_set: str, limit: int = 20) -> dict:
        if limit < 1 or limit > 20:
            raise ValueError("limit must be between 1 and 20")
        definitions = self._definitions(proxy_set)
        symbols = tuple(dict.fromkeys(instrument.symbol for definition in definitions for instrument in definition.instruments if instrument.enabled))
        cache_key = ("market_core", *sorted(symbols))
        cached, cache_hit = self.cache.get_or_fetch(cache_key, lambda: (self._fetch_quotes(symbols),))
        batch = cached[0]
        histories = get_security_proxy_daily_histories(session, symbols, limit=limit)
        groups: list[dict] = []
        for definition in definitions:
            instruments = [self._instrument_payload(item, histories.get(item.symbol, ()), batch) for item in definition.instruments if item.enabled]
            groups.append({
                "proxy_set": definition.market_path_key,
                "display_name": definition.display_name,
                "status": "available" if any(item["live"]["status"] == "available" for item in instruments) else "unavailable",
                "instruments": instruments,
            })
        return {
            "market_core": "standalone_objective", "proxy_set": proxy_set,
            "provider": self.provider.provider_key, "provider_role": self.provider.provider_role,
            "cache_hit": cache_hit, "provider_request_count": batch.provider_request_count if not cache_hit else 0,
            "groups": groups,
        }

    def broad_market(self, session: Session, *, limit: int = 20) -> dict:
        """Read independent broad-market ETFs without involving any report or proxy set."""
        if limit < 1 or limit > 20:
            raise ValueError("limit must be between 1 and 20")
        anchors = load_broad_market_anchors()
        symbols = tuple(item.symbol for item in anchors)
        cache_key = ("market_core_broad", *symbols)
        cached, cache_hit = self.cache.get_or_fetch(cache_key, lambda: (self._fetch_quotes(symbols),))
        batch = cached[0]
        histories = get_security_proxy_daily_histories(session, symbols, limit=limit)
        trading_date_axis = [day.isoformat() for day in market_core_completed_dates(session)[-10:]]
        return {
            "market_core": "standalone_objective", "universe": "broad_market_anchors",
            "date_axis_kind": "market_trading_day", "trading_date_axis": trading_date_axis,
            "provider": self.provider.provider_key, "provider_role": self.provider.provider_role,
            "cache_hit": cache_hit, "provider_request_count": batch.provider_request_count if not cache_hit else 0,
            "anchors": [self._instrument_payload(item, histories.get(item.symbol, ()), batch) for item in anchors],
        }

    def _instrument_payload(self, instrument: SecurityProxyInstrument | BroadMarketAnchor, history: tuple[object, ...], batch: _CachedProxyBatch) -> dict:
        quote = batch.quotes.get(instrument.symbol)
        now = _aware(self.now())
        quote_time = getattr(quote, "quote_datetime", None)
        display = reader_quote_display(
            quote_available=quote is not None,
            quote_datetime=quote_time if isinstance(quote_time, datetime) else None,
            current=getattr(quote, "current", None),
            now=now,
        )
        live_current = getattr(quote, "current", None) if display.status == "available" else None
        indicator_current = live_current if live_current is not None else (history[-1].close if history else None)
        live = {
            "status": display.status,
            "current": _as_float(live_current), "pre_close": _as_float(getattr(quote, "pre_close", None)) if display.status == "available" else None,
            "pct_change": _as_float(getattr(quote, "pct_change", None)) if display.status == "available" else None,
            "quote_datetime": quote_time.isoformat() if display.status == "available" else None,
            "server_received_at": batch.server_received_at.isoformat() if display.status == "available" else None,
            "freshness": display.freshness,
            "display_mode": display.display_mode,
            "session_state": display.session_state,
            "provider": self.provider.provider_key,
            "error_code": display.error_code if quote is not None else batch.failures.get(instrument.symbol),
        }
        return {
            "symbol": instrument.symbol, "name": instrument.security_name,
            "role": instrument.proxy_role if isinstance(instrument, SecurityProxyInstrument) else "broad_market_etf",
            "security_code": instrument.reader_code,
            "coverage_type": instrument.coverage_type if isinstance(instrument, SecurityProxyInstrument) else "full",
            "live": live,
            "latest_completed": self._latest_completed(history),
            "history": self._history_rows(history),
            "coverage": self._coverage(history),
            "indicators": self._objective_averages(history, indicator_current),
        }

    def _current_quote_payload(self, instrument: SecurityProxyInstrument | BroadMarketAnchor, batch: _CachedProxyBatch, now: datetime) -> dict:
        quote = batch.quotes.get(instrument.symbol)
        quote_time = getattr(quote, "quote_datetime", None)
        display = reader_quote_display(
            quote_available=quote is not None,
            quote_datetime=quote_time if isinstance(quote_time, datetime) else None,
            current=getattr(quote, "current", None),
            now=now,
        )
        available = display.status == "available"
        return {
            "symbol": instrument.symbol,
            "name": instrument.security_name,
            "security_code": instrument.reader_code,
            "status": display.status,
            "current": _as_float(getattr(quote, "current", None)) if available else None,
            "pre_close": _as_float(getattr(quote, "pre_close", None)) if available else None,
            "pct_change": _as_float(getattr(quote, "pct_change", None)) if available else None,
            "quote_datetime": quote_time.isoformat() if available else None,
            "server_received_at": batch.server_received_at.isoformat() if available else None,
            "freshness": display.freshness,
            "display_mode": display.display_mode,
            "session_state": display.session_state,
            "provider": self.provider.provider_key,
            "error_code": display.error_code if quote is not None else batch.failures.get(instrument.symbol),
        }
