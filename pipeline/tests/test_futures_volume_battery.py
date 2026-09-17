"""個股期貨成交量異常 battery(docs/38,事前登記 `c70f1c2`)。

fixture 的每一個數字都是**發明的**,而且是為了讓答案可以手算而發明的:一天 100 口
的底,每七天一個 200 口的「中量日」,以及五個嚴格遞增的尖峰。任何一天會不會舉旗、
會撞到哪一條否決,在寫測試的時候就已經決定了——這支測試裡沒有一個期望值是「跑出來
之後抄回去」的,也沒有任何一個數字來自真實的期貨資料。這正是事前登記的要求:前置
實作必須在看到回補資料之前就能被驗證。

覆蓋的不只是快樂路徑:五條否決各有一個**真的把它點著**的構造案例(R1 缺列、
R2a 中位數為 0、R2b 實質性、R2b 乘數未知、R4 兩側排除),三種裁決(上線、
冗餘、檢定力不足)與檢定 B 的失敗各有一個。只驗快樂路徑等於沒驗這支程式。
"""
import json
import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import radar.config as config
import radar.db as db
from radar import schema
from radar.cli import main
from radar.compute.branch_window_direction_battery import LOW_SAMPLE_SURVIVORS
from radar.compute.settlement_calendar import EXCLUSION_MARKET_DAYS_BEFORE
from radar.compute.futures_volume_battery import (
    FORWARD_SPOT_DAYS,
    MATERIALITY_INVERSE_FRACTION,
    PLACEBO_SEEDS,
    PLACEBO_SIGMA_MULTIPLE,
    PREREGISTRATION_COMMIT,
    WINDOW_DAYS,
    _StockCalendar,
    build_futures_volume_battery,
    comparison_window,
    draw_placebo,
    evaluate_contract_day,
    lower_median,
    overall_verdict,
    placebo_pool,
    seed_result,
    spot_new_high,
    discriminability_verdict,
    informativeness_verdict,
    write_futures_volume_battery,
)


def _weekdays(start: date, count: int) -> list[str]:
    days: list[str] = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current.isoformat())
        current += timedelta(days=1)
    return days


# 2026-01-05(週一)起 200 個工作日,到 2026-10-09。期間內每一個第三個星期三都是
# 工作日,所以 R4 排除日就是手算得出的那四天一組(例 5 月:05-15、18、19、20)。
_DAY_COUNT = 200
_DAYS = _weekdays(date(2026, 1, 5), _DAY_COUNT)

_PERIOD, _MEDIUM_PHASE = 7, 3       # 中量日:index % 7 == 3
_BASE_LOTS, _MEDIUM_LOTS = 100, 200
_SPOT_BASE = 1_000_000              # 股
_MULTIPLIER = 2_000                 # 股/口,標準型

# 五個嚴格遞增的尖峰。index % 7 == 0,所以尖峰日與中量日永不重疊,而且尖峰後
# 第 2 天(index % 7 == 2)可以單獨拿來放現貨爆量,不會撞到任何中量日的往後窗口。
_SPIKE_INDEXES = (84, 105, 126, 147, 168)
_SPIKE_LOTS = (500, 600, 700, 800, 900)
_SPIKES = dict(zip(_SPIKE_INDEXES, _SPIKE_LOTS))

# 現貨爆量日:尖峰日 + 2。量嚴格遞增,所以每一個都是它自己的 60 日新高。
_BUMPS_AFTER_SPIKES = {
    index + 2: 2_000_000 + 1_000_000 * order
    for order, index in enumerate(_SPIKE_INDEXES)
}
_BUMPS_ON_SPIKES = {
    index: 2_000_000 + 1_000_000 * order
    for order, index in enumerate(_SPIKE_INDEXES)
}
# 「每個中量日之後也爆量」:安慰劑臂與旗標臂的命中率會一樣高,檢定 B 因此必敗。
_BUMPS_EVERYWHERE = {
    **{index: 2_000_000 + 10_000 * index
       for index in range(_DAY_COUNT) if index % _PERIOD == 5},
    **{index + 2: 2_000_000 + 10_000 * (index + 2) for index in _SPIKE_INDEXES},
}

# 5 月結算日與其前 3 個市場日(手算:2026-05-20 是五月第三個星期三,且是工作日)。
_MAY_SETTLEMENT_INDEX = 97          # 2026-05-20
_MAY_WINDOW_FIRST_INDEX = 94        # 2026-05-15
_DAY_AFTER_SETTLEMENT_INDEX = 98    # 2026-05-21,**不**排除(R4:結算次日不排除)


def _pattern_lots(*, base: int = _BASE_LOTS, medium: int | None = _MEDIUM_LOTS,
                  overrides: dict[int, int | None] | None = None) -> dict[int, int | None]:
    lots: dict[int, int | None] = {
        index: (medium if medium is not None and index % _PERIOD == _MEDIUM_PHASE else base)
        for index in range(_DAY_COUNT)
    }
    lots.update(overrides or {})
    return lots


def _spot_volumes(bumps: dict[int, int] | None = None) -> dict[int, int]:
    volumes = {index: _SPOT_BASE for index in range(_DAY_COUNT)}
    volumes.update(bumps or {})
    return volumes


