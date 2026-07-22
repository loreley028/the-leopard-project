from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Callable, Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..models import DailyBar, DataStatus, LiquidityStatus, Market
from .base import MarketDataProvider, ProviderError, ProviderErrorCategory, SymbolValidation
from .policy import provider_symbol


Transport = Callable[[str, float], bytes]
_CALLBACK = re.compile(rb"^[^(]+\((.*)\)\s*$", re.DOTALL)


def _default_transport(url: str, timeout: float) -> bytes:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 Phase-1A validation (low-rate)"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        if exc.code == 429:
            raise ProviderError(ProviderErrorCategory.RATE_LIMIT, "provider rate limited request", retryable=True) from exc
        if exc.code == 404:
            raise ProviderError(ProviderErrorCategory.INVALID_SYMBOL, "provider returned HTTP 404", retryable=False) from exc
        raise ProviderError(ProviderErrorCategory.NETWORK, f"provider returned HTTP {exc.code}", retryable=500 <= exc.code) from exc
    except TimeoutError as exc:
        raise ProviderError(ProviderErrorCategory.TIMEOUT, "provider request timed out", retryable=True) from exc
    except URLError as exc:
        category = ProviderErrorCategory.TIMEOUT if isinstance(exc.reason, TimeoutError) else ProviderErrorCategory.NETWORK
        raise ProviderError(category, "provider network request failed", retryable=True) from exc


def _unwrap(payload: bytes) -> tuple[dict[str, object], str]:
    digest = hashlib.sha256(payload).hexdigest()
    match = _CALLBACK.match(payload.strip())
    if not match:
        raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "response is not a JSON callback", retryable=False)
    try:
        return json.loads(match.group(1)), digest
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "callback JSON is malformed", retryable=False) from exc


