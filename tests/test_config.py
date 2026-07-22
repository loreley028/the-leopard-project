from __future__ import annotations

import json
import unittest
from collections import Counter
from datetime import date
from pathlib import Path

from leopard_project.config import CONFIG_DIR, load_seed_bundle, mapping_is_eligible, normalize_alias
from leopard_project.mappings import approve_research_version
from leopard_project.models import MappingStatus


class ConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = load_seed_bundle()

    def test_sector_and_group_counts(self) -> None:
        self.assertEqual(len(self.bundle.sectors), 66)
        counts = Counter(sector.category_level_1 for sector in self.bundle.sectors)
        self.assertEqual(
            list(counts.items()),
            [
                ("科技硬件与通信", 13),
                ("科技软件、传媒与互联网", 9),
                ("医药、消费与服务", 15),
                ("大金融", 5),
                ("新能源、汽车与高端制造", 7),
                ("资源、能源与周期", 12),
                ("军工、航天与运输", 4),
                ("地产", 1),
            ],
        )

    def test_sector_keys_names_and_order_are_unique(self) -> None:
        self.assertEqual(len({sector.sector_key for sector in self.bundle.sectors}), 66)
        self.assertEqual(len({sector.sector_name for sector in self.bundle.sectors}), 66)
        self.assertEqual([sector.overall_order for sector in self.bundle.sectors], list(range(1, 67)))

    def test_alias_normalization(self) -> None:
        self.assertEqual(normalize_alias("AI应用", self.bundle), "ai_applications")
        self.assertEqual(normalize_alias("锂电池", self.bundle), "battery_lithium")
        self.assertEqual(normalize_alias("光模块", self.bundle), "cpo")
        self.assertIsNone(normalize_alias("不存在的板块", self.bundle))

    def test_mapping_research_state_and_sources(self) -> None:
        statuses = Counter(mapping.mapping_status for mapping in self.bundle.mappings)
        self.assertEqual(statuses[MappingStatus.CONFIRMED], 62)
        self.assertEqual(statuses[MappingStatus.CANDIDATE], 4)
        self.assertTrue(all(mapping.primary_source_url for mapping in self.bundle.mappings))
        self.assertTrue(all(not mapping.user_confirmed for mapping in self.bundle.mappings))
        self.assertTrue(all(mapping.effective_date is None for mapping in self.bundle.mappings))

    def test_unapproved_mappings_cannot_enter_daily_job(self) -> None:
        self.assertFalse(any(mapping_is_eligible(mapping, date(2026, 7, 22)) for mapping in self.bundle.mappings))

    def test_custom_compositions_are_exact_and_weights_sum_to_one(self) -> None:
        document = json.loads((CONFIG_DIR / "custom_compositions_v2_3.json").read_text(encoding="utf-8"))
        self.assertEqual(
            {row["symbol"] for row in document["compositions"]},
            {"CUSTOM_HOTEL_CATERING", "CUSTOM_FOOD_BEVERAGE", "CUSTOM_PV_STORAGE", "CUSTOM_OIL_PETROCHEM"},
        )
        weighted = [row for row in document["compositions"] if "components" in row]
        self.assertTrue(all(sum(component["weight"] for component in row["components"]) == 1 for row in weighted))
        custom_mappings = [mapping for mapping in self.bundle.mappings if mapping.primary_symbol.startswith("CUSTOM_")]
        self.assertEqual(len(custom_mappings), 4)

    def test_primary_symbols_are_unique(self) -> None:
        symbols = [mapping.primary_symbol for mapping in self.bundle.mappings]
        self.assertEqual(len(symbols), len(set(symbols)))

    def test_hang_seng_tech_keeps_hk_identifiers(self) -> None:
        mapping = next(mapping for mapping in self.bundle.mappings if mapping.sector_key == "hang_seng_tech")
        self.assertEqual(mapping.ths_display_code, "HS2083")
        self.assertEqual(mapping.primary_symbol, "HS2083")
        self.assertIn("HSTECH", mapping.backup_symbols)

    def test_batch_approval_creates_new_version_without_overwrite(self) -> None:
        source_path = CONFIG_DIR / "sector_mappings_v2_3.json"
        original = json.loads(source_path.read_text(encoding="utf-8"))
        before = json.loads(json.dumps(original))
        approved = approve_research_version(original, "v2.3-20260722")
        self.assertEqual(original, before)
        self.assertEqual(approved["parent_mapping_version"], "v2.3-20260722")
        self.assertEqual(approved["mapping_version"], "v2.3-20260722-approved")
        self.assertTrue(all(row["user_confirmed"] for row in approved["mappings"]))
        self.assertFalse(any(row["included_in_daily_job"] for row in approved["mappings"]))

    def test_batch_approval_requires_effective_date_for_daily_job(self) -> None:
        original = json.loads((CONFIG_DIR / "sector_mappings_v2_3.json").read_text(encoding="utf-8"))
        approved = approve_research_version(original, "v2.3-20260722", effective_date=date(2026, 7, 23))
        self.assertEqual(sum(row["included_in_daily_job"] for row in approved["mappings"]), 66)
        original["mappings"][0]["provider_key"] = ""
        incomplete = approve_research_version(original, "v2.3-20260722", effective_date=date(2026, 7, 23))
        self.assertFalse(incomplete["mappings"][0]["included_in_daily_job"])


if __name__ == "__main__":
    unittest.main()
