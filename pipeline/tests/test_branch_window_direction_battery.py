"""買低賣高「窗口方向」樣本外 battery(唯讀,決定已上線面板去留)。

這裡驗的是**協定本身有沒有被正確執行**:切分落在交易日、episode 在各半段獨立
重建、消失的 pair 不被靜默丟掉、安慰劑同時吃兩個帶寬、lag 用的是次一*市場*日,
以及四條事先寫死的撤回條件在**邊界上**的行為。不驗「誰是關鍵分點」——那是資料
的事,不是程式的事。
"""
import json
import tracemalloc
import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import radar.config as config
import radar.db as db
from radar import schema
from radar.cli import main
from radar.compute.branch_window_direction_battery import (
    BACKWARD_PULL_OBS_EXP,
    BACKWARD_STRONG_OBS_EXP,
    EVAL_MIN_KNOWN_PER_SIDE,
    FLAG_MIN_KNOWN_PER_SIDE,
    FLAG_MIN_RATE,
    FORWARD_MIN_OBS_EXP,
    LAG_MIN_RETAINED_RATIO,
    PLACEBO_BAND,
    PLACEBO_MAX_OBS_EXP,
    _HalfCounts,
    _PairAccum,
    build_branch_window_direction_battery,
    build_pair_counts,
    build_verdicts,
    is_flagged,
    match_placebo,
    percentile_observation,
    probability_exceeds,
    split_window,
    write_branch_window_direction_battery,
)

# 價格以 20 天為週期,所以**任何** 20 個連續市場日的窗口都涵蓋剛好一個完整週期,
# min/max 恆為 (100, 195)。於是分位只由該日自己的收盤決定:pctile = p / 19,
# 其中 p = 市場日序號 % 20。低買(<=0.40)是 p <= 7,高賣(>=0.60)是 p >= 12。
# 往前看與往後看因此在同一份價格上都可控,不必為兩個方向各造一組資料。
_PERIOD = 20


def _market_days(start: date, count: int) -> list[str]:
    days: list[str] = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def _close_for(index: int) -> float:
    return 100.0 + 5.0 * (index % _PERIOD)


# 形成／評估半段各 40 個市場日;每個半段的偏移量都對齊週期起點。
_BUY_OFFSETS = (0, 2, 4, 6, 10, 20, 22, 24, 26, 30)    # p: 8 個 <=7(命中)、2 個 =10
_SELL_OFFSETS = (8, 12, 14, 16, 18, 28, 32, 34, 36, 38)  # p: 8 個 >=12(命中)、2 個 =8
_NOISE_BUY_OFFSETS = (9, 11, 13, 15, 17, 19, 29, 31, 33, 35)   # p 全部 >7:全不命中
_NOISE_SELL_OFFSETS = (1, 3, 5, 7, 21, 23, 25, 27, 37, 39)     # p 全部 <12:8 個不命中


