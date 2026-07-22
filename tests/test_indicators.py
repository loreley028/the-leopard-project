from __future__ import annotations

import unittest
from decimal import Decimal

from leopard_project.indicators import (
    build_weighted_index_by_date,
    build_weighted_index,
    calculate_indicators,
    classify_volume,
    complete_history_ranks,
    competition_ranks,
    crossed_ma20,
    equal_weight_available_return,
    moving_average,
    percent_change,
)
from leopard_project.models import DataStatus

from fixtures import make_bars


class IndicatorTests(unittest.TestCase):
    def test_percent_change_and_moving_average(self) -> None:
        self.assertEqual(percent_change(Decimal("110"), Decimal("100")), Decimal("10.0"))
        self.assertEqual(moving_average([Decimal("1"), Decimal("2"), Decimal("3")], 2), Decimal("2.5"))

    def test_full_indicator_snapshot(self) -> None:
        bars = make_bars(120)
        snapshot = calculate_indicators(bars)
        self.assertEqual(snapshot.return_5d, percent_change(Decimal("219"), Decimal("214")))
        self.assertEqual(snapshot.return_60d, percent_change(Decimal("219"), Decimal("159")))
        self.assertEqual(snapshot.ma5, Decimal("217"))
        self.assertEqual(snapshot.ma60, Decimal("189.5"))
        self.assertEqual(snapshot.high_20d, Decimal("219"))
        self.assertTrue(snapshot.new_high_20d)
        self.assertEqual(snapshot.data_status, DataStatus.NORMAL)
        self.assertEqual(snapshot, calculate_indicators(bars))

    def test_insufficient_data_is_explicit(self) -> None:
        snapshot = calculate_indicators(make_bars(5))
        self.assertIsNone(snapshot.return_5d)
        self.assertIsNone(snapshot.ma20)
        self.assertIsNone(snapshot.new_high_20d)
        self.assertEqual(snapshot.data_status, DataStatus.HISTORY_INSUFFICIENT)

    def test_short_history_computes_available_periods_but_not_full_rank(self) -> None:
        bars = make_bars(14)
        snapshot = calculate_indicators(bars)
        self.assertIsNotNone(snapshot.return_5d)
        self.assertIsNotNone(snapshot.return_10d)
        self.assertIsNone(snapshot.return_20d)
        self.assertEqual(snapshot.data_status, DataStatus.HISTORY_INSUFFICIENT)
        ranks = complete_history_ranks(
            {"glass": Decimal("5"), "semiconductor": Decimal("3")},
            {"glass": 14, "semiconductor": 131},
        )
        self.assertEqual(ranks, {"semiconductor": 1})

    def test_volume_labels(self) -> None:
        self.assertEqual(classify_volume(Decimal("1.2")), "放量")
        self.assertEqual(classify_volume(Decimal("1.0")), "正常")
        self.assertEqual(classify_volume(Decimal("0.8")), "缩量")

    def test_volume_labels_use_own_ma5_and_ma20(self) -> None:
        bars = list(make_bars(120))
        bars[-1] = bars[-1].model_copy(update={"volume": Decimal("10000"), "amount": None})
        snapshot = calculate_indicators(bars)
        self.assertEqual(snapshot.volume_label_5d, "放量")
        self.assertEqual(snapshot.volume_label_20d, "放量")
        self.assertIsNone(snapshot.amount_vs_5d_avg)

    def test_new_low(self) -> None:
        snapshot = calculate_indicators(make_bars(20, descending=True))
        self.assertTrue(snapshot.new_low_20d)
        self.assertFalse(snapshot.new_high_20d)

    def test_ma20_crossings(self) -> None:
        above = [Decimal("100")] * 20 + [Decimal("110")]
        below = [Decimal("100")] * 20 + [Decimal("90")]
        self.assertEqual(crossed_ma20(above), (True, False))
        self.assertEqual(crossed_ma20(below), (False, True))

    def test_competition_ranking_excludes_missing_and_preserves_ties(self) -> None:
        ranks = competition_ranks({"a": Decimal("3"), "b": Decimal("2"), "c": Decimal("2"), "missing": None})
        self.assertEqual(ranks, {"a": 1, "b": 2, "c": 2})

    def test_custom_index_is_deterministic(self) -> None:
        returns = {
            "881133": [Decimal("0"), Decimal("0.02"), Decimal("-0.01")],
            "881134": [Decimal("0"), Decimal("0.00"), Decimal("0.03")],
        }
        weights = {"881133": Decimal("0.5"), "881134": Decimal("0.5")}
        first = build_weighted_index(returns, weights)
        second = build_weighted_index(returns, weights)
        self.assertEqual(first, second)
        self.assertEqual(first, (Decimal("1000"), Decimal("1010.000"), Decimal("1020.1000000")))

    def test_custom_index_rejects_invalid_weights(self) -> None:
        with self.assertRaises(ValueError):
            build_weighted_index({"a": [Decimal("0")]}, {"a": Decimal("0.9")})

    def test_custom_index_uses_date_intersection(self) -> None:
        from datetime import date
        common = date(2026, 7, 21)
        result = build_weighted_index_by_date(
            {
                "a": {date(2026, 7, 20): Decimal("0"), common: Decimal("0.02")},
                "b": {common: Decimal("0.04"), date(2026, 7, 22): Decimal("0.01")},
            },
            {"a": Decimal("0.5"), "b": Decimal("0.5")},
        )
        self.assertEqual(result, ((common, Decimal("1000")),))

    def test_custom_index_rejects_missing_component_series(self) -> None:
        with self.assertRaises(ValueError):
            build_weighted_index_by_date(
                {"a": {}, "b": {}},
                {"a": Decimal("0.5"), "b": Decimal("0.5")},
            )

    def test_hotel_constituent_return_excludes_missing_and_is_explicit_when_empty(self) -> None:
        self.assertEqual(
            equal_weight_available_return([Decimal("0.01"), None, Decimal("0.03")]),
            Decimal("0.02"),
        )
        self.assertIsNone(equal_weight_available_return([None, None]))


if __name__ == "__main__":
    unittest.main()
