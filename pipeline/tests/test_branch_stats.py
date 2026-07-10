import unittest

from radar.compute.compute_branch_stats import (
    credibility_score,
    daytrade_flag,
    merge_consecutive_events,
    price_percentile,
    recency_factor,
)

# 交易日曆(含未成為資格日的 01-05):判定連續用。
CAL = ["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"]
IDX = {d: i for i, d in enumerate(CAL)}


class MergeEventsTests(unittest.TestCase):
    def test_consecutive_days_merge_to_first_day(self):
        self.assertEqual(
            merge_consecutive_events(["2026-01-01", "2026-01-02"], IDX),
            ["2026-01-01"],
        )

    def test_gap_breaks_into_two_events(self):
        # 01-02 與 01-05 之間隔了非資格交易日(索引 1→2 為相鄰,故要拉開)
        self.assertEqual(
            merge_consecutive_events(["2026-01-01", "2026-01-05"], IDX),
            ["2026-01-01", "2026-01-05"],
        )

    def test_mixed_runs(self):
        self.assertEqual(
            merge_consecutive_events(
                ["2026-01-01", "2026-01-02", "2026-01-06", "2026-01-07"], IDX),
            ["2026-01-01", "2026-01-06"],
        )

    def test_three_consecutive_single_event(self):
        self.assertEqual(
            merge_consecutive_events(
                ["2026-01-05", "2026-01-06", "2026-01-07"], IDX),
            ["2026-01-05"],
        )

    def test_unknown_date_is_standalone(self):
        self.assertEqual(
            merge_consecutive_events(["2025-12-31", "2026-01-01"], IDX),
            ["2025-12-31", "2026-01-01"],
        )


class DaytradeTests(unittest.TestCase):
    def test_below_min_obs_not_determined(self):
        is_dt, rate = daytrade_flag([(100, 90), (100, 90), (100, 90)])
        self.assertFalse(is_dt)
        self.assertIsNone(rate)

    def test_payback_threshold_is_inclusive(self):
        # sell 恰為 0.7*net → 視為回吐
        is_dt, rate = daytrade_flag([(100, 70)] * 4)
        self.assertTrue(is_dt)
        self.assertEqual(rate, 1.0)

    def test_just_below_payback_not_counted(self):
        is_dt, rate = daytrade_flag([(100, 69)] * 4)
        self.assertFalse(is_dt)
        self.assertEqual(rate, 0.0)

    def test_rate_boundary_060_is_daytrade(self):
        # 5 筆 3 回吐 = 0.6 → 成立
        is_dt, rate = daytrade_flag(
            [(100, 80), (100, 80), (100, 80), (100, 0), (100, 0)])
        self.assertAlmostEqual(rate, 0.6)
        self.assertTrue(is_dt)

    def test_rate_below_boundary_not_daytrade(self):
        # 5 筆 2 回吐 = 0.4
        is_dt, rate = daytrade_flag(
            [(100, 80), (100, 80), (100, 0), (100, 0), (100, 0)])
        self.assertAlmostEqual(rate, 0.4)
        self.assertFalse(is_dt)


class PricePercentileTests(unittest.TestCase):
    def test_midpoint(self):
        self.assertEqual(price_percentile(5, 0, 10), 0.5)

    def test_at_low(self):
        self.assertEqual(price_percentile(0, 0, 10), 0.0)

    def test_at_high(self):
        self.assertEqual(price_percentile(10, 0, 10), 1.0)

    def test_zero_range_returns_half(self):
        self.assertEqual(price_percentile(5, 5, 5), 0.5)

    def test_none_returns_half(self):
        self.assertEqual(price_percentile(None, 0, 10), 0.5)


class RecencyTests(unittest.TestCase):
    def test_no_recent_matured_is_zero(self):
        self.assertEqual(recency_factor(None, 3.0), 0.0)

    def test_recent_negative_is_zero(self):
        self.assertEqual(recency_factor(-1.0, 3.0), 0.0)

    def test_all_period_nonpositive_but_recent_positive_is_one(self):
        self.assertEqual(recency_factor(2.0, 0.0), 1.0)
        self.assertEqual(recency_factor(2.0, None), 1.0)

    def test_decay_ratio(self):
        self.assertEqual(recency_factor(2.0, 4.0), 0.5)

    def test_recent_stronger_capped_at_one(self):
        self.assertEqual(recency_factor(5.0, 2.0), 1.0)


class CredibilityScoreTests(unittest.TestCase):
    def test_win_rate_40_scores_zero(self):
        self.assertEqual(
            credibility_score(40.0, 0.0, 1.0, 0.0, 0.0), 0.0)

    def test_win_rate_70_full_component(self):
        # 只有勝率項:0.30 * 100 = 30
        self.assertEqual(
            credibility_score(70.0, None, 1.0, 0.0, 0.0), 30.0)

    def test_avg_ret5_full_component(self):
        # +5% → 0.25 * 100 = 25
        self.assertEqual(
            credibility_score(None, 5.0, 1.0, 0.0, 0.0), 25.0)

    def test_avg_ret5_zero_component(self):
        self.assertEqual(
            credibility_score(None, 0.0, 1.0, 0.0, 0.0), 0.0)

    def test_amount_log_scale(self):
        # 10 億 → 0.10 * 100 = 10;千萬 → 0
        self.assertEqual(
            credibility_score(None, None, 1.0, 1e9, 0.0), 10.0)
        self.assertEqual(
            credibility_score(None, None, 1.0, 1e7, 0.0), 0.0)

    def test_buy_percentile_low_is_good(self):
        # 買在低點 percentile=0 → (1-0)*0.15*100 = 15
        self.assertEqual(
            credibility_score(None, None, 0.0, 0.0, 0.0), 15.0)

    def test_recency_component(self):
        self.assertEqual(
            credibility_score(None, None, 1.0, 0.0, 1.0), 20.0)

    def test_missing_win_and_ret_score_zero_components(self):
        # 全缺 + percentile=1 + amount 0 + recency 0 → 0
        self.assertEqual(
            credibility_score(None, None, 1.0, 0.0, 0.0), 0.0)


if __name__ == "__main__":
    unittest.main()
