from __future__ import annotations

import hashlib
import json
import re
import time
from http.client import RemoteDisconnected
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ..config import load_seed_bundle
from ..models import DailyBar, DataStatus, LiquidityStatus, Market, ProviderNativeClose, SectorMapping
from .base import ProviderError, ProviderErrorCategory


Transport = Callable[[str, float], bytes]


def _transport(url: str, timeout: float) -> bytes:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 The-Leopard-Project research validation"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        category = ProviderErrorCategory.RATE_LIMIT if exc.code == 429 else ProviderErrorCategory.NETWORK
        raise ProviderError(category, f"Eastmoney HTTP {exc.code}", retryable=exc.code == 429 or exc.code >= 500) from exc
    except (URLError, TimeoutError, RemoteDisconnected, ConnectionError) as exc:
        raise ProviderError(ProviderErrorCategory.NETWORK, "Eastmoney spot request failed", retryable=True) from exc


def _name(value: str) -> str:
    return re.sub(r"[\s/／、·_-]+", "", value).lower()


class EastmoneyBoardSpotProvider:
    """Paginated board spot cache for research-only intraday display.

    It deliberately resolves only unambiguous names. A missing or ambiguous
    taxonomy match is a Provider failure, never a silent board substitution.
    """

    provider_key = "eastmoney_board_spot"
    provider_role = "research_provider"
    endpoint_role = "public_board_spot"
    endpoint = "https://push2.eastmoney.com/api/qt/clist/get"
    history_endpoint = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    page_size = 100
    max_pages = 8
    component_candidates = {
        "881134": (2, ("食品加工制造", "食品加工")),
        "881133": (2, ("饮料制造", "饮料乳品")),
        "881279": (2, ("光伏设备",)),
        "885921": (3, ("储能", "储能概念")),
        "881180": (2, ("石油加工贸易", "炼化及贸易")),
        "881107": (2, ("油气开采及服务", "油服工程")),
        "881160": (2, ("酒店餐饮",)),
    }
    # Explicit cross-provider spelling/level translations. These retain the
    # canonical THS mapping and are recorded in lineage; broader substitutes
    # such as 算力概念 for 算力租赁 are deliberately excluded.
    provider_name_candidates = {
        "cpo": ("CPO概念",),
        "liquid_cooling": ("液冷概念",),
        "gaming": ("游戏Ⅱ",),
        "it_services": ("IT服务Ⅱ",),
        "baijiu": ("白酒Ⅱ",),
        "traditional_chinese_medicine": ("中药Ⅱ",),
        "securities": ("证券Ⅱ",),
        "insurance": ("保险Ⅱ",),
        "aerospace_equipment": ("航天装备Ⅱ",),
        "port_shipping": ("航运港口",),
    }

    def __init__(
        self, *, transport: Transport | None = None, timeout: float = 15.0,
        minimum_history_interval: float | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._transport = transport or _transport
        self._timeout = timeout
        self._records: dict[str, dict] | None = None
        self._records_by_kind: dict[int, dict[str, dict]] = {}
        self._digest = ""
        self.request_count = 0
        self._load_error: ProviderError | None = None
        self._history_cache: dict[tuple[str, date], tuple[ProviderNativeClose, ...]] = {}
        # The public history endpoint starts dropping requests under a short
        # burst. Production transport is deliberately slower; deterministic
        # injected transports remain delay-free unless a test asks otherwise.
        self._minimum_history_interval = (
            0.45 if minimum_history_interval is None and transport is None
            else 0.0 if minimum_history_interval is None
            else minimum_history_interval
        )
        self._clock = clock
        self._sleeper = sleeper
        self._last_history_request_at: float | None = None

    def begin_cycle(self) -> None:
        """Expire the previous server-cycle snapshot before a new refresh."""
        self._records = None
        self._records_by_kind = {}
        self._digest = ""
        self.request_count = 0
        self._load_error = None

    def _url(self, board_type: int, page: int = 1) -> str:
        query = urlencode({
            "pn": page, "pz": self.page_size, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f3",
            "fs": f"m:90+t:{board_type}",
            "fields": "f2,f3,f4,f5,f6,f12,f14,f15,f16,f17,f18",
        })
        return f"{self.endpoint}?{query}"

    def _history_url(self, symbol: str, as_of: date) -> str:
        query = urlencode({
            "secid": f"90.{symbol}", "klt": 101, "fqt": 0,
            "beg": (as_of - timedelta(days=30)).strftime("%Y%m%d"),
            "end": as_of.strftime("%Y%m%d"),
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        })
        return f"{self.history_endpoint}?{query}"

    def _native_history(self, symbol: str, as_of: date) -> tuple[ProviderNativeClose, ...]:
        key = (symbol, as_of)
        if key in self._history_cache:
            return self._history_cache[key]
        now = self._clock()
        if self._last_history_request_at is not None:
            wait = self._minimum_history_interval - (now - self._last_history_request_at)
            if wait > 0:
                self._sleeper(wait)
        payload = self._transport(self._history_url(symbol, as_of), self._timeout)
        self._last_history_request_at = self._clock()
        self.request_count += 1
        try:
            document = json.loads(payload)
            data = document.get("data") or {}
            rows = data.get("klines") or []
            response_symbol = str(data.get("code") or symbol)
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as exc:
            raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "Eastmoney native history is malformed", retryable=False) from exc
        if response_symbol.upper() != symbol.upper() or not isinstance(rows, list):
            raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "Eastmoney native history symbol mismatch", retryable=False)
        digest = hashlib.sha256(payload).hexdigest()
        parsed: list[ProviderNativeClose] = []
        try:
            for row in rows:
                fields = str(row).split(",")
                day = date.fromisoformat(fields[0])
                close = Decimal(fields[2])
                if day <= as_of and close > 0:
                    parsed.append(ProviderNativeClose(
                        provider=self.provider_key, provider_symbol=symbol,
                        trade_date=day, close=close, source_payload_hash=digest,
                        lineage=f"Eastmoney public push2his:90.{symbol}:klt101:fqt0",
                    ))
        except (IndexError, ValueError, ArithmeticError) as exc:
            raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "Eastmoney native history row is malformed", retryable=False) from exc
        ordered = tuple(sorted(parsed, key=lambda item: item.trade_date))
        if len({item.trade_date for item in ordered}) != len(ordered):
            raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "Eastmoney native history has duplicate dates", retryable=False)
        if len(ordered) < 4:
            raise ProviderError(ProviderErrorCategory.NO_DATA, "Eastmoney native history has fewer than four closes", retryable=True)
        self._history_cache[key] = ordered[-4:]
        return self._history_cache[key]

    def _safe_native_history(self, symbol: str, as_of: date) -> tuple[tuple[ProviderNativeClose, ...], str, str | None]:
        for attempt in range(3):
            try:
                return self._native_history(symbol, as_of), "complete", None
            except ProviderError as exc:
                if not exc.retryable or attempt == 2:
                    return (), "provider_failed", exc.category.value
                self._sleeper(0.75 * (2 ** attempt))
            except Exception:
                return (), "provider_failed", "provider_error"
        return (), "provider_failed", "provider_error"

    def _load(self) -> None:
        if self._records is not None:
            return
        if self._load_error is not None:
            raise self._load_error
        payloads_by_kind: dict[int, list[bytes]] = {2: [], 3: []}
        try:
            for kind in (2, 3):
                kind_payloads: list[bytes] = []
                seen_codes: set[str] = set()
                total: int | None = None
                for page in range(1, self.max_pages + 1):
                    self.request_count += 1
                    payload = self._transport(self._url(kind, page), self._timeout)
                    try:
                        document = json.loads(payload)
                        rows = document.get("data", {}).get("diff", [])
                        raw_total = document.get("data", {}).get("total")
                        total = int(raw_total) if raw_total is not None else total
                    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, TypeError, ValueError) as exc:
                        raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "Eastmoney board response is malformed", retryable=False) from exc
                    if not isinstance(rows, list):
                        raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "Eastmoney board rows are missing", retryable=False)
                    page_codes = {str(row.get("f12")) for row in rows if isinstance(row, dict) and row.get("f12")}
                    if not rows or page_codes <= seen_codes:
                        break
                    kind_payloads.append(payload)
                    seen_codes.update(page_codes)
                    if (total is not None and len(seen_codes) >= total) or len(rows) < self.page_size:
                        break
                payloads_by_kind[kind].extend(kind_payloads)
                self._records_by_kind[kind] = {}
        except ProviderError as exc:
            self._load_error = exc
            raise
        digest = hashlib.sha256(b"\n".join(payload for kind in (2, 3) for payload in payloads_by_kind[kind])).hexdigest()
        grouped: dict[str, list[dict]] = {}
        for kind in (2, 3):
            grouped_for_kind: dict[str, list[dict]] = {}
            for payload in payloads_by_kind[kind]:
                document = json.loads(payload)
                rows = document.get("data", {}).get("diff", [])
                for row in rows:
                    if not isinstance(row, dict) or not row.get("f14"):
                        continue
                    grouped.setdefault(_name(str(row["f14"])), []).append(row)
                    grouped_for_kind.setdefault(_name(str(row["f14"])), []).append(row)
            self._records_by_kind[kind] = {key: values[0] for key, values in grouped_for_kind.items() if len(values) == 1}
        self._records = {key: values[0] for key, values in grouped.items() if len(values) == 1}
        self._digest = digest

    def _resolve(self, mapping: SectorMapping) -> dict:
        self._load()
        assert self._records is not None
        if mapping.primary_symbol.upper().startswith("BK"):
            exact = {
                str(row.get("f12")): row
                for rows in self._records_by_kind.values()
                for row in rows.values()
                if isinstance(row, dict) and row.get("f12")
            }.get(mapping.primary_symbol)
            if exact is None:
                raise ProviderError(
                    ProviderErrorCategory.INVALID_SYMBOL,
                    f"explicit Eastmoney board symbol unavailable: {mapping.primary_symbol}",
                    retryable=False,
                )
            return exact
        bundle = load_seed_bundle()
        kind = 2 if mapping.ths_sector_type == "行业" else 3 if mapping.ths_sector_type == "概念" else None
        records = self._records_by_kind.get(kind, self._records) if kind is not None else self._records
        candidates = [mapping.sector_name, mapping.ths_candidate_name]
        candidates.extend(self.provider_name_candidates.get(mapping.sector_key, ()))
        candidates.extend(alias.alias for alias in bundle.aliases if alias.confirmed and alias.sector_key == mapping.sector_key)
        if mapping.sector_key == "hotel_catering":
            candidates.insert(0, "旅游酒店")
        for candidate in candidates:
            row = records.get(_name(candidate))
            if row is not None:
                return row
        raise ProviderError(
            ProviderErrorCategory.NAME_MISMATCH,
            f"no unambiguous Eastmoney board mapping for {mapping.sector_name}",
            retryable=False,
        )

    def _resolve_component(self, symbol: str) -> dict:
        self._load()
        kind, candidates = self.component_candidates[symbol]
        records = self._records_by_kind.get(kind, {})
        for candidate in candidates:
            row = records.get(_name(candidate))
            if row is not None:
                return row
        raise ProviderError(ProviderErrorCategory.NAME_MISMATCH, f"no Eastmoney component mapping for {symbol}", retryable=False)

    def _composite(self, mapping: SectorMapping, as_of: datetime) -> DailyBar:
        symbols = ("881160",) if mapping.sector_key == "hotel_catering" else mapping.backup_symbols
        rows = [self._resolve_component(symbol) for symbol in symbols]
        if not rows:
            raise ProviderError(ProviderErrorCategory.NO_DATA, "custom composite has no components", retryable=False)
        weight = Decimal("1") / Decimal(len(rows))
        pre_close = Decimal("1000")
        def normalized(field: str) -> Decimal:
            values = [(self._decimal(row, field), self._decimal(row, "f18")) for row in rows]
            if any(value is None or previous in (None, Decimal("0")) for value, previous in values):
                raise ProviderError(ProviderErrorCategory.NO_DATA, f"custom composite component lacks {field}", retryable=True)
            return pre_close * sum((value / previous) * weight for value, previous in values if value is not None and previous is not None)
        close, open_, high, low = (normalized(field) for field in ("f2", "f17", "f15", "f16"))
        pct = (close / pre_close - Decimal("1")) * Decimal("100")
        volumes = [self._decimal(row, "f5") for row in rows]
        amounts = [self._decimal(row, "f6") for row in rows]
        volume = sum((value or Decimal("0")) * weight for value in volumes) if all(value is not None for value in volumes) else None
        amount = sum((value or Decimal("0")) * weight for value in amounts) if all(value is not None for value in amounts) else None
        local_day = as_of.astimezone(ZoneInfo("Asia/Shanghai")).date() if as_of.tzinfo else date.today()
        provider_symbols = "+".join(str(row.get("f12", "")) for row in rows)
        lineage = "Eastmoney public push2 composite:" + "+".join(f"{symbol}->{row.get('f12')}" for symbol, row in zip(symbols, rows))
        if mapping.sector_key == "hotel_catering":
            lineage = (
                f"canonical_sector={mapping.sector_name};mapping_type=proxy;proxy_symbol=881160;"
                f"provider={self.provider_key};provider_symbol={rows[0].get('f12')};"
                f"provider_name={rows[0].get('f14')};rationale=881160 temporary proxy;"
                f"as_of={as_of.isoformat()};source_status=available"
            )
        history_results = [
            self._safe_native_history(str(row.get("f12", "")), local_day - timedelta(days=1))
            for row in rows
        ]
        component_histories = [item[0] for item in history_results]
        native_history: tuple[ProviderNativeClose, ...] = ()
        native_status = "provider_failed" if any(item[1] != "complete" for item in history_results) else "complete"
        native_error = next((item[2] for item in history_results if item[2]), None)
        if native_status == "complete":
            common_days = sorted(set.intersection(*(set(item.trade_date for item in history) for history in component_histories)))
            if len(common_days) >= 4:
                selected_days = common_days[-4:]
                latest_values = [{item.trade_date: item.close for item in history} for history in component_histories]
                native_digest = hashlib.sha256(
                    "|".join(item.source_payload_hash for history in component_histories for item in history).encode()
                ).hexdigest()
                native_history = tuple(ProviderNativeClose(
                    provider=self.provider_key,
                    provider_symbol=provider_symbols,
                    trade_date=day,
                    close=pre_close * sum(
                        (values[day] / values[selected_days[-1]]) * weight for values in latest_values
                    ),
                    source_payload_hash=native_digest,
                    lineage=f"{lineage}; native synthetic history; weights={weight}",
                ) for day in selected_days)
            else:
                native_status, native_error = "insufficient", "insufficient_common_dates"
        return DailyBar(
            symbol=mapping.primary_symbol, symbol_name=mapping.sector_name, market=Market.CN_A,
            trade_date=local_day, open=open_, high=high, low=low, close=close, pre_close=pre_close,
            change=close - pre_close, pct_change=pct, volume=volume, amount=amount, turnover_rate=None,
            liquidity_status=LiquidityStatus.COMPLETE if volume is not None and amount is not None else LiquidityStatus.PARTIAL,
            provider=self.provider_key, fetched_at=as_of, source_payload_hash=self._digest,
            data_status=DataStatus.PROXY if mapping.sector_key == "hotel_catering" else DataStatus.NORMAL,
            provider_symbol=provider_symbols, lineage=lineage,
            provider_native_history=native_history,
            provider_native_history_status=native_status,
            provider_native_history_error=native_error,
        )

    @staticmethod
    def _decimal(row: dict, key: str) -> Decimal | None:
        value = row.get(key)
        return None if value in (None, "-", "") else Decimal(str(value))

    def fetch_intraday_snapshot(self, sector_mapping: object, as_of: datetime) -> DailyBar:
        if not isinstance(sector_mapping, SectorMapping):
            raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "sector mapping type is invalid", retryable=False)
        if sector_mapping.primary_symbol.startswith("CUSTOM_"):
            return self._composite(sector_mapping, as_of)
        row = self._resolve(sector_mapping)
        close = self._decimal(row, "f2")
        pre_close = self._decimal(row, "f18")
        open_ = self._decimal(row, "f17")
        high = self._decimal(row, "f15")
        low = self._decimal(row, "f16")
        pct = self._decimal(row, "f3")
        if None in {close, pre_close, open_, high, low, pct} or close == 0 or pre_close == 0:
            raise ProviderError(ProviderErrorCategory.NO_DATA, "Eastmoney spot row has no usable quote", retryable=True)
        volume, amount = self._decimal(row, "f5"), self._decimal(row, "f6")
        liquidity = LiquidityStatus.COMPLETE if volume is not None and amount is not None else LiquidityStatus.PARTIAL
        local_day = as_of.astimezone(ZoneInfo("Asia/Shanghai")).date() if as_of.tzinfo else date.today()
        provider_symbol = str(row.get("f12", ""))
        native_history, native_status, native_error = self._safe_native_history(
            provider_symbol, local_day - timedelta(days=1)
        )
        return DailyBar(
            symbol=str(row.get("f12", "")), symbol_name=str(row.get("f14", sector_mapping.sector_name)),
            market=Market.CN_A, trade_date=local_day, open=open_, high=high, low=low, close=close,
            pre_close=pre_close, change=close - pre_close, pct_change=pct, volume=volume, amount=amount,
            turnover_rate=None, liquidity_status=liquidity, provider=self.provider_key,
            fetched_at=as_of, source_payload_hash=self._digest, data_status=DataStatus.NORMAL,
            provider_symbol=provider_symbol,
            lineage=(
                f"Eastmoney public push2:m90:t{2 if sector_mapping.ths_sector_type == '行业' else 3}:"
                f"{row.get('f12', '')}:{row.get('f14', '')}; canonical={sector_mapping.sector_name}"
            ),
            provider_native_history=native_history,
            provider_native_history_status=native_status,
            provider_native_history_error=native_error,
        )
