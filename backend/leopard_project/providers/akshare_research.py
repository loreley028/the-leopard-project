from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Callable, Iterable, Mapping, Sequence

from ..config import CONFIG_DIR
from ..models import DailyBar, DataStatus, LiquidityStatus, Market
from .base import MarketDataProvider, ProviderError, ProviderErrorCategory, SymbolValidation


ResearchFetcher = Callable[[str, str, str, date, date], Sequence[Mapping[str, object]]]


def _symbol_metadata() -> dict[str, tuple[str, str]]:
    document = json.loads((CONFIG_DIR / "sector_mappings_v2_3.json").read_text(encoding="utf-8"))
    result = {
        str(row["primary_symbol"]): (str(row["ths_candidate_name"]), str(row["ths_sector_type"]))
        for row in document["mappings"]
        if not str(row["primary_symbol"]).startswith("CUSTOM_")
        and str(row["ths_sector_type"]) in {"行业", "概念"}
    }
    result["881160"] = ("酒店餐饮", "行业")
    return result


def build_live_akshare_fetcher() -> ResearchFetcher:
    """Build an explicit live fetcher; importing AKShare never occurs in offline paths."""
    try:
        import akshare as ak  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ProviderError(
            ProviderErrorCategory.PROVIDER_UNAVAILABLE,
            "AKShare optional research dependency is not installed",
            retryable=False,
        ) from exc

    def fetch(_symbol: str, sector_name: str, sector_type: str, start: date, end: date) -> Sequence[Mapping[str, object]]:
        function = (
            ak.stock_board_industry_index_ths
            if sector_type == "行业"
            else ak.stock_board_concept_index_ths
        )
        frame = function(
            symbol=sector_name,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )
        return tuple(frame.to_dict(orient="records"))

    return fetch


