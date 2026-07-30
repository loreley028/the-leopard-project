from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from leopard_project.models import DailyBar, DataStatus, LiquidityStatus, Market
from leopard_project.provider_selection import provider_comparison, run_provider_selection


class OfflineSelectionProvider:
    provider_key = "ths_public_validation"

    def historical_daily_bars(self, symbol: str, start: date, end: date, market: Market):
        count = 14 if symbol == "886111" else 121
        rows = []
        for index in range(count):
            close = Decimal(100 + index)
            rows.append(DailyBar(
                symbol=symbol, symbol_name=symbol, market=Market.CN_A,
                trade_date=date(2026, 1, 1) + timedelta(days=index),
                open=close, high=close + 1, low=close - 1, close=close,
                pre_close=close - 1, change=1, pct_change=Decimal(1) / (close - 1) * 100,
                volume=Decimal(1000), turnover_rate=None, amount=Decimal(2000),
                liquidity_status=LiquidityStatus.COMPLETE, provider=self.provider_key,
                fetched_at=datetime(2026, 7, 22, tzinfo=UTC), source_payload_hash="b" * 64,
                data_status=DataStatus.NORMAL,
            ))
        return tuple(rows)


class ProviderSelectionTests(unittest.TestCase):
    def test_coverage_and_comparison_schema_are_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            coverage, comparison = run_provider_selection(
                output_dir=Path(directory), provider=OfflineSelectionProvider(), end=date(2026, 7, 22)
            )
        summary = coverage["summary"]
        self.assertEqual(summary["supported_sector_count"], 66)
        self.assertEqual(summary["real_data_count"], 66)
        self.assertEqual(summary["full_history_count"], 65)
        self.assertEqual(summary["field_counts"]["has_turnover_rate"], 0)
        self.assertEqual(comparison["selection_conclusion"], "D_free_or_public_sources_are_not_yet_sufficient_for_stable_production")
        self.assertFalse(comparison["production_primary_approved"])
        required = {
            "provider_name", "provider_role", "supported_sector_count", "coverage_rate",
            "full_history_count", "latest_trade_date_count", "has_open", "has_high", "has_low",
            "has_close", "has_pre_close", "has_pct_change", "has_volume", "has_turnover_rate",
            "has_amount", "freshness_risk", "stale_snapshot_risk", "rate_limit",
            "authentication_required", "paid_permission_required", "licensing_risk",
            "endpoint_stability", "integration_complexity", "maintenance_cost",
            "production_recommendation", "blocking_reasons",
        }
        self.assertTrue(all(required <= set(row) for row in comparison["providers"]))

    def test_public_source_cannot_be_promoted_by_coverage_alone(self) -> None:
        coverage = {
            "summary": {
                "real_data_count": 65, "coverage_rate": 1.0, "full_history_count": 64,
                "latest_trade_date_count": 65,
                "field_counts": {name: 65 for name in (
                    "has_open", "has_high", "has_low", "has_close", "has_pre_close",
                    "has_pct_change", "has_volume", "has_turnover_rate", "has_amount",
                )},
            }
        }
        result = provider_comparison(coverage)
        public = result["providers"][0]
        self.assertEqual(public["provider_role"], "diagnostic_provider")
        self.assertIn("no_sla", public["blocking_reasons"])


if __name__ == "__main__":
    unittest.main()
