"""期貨訊號之後買得到那一天漲 ≥ 3% 的 battery(docs/40,事前登記 `e9212bd`)。

fixture 的每一個數字都是**發明的**,為了能手算:

- 市場日曆 D = 2026-02-02..2026-10-16 的平日;期貨日曆少最後一天(**正式機的形狀**,
  docs/38 §7.12:現貨比期貨多一個交易日),所以 as_of = 2026-10-15、價格視界 10-16。
- 期貨量平常 100 口,舉旗日 ``1000 + 10k`` 口(k = 該契約第幾次舉旗,所以永遠創新高);
  乘數 2000 → 實質。乘數 1 的契約舉旗必然 ``R2b_immaterial``。
- 現貨量平常 1,000,000 股,恆不創新高 → ``S = False``;要 ``S = True`` 就給更大的量。
- 價格平常開 100 收 100(不漲不跌);情境把某些 e 日的收盤改成 104 / 96。

沒有一個數字來自真實資料。
"""
import hashlib
import io
import json
import re
import sqlite3
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import radar.config as config
import radar.db as db
from radar.cli import main
from radar.compute import branch_window_direction_battery as bwd
from radar.compute import futures_volume_battery as fvb
from radar.compute import next_day_futures_signal_battery as nfs
from radar.compute import next_day_surge_battery as nds
from radar.compute import settlement_calendar as sc

from tests.test_futures_export import RANK_ISH, RATIO_ISH

PIPELINE = Path(__file__).resolve().parents[1]


def _weekdays(start: date, end: date) -> list[str]:
    days, current = [], start
    while current <= end:
        if current.weekday() < 5:
            days.append(current.isoformat())
        current += timedelta(days=1)
    return days


DAYS = _weekdays(date(2026, 2, 2), date(2026, 10, 16))   # D
FUT_DAYS = DAYS[:-1]                                      # 期貨少最後一天
AS_OF = FUT_DAYS[-1]                                      # 2026-10-15
HORIZON = DAYS[-1]                                        # 2026-10-16
BASE_FUT = 100
BASE_SPOT = 1_000_000
MISSING = object()


def after(day: str, count: int) -> str | None:
    """測試自己的日曆算術,不借 battery 的函式。"""
    index = DAYS.index(day) + count
    return DAYS[index] if index < len(DAYS) else None


class Market:
    """一份自造的市場:股票、契約、舉旗日、現貨量與價格覆寫。"""

    def __init__(self):
        self.types: dict[str, str] = {}
        self.contracts: list[dict] = []
        self.spikes: dict[str, set[str]] = {}
        self.spot: dict[tuple[str, str], object] = {}
        self.bars: dict[tuple[str, str], object] = {}
        self.fut_missing: dict[str, set[str]] = {}   # 契約 → 沒有一般時段列的日子

    def add(self, stock_id, *, type_="stock", contracts=None):
        self.types[stock_id] = type_
        for code, multiplier in contracts or [(f"{stock_id}F", 2000)]:
            self.contracts.append({"contract_code": code, "stock_id": stock_id,
                                   "contract_multiplier": multiplier})
            self.spikes.setdefault(code, set())
        return self

    def spike(self, code, *days):
        self.spikes[code].update(days)
        return self

    def close(self, stock_id, day, close):
        self.bars[(stock_id, day)] = {"close": close}

    def futures_volumes(self, code) -> dict[str, int]:
        volumes, count = {}, 0
        for day in FUT_DAYS:
            if day in self.fut_missing.get(code, ()):
                continue
            if day in self.spikes[code]:
                volumes[day] = 1000 + 10 * count
                count += 1
            else:
                volumes[day] = BASE_FUT
        return volumes

    def price_rows(self) -> dict[tuple[str, str], dict]:
        rows = {}
        for stock_id in self.types:
            for day in DAYS:
                volume = self.spot.get((stock_id, day), BASE_SPOT)
                if volume is MISSING or self.bars.get((stock_id, day)) is MISSING:
                    continue
                rows[(stock_id, day)] = {"open": 100.0, "close": 100.0, "volume": volume,
                                         **self.bars.get((stock_id, day), {})}
        return rows

    def inputs(self) -> dict:
        spot = {}
        for (stock_id, day), row in sorted(self.price_rows().items()):
            days, volumes = spot.setdefault(stock_id, ([], {}))
            days.append(day)
            volumes[day] = row["volume"]
        return {
            "futures_days": list(FUT_DAYS),
            "market_days": list(DAYS),
            "contracts": [dict(contract) for contract in self.contracts],
            "stock_types": dict(self.types),
            "per_contract": {
                contract["contract_code"]: {
                    "volume": self.futures_volumes(contract["contract_code"]),
                    "open_interest": {},
                }
                for contract in self.contracts
            },
            "spot": spot,
        }

    def structure(self):
        return nfs.signal_structure(as_of=AS_OF, **self.inputs())

    def report(self, structure=None):
        return nfs.assemble(
            structure=structure or self.structure(), market_days=list(DAYS),
            horizon=HORIZON, bars=self.price_rows(), run_number=1,
        )


def grid(*, stocks=20, period=5, everyone_on=None) -> Market:
    """股票 i 在期貨日 j 舉旗若且唯若 ``(i + j) % period == 0``:每天 4 檔舉旗、16 檔安靜。"""
    market = Market()
    for i in range(stocks):
        stock_id = f"S{i:02d}"
        market.add(stock_id)
        market.spike(f"{stock_id}F",
                     *[day for j, day in enumerate(FUT_DAYS) if (i + j) % period == 0])
        if everyone_on:
            market.spike(f"{stock_id}F", everyone_on)
    return market


def scorable(structure) -> list[tuple[str, str]]:
    """事件中 e 日落在價格視界內的那些(這份 fixture 每一列都有價格)。"""
    return [key for key in structure["events"] if after(key[1], 2) is not None]


def set_outcome(market: Market, key, close):
    market.close(key[0], after(key[1], 2), close)


# ── §0:日曆、hit / drop ──────────────────────────────────────────────────