class SplitAndEpisodeRebuildTests(unittest.TestCase):
    """切分與 episode 重建 —— 不碰資料庫的純函式層。"""

    def setUp(self):
        self.days = _market_days(date(2026, 1, 5), 120)
        self.index = {day: i for i, day in enumerate(self.days)}
        self.rows = {
            day: {"open": _close_for(i), "close": _close_for(i)}
            for i, day in enumerate(self.days)
        }

    def test_split_lands_on_trading_days_and_halves_are_contiguous(self):
        split = split_window(trading_days=self.days, window_days=80)
        for key in ("window_from", "window_to", "formation_from",
                    "formation_to", "evaluation_from", "evaluation_to"):
            self.assertIn(split[key], self.days, key)
        # 邊界日期本身必須是真的市場交易日,不是把日曆對半除出來的日期。
        self.assertEqual(split["formation_from"], self.days[40])
        self.assertEqual(split["formation_to"], self.days[79])
        self.assertEqual(split["evaluation_from"], self.days[80])
        self.assertEqual(split["evaluation_to"], self.days[119])
        self.assertEqual(split["formation_market_days"], 40)
        self.assertEqual(split["evaluation_market_days"], 40)
        self.assertFalse(split["window_truncated"])
        # 相鄰但不重疊:評估半段的第一天就是形成半段最後一天的次一交易日。
        self.assertEqual(
            self.index[split["evaluation_from"]],
            self.index[split["formation_to"]] + 1,
        )
        # 邊界跨過一個週末,所以「對半切」不可能只是日曆天數除以二。
        self.assertGreater(
            date.fromisoformat(split["evaluation_from"])
            - date.fromisoformat(split["formation_to"]),
            timedelta(days=1),
        )

    def test_odd_window_gives_the_extra_trading_day_to_the_evaluation_half(self):
        split = split_window(trading_days=self.days, window_days=81)
        self.assertEqual(split["formation_market_days"], 40)
        self.assertEqual(split["evaluation_market_days"], 41)

    def test_truncated_window_is_flagged_not_padded(self):
        split = split_window(trading_days=self.days[:10], window_days=80)
        self.assertTrue(split["window_truncated"])
        self.assertEqual(split["window_market_days"], 10)
        self.assertEqual(split["window_from"], self.days[0])

    def test_run_straddling_the_boundary_becomes_one_episode_in_each_half(self):
        split = split_window(trading_days=self.days, window_days=80)
        halves = (
            ("formation", split["formation_from"], split["formation_to"]),
            ("evaluation", split["evaluation_from"], split["evaluation_to"]),
        )
        straddling = [self.days[78], self.days[79], self.days[80], self.days[81]]
        accum = build_pair_counts(
            dates_by_side={"buy": straddling, "sell": []},
            abs_pct_by_date={day: 2.0 for day in straddling},
            halves=halves, market_index=self.index,
            market_days=self.days, row_by_date=self.rows,
        )
        # 四個相鄰市場日,在整段窗口上會是一段;各半段獨立重建後是各一段。
        self.assertEqual(accum.formation.buy_episodes, 1)
        self.assertEqual(accum.evaluation.buy_episodes, 1)
        # 而且評估半段那一段的事件日是 days[80],不是 days[78]。
        self.assertEqual(
            accum.evaluation.hits[("backward", False, "buy")],
            1 if (80 % _PERIOD) / 19 <= 0.40 else 0,
        )

    def test_lag_uses_the_next_market_day_not_the_next_calendar_day(self):
        # days[79] 是週五(其後為週末),次一市場日是 days[80] 而非日曆次日。
        friday = self.days[79]
        self.assertEqual(
            date.fromisoformat(self.days[80]) - date.fromisoformat(friday),
            timedelta(days=3),
        )
        calendar_next = (
            date.fromisoformat(friday) + timedelta(days=1)
        ).isoformat()
        self.assertNotIn(calendar_next, self.index)

        percentile, status = percentile_observation(
            direction="backward", lagged=True, event_date=friday,
            market_index=self.index, market_days=self.days, row_by_date=self.rows,
        )
        self.assertEqual(status, "known")
        # 參考價是 days[80] 的收盤(p=0 → 100),窗口仍是 days[60..79]。
        self.assertAlmostEqual(percentile, 0.0, places=6)
        unlagged, unlagged_status = percentile_observation(
            direction="backward", lagged=False, event_date=friday,
            market_index=self.index, market_days=self.days, row_by_date=self.rows,
        )
        self.assertEqual(unlagged_status, "known")
        self.assertAlmostEqual(unlagged, 19 / 19, places=6)

    def test_lag_at_the_last_market_day_is_immature_not_unknown(self):
        percentile, status = percentile_observation(
            direction="backward", lagged=True, event_date=self.days[-1],
            market_index=self.index, market_days=self.days, row_by_date=self.rows,
        )
        self.assertIsNone(percentile)
        self.assertEqual(status, "immature")

    def test_immature_and_unknown_never_enter_a_denominator(self):
        half = _HalfCounts()
        half.add_observation(direction="forward", lagged=False, side="buy",
                             percentile=None, status="immature")
        half.add_observation(direction="forward", lagged=False, side="buy",
                             percentile=None, status="unknown")
        self.assertEqual(half.known[("forward", False, "buy")], 0)
        self.assertEqual(half.hits[("forward", False, "buy")], 0)