def _contract(code: str, stock_id: str, *, multiplier: int | None = _MULTIPLIER,
              lots: dict[int, int | None] | None = None) -> dict:
    return {
        "code": code, "stock_id": stock_id, "multiplier": multiplier,
        "lots": _pattern_lots(overrides=_SPIKES) if lots is None else lots,
    }


def _standard_contracts(count: int) -> list[dict]:
    return [
        _contract(f"S{index}F", f"100{index}")
        for index in range(1, count + 1)
    ]


class _FixtureDB(unittest.TestCase):
    """一個空的暫存資料庫,外加把上面那些發明出來的數字寫進去的 helper。"""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.old_url, self.old_dir = config.DB_URL, config.DATA_DIR
        self.db_path = self.tmp_path / "futures-battery.db"
        config.DB_URL = "sqlite:///" + self.db_path.as_posix()
        config.DATA_DIR = self.tmp_path
        db._engine = None
        db.init_db()

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self.old_url, self.old_dir
        self.tmp.cleanup()

    def write_fixture(self, *, contracts: list[dict],
                      spot: dict[int, int] | None = None,
                      spot_by_stock: dict[str, dict[int, int]] | None = None) -> None:
        stock_ids = sorted({contract["stock_id"] for contract in contracts})
        spot_by_stock = dict(spot_by_stock or {})
        for stock_id in stock_ids:
            spot_by_stock.setdefault(stock_id, spot if spot is not None else _spot_volumes())
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": stock_id, "name": f"Fixture {stock_id}",
                 "market": "twse", "type": "stock"}
                for stock_id in stock_ids
            ])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": stock_id, "date": _DAYS[index], "open": 10.0,
                 "close": 10.0, "adj_factor": 1.0, "volume": volume}
                for stock_id, volumes in sorted(spot_by_stock.items())
                for index, volume in sorted(volumes.items())
            ])
            conn.execute(schema.futures_contracts.insert(), [
                {"contract_code": contract["code"], "stock_id": contract["stock_id"],
                 "stock_name": f"Fixture {contract['stock_id']}",
                 "is_stock_future": True, "market": "twse",
                 "contract_multiplier": contract["multiplier"],
                 "first_seen": _DAYS[0], "last_seen": _DAYS[-1]}
                for contract in contracts
            ])
            rows = []
            for contract in contracts:
                for index, lots in sorted(contract["lots"].items()):
                    if lots is None:
                        continue    # 缺列 ≠ 0 口:這一天根本沒有列。
                    rows.append({
                        "contract_code": contract["code"], "date": _DAYS[index],
                        "contract_month": "202612", "session": "一般",
                        "volume": lots, "open_interest": 1_000 + index,
                    })
                    # 盤後列與價差組合列都給一個大到不可能忽略的量:統計量若不小心
                    # 讀到它們,下面每一個期望值都會錯。
                    rows.append({
                        "contract_code": contract["code"], "date": _DAYS[index],
                        "contract_month": "202612", "session": "盤後",
                        "volume": 999_999, "open_interest": None,
                    })
                    rows.append({
                        "contract_code": contract["code"], "date": _DAYS[index],
                        "contract_month": "202612/202701", "session": "一般",
                        "volume": 888_888, "open_interest": None,
                    })
            conn.execute(schema.futures_daily.insert(), rows)

    def report(self, **kwargs):
        return build_futures_volume_battery(as_of=_DAYS[-1], **kwargs)

    @staticmethod
    def flagged_pairs(report) -> set[tuple[str, str]]:
        return {
            (entry["contract_code"], entry["date"])
            for entry in report["f_only_sample"]
        }


class FrozenConstantTests(unittest.TestCase):
    """§3.5:60、3 天、1%、2σ、30、5 天、seed 清單,看到資料之後都不得更動。

    這支測試的作用不是抓 bug,是讓「悄悄把 60 改成 20」這個動作必須先刪掉一條
    寫著「不得更動」的測試——那就不再是悄悄的了。
    """

    def test_the_pre_registered_numbers_are_what_the_document_says(self):
        self.assertEqual(WINDOW_DAYS, 60)
        self.assertEqual(FORWARD_SPOT_DAYS, 5)
        self.assertEqual(MATERIALITY_INVERSE_FRACTION, 100)
        self.assertEqual(PLACEBO_SIGMA_MULTIPLE, 2.0)
        self.assertEqual(PLACEBO_SEEDS, tuple(range(10)))
        self.assertEqual(EXCLUSION_MARKET_DAYS_BEFORE, 3)
        # 30 沿用 branch_window_direction_battery,不另立一個數字。
        self.assertEqual(LOW_SAMPLE_SURVIVORS, 30)
        self.assertEqual(PREREGISTRATION_COMMIT, "c70f1c2")


