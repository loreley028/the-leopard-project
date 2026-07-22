from __future__ import annotations

import json
import unittest
from datetime import date
from decimal import Decimal

from pydantic import ValidationError

from leopard_project.models import DataStatus, SupportStatus
from leopard_project.support import (
    CollectionPlan, UnsupportedSector, build_collection_plan, collection_success_rate,
    failure_alert_keys, load_support_policy, pdf_report_includes_sector, ranking_keys,
    retry_keys, supported_indicator_keys, validate_support_policy,
)


class SupportScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = load_support_policy()
        cls.plan = build_collection_plan(date(2026, 7, 22))

    def test_catalog_support_and_denominator_are_66_65_1(self) -> None:
        self.assertEqual(self.plan.total_business_sectors, 66)
        self.assertEqual(len(self.plan.tasks), 65)
        self.assertEqual(len(self.plan.unsupported_sectors), 1)
        self.assertEqual(self.plan.collection_denominator, 65)
        self.assertEqual(collection_success_rate(64, self.plan), Decimal(64) / Decimal(65))

    def test_hstech_is_explicitly_unsupported_not_failed(self) -> None:
        row = self.plan.unsupported_sectors[0]
        self.assertEqual(row.sector_key, "hang_seng_tech")
        self.assertEqual(row.canonical_symbol, "HSTECH")
        self.assertEqual(row.support_status, SupportStatus.UNSUPPORTED)
        self.assertEqual(row.data_status, DataStatus.UNSUPPORTED)
        self.assertEqual(row.reason_code, "cross_market_not_integrated")
        self.assertEqual(row.display_text, "暂不支持")
        self.assertNotEqual(row.data_status, DataStatus.PROVIDER_FAILED)

    def test_hstech_is_excluded_from_collection_indicators_rank_alerts_and_retry(self) -> None:
        self.assertNotIn("hang_seng_tech", {task.sector_key for task in self.plan.tasks})
        self.assertNotIn("hang_seng_tech", supported_indicator_keys(self.plan))
        self.assertNotIn("hang_seng_tech", ranking_keys(self.plan))
        self.assertEqual(failure_alert_keys(["hang_seng_tech"], self.plan), ())
        self.assertEqual(retry_keys(["hang_seng_tech"], self.plan), ())
        self.assertFalse(any("HSTECH" in task.provider_symbols or "HS2083" in task.provider_symbols for task in self.plan.tasks))

    def test_pdf_report_remains_independent(self) -> None:
        self.assertTrue(pdf_report_includes_sector("hang_seng_tech"))
        self.assertTrue(self.policy["pdf_report_independence"]["unsupported_market_data_must_not_remove_transcript_content"])

    def test_special_a_share_policies_are_preserved(self) -> None:
        hotel = next(task for task in self.plan.tasks if task.sector_key == "hotel_catering")
        glass = next(task for task in self.plan.tasks if task.sector_key == "glass_substrate")
        self.assertEqual(hotel.mapping_type, "proxy")
        self.assertEqual(hotel.provider_symbols, ("881160",))
        self.assertEqual(hotel.data_status, DataStatus.PROXY)
        self.assertEqual(glass.provider_symbols, ("886111",))
        self.assertEqual(glass.data_status, DataStatus.SHORT_HISTORY)
        self.assertNotIn("glass_substrate", ranking_keys(self.plan, require_full_history=True))
        self.assertEqual(sum(task.mapping_type == "custom_composite" for task in self.plan.tasks), 3)

    def test_plan_is_deterministic_and_rejects_count_drift(self) -> None:
        self.assertEqual(self.plan, build_collection_plan(date(2026, 7, 22)))
        changed = json.loads(json.dumps(self.policy))
        changed["supported_market_sectors"] = 64
        with self.assertRaises(ValueError):
            build_collection_plan(date(2026, 7, 22), changed)

    def test_unknown_state_is_rejected(self) -> None:
        row = self.plan.unsupported_sectors[0].model_dump()
        row["data_status"] = "unexpected"
        with self.assertRaises(ValidationError):
            UnsupportedSector(**row)

    def test_provider_roles_are_allow_listed_and_not_production(self) -> None:
        validate_support_policy(self.policy)
        roles = set(self.policy["provider_roles"].values())
        self.assertNotIn("production_primary", roles)
        self.assertNotIn("production_fallback", roles)


if __name__ == "__main__":
    unittest.main()