class PlaceboMatcherTests(unittest.TestCase):
    """張數配對安慰劑:兩個帶寬都要吃,而且永遠不會抽到被標記的 pair 自己。"""

    @staticmethod
    def _pair(buy_episodes: int, sell_episodes: int, median_abs_pct: float) -> _PairAccum:
        accum = _PairAccum()
        accum.formation.buy_episodes = buy_episodes
        accum.formation.sell_episodes = sell_episodes
        accum.formation.median_abs_pct = median_abs_pct
        return accum

    def setUp(self):
        import random

        self.rng = random.Random(1)
        self.accums = {
            "FLAGGED": self._pair(20, 20, 4.0),
            "SIZE_OK": self._pair(20, 20, 4.0),          # 兩個帶寬都在內
            "COUNT_OUT": self._pair(30, 20, 4.0),        # 買側 episode 數超出 ±25%
            "SELL_COUNT_OUT": self._pair(20, 30, 4.0),   # 賣側 episode 數超出
            "PCT_OUT": self._pair(20, 20, 8.0),          # abs(pct) 中位數超出 ±25%
        }

    def test_matcher_requires_both_bands(self):
        matched = match_placebo(
            flagged=["FLAGGED"], flagged_set={"FLAGGED"},
            accums=self.accums, rng=self.rng,
        )
        self.assertEqual(matched, {"FLAGGED": "SIZE_OK"})

    def test_matcher_never_draws_the_flagged_pair_itself(self):
        only_itself = {"FLAGGED": self.accums["FLAGGED"]}
        matched = match_placebo(
            flagged=["FLAGGED"], flagged_set={"FLAGGED"},
            accums=only_itself, rng=self.rng,
        )
        self.assertEqual(matched, {})

    def test_matcher_never_draws_another_flagged_pair(self):
        accums = dict(self.accums)
        accums["FLAGGED_TWIN"] = self._pair(20, 20, 4.0)
        del accums["SIZE_OK"]
        matched = match_placebo(
            flagged=["FLAGGED", "FLAGGED_TWIN"],
            flagged_set={"FLAGGED", "FLAGGED_TWIN"},
            accums=accums, rng=self.rng,
        )
        self.assertEqual(matched, {})

    def test_band_edges_are_inclusive_on_both_dimensions(self):
        accums = {
            "FLAGGED": self._pair(20, 20, 4.0),
            "EDGE_LOW": self._pair(15, 15, 3.0),    # 剛好 -25%
            "EDGE_HIGH": self._pair(25, 25, 5.0),   # 剛好 +25%
        }
        self.assertEqual(PLACEBO_BAND, 0.25)
        matched = match_placebo(
            flagged=["FLAGGED"], flagged_set={"FLAGGED"}, accums=accums, rng=self.rng,
        )
        self.assertIn(matched["FLAGGED"], {"EDGE_LOW", "EDGE_HIGH"})

    def test_a_placebo_is_used_at_most_once_per_stock(self):
        accums = {
            "F1": self._pair(20, 20, 4.0),
            "F2": self._pair(20, 20, 4.0),
            "ONLY": self._pair(20, 20, 4.0),
        }
        matched = match_placebo(
            flagged=["F1", "F2"], flagged_set={"F1", "F2"}, accums=accums, rng=self.rng,
        )
        self.assertEqual(matched, {"F1": "ONLY"})


class FlaggingAndNullTests(unittest.TestCase):
    def test_flagging_bar_is_exact_at_its_boundaries(self):
        half = _HalfCounts()
        for side in ("buy", "sell"):
            half.known[("backward", False, side)] = FLAG_MIN_KNOWN_PER_SIDE
            half.hits[("backward", False, side)] = 7
        self.assertEqual((FLAG_MIN_KNOWN_PER_SIDE, FLAG_MIN_RATE), (10, 0.70))
        self.assertTrue(is_flagged(half, "backward"))     # 10 次、0.70 剛好過
        half.hits[("backward", False, "sell")] = 6
        self.assertFalse(is_flagged(half, "backward"))    # 0.60 不過
        half.hits[("backward", False, "sell")] = 7
        half.known[("backward", False, "buy")] = FLAG_MIN_KNOWN_PER_SIDE - 1
        half.hits[("backward", False, "buy")] = 9
        self.assertFalse(is_flagged(half, "backward"))    # 9 次即使 1.0 也不過

    def test_binomial_null_matches_the_exceeds_predicate(self):
        # p = 0.5、n = 3:命中 > 1.5 的機率 = P(2) + P(3) = 0.5
        self.assertAlmostEqual(probability_exceeds(3, 0.5), 0.5, places=9)
        # p = 1.0 時沒有任何結果能超過自己那檔股票。
        self.assertAlmostEqual(probability_exceeds(5, 1.0), 0.0, places=9)


