"""Standalone, report-independent Market Core read model.

This module intentionally knows only about a single Shanghai index, the
versioned fixed-security registry, completed EOD rows, and Tencent's standard
security quote contract.  It must never query or receive a report identifier,
PDF, sector assessment, path entry, or defense line.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable, Iterable

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from leopard_project.indicators import distance_from_average, moving_average
from leopard_project.providers.tencent_standard_quote import TencentQuoteError, TencentQuoteErrorCode, TencentStandardSecurityQuoteProvider
from leopard_project.security_proxy_daily import get_security_proxy_daily_histories
from leopard_project.security_proxy_observation import APPROVED, SecurityProxyDefinition, SecurityProxyInstrument, load_security_proxy_registry
from leopard_project.broad_market_anchors import BroadMarketAnchor, load_broad_market_anchors

from .live_market_anchor import LiveShanghaiMarketAnchorService, SHANGHAI_COMPOSITE_NAME, SHANGHAI_COMPOSITE_SYMBOL
from .models import LiveMarketAnchorDaily
from .security_proxy_viewer import SecurityProxyViewerCache


LIVE_FRESHNESS = timedelta(minutes=15)


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
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.provider = provider
        self.live_anchor = live_anchor
        self.enabled = enabled
        self.registry = registry or load_security_proxy_registry()
        self.cache = cache or SecurityProxyViewerCache()
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
        rows = tuple(reversed(session.scalars(select(LiveMarketAnchorDaily).where(
            LiveMarketAnchorDaily.symbol == SHANGHAI_COMPOSITE_SYMBOL,
        ).order_by(desc(LiveMarketAnchorDaily.trading_date)).limit(limit)).all()))
        live = self.live_anchor.observe_objective()
        quote_time = datetime.fromisoformat(live["quote_datetime"]) if live.get("quote_datetime") else None
        now = _aware(self.now())
        fresh = live.get("quote_status") == "available" and quote_time is not None and now - _aware(quote_time) <= LIVE_FRESHNESS
        live_payload = {
            "status": "available" if fresh else "unavailable",
            "symbol": SHANGHAI_COMPOSITE_SYMBOL,
            "name": live.get("index_name", SHANGHAI_COMPOSITE_NAME),
            "current": live.get("current") if fresh else None,
            "pre_close": live.get("pre_close") if fresh else None,
            "pct_change": live.get("pct_change") if fresh else None,
            "quote_datetime": live.get("quote_datetime") if fresh else None,
            "server_received_at": live.get("server_received_at") if fresh else None,
            "freshness": "fresh" if fresh else ("stale" if live.get("quote_status") == "available" else "unavailable"),
            "provider": live.get("provider"),
            "error_code": None if fresh else ("stale_quote" if live.get("quote_status") == "available" else live.get("error_code")),
            "cache_hit": live.get("cache_hit", False),
        }
        current = live_payload["current"] if live_payload["current"] is not None else (rows[-1].close if rows else None)
        return {
            "market_core": "standalone_objective", "symbol": SHANGHAI_COMPOSITE_SYMBOL,
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
        return {
            "market_core": "standalone_objective", "universe": "broad_market_anchors",
            "provider": self.provider.provider_key, "provider_role": self.provider.provider_role,
            "cache_hit": cache_hit, "provider_request_count": batch.provider_request_count if not cache_hit else 0,
            "anchors": [self._instrument_payload(item, histories.get(item.symbol, ()), batch) for item in anchors],
        }

    def _instrument_payload(self, instrument: SecurityProxyInstrument | BroadMarketAnchor, history: tuple[object, ...], batch: _CachedProxyBatch) -> dict:
        quote = batch.quotes.get(instrument.symbol)
        now = _aware(self.now())
        quote_time = getattr(quote, "quote_datetime", None)
        fresh = quote is not None and isinstance(quote_time, datetime) and now - _aware(quote_time) <= LIVE_FRESHNESS
        live_current = getattr(quote, "current", None) if fresh else None
        indicator_current = live_current if live_current is not None else (history[-1].close if history else None)
        live = {
            "status": "available" if fresh else "unavailable",
            "current": _as_float(live_current), "pre_close": _as_float(getattr(quote, "pre_close", None)) if fresh else None,
            "pct_change": _as_float(getattr(quote, "pct_change", None)) if fresh else None,
            "quote_datetime": quote_time.isoformat() if fresh else None,
            "server_received_at": batch.server_received_at.isoformat() if fresh else None,
            "freshness": "fresh" if fresh else ("stale" if quote is not None else "unavailable"),
            "provider": self.provider.provider_key,
            "error_code": None if fresh else ("stale_quote" if quote is not None else batch.failures.get(instrument.symbol)),
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
