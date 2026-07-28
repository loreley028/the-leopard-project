from __future__ import annotations

import hashlib
import json
import re
from http.client import RemoteDisconnected
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ..config import load_seed_bundle
from ..models import DailyBar, DataStatus, LiquidityStatus, Market, SectorMapping
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
    """Two-request board spot cache for research-only intraday display.

    It deliberately resolves only unambiguous names. A missing or ambiguous
    taxonomy match is a Provider failure, never a silent board substitution.
    """

    provider_key = "eastmoney_board_spot"
    provider_role = "research_provider"
    endpoint_role = "public_board_spot"
    endpoint = "https://push2.eastmoney.com/api/qt/clist/get"

    def __init__(self, *, transport: Transport | None = None, timeout: float = 15.0) -> None:
        self._transport = transport or _transport
        self._timeout = timeout
        self._records: dict[str, dict] | None = None
        self._records_by_kind: dict[int, dict[str, dict]] = {}
        self._digest = ""
        self.request_count = 0
        self._load_error: ProviderError | None = None

    def begin_cycle(self) -> None:
        """Expire the previous server-cycle snapshot before a new refresh."""
        self._records = None
        self._records_by_kind = {}
        self._digest = ""
        self.request_count = 0
        self._load_error = None

    def _url(self, board_type: int) -> str:
        query = urlencode({
            "pn": 1, "pz": 500, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f3",
            "fs": f"m:90+t:{board_type}",
            "fields": "f2,f3,f4,f5,f6,f12,f14,f15,f16,f17,f18",
        })
        return f"{self.endpoint}?{query}"

    def _load(self) -> None:
        if self._records is not None:
            return
        if self._load_error is not None:
            raise self._load_error
        payloads = []
        try:
            for kind in (2, 3):
                self.request_count += 1
                payloads.append(self._transport(self._url(kind), self._timeout))
        except ProviderError as exc:
            self._load_error = exc
            raise
        digest = hashlib.sha256(b"\n".join(payloads)).hexdigest()
        grouped: dict[str, list[dict]] = {}
        for kind, payload in zip((2, 3), payloads):
            grouped_for_kind: dict[str, list[dict]] = {}
            try:
                rows = json.loads(payload).get("data", {}).get("diff", [])
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as exc:
                raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "Eastmoney board response is malformed", retryable=False) from exc
            if not isinstance(rows, list):
                raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "Eastmoney board rows are missing", retryable=False)
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
        bundle = load_seed_bundle()
        kind = 2 if mapping.ths_sector_type == "行业" else 3 if mapping.ths_sector_type == "概念" else None
        records = self._records_by_kind.get(kind, self._records) if kind is not None else self._records
        candidates = [mapping.sector_name, mapping.ths_candidate_name]
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

    @staticmethod
    def _decimal(row: dict, key: str) -> Decimal | None:
        value = row.get(key)
        return None if value in (None, "-", "") else Decimal(str(value))

    def fetch_intraday_snapshot(self, sector_mapping: object, as_of: datetime) -> DailyBar:
        if not isinstance(sector_mapping, SectorMapping):
            raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "sector mapping type is invalid", retryable=False)
        if sector_mapping.primary_symbol.startswith("CUSTOM_"):
            raise ProviderError(ProviderErrorCategory.NAME_MISMATCH, "custom composite spot mapping is not approved", retryable=False)
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
        return DailyBar(
            symbol=str(row.get("f12", "")), symbol_name=str(row.get("f14", sector_mapping.sector_name)),
            market=Market.CN_A, trade_date=local_day, open=open_, high=high, low=low, close=close,
            pre_close=pre_close, change=close - pre_close, pct_change=pct, volume=volume, amount=amount,
            turnover_rate=None, liquidity_status=liquidity, provider=self.provider_key,
            fetched_at=as_of, source_payload_hash=self._digest, data_status=DataStatus.NORMAL,
        )
