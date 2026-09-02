import unittest

from radar.compute.compute_branch_stats import (
    DAYTRADE_MIN_OBS,
    DAYTRADE_MIN_PAIRS,
    DAYTRADE_PAIR_SHARE,
    _BranchAgg,
    auto_in_blocked_by_daytrade,
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
        # 未判定 = (None, None),不是 (False, None)。
        is_dt, rate = daytrade_flag([(100, 90), (100, 90), (100, 90)])
        self.assertIsNone(is_dt)
        self.assertIsNone(rate)

    def test_seven_observations_still_not_determined(self):
        # DAYTRADE_MIN_OBS = 8:7 筆全回吐仍不判定。
        is_dt, rate = daytrade_flag([(100, 100)] * 7)
        self.assertIsNone(is_dt)
        self.assertIsNone(rate)

    def test_payback_threshold_is_inclusive(self):
        # sell 恰為 0.7*net → 視為回吐
        is_dt, rate = daytrade_flag([(100, 70)] * 8)
        self.assertTrue(is_dt)
        self.assertEqual(rate, 1.0)

    def test_just_below_payback_not_counted(self):
        is_dt, rate = daytrade_flag([(100, 69)] * 8)
        self.assertFalse(is_dt)
        self.assertEqual(rate, 0.0)

    def test_rate_boundary_060_is_daytrade(self):
        # 10 筆 6 回吐 = 0.6 → 成立
        is_dt, rate = daytrade_flag([(100, 80)] * 6 + [(100, 0)] * 4)
        self.assertAlmostEqual(rate, 0.6)
        self.assertTrue(is_dt)

    def test_rate_below_boundary_not_daytrade(self):
        # 10 筆 4 回吐 = 0.4
        is_dt, rate = daytrade_flag([(100, 80)] * 4 + [(100, 0)] * 6)
        self.assertAlmostEqual(rate, 0.4)
        self.assertFalse(is_dt)

    def test_explicit_min_obs_overrides_default(self):
        # 影子報表凍結歷史門檻用;線上路徑不傳這個參數。
        is_dt, rate = daytrade_flag([(100, 100)] * 4, min_obs=4)
        self.assertTrue(is_dt)
        self.assertEqual(rate, 1.0)


class BranchDaytradeShareTests(unittest.TestCase):
    """分點層:配對比例取代 pooled 回吐比率。"""

    @staticmethod
    def _agg(determined: int, flagged: int) -> _BranchAgg:
        agg = _BranchAgg()
        for i in range(determined):
            agg.add_pair(i < flagged)
        return agg

    def test_none_pairs_are_ignored(self):
        agg = _BranchAgg()
        for _ in range(50):
            agg.add_pair(None)
        self.assertEqual(agg.dt_pairs_determined, 0)
        self.assertEqual(agg.dt_pairs_flagged, 0)
        self.assertIsNone(agg.is_daytrade())

    def test_19_determined_pairs_not_determined(self):
        # 19 個配對全部被標記,仍不判定(DAYTRADE_MIN_PAIRS = 20)。
        self.assertIsNone(self._agg(19, 19).is_daytrade())

    def test_20_determined_pairs_are_decided(self):
        self.assertIs(self._agg(20, 20).is_daytrade(), True)
        self.assertIs(self._agg(20, 0).is_daytrade(), False)

    def test_share_boundary_020_is_daytrade(self):
        # 100 個可判定配對、20 個標記 = 0.20 恰好成立(分母使兩側皆可精確表示)。
        agg = self._agg(100, 20)
        self.assertEqual(agg.dt_pairs_flagged / agg.dt_pairs_determined, 0.20)
        self.assertIs(agg.is_daytrade(), True)

    def test_share_below_boundary_not_daytrade(self):
        agg = self._agg(100, 19)
        self.assertEqual(agg.dt_pairs_flagged / agg.dt_pairs_determined, 0.19)
        self.assertIs(agg.is_daytrade(), False)

    def test_constants(self):
        self.assertEqual(DAYTRADE_MIN_OBS, 8)
        self.assertEqual(DAYTRADE_MIN_PAIRS, 20)
        self.assertEqual(DAYTRADE_PAIR_SHARE, 0.20)


class AutoInDaytradeGateTests(unittest.TestCase):
    """is_daytrade 為 NULL(未判定)不得擋自動入選,否則新分點永遠選不進來。"""

    def test_null_daytrade_does_not_block_auto_in(self):
        self.assertFalse(auto_in_blocked_by_daytrade(None))

    def test_false_daytrade_does_not_block_auto_in(self):
        self.assertFalse(auto_in_blocked_by_daytrade(False))

    def test_true_daytrade_blocks_auto_in(self):
        self.assertTrue(auto_in_blocked_by_daytrade(True))

    def test_undetermined_branch_agg_does_not_block_auto_in(self):
        # 端到端:配對數不足的分點 → is_daytrade() 為 None → 不擋。
        agg = _BranchAgg()
        agg.add_pair(True)
        self.assertIsNone(agg.is_daytrade())
        self.assertFalse(auto_in_blocked_by_daytrade(agg.is_daytrade()))


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
