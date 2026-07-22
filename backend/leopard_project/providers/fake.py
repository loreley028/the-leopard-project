from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Iterable, Mapping, Sequence

from ..models import DailyBar, DataStatus, LiquidityStatus, Market
from .base import MarketDataProvider, ProviderError, ProviderErrorCategory, SymbolValidation


class FakeProvider(MarketDataProvider):
    provider_key = "fixture"

    def __init__(self, bars: Sequence[DailyBar], calendars: Mapping[Market, Sequence[date]]) -> None:
        self._bars = tuple(bars)
        self._calendars = {market: tuple(days) for market, days in calendars.items()}

    def trading_calendar(self, start: date, end: date, market: Market) -> Sequence[date]:
        return tuple(day for day in self._calendars.get(market, ()) if start <= day <= end)

    def validate_symbol(self, symbol: str, market: Market) -> SymbolValidation:
        valid = any(bar.symbol == symbol and bar.market == market for bar in self._bars)
        return SymbolValidation(symbol, valid, market, self.provider_key, None if valid else "fixture symbol not found")

    def historical_daily_bars(self, symbol: str, start: date, end: date, market: Market) -> Sequence[DailyBar]:
        return tuple(bar for bar in self._bars if bar.symbol == symbol and bar.market == market and start <= bar.trade_date <= end)

    def bars_for_date(self, symbols: Iterable[str], trade_date: date, market: Market) -> Sequence[DailyBar]:
        requested = set(symbols)
        return tuple(bar for bar in self._bars if bar.symbol in requested and bar.market == market and bar.trade_date == trade_date)

    def normalize_bar(self, raw: Mapping[str, object], market: Market) -> DailyBar:
        required = {"symbol", "symbol_name", "trade_date", "open", "high", "low", "close", "pre_close", "volume"}
        missing = sorted(required - raw.keys())
        if missing:
            raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, f"missing fields: {', '.join(missing)}", retryable=False)
        close = Decimal(str(raw["close"]))
        pre_close = Decimal(str(raw["pre_close"]))
        change = close - pre_close
        pct_change = Decimal("0") if pre_close == 0 else (close / pre_close - 1) * Decimal("100")
        payload_hash = hashlib.sha256(repr(sorted(raw.items())).encode()).hexdigest()
        volume = None if raw.get("volume") in (None, "") else Decimal(str(raw["volume"]))
        amount = None if raw.get("amount") in (None, "") else Decimal(str(raw["amount"]))
        turnover_rate = None if raw.get("turnover_rate") in (None, "") else Decimal(str(raw["turnover_rate"]))
        liquidity_status = (
            LiquidityStatus.COMPLETE if volume is not None and amount is not None
            else LiquidityStatus.PARTIAL if any(value is not None for value in (volume, turnover_rate, amount))
            else LiquidityStatus.UNAVAILABLE
        )
        return DailyBar(
            symbol=str(raw["symbol"]),
            symbol_name=str(raw["symbol_name"]),
            market=market,
            trade_date=date.fromisoformat(str(raw["trade_date"])),
            open=Decimal(str(raw["open"])),
            high=Decimal(str(raw["high"])),
            low=Decimal(str(raw["low"])),
            close=close,
            pre_close=pre_close,
            change=change,
            pct_change=pct_change,
            volume=volume,
            turnover_rate=turnover_rate,
            amount=amount,
            liquidity_status=liquidity_status,
            provider=self.provider_key,
            fetched_at=datetime(2026, 7, 22, 8, 30, tzinfo=timezone.utc),
            source_payload_hash=payload_hash,
            data_status=DataStatus.NORMAL,
        )