def _direction_stub(*, obs_exp, lag_obs_exp, placebo_obs_exp,
                    both, compared, placebo_both, placebo_compared):
    def arm(both_count, compared_count, ratio):
        return {
            "pairs": compared_count, "with_evaluation_activity": compared_count,
            "survivors": compared_count, "without_stock_baseline": 0,
            "compared_pairs": compared_count,
            "evaluation_buy_episodes": compared_count, "evaluation_buy_known": compared_count,
            "evaluation_buy_hits": both_count,
            "evaluation_sell_episodes": compared_count, "evaluation_sell_known": compared_count,
            "evaluation_sell_hits": both_count,
            "exceeds_own_stock_buy": both_count, "exceeds_own_stock_sell": both_count,
            "exceeds_own_stock_both": both_count,
            "exceeds_own_stock_both_rate": (
                both_count / compared_count if compared_count else None
            ),
            "median_margin_pp_buy": 1.0, "median_margin_pp_sell": 1.0,
            "expected_exceeds_own_stock_both": 1.0,
            "obs_exp": ratio, "low_sample": False,
        }

    return {
        "evaluation": {
            "unlagged": arm(both, compared, obs_exp),
            "lag": arm(both, compared, lag_obs_exp),
        },
        "placebo": {
            "unlagged": arm(placebo_both, placebo_compared, placebo_obs_exp),
            "lag": arm(placebo_both, placebo_compared, placebo_obs_exp),
        },
    }


