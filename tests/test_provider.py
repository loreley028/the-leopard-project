from __future__ import annotations

import json
import unittest
from datetime import date
from pathlib import Path

from leopard_project.models import LiquidityStatus, Market
from leopard_project.providers import FakeProvider, ProviderError


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "provider_rows.json"


class FakeProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        rows = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        temporary = FakeProvider([], {})
        bars = [temporary.normalize_bar({key: value for key, value in row.items() if key != "market"}, Market(row["market"])) for row in rows]
        cls.provider = FakeProvider(
            bars,
            {
                Market.CN_A: [date(2026, 7, 20), date(2026, 7, 21)],
                Market.HK: [date(2026, 7, 20), date(2026, 7, 22)],
            },
        )

    def test_field_normalization(self) -> None:
        bars = self.provider.historical_daily_bars("881121", date(2026, 7, 20), date(2026, 7, 20), Market.CN_A)
        self.assertEqual(len(bars), 1)
        self.assertEqual(str(bars[0].pct_change), "2.00")
        self.assertEqual(bars[0].provider, "fixture")
        self.assertEqual(len(bars[0].source_payload_hash), 64)

    def test_hk_calendar_is_independent_from_a_share_calendar(self) -> None:
        hk_days = self.provider.trading_calendar(date(2026, 7, 21), date(2026, 7, 22), Market.HK)
        a_days = self.provider.trading_calendar(date(2026, 7, 21), date(2026, 7, 22), Market.CN_A)
        self.assertEqual(hk_days, (date(2026, 7, 22),))
        self.assertEqual(a_days, (date(2026, 7, 21),))

    def test_symbol_validation_uses_market(self) -> None:
        self.assertTrue(self.provider.validate_symbol("HS2083", Market.HK).valid)
        self.assertFalse(self.provider.validate_symbol("HS2083", Market.CN_A).valid)

    def test_malformed_provider_row_is_classified(self) -> None:
        with self.assertRaises(ProviderError) as context:
            self.provider.normalize_bar({"symbol": "broken"}, Market.CN_A)
        self.assertFalse(context.exception.retryable)

    def test_normalization_is_deterministic(self) -> None:
        raw = {
            "symbol": "X", "symbol_name": "X", "trade_date": "2026-07-20",
            "open": "1", "high": "2", "low": "1", "close": "2", "pre_close": "1",
            "volume": "3", "amount": "4",
        }
        self.assertEqual(self.provider.normalize_bar(raw, Market.CN_A), self.provider.normalize_bar(raw, Market.CN_A))

    def test_amount_is_optional_and_is_never_inferred(self) -> None:
        raw = {
            "symbol": "X", "symbol_name": "X", "trade_date": "2026-07-20",
            "open": "1", "high": "2", "low": "1", "close": "2", "pre_close": "1",
            "volume": "300", "turnover_rate": "1.5", "avg_price": "1.8",
        }
        bar = self.provider.normalize_bar(raw, Market.CN_A)
        self.assertIsNone(bar.amount)
        self.assertEqual(bar.volume, 300)
        self.assertEqual(bar.turnover_rate, 1.5)
        self.assertEqual(bar.liquidity_status, LiquidityStatus.PARTIAL)


if __name__ == "__main__":
    unittest.main()
