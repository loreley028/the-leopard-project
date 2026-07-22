from __future__ import annotations

import json
import unittest
from datetime import UTC, date, datetime
from decimal import Decimal

from leopard_project.models import DataStatus, LiquidityStatus, Market
from leopard_project.provider_validation import audit_bars, canonical_bar_hash, validate_expected_name
from leopard_project.providers import ProviderError, ProviderErrorCategory, ThsPublicValidationProvider


def callback(name: str, document: dict[str, object]) -> bytes:
    return f'{name}({json.dumps(document, separators=(",", ":"))})'.encode()


def board_payload(rows: int = 121) -> bytes:
    values = []
    for index in range(rows):
        day = date.fromordinal(date(2026, 1, 1).toordinal() + index)
        close = Decimal("100") + index
        values.append(f'{day:%Y%m%d},{close - 1},{close + 1},{close - 2},{close},{1000 + index},{2000 + index},,,,0')
    return callback("quotebridge_v4_line", {"data": ";".join(values)})


def hstech_payload() -> bytes:
    return callback("quotebridge_v6_line", {
        "sortYear": [[2026, 2]], "priceFactor": 100,
        "price": "450000,100,200,50,451000,150,250,75",
        "dates": "0720,0721", "volumn": "1000,1200", "name": "恒生科技指数",
    })


class ThsPublicProviderTests(unittest.TestCase):
    def provider(self, payload: bytes) -> ThsPublicValidationProvider:
        return ThsPublicValidationProvider(
            transport=lambda _url, _timeout: payload,
            minimum_interval=0,
            fetched_at=lambda: datetime(2026, 7, 22, tzinfo=UTC),
        )

    def test_board_fields_units_sorting_and_derived_change(self) -> None:
        bars = self.provider(board_payload()).historical_daily_bars("881121", date(2026, 1, 1), date(2026, 12, 31), Market.CN_A)
        self.assertEqual(len(bars), 121)
        self.assertEqual(bars[1].pre_close, bars[0].close)
        self.assertEqual(bars[1].change, Decimal("1"))
        self.assertEqual(bars[-1].volume, Decimal("1120"))
        self.assertEqual(bars[-1].amount, Decimal("2120"))
        self.assertTrue(audit_bars(bars).at_least_120)

    def test_hstech_normalization_is_market_specific_and_amount_incomplete(self) -> None:
        bars = self.provider(hstech_payload()).historical_daily_bars("HS2083", date(2026, 1, 1), date(2026, 12, 31), Market.HK)
        self.assertEqual(bars[-1].symbol, "HSTECH")
        self.assertEqual(bars[-1].high, Decimal("4511.5"))
        self.assertEqual(bars[-1].low, Decimal("4507.5"))
        self.assertEqual(bars[-1].open, Decimal("4509.25"))
        self.assertIsNone(bars[-1].amount)
        self.assertEqual(bars[-1].liquidity_status, LiquidityStatus.PARTIAL)
        self.assertEqual(bars[-1].data_status, DataStatus.NORMAL)

    def test_empty_response_is_classified(self) -> None:
        provider = self.provider(b"")
        with self.assertRaises(ProviderError) as caught:
            provider.historical_daily_bars("881121", date(2026, 1, 1), date(2026, 12, 31), Market.CN_A)
        self.assertEqual(caught.exception.category, ProviderErrorCategory.NO_DATA)

    def test_invalid_symbol_is_not_retryable(self) -> None:
        with self.assertRaises(ProviderError) as caught:
            self.provider(board_payload()).historical_daily_bars("BAD", date(2026, 1, 1), date(2026, 12, 31), Market.CN_A)
        self.assertEqual(caught.exception.category, ProviderErrorCategory.INVALID_SYMBOL)
        self.assertFalse(caught.exception.retryable)

    def test_duplicate_dates_are_rejected(self) -> None:
        row = "20260721,1,2,1,2,3,4,,,,0"
        with self.assertRaises(ProviderError) as caught:
            self.provider(callback("x", {"data": f"{row};{row}"})).historical_daily_bars("881121", date(2026, 1, 1), date(2026, 12, 31), Market.CN_A)
        self.assertEqual(caught.exception.category, ProviderErrorCategory.MALFORMED_RESPONSE)

    def test_timeout_and_rate_limit_categories_are_preserved(self) -> None:
        for category in (ProviderErrorCategory.TIMEOUT, ProviderErrorCategory.RATE_LIMIT):
            def fail(_url: str, _timeout: float, category: ProviderErrorCategory = category) -> bytes:
                raise ProviderError(category, "redacted", retryable=True)
            provider = ThsPublicValidationProvider(transport=fail, minimum_interval=0)
            with self.assertRaises(ProviderError) as caught:
                provider.historical_daily_bars("881121", date(2026, 1, 1), date(2026, 12, 31), Market.CN_A)
            self.assertEqual(caught.exception.category, category)
            self.assertNotIn("token", str(caught.exception).lower())

    def test_repeated_request_is_cached_and_deterministic(self) -> None:
        calls = 0
        def transport(_url: str, _timeout: float) -> bytes:
            nonlocal calls
            calls += 1
            return board_payload()
        provider = ThsPublicValidationProvider(transport=transport, minimum_interval=0)
        first = provider.historical_daily_bars("881121", date(2026, 1, 1), date(2026, 12, 31), Market.CN_A)
        second = provider.historical_daily_bars("881121", date(2026, 1, 1), date(2026, 12, 31), Market.CN_A)
        self.assertEqual(calls, 1)
        self.assertEqual(canonical_bar_hash(first), canonical_bar_hash(second))

    def test_insufficient_history_is_explicit(self) -> None:
        bars = self.provider(board_payload(5)).historical_daily_bars("881121", date(2026, 1, 1), date(2026, 12, 31), Market.CN_A)
        self.assertFalse(audit_bars(bars).at_least_120)

    def test_name_mismatch_is_explicit_and_not_retryable(self) -> None:
        with self.assertRaises(ProviderError) as caught:
            validate_expected_name("恒生科技", "恒生综合指数", aliases=("恒生科技指数",))
        self.assertEqual(caught.exception.category, ProviderErrorCategory.NAME_MISMATCH)
        self.assertFalse(caught.exception.retryable)


if __name__ == "__main__":
    unittest.main()