class VerdictBoundaryTests(unittest.TestCase):
    """四條事先寫死的撤回條件,逐條在門檻邊界上驗。"""

    @staticmethod
    def _verdicts(**kwargs):
        forward = _direction_stub(**kwargs.pop("forward"))
        backward = _direction_stub(**kwargs.pop("backward"))
        return {
            item["criterion"]: item
            for item in build_verdicts({"forward": forward, "backward": backward})
        }

    def _base(self, **overrides):
        forward = dict(
            obs_exp=3.0, lag_obs_exp=3.0, placebo_obs_exp=1.0,
            both=90, compared=100, placebo_both=10, placebo_compared=100,
        )
        backward = dict(
            obs_exp=3.0, lag_obs_exp=3.0, placebo_obs_exp=1.0,
            both=90, compared=100, placebo_both=10, placebo_compared=100,
        )
        forward.update(overrides.pop("forward", {}))
        backward.update(overrides.pop("backward", {}))
        return self._verdicts(forward=forward, backward=backward)

    def test_placebo_obs_exp_threshold_is_strict(self):
        at_threshold = self._base(forward={"placebo_obs_exp": PLACEBO_MAX_OBS_EXP})
        self.assertFalse(
            at_threshold["forward_vs_flow_matched_placebo"]["observed"]
            ["placebo_obs_exp_exceeded"]
        )
        above = self._base(forward={"placebo_obs_exp": PLACEBO_MAX_OBS_EXP + 0.01})
        self.assertTrue(above["forward_vs_flow_matched_placebo"]["triggered"])
        self.assertIn("WITHDRAW forward", above["forward_vs_flow_matched_placebo"]["line"])

    def test_identical_rates_are_inside_the_two_sigma_band(self):
        verdicts = self._base(forward={"both": 50, "placebo_both": 50})
        criterion = verdicts["forward_vs_flow_matched_placebo"]
        self.assertTrue(criterion["observed"]["within_sigma_band"])
        self.assertTrue(criterion["triggered"])

    def test_a_wide_separation_from_the_placebo_keeps_forward(self):
        verdicts = self._base()
        criterion = verdicts["forward_vs_flow_matched_placebo"]
        self.assertFalse(criterion["observed"]["within_sigma_band"])
        self.assertFalse(criterion["triggered"])
        self.assertIn("KEEP forward", criterion["line"])

    def test_lag_test_triggers_only_below_half(self):
        exactly_half = self._base(forward={"obs_exp": 3.0, "lag_obs_exp": 1.5})
        self.assertEqual(LAG_MIN_RETAINED_RATIO, 0.5)
        self.assertFalse(exactly_half["forward_lag_test"]["triggered"])
        below = self._base(forward={"obs_exp": 3.0, "lag_obs_exp": 1.4999})
        self.assertTrue(below["forward_lag_test"]["triggered"])

    def test_forward_weak_while_backward_strong_boundaries(self):
        boundary = self._base(
            forward={"obs_exp": FORWARD_MIN_OBS_EXP},
            backward={"obs_exp": BACKWARD_STRONG_OBS_EXP},
        )
        self.assertFalse(boundary["forward_weak_while_backward_strong"]["triggered"])
        triggered = self._base(
            forward={"obs_exp": FORWARD_MIN_OBS_EXP - 0.0001},
            backward={"obs_exp": BACKWARD_STRONG_OBS_EXP},
        )
        self.assertTrue(triggered["forward_weak_while_backward_strong"]["triggered"])
        # 往前看也弱的時候,這條不成立(它比的是兩個方向的落差)。
        both_weak = self._base(
            forward={"obs_exp": 1.0}, backward={"obs_exp": BACKWARD_STRONG_OBS_EXP - 0.1},
        )
        self.assertFalse(both_weak["forward_weak_while_backward_strong"]["triggered"])

    def test_backward_pull_threshold_decides_the_shipped_panel(self):
        boundary = self._base(backward={"obs_exp": BACKWARD_PULL_OBS_EXP})
        self.assertFalse(boundary["backward_collapse_toward_placebo"]["triggered"])
        self.assertIn("KEEP backward", boundary["backward_collapse_toward_placebo"]["line"])
        collapsed = self._base(backward={"obs_exp": BACKWARD_PULL_OBS_EXP - 0.0001})
        self.assertTrue(collapsed["backward_collapse_toward_placebo"]["triggered"])
        self.assertIn(
            "WITHDRAW backward", collapsed["backward_collapse_toward_placebo"]["line"],
        )

    def test_undefined_numbers_are_reported_as_not_evaluable_never_as_pass(self):
        verdicts = self._base(
            forward={"obs_exp": None, "lag_obs_exp": None, "compared": 0,
                     "placebo_compared": 0},
        )
        for criterion in ("forward_vs_flow_matched_placebo", "forward_lag_test",
                          "forward_weak_while_backward_strong"):
            self.assertIsNone(verdicts[criterion]["triggered"], criterion)
            self.assertFalse(verdicts[criterion]["evaluable"], criterion)
            self.assertIn("NOT EVALUABLE", verdicts[criterion]["line"], criterion)