class PureRuleTests(unittest.TestCase):
    """§1 與 §2 的算術層:沒有資料庫,沒有日曆,只有手算的數字。"""

    def test_lower_median_takes_the_smaller_middle_value(self):
        self.assertEqual(lower_median([1, 2, 3, 4]), 2)
        self.assertEqual(lower_median([5]), 5)
        self.assertEqual(lower_median([9, 1, 7]), 7)

    def test_comparison_window_skips_excluded_days_and_extends_backwards(self):
        days = [f"2026-01-{day:02d}" for day in range(1, 32)]
        window = comparison_window(
            candidate="2026-01-31", futures_days=days, excluded=frozenset(),
        )
        self.assertIsNone(window, "30 days cannot fill a 60-day window")

        short = list(days)
        # 用一個縮小版的視窗長度不可行(60 是寫死的),所以改驗排除日的行為:
        # 造一串夠長的日子,排掉其中三天,窗口必須往前多取三天補足。
        long_days = [f"2026-{month:02d}-{day:02d}"
                     for month in (1, 2, 3, 4) for day in range(1, 29)]
        excluded = frozenset({"2026-03-01", "2026-03-02", "2026-03-03"})
        window = comparison_window(
            candidate="2026-04-01", futures_days=long_days, excluded=excluded,
        )
        self.assertEqual(len(window), WINDOW_DAYS)
        self.assertFalse(set(window) & excluded)
        self.assertEqual(window[-1], "2026-03-28")
        # 沒有排除日時窗口的起點會晚三天——排除日確實把窗口往前推了。
        unexcluded = comparison_window(
            candidate="2026-04-01", futures_days=long_days, excluded=frozenset(),
        )
        self.assertLess(window[0], unexcluded[0])

    def test_r1_refuses_a_short_window_and_a_missing_row(self):
        full = [100] * WINDOW_DAYS
        self.assertEqual(
            evaluate_contract_day(
                today_volume=500, window_volumes=None, multiplier=_MULTIPLIER,
                spot_window_volumes=[_SPOT_BASE] * WINDOW_DAYS,
            )["refusal"],
            "R1_window_gap",
        )
        with_hole = list(full)
        with_hole[17] = None
        self.assertEqual(
            evaluate_contract_day(
                today_volume=500, window_volumes=with_hole, multiplier=_MULTIPLIER,
                spot_window_volumes=[_SPOT_BASE] * WINDOW_DAYS,
            )["refusal"],
            "R1_window_gap",
        )
        # 缺列 ≠ 0 口:同一個窗口把缺的那天讀成 0 就會通過 R1。
        as_zero = list(full)
        as_zero[17] = 0
        self.assertIsNone(
            evaluate_contract_day(
                today_volume=500, window_volumes=as_zero, multiplier=_MULTIPLIER,
                spot_window_volumes=[_SPOT_BASE] * WINDOW_DAYS,
            )["refusal"],
        )

    def test_r2a_refuses_a_zero_median_before_asking_about_the_multiplier(self):
        outcome = evaluate_contract_day(
            today_volume=500, window_volumes=[0] * WINDOW_DAYS, multiplier=None,
            spot_window_volumes=[_SPOT_BASE] * WINDOW_DAYS,
        )
        self.assertEqual(outcome["refusal"], "R2a_zero_median")
        self.assertFalse(outcome["flag"])

    def test_an_unknown_multiplier_refuses_and_is_never_assumed_to_be_2000(self):
        arguments = {
            "today_volume": 500,
            "window_volumes": [100] * WINDOW_DAYS,
            "spot_window_volumes": [_SPOT_BASE] * WINDOW_DAYS,
        }
        self.assertEqual(
            evaluate_contract_day(multiplier=None, **arguments)["refusal"],
            "R2b_multiplier_unknown",
        )
        # 同一天,乘數已知就會舉旗——所以上面那一條是**乘數未知**在否決,
        # 不是這一天本來就不合格。
        known = evaluate_contract_day(multiplier=_MULTIPLIER, **arguments)
        self.assertIsNone(known["refusal"])
        self.assertTrue(known["flag"])

    def test_r2b_materiality_is_the_three_times_two_lots_case(self):
        # 文件的例子:中位數 2 口的契約,6 口就是 3 倍。
        # 100 × (6 − 2) × 2,000 = 800,000 股 < 現貨日常量 1,000,000 股 → 否決。
        outcome = evaluate_contract_day(
            today_volume=6, window_volumes=[2] * WINDOW_DAYS, multiplier=_MULTIPLIER,
            spot_window_volumes=[_SPOT_BASE] * WINDOW_DAYS,
        )
        self.assertEqual(outcome["refusal"], "R2b_immaterial")
        # 邊界:7 口剛好等於 1%,「≥」所以通過,而且它確實創了新高。
        boundary = evaluate_contract_day(
            today_volume=7, window_volumes=[2] * WINDOW_DAYS, multiplier=_MULTIPLIER,
            spot_window_volumes=[_SPOT_BASE] * WINDOW_DAYS,
        )
        self.assertIsNone(boundary["refusal"])
        self.assertTrue(boundary["flag"])

    def test_r2b_refuses_when_the_spot_ruler_has_a_hole(self):
        spot = [_SPOT_BASE] * WINDOW_DAYS
        spot[3] = None
        self.assertEqual(
            evaluate_contract_day(
                today_volume=500, window_volumes=[100] * WINDOW_DAYS,
                multiplier=_MULTIPLIER, spot_window_volumes=spot,
            )["refusal"],
            "R2b_spot_history_gap",
        )

    def test_the_flag_is_strictly_greater_than_the_window_max(self):
        window = [100] * (WINDOW_DAYS - 1) + [500]
        arguments = {
            "window_volumes": window, "multiplier": _MULTIPLIER,
            "spot_window_volumes": [_SPOT_BASE] * WINDOW_DAYS,
        }
        self.assertFalse(evaluate_contract_day(today_volume=500, **arguments)["flag"])
        self.assertTrue(evaluate_contract_day(today_volume=501, **arguments)["flag"])

    def test_the_reported_facts_are_integers_and_there_is_no_ratio(self):
        outcome = evaluate_contract_day(
            today_volume=500, window_volumes=[100] * 59 + [200],
            multiplier=_MULTIPLIER, spot_window_volumes=[_SPOT_BASE] * WINDOW_DAYS,
        )
        self.assertEqual(outcome["today"], 500)
        self.assertEqual(outcome["window_max"], 200)
        self.assertEqual(outcome["window_median"], 100)
        self.assertEqual(outcome["window_days"], WINDOW_DAYS)
        for key, value in outcome.items():
            if key not in ("refusal", "flag"):
                self.assertIsInstance(value, int, key)


