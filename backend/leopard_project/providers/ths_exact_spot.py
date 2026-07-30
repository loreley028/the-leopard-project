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


def _exact_mappings() -> dict[str, dict]:
    output: dict[str, dict] = {}
    for sector_key, capability in load_provider_capabilities().items():
        for candidate in capability.selectable_candidates:
            if candidate.provider == "ths_exact_spot":
                output[sector_key] = {
                    "sector_key": sector_key,
                    "canonical_sector": capability.display_name,
                    "provider_symbol": candidate.symbol,
                    "provider_name": candidate.provider_name,
                    "mapping_type": candidate.mapping_type,
                    "components": candidate.components,
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

    def _mapping(self, mapping: SectorMapping) -> dict:
        item = self._mappings.get(mapping.sector_key)
        if item is None:
            raise ProviderError(ProviderErrorCategory.INVALID_SYMBOL, "exact THS intraday mapping is unavailable", retryable=False)
        if item["provider_symbol"] != mapping.primary_symbol or item["canonical_sector"] != mapping.sector_name:
            raise ProviderError(ProviderErrorCategory.NAME_MISMATCH, "exact THS intraday mapping conflicts with canonical mapping", retryable=False)
        return item

    def _component(self, symbol: str, name: str, local_day: date) -> tuple[dict, tuple[DailyBar, ...], bytes]:
        payload = self._detail(symbol)
        values = self._parse_detail(payload, name=name, symbol=symbol)
        cached_before = len(self._history._cache)
        bars = tuple(self._history.historical_daily_bars(
            symbol, local_day - timedelta(days=30), local_day - timedelta(days=1), Market.CN_A,
        ))
        self.request_count += len(self._history._cache) - cached_before
        if len(bars) < 4:
            raise ProviderError(ProviderErrorCategory.NO_DATA, "same-source composite history is insufficient", retryable=True)
        return values, bars[-4:], payload

    def _composite_snapshot(self, item: dict, as_of: datetime) -> DailyBar:
        local_day = as_of.astimezone(ZoneInfo("Asia/Shanghai")).date()
        components = tuple(item.get("components") or ())
        if not components or abs(sum(Decimal(str(row["weight"])) for row in components) - Decimal("1")) > Decimal("0.000001"):
            raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "composite weights are invalid", retryable=False)
        fetched = [
            (*self._component(str(row["symbol"]), str(row["provider_name"]), local_day), Decimal(str(row["weight"])), row)
            for row in components
        ]
        dates = [tuple(bar.trade_date for bar in bars) for _, bars, _, _, _ in fetched]
        if not dates or any(value != dates[0] for value in dates[1:]):
            raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "composite history dates do not align", retryable=False)
        synthetic = Decimal("1000")
        native: list[ProviderNativeClose] = []
        for index, trade_day in enumerate(dates[0]):
            weighted_return = sum((
                (bars[index].close / bars[index].pre_close - Decimal("1")) * weight
                for _, bars, _, weight, _ in fetched
            ), Decimal("0"))
            synthetic *= Decimal("1") + weighted_return
            digest = hashlib.sha256(":".join(bars[index].source_payload_hash for _, bars, _, _, _ in fetched).encode()).hexdigest()
            native.append(ProviderNativeClose(
                provider=self.provider_key, provider_symbol=item["provider_symbol"], trade_date=trade_day,
                close=synthetic, source_payload_hash=digest,
                lineage=";".join(f"component={row['symbol']}:{row['provider_name']}:weight={weight}" for _, _, _, weight, row in fetched),
            ))
        current_return = sum((
            (Decimal(values["current"]) / Decimal(values["pre_close"]) - Decimal("1")) * weight
            for values, _, _, weight, _ in fetched
        ), Decimal("0"))
        pre_close = native[-1].close
        current = pre_close * (Decimal("1") + current_return)

        def weighted_ratio(field: str) -> Decimal:
            return sum((Decimal(values[field]) / Decimal(values["pre_close"]) * weight for values, _, _, weight, _ in fetched), Decimal("0"))

        volume = sum((Decimal(values["volume"]) for values, _, _, _, _ in fetched), Decimal("0"))
        amount = sum((Decimal(values["amount"]) for values, _, _, _, _ in fetched), Decimal("0"))
        payload_hash = hashlib.sha256(":".join(hashlib.sha256(payload).hexdigest() for _, _, payload, _, _ in fetched).encode()).hexdigest()
        component_lineage = ",".join(f"{row['symbol']}:{row['provider_name']}:{weight}" for _, _, _, weight, row in fetched)
        return DailyBar(
            symbol=item["provider_symbol"], symbol_name=item["canonical_sector"], market=Market.CN_A,
            trade_date=local_day, open=pre_close * weighted_ratio("open"), high=pre_close * weighted_ratio("high"),
            low=pre_close * weighted_ratio("low"), close=current, pre_close=pre_close,
            change=current - pre_close, pct_change=current_return * Decimal("100"), volume=volume, amount=amount,
            turnover_rate=None, liquidity_status=LiquidityStatus.COMPLETE, provider=self.provider_key,
            fetched_at=as_of, source_payload_hash=payload_hash, data_status=DataStatus.NORMAL,
            provider_symbol=item["provider_symbol"],
            lineage=f"THS exact weighted composite;components={component_lineage};mapping_type=composite;fail_closed=true",
            provider_native_history=tuple(native), provider_native_history_status="complete",
        )

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
        if item["mapping_type"] == "composite":
            return self._composite_snapshot(item, as_of)
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
            source_payload_hash=digest,
            data_status=DataStatus.PROXY if item["mapping_type"] == "proxy" else DataStatus.NORMAL,
            provider_symbol=symbol,
            lineage=(
                f"THS public q detail:{symbol}:{name}; exact mapping; no login or Cookie;"
                f"canonical_market_path={item['sector_key']};provider_name={name};provider_symbol={symbol};"
                f"mapping_type={item['mapping_type']};"
                f"semantic_difference={'tourism_and_hotel_is_broader_than_hotel' if item['mapping_type'] == 'proxy' else 'none'};"
                "same_provider_same_symbol=true"
            ),
            provider_native_history=native_history,
            provider_native_history_status=native_status,
            provider_native_history_error=native_error,
        )
