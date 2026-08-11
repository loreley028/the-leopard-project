"""Read-only Tencent standard-security quote adapter.

This diagnostic provider intentionally accepts only the complete ``sh``/``sz``
security wire format.  It is not registered with sector paths, Scheduler, or
Viewer routes, and it never persists upstream payloads.
"""
from __future__ import annotations

import hashlib
import json
import re
import socket
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from http.client import RemoteDisconnected
from pathlib import Path
from typing import Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from ..config import CONFIG_DIR


Transport = Callable[[str, float], bytes]
SHANGHAI = ZoneInfo("Asia/Shanghai")
CONFIG_PATH = CONFIG_DIR / "tencent_standard_quote_provider_v1.json"


class TencentQuoteErrorCode(StrEnum):
    EMPTY_REPLY = "empty_reply"
    REMOTE_DISCONNECTED = "remote_disconnected"
    TIMEOUT = "timeout"
    DECODE_ERROR = "decode_error"
    MALFORMED_RECORD = "malformed_record"
    INSUFFICIENT_FIELDS = "insufficient_fields"
    STALE_QUOTE = "stale_quote"
    CALCULATION_INCONSISTENT = "calculation_inconsistent"


class TencentQuoteError(RuntimeError):
    def __init__(self, code: TencentQuoteErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class StandardSecurityQuote:
    """Normalized, non-persistent standard-security quote."""

    requested_symbol: str
    name: str
    symbol: str
    current: Decimal
    pre_close: Decimal
    quote_datetime: datetime
    change: Decimal
    pct_change: Decimal
    response_field_count: int
    payload_sha256: str
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    amount_yuan: Decimal | None = None


@dataclass(frozen=True)
class TencentQuoteBatch:
    quotes: tuple[StandardSecurityQuote, ...]
    failures: dict[str, TencentQuoteErrorCode]
    request_count: int


def load_tencent_quote_config(path: Path = CONFIG_PATH) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _default_transport(url: str, timeout: float) -> bytes:
    try:
        # No Cookie, token, Referer, special User-Agent, or retry is used.
        with urlopen(url, timeout=timeout) as response:
            return response.read()
    except (socket.timeout, TimeoutError) as exc:
        raise TencentQuoteError(TencentQuoteErrorCode.TIMEOUT, "Tencent quote request timed out") from exc
    except RemoteDisconnected as exc:
        raise TencentQuoteError(TencentQuoteErrorCode.REMOTE_DISCONNECTED, "Tencent quote peer disconnected") from exc
    except HTTPError as exc:
        raise TencentQuoteError(TencentQuoteErrorCode.REMOTE_DISCONNECTED, f"Tencent quote HTTP {exc.code}") from exc
    except URLError as exc:
        if isinstance(exc.reason, (socket.timeout, TimeoutError)):
            raise TencentQuoteError(TencentQuoteErrorCode.TIMEOUT, "Tencent quote request timed out") from exc
        if isinstance(exc.reason, RemoteDisconnected):
            raise TencentQuoteError(TencentQuoteErrorCode.REMOTE_DISCONNECTED, "Tencent quote peer disconnected") from exc
        raise TencentQuoteError(TencentQuoteErrorCode.REMOTE_DISCONNECTED, "Tencent quote transport failed") from exc


class TencentStandardSecurityQuoteProvider:
    """Default-disabled diagnostic adapter for complete Tencent security records."""

    provider_key = "tencent_standard_security_quote"
    provider_role = "diagnostic_provider"

    def __init__(
        self,
        *,
        transport: Transport | None = None,
        config: dict[str, object] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config or load_tencent_quote_config()
        self._transport = transport or _default_transport
        self._now = now or (lambda: datetime.now(SHANGHAI))
        request = self.config["request"]
        validation = self.config["validation"]
        self.timeout = float(request["timeout_seconds"])
        self.max_batch_size = int(request["max_batch_size"])
        self.minimum_field_count = int(validation["minimum_field_count"])
        self.price_tolerance = Decimal(str(validation["price_tolerance"]))
        self.pct_change_tolerance = Decimal(str(validation["pct_change_tolerance"]))
        self.max_quote_age_seconds = int(validation["max_quote_age_seconds"])
        self._symbol_pattern = re.compile(str(self.config["supported_symbol_pattern"]))
        self.request_count = 0

    @property
    def enabled(self) -> bool:
        return bool(self.config["enabled"])

    def _symbols(self, symbols: Iterable[str]) -> tuple[str, ...]:
        deduplicated = tuple(dict.fromkeys(str(symbol).lower() for symbol in symbols))
        if not deduplicated:
            raise ValueError("at least one security symbol is required")
        if len(deduplicated) > self.max_batch_size:
            raise ValueError(f"batch exceeds configured maximum of {self.max_batch_size}")
        if any(not self._symbol_pattern.fullmatch(symbol) for symbol in deduplicated):
            raise ValueError("only complete shXXXXXX and szXXXXXX securities are supported")
        return deduplicated

    def _url(self, symbols: tuple[str, ...]) -> str:
        # Deliberately emits only the validated complete symbol form.
        return str(self.config["endpoint_template"]).format(symbols=",".join(symbols))

    @staticmethod
    def _records(text: str) -> dict[str, tuple[str, ...]]:
        records: dict[str, tuple[str, ...]] = {}
        for item in text.split(";"):
            item = item.strip()
            if not item:
                continue
            match = re.fullmatch(r'v_([a-z]{2}\d{6})="(.*)"', item)
            if match is None:
                continue
            records[match.group(1).lower()] = tuple(match.group(2).split("~"))
        return records

    @staticmethod
    def _decimal(value: str, field: str) -> Decimal:
        try:
            decimal = Decimal(value)
        except (InvalidOperation, ValueError) as exc:
            raise TencentQuoteError(TencentQuoteErrorCode.MALFORMED_RECORD, f"Tencent {field} is not numeric") from exc
        if not decimal.is_finite():
            raise TencentQuoteError(TencentQuoteErrorCode.MALFORMED_RECORD, f"Tencent {field} is not finite")
        return decimal

    def _parse_record(self, requested_symbol: str, fields: tuple[str, ...], payload_sha256: str) -> StandardSecurityQuote:
        if len(fields) < self.minimum_field_count:
            raise TencentQuoteError(TencentQuoteErrorCode.INSUFFICIENT_FIELDS, "Tencent record has fewer than 33 fields")
        contract = self.config["field_contract"]
        name = fields[int(contract["name_index"])]
        symbol = fields[int(contract["symbol_index"])]
        if not name or not symbol or symbol != requested_symbol[2:]:
            raise TencentQuoteError(TencentQuoteErrorCode.MALFORMED_RECORD, "Tencent symbol does not match the requested security")
        current = self._decimal(fields[int(contract["current_index"])], "current")
        pre_close = self._decimal(fields[int(contract["pre_close_index"])], "pre_close")
        change = self._decimal(fields[int(contract["change_index"])], "change")
        pct_change = self._decimal(fields[int(contract["pct_change_index"])], "pct_change")
        if current <= 0 or pre_close <= 0:
            raise TencentQuoteError(TencentQuoteErrorCode.MALFORMED_RECORD, "Tencent current or pre-close is not positive")
        try:
            quote_datetime = datetime.strptime(fields[int(contract["quote_datetime_index"])], "%Y%m%d%H%M%S").replace(tzinfo=SHANGHAI)
        except ValueError as exc:
            raise TencentQuoteError(TencentQuoteErrorCode.MALFORMED_RECORD, "Tencent quote timestamp is invalid") from exc
        if abs((current - pre_close) - change) > self.price_tolerance or abs(((current / pre_close - Decimal("1")) * Decimal("100")) - pct_change) > self.pct_change_tolerance:
            raise TencentQuoteError(TencentQuoteErrorCode.CALCULATION_INCONSISTENT, "Tencent quote arithmetic is inconsistent")
        p35 = fields[35].split("/") if len(fields) > 35 and fields[35] else []
        if p35:
            component_price = self._decimal(p35[0], "p35_price")
            if abs(component_price - current) > self.price_tolerance:
                raise TencentQuoteError(TencentQuoteErrorCode.CALCULATION_INCONSISTENT, "Tencent p35 price differs from current")

        def optional_positive(index_name: str, label: str) -> Decimal | None:
            try:
                value = self._decimal(fields[int(contract[index_name])], label)
            except (IndexError, KeyError, TencentQuoteError):
                return None
            return value if value > 0 else None

        open_ = optional_positive("open_index", "open")
        high = optional_positive("high_index", "high")
        low = optional_positive("low_index", "low")
        if open_ is not None and high is not None and low is not None and not (low <= open_ <= high and low <= current <= high):
            open_ = high = low = None
        amount_yuan: Decimal | None = None
        if len(p35) == 3:
            try:
                candidate = self._decimal(p35[2], "amount_yuan")
                amount_yuan = candidate if candidate >= 0 else None
            except TencentQuoteError:
                amount_yuan = None
        age = (self._now().astimezone(SHANGHAI) - quote_datetime).total_seconds()
        if age > self.max_quote_age_seconds or age < -self.max_quote_age_seconds:
            raise TencentQuoteError(TencentQuoteErrorCode.STALE_QUOTE, "Tencent quote timestamp is stale")
        return StandardSecurityQuote(
            requested_symbol=requested_symbol, name=name, symbol=symbol, current=current, pre_close=pre_close,
            quote_datetime=quote_datetime, change=change, pct_change=pct_change,
            response_field_count=len(fields), payload_sha256=payload_sha256,
            open=open_, high=high, low=low, amount_yuan=amount_yuan,
        )

    def fetch_batch(self, symbols: Iterable[str], *, allow_network: bool = False) -> TencentQuoteBatch:
        if not self.enabled and not allow_network:
            raise PermissionError("Tencent standard-security Provider is disabled; explicit diagnostic authorization is required")
        requested = self._symbols(symbols)
        self.request_count = 0
        payload = self._transport(self._url(requested), self.timeout)
        self.request_count = 1
        if not payload:
            return TencentQuoteBatch((), {symbol: TencentQuoteErrorCode.EMPTY_REPLY for symbol in requested}, self.request_count)
        try:
            decoded = payload.decode("gbk", errors="strict")
        except UnicodeDecodeError:
            return TencentQuoteBatch((), {symbol: TencentQuoteErrorCode.DECODE_ERROR for symbol in requested}, self.request_count)
        records = self._records(decoded)
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        quotes: list[StandardSecurityQuote] = []
        failures: dict[str, TencentQuoteErrorCode] = {}
        for symbol in requested:
            fields = records.get(symbol)
            if fields is None:
                failures[symbol] = TencentQuoteErrorCode.MALFORMED_RECORD
                continue
            try:
                quotes.append(self._parse_record(symbol, fields, payload_sha256))
            except TencentQuoteError as exc:
                failures[symbol] = exc.code
        return TencentQuoteBatch(tuple(quotes), failures, self.request_count)
