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
    PREREGISTRATION_AMENDMENT,
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

# 現貨爆量日:尖峰日 **+ 5**。量嚴格遞增,所以每一個都是它自己的 60 日新高。
# 為什麼是第 5 天而不是第 2 天:命中一個爆量日的日子是它前面那 5 天,而爆量放在
# 尖峰 + 5 時,那 5 天恰好是 {尖峰, 尖峰+1..+4}——全部都因為共用往後窗口而不在
# 安慰劑池裡。於是 ``h_P = 0`` 是**構造出來的**,不是跑出來之後抄回來的。
_BUMPS_AFTER_SPIKES = {
    index + FORWARD_SPOT_DAYS: 2_000_000 + 1_000_000 * order
    for order, index in enumerate(_SPIKE_INDEXES)
}
_BUMPS_ON_SPIKES = {
    index: 2_000_000 + 1_000_000 * order
    for order, index in enumerate(_SPIKE_INDEXES)
}
# 「每 5 天就爆一次量,只有尖峰日不爆」:任何一天的往後 5 天裡都一定有一個爆量日,
# 所以安慰劑臂與旗標臂的命中率都是 100%,檢定 B 因此必敗;而尖峰日自己維持底量,
# 所以它們是 ¬S,進得了 F_only。尖峰另取一組,避開 index % 5 == 0 的爆量日。
_FAIL_SPIKE_INDEXES = (84, 106, 127, 148, 169)
_FAIL_SPIKES = dict(zip(_FAIL_SPIKE_INDEXES, _SPIKE_LOTS))
_BUMPS_EVERY_FIVE = {
    index: 2_000_000 + 10_000 * index
    for index in range(_DAY_COUNT) if index % FORWARD_SPOT_DAYS == 0
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


def _rising_spot() -> dict[int, int]:
    """每天都比昨天多一點,只有尖峰日凹下去。

    於是**每一個非尖峰日都是它自己的現貨 60 日新高**(S = 1),而尖峰日是 ¬S。
    安慰劑合格日要的是 ¬S,所以這份現貨序列把池子餓死到一天不剩——但餓死的理由
    是現貨天天創高,不是「期貨那天不夠大」。
    """
    volumes = {index: 1_000_000 + 1_000 * index for index in range(_DAY_COUNT)}
    volumes.update({index: 500_000 for index in _SPIKE_INDEXES})
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

    def test_sets_f_is_documented_as_not_being_test_a_input(self):
        """`sets.f` 與檢定 A 的輸入不是同一個數,這件事必須寫在 JSON 自己身上。

        §3.4 要求記錄 |F|,所以 `sets.f` 這個鍵不能改名;但修訂之後檢定 A 讀的是
        `sets.f_with_established_spot_flag`。讀 JSON 的人若拿 `sets.f` 去跟 30 比,
        得到的是修訂前的答案——而規則凍結之後,這扇門就關上了。所以把區別寫進
        `_definitions()`,並用這條測試釘住:拿掉說明就要先刪掉這條測試。
        """
        from radar.compute.futures_volume_battery import _definitions

        d = _definitions()
        self.assertIn("sets.f", d, "sets.f 必須有自己的說明,不能只靠讀者推敲")
        text = d["sets.f"]
        self.assertIn("NOT the input to test A", text)
        self.assertIn("f_with_established_spot_flag", text,
                      "說明要指出真正的輸入是哪一個鍵,不能只說『不是這個』")

    def test_the_amendment_is_named_and_claims_v1_standing(self):
        """§6 修訂沒有動任何一個數字,但它必須在 JSON 裡指認得出來。

        修訂的地位來自「回補資料當時還看不見」,不來自某一個 hash——凍結規則的
        觸發點是資料可見性。這條測試鎖住那句宣稱會被寫出去。
        """
        self.assertIn("§6", PREREGISTRATION_AMENDMENT)
        self.assertIn("before any backfilled futures data was queried",
                      PREREGISTRATION_AMENDMENT)


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

    def test_a_quiet_day_is_seen_by_the_rule_and_not_refused(self):
        """§6 修訂 1 的迴歸:平靜日**不**撞 R2b,所以它進得了安慰劑池。

        今天等於自己的中位數 → 超出量 0 口 → 實質性不等式結構上不可能成立。
        舊版把那條不等式套在每一個契約-日上,於是「安慰劑 = R1–R5 全過且
        flag = 0」把所有平靜日都排掉了,對照組變成「接近創高的日子」——那是
        另一個假設,不是比較嚴格的同一個假設。
        """
        quiet = evaluate_contract_day(
            today_volume=100, window_volumes=[100] * WINDOW_DAYS,
            multiplier=_MULTIPLIER, spot_window_volumes=[_SPOT_BASE] * WINDOW_DAYS,
        )
        self.assertIsNone(quiet["refusal"])
        self.assertFalse(quiet["flag"])
        # 薄契約的平靜日同樣不被否決:那正是舊寫法餓死安慰劑池的地方
        # (窗口中位數 3 口,對上 5,000,000 股的現貨日常量)。
        thin = evaluate_contract_day(
            today_volume=3, window_volumes=[3] * WINDOW_DAYS, multiplier=_MULTIPLIER,
            spot_window_volumes=[5_000_000] * WINDOW_DAYS,
        )
        self.assertIsNone(thin["refusal"])
        self.assertFalse(thin["flag"])
        # 低於中位數的日子(超出量是負的)也一樣只是「看過、沒舉旗」。
        below = evaluate_contract_day(
            today_volume=1, window_volumes=[3] * WINDOW_DAYS, multiplier=_MULTIPLIER,
            spot_window_volumes=[5_000_000] * WINDOW_DAYS,
        )
        self.assertIsNone(below["refusal"])
        self.assertFalse(below["flag"])

    def test_r2b_materiality_is_the_three_times_two_lots_case(self):
        # 文件的例子:中位數 2 口的契約,6 口就是 3 倍。
        # 100 × (6 − 2) × 2,000 = 800,000 股 < 現貨日常量 1,000,000 股 → 否決。
        # 6 口同時也創了 60 日新高(窗口全是 2 口),所以實質性這關才會被問到。
        outcome = evaluate_contract_day(
            today_volume=6, window_volumes=[2] * WINDOW_DAYS, multiplier=_MULTIPLIER,
            spot_window_volumes=[_SPOT_BASE] * WINDOW_DAYS,
        )
        self.assertEqual(outcome["refusal"], "R2b_immaterial")
        self.assertFalse(outcome["flag"])
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

    def test_maturity_needs_all_five_forward_flags_to_be_known(self):
        """§6 修訂 2:五個往後日的 S 有一個算不出來,這一天就不成熟。

        §3.1 寫的是不進分母**也不算未命中**。只數「有沒有 5 天」的話,答案是
        ``None`` 的那一天會被 ``forward_hit`` 讀成「沒命中」,後半句就被違反了。
        index 105 的量抽掉之後,S(105) 變成不知道:以它為第 5 天的 index 100
        因此不成熟,而往後窗口停在 104 的 index 99 照樣成熟。
        """
        self.volumes[self.days[105]] = None
        calendar = _StockCalendar(self.days, self.volumes)
        self.assertTrue(calendar.is_mature(self.days[99]))
        self.assertFalse(calendar.is_mature(self.days[100]))
        # 只缺了往後窗口,這一天自己的 S 仍然算得出來——不成熟不是因為讀不到 t。
        self.assertIs(calendar.new_high(self.days[100]), False)

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
            discriminability_verdict(
                f_established_count=40, f_only_count=LOW_SAMPLE_SURVIVORS,
            )["outcome"],
            "PASS",
        )
        redundant = discriminability_verdict(
            f_established_count=LOW_SAMPLE_SURVIVORS,
            f_only_count=LOW_SAMPLE_SURVIVORS - 1,
        )
        self.assertEqual(redundant["outcome"], "REDUNDANT WITH SPOT")
        underpowered = discriminability_verdict(
            f_established_count=LOW_SAMPLE_SURVIVORS - 1, f_only_count=0,
        )
        self.assertEqual(underpowered["outcome"], "UNDERPOWERED")
        self.assertIn("NOT a refutation", underpowered["line"])

    def test_redundant_needs_thirty_days_whose_spot_flag_is_established(self):
        """§6 修訂 4:冗餘是一句關於 S = 1 的話,湊不出 30 天就不能講。

        檢定 A 讀的是 ``|F_only| + |F_{S=1}|``。少一天(現貨旗標不知道的那種)
        就從「冗餘」掉回「檢定力不足」——兩者不是同一種紀錄:前者是一個結論,
        後者明說自己不是否證。
        """
        borderline = discriminability_verdict(
            f_established_count=LOW_SAMPLE_SURVIVORS, f_only_count=2,
        )
        self.assertEqual(borderline["outcome"], "REDUNDANT WITH SPOT")
        one_short = discriminability_verdict(
            f_established_count=LOW_SAMPLE_SURVIVORS - 1, f_only_count=2,
        )
        self.assertEqual(one_short["outcome"], "UNDERPOWERED")
        self.assertIn("unknown", one_short["line"])
        self.assertEqual(
            one_short["observed"]["f_with_established_spot_flag"],
            LOW_SAMPLE_SURVIVORS - 1,
        )

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
        # §6 修訂 5(i):不可評估 = 不上線,而且對 §3.5 的重跑規則算「無結果」。
        self.assertIn("DO NOT SHIP", verdict["means"])
        self.assertIn("無結果", verdict["means"])
        decision = overall_verdict(
            test_a=discriminability_verdict(f_established_count=40, f_only_count=40),
            test_b=verdict,
        )
        self.assertEqual(decision["decision"], "DO NOT SHIP")
        self.assertEqual(decision["reason"], "not_evaluable")

    def test_shipping_needs_both_tests(self):
        passing_a = discriminability_verdict(f_established_count=40, f_only_count=40)
        passing_b = informativeness_verdict(seeds=[
            seed_result(seed=s, n=40, h_f=40, h_p=0, matched=True) for s in PLACEBO_SEEDS
        ])
        self.assertEqual(
            overall_verdict(test_a=passing_a, test_b=passing_b)["decision"], "SHIP",
        )
        self.assertEqual(
            overall_verdict(
                test_a=discriminability_verdict(f_established_count=40, f_only_count=1),
                test_b=passing_b,
            )["reason"],
            "redundant_with_spot",
        )
        self.assertEqual(
            overall_verdict(
                test_a=discriminability_verdict(f_established_count=1, f_only_count=1),
                test_b=passing_b,
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
        # 每 5 天一個現貨爆量日,所以**任何**一天的往後 5 天裡都有一個新高:
        # 旗標臂與安慰劑臂的命中率都是 100%,差距 0,檢定 B 必敗。
        contracts = [
            _contract(f"S{index}F", f"100{index}",
                      lots=_pattern_lots(overrides=_FAIL_SPIKES))
            for index in range(1, 9)
        ]
        self.write_fixture(contracts=contracts,
                           spot=_spot_volumes(_BUMPS_EVERY_FIVE))
        report = self.report()
        self.assertEqual(report["tests"]["A"]["outcome"], "PASS")
        self.assertEqual(report["tests"]["B"]["outcome"], "FAIL")
        for seed in report["tests"]["B"]["seeds"]:
            self.assertEqual(seed["h_p"], seed["n"], seed["seed"])
            self.assertFalse(seed["passed"])
        self.assertEqual(report["verdict"]["reason"], "forward_test_failed")
        self.assertEqual(report["verdict"]["decision"], "DO NOT SHIP")

    def test_an_empty_placebo_pool_is_not_evaluable_rather_than_a_pass(self):
        # 現貨天天創高(只有尖峰日凹下去),所以「¬S」的日子只剩尖峰日自己,而尖峰日
        # 正是旗標日 → 合格日一天都不剩,安慰劑抽不滿 k。h_P 會被少抽的日子系統性
        # 壓低,所以裁決是「不可評估」,不是「過」。
        contracts = [
            _contract(f"N{index}F", f"200{index}") for index in range(1, 9)
        ]
        self.write_fixture(contracts=contracts, spot=_rising_spot())
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

    def test_a_short_draw_names_the_stocks_and_their_pool_sizes(self):
        """§6 修訂 5(ii):抽不滿時,JSON 要逐檔寫出 (stock_id, k, pool_size)。

        差額與 seed 無關(每個 seed 都抽 ``min(k, |pool|)`` 天),而讀者必須能分辨
        「這檔結構性餓死、再多資料也救不了」與「再等幾個月就補得滿」。一個總數
        辦不到這件事,所以這是報告義務,不是規則。
        """
        contracts = [_contract(f"N{index}F", f"200{index}") for index in range(1, 9)]
        self.write_fixture(contracts=contracts, spot=_rising_spot())
        report = self.report()
        self.assertEqual(
            report["sets"]["placebo_short_stocks"],
            [{"stock_id": f"200{index}", "k": len(_SPIKE_INDEXES), "pool_size": 0}
             for index in range(1, 9)],
        )
        self.assertIn("DO NOT SHIP", report["tests"]["B"]["means"])
        self.assertIn("無結果", report["tests"]["B"]["means"])

    def test_a_pool_that_is_large_enough_names_no_short_stock(self):
        self.write_fixture(contracts=_standard_contracts(8),
                           spot=_spot_volumes(_BUMPS_AFTER_SPIKES))
        self.assertEqual(self.report()["sets"]["placebo_short_stocks"], [])

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


# 現貨量缺一天,會在兩個地方同時留下洞,而那兩個洞的半徑不一樣:
#   * 該日之後 60 個現貨交易日的 S 全部變成「不知道」(它落在人家的比較窗口裡);
#   * 以那些日子為往後窗口成員的更早的日子,因此**不成熟**(§6 修訂 2)。
# 洞挖在 R4 排除日上,期貨比較窗口跳過它,所以 R2b 的尺不會因此破掉——這是唯一
# 能讓「旗標日的 S 未知、但它仍然成熟」同時成立的位置。
_SPOT_HOLE_INDEX = 94                       # 2026-05-15,五月結算窗口第一天
_UNKNOWN_FLAG_INDEX = _SPOT_HOLE_INDEX + WINDOW_DAYS     # 154 = 2026-08-07
_UNKNOWN_FLAG_LOTS = 850                    # > 前四個尖峰的最高 800 口


class UnknownSpotFlagTests(_FixtureDB):
    """S(s, t) 算不出來的旗標日:計進 F,但**不**進 F_only,也不能撐起「冗餘」。"""

    def test_an_unknown_spot_flag_keeps_the_day_out_of_f_only(self):
        # index 94 是五月結算窗口裡的一天,被 R4 排除在**期貨**比較窗口之外(R2b
        # 因此讀不到它),但它仍在**現貨**的 60 日窗口裡——現貨不套 R4。
        # index 154 = 94 + 60 是最後一個把它含進 S 窗口的日子,而 155..159 的窗口
        # 都已經越過它,所以 154 是「S 未知但成熟」;105/126/147 則連往後窗口都被
        # 蓋住,依 §6 修訂 2 不成熟。
        self.assertEqual(_DAYS[_SPOT_HOLE_INDEX], "2026-05-15")
        self.assertEqual(_DAYS[_UNKNOWN_FLAG_INDEX], "2026-08-07")
        spot = _spot_volumes(_BUMPS_AFTER_SPIKES)
        spot[_SPOT_HOLE_INDEX] = None
        lots = _pattern_lots(overrides={
            **_SPIKES, _UNKNOWN_FLAG_INDEX: _UNKNOWN_FLAG_LOTS,
        })
        self.write_fixture(contracts=[_contract("AAF", "1001", lots=lots)], spot=spot)
        report = self.report()
        self.assertEqual(report["sets"]["f_all_including_immature"], 6)
        self.assertEqual(report["sets"]["f_immature"], 3)
        self.assertEqual(report["sets"]["f"], 3)
        self.assertEqual(report["sets"]["f_with_unknown_spot_flag"], 1)
        self.assertEqual(report["sets"]["f_with_established_spot_flag"], 2)
        self.assertEqual(report["sets"]["f_only"], 2)
        self.assertEqual(
            sorted(date for _code, date in self.flagged_pairs(report)),
            [_DAYS[84], _DAYS[168]],
        )


# §6 修訂 4 的構造:每一檔股票挖兩個現貨洞,洞都在 R4 排除日上,而洞 + 60 天
# 正好是一個期貨尖峰日。於是每個尖峰都是「S 未知但成熟」,|F| 湊得到 30 以上,
# |F_only| 與 |F_{S=1}| 卻都是 0。兩個洞相距 85 天 > 64,所以彼此不蓋到對方那
# 一組往後窗口——否則尖峰會變成不成熟,連 |F| 都湊不出來。
_UNKNOWN_HOLE_INDEXES = (29, 114)
_UNKNOWN_SPIKE_INDEXES = tuple(
    index + WINDOW_DAYS for index in _UNKNOWN_HOLE_INDEXES
)   # 89、174
_UNKNOWN_SPIKE_LOTS = (500, 600)
_UNKNOWN_STOCK_COUNT = 16       # 16 × 2 = 32 面旗標,剛好越過 30


class UnknownSpotFlagVerdictTests(_FixtureDB):
    def test_redundant_is_unreachable_when_f_only_clears_thirty_via_unknown_days(self):
        """§6 修訂 4:靠 S 未知的日子湊到 30,是檢定力不足,不是冗餘。

        「冗餘」宣稱的是「期貨創高多半是現貨創高的回聲」——一句只關於 S = 1 的
        話。這裡 32 面旗標的 S 一個都不知道,所以它們對那句話一個字都沒說;
        把 |F| 直接餵給檢定 A 的舊寫法會在這份 fixture 上輸出「冗餘」,而那是一個
        **結論**,會被寫進 STATUS 告訴使用者「這個功能沒有獨立內容」。
        """
        spot = _spot_volumes()
        for index in _UNKNOWN_HOLE_INDEXES:
            spot[index] = None
        lots = _pattern_lots(overrides=dict(
            zip(_UNKNOWN_SPIKE_INDEXES, _UNKNOWN_SPIKE_LOTS)
        ))
        contracts = [
            _contract(f"U{index}F", f"300{index}", lots=lots)
            for index in range(1, _UNKNOWN_STOCK_COUNT + 1)
        ]
        self.write_fixture(contracts=contracts, spot=spot)
        report = self.report()
        expected = _UNKNOWN_STOCK_COUNT * len(_UNKNOWN_SPIKE_INDEXES)
        self.assertEqual(report["sets"]["f"], expected)
        self.assertGreaterEqual(expected, LOW_SAMPLE_SURVIVORS)
        self.assertEqual(report["sets"]["f_with_unknown_spot_flag"], expected)
        self.assertEqual(report["sets"]["f_with_established_spot_flag"], 0)
        self.assertEqual(report["sets"]["f_only"], 0)
        self.assertEqual(report["tests"]["A"]["outcome"], "UNDERPOWERED")
        self.assertIn("NOT a refutation", report["tests"]["A"]["line"])
        self.assertEqual(report["verdict"]["reason"], "underpowered")


# 這份 fixture 的安慰劑池大小是**手算**的,不是跑出來抄回來的:
#   候選日 = index 76..194(76 是第一個湊得滿 60 個非排除日的日子,194 是最後一個
#   有 5 個往後現貨日的日子)共 119 天,扣掉區間內的 20 個 R4 排除日 = 99 天;
#   扣掉 5 個現貨爆量日(S = 1)與 5 個旗標日 = 89 天;再扣掉「旗標日 + 其後 5 天」
#   這 30 天裡尚未被扣掉的 20 天 = **69 天**。
_ORDINARY_POOL_DAYS = 69
# 現貨量在 index 190 缺一天:185..189 因為往後窗口有未知的 S 而不成熟(§6 修訂 2),
# 190..194 的 S 本身就是未知(不是 False),兩段共 10 天離開池子。
_LATE_SPOT_HOLE_INDEX = 190
_POOL_DAYS_AFTER_LATE_HOLE = 59


class PlaceboPoolShapeTests(_FixtureDB):
    """安慰劑池裝的是**平常的日子**,不是「差一點就創高的日子」。"""

    def test_the_pool_is_every_ordinary_day_the_rule_looked_at(self):
        """§6 修訂 1 的迴歸,在報告這一層。

        舊寫法把 R2b 的實質性不等式套在每一個契約-日上,於是只有「超出中位數夠多」
        的日子進得了池子——這份 fixture 裡就只剩每七天一個的中量日。池子從 69 天
        縮到十幾天,而且縮的方向是系統性的:對照組被換成了接近創高的日子。
        """
        self.write_fixture(contracts=[_contract("AAF", "1001")],
                           spot=_spot_volumes(_BUMPS_AFTER_SPIKES))
        report = self.report()
        self.assertEqual(report["sets"]["f_only"], len(_SPIKE_INDEXES))
        self.assertEqual(report["sets"]["placebo_pool_days"], _ORDINARY_POOL_DAYS)
        self.assertEqual(report["refusals"]["R2b_immaterial"], 0)

    def test_a_day_with_an_unknown_forward_flag_leaves_the_pool_too(self):
        """§6 修訂 2:不成熟的日子兩臂都不進,**安慰劑池也不進**。"""
        spot = _spot_volumes(_BUMPS_AFTER_SPIKES)
        spot[_LATE_SPOT_HOLE_INDEX] = None
        self.write_fixture(contracts=[_contract("AAF", "1001")], spot=spot)
        report = self.report()
        self.assertEqual(report["sets"]["f_only"], len(_SPIKE_INDEXES))
        self.assertEqual(
            report["sets"]["placebo_pool_days"], _POOL_DAYS_AFTER_LATE_HOLE,
        )


# 薄契約 + 厚契約掛在同一檔股票上。厚契約在 index 126 沒有列,所以那一天的資格
# 完全由薄契約決定——這是唯一能把「某一天進不進池子」單獨量出來的擺法,因為
# 合格日是**逐股票**聯集的,同一天只要有任何一個契約合格就會進池子。
_THIN_PROBE_INDEX = 126
_THIN_POOL_DAYS = 93            # 99 個候選日 − 「旗標日 + 其後 5 天」6 天
_THIN_POOL_DAYS_IF_IMMATERIAL = _THIN_POOL_DAYS - 1


class ImmaterialNewHighTests(_FixtureDB):
    """實質性擋下來的創高日:旗標臂不進,安慰劑池也不進。"""

    def _fixture(self, probe_lots: int) -> dict:
        fat = _pattern_lots(overrides={84: 500, _THIN_PROBE_INDEX: None})
        thin = _pattern_lots(base=2, medium=None,
                             overrides={_THIN_PROBE_INDEX: probe_lots})
        self.write_fixture(contracts=[
            _contract("FATF", "1001", lots=fat),
            _contract("THIF", "1001", lots=thin),
        ])
        return self.report()

    def test_a_quiet_probe_day_is_in_the_pool(self):
        report = self._fixture(probe_lots=2)
        self.assertEqual(report["sets"]["f_only"], 1)
        self.assertEqual(report["sets"]["placebo_pool_days"], _THIN_POOL_DAYS)
        self.assertEqual(report["refusals"]["R2b_immaterial"], 0)

    def test_an_immaterial_new_high_enters_neither_arm(self):
        """§2 標頭:否決把該日從旗標**與** §3 樣本一起移除。

        6 口對上中位數 2 口的窗口是創高,但 100 × (6 − 2) × 2,000 = 800,000 股
        <  現貨日常量 1,000,000 股,所以它被 R2b 擋下。它不上榜(旗標臂),而池子
        剛好少一天(安慰劑臂)——少的正是它自己。
        """
        report = self._fixture(probe_lots=6)
        self.assertEqual(report["sets"]["f_only"], 1)
        self.assertNotIn(("THIF", _DAYS[_THIN_PROBE_INDEX]), self.flagged_pairs(report))
        self.assertEqual(report["refusals"]["R2b_immaterial"], 1)
        self.assertEqual(
            report["sets"]["placebo_pool_days"], _THIN_POOL_DAYS_IF_IMMATERIAL,
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
