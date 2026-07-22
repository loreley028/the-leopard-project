from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout

from leopard_project.cli import main


class Phase1B1CliTests(unittest.TestCase):
    def test_eod_status_is_offline_and_reclassifies_three_intraday_rows(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main([
                "market", "eod-status", "--provider", "ths_public",
                "--as-of", "2026-07-22T15:30:00+08:00",
            ])
        document = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertFalse(document["network_access"])
        self.assertEqual(document["status_counts"]["intraday_snapshot"], 3)
        self.assertNotIn("cookie", output.getvalue().lower())
        self.assertNotIn("authorization", output.getvalue().lower())

    def test_single_sector_compare_uses_checked_replay(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main([
                "provider", "compare", "--sector-key", "semiconductor",
                "--as-of", "2026-07-22T15:30:00+08:00",
            ])
        document = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertFalse(document["network_access"])
        self.assertEqual(document["record"]["source_independence_status"], "shared_upstream")

    def test_validation_mode_cannot_silently_access_network(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            main(["reconcile", "run", "--mode", "validation", "--trade-date", "2026-07-21"])
        self.assertIn("live dual-source validation is not available", str(caught.exception))

    def test_live_flag_requires_explicit_confirmation(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            main([
                "reconcile", "run", "--mode", "validation", "--trade-date", "2026-07-21", "--live",
            ])
        self.assertIn("--confirm-network", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