class AkshareResearchProvider(MarketDataProvider):
    """Research-only adapter for AKShare Tonghuashun board interfaces.

    A fetcher must be injected explicitly. Construction alone cannot access the
    network, and no retry or credential path exists.
    """

    provider_key = "akshare_ths_research"

    def __init__(
        self,
        *,
        fetcher: ResearchFetcher | None = None,
        fetched_at: Callable[[], datetime] | None = None,
    ) -> None:
        self._fetcher = fetcher
        self._fetched_at = fetched_at or (lambda: datetime.now(UTC))
        self._metadata = _symbol_metadata()
        self._observed_calendar: set[date] = set()

    def trading_calendar(self, start: date, end: date, market: Market) -> Sequence[date]:
        if market != Market.CN_A:
            return ()
        return tuple(sorted(day for day in self._observed_calendar if start <= day <= end))

    def validate_symbol(self, symbol: str, market: Market) -> SymbolValidation:
        if market != Market.CN_A or symbol not in self._metadata:
            return SymbolValidation(symbol, False, market, self.provider_key, "research mapping unavailable")
        if self._fetcher is None:
            return SymbolValidation(symbol, False, market, self.provider_key, "explicit live fetcher not configured")
        return SymbolValidation(symbol, True, market, self.provider_key)

    def historical_daily_bars(self, symbol: str, start: date, end: date, market: Market) -> Sequence[DailyBar]:
        if market != Market.CN_A:
            raise ProviderError(
                ProviderErrorCategory.INVALID_SYMBOL,
                "AKShare research adapter is restricted to CN_A sectors",
                retryable=False,
            )
        if self._fetcher is None:
            raise ProviderError(
                ProviderErrorCategory.PROVIDER_UNAVAILABLE,
                "AKShare network access requires an explicit research fetcher",
                retryable=False,
            )
        try:
            sector_name, sector_type = self._metadata[symbol]
        except KeyError as exc:
            raise ProviderError(
                ProviderErrorCategory.INVALID_SYMBOL,
                "AKShare research mapping is unavailable for symbol",
                retryable=False,
            ) from exc
        try:
            rows = self._fetcher(symbol, sector_name, sector_type, start, end)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(
                ProviderErrorCategory.NETWORK,
                "AKShare research request failed",
                retryable=False,
            ) from exc
        ordered_rows = sorted(rows, key=lambda row: str(row.get("trade_date", row.get("日期", row.get("date", "")))))
        normalized: list[DailyBar] = []
        previous_close: Decimal | None = None
        for row in ordered_rows:
            enriched = {**row, "symbol": symbol, "symbol_name": sector_name}
            if "pre_close" not in enriched and "昨收" not in enriched and previous_close is not None:
                enriched["pre_close"] = previous_close
            current = self.normalize_bar(enriched, market)
            normalized.append(current)
            previous_close = current.close
        bars = tuple(normalized)
        filtered = tuple(sorted((bar for bar in bars if start <= bar.trade_date <= end), key=lambda bar: bar.trade_date))
        days = [bar.trade_date for bar in filtered]
        if len(days) != len(set(days)):
            raise ProviderError(
                ProviderErrorCategory.MALFORMED_RESPONSE,
                "AKShare research response contains duplicate dates",
                retryable=False,
            )
        self._observed_calendar.update(days)
        return filtered

    def bars_for_date(self, symbols: Iterable[str], trade_date: date, market: Market) -> Sequence[DailyBar]:
        result: list[DailyBar] = []
        for symbol in symbols:
            result.extend(self.historical_daily_bars(symbol, trade_date, trade_date, market))
        return tuple(result)

    def normalize_bar(self, raw: Mapping[str, object], market: Market) -> DailyBar:
        aliases = {
            "trade_date": ("trade_date", "日期", "date"),
            "open": ("open", "开盘价", "开盘"),
            "high": ("high", "最高价", "最高"),
            "low": ("low", "最低价", "最低"),
            "close": ("close", "收盘价", "收盘"),
            "volume": ("volume", "成交量"),
            "amount": ("amount", "成交额"),
            "turnover_rate": ("turnover_rate", "换手率"),
        }

        def value(name: str) -> object | None:
            return next((raw[key] for key in aliases[name] if key in raw), None)

        required = ("trade_date", "open", "high", "low", "close", "volume")
        missing = tuple(name for name in required if value(name) in (None, ""))
        if missing:
            raise ProviderError(
                ProviderErrorCategory.MALFORMED_RESPONSE,
                f"AKShare normalized row is missing required fields: {', '.join(missing)}",
                retryable=False,
            )
        close = Decimal(str(value("close")))
        pre_close_raw = raw.get("pre_close", raw.get("昨收"))
        pre_close = close if pre_close_raw in (None, "") else Decimal(str(pre_close_raw))
        change = close - pre_close
        pct_change_raw = raw.get("pct_change", raw.get("涨跌幅"))
        pct_change = (
            Decimal("0") if pre_close == 0
            else (change / pre_close * Decimal("100"))
            if pct_change_raw in (None, "")
            else Decimal(str(pct_change_raw))
        )
        volume = Decimal(str(value("volume")))
        amount_raw = value("amount")
        turnover_raw = value("turnover_rate")
        amount = None if amount_raw in (None, "") else Decimal(str(amount_raw))
        turnover_rate = None if turnover_raw in (None, "") else Decimal(str(turnover_raw))
        liquidity = LiquidityStatus.COMPLETE if amount is not None else LiquidityStatus.PARTIAL
        digest = hashlib.sha256(
            json.dumps({str(key): str(raw[key]) for key in sorted(raw)}, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        return DailyBar(
            symbol=str(raw["symbol"]),
            symbol_name=str(raw["symbol_name"]),
            market=market,
            trade_date=date.fromisoformat(str(value("trade_date"))[:10]),
            open=Decimal(str(value("open"))),
            high=Decimal(str(value("high"))),
            low=Decimal(str(value("low"))),
            close=close,
            pre_close=pre_close,
            change=change,
            pct_change=pct_change,
            volume=volume,
            turnover_rate=turnover_rate,
            amount=amount,
            liquidity_status=liquidity,
            provider=self.provider_key,
            fetched_at=self._fetched_at(),
            source_payload_hash=digest,
            data_status=DataStatus.NORMAL,
        )