class ThsPublicValidationProvider(MarketDataProvider):
    """Low-rate validation adapter for public THS chart responses.

    This adapter is deliberately marked validation-only. It avoids tokens and
    credentials, caches identical requests, and never retries automatically.
    Production use requires a licensed, documented provider contract.
    """

    provider_key = "ths_public_validation"
    board_url = "https://d.10jqka.com.cn/v4/line/bk_{symbol}/01/{year}.js"
    hk_url = "https://d.10jqka.com.cn/v6/line/176_HS2083/01/all.js"

    def __init__(
        self,
        *,
        transport: Transport | None = None,
        timeout: float = 20.0,
        minimum_interval: float = 0.35,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        fetched_at: Callable[[], datetime] | None = None,
    ) -> None:
        self._transport = transport or _default_transport
        self._timeout = timeout
        self._minimum_interval = minimum_interval
        self._clock = clock
        self._sleeper = sleeper
        self._fetched_at = fetched_at or (lambda: datetime.now(UTC))
        self._cache: dict[str, bytes] = {}
        self._last_request_at: float | None = None
        self._calendars: dict[Market, set[date]] = {Market.CN_A: set(), Market.HK: set()}

    def _get(self, url: str) -> bytes:
        if url in self._cache:
            return self._cache[url]
        now = self._clock()
        if self._last_request_at is not None:
            wait = self._minimum_interval - (now - self._last_request_at)
            if wait > 0:
                self._sleeper(wait)
        payload = self._transport(url, self._timeout)
        self._last_request_at = self._clock()
        if not payload:
            raise ProviderError(ProviderErrorCategory.NO_DATA, "provider returned an empty response", retryable=False)
        self._cache[url] = payload
        return payload

    def trading_calendar(self, start: date, end: date, market: Market) -> Sequence[date]:
        return tuple(sorted(day for day in self._calendars[market] if start <= day <= end))

    def validate_symbol(self, symbol: str, market: Market) -> SymbolValidation:
        try:
            end = date.today()
            start = date(end.year, 1, 1)
            valid = bool(self.historical_daily_bars(symbol, start, end, market))
            return SymbolValidation(symbol, valid, market, self.provider_key, None if valid else "no rows")
        except ProviderError as exc:
            return SymbolValidation(symbol, False, market, self.provider_key, f"{exc.category}: {exc}")

    def historical_daily_bars(self, symbol: str, start: date, end: date, market: Market) -> Sequence[DailyBar]:
        if market == Market.HK:
            if symbol not in {"HS2083", "HSTECH"}:
                raise ProviderError(ProviderErrorCategory.INVALID_SYMBOL, "only HS2083/HSTECH is supported for HK validation", retryable=False)
            if provider_symbol("HSTECH", self.provider_key) != "HS2083":
                raise ProviderError(ProviderErrorCategory.PROVIDER_UNAVAILABLE, "HSTECH provider mapping is invalid", retryable=False)
            document, digest = _unwrap(self._get(self.hk_url))
            bars = self._parse_hstech(document, digest)
        else:
            if not re.fullmatch(r"88\d{4}", symbol):
                raise ProviderError(ProviderErrorCategory.INVALID_SYMBOL, "THS board symbol must be six digits beginning with 88", retryable=False)
            bars: list[DailyBar] = []
            for year in range(start.year, end.year + 1):
                document, digest = _unwrap(self._get(self.board_url.format(symbol=symbol, year=year)))
                bars.extend(self._parse_board(symbol, document, digest))
        selected = tuple(bar for bar in bars if start <= bar.trade_date <= end)
        self._calendars[market].update(bar.trade_date for bar in selected)
        return selected

    def bars_for_date(self, symbols: Iterable[str], trade_date: date, market: Market) -> Sequence[DailyBar]:
        result: list[DailyBar] = []
        for symbol in symbols:
            result.extend(self.historical_daily_bars(symbol, trade_date, trade_date, market))
        return tuple(result)

    def normalize_bar(self, raw: Mapping[str, object], market: Market) -> DailyBar:
        try:
            close = Decimal(str(raw["close"]))
            pre_close = Decimal(str(raw["pre_close"]))
            change = close - pre_close
            pct_change = change / pre_close * Decimal("100") if pre_close else Decimal("0")
            volume = None if raw.get("volume") in (None, "") else Decimal(str(raw["volume"]))
            amount = None if raw.get("amount") in (None, "") else Decimal(str(raw["amount"]))
            turnover_rate = None if raw.get("turnover_rate") in (None, "") else Decimal(str(raw["turnover_rate"]))
            liquidity_status = (
                LiquidityStatus.COMPLETE if volume is not None and amount is not None
                else LiquidityStatus.PARTIAL if any(value is not None for value in (volume, turnover_rate, amount))
                else LiquidityStatus.UNAVAILABLE
            )
            return DailyBar(
                symbol=str(raw["symbol"]), symbol_name=str(raw["symbol_name"]), market=market,
                trade_date=date.fromisoformat(str(raw["trade_date"])), open=Decimal(str(raw["open"])),
                high=Decimal(str(raw["high"])), low=Decimal(str(raw["low"])), close=close,
                pre_close=pre_close, change=change, pct_change=pct_change,
                volume=volume,
                turnover_rate=turnover_rate,
                amount=amount, liquidity_status=liquidity_status,
                provider=self.provider_key, fetched_at=raw.get("fetched_at", self._fetched_at()),
                source_payload_hash=str(raw["source_payload_hash"]),
                data_status=DataStatus(str(raw.get("data_status", DataStatus.NORMAL))),
            )
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "bar row cannot be normalized", retryable=False) from exc

    def _parse_board(self, symbol: str, document: Mapping[str, object], digest: str) -> list[DailyBar]:
        data = document.get("data")
        if not isinstance(data, str) or not data:
            raise ProviderError(ProviderErrorCategory.NO_DATA, "board response contains no data", retryable=False)
        parsed: list[tuple[date, list[str]]] = []
        for row in data.split(";"):
            fields = row.split(",")
            if len(fields) < 7:
                raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "board row has fewer than seven fields", retryable=False)
            parsed.append((datetime.strptime(fields[0], "%Y%m%d").date(), fields))
        parsed.sort(key=lambda item: item[0])
        if len({day for day, _ in parsed}) != len(parsed):
            raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "board response contains duplicate dates", retryable=False)
        result: list[DailyBar] = []
        previous: Decimal | None = None
        for day, fields in parsed:
            close = Decimal(fields[4])
            pre_close = previous if previous is not None else close
            result.append(self.normalize_bar({
                "symbol": symbol, "symbol_name": symbol, "trade_date": day.isoformat(),
                "open": fields[1], "high": fields[2], "low": fields[3], "close": fields[4],
                "pre_close": pre_close, "volume": fields[5], "amount": fields[6],
                "source_payload_hash": digest,
            }, Market.CN_A))
            previous = close
        return result

    def _parse_hstech(self, document: Mapping[str, object], digest: str) -> list[DailyBar]:
        try:
            counts = [(int(year), int(count)) for year, count in document["sortYear"]]  # type: ignore[index]
            tokens = [int(value) for value in str(document["price"]).split(",")]
            dates = str(document["dates"]).split(",")
            volumes = str(document["volumn"]).split(",")
            factor = Decimal(str(document["priceFactor"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "HSTECH response fields are malformed", retryable=False) from exc
        if len(tokens) != len(dates) * 4 or len(volumes) != len(dates):
            raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "HSTECH response arrays have inconsistent lengths", retryable=False)
        years = [year for year, count in counts for _ in range(count)]
        if len(years) != len(dates):
            raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "HSTECH year counts do not match dates", retryable=False)
        result: list[DailyBar] = []
        previous: Decimal | None = None
        for index, (year, month_day) in enumerate(zip(years, dates, strict=True)):
            close_raw, high_delta, low_delta, open_delta = tokens[index * 4:index * 4 + 4]
            close = Decimal(close_raw) / factor
            high = close + Decimal(high_delta) / factor
            low = close - Decimal(low_delta) / factor
            open_ = close - Decimal(open_delta) / factor
            pre_close = previous if previous is not None else close
            result.append(self.normalize_bar({
                "symbol": "HSTECH", "symbol_name": str(document.get("name", "恒生科技指数")),
                "trade_date": f"{year}-{month_day[:2]}-{month_day[2:]}",
                "open": open_, "high": high, "low": low, "close": close, "pre_close": pre_close,
                "volume": volumes[index] or None, "amount": None, "source_payload_hash": digest,
                "data_status": DataStatus.NORMAL,
            }, Market.HK))
            previous = close
        return result