class SpotSideTests(unittest.TestCase):
    """S(s, t) 與往後看窗口:現貨不轉倉,不套 R4,窗口以該股自己的日曆計。"""

    def setUp(self):
        self.days = list(_DAYS)
        self.volumes = {day: _SPOT_BASE for day in self.days}

    def test_a_new_high_needs_sixty_days_of_history_and_a_strict_greater(self):
        self.assertIsNone(spot_new_high(
            stock_days=self.days, volumes=self.volumes, day=self.days[WINDOW_DAYS - 1],
        ))
        self.assertFalse(spot_new_high(
            stock_days=self.days, volumes=self.volumes, day=self.days[WINDOW_DAYS],
        ))
        self.volumes[self.days[WINDOW_DAYS]] = _SPOT_BASE + 1
        self.assertTrue(spot_new_high(
            stock_days=self.days, volumes=self.volumes, day=self.days[WINDOW_DAYS],
        ))

    def test_a_missing_spot_volume_is_unknown_not_a_non_high(self):
        self.volumes[self.days[70]] = None
        self.assertIsNone(spot_new_high(
            stock_days=self.days, volumes=self.volumes, day=self.days[70],
        ))
        # 窗口裡缺一天也是不知道,不是「沒創高」。
        self.volumes[self.days[70]] = _SPOT_BASE
        self.volumes[self.days[65]] = None
        self.assertIsNone(spot_new_high(
            stock_days=self.days, volumes=self.volumes, day=self.days[70],
        ))

    def test_maturity_needs_five_spot_days_after_t(self):
        calendar = _StockCalendar(self.days, self.volumes)
        self.assertTrue(calendar.is_mature(self.days[-FORWARD_SPOT_DAYS - 1]))
        self.assertFalse(calendar.is_mature(self.days[-FORWARD_SPOT_DAYS]))
        self.assertFalse(calendar.is_mature(self.days[-1]))

    def test_the_forward_window_is_five_spot_days_not_five_calendar_days(self):
        self.volumes[self.days[105]] = 9_000_000
        calendar = _StockCalendar(self.days, self.volumes)
        self.assertTrue(calendar.forward_hit(self.days[100]))
        self.assertFalse(calendar.forward_hit(self.days[99]))   # 第 6 天不算
        self.assertFalse(calendar.forward_hit(self.days[105]))  # 當天自己不算


class PlaceboTests(unittest.TestCase):
    """安慰劑池與抽樣:共用往後窗口的日子出局,同一個 seed 給同一組日子。"""

    def setUp(self):
        self.days = list(_DAYS)
        self.calendar = _StockCalendar(self.days, {day: _SPOT_BASE for day in self.days})

    def test_the_pool_drops_the_flagged_day_itself_and_the_five_after_it(self):
        eligible = {self.days[index] for index in range(100, 112)}
        pool = placebo_pool(
            eligible_days=eligible, flagged_days={self.days[104]},
            calendar=self.calendar,
        )
        self.assertNotIn(self.days[104], pool)
        for index in range(105, 110):
            self.assertNotIn(self.days[index], pool)
        self.assertIn(self.days[103], pool)
        self.assertIn(self.days[110], pool)

    def test_the_draw_is_count_matched_and_reproducible_per_seed(self):
        pools = {"A": [self.days[index] for index in range(20)]}
        first = draw_placebo(pools=pools, counts={"A": 5}, seed=0)
        again = draw_placebo(pools=pools, counts={"A": 5}, seed=0)
        other = draw_placebo(pools=pools, counts={"A": 5}, seed=1)
        self.assertEqual(len(first["A"]), 5)
        self.assertEqual(first, again)
        self.assertNotEqual(first, other)

    def test_a_pool_smaller_than_k_is_drawn_dry_not_padded(self):
        pools = {"A": [self.days[0], self.days[1]]}
        drawn = draw_placebo(pools=pools, counts={"A": 5}, seed=0)
        self.assertEqual(len(drawn["A"]), 2)