class BatteryEndToEndTests(unittest.TestCase):
    """真的跑一次:唯讀、切分、存活、安慰劑、verdict、以及不寫任何一列。"""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.old_url, self.old_dir = config.DB_URL, config.DATA_DIR
        self.db_path = self.tmp_path / "battery.db"
        config.DB_URL = "sqlite:///" + self.db_path.as_posix()
        config.DATA_DIR = self.tmp_path
        db._engine = None
        db.init_db()
        self.days = _market_days(date(2026, 1, 5), 120)
        self.as_of = self.days[119]
        self.formation_base, self.evaluation_base = 40, 80

        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": "P", "name": "Pooled", "market": "twse", "type": "stock"},
                {"id": "V", "name": "Vanish", "market": "twse", "type": "stock"},
            ])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": stock_id, "date": day, "open": _close_for(index),
                 "close": _close_for(index), "adj_factor": 1.0}
                for stock_id in ("P", "V")
                for index, day in enumerate(self.days)
            ])
            conn.execute(schema.tracked_branches.insert(), [
                {"branch_name": name, "source": "manual", "added_at": self.days[0]}
                for name in ("FLAGGED", "NOISE", "VANISH")
            ])
            conn.execute(schema.branch_dim.insert(), [
                {"id": 1, "branch_key": "flagged", "branch_name": "FLAGGED"},
                {"id": 2, "branch_key": "noise", "branch_name": "NOISE"},
                {"id": 3, "branch_key": "vanish", "branch_name": "VANISH"},
            ])
            conn.execute(schema.branch_trades_raw.insert(), self._trade_rows())
        # 寫入端連線刻意留著不關:正式機上回補容器就是這樣持有一個帶著未
        # checkpoint 之 WAL frame 的資料庫,唯讀報表必須在那個狀態下也不動它。

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self.old_url, self.old_dir
        self.tmp.cleanup()

    def _trade_rows(self):
        rows = []

        def add(stock_id, branch_id, base, offsets, net_lots, pct):
            for offset in offsets:
                rows.append({
                    "stock_id": stock_id, "date": self.days[base + offset],
                    "branch_id": branch_id, "net_lots": net_lots,
                    "sell_lots": 0 if net_lots > 0 else -net_lots,
                    "pct": pct, "source": "fixture",
                })

        for base in (self.formation_base, self.evaluation_base):
            add("P", 1, base, _BUY_OFFSETS, 40, 4.0)
            add("P", 1, base, _SELL_OFFSETS, -40, -4.0)
            add("P", 2, base, _NOISE_BUY_OFFSETS, 40, 4.0)
            add("P", 2, base, _NOISE_SELL_OFFSETS, -40, -4.0)
        # VANISH 只在形成半段有活動:被標記,然後整段評估期消失。
        add("V", 3, self.formation_base, _BUY_OFFSETS, 40, 4.0)
        add("V", 3, self.formation_base, _SELL_OFFSETS, -40, -4.0)
        return rows

    def _report(self):
        return build_branch_window_direction_battery(
            as_of=self.as_of, window_days=80, seed=7,
        )

    def test_split_dates_are_reported_and_land_on_trading_days(self):
        split = self._report()["split"]
        self.assertEqual(split["formation_from"], self.days[40])
        self.assertEqual(split["formation_to"], self.days[79])
        self.assertEqual(split["evaluation_from"], self.days[80])
        self.assertEqual(split["evaluation_to"], self.days[119])
        self.assertEqual(split["window_market_days"], 80)

    def test_backward_flagging_survivorship_and_own_stock_comparison(self):
        backward = self._report()["directions"]["backward"]
        # FLAGGED 與 VANISH 各 10 買 10 賣、兩側 8/10 = 0.8 >= 0.7。
        self.assertEqual(backward["formation"]["flagged_pairs"], 2)
        self.assertEqual(backward["formation"]["flagged_stocks"], 2)
        survivorship = backward["survivorship"]
        self.assertEqual(survivorship["flagged_pairs"], 2)
        # 消失的那一對留在分母裡,被算成「沒有存活」,不是被靜默丟掉。
        self.assertEqual(survivorship["with_evaluation_activity"], 1)
        self.assertEqual(survivorship["without_evaluation_activity"], 1)
        self.assertEqual(survivorship["survivors"], 1)
        self.assertEqual(survivorship["survivors_min_known_per_side"],
                         EVAL_MIN_KNOWN_PER_SIDE)
        evaluation = backward["evaluation"]["unlagged"]
        self.assertEqual(evaluation["compared_pairs"], 1)
        # 該股 pooled 買側率 = (8 + 0) / 20 = 0.4,FLAGGED 為 0.8 → 勝過自己那檔。
        self.assertEqual(evaluation["exceeds_own_stock_buy"], 1)
        self.assertEqual(evaluation["exceeds_own_stock_sell"], 1)
        self.assertEqual(evaluation["exceeds_own_stock_both"], 1)
        self.assertAlmostEqual(evaluation["median_margin_pp_buy"], 40.0, places=6)
        self.assertGreater(evaluation["obs_exp"], 1.0)

    def test_re_flag_rate_is_reported_but_marked_as_not_a_criterion(self):
        report = self._report()
        re_flag = report["directions"]["backward"]["re_flag"]
        self.assertEqual(re_flag["formation_flagged_pairs"], 2)
        self.assertEqual(re_flag["re_flagged_on_evaluation_half"], 1)
        self.assertFalse(re_flag["is_withdrawal_criterion"])
        self.assertNotIn(
            "re_flag", {verdict["criterion"] for verdict in report["verdicts"]},
        )
        self.assertTrue(any("NOT a withdrawal criterion" in note
                            for note in report["notes"]))

    def test_forward_events_near_as_of_are_immature_not_misses(self):
        report = self._report()
        forward = report["directions"]["forward"]["evaluation"]["unlagged"]
        backward = report["directions"]["backward"]["evaluation"]["unlagged"]
        # 兩個方向看的是同一批 episode。
        self.assertEqual(forward["evaluation_buy_episodes"], 10)
        self.assertEqual(backward["evaluation_buy_episodes"], 10)
        # 但評估半段一路延伸到 as_of,往後看窗口需要事件後 19 個市場日,所以
        # 靠近 as_of 的事件未成熟:只有偏移量 <= 20 的事件算得出來。
        self.assertEqual(forward["evaluation_buy_known"], 6)
        self.assertEqual(forward["evaluation_sell_known"], 5)
        self.assertEqual(backward["evaluation_buy_known"], 10)
        self.assertEqual(backward["evaluation_sell_known"], 10)
        # 未成熟被排除在分母外,**不是**被算成沒命中:命中率因此沒有被稀釋。
        self.assertEqual(forward["evaluation_buy_hits"], 5)
        self.assertEqual(forward["evaluation_sell_hits"], 4)
        self.assertGreater(forward["evaluation_buy_hits"] / forward["evaluation_buy_known"],
                           0.7)

    def test_json_carries_every_number_needed_to_recompute_the_verdicts(self):
        report = self._report()
        self.assertEqual(len(report["verdicts"]), 4)
        for verdict in report["verdicts"]:
            self.assertIn(verdict["outcome"].split()[0],
                          {"WITHDRAW", "KEEP", "NOT"})
            self.assertTrue(verdict["threshold"])
            self.assertIsInstance(verdict["observed"], dict)
        self.assertEqual(report["metadata"]["database_writes"], False)
        json.dumps(report, ensure_ascii=False)  # 必須可序列化

    def test_report_writes_nothing_to_the_database_or_its_sidecars(self):
        wal = self.tmp_path / "battery.db-wal"
        self.assertTrue(wal.is_file(), "fixture must exercise an active WAL")
        self.assertGreater(len(wal.read_bytes()), 32, "WAL must hold uncheckpointed frames")
        before = {
            "db": self.db_path.read_bytes(),
            "-wal": wal.read_bytes(),
            "-journal": (
                (self.tmp_path / "battery.db-journal").read_bytes()
                if (self.tmp_path / "battery.db-journal").exists() else None
            ),
        }
        out = self.tmp_path / "battery.json"
        write_branch_window_direction_battery(
            as_of=self.as_of, window_days=80, seed=7, out=out,
        )
        self.assertTrue(out.is_file())
        self.assertEqual(self.db_path.read_bytes(), before["db"])
        self.assertEqual(wal.read_bytes(), before["-wal"])
        journal = self.tmp_path / "battery.db-journal"
        self.assertEqual(
            journal.read_bytes() if journal.exists() else None, before["-journal"],
        )

    def test_out_guard_refuses_the_database_and_its_sidecars(self):
        before = self.db_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "must not be"):
            write_branch_window_direction_battery(
                as_of=self.as_of, window_days=80, out=self.db_path,
            )
        for suffix in ("-wal", "-shm", "-journal"):
            with self.assertRaisesRegex(ValueError, "sidecar"):
                write_branch_window_direction_battery(
                    as_of=self.as_of, window_days=80,
                    out=self.tmp_path / f"battery.db{suffix}",
                )
        import os

        hardlink = self.tmp_path / "alias.db"
        os.link(self.db_path, hardlink)
        with self.assertRaisesRegex(ValueError, "alias"):
            write_branch_window_direction_battery(
                as_of=self.as_of, window_days=80, out=hardlink,
            )
        symlink = self.tmp_path / "alias-symlink.db"
        try:
            os.symlink(self.db_path, symlink)
        except OSError:
            symlink = None  # Windows 未開發者模式時無法建立 symlink
        if symlink is not None:
            with self.assertRaisesRegex(ValueError, "must not be"):
                write_branch_window_direction_battery(
                    as_of=self.as_of, window_days=80, out=symlink,
                )
        self.assertEqual(self.db_path.read_bytes(), before)

    def test_missing_database_fails_closed_without_creating_a_file(self):
        missing = self.tmp_path / "absent.db"
        config.DB_URL = "sqlite:///" + missing.as_posix()
        try:
            with self.assertRaisesRegex(FileNotFoundError, "does not exist"):
                build_branch_window_direction_battery(as_of=self.as_of, window_days=80)
            self.assertFalse(missing.exists())
        finally:
            config.DB_URL = "sqlite:///" + self.db_path.as_posix()

    def test_cli_runs_read_only_and_prints_a_verdict_line_per_criterion(self):
        out = self.tmp_path / "cli.json"
        main([
            "branch-window-direction-battery",
            "--as-of", self.as_of, "--window-days", "80",
            "--seed", "7", "--out", str(out),
        ])
        report = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(len(report["verdicts"]), 4)
        self.assertEqual(report["metadata"]["read_only"], True)


