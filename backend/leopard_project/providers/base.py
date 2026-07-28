from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Iterable, Mapping, Sequence

from ..models import DailyBar, Market


class ProviderErrorCategory(StrEnum):
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    RATE_LIMIT = "rate_limit"
    NETWORK = "network"
    INVALID_SYMBOL = "invalid_symbol"
    NO_DATA = "no_data"
    MALFORMED_RESPONSE = "malformed_response"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    TIMEOUT = "timeout"
    NAME_MISMATCH = "name_mismatch"


class ProviderError(RuntimeError):
    def __init__(self, category: ProviderErrorCategory, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable


@dataclass(frozen=True)
class SymbolValidation:
    symbol: str
    valid: bool
    market: Market
    provider: str
    reason: str | None = None


class MarketDataProvider(ABC):
    provider_key: str

    @abstractmethod
    def trading_calendar(self, start: date, end: date, market: Market) -> Sequence[date]: ...

    @abstractmethod
    def validate_symbol(self, symbol: str, market: Market) -> SymbolValidation: ...

    @abstractmethod
    def historical_daily_bars(self, symbol: str, start: date, end: date, market: Market) -> Sequence[DailyBar]: ...

    @abstractmethod
    def bars_for_date(self, symbols: Iterable[str], trade_date: date, market: Market) -> Sequence[DailyBar]: ...

    @abstractmethod
    def normalize_bar(self, raw: Mapping[str, object], market: Market) -> DailyBar: ...

    def fetch_intraday_snapshot(self, sector_mapping: object, as_of: datetime) -> DailyBar:
        """Return a current-session snapshot; historical daily APIs must not implement this implicitly."""
        raise ProviderError(
            ProviderErrorCategory.PROVIDER_UNAVAILABLE,
            f"{self.provider_key} has no validated intraday endpoint",
            retryable=False,
        )