class VerdictArithmeticTests(unittest.TestCase):
    """§3.2–§3.4 的判準,在邊界上。"""

    def test_test_a_tells_the_three_outcomes_apart(self):
        self.assertEqual(
            discriminability_verdict(f_count=40, f_only_count=LOW_SAMPLE_SURVIVORS)["outcome"],
            "PASS",
        )
        redundant = discriminability_verdict(
            f_count=LOW_SAMPLE_SURVIVORS, f_only_count=LOW_SAMPLE_SURVIVORS - 1,
        )
        self.assertEqual(redundant["outcome"], "REDUNDANT WITH SPOT")
        underpowered = discriminability_verdict(
            f_count=LOW_SAMPLE_SURVIVORS - 1, f_only_count=0,
        )
        self.assertEqual(underpowered["outcome"], "UNDERPOWERED")
        self.assertIn("NOT a refutation", underpowered["line"])

    def test_sigma_has_a_floor_of_one(self):
        result = seed_result(seed=0, n=40, h_f=40, h_p=0, matched=True)
        self.assertEqual(result["sigma_p"], 1.0)
        self.assertTrue(result["passed"])
        # 差距剛好 2σ 要過,差一點就不過。
        self.assertTrue(seed_result(seed=0, n=40, h_f=2, h_p=0, matched=True)["passed"])
        self.assertFalse(seed_result(seed=0, n=40, h_f=1, h_p=0, matched=True)["passed"])

    def test_one_failing_seed_fails_the_whole_test(self):
        seeds = [seed_result(seed=s, n=40, h_f=40, h_p=0, matched=True)
                 for s in PLACEBO_SEEDS]
        self.assertTrue(informativeness_verdict(seeds=seeds)["passed"])
        seeds[7] = seed_result(seed=7, n=40, h_f=40, h_p=39, matched=True)
        spoiled = informativeness_verdict(seeds=seeds)
        self.assertFalse(spoiled["passed"])
        self.assertIn("[7]", spoiled["line"])

    def test_a_short_placebo_draw_is_not_evaluable_rather_than_a_pass(self):
        seeds = [seed_result(seed=s, n=40, h_f=40, h_p=0, matched=s != 3)
                 for s in PLACEBO_SEEDS]
        verdict = informativeness_verdict(seeds=seeds)
        self.assertFalse(verdict["evaluable"])
        self.assertEqual(verdict["outcome"], "NOT EVALUABLE")
        decision = overall_verdict(
            test_a=discriminability_verdict(f_count=40, f_only_count=40), test_b=verdict,
        )
        self.assertEqual(decision["decision"], "DO NOT SHIP")
        self.assertEqual(decision["reason"], "not_evaluable")

    def test_shipping_needs_both_tests(self):
        passing_a = discriminability_verdict(f_count=40, f_only_count=40)
        passing_b = informativeness_verdict(seeds=[
            seed_result(seed=s, n=40, h_f=40, h_p=0, matched=True) for s in PLACEBO_SEEDS
        ])
        self.assertEqual(
            overall_verdict(test_a=passing_a, test_b=passing_b)["decision"], "SHIP",
        )
        self.assertEqual(
            overall_verdict(
                test_a=discriminability_verdict(f_count=40, f_only_count=1), test_b=passing_b,
            )["reason"],
            "redundant_with_spot",
        )
        self.assertEqual(
            overall_verdict(
                test_a=discriminability_verdict(f_count=1, f_only_count=1), test_b=passing_b,
            )["reason"],
            "underpowered",
        )