class CalendarTests(unittest.TestCase):
    def test_e_is_the_second_market_day_after_t(self):
        self.assertEqual(nfs.entry_day(DAYS, "2026-07-02"), "2026-07-06")
        self.assertEqual(nfs.visible_day(DAYS, "2026-07-02"), "2026-07-03")
        self.assertEqual(nfs.ENTRY_MARKET_DAYS_AFTER, 2)
        # t 本身不在 D 裡也一樣(週六):之後第 2 個市場日。
        self.assertEqual(nfs.entry_day(DAYS, "2026-07-04"), "2026-07-07")
        self.assertIsNone(nfs.entry_day(DAYS, AS_OF))
        self.assertEqual(nfs.entry_day(DAYS, FUT_DAYS[-2]), HORIZON)

    def test_the_exclusion_window_is_frozen(self):
        self.assertEqual(nfs.EXCLUSION_FROM, "2026-09-18")
        self.assertEqual(nfs.EXCLUSION_TO, "2026-10-02")
        self.assertFalse(nfs.in_exclusion_window("2026-09-17"))
        self.assertTrue(nfs.in_exclusion_window("2026-09-18"))
        self.assertTrue(nfs.in_exclusion_window("2026-10-02"))
        self.assertFalse(nfs.in_exclusion_window("2026-10-03"))
        self.assertFalse(nfs.in_exclusion_window("2026-10-05"))

    def test_hit_and_drop_are_three_percent_in_decimal(self):
        self.assertEqual(nfs.THRESHOLD_PCT, 3)
        self.assertEqual(nfs.LEG, "entry_open_to_close")
        self.assertTrue(nfs.moved_up(open_price=100.0, close_price=103.0, pct=3))
        self.assertFalse(nfs.moved_up(open_price=100.0, close_price=102.99, pct=3))
        self.assertTrue(nfs.moved_down(open_price=100.0, close_price=97.0, pct=3))
        self.assertFalse(nfs.moved_down(open_price=100.0, close_price=97.01, pct=3))
        # 12.35 × 1.03 = 12.7205、× 0.97 = 11.9795:門檻上的那一天不交給浮點。
        self.assertTrue(nfs.moved_up(open_price=12.35, close_price=12.7205, pct=3))
        self.assertFalse(nfs.moved_up(open_price=12.35, close_price=12.7204, pct=3))
        self.assertTrue(nfs.moved_down(open_price=12.35, close_price=11.9795, pct=3))
        self.assertFalse(nfs.moved_down(open_price=12.35, close_price=11.9796, pct=3))


# ── §2:否決 ───────────────────────────────────────────────────────────────

class AssessTests(unittest.TestCase):
    BAR = {"open": 100.0, "close": 104.0, "volume": 5}

    def _assess(self, entry="E", bar=BAR, visible=None, horizon="Z"):
        return nfs.assess(entry=entry, horizon=horizon, entry_bar=bar, visible_bar=visible)

    def test_r1_and_r2_codes(self):
        self.assertEqual(self._assess(entry=None)["refusal"], "R1_no_entry_day")
        self.assertEqual(self._assess(entry="2026-10-19", horizon="2026-10-16")["refusal"],
                         "R1_no_entry_day")
        self.assertEqual(self._assess(bar=None)["refusal"], "R1_no_entry_row")
        for bad in (None, 0.0, -1.0):
            self.assertEqual(self._assess(bar={**self.BAR, "open": bad})["refusal"],
                             "R1_bad_open")
        self.assertEqual(self._assess(bar={**self.BAR, "close": None})["refusal"],
                         "R1_no_close")
        for halted in (0, None):
            self.assertEqual(self._assess(bar={**self.BAR, "volume": halted})["refusal"],
                             "R2_suspended")

    def test_a_clean_row_counts_hits_and_drops(self):
        outcome = self._assess()
        self.assertIsNone(outcome["refusal"])
        self.assertTrue(outcome["hit"])
        self.assertFalse(outcome["drop"])
        self.assertEqual(outcome["moves"][5], (False, False))
        down = self._assess(bar={**self.BAR, "close": 92.0})
        self.assertTrue(down["drop"])
        self.assertEqual(down["moves"][7], (False, True))

    def test_a_locked_limit_up_open_is_a_structural_miss_not_a_refusal(self):
        visible = {"open": 100.0, "close": 100.0, "volume": 5}
        outcome = self._assess(bar={"open": 110.0, "close": 110.0, "volume": 5},
                               visible=visible)
        self.assertIsNone(outcome["refusal"])
        self.assertFalse(outcome["hit"])
        self.assertTrue(outcome["limit_open"])
        self.assertFalse(self._assess(bar={"open": 109.4, "close": 109.4, "volume": 5},
                                      visible=visible)["limit_open"])


# ── §0 / §3.1:結構(訊號、事件、X、對照候選) ─────────────────────────────

class SegmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        market = Market().add("G")
        # 06-01/06-02 連續 → 一段;06-03 安靜;06-04 新的一段。
        # 06-12..06-17 是六月 R4 窗口:06-11 與 06-18 被它隔開,是兩段。
        market.spike("GF", "2026-06-01", "2026-06-02", "2026-06-04",
                     "2026-06-11", "2026-06-18")
        cls.structure = market.structure()

    def test_r4_days_are_the_june_settlement_window(self):
        for day in ("2026-06-12", "2026-06-15", "2026-06-16", "2026-06-17"):
            self.assertIn(day, self.structure["excluded"])

    def test_a_run_counts_once_and_any_non_signal_day_breaks_it(self):
        self.assertEqual(
            self.structure["events"],
            [("G", "2026-06-01"), ("G", "2026-06-04"), ("G", "2026-06-11"),
             ("G", "2026-06-18")],
        )
        self.assertEqual(len(self.structure["signal_days"]), 5)


class CalendarEdgeTests(unittest.TestCase):
    def test_runs_follow_the_futures_calendar_not_d(self):
        """期貨休市但現貨開市的那一天不在期貨日曆上:08-04 與 08-06 是相鄰的期貨日,一段。"""
        market = Market().add("A")
        market.spike("AF", "2026-08-04", "2026-08-06")
        inputs = market.inputs()
        inputs["futures_days"] = [day for day in inputs["futures_days"] if day != "2026-08-05"]
        structure = nfs.signal_structure(as_of=AS_OF, **inputs)
        self.assertEqual(structure["events"], [("A", "2026-08-04")])
        self.assertEqual(len(structure["signal_days"]), 2)

    def test_an_undeterminable_settlement_window_is_not_a_signal_day(self):
        """日曆停在 10-16:十月名目結算日 10-21 之前只剩 2 個平日,算不出窗口 → 不主張。"""
        market = Market().add("A")
        inputs = market.inputs()
        inputs["futures_days"] = list(DAYS)
        inputs["per_contract"]["AF"]["volume"][HORIZON] = 50_000
        structure = nfs.signal_structure(as_of=HORIZON, **inputs)
        self.assertEqual(structure["counts"]["settlement_undeterminable_days"], 1)
        self.assertEqual(structure["signal_days"], [])
        self.assertNotIn(("A", HORIZON), structure["pool_candidates"])
        # 日曆多知道一週後就看得出來:10-16 正是結算前 3 個市場日之一(R4)。不主張是對的。
        inputs["market_days"] = list(DAYS) + ["2026-10-19", "2026-10-20", "2026-10-21"]
        known = nfs.signal_structure(as_of=HORIZON, **inputs)
        self.assertIn(HORIZON, known["excluded"])
        self.assertEqual(known["signal_days"], [])

    def test_a_day_whose_contracts_are_all_refused_is_not_a_control(self):
        """W 的契約缺一列 → 之後 60 個期貨日 R1 否決;現貨照常、S 為 False,仍不是對照日。"""
        market = Market().add("W")
        market.fut_missing["WF"] = {"2026-07-01"}
        structure = market.structure()
        pool = set(structure["pool_candidates"])
        self.assertGreater(structure["counts"]["contract_refusals"]["R1_window_gap"], 0)
        for day in ("2026-07-02", "2026-07-20", "2026-08-03"):
            self.assertNotIn(("W", day), pool)
        self.assertIn(("W", "2026-06-30"), pool)


class ExclusionWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        market = Market()
        for stock_id in ("X1", "X2", "X3", "X4", "X5"):
            market.add(stock_id)
        market.spike("X1F", "2026-09-17")
        market.spike("X2F", "2026-09-18")
        market.spike("X3F", "2026-10-02")
        market.spike("X4F", "2026-10-05")
        market.spike("X5F", "2026-10-02", "2026-10-05")   # 段落始於 X 內
        cls.structure = market.structure()

    def test_x_removes_both_ends_inclusive_and_runs_are_found_first(self):
        self.assertEqual(self.structure["events"],
                         [("X1", "2026-09-17"), ("X4", "2026-10-05")])
        self.assertEqual(self.structure["counts"]["events_removed_by_x"], 3)
        self.assertEqual(self.structure["counts"]["signal_days_removed_by_x"], 3)
        self.assertEqual(
            self.structure["signal_days"],
            [("X1", "2026-09-17"), ("X4", "2026-10-05"), ("X5", "2026-10-05")],
        )

    def test_x_days_are_not_control_days(self):
        pool = set(self.structure["pool_candidates"])
        for day in ("2026-09-18", "2026-09-21", "2026-10-01", "2026-10-02"):
            self.assertNotIn(("X1", day), pool)
        self.assertIn(("X2", "2026-09-17"), pool)
        self.assertIn(("X1", "2026-10-05"), pool)
        self.assertIn(("X1", "2026-09-10"), pool)

    def test_x_days_are_not_in_the_halving_calendar(self):
        eval_days = self.structure["eval_days"]
        self.assertFalse([day for day in eval_days if "2026-09-18" <= day <= "2026-10-02"])
        self.assertEqual(
            eval_days,
            [day for day in DAYS if self.structure["evaluation_from"] <= day <= AS_OF
             and not "2026-09-18" <= day <= "2026-10-02"],
        )
        self.assertEqual(self.structure["counts"]["market_days_removed_by_x"], 11)
        halves = bwd.split_window(trading_days=eval_days, window_days=len(eval_days))
        self.assertEqual(self.structure["halves"], halves)


