"""Explicit, read-only fallback observation for approved security proxies."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterable

from .config import CONFIG_DIR
from .providers.tencent_standard_quote import TencentQuoteError, TencentQuoteErrorCode, TencentStandardSecurityQuoteProvider


REGISTRY_PATH = CONFIG_DIR / "security_proxy_registry_v1.json"
SYMBOL = re.compile(r"^(?:sh|sz)\d{6}$")
APPROVED = "approved_fallback"
NO_RELIABLE = "no_reliable_security_proxy"
FIXED_DISCLOSURE = "代理观察仅用于正式板块源不可用时的人工研究参考；不替代正式板块，不构成合成板块指数或投资建议。"


class SecurityProxyRegistryError(ValueError):
    pass


@dataclass(frozen=True)
class SecurityProxyInstrument:
    symbol: str
    exchange: str
    security_code: str
    security_name: str
    proxy_role: str
    coverage_type: str
    display_order: int
    enabled: bool
    rationale: str


@dataclass(frozen=True)
class SecurityProxyDefinition:
    market_path_key: str
    display_name: str
    official_board_preferred: bool
    fallback_only: bool
    production_enabled: bool
    status: str
    recommended_display_mode: str
    primary_observation_symbol: str | None
    priority_theme: bool
    etf_proxies: tuple[SecurityProxyInstrument, ...]
    leader_proxies: tuple[SecurityProxyInstrument, ...]
    semantic_risks: tuple[str, ...]
    disclosure: str
    version: str
    effective_date: str

    @property
    def instruments(self) -> tuple[SecurityProxyInstrument, ...]:
        return self.etf_proxies + self.leader_proxies

    @property
    def primary_observation(self) -> SecurityProxyInstrument | None:
        return next((item for item in self.instruments if item.symbol == self.primary_observation_symbol), None)


@dataclass(frozen=True)
class SecurityProxyInstrumentQuote:
    symbol: str
    security_name: str
    proxy_role: str
    coverage_type: str
    current: Decimal | None
    pre_close: Decimal | None
    change: Decimal | None
    pct_change: Decimal | None
    quote_datetime: datetime | None
    quote_status: str
    error_class: str | None


@dataclass(frozen=True)
class SecurityProxyObservation:
    market_path_key: str
    display_name: str
    source_mode: str
    display_label: str
    recommended_display_mode: str
    official_board_preferred: bool
    quote_datetime: datetime | None
    fetched_at: datetime
    instruments: tuple[SecurityProxyInstrumentQuote, ...]
    disclosure: str
    status: str


def _instrument(value: dict[str, object], role: str) -> SecurityProxyInstrument:
    return SecurityProxyInstrument(
        symbol=str(value["symbol"]), exchange=str(value["exchange"]), security_code=str(value["security_code"]),
        security_name=str(value["security_name"]), proxy_role=str(value["proxy_role"]), coverage_type=str(value["coverage_type"]),
        display_order=int(value["display_order"]), enabled=bool(value["enabled"]), rationale=str(value["rationale"]),
    )


def _definition(value: dict[str, object]) -> SecurityProxyDefinition:
    return SecurityProxyDefinition(
        market_path_key=str(value["market_path_key"]), display_name=str(value["display_name"]),
        official_board_preferred=bool(value["official_board_preferred"]), fallback_only=bool(value["fallback_only"]),
        production_enabled=bool(value["production_enabled"]), status=str(value["status"]),
        recommended_display_mode=str(value["recommended_display_mode"]),
        primary_observation_symbol=str(value["primary_observation_symbol"]) if value.get("primary_observation_symbol") else None,
        priority_theme=bool(value["priority_theme"]),
        etf_proxies=tuple(_instrument(row, "etf") for row in value["etf_proxies"]),
        leader_proxies=tuple(_instrument(row, "leader") for row in value["leader_proxies"]),
        semantic_risks=tuple(str(item) for item in value["semantic_risks"]), disclosure=str(value["disclosure"]),
        version=str(value["version"]), effective_date=str(value["effective_date"]),
    )


def validate_security_proxy_registry(document: dict[str, object]) -> tuple[SecurityProxyDefinition, ...]:
    if document.get("default_enabled") is not False or document.get("official_board_preferred") is not True:
        raise SecurityProxyRegistryError("registry must remain default-disabled and prefer official boards")
    if not document.get("disclosure"):
        raise SecurityProxyRegistryError("registry disclosure is required")
    paths = tuple(_definition(row) for row in document.get("paths", []))
    if len({path.market_path_key for path in paths}) != len(paths):
        raise SecurityProxyRegistryError("market path keys must be unique")
    approved = [path for path in paths if path.status == APPROVED]
    if len(approved) != 11:
        raise SecurityProxyRegistryError("exactly 11 approved fallback paths are required")
    for path in paths:
        if path.status not in {APPROVED, NO_RELIABLE, "disabled"}:
            raise SecurityProxyRegistryError("path status is invalid")
        if not path.official_board_preferred or not path.fallback_only or path.production_enabled or not path.disclosure:
            raise SecurityProxyRegistryError("every path must be a disclosed, non-production fallback")
        instruments = path.instruments
        if path.status == NO_RELIABLE and instruments:
            raise SecurityProxyRegistryError("no-reliable path must not contain instruments")
        if path.status == NO_RELIABLE and path.primary_observation_symbol is not None:
            raise SecurityProxyRegistryError("no-reliable path must not define a primary observation")
        if path.status == APPROVED and not instruments:
            raise SecurityProxyRegistryError("approved fallback needs an instrument")
        if path.status == APPROVED and path.primary_observation is None:
            raise SecurityProxyRegistryError("approved fallback needs an enabled fixed primary observation")
        if len(path.etf_proxies) > 1 or len(path.leader_proxies) > (3 if path.priority_theme else 1):
            raise SecurityProxyRegistryError("proxy count exceeds path limit")
        symbols = [item.symbol for item in instruments]
        orders = [item.display_order for item in instruments]
        if len(symbols) != len(set(symbols)) or len(orders) != len(set(orders)):
            raise SecurityProxyRegistryError("path has duplicate symbol or display order")
        for item in path.etf_proxies:
            if item.proxy_role != "etf": raise SecurityProxyRegistryError("ETF role mismatch")
        for item in path.leader_proxies:
            if item.proxy_role != "leader": raise SecurityProxyRegistryError("leader role mismatch")
        for item in instruments:
            if not SYMBOL.fullmatch(item.symbol) or item.security_code != item.symbol[2:] or item.exchange != item.symbol[:2].upper():
                raise SecurityProxyRegistryError("security symbol is invalid")
        if path.primary_observation is not None and not path.primary_observation.enabled:
            raise SecurityProxyRegistryError("primary observation must remain enabled")
    cpo = next(item for item in paths if item.market_path_key == "cpo")
    if [item.symbol for item in cpo.etf_proxies] != ["sh515880"] or [item.symbol for item in cpo.leader_proxies] != ["sz300308", "sz300502", "sz300394"]:
        raise SecurityProxyRegistryError("CPO must retain the approved ETF and three leaders")
    if {item.market_path_key for item in paths if item.status == NO_RELIABLE} != {"glass_substrate", "catering"}:
        raise SecurityProxyRegistryError("no-reliable paths are incomplete")
    return paths


def load_security_proxy_registry(path: Path = REGISTRY_PATH) -> tuple[SecurityProxyDefinition, ...]:
    return validate_security_proxy_registry(json.loads(path.read_text(encoding="utf-8")))


class SecurityProxyObservationService:
    """Explicit-use service; it has no Scheduler, database, API or UI integration."""

    def __init__(self, *, provider: TencentStandardSecurityQuoteProvider, registry: tuple[SecurityProxyDefinition, ...] | None = None, now: Callable[[], datetime] = datetime.now) -> None:
        self.provider = provider
        self.registry = registry or load_security_proxy_registry()
        self._now = now

    def observe(self, market_path_keys: Iterable[str], *, enable_provider: bool = False) -> tuple[SecurityProxyObservation, ...]:
        selected = tuple(next((item for item in self.registry if item.market_path_key == key), None) for key in dict.fromkeys(market_path_keys))
        if any(item is None for item in selected):
            missing = next(key for key, item in zip(dict.fromkeys(market_path_keys), selected) if item is None)
            raise KeyError(f"security proxy path is not configured: {missing}")
        paths = tuple(item for item in selected if item is not None)
        fetched_at = self._now()
        requested = tuple(dict.fromkeys(item.symbol for path in paths if path.status == APPROVED for item in path.instruments if item.enabled))
        if not enable_provider:
            return tuple(self._observation(path, {}, {}, fetched_at, "disabled") for path in paths)
        try:
            batch = self.provider.fetch_batch(requested, allow_network=True) if requested else None
            quotes = {quote.requested_symbol: quote for quote in batch.quotes} if batch else {}
            failures = batch.failures if batch else {}
        except TencentQuoteError as exc:
            quotes, failures = {}, {symbol: exc.code for symbol in requested}
        return tuple(self._observation(path, quotes, failures, fetched_at, None) for path in paths)

    @staticmethod
    def _observation(path: SecurityProxyDefinition, quotes: dict, failures: dict[str, TencentQuoteErrorCode], fetched_at: datetime, forced_status: str | None) -> SecurityProxyObservation:
        if path.status != APPROVED:
            return SecurityProxyObservation(path.market_path_key, path.display_name, "security_proxy", "代理观察", path.recommended_display_mode, True, None, fetched_at, (), path.disclosure, "not_configured")
        items: list[SecurityProxyInstrumentQuote] = []
        for item in path.instruments:
            quote = quotes.get(item.symbol)
            error = failures.get(item.symbol)
            items.append(SecurityProxyInstrumentQuote(
                item.symbol, item.security_name, item.proxy_role, item.coverage_type,
                quote.current if quote else None, quote.pre_close if quote else None, quote.change if quote else None,
                quote.pct_change if quote else None, quote.quote_datetime if quote else None,
                "available" if quote else "unavailable", error.value if error else ("provider_disabled" if forced_status else None),
            ))
        available = sum(item.quote_status == "available" for item in items)
        status = forced_status or ("available" if available == len(items) else "partial" if available else "unavailable")
        latest = max((item.quote_datetime for item in items if item.quote_datetime), default=None)
        return SecurityProxyObservation(path.market_path_key, path.display_name, "security_proxy", "代理观察", path.recommended_display_mode, True, latest, fetched_at, tuple(items), path.disclosure, status)