class RefusalPathTests(_FixtureDB):
    """五條否決各有一個真的把它點著的構造案例。"""

    def test_a_missing_row_inside_the_window_refuses_that_candidate_only(self):
        holed = _pattern_lots(overrides={**_SPIKES, 166: None})
        self.write_fixture(
            contracts=[_contract("AAF", "1001"), _contract("BBF", "1002", lots=holed)],
            spot=_spot_volumes(_BUMPS_AFTER_SPIKES),
        )
        report = self.report()
        flagged = self.flagged_pairs(report)
        # 2026-08-25 缺列落在 2026-08-27 那個尖峰的比較窗口裡 → 該日被 R1 否決;
        # 更早的四個尖峰窗口不含缺列的那天,照樣上榜。
        self.assertEqual(_DAYS[166], "2026-08-25")
        self.assertNotIn(("BBF", _DAYS[168]), flagged)
        self.assertIn(("AAF", _DAYS[168]), flagged)
        for index in _SPIKE_INDEXES[:-1]:
            self.assertIn(("BBF", _DAYS[index]), flagged)
        self.assertGreater(report["refusals"]["R1_window_gap"], 0)
        self.assertGreater(
            report["coverage"]["contract_days_without_regular_session_row"], 0,
        )

    def test_a_zero_median_contract_refuses_even_on_a_huge_spike(self):
        self.write_fixture(
            contracts=[
                _contract("AAF", "1001"),
                _contract("ZZF", "1002",
                          lots=_pattern_lots(base=0, medium=None, overrides=_SPIKES)),
            ],
            spot=_spot_volumes(_BUMPS_AFTER_SPIKES),
        )
        report = self.report()
        flagged = self.flagged_pairs(report)
        self.assertFalse({pair for pair in flagged if pair[0] == "ZZF"})
        self.assertIn(("AAF", _DAYS[84]), flagged)
        self.assertGreater(report["refusals"]["R2a_zero_median"], 0)

    def test_immateriality_refuses_six_lots_and_admits_seven(self):
        thin_six = _pattern_lots(base=2, medium=None, overrides={84: 6})
        thin_seven = _pattern_lots(base=2, medium=None, overrides={84: 7})
        self.write_fixture(
            contracts=[
                _contract("SIXF", "1001", lots=thin_six),
                _contract("SEVF", "1002", lots=thin_seven),
            ],
        )
        report = self.report()
        flagged = self.flagged_pairs(report)
        self.assertNotIn(("SIXF", _DAYS[84]), flagged)
        self.assertIn(("SEVF", _DAYS[84]), flagged)
        self.assertGreater(report["refusals"]["R2b_immaterial"], 0)

    def test_a_null_multiplier_refuses_while_its_twin_flags(self):
        self.write_fixture(
            contracts=[
                _contract("KNF", "1001"),
                _contract("NULF", "1002", multiplier=None),
            ],
            spot=_spot_volumes(_BUMPS_AFTER_SPIKES),
        )
        report = self.report()
        flagged = self.flagged_pairs(report)
        self.assertFalse({pair for pair in flagged if pair[0] == "NULF"})
        self.assertIn(("KNF", _DAYS[84]), flagged)
        self.assertEqual(report["coverage"]["contracts_with_known_multiplier"], 1)
        self.assertGreater(report["refusals"]["R2b_multiplier_unknown"], 0)
        self.assertTrue(any("never assumed to be 2,000" in note
                            for note in report["notes"]))

    def test_a_target_with_no_spot_rows_at_all_has_no_ruler_and_is_refused(self):
        self.write_fixture(
            contracts=[_contract("AAF", "1001"), _contract("NOSF", "1002")],
            spot_by_stock={"1002": {}},
        )
        report = self.report()
        flagged = self.flagged_pairs(report)
        self.assertFalse({pair for pair in flagged if pair[0] == "NOSF"})
        self.assertIn(("AAF", _DAYS[84]), flagged)
        self.assertGreater(
            report["coverage"]["contract_days_without_spot_calendar"], 0,
        )
        self.assertGreater(report["refusals"]["R2b_spot_history_gap"], 0)

    def test_the_settlement_window_is_excluded_from_the_candidate_set(self):
        # 兩個尖峰刻意放在 2026-05-20(結算日)與 2026-05-15(窗口第一天),
        # 第三個放在 2026-05-21(結算次日,R4 明文**不**排除)。
        on_window = _pattern_lots(overrides={
            _MAY_WINDOW_FIRST_INDEX: 500,
            _MAY_SETTLEMENT_INDEX: 600,
            _DAY_AFTER_SETTLEMENT_INDEX: 700,
        })
        self.write_fixture(contracts=[_contract("RLF", "1001", lots=on_window)])
        report = self.report()
        flagged = self.flagged_pairs(report)
        self.assertEqual(_DAYS[_MAY_SETTLEMENT_INDEX], "2026-05-20")
        self.assertNotIn(("RLF", "2026-05-15"), flagged)
        self.assertNotIn(("RLF", "2026-05-20"), flagged)
        self.assertIn(("RLF", "2026-05-21"), flagged)
        self.assertGreater(
            report["coverage"]["contract_days_in_settlement_window"], 0,
        )

    def test_the_settlement_window_is_excluded_from_the_comparison_window(self):
        # 兩個契約只差一天:巨量落在結算日(排除)vs 結算次日(不排除)。
        # 六月那個尖峰只有在巨量被排除出窗口時才可能創高。
        inside = _pattern_lots(overrides={_MAY_SETTLEMENT_INDEX: 5_000, 105: 500})
        outside = _pattern_lots(overrides={_DAY_AFTER_SETTLEMENT_INDEX: 5_000, 105: 500})
        self.write_fixture(
            contracts=[
                _contract("EXF", "1001", lots=inside),
                _contract("INF", "1002", lots=outside),
            ],
        )
        flagged = self.flagged_pairs(self.report())
        self.assertIn(("EXF", _DAYS[105]), flagged)
        self.assertNotIn(("INF", _DAYS[105]), flagged)
        # 對照組的巨量本身是結算次日,它自己照樣上榜——差別只在窗口,不在別處。
        self.assertIn(("INF", "2026-05-21"), flagged)

    def test_after_hours_and_spread_rows_never_reach_the_statistic(self):
        self.write_fixture(contracts=[_contract("AAF", "1001")],
                           spot=_spot_volumes(_BUMPS_AFTER_SPIKES))
        report = self.report()
        entry = next(item for item in report["f_only_sample"]
                     if item["date"] == _DAYS[84])
        # fixture 每天都寫了 999,999 口盤後與 888,888 口價差組合。
        self.assertEqual(entry["today"], 500)
        self.assertEqual(entry["window_max"], _MEDIUM_LOTS)
        self.assertEqual(entry["window_median"], _BASE_LOTS)
        self.assertEqual(entry["oi_change"], 1)
        self.assertIn("structural", report["refusals"]["R3_after_hours"])
        self.assertIn("BLIND SPOT", report["refusals"]["R5_multiplier_change"])


