from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from decimal import Decimal

from leopard_project.models import LiquidityStatus, Market
from leopard_project.providers import AkshareResearchProvider, ProviderError, ProviderErrorCategory


class AkshareResearchProviderTests(unittest.TestCase):
    def test_default_adapter_never_accesses_network(self) -> None:
        provider = AkshareResearchProvider()
        with self.assertRaises(ProviderError) as caught:
            provider.historical_daily_bars("881121", date(2026, 7, 21), date(2026, 7, 21), Market.CN_A)
        self.assertEqual(caught.exception.category, ProviderErrorCategory.PROVIDER_UNAVAILABLE)
        self.assertNotIn("token", str(caught.exception).lower())

    def test_injected_research_rows_are_normalized(self) -> None:
        observed: list[tuple[str, str, str]] = []

        def fetch(symbol: str, name: str, sector_type: str, _start: date, _end: date):
            observed.append((symbol, name, sector_type))
            return ({
                "日期": "2026-07-21", "开盘价": "99", "最高价": "102", "最低价": "98",
                "收盘价": "101", "成交量": "1000", "成交额": "2000", "pre_close": "100",
            },)

        provider = AkshareResearchProvider(
            fetcher=fetch,
            fetched_at=lambda: datetime(2026, 7, 22, tzinfo=UTC),
        )
        bars = provider.historical_daily_bars("881121", date(2026, 7, 21), date(2026, 7, 21), Market.CN_A)
        self.assertEqual(observed, [("881121", "半导体", "行业")])
        self.assertEqual(bars[0].close, Decimal("101"))
        self.assertEqual(bars[0].pct_change, Decimal("1"))
        self.assertEqual(bars[0].liquidity_status, LiquidityStatus.COMPLETE)

    def test_amount_is_optional(self) -> None:
        provider = AkshareResearchProvider(fetcher=lambda *_args: ({
            "日期": "2026-07-21", "开盘价": "99", "最高价": "102", "最低价": "98",
            "收盘价": "101", "成交量": "1000", "pre_close": "100",
        },))
        bar = provider.historical_daily_bars("881121", date(2026, 7, 21), date(2026, 7, 21), Market.CN_A)[0]
        self.assertIsNone(bar.amount)
        self.assertEqual(bar.liquidity_status, LiquidityStatus.PARTIAL)

    def test_adjacent_close_derives_pre_close_without_fabricating_amount(self) -> None:
        provider = AkshareResearchProvider(fetcher=lambda *_args: (
            {"日期": "2026-07-20", "开盘价": "99", "最高价": "101", "最低价": "98", "收盘价": "100", "成交量": "900"},
            {"日期": "2026-07-21", "开盘价": "100", "最高价": "102", "最低价": "99", "收盘价": "101", "成交量": "1000"},
        ))
        bars = provider.historical_daily_bars("881121", date(2026, 7, 20), date(2026, 7, 21), Market.CN_A)
        self.assertEqual(bars[1].pre_close, bars[0].close)
        self.assertEqual(bars[1].pct_change, Decimal("1"))
        self.assertIsNone(bars[1].amount)

    def test_hk_is_explicitly_rejected(self) -> None:
        provider = AkshareResearchProvider(fetcher=lambda *_args: ())
        with self.assertRaises(ProviderError) as caught:
            provider.historical_daily_bars("HSTECH", date(2026, 7, 21), date(2026, 7, 21), Market.HK)
        self.assertEqual(caught.exception.category, ProviderErrorCategory.INVALID_SYMBOL)


if __name__ == "__main__":
    unittest.main()
