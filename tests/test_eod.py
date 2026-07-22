from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from decimal import Decimal

from leopard_project.eod import EodStatus, FixtureTradingCalendar, assess_eod, load_eod_policy
from leopard_project.models import DailyBar, DataStatus, LiquidityStatus, Market
from leopard_project.support import build_collection_plan


def bar(day: date, *, volume: Decimal | None = Decimal("1000"), amount: Decimal | None = Decimal("2000")) -> DailyBar:
    liquidity = (
        LiquidityStatus.COMPLETE if volume is not None and amount is not None
        else LiquidityStatus.PARTIAL if volume is not None or amount is not None
        else LiquidityStatus.UNAVAILABLE
    )
    return DailyBar(
        symbol="881121", symbol_name="半导体", market=Market.CN_A, trade_date=day,
        open=Decimal("99"), high=Decimal("102"), low=Decimal("98"), close=Decimal("101"),
        pre_close=Decimal("100"), change=Decimal("1"), pct_change=Decimal("1"),
        volume=volume, amount=amount, liquidity_status=liquidity,
        provider="fixture", fetched_at=datetime(2026, 7, 22, tzinfo=UTC),
        source_payload_hash="fixture-hash", data_status=DataStatus.NORMAL,
    )


class EodGatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = load_eod_policy()
        cls.calendar = FixtureTradingCalendar.from_file()

    def assess(self, bars: tuple[DailyBar, ...], as_of: str, **kwargs: object):
        return assess_eod(
            bars,
            provider_name="ths_public_validation",
            as_of=datetime.fromisoformat(as_of),
            calendar=self.calendar,
            policy=self.policy,
            **kwargs,
        )

    def test_current_day_before_safe_time_is_intraday(self) -> None:
        result = self.assess((bar(date(2026, 7, 21)), bar(date(2026, 7, 22))), "2026-07-22T15:30:00+08:00")
        self.assertEqual(result.expected_trade_date, date(2026, 7, 21))
        self.assertEqual(result.status, EodStatus.INTRADAY_SNAPSHOT)
        self.assertFalse(result.eligible_for_eod)

    def test_current_day_after_safe_time_is_complete(self) -> None:
        result = self.assess((bar(date(2026, 7, 22)),), "2026-07-22T16:30:00+08:00")
        self.assertEqual(result.status, EodStatus.COMPLETE_EOD)
        self.assertTrue(result.eligible_for_eod)

    def test_latest_before_expected_is_stale(self) -> None:
        result = self.assess((bar(date(2026, 7, 21)),), "2026-07-22T17:00:00+08:00")
        self.assertEqual(result.status, EodStatus.STALE_SNAPSHOT)

    def test_latest_after_expected_is_future(self) -> None:
        result = self.assess((bar(date(2026, 7, 23)),), "2026-07-22T17:00:00+08:00")
        self.assertEqual(result.status, EodStatus.FUTURE_SNAPSHOT)

    def test_no_rows_is_missing_expected_date(self) -> None:
        result = self.assess((), "2026-07-22T17:00:00+08:00")
        self.assertEqual(result.status, EodStatus.MISSING_EXPECTED_TRADE_DATE)

    def test_weekend_uses_fixture_previous_session(self) -> None:
        result = self.assess((bar(date(2026, 7, 17)),), "2026-07-19T17:00:00+08:00")
        self.assertEqual(result.expected_trade_date, date(2026, 7, 17))
        self.assertEqual(result.status, EodStatus.COMPLETE_EOD)

    def test_holiday_fixture_is_not_assumed_from_weekday(self) -> None:
        result = self.assess((bar(date(2026, 4, 30)),), "2026-05-01T17:00:00+08:00")
        self.assertEqual(result.expected_trade_date, date(2026, 4, 30))

    def test_naive_time_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assess_eod(
                (bar(date(2026, 7, 22)),), provider_name="ths_public_validation",
                as_of=datetime(2026, 7, 22, 17), calendar=self.calendar, policy=self.policy,
            )

    def test_timezone_conversion_occurs_before_cutoff(self) -> None:
        result = self.assess((bar(date(2026, 7, 22)),), "2026-07-22T08:29:00+00:00")
        self.assertEqual(result.status, EodStatus.INTRADAY_SNAPSHOT)
        result = self.assess((bar(date(2026, 7, 22)),), "2026-07-22T08:31:00+00:00")
        self.assertEqual(result.status, EodStatus.COMPLETE_EOD)

    def test_duplicate_dates_are_incomplete(self) -> None:
        duplicate = bar(date(2026, 7, 22))
        result = self.assess((duplicate, duplicate), "2026-07-22T17:00:00+08:00")
        self.assertEqual(result.status, EodStatus.INCOMPLETE_FIELDS)
        self.assertIn("duplicate_dates", result.anomaly_codes)

    def test_unsorted_dates_are_incomplete(self) -> None:
        result = self.assess(
            (bar(date(2026, 7, 22)), bar(date(2026, 7, 21))),
            "2026-07-22T17:00:00+08:00",
        )
        self.assertEqual(result.status, EodStatus.INCOMPLETE_FIELDS)
        self.assertIn("dates_not_sorted", result.anomaly_codes)

    def test_missing_required_volume_is_incomplete(self) -> None:
        result = self.assess((bar(date(2026, 7, 22), volume=None),), "2026-07-22T17:00:00+08:00")
        self.assertEqual(result.status, EodStatus.INCOMPLETE_FIELDS)
        self.assertIn("volume", result.missing_required_fields)

    def test_optional_amount_can_be_missing(self) -> None:
        result = self.assess((bar(date(2026, 7, 22), amount=None),), "2026-07-22T17:00:00+08:00")
        self.assertEqual(result.status, EodStatus.COMPLETE_EOD)

    def test_unsupported_is_not_provider_failure(self) -> None:
        result = self.assess((), "2026-07-22T17:00:00+08:00", unsupported=True)
        self.assertEqual(result.status, EodStatus.UNSUPPORTED)
        self.assertNotEqual(result.status, EodStatus.PROVIDER_FAILED)

    def test_provider_failure_is_explicit(self) -> None:
        result = self.assess((), "2026-07-22T17:00:00+08:00", provider_failed=True)
        self.assertEqual(result.status, EodStatus.PROVIDER_FAILED)

    def test_supported_plan_remains_65_and_hstech_absent(self) -> None:
        plan = build_collection_plan(date(2026, 7, 22))
        self.assertEqual(len(plan.tasks), 65)
        self.assertNotIn("hang_seng_tech", {task.sector_key for task in plan.tasks})


if __name__ == "__main__":
    unittest.main()