class VerdictEndToEndTests(_FixtureDB):
    """三種裁決各跑一次:上線、冗餘、檢定力不足,外加檢定 B 的失敗。"""

    def test_a_passing_battery_ships(self):
        self.write_fixture(contracts=_standard_contracts(8),
                           spot=_spot_volumes(_BUMPS_AFTER_SPIKES))
        report = self.report()
        self.assertEqual(report["sets"]["f"], 40)
        self.assertEqual(report["sets"]["f_only"], 40)
        self.assertEqual(report["sets"]["f_with_unknown_spot_flag"], 0)
        self.assertEqual(report["sets"]["placebo_day_shortfall_across_seeds"], 0)
        self.assertEqual(report["tests"]["A"]["outcome"], "PASS")
        self.assertEqual(report["tests"]["B"]["h_f"], 40)
        self.assertEqual([seed["seed"] for seed in report["tests"]["B"]["seeds"]],
                         list(PLACEBO_SEEDS))
        for seed in report["tests"]["B"]["seeds"]:
            self.assertEqual(seed["h_p"], 0, seed["seed"])
            self.assertEqual(seed["sigma_p"], 1.0)
            self.assertTrue(seed["passed"])
        self.assertEqual(report["verdict"]["decision"], "SHIP")
        self.assertEqual(report["metadata"]["preregistration_commit"],
                         PREREGISTRATION_COMMIT)

    def test_a_futures_high_that_is_always_a_spot_high_is_redundant(self):
        self.write_fixture(contracts=_standard_contracts(8),
                           spot=_spot_volumes(_BUMPS_ON_SPIKES))
        report = self.report()
        self.assertEqual(report["sets"]["f"], 40)
        self.assertEqual(report["sets"]["f_only"], 0)
        self.assertEqual(report["tests"]["A"]["outcome"], "REDUNDANT WITH SPOT")
        self.assertEqual(report["verdict"]["reason"], "redundant_with_spot")
        self.assertEqual(report["verdict"]["decision"], "DO NOT SHIP")

    def test_too_few_flags_is_underpowered_and_says_so(self):
        self.write_fixture(contracts=_standard_contracts(2),
                           spot=_spot_volumes(_BUMPS_AFTER_SPIKES))
        report = self.report()
        self.assertEqual(report["sets"]["f"], 10)
        self.assertEqual(report["sets"]["f_only"], 10)
        self.assertEqual(report["tests"]["A"]["outcome"], "UNDERPOWERED")
        self.assertEqual(report["verdict"]["reason"], "underpowered")
        self.assertIn("NOT a refutation", report["tests"]["A"]["line"])

    def test_a_placebo_that_hits_just_as_often_fails_test_b(self):
        self.write_fixture(contracts=_standard_contracts(8),
                           spot=_spot_volumes(_BUMPS_EVERYWHERE))
        report = self.report()
        self.assertEqual(report["tests"]["A"]["outcome"], "PASS")
        self.assertEqual(report["tests"]["B"]["outcome"], "FAIL")
        for seed in report["tests"]["B"]["seeds"]:
            self.assertEqual(seed["h_p"], seed["n"], seed["seed"])
            self.assertFalse(seed["passed"])
        self.assertEqual(report["verdict"]["reason"], "forward_test_failed")
        self.assertEqual(report["verdict"]["decision"], "DO NOT SHIP")

    def test_an_empty_placebo_pool_is_not_evaluable_rather_than_a_pass(self):
        # 沒有中量日的契約:任何一天都撞 R2b(今天等於自己的中位數),於是「規則
        # 看過但沒舉旗」的合格日一天都不存在,安慰劑抽不滿 k。這種情況下 h_P 會
        # 被少抽的日子系統性壓低,所以裁決是「不可評估」,不是「過」。
        contracts = [
            _contract(f"N{index}F", f"200{index}",
                      lots=_pattern_lots(medium=None, overrides=_SPIKES))
            for index in range(1, 9)
        ]
        self.write_fixture(contracts=contracts, spot=_spot_volumes(_BUMPS_AFTER_SPIKES))
        report = self.report()
        self.assertEqual(report["sets"]["f_only"], 40)
        self.assertEqual(report["sets"]["placebo_pool_days"], 0)
        self.assertEqual(
            report["sets"]["placebo_day_shortfall_across_seeds"], 40 * len(PLACEBO_SEEDS),
        )
        self.assertEqual(report["tests"]["A"]["outcome"], "PASS")
        self.assertEqual(report["tests"]["B"]["outcome"], "NOT EVALUABLE")
        self.assertEqual(report["verdict"]["reason"], "not_evaluable")
        self.assertEqual(report["verdict"]["decision"], "DO NOT SHIP")

    def test_immature_flags_are_reported_but_never_counted_as_misses(self):
        late = _pattern_lots(overrides={**_SPIKES, _DAY_COUNT - 2: 5_000})
        self.write_fixture(
            contracts=[_contract("AAF", "1001", lots=late)],
            spot=_spot_volumes(_BUMPS_AFTER_SPIKES),
        )
        report = self.report()
        self.assertEqual(report["sets"]["f_immature"], 1)
        self.assertEqual(report["sets"]["f"], 5)
        self.assertEqual(report["sets"]["f_all_including_immature"], 6)
        self.assertNotIn(("AAF", _DAYS[_DAY_COUNT - 2]), self.flagged_pairs(report))