class StreamingMemoryTests(unittest.TestCase):
    """1.7GB OOM 的形狀是「持有整份 episode 清單」。這裡量的就是它不會再發生。

    量的是**成長率**而不只是絕對值:pair 數量加倍時尖峰記憶體不該跟著加倍,
    因為任何時候都只有一檔股票的價格切片與那一檔的計數器活著。
    """

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.old_url, self.old_dir = config.DB_URL, config.DATA_DIR
        self.days = _market_days(date(2026, 1, 5), 120)
        self.as_of = self.days[119]

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self.old_url, self.old_dir
        self.tmp.cleanup()

    def _peak_bytes_for(self, *, stocks: int, branches: int) -> tuple[int, int]:
        db_path = self.tmp_path / f"mem-{stocks}x{branches}.db"
        config.DB_URL = "sqlite:///" + db_path.as_posix()
        config.DATA_DIR = self.tmp_path
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        db.init_db()
        stock_ids = [f"S{index:04d}" for index in range(stocks)]
        branch_names = [f"B{index:04d}" for index in range(branches)]
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": stock_id, "name": stock_id, "market": "twse", "type": "stock"}
                for stock_id in stock_ids
            ])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": stock_id, "date": day, "open": _close_for(index),
                 "close": _close_for(index), "adj_factor": 1.0}
                for stock_id in stock_ids
                for index, day in enumerate(self.days)
            ])
            conn.execute(schema.tracked_branches.insert(), [
                {"branch_name": name, "source": "manual", "added_at": self.days[0]}
                for name in branch_names
            ])
            conn.execute(schema.branch_dim.insert(), [
                {"id": index + 1, "branch_key": name.lower(), "branch_name": name}
                for index, name in enumerate(branch_names)
            ])
            conn.execute(schema.branch_trades_raw.insert(), [
                {"stock_id": stock_id, "date": self.days[base + offset],
                 "branch_id": branch_index + 1, "net_lots": net_lots,
                 "sell_lots": 0 if net_lots > 0 else -net_lots,
                 "pct": pct, "source": "fixture"}
                for stock_id in stock_ids
                for branch_index in range(branches)
                for base in (40, 80)
                for offsets, net_lots, pct in (
                    (_BUY_OFFSETS, 40, 4.0), (_SELL_OFFSETS, -40, -4.0),
                )
                for offset in offsets
            ])
        db.get_engine().dispose()
        db._engine = None

        tracemalloc.start()
        try:
            tracemalloc.reset_peak()
            report = build_branch_window_direction_battery(
                as_of=self.as_of, window_days=80, seed=7,
            )
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(report["coverage"]["pairs_streamed"], stocks * branches)
        return peak, report["coverage"]["pairs_streamed"]

    def test_peak_memory_does_not_scale_with_pair_count(self):
        small_peak, small_pairs = self._peak_bytes_for(stocks=6, branches=15)
        large_peak, large_pairs = self._peak_bytes_for(stocks=12, branches=15)
        self.assertEqual((small_pairs, large_pairs), (90, 180))
        # 絕對上限:整份計算的追蹤配置量遠低於任何會 OOM 的量級。
        self.assertLess(small_peak, 8 * 1024 * 1024, f"small peak={small_peak} bytes")
        self.assertLess(large_peak, 8 * 1024 * 1024, f"large peak={large_peak} bytes")
        # 成長上限:pair 數加倍,尖峰不得跟著加倍(持有整份清單的實作會)。
        self.assertLess(
            large_peak, 1.5 * small_peak,
            f"small={small_peak} large={large_peak} bytes: peak grew with pair count",
        )


if __name__ == "__main__":
    unittest.main()
