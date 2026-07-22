from __future__ import annotations

import unittest
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from leopard_project.models import DailyBar, DataStatus, LiquidityStatus, Market
from leopard_project.provider_validation import run_validation
from leopard_project.providers import (
    ProviderRole,
    SnapshotAnomaly,
    detect_snapshot_anomaly,
    production_admission_met,
    provider_role,
    provider_symbol,
)


class OfflineCoverageProvider:
    provider_key = "ths_public_validation"

    def historical_daily_bars(self, symbol: str, start: date, end: date, market: Market):
        count = 14 if symbol == "886111" else 121
        canonical = "HSTECH" if market == Market.HK else symbol
        amount = None if market == Market.HK else Decimal("2000")
        liquidity = LiquidityStatus.PARTIAL if amount is None else LiquidityStatus.COMPLETE
        rows = []
        for index in range(count):
            close = Decimal("100") + index
            rows.append(DailyBar(
                symbol=canonical, symbol_name=canonical, market=market,
                trade_date=date(2026, 1, 1) + timedelta(days=index),
                open=close, high=close + 1, low=close - 1, close=close,
                pre_close=close - 1, change=1,
                pct_change=Decimal("1") / (close - 1) * 100,
                volume=Decimal("1000"), turnover_rate=None, amount=amount,
                liquidity_status=liquidity, provider=self.provider_key,
                fetched_at=datetime(2026, 7, 22, tzinfo=UTC), source_payload_hash="a" * 64,
                data_status=DataStatus.NORMAL,
            ))
        return tuple(rows)


class ProviderPolicyTests(unittest.TestCase):
    def test_hstech_provider_symbol_conversion(self) -> None:
        self.assertEqual(provider_symbol("HSTECH", "ths_public_validation"), "HS2083")
        self.assertEqual(provider_symbol("HSTECH", "tushare_ths_daily"), "HKTECH")

    def test_provider_roles_and_production_admission(self) -> None:
        self.assertEqual(provider_role("tushare_ths_daily"), ProviderRole.CANDIDATE_PRIMARY)
        self.assertEqual(provider_role("ths_public_validation"), ProviderRole.DIAGNOSTIC_PROVIDER)
        self.assertFalse(production_admission_met([
            "account_permission_verified", "all_66_symbol_conversions_verified", "full_live_scan_passed",
            "five_consecutive_trading_days_dual_source_reconciled", "freshness_checks_passed",
            "field_and_unit_contract_approved",
        ]))

    def test_snapshot_regression_detection(self) -> None:
        self.assertEqual(
            detect_snapshot_anomaly(date(2026, 7, 21), 133, date(2026, 4, 21), 72),
            SnapshotAnomaly.STALE_SNAPSHOT,
        )
        self.assertEqual(
            detect_snapshot_anomaly(date(2026, 7, 21), 133, date(2026, 7, 21), 72),
            SnapshotAnomaly.HISTORY_LENGTH_CHANGED,
        )

    def test_exclusive_coverage_categories_sum_to_66(self) -> None:
        coverage = run_validation(scope="all", provider=OfflineCoverageProvider())
        summary = coverage["summary"]
        self.assertEqual(summary["exclusive_classification_total"], 66)
        self.assertEqual(summary["exclusive_classifications"], {
            "direct_full": 60,
            "direct_short_history": 1,
            "cross_market_special": 1,
            "custom_composite_ready": 3,
            "proxy_only": 1,
            "unavailable": 0,
        })
        hotel = next(row for row in coverage["results"] if row["sector_key"] == "hotel_catering")
        self.assertEqual(hotel["provider_symbol"], "881160")
        self.assertEqual(hotel["mapping_type"], "proxy")
        self.assertEqual(hotel["data_status"], DataStatus.PROXY)
        hstech = next(row for row in coverage["results"] if row["sector_key"] == "hang_seng_tech")
        self.assertTrue(hstech["eligible_for_normal_write"])


if __name__ == "__main__":
    unittest.main()
