from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from html.parser import HTMLParser
from typing import Callable
from zoneinfo import ZoneInfo

from ..models import DailyBar, DataStatus, LiquidityStatus, Market, ProviderNativeClose, SectorMapping
from .base import ProviderError, ProviderErrorCategory
from .capabilities import load_provider_capabilities
from .ths_public import ThsPublicValidationProvider, _default_transport


Transport = Callable[[str, float], bytes]


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._ignored += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._ignored:
            self._ignored -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored and data.strip():
            self.parts.append(data.strip())


def _exact_mappings() -> dict[str, dict[str, str]]:
    output: dict[str, dict[str, str]] = {}
    for sector_key, capability in load_provider_capabilities().items():
        for candidate in capability.selectable_candidates:
            if candidate.provider == "ths_exact_spot" and candidate.mapping_type in {"direct", "proxy"}:
                output[sector_key] = {
                    "sector_key": sector_key,
                    "canonical_sector": capability.display_name,
                    "provider_symbol": candidate.symbol,
                    "provider_name": candidate.provider_name,
                    "mapping_type": candidate.mapping_type,
                }
                break
    return output


class ThsExactSpotProvider:
    """Exact, capability-gated THS public board adapter; never fuzzy-searches."""

    provider_key = "ths_exact_spot"
    provider_role = "diagnostic_provider"
    detail_url = "https://q.10jqka.com.cn/thshy/detail/code/{symbol}/"

    def __init__(self, *, transport: Transport | None = None, timeout: float = 20.0) -> None:
        self._transport = transport or _default_transport
        self._timeout = timeout
        self._mappings = _exact_mappings()
        self._history = ThsPublicValidationProvider(transport=self._transport)
        self._detail_cache: dict[str, bytes] = {}
        self.request_count = 0

    def begin_cycle(self) -> None:
        self._detail_cache = {}
        self.request_count = 0

    def _mapping(self, mapping: SectorMapping) -> dict[str, str]:
        item = self._mappings.get(mapping.sector_key)
        if item is None:
            raise ProviderError(ProviderErrorCategory.INVALID_SYMBOL, "exact THS intraday mapping is unavailable", retryable=False)
        if item["provider_symbol"] != mapping.primary_symbol or item["canonical_sector"] != mapping.sector_name:
            raise ProviderError(ProviderErrorCategory.NAME_MISMATCH, "exact THS intraday mapping conflicts with canonical mapping", retryable=False)
        return item

    def _detail(self, symbol: str) -> bytes:
        if symbol not in self._detail_cache:
            payload = self._transport(self.detail_url.format(symbol=symbol), self._timeout)
            self.request_count += 1
            if not payload:
                raise ProviderError(ProviderErrorCategory.NO_DATA, "THS exact detail page is empty", retryable=True)
            self._detail_cache[symbol] = payload
        return self._detail_cache[symbol]

    @staticmethod
    def _parse_detail(payload: bytes, *, name: str, symbol: str) -> dict[str, Decimal | str]:
        parser = _VisibleText()
        decoded = None
        for encoding in ("utf-8", "gb18030"):
            try:
                decoded = payload.decode(encoding, errors="strict")
                break
            except UnicodeDecodeError:
                continue
        if decoded is None:
            raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "THS exact detail page encoding is invalid", retryable=False)
        try:
            parser.feed(decoded)
        except ValueError as exc:
            raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "THS exact detail page markup is invalid", retryable=False) from exc
        text = re.sub(r"\s+", " ", " ".join(parser.parts))
        number = r"(-?\d+(?:\.\d+)?)"
        pattern = re.compile(
            rf"{re.escape(name)}\s*{re.escape(symbol)}\s+{number}\s+{number}\s+{number}%"
            rf"\s+今开\s+{number}\s+昨收\s+{number}\s+最低\s+{number}\s+最高\s+{number}"
            rf"\s+成交量\(万手\)\s+{number}.*?成交额\(亿\)\s+{number}",
        )
        match = pattern.search(text)
        if match is None:
            raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "THS exact detail fields are unavailable", retryable=True)
        current, change, pct, open_, pre_close, low, high, volume_wan, amount_yi = (
            Decimal(value) for value in match.groups()
        )
        return {
            "current": current, "change": change, "pct": pct, "open": open_,
            "pre_close": pre_close, "low": low, "high": high,
            "volume": volume_wan * Decimal("10000"),
            "amount": amount_yi * Decimal("100000000"),
            "text_name": name,
        }

    def fetch_intraday_snapshot(self, sector_mapping: object, as_of: datetime) -> DailyBar:
        if not isinstance(sector_mapping, SectorMapping):
            raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "sector mapping type is invalid", retryable=False)
        item = self._mapping(sector_mapping)
        symbol, name = item["provider_symbol"], item["provider_name"]
        payload = self._detail(symbol)
        values = self._parse_detail(payload, name=name, symbol=symbol)
        local_day = as_of.astimezone(ZoneInfo("Asia/Shanghai")).date()
        native_history: tuple[ProviderNativeClose, ...] = ()
        native_status, native_error = "complete", None
        try:
            cached_before = len(self._history._cache)
            bars = self._history.historical_daily_bars(
                symbol, local_day - timedelta(days=30), local_day - timedelta(days=1), Market.CN_A,
            )
            self.request_count += len(self._history._cache) - cached_before
            native_history = tuple(ProviderNativeClose(
                provider=self.provider_key, provider_symbol=symbol, trade_date=bar.trade_date,
                close=bar.close, source_payload_hash=bar.source_payload_hash,
                lineage=f"THS public q detail + d line:bk_{symbol}:01; exact canonical={name}",
            ) for bar in bars[-4:])
            if len(native_history) != 4:
                native_status, native_error = "insufficient", "fewer_than_four_closes"
        except ProviderError as exc:
            native_status, native_error = "provider_failed", exc.category.value
        digest = hashlib.sha256(payload).hexdigest()
        current = Decimal(values["current"])
        pre_close = Decimal(values["pre_close"])
        pct = Decimal(values["pct"])
        return DailyBar(
            symbol=symbol, symbol_name=name, market=Market.CN_A, trade_date=local_day,
            open=Decimal(values["open"]), high=Decimal(values["high"]), low=Decimal(values["low"]),
            close=current, pre_close=pre_close, change=current - pre_close, pct_change=pct,
            volume=Decimal(values["volume"]), amount=Decimal(values["amount"]), turnover_rate=None,
            liquidity_status=LiquidityStatus.COMPLETE, provider=self.provider_key, fetched_at=as_of,
            source_payload_hash=digest, data_status=DataStatus.NORMAL, provider_symbol=symbol,
            lineage=(
                f"THS public q detail:{symbol}:{name}; exact mapping; no login or Cookie;"
                f"mapping_type={item['mapping_type']}"
            ),
            provider_native_history=native_history,
            provider_native_history_status=native_status,
            provider_native_history_error=native_error,
        )
