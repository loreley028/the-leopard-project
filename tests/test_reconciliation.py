from __future__ import annotations

import unittest
from datetime import date, datetime
from decimal import Decimal

from leopard_project.eod import EodAssessment, EodStatus
from leopard_project.models import Market
from leopard_project.provider_lineage import IndependenceStatus, compare_lineages, lineage_by_name
from leopard_project.reconciliation import (
    ReconciliationStatus, ReconciliationValues, SourceSnapshot, deterministic_run_id,
    load_reconciliation_policy, reconcile_sector, run_controlled_replay,
)


AS_OF = datetime.fromisoformat("2026-07-22T17:00:00+08:00")
DAY = date(2026, 7, 22)


def eod(status: EodStatus = EodStatus.COMPLETE_EOD, actual: date = DAY) -> EodAssessment:
    return EodAssessment(
        policy_version="fixture", provider_name="fixture", market=Market.CN_A,
        requested_as_of=AS_OF, expected_trade_date=DAY, actual_trade_date=actual,
        status=status, eligible_for_eod=status == EodStatus.COMPLETE_EOD, row_count=1,
    )


def values(close: str = "100", pct: str = "1", volume: str | None = "1000", amount: str | None = "2000") -> ReconciliationValues:
    return ReconciliationValues(
        close=Decimal(close), pct_change=Decimal(pct),
        volume=None if volume is None else Decimal(volume),
        amount=None if amount is None else Decimal(amount),
    )


class ReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = load_reconciliation_policy()
        cls.public = lineage_by_name("ths_public_validation")
        cls.akshare = lineage_by_name("akshare_ths_research")
        cls.independent = cls.akshare.model_copy(update={
            "provider_name": "authorized_fixture",
            "upstream_vendor": "IndependentVendor",
            "endpoint_host": "api.independent.invalid",
            "documented_api": True,
            "licensing_status": "authorized",
        })
        cls.public_authorized = cls.public.model_copy(update={
            "documented_api": True, "licensing_status": "authorized",
        })

    def reconcile(self, source_a: SourceSnapshot | None, source_b: SourceSnapshot | None, *, independent: bool = True):
        return reconcile_sector(
            reconciliation_run_id="fixture-run", requested_as_of=AS_OF,
            expected_trade_date=DAY, sector_key="semiconductor", sector_name="半导体",
            canonical_symbol="881121", source_a=source_a, source_b=source_b,
            lineage_a=self.public_authorized,
            lineage_b=self.independent if independent else self.akshare,
            created_at=AS_OF, policy=self.policy,
        )

    def snapshot(self, value: ReconciliationValues, status: EodStatus = EodStatus.COMPLETE_EOD, actual: date = DAY) -> SourceSnapshot:
        return SourceSnapshot(provider_name="fixture", eod=eod(status, actual), values=value)

    def test_lineage_serialization_and_vendor_level_assessment(self) -> None:
        self.assertEqual(self.akshare.model_dump(mode="json")["provider_role"], "research_provider")
        self.assertEqual(compare_lineages(self.public, self.akshare), IndependenceStatus.SHARED_UPSTREAM)

    def test_same_provider_is_shared_not_independent(self) -> None:
        self.assertEqual(compare_lineages(self.public, self.public), IndependenceStatus.SHARED_UPSTREAM)

    def test_unknown_lineage_is_not_promoted(self) -> None:
        unknown = self.akshare.model_copy(update={"upstream_vendor": None})
        self.assertEqual(compare_lineages(self.public, unknown), IndependenceStatus.UNKNOWN)

    def test_matched(self) -> None:
        result = self.reconcile(self.snapshot(values()), self.snapshot(values("100.005", "1.005", "1001")))
        self.assertEqual(result.reconciliation_status, ReconciliationStatus.MATCHED)

    def test_acceptable_difference(self) -> None:
        result = self.reconcile(self.snapshot(values()), self.snapshot(values("100.05", "1.03", "1005")))
        self.assertEqual(result.reconciliation_status, ReconciliationStatus.ACCEPTABLE_DIFFERENCE)

    def test_material_difference(self) -> None:
        result = self.reconcile(self.snapshot(values()), self.snapshot(values("100.2", "1.1", "1005")))
        self.assertEqual(result.reconciliation_status, ReconciliationStatus.MATERIAL_DIFFERENCE)

    def test_manual_review_threshold(self) -> None:
        result = self.reconcile(self.snapshot(values()), self.snapshot(values("101", "2", "1100")))
        self.assertEqual(result.reconciliation_status, ReconciliationStatus.MANUAL_REVIEW)

    def test_shared_upstream_cannot_count_as_matched(self) -> None:
        result = self.reconcile(self.snapshot(values()), self.snapshot(values()), independent=False)
        self.assertEqual(result.reconciliation_status, ReconciliationStatus.SOURCE_NOT_INDEPENDENT)

    def test_intraday_is_excluded(self) -> None:
        result = self.reconcile(self.snapshot(values(), EodStatus.INTRADAY_SNAPSHOT), self.snapshot(values()))
        self.assertEqual(result.reconciliation_status, ReconciliationStatus.INTRADAY_EXCLUDED)

    def test_stale_source_is_excluded(self) -> None:
        result = self.reconcile(self.snapshot(values(), EodStatus.STALE_SNAPSHOT), self.snapshot(values()))
        self.assertEqual(result.reconciliation_status, ReconciliationStatus.STALE_SOURCE)

    def test_future_snapshot_blocks(self) -> None:
        result = self.reconcile(self.snapshot(values(), EodStatus.FUTURE_SNAPSHOT), self.snapshot(values()))
        self.assertEqual(result.reconciliation_status, ReconciliationStatus.FUTURE_SNAPSHOT)

    def test_provider_failure_is_explicit(self) -> None:
        result = self.reconcile(self.snapshot(values(), EodStatus.PROVIDER_FAILED), self.snapshot(values()))
        self.assertEqual(result.reconciliation_status, ReconciliationStatus.PROVIDER_FAILED)

    def test_required_field_missing(self) -> None:
        result = self.reconcile(self.snapshot(values(volume=None)), self.snapshot(values()))
        self.assertEqual(result.reconciliation_status, ReconciliationStatus.FIELD_MISSING)

    def test_optional_amount_missing_is_recorded_and_continues(self) -> None:
        result = self.reconcile(self.snapshot(values(amount=None)), self.snapshot(values(amount=None)))
        self.assertEqual(result.reconciliation_status, ReconciliationStatus.MATCHED)
        self.assertIn("optional_amount_missing", result.anomaly_codes)

    def test_calendar_mismatch(self) -> None:
        result = self.reconcile(
            self.snapshot(values(), actual=date(2026, 7, 21)),
            self.snapshot(values(), actual=DAY),
        )
        self.assertEqual(result.reconciliation_status, ReconciliationStatus.CALENDAR_MISMATCH)

    def test_one_source_missing(self) -> None:
        result = self.reconcile(self.snapshot(values()), None)
        self.assertEqual(result.reconciliation_status, ReconciliationStatus.ONE_SOURCE_MISSING)

    def test_deterministic_run_and_reconciliation(self) -> None:
        first = deterministic_run_id(self.policy.reconciliation_version, "replay", date(2026, 7, 21))
        second = deterministic_run_id(self.policy.reconciliation_version, "replay", date(2026, 7, 21))
        self.assertEqual(first, second)
        left = self.reconcile(self.snapshot(values()), self.snapshot(values()))
        right = self.reconcile(self.snapshot(values()), self.snapshot(values()))
        self.assertEqual(left, right)

    def test_thresholds_are_loaded_from_versioned_policy(self) -> None:
        self.assertEqual(self.policy.close_difference_pct_matched, Decimal("0.01"))
        self.assertEqual(self.policy.manual_review_threshold, Decimal("0.50"))

    def test_controlled_replay_covers_exactly_65_without_hstech(self) -> None:
        summary, details = run_controlled_replay()
        self.assertEqual(summary["plan_sector_count"], 65)
        self.assertEqual(len(details["records"]), 65)
        self.assertEqual(summary["intraday_snapshot_count"], 3)
        self.assertNotIn("hang_seng_tech", {row["sector_key"] for row in details["records"]})


if __name__ == "__main__":
    unittest.main()