class UnknownSpotFlagTests(_FixtureDB):
    """S(s, t) 算不出來的旗標日:計進 F,但**不**進 F_only。"""

    def test_an_unknown_spot_flag_keeps_the_day_out_of_f_only(self):
        # 2026-04-13(index 70)是四月結算窗口裡的一天,所以它被 R4 排除在**期貨**
        # 比較窗口之外(R2b 因此讀不到它),但它仍在**現貨**的 60 日窗口裡——現貨
        # 不套 R4。把那一天的現貨量設成 NULL,S 就對其後 60 個交易日全部變成
        # 「不知道」,而那正好蓋掉前三個尖峰。
        self.assertEqual(_DAYS[70], "2026-04-13")
        spot = _spot_volumes(_BUMPS_AFTER_SPIKES)
        spot[70] = None
        self.write_fixture(contracts=[_contract("AAF", "1001")], spot=spot)
        report = self.report()
        self.assertEqual(report["sets"]["f"], 5)
        self.assertEqual(report["sets"]["f_with_unknown_spot_flag"], 3)
        self.assertEqual(report["sets"]["f_only"], 2)
        self.assertEqual(
            sorted(date for _code, date in self.flagged_pairs(report)),
            [_DAYS[147], _DAYS[168]],
        )


class MultiplierMigrationTests(unittest.TestCase):
    """既有資料庫檔案要靠 additive migration 拿到這一欄,而且既有列維持 NULL。"""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.old_url, self.old_dir = config.DB_URL, config.DATA_DIR
        self.db_path = self.tmp_path / "legacy.db"
        config.DB_URL = "sqlite:///" + self.db_path.as_posix()
        config.DATA_DIR = self.tmp_path
        db._engine = None

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self.old_url, self.old_dir
        self.tmp.cleanup()

    def test_an_existing_table_gains_the_column_with_null_for_every_row(self):
        import sqlite3

        connection = sqlite3.connect(self.db_path)
        try:
            # 這一段是**加欄位之前**的 futures_contracts,逐字照舊。
            connection.execute("""
                CREATE TABLE futures_contracts (
                    contract_code TEXT NOT NULL,
                    stock_id TEXT NOT NULL,
                    stock_name TEXT,
                    is_stock_future BOOLEAN,
                    is_stock_option BOOLEAN,
                    is_weekly_option BOOLEAN,
                    market TEXT,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    PRIMARY KEY (contract_code)
                )
            """)
            connection.execute(
                "INSERT INTO futures_contracts (contract_code, stock_id, first_seen, "
                "last_seen) VALUES ('CCF', '2303', '2026-09-15', '2026-09-16')"
            )
            connection.commit()
        finally:
            connection.close()

        db.init_db()
        with db.get_engine().connect() as conn:
            columns = {
                row[1]: row
                for row in conn.exec_driver_sql(
                    "PRAGMA table_info(futures_contracts)"
                ).fetchall()
            }
            rows = conn.exec_driver_sql(
                "SELECT contract_code, contract_multiplier FROM futures_contracts"
            ).fetchall()
        self.assertIn("contract_multiplier", columns)
        self.assertEqual(columns["contract_multiplier"][2], "INTEGER")
        self.assertEqual(columns["contract_multiplier"][3], 0, "must stay nullable")
        # 既有列不是被重建的,而且它的乘數是 NULL = 未知,不是 2,000。
        self.assertEqual(rows, [("CCF", None)])

        db.init_db()    # 再跑一次不得重覆加欄位
        with db.get_engine().connect() as conn:
            self.assertEqual(
                sum(1 for row in conn.exec_driver_sql(
                    "PRAGMA table_info(futures_contracts)"
                ).fetchall() if row[1] == "contract_multiplier"),
                1,
            )


class ReadOnlyAndOutputTests(_FixtureDB):
    def test_the_battery_writes_nothing_to_the_database(self):
        self.write_fixture(contracts=_standard_contracts(2),
                           spot=_spot_volumes(_BUMPS_AFTER_SPIKES))
        if db._engine is not None:
            db._engine.dispose()
            db._engine = None
        before = self.db_path.read_bytes()
        out = self.tmp_path / "battery.json"
        report = write_futures_volume_battery(as_of=_DAYS[-1], out=out)
        self.assertEqual(self.db_path.read_bytes(), before)
        self.assertFalse(report["metadata"]["database_writes"])
        self.assertFalse(report["metadata"]["schema_changes"])
        written = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(written["verdict"], report["verdict"])

    def test_the_multiplier_column_stays_null_for_every_existing_row(self):
        self.write_fixture(contracts=[_contract("NULF", "1001", multiplier=None)])
        with db.get_engine().connect() as conn:
            rows = conn.exec_driver_sql(
                "SELECT contract_multiplier FROM futures_contracts"
            ).fetchall()
        self.assertEqual([row[0] for row in rows], [None])

    def test_the_output_path_may_not_be_the_database(self):
        self.write_fixture(contracts=_standard_contracts(1))
        with self.assertRaisesRegex(ValueError, "must not be"):
            write_futures_volume_battery(as_of=_DAYS[-1], out=str(self.db_path))

    def test_cli_runs_the_battery_and_prints_the_verdict(self):
        self.write_fixture(contracts=_standard_contracts(2),
                           spot=_spot_volumes(_BUMPS_AFTER_SPIKES))
        if db._engine is not None:
            db._engine.dispose()
            db._engine = None
        out = self.tmp_path / "cli.json"
        main(["futures-volume-battery", "--as-of", _DAYS[-1], "--out", str(out)])
        written = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(written["metadata"]["run_number"], 1)
        self.assertEqual(written["tests"]["A"]["outcome"], "UNDERPOWERED")


if __name__ == "__main__":
    unittest.main()