class EvaluationPeriodTests(unittest.TestCase):
    def test_only_population_contract_days_start_it(self):
        """ETF 契約比股票早被看過:評估期仍從股票第一個被看過的日子起算。"""
        market = Market().add("A").add("E50", type_="etf")
        market.fut_missing["AF"] = set(FUT_DAYS[:30])
        structure = market.structure()
        excluded = sc.settlement_exclusion_set(
            date_from=FUT_DAYS[0], date_to=AS_OF, market_days=DAYS)
        clean_a = [day for day in FUT_DAYS[30:] if day not in excluded]
        self.assertEqual(structure["evaluation_from"], clean_a[fvb.WINDOW_DAYS])

    def test_the_first_half_ends_on_its_last_day_and_the_odd_day_goes_to_h2(self):
        inputs = Market().add("A").inputs()
        lengths = set()
        for as_of in (FUT_DAYS[-1], FUT_DAYS[-2]):
            structure = nfs.signal_structure(as_of=as_of, **inputs)
            half_of, eval_days = structure["half_of"], structure["eval_days"]
            lengths.add(len(eval_days) % 2)
            first = [day for day in eval_days if half_of(day) == "H1"]
            self.assertEqual(first, eval_days[:len(eval_days) // 2])
            self.assertEqual(half_of(structure["halves"]["formation_to"]), "H1")
            self.assertEqual(half_of(structure["halves"]["evaluation_from"]), "H2")
        self.assertEqual(lengths, {0, 1})               # 奇偶兩種都測到

    def test_it_starts_at_the_first_day_the_rule_saw_unrefused(self):
        structure = Market().add("A").structure()
        excluded = sc.settlement_exclusion_set(
            date_from=FUT_DAYS[0], date_to=AS_OF, market_days=DAYS)
        clean = [day for day in FUT_DAYS if day not in excluded]
        self.assertEqual(structure["evaluation_from"], clean[fvb.WINDOW_DAYS])
        self.assertNotEqual(structure["evaluation_from"], FUT_DAYS[0])
        self.assertEqual(structure["evaluation_to"], AS_OF)


class PoolTests(unittest.TestCase):
    """§3.1 合格對照日的五條,逐條各一個反例。"""

    OK = "2026-07-01"
    S_TRUE = "2026-07-02"
    SIGNAL = "2026-07-06"
    FLAG_S_TRUE = "2026-07-08"
    R4 = "2026-07-13"
    IMMATERIAL = "2026-07-20"
    S_UNKNOWN = "2026-10-14"

    @classmethod
    def setUpClass(cls):
        market = Market().add("P", contracts=[("PAF", 2000), ("PBF", 1)])
        market.add("0050", type_="etf")
        market.add("Q")
        # R4 那天 P 是安靜的:若 R4 沒被跳過,它會是一個完美的對照日。
        market.spike("PAF", cls.SIGNAL, cls.FLAG_S_TRUE)
        market.spike("PBF", cls.IMMATERIAL)
        market.spike("0050F", "2026-07-07")
        market.spot[("P", cls.S_TRUE)] = 5_000_000
        market.spot[("P", cls.FLAG_S_TRUE)] = 6_000_000
        market.spot[("P", cls.S_UNKNOWN)] = None
        cls.structure = market.structure()
        cls.pool = set(cls.structure["pool_candidates"])
        cls.report = market.report(cls.structure)

    def test_an_ordinary_quiet_day_is_eligible(self):
        self.assertIn(("P", self.OK), self.pool)
        self.assertIn(("P", "2026-07-21"), self.pool)

    def test_s_true_is_not_eligible(self):
        self.assertNotIn(("P", self.S_TRUE), self.pool)

    def test_s_unknown_is_not_eligible(self):
        self.assertNotIn(("P", self.S_UNKNOWN), self.pool)
        self.assertIn(("P", "2026-10-13"), self.pool)

    def test_days_next_to_events_are_deliberately_kept(self):
        """§3.1:事件的下一天、以及同一天其他股票的日子,都**不**從池子排除。"""
        self.assertIn(("P", "2026-07-07"), self.pool)
        self.assertIn(("P", "2026-07-03"), self.pool)
        self.assertIn(("Q", self.SIGNAL), self.pool)
        self.assertIn(("Q", "2026-07-07"), self.pool)

    def test_a_signal_day_is_not_eligible_even_if_another_contract_is_quiet(self):
        self.assertIn(("P", self.SIGNAL), self.structure["events"])
        self.assertNotIn(("P", self.SIGNAL), self.pool)

    def test_a_flagged_day_is_not_eligible_whatever_s_is(self):
        self.assertNotIn(("P", self.FLAG_S_TRUE), self.structure["signal_days"])
        self.assertNotIn(("P", self.FLAG_S_TRUE), self.pool)

    def test_an_r4_day_is_neither_a_signal_nor_a_control(self):
        self.assertIn(self.R4, self.structure["excluded"])
        self.assertNotIn(("P", self.R4), self.pool)
        self.assertNotIn(("P", self.R4), self.structure["signal_days"])

    def test_an_r2b_immaterial_day_is_not_eligible(self):
        self.assertGreaterEqual(
            self.structure["counts"]["contract_refusals"]["R2b_immaterial"], 1)
        self.assertNotIn(("P", self.IMMATERIAL), self.pool)

    def test_etf_underlyings_enter_no_arm(self):
        self.assertFalse([key for key in self.pool if key[0] == "0050"])
        self.assertFalse([key for key in self.structure["signal_days"] if key[0] == "0050"])
        self.assertEqual(self.structure["counts"]["non_population_signal_days"], 1)
        self.assertEqual(self.report["companion"]["non_population_signal_days"], 1)

    def test_the_fifth_condition_needs_a_mature_entry_day(self):
        self.assertIn(("Q", AS_OF), self.pool)          # 候選(1–4 成立)
        self.assertEqual(self.report["refusals"]["pool"]["R1_no_entry_day"], 1)
        self.assertEqual(self.report["refusals"]["pool"]["R2_suspended"], 1)  # P 10-12 → e 10-14


class SpotFlagTests(unittest.TestCase):
    def test_a_flag_with_unknown_s_is_not_a_signal_day(self):
        market = Market().add("U")
        market.spike("UF", "2026-10-13")
        market.spot[("U", "2026-10-13")] = None
        structure = market.structure()
        self.assertEqual(structure["signal_days"], [])
        self.assertEqual(structure["events"], [])
        self.assertEqual(structure["counts"]["flagged_days_with_unknown_spot_flag"], 1)

    def test_a_flag_with_s_true_is_not_a_signal_day(self):
        market = Market().add("U")
        market.spike("UF", "2026-07-01")
        market.spot[("U", "2026-07-01")] = 5_000_000
        self.assertEqual(market.structure()["signal_days"], [])


class EntryDayCallSiteTests(unittest.TestCase):
    def test_e_follows_the_market_calendar_not_the_stocks_own_rows(self):
        """E 在 v 日沒有任何列:e 仍是 D 的第 2 天,不是該股自己的第 2 個列。"""
        market = Market().add("E")
        market.spike("EF", "2026-06-24")
        market.spot[("E", "2026-06-25")] = MISSING
        market.close("E", "2026-06-26", 104.0)   # D 的 e
        market.close("E", "2026-06-29", 100.0)   # 該股自己的第 2 個列
        report = market.report()
        self.assertEqual(report["sets"]["events"], 1)
        self.assertEqual(report["sets"]["hits"], 1)
        self.assertEqual(report["companion"]["signal"]["visible_unknown"], 1)

    def test_production_shape_the_last_futures_days_use_the_extra_spot_day(self):
        """期貨少一天:t = 期貨倒數第 2 天的 e 是只存在於 D 的那一天。"""
        market = Market().add("T")
        market.spike("TF", FUT_DAYS[-2], FUT_DAYS[-1])
        market.spike("TF", "2026-10-08")
        market.close("T", HORIZON, 104.0)
        report = market.report()
        self.assertEqual(report["refusals"]["events"]["R1_no_entry_day"], 0)
        # 10-14、10-15 是一段;10-08 另一段。10-14 的 e = 10-16(價格視界)。
        self.assertEqual(report["sets"]["events"], 2)
        self.assertEqual(report["sets"]["hits"], 1)
        self.assertEqual(report["facts"], None)  # 對照只有一檔,P_date 抽不到

    def test_an_event_on_as_of_is_immature(self):
        market = Market().add("T")
        market.spike("TF", AS_OF)
        report = market.report()
        self.assertEqual(report["refusals"]["events"]["R1_no_entry_day"], 1)
        self.assertEqual(report["sets"]["events"], 0)


# ── §3:裁決路徑 ──────────────────────────────────────────────────────────

class VerdictPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_structure = grid().structure()

    def run_grid(self, outcome_of, *, market=None, structure=None):
        market = market or grid()
        structure = structure or self.base_structure
        for key in scorable(structure):
            close = outcome_of(key, structure)
            if close is not None:
                set_outcome(market, key, close)
        return market.report(structure)

    def test_ship(self):
        report = self.run_grid(lambda key, s: 104.0)
        n = len(scorable(self.base_structure))
        self.assertGreater(n, 200)
        self.assertEqual(report["sets"]["events"], n)
        self.assertEqual(report["sets"]["hits"], n)
        self.assertEqual(report["sets"]["drops"], 0)
        self.assertEqual(len(report["tests"]["B"]["seeds"]), 20)
        self.assertEqual(len(report["tests"]["D"]["seeds"]), 20)
        self.assertEqual(len(report["tests"]["C"]["entries"]), 40)
        for entry in report["tests"]["B"]["seeds"]:
            self.assertEqual(entry["h_p"], 0)
        self.assertEqual(report["verdict"]["decision"], "SHIP")
        facts = report["facts"]
        self.assertEqual(tuple(facts), nfs.FACT_KEYS)
        self.assertEqual(facts["placebo_stock_hits"], {"min": 0, "max": 0})
        self.assertEqual(facts["placebo_date_drops"], {"min": 0, "max": 0})
        self.assertEqual(facts["events"], n)
        days = sorted(day for _, day in scorable(self.base_structure))
        self.assertEqual((facts["from"], facts["to"]), (days[0], days[-1]))
        self.assertEqual(report["metadata"]["preregistration_commit"], "e9212bd")
        self.assertEqual(report["companion"]["signal"]["visible_hits"], 0)

    def test_underpowered(self):
        hits = set(scorable(self.base_structure)[:10])
        report = self.run_grid(lambda key, s: 104.0 if key in hits else None)
        self.assertEqual(report["tests"]["A"]["outcome"], "UNDERPOWERED")
        self.assertEqual(report["verdict"]["reason"], "underpowered")

    def test_not_evaluable_lists_the_short_date(self):
        everyone = "2026-06-24"
        market = grid(everyone_on=everyone)
        structure = market.structure()
        report = self.run_grid(lambda key, s: 104.0, market=market, structure=structure)
        self.assertTrue(report["tests"]["A"]["passed"])
        self.assertEqual(report["verdict"]["reason"], "not_evaluable")
        # 20 檔都舉旗,但前一天舉旗的 4 檔是段落延續,不是事件:k = 16。
        self.assertEqual(report["sets"]["placebo_short"]["date"],
                         [{"date": everyone, "k": 16, "pool_size": 0}])
        self.assertEqual(report["sets"]["placebo_short"]["stock"], [])
        # 抽不滿的 seed 在每一個檢定裡都不可評估,不只 B。
        self.assertFalse(report["tests"]["D"]["evaluable"])
        self.assertFalse(report["tests"]["C"]["evaluable"])
        self.assertFalse([e for e in report["tests"]["C"]["entries"]
                          if e["placebo"] == "date" and e["evaluable"]])

    def test_informativeness_failed_when_every_day_hits(self):
        market = grid()
        for (stock_id, day) in list(market.price_rows()):
            market.close(stock_id, day, 104.0)
        report = market.report(self.base_structure)
        self.assertEqual(report["tests"]["B"]["outcome"], "FAIL")
        self.assertEqual(report["verdict"]["reason"], "informativeness_failed")

    def test_direction_failed_when_extra_hits_are_matched_by_extra_drops(self):
        """h − d = 1 > 0:草案的 ``h − drops > 0`` 會過,D(2σ_N,對照 0)不過。"""
        events = scorable(self.base_structure)
        closes = {key: (104.0 if index % 2 == 0 else 96.0) for index, key in enumerate(events)}
        if len(events) % 2 == 0:
            closes[events[-1]] = None
        report = self.run_grid(lambda key, s: closes[key])
        self.assertEqual(report["sets"]["hits"] - report["sets"]["drops"], 1)
        self.assertEqual(report["tests"]["B"]["outcome"], "PASS")
        self.assertEqual(report["tests"]["D"]["outcome"], "FAIL")
        self.assertEqual(report["verdict"]["reason"], "direction_failed")
        self.assertIn("波動", report["verdict"]["status_text"])

    def test_consistency_failed_when_one_half_has_no_hits(self):
        half_of = self.base_structure["half_of"]
        report = self.run_grid(lambda key, s: 104.0 if half_of(key[1]) == "H2" else None)
        self.assertEqual(report["sets"]["hits_by_half"]["H1"], 0)
        self.assertEqual(report["tests"]["B"]["outcome"], "PASS")
        self.assertEqual(report["tests"]["D"]["outcome"], "PASS")
        self.assertEqual(report["tests"]["C"]["outcome"], "FAIL")
        self.assertEqual(report["verdict"]["reason"], "consistency_failed")

    def test_b_and_d_read_the_same_draw(self):
        report = self.run_grid(lambda key, s: 104.0)
        for b, d, counts in zip(
            report["tests"]["B"]["seeds"], report["tests"]["D"]["seeds"],
            report["placebo_counts"]["stock"] + report["placebo_counts"]["date"],
        ):
            self.assertEqual((b["placebo"], b["seed"]), (d["placebo"], d["seed"]))
            self.assertEqual(b["h_p"], d["h_p"])
            self.assertEqual(counts["hits"], b["h_p"])
            self.assertEqual(counts["drops"], d["d_p"])


def _keep(key) -> bool:
    return after(key[1], 2) is not None


class ExactDrawTests(unittest.TestCase):
    """對照組的每一個 seed 都必須是**事前登記的那一次抽樣**:同股同半段、同日他股,
    seed 0..9,B 與 D 讀同一批。對照日的漲跌依一個與訊號無關的樣式散布,所以不同
    seed 抽到的漲跌數不同——換 seed、換池子、換半段、另抽一批都會被看見。"""

    @classmethod
    def setUpClass(cls):
        market = grid()
        for i in range(20):
            for x, day in enumerate(DAYS):
                residue = (7 * i + 3 * x) % 11
                if residue in (0, 1, 2):
                    market.close(f"S{i:02d}", day, 104.0)
                elif residue in (3, 4):
                    market.close(f"S{i:02d}", day, 96.0)
        cls.rows = market.price_rows()
        cls.structure = market.structure()
        cls.report = market.report(cls.structure)

    def outcome(self, key):
        close = self.rows[(key[0], after(key[1], 2))]["close"]
        return close >= 103, close <= 97

    def test_each_seed_is_the_preregistered_draw(self):
        half_of = self.structure["half_of"]
        events = [key for key in self.structure["events"] if _keep(key)]
        pools = {"stock": {}, "date": {}}
        for key in self.structure["pool_candidates"]:
            if _keep(key):
                pools["stock"].setdefault((key[0], half_of(key[1])), []).append(key)
                pools["date"].setdefault(key[1], []).append(key)
        counts = {"stock": {}, "date": {}}
        for stock_id, day in events:
            for placebo, key in (("stock", (stock_id, half_of(day))), ("date", day)):
                counts[placebo][key] = counts[placebo].get(key, 0) + 1

        b_seeds = {(e["placebo"], e["seed"]): e for e in self.report["tests"]["B"]["seeds"]}
        d_seeds = {(e["placebo"], e["seed"]): e for e in self.report["tests"]["D"]["seeds"]}
        c_entries = {(e["placebo"], e["seed"], e["half"]): e
                     for e in self.report["tests"]["C"]["entries"]}
        for placebo in ("stock", "date"):
            seen = set()
            for seed in range(10):
                drawn = nds.draw_matched(pools=pools[placebo], counts=counts[placebo],
                                         seed=seed)["drawn"]
                hits = sum(self.outcome(key)[0] for key in drawn)
                drops = sum(self.outcome(key)[1] for key in drawn)
                seen.add((hits, drops))
                self.assertEqual(b_seeds[(placebo, seed)]["h_p"], hits, (placebo, seed))
                self.assertEqual(b_seeds[(placebo, seed)]["n"], len(events))
                self.assertEqual(d_seeds[(placebo, seed)]["h_p"], hits)
                self.assertEqual(d_seeds[(placebo, seed)]["d_p"], drops, (placebo, seed))
                self.assertEqual(d_seeds[(placebo, seed)]["n"], len(events))
                for half in ("H1", "H2"):
                    self.assertEqual(
                        c_entries[(placebo, seed, half)]["h_p"],
                        sum(self.outcome(key)[0] for key in drawn if half_of(key[1]) == half),
                    )
            self.assertGreater(len(seen), 3, placebo)    # 抽樣真的隨 seed 變

    def test_n_is_the_count_after_refusals(self):
        self.assertGreater(len(self.structure["events"]), self.report["sets"]["events"])
        self.assertGreater(self.report["refusals"]["events"]["R1_no_entry_day"], 0)


class HalfAsymmetryTests(unittest.TestCase):
    """前半的每一個日子 e 日都漲、後半只有事件漲:同股對照必須從**同一半**抽。"""

    @classmethod
    def setUpClass(cls):
        market = grid()
        structure = market.structure()
        h1_last = structure["halves"]["formation_to"]
        hit_days = {after(day, 2) for day in DAYS if day <= h1_last and after(day, 2)}
        for i in range(20):
            for day in hit_days:
                market.close(f"S{i:02d}", day, 104.0)
        for key in scorable(structure):
            set_outcome(market, key, 104.0)
        cls.structure = structure
        cls.report = market.report(structure)

    def test_placebos_are_matched_within_the_half(self):
        report = self.report
        first, second = report["sets"]["events_by_half"]["H1"], report["sets"]["events_by_half"]["H2"]
        self.assertNotEqual(first, second)
        for entry in report["tests"]["B"]["seeds"]:
            self.assertEqual(entry["h_p"], first, entry)
        for entry in report["tests"]["C"]["entries"]:
            self.assertEqual(entry["h_p"], first if entry["half"] == "H1" else 0, entry)
            self.assertEqual(entry["h"], first if entry["half"] == "H1" else second)

    def test_the_first_half_has_no_edge_so_c_fails(self):
        self.assertEqual(self.report["tests"]["B"]["outcome"], "PASS")
        self.assertEqual(self.report["tests"]["D"]["outcome"], "PASS")
        self.assertEqual(self.report["tests"]["C"]["outcome"], "FAIL")
        self.assertEqual(self.report["verdict"]["reason"], "consistency_failed")


class TestFormulaTests(unittest.TestCase):
    def test_a_boundary_is_inclusive_on_both_counts(self):
        self.assertTrue(nfs.power_verdict(n=30, h=30)["passed"])
        self.assertFalse(nfs.power_verdict(n=30, h=29)["passed"])
        self.assertFalse(nfs.power_verdict(n=29, h=30)["passed"])
        self.assertFalse(nfs.power_verdict(n=1000, h=29)["passed"])

    def test_not_evaluable_cites_the_test_that_could_not_be_scored(self):
        ok = {"passed": True, "evaluable": True, "line": "ok"}
        a = {"passed": True, "line": "a"}
        for name in ("b", "d", "c"):
            tests = {"b": ok, "d": ok, "c": ok,
                     name: {"passed": False, "evaluable": False, "line": f"{name}-line"}}
            verdict = nfs.overall_verdict(test_a=a, test_b=tests["b"], test_d=tests["d"],
                                          test_c=tests["c"])
            self.assertEqual(verdict["reason"], "not_evaluable")
            self.assertIn(f"{name}-line", verdict["line"])

    def test_choices_record_every_ambiguity(self):
        choices = nfs._choices()
        self.assertEqual(len(choices), 8)
        text = json.dumps(choices)
        for needle in ("settlement_is_determinable", "--price-horizon", "bit-exactly",
                       "type='stock'", "authorizer", "visible_unknown",
                       "two_contract_signal_days", "fully drawn", "signal_facts"):
            self.assertIn(needle, text)

    def test_imports_are_the_live_symbols(self):
        self.assertIs(nfs.LOW_SAMPLE_SURVIVORS, bwd.LOW_SAMPLE_SURVIVORS)
        self.assertIs(nfs.PLACEBO_SEEDS, fvb.PLACEBO_SEEDS)
        self.assertIs(nfs.PLACEBO_SIGMA_MULTIPLE, fvb.PLACEBO_SIGMA_MULTIPLE)
        self.assertIs(nfs.seed_result, fvb.seed_result)
        self.assertIs(nfs.evaluate_contract_day_in_calendar, fvb.evaluate_contract_day_in_calendar)
        self.assertIs(nfs.spot_new_high, fvb.spot_new_high)
        self.assertIs(nfs.settlement_exclusion_set, sc.settlement_exclusion_set)
        self.assertIs(nfs.draw_matched, nds.draw_matched)
        self.assertIs(nfs._dec, nds._dec)

    def test_no_restated_numbers_and_no_stored_entry_column(self):
        source = (PIPELINE / "radar" / "compute" / "next_day_futures_signal_battery.py"
                  ).read_text(encoding="utf-8")
        code = "\n".join(line for line in source.splitlines()
                         if line.strip() and not line.strip().startswith("#")
                         and "``" not in line)
        self.assertIsNone(re.search(r"^\s*\w+\s*=\s*30\b|[<>]=?\s*30\b", code, re.M))
        self.assertIsNone(re.search(r"range\(10\)|\b2\.0\b|\b1\.095\b", code))
        self.assertNotIn("entry_date", source)
        self.assertNotIn("daily_scores", source)

    def test_sigma_n_formula(self):
        entry = nfs.direction_result(seed=0, n=100, h=40, d=10, h_p=20, d_p=10, matched=True)
        self.assertAlmostEqual(entry["sigma_n"], round((30 - 100 / 100) ** 0.5, 6))
        self.assertTrue(entry["passed"])
        # σ_N 的下限 1:對照 0 漲 0 跌時,h − d 要 ≥ 2。
        self.assertTrue(nfs.direction_result(seed=0, n=50, h=2, d=0, h_p=0, d_p=0,
                                             matched=True)["passed"])
        self.assertFalse(nfs.direction_result(seed=0, n=50, h=1, d=0, h_p=0, d_p=0,
                                              matched=True)["passed"])
        # 草案的 h − d > 0 在這裡會過:訊號跟自己比,量到的是行情。
        self.assertFalse(nfs.direction_result(seed=0, n=100, h=40, d=0, h_p=40, d_p=0,
                                              matched=True)["passed"])
        self.assertFalse(nfs.direction_result(seed=0, n=100, h=40, d=0, h_p=0, d_p=0,
                                              matched=False)["evaluable"])

    def test_one_failing_criterion_of_twenty_fails_b_and_d(self):
        good = {"evaluable": True, "passed": True}
        seeds = [{"placebo": p, "seed": s, **good} for p in ("stock", "date") for s in range(10)]
        self.assertEqual(nfs.informativeness_verdict(seeds=seeds)["outcome"], "PASS")
        self.assertEqual(nfs.direction_verdict(seeds=seeds)["outcome"], "PASS")
        for index in (0, 9, 10, 19):
            broken = list(seeds)
            broken[index] = {**broken[index], "passed": False}
            self.assertEqual(nfs.informativeness_verdict(seeds=broken)["outcome"], "FAIL")
            self.assertEqual(nfs.direction_verdict(seeds=broken)["outcome"], "FAIL")
        only_one = [{**entry, "passed": index == 0} for index, entry in enumerate(seeds)]
        self.assertFalse(nfs.informativeness_verdict(seeds=only_one)["passed"])
        self.assertFalse(nfs.direction_verdict(seeds=only_one)["passed"])

    def test_one_failing_seed_reaches_the_overall_verdict(self):
        """19 個 seed 過、1 個不過:整體裁決仍是不過,不論哪一層去讀 seed。"""
        good = {"evaluable": True, "passed": True}
        seeds = [{"placebo": p, "seed": s, **good} for p in ("stock", "date") for s in range(10)]
        broken = seeds[:-1] + [{**seeds[-1], "passed": False}]
        a = nfs.power_verdict(n=100, h=50)
        c = nfs.consistency_verdict(entries=[{"placebo": "stock", "seed": 0, "half": "H1",
                                              "evaluable": True, "passed": True}])
        self.assertEqual(nfs.overall_verdict(
            test_a=a, test_b=nfs.informativeness_verdict(seeds=broken),
            test_d=nfs.direction_verdict(seeds=seeds), test_c=c)["reason"],
            "informativeness_failed")
        self.assertEqual(nfs.overall_verdict(
            test_a=a, test_b=nfs.informativeness_verdict(seeds=seeds),
            test_d=nfs.direction_verdict(seeds=broken), test_c=c)["reason"],
            "direction_failed")

    def test_verdict_order(self):
        ok = {"passed": True, "evaluable": True, "line": "x"}
        bad = {"passed": False, "evaluable": True, "line": "x"}
        blank = {"passed": False, "evaluable": False, "line": "x"}
        a_no = {"passed": False, "line": "a"}

        def reason(a=ok, b=ok, d=ok, c=ok):
            return nfs.overall_verdict(test_a=a, test_b=b, test_d=d, test_c=c)["reason"]

        self.assertEqual(reason(a=a_no, b=blank, d=bad, c=bad), "underpowered")
        self.assertEqual(reason(b=blank, d=bad), "not_evaluable")
        self.assertEqual(reason(d=blank), "not_evaluable")
        self.assertEqual(reason(b=bad, d=bad, c=bad), "informativeness_failed")
        self.assertEqual(reason(d=bad, c=bad), "direction_failed")
        self.assertEqual(reason(c=bad), "consistency_failed")
        self.assertEqual(nfs.overall_verdict(test_a=ok, test_b=ok, test_d=ok, test_c=ok)
                         ["decision"], "SHIP")


class AsOfTests(unittest.TestCase):
    def test_as_of_is_the_min_of_both_imports_and_cannot_be_chosen(self):
        self.assertEqual(nfs.check_as_of(as_of=AS_OF, max_futures_date=AS_OF,
                                         max_price_date=HORIZON, historical=False), HORIZON)
        with self.assertRaisesRegex(ValueError, "after the last day"):
            nfs.check_as_of(as_of=HORIZON, max_futures_date=AS_OF,
                            max_price_date=HORIZON, historical=False)
        with self.assertRaisesRegex(ValueError, "not min"):
            nfs.check_as_of(as_of=FUT_DAYS[-2], max_futures_date=AS_OF,
                            max_price_date=HORIZON, historical=False)
        # 期貨反而領先(當日匯入之後可能):as_of 是現貨的最後一天。
        self.assertEqual(nfs.check_as_of(as_of=AS_OF, max_futures_date=HORIZON,
                                         max_price_date=AS_OF, historical=False), AS_OF)
        # --historical:只能更早,價格視界保守地取 as_of。
        self.assertEqual(nfs.check_as_of(as_of=FUT_DAYS[-2], max_futures_date=AS_OF,
                                         max_price_date=HORIZON, historical=True),
                         FUT_DAYS[-2])
        with self.assertRaisesRegex(ValueError, "after the last day"):
            nfs.check_as_of(as_of=HORIZON, max_futures_date=AS_OF,
                            max_price_date=HORIZON, historical=True)

    def test_price_horizon_only_with_historical_and_within_range(self):
        self.assertEqual(nfs.check_as_of(as_of=FUT_DAYS[-2], max_futures_date=AS_OF,
                                         max_price_date=HORIZON, historical=True,
                                         price_horizon=AS_OF), AS_OF)
        with self.assertRaisesRegex(ValueError, "only allowed with --historical"):
            nfs.check_as_of(as_of=AS_OF, max_futures_date=AS_OF, max_price_date=HORIZON,
                            historical=False, price_horizon=HORIZON)
        for bad in (FUT_DAYS[-3], "2026-10-19"):
            with self.assertRaisesRegex(ValueError, "must lie in"):
                nfs.check_as_of(as_of=FUT_DAYS[-2], max_futures_date=AS_OF,
                                max_price_date=HORIZON, historical=True, price_horizon=bad)


class FactsShapeTests(unittest.TestCase):
    FACTS = nfs.signal_facts(
        date_from="2026-06-01", date_to="2026-10-14", events=400, hits=60, drops=40,
        placebo_stock_hits=[30, 41], placebo_stock_drops=[20, 33],
        placebo_date_hits=[28, 35], placebo_date_drops=[25, 31],
    )

    def test_exactly_the_section_1_keys_and_only_integers(self):
        self.assertEqual(tuple(self.FACTS), nfs.FACT_KEYS)
        self.assertEqual(self.FACTS["placebo_stock_drops"], {"min": 20, "max": 33})
        self.assertEqual(self.FACTS["threshold_pct"], 3)
        forbidden = set(RATIO_ISH + RANK_ISH) | {"rate", "prob", "probability", "percent",
                                                  "share", "win", "surge"}
        for key, value in self.FACTS.items():
            self.assertFalse(set(key.split("_")) & forbidden, key)
            for inner in (value.values() if isinstance(value, dict) else [value]):
                self.assertNotIsInstance(inner, (bool, float))

    def test_no_events_or_no_placebo_means_no_claim(self):
        self.assertIsNone(nfs.signal_facts(
            date_from=None, date_to=None, events=0, hits=0, drops=0,
            placebo_stock_hits=[1], placebo_stock_drops=[1],
            placebo_date_hits=[1], placebo_date_drops=[1]))


# ── 端到端:暫存資料庫 ────────────────────────────────────────────────────

class _FixtureDB(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.old_url, self.old_dir = config.DB_URL, config.DATA_DIR
        self.db_path = self.tmp_path / "futures-signal-battery.db"
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

    def write(self, market: Market):
        rows = market.price_rows()
        with db.get_engine().begin() as conn:
            conn.exec_driver_sql("DELETE FROM stocks")
            for stock_id, type_ in market.types.items():
                conn.exec_driver_sql(
                    "INSERT INTO stocks (id, name, market, type, is_active) "
                    "VALUES (?, ?, 'twse', ?, 1)", (stock_id, stock_id, type_))
            conn.exec_driver_sql(
                "INSERT INTO daily_prices (stock_id, date, open, close, volume) "
                "VALUES (?, ?, ?, ?, ?)",
                [(s, d, r["open"], r["close"], r["volume"]) for (s, d), r in rows.items()],
            )
            # daily_scores 的 entry_date 是 t+1:battery 若讀它當 e,結果就會錯。
            conn.exec_driver_sql(
                "INSERT INTO daily_scores (stock_id, date, final, entry_date) "
                "VALUES (?, ?, 50, ?)",
                [(s, d, after(d, 1)) for (s, d) in rows],
            )
            for contract in market.contracts:
                conn.exec_driver_sql(
                    "INSERT INTO futures_contracts (contract_code, stock_id, "
                    "contract_multiplier, first_seen, last_seen) VALUES (?, ?, ?, ?, ?)",
                    (contract["contract_code"], contract["stock_id"],
                     contract["contract_multiplier"], FUT_DAYS[0], AS_OF))
                volumes = market.futures_volumes(contract["contract_code"])
                conn.exec_driver_sql(
                    "INSERT INTO futures_daily (contract_code, date, contract_month, "
                    "session, volume, open_interest) VALUES (?, ?, '202612', '一般', ?, 1000)",
                    [(contract["contract_code"], day, volume) for day, volume in volumes.items()],
                )
                # 盤後列:R3 在查詢層就不讀;量大到會舉旗,若被讀進來結果就會變。
                conn.exec_driver_sql(
                    "INSERT INTO futures_daily (contract_code, date, contract_month, "
                    "session, volume, open_interest) VALUES (?, ?, '202612', '盤後', ?, 1)",
                    [(contract["contract_code"], day, 999_999) for day in FUT_DAYS[::7]],
                )
        db._engine.dispose()
        db._engine = None

    def ship_market(self) -> Market:
        market = grid()
        market.add("0050", type_="etf")
        market.spike("0050F", *FUT_DAYS[100::9])
        for key in scorable(market.structure()):
            set_outcome(market, key, 104.0)
        return market


class EndToEndTests(_FixtureDB):
    def test_the_database_path_matches_the_in_memory_assembly(self):
        market = self.ship_market()
        self.write(market)
        report = nfs.build_next_day_futures_signal_battery(as_of=AS_OF)
        expected = market.report()
        self.assertEqual(report["verdict"]["decision"], "SHIP")
        for key in ("events", "hits", "drops", "events_by_half"):
            self.assertEqual(report["sets"][key], expected["sets"][key])
        self.assertEqual(report["metadata"]["price_horizon"], HORIZON)
        self.assertGreater(report["companion"]["non_population_signal_days"], 0)
        self.assertEqual(report["metadata"]["x_from"], "2026-09-18")

    def test_as_of_is_enforced_against_the_database(self):
        self.write(self.ship_market())
        with self.assertRaisesRegex(ValueError, "after the last day"):
            nfs.build_next_day_futures_signal_battery(as_of=HORIZON)
        with self.assertRaisesRegex(ValueError, "not min"):
            nfs.build_next_day_futures_signal_battery(as_of=FUT_DAYS[-3])
        report = nfs.build_next_day_futures_signal_battery(as_of=FUT_DAYS[-3],
                                                           historical=True)
        self.assertTrue(report["metadata"]["historical_as_of"])
        self.assertEqual(report["metadata"]["price_horizon"], FUT_DAYS[-3])
        widened = nfs.build_next_day_futures_signal_battery(
            as_of=FUT_DAYS[-3], historical=True, price_horizon=FUT_DAYS[-2])
        self.assertEqual(widened["metadata"]["price_horizon"], FUT_DAYS[-2])
        self.assertLess(widened["refusals"]["events"]["R1_no_entry_day"],
                        report["refusals"]["events"]["R1_no_entry_day"])
        with self.assertRaisesRegex(ValueError, "only allowed with --historical"):
            nfs.build_coverage(as_of=AS_OF, price_horizon=HORIZON)

    def test_the_battery_writes_nothing(self):
        self.write(self.ship_market())
        before = hashlib.sha256(self.db_path.read_bytes()).hexdigest()
        out = self.tmp_path / "battery.json"
        report = nfs.write_next_day_futures_signal_battery(as_of=AS_OF, out=out)
        nfs.build_coverage(as_of=AS_OF)
        self.assertEqual(hashlib.sha256(self.db_path.read_bytes()).hexdigest(), before)
        self.assertTrue(report["metadata"]["read_only"])
        written = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(written["verdict"], report["verdict"])
        with self.assertRaisesRegex(ValueError, "must not be"):
            nfs.write_next_day_futures_signal_battery(as_of=AS_OF, out=str(self.db_path))

    def test_the_output_is_deterministic(self):
        self.write(self.ship_market())
        first, second = self.tmp_path / "a.json", self.tmp_path / "b.json"
        nfs.write_next_day_futures_signal_battery(as_of=AS_OF, out=first)
        nfs.write_next_day_futures_signal_battery(as_of=AS_OF, out=second)
        self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_cli(self):
        self.write(self.ship_market())
        out = self.tmp_path / "cli.json"
        with redirect_stdout(io.StringIO()) as printed:
            main(["next-day-futures-signal-battery", "--as-of", AS_OF, "--run-number", "2",
                  "--out", str(out)])
        written = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(written["metadata"]["run_number"], 2)
        self.assertEqual(written["verdict"]["decision"], "SHIP")
        self.assertIn("[SHIP]", printed.getvalue())


class CoverageOnlyTests(_FixtureDB):
    def test_coverage_never_touches_an_outcome_price(self):
        market = self.ship_market()
        self.write(market)
        full = nfs.build_next_day_futures_signal_battery(as_of=AS_OF)
        with mock.patch.object(nfs, "load_outcome_bars",
                               side_effect=AssertionError("outcome prices read")), \
             mock.patch.object(nfs, "assess",
                               side_effect=AssertionError("outcome assessed")):
            coverage = nfs.build_coverage(as_of=AS_OF)
            # 同一個補丁下,完整 battery 會碰到結果價格:補丁是有牙齒的。
            with self.assertRaises(AssertionError):
                nfs.build_next_day_futures_signal_battery(as_of=AS_OF)
        self.assertEqual(coverage["evaluation_from"], full["coverage"]["evaluation_from"])
        self.assertEqual(coverage["evaluation_to"], AS_OF)
        self.assertEqual(coverage["signal_days"], full["coverage"]["signal_days"])
        self.assertEqual(coverage["events_before_outcome_refusals"],
                         full["coverage"]["events_before_outcome_refusals"])
        self.assertEqual(coverage["events_before_outcome_refusals"],
                         len(market.structure()["events"]))

    def test_the_coverage_connection_cannot_read_price_columns(self):
        self.write(self.ship_market())
        connection = sqlite3.connect(self.db_path.as_uri() + "?mode=ro", uri=True)
        try:
            nfs.seal_outcome_columns(connection)
            self.assertTrue(connection.execute(
                "SELECT stock_id, date, volume FROM daily_prices LIMIT 1").fetchone())
            for column in ("open", "close", "high", "low", "adj_factor", "turnover", "*"):
                with self.assertRaises(sqlite3.DatabaseError):
                    connection.execute(f"SELECT {column} FROM daily_prices LIMIT 1")
            # 期貨:量、未平倉與鍵可讀;任何價格與結算價不可讀。
            connection.execute(
                "SELECT contract_code, date, contract_month, session, volume, open_interest "
                "FROM futures_daily LIMIT 1").fetchall()
            for column in ("open", "high", "low", "last", "change", "settlement_price", "*"):
                with self.assertRaises(sqlite3.DatabaseError, msg=column):
                    connection.execute(f"SELECT {column} FROM futures_daily LIMIT 1")
            connection.execute(
                "SELECT contract_code, stock_id, contract_multiplier FROM futures_contracts"
            ).fetchall()
            connection.execute("SELECT id, type FROM stocks").fetchall()
            # 沒有列在白名單上的表與欄位:往後報酬、指標、其餘一切。
            for sql in ("SELECT fwd_1d FROM daily_scores", "SELECT stock_id FROM daily_scores",
                        "SELECT * FROM indicators_daily", "SELECT name FROM stocks",
                        "SELECT stock_name FROM futures_contracts"):
                with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                    connection.execute(sql)
        finally:
            connection.close()

    def test_the_coverage_run_installs_the_seal(self):
        """一個偷讀 open 的載入器,在 coverage 連線上必須被 SQLite 擋下。"""
        from sqlalchemy import text as sql_text
        from sqlalchemy.exc import DatabaseError
        self.write(self.ship_market())
        real = nfs.load_stock_types

        def snooping(conn):
            conn.execute(sql_text("SELECT open FROM daily_prices LIMIT 1")).fetchall()
            return real(conn)

        with mock.patch.object(nfs, "load_stock_types", side_effect=snooping):
            with self.assertRaises(DatabaseError):
                nfs.build_coverage(as_of=AS_OF)
            # 完整 battery 的連線沒有封印,同一個載入器照常跑完。
            nfs.build_next_day_futures_signal_battery(as_of=AS_OF)

    def test_coverage_enforces_as_of_and_the_cli_prints_it(self):
        self.write(self.ship_market())
        with self.assertRaisesRegex(ValueError, "not min"):
            nfs.build_coverage(as_of=FUT_DAYS[-3])
        with mock.patch.object(nfs, "load_outcome_bars",
                               side_effect=AssertionError("outcome prices read")), \
             redirect_stdout(io.StringIO()) as printed:
            main(["next-day-futures-signal-battery", "--as-of", AS_OF, "--coverage-only"])
        self.assertIn("--coverage-only", printed.getvalue())
        self.assertIn("signal_days=", printed.getvalue())


if __name__ == "__main__":
    unittest.main()
