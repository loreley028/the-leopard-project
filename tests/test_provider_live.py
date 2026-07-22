from __future__ import annotations

import os
import unittest
from datetime import date

from leopard_project.models import Market
from leopard_project.providers import ThsPublicValidationProvider

try:
    import pytest
    live_marker = pytest.mark.live
except ModuleNotFoundError:  # unittest remains the dependency-free local fallback
    live_marker = lambda value: value


@live_marker
@unittest.skipUnless(os.environ.get("LEOPARD_RUN_LIVE") == "1", "set LEOPARD_RUN_LIVE=1 for explicit network test")
class LiveProviderTests(unittest.TestCase):
    def test_representative_industry_endpoint(self) -> None:
        bars = ThsPublicValidationProvider().historical_daily_bars(
            "881121", date(2026, 1, 1), date.today(), Market.CN_A
        )
        self.assertGreaterEqual(len(bars), 120)


if __name__ == "__main__":
    unittest.main()
