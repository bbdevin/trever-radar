"""「隔天大漲」次數 battery(docs/39,事前登記 `f8a57b5`)。

fixture 的每一個數字都是**發明的**,而且是為了能手算而發明的:40 檔股票、20 個
市場交易日,股票 i 在第 d 天上榜若且唯若 ``(d + i) % 3 == 0``。於是每一個上榜日都是
一段的首日(前一天必然不在榜上),事件數可以直接數出來:

- d ≡ 0 (mod 3) 的 7 天(0..18)各 14 檔、d ≡ 1 的 6 天(1..16)各 13 檔、
  d ≡ 2 的 6 天各 13 檔 → **254** 個成熟事件;
- 第 19 天(最後一個市場日)的 13 個事件沒有進場日 → R1。

價格:開盤恆為 100;第 d 天收盤 110 若且唯若該股**第 d − 1 天在榜上**,否則 100。
所以上榜臂每一個事件都命中,而任何不在榜上的日子的次日都是上榜日、收盤 100、
不命中——``h_P = 0`` 是**構造出來的**,不是跑出來之後抄回來的。這支測試沒有一個
數字來自真實資料:事前登記要求前置實作在看到資料之前就能被驗證。
"""
import hashlib
import json
import re
import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import radar.config as config
import radar.db as db
from radar.cli import main
from radar.compute import branch_window_direction_battery as bwd
from radar.compute import futures_volume_battery as fvb
from radar.compute import next_day_surge_battery as nds
from radar.compute.next_day_surge_battery import (
    FACT_KEYS,
    LEG,
    LIST_CAP,
    LIST_MIN_FINAL,
    SURGE_THRESHOLD_PCT,
    assess,
    build_next_day_surge_battery,
    draw_matched,
    event_first_days,
    is_surge,
    overall_verdict,
    power_verdict,
    published_list,
    surge_facts,
    write_next_day_surge_battery,
)

# 與 test_futures_export 同一份詞彙。這裡另外逐詞比對,理由見 SurgeFactsShapeTests。
from tests.test_futures_export import RANK_ISH, RATIO_ISH

PIPELINE = Path(__file__).resolve().parents[1]


def _weekdays(start: date, count: int) -> list[str]:
    days: list[str] = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current.isoformat())
        current += timedelta(days=1)
    return days


_DAYS = _weekdays(date(2026, 3, 2), 20)
_STOCKS = [f"9{index:03d}" for index in range(40)]
_EVENTS_MATURE = 7 * 14 + 6 * 13 + 6 * 13          # 254
_EVENTS_LAST_DAY = 13                              # d = 19 ≡ 1 → i ≡ 2 → 13 檔


def _on_list(stock_index: int, day_index: int) -> bool:
    return (day_index + stock_index) % 3 == 0


def _row(stock_id, final=80, branch=50, turnover=1_000_000_000):
    return {"stock_id": stock_id, "final": final, "branch_score": branch,
            "turnover": turnover}


# ── §0:命中 ───────────────────────────────────────────────────────────────

class SurgeRuleTests(unittest.TestCase):
    def test_exactly_seven_percent_is_a_hit(self):
        self.assertTrue(is_surge(open_price=100.0, close_price=107.0))
        self.assertFalse(is_surge(open_price=100.0, close_price=106.99))

    def test_the_comparison_is_decimal_not_float(self):
        # 12.35 × 1.07 = 13.2145:恰好在門檻上的那一天,不能交給浮點運氣。
        self.assertTrue(is_surge(open_price=12.35, close_price=13.2145))
        self.assertFalse(is_surge(open_price=12.35, close_price=13.2144))
        self.assertTrue(is_surge(open_price=1.15, close_price=1.2305))

    def test_the_threshold_is_the_borrowed_seven(self):
        self.assertEqual(SURGE_THRESHOLD_PCT, 7)
        self.assertEqual(LEG, "entry_open_to_close")


# ── §0:上榜 ───────────────────────────────────────────────────────────────

class PublishedListTests(unittest.TestCase):
    def test_below_65_is_never_listed(self):
        result = published_list([_row("A", final=64), _row("B", final=65)])
        self.assertEqual(result["stock_ids"], {"B"})

    def test_the_cap_is_40_and_the_rest_are_counted(self):
        rows = [_row(f"S{i:02d}", final=90, turnover=10**9 - i) for i in range(42)]
        result = published_list(rows)
        self.assertEqual(len(result["stock_ids"]), LIST_CAP)
        self.assertNotIn("S40", result["stock_ids"])
        self.assertEqual(result["over_cap"], 2)
        self.assertEqual(result["tie_at_cap"], 0)

    def test_full_ties_at_the_cap_are_all_included(self):
        rows = [_row(f"S{i:02d}", final=90, turnover=10**10 + i) for i in range(39)]
        rows += [_row("TIE1", final=65), _row("TIE2", final=65),
                 _row("LOW", final=65, turnover=1)]
        result = published_list(rows)
        self.assertIn("TIE1", result["stock_ids"])
        self.assertIn("TIE2", result["stock_ids"])
        self.assertNotIn("LOW", result["stock_ids"])
        self.assertEqual(result["tie_at_cap"], 1)
        self.assertEqual(result["over_cap"], 1)

    def test_missing_branch_sorts_below_any_branch(self):
        rows = [_row(f"S{i:02d}", final=90) for i in range(39)]
        rows += [_row("NOBRANCH", final=70, branch=None), _row("ZERO", final=70, branch=0)]
        result = published_list(rows)
        self.assertIn("ZERO", result["stock_ids"])
        self.assertNotIn("NOBRANCH", result["stock_ids"])

    def test_the_numbers_are_the_ones_export_uses(self):
        """絆線:export 的綜合榜改了 65 或 40,這裡要紅,而不是靜靜量另一張榜。"""
        source = (PIPELINE / "radar" / "export" / "json_export.py").read_text(encoding="utf-8")
        self.assertIn(f"SCORE_LIST_MIN_FINAL = {LIST_MIN_FINAL}\n", source)
        self.assertIn('score = [s for s in score_all if s["scores"]["final"] '
                      '>= SCORE_LIST_MIN_FINAL]', source)
        self.assertIn(f"score = score[:{LIST_CAP}]", source)
        self.assertIn('s["scores"]["branch"] if s["scores"]["branch"] is not None '
                      'else float("-inf")', source)


class ListDefinitionDriftTests(unittest.TestCase):
    def test_v1_deliberately_reconstructs_the_pre_gate_list(self):
        """export 在 2026-09-24 加了資料齊全閘門(``score_list_gate``),扣留的日子
        發佈的榜是空的;v1 battery **刻意不套用它**。

        docs/39 §0 的上榜定義在閘門出現之前就凍結了(f8a57b5),第 1 次執行也是依它
        跑的;把閘門接進 v1 等於事後改 v1 的規則。§3.8 規定上榜規則一改,計數就從
        改變日重新起算、依 v2 規則重新取得資格——所以任何 v2 的上榜定義必須**含**
        這道閘門。這條測試存在,是為了讓這個分歧寫在明處:上面那條絆線只比對排序
        與門檻,單靠它會讓人以為 battery 與 export 仍然是同一張榜(驗證者抓到)。
        """
        export = (PIPELINE / "radar" / "export" / "json_export.py").read_text(encoding="utf-8")
        battery = (PIPELINE / "radar" / "compute" / "next_day_surge_battery.py").read_text(
            encoding="utf-8")
        self.assertIn("score_list_gate(", export)
        self.assertNotIn("score_list_gate", battery)


class EventTests(unittest.TestCase):
    def test_a_run_counts_once_at_its_first_day(self):
        days = ["d1", "d2", "d3", "d4", "d5"]
        on_list = {"d1": {"A"}, "d2": {"A", "B"}, "d3": {"B"}, "d4": set(), "d5": {"A", "B"}}
        self.assertEqual(
            event_first_days(on_list=on_list, days=days),
            [("A", "d1"), ("B", "d2"), ("A", "d5"), ("B", "d5")],
        )

    def test_a_day_missing_from_the_scores_breaks_the_run(self):
        days = ["d1", "d2", "d3"]
        on_list = {"d1": {"A"}, "d3": {"A"}}
        self.assertEqual(event_first_days(on_list=on_list, days=days),
                         [("A", "d1"), ("A", "d3")])


# ── §2:否決 ───────────────────────────────────────────────────────────────

class AssessTests(unittest.TestCase):
    BAR = {"open": 100.0, "close": 108.0, "adj_factor": 1.0}
    SIGNAL = {"open": 90.0, "close": 100.0, "adj_factor": 1.0}

    def _score(self, **overrides):
        return {"entry_date": "E", "fwd_1d": 8.0, **overrides}

    def test_a_clean_row_is_scored_from_raw_prices(self):
        outcome = assess(score=self._score(), entry_day="E",
                         entry_bar=self.BAR, signal_bar=self.SIGNAL)
        self.assertIsNone(outcome["refusal"])
        self.assertTrue(outcome["hit"])
        self.assertTrue(outcome["board_hit"])
        self.assertFalse(outcome["limit_open"])

    def test_r1_codes(self):
        self.assertEqual(assess(score=self._score(), entry_day=None, entry_bar=None,
                                signal_bar=None)["refusal"], "R1_no_entry_day")
        self.assertEqual(assess(score=self._score(), entry_day="E", entry_bar=None,
                                signal_bar=None)["refusal"], "R1_no_entry_row")
        for bad_open in (None, 0.0, -1.0):
            self.assertEqual(assess(score=self._score(), entry_day="E",
                                    entry_bar={**self.BAR, "open": bad_open},
                                    signal_bar=None)["refusal"], "R1_bad_open")
        self.assertEqual(assess(score=self._score(), entry_day="E",
                                entry_bar={**self.BAR, "close": None},
                                signal_bar=None)["refusal"], "R1_no_close")

    def test_a_shifted_entry_is_refused_not_rescored(self):
        """缺了 t+1 時 forward_returns 會往後找,儲存的 fwd_1d 講的是 t+2。"""
        outcome = assess(score=self._score(entry_date="LATER"), entry_day="E",
                         entry_bar=self.BAR, signal_bar=None)
        self.assertEqual(outcome["refusal"], "R2_entry_shifted")

    def test_a_stored_return_off_by_more_than_rounding_is_refused(self):
        ok = assess(score=self._score(fwd_1d=8.01), entry_day="E",
                    entry_bar=self.BAR, signal_bar=None)
        self.assertIsNone(ok["refusal"])
        bad = assess(score=self._score(fwd_1d=8.02), entry_day="E",
                     entry_bar=self.BAR, signal_bar=None)
        self.assertEqual(bad["refusal"], "R2_fwd_mismatch")
        # 恰好差 0.01 仍在容差內(嚴格大於才否決):重算值是精確的 0.0。
        flat = {"open": 100.0, "close": 100.0, "adj_factor": 1.0}
        edge = assess(score=self._score(fwd_1d=0.01), entry_day="E",
                      entry_bar=flat, signal_bar=None)
        self.assertIsNone(edge["refusal"])
        missing = assess(score=self._score(fwd_1d=None), entry_day="E",
                         entry_bar=self.BAR, signal_bar=None)
        self.assertEqual(missing["refusal"], "R2_fwd_mismatch")

    def test_a_locked_limit_up_open_is_a_structural_miss(self):
        """跳空漲停、開盤即收盤:板面算大漲,本規則不算——你買不到那個價。"""
        bar = {"open": 110.0, "close": 110.0, "adj_factor": 1.0}
        outcome = assess(score=self._score(fwd_1d=0.0), entry_day="E",
                         entry_bar=bar, signal_bar=self.SIGNAL)
        self.assertFalse(outcome["hit"])
        self.assertTrue(outcome["board_hit"])
        self.assertTrue(outcome["limit_open"])


# ── §3:裁決 ───────────────────────────────────────────────────────────────

class VerdictTests(unittest.TestCase):
    def test_the_30_is_imported_not_restated(self):
        self.assertIs(nds.LOW_SAMPLE_SURVIVORS, bwd.LOW_SAMPLE_SURVIVORS)
        self.assertIs(nds.PLACEBO_SEEDS, fvb.PLACEBO_SEEDS)
        self.assertIs(nds.seed_result, fvb.seed_result)
        source = (PIPELINE / "radar" / "compute" / "next_day_surge_battery.py").read_text(
            encoding="utf-8")
        # 只抓**賦值**與比較式裡的字面值:docstring 引用 ``n >= 30`` 是在描述規則。
        code = "\n".join(
            line for line in source.splitlines()
            if line.strip() and not line.strip().startswith(("#", "``", "A ", "B ", "C "))
            and "``" not in line
        )
        self.assertIsNone(re.search(r"^\s*\w+\s*=\s*30\b|[<>]=?\s*30\b", code, re.M))
        self.assertIsNone(re.search(r"range\(10\)", code))
        self.assertIsNone(re.search(r"\b2\.0\b|sqrt", code))

    def test_power_needs_both_n_and_hits(self):
        self.assertTrue(power_verdict(n=30, h_l=30)["passed"])
        self.assertFalse(power_verdict(n=1000, h_l=29)["passed"])
        self.assertFalse(power_verdict(n=29, h_l=29)["passed"])
        self.assertIn("NOT a refutation", power_verdict(n=5, h_l=1)["line"])

    def test_verdict_reasons_are_not_interchangeable(self):
        a_ok = {"passed": True, "line": "a"}
        a_no = {"passed": False, "line": "a"}
        good = {"passed": True, "evaluable": True, "line": "x"}
        bad = {"passed": False, "evaluable": True, "line": "x"}
        blank = {"passed": False, "evaluable": False, "line": "x"}
        self.assertEqual(overall_verdict(test_a=a_no, test_b=good, test_c=good)["reason"],
                         "underpowered")
        self.assertEqual(overall_verdict(test_a=a_ok, test_b=blank, test_c=good)["reason"],
                         "not_evaluable")
        self.assertEqual(overall_verdict(test_a=a_ok, test_b=bad, test_c=good)["reason"],
                         "informativeness_failed")
        self.assertEqual(overall_verdict(test_a=a_ok, test_b=good, test_c=bad)["reason"],
                         "consistency_failed")
        self.assertEqual(overall_verdict(test_a=a_ok, test_b=good, test_c=good)["decision"],
                         "SHIP")

    def test_one_failing_criterion_of_twenty_fails_b(self):
        good = {"evaluable": True, "passed": True}
        seeds = [{"placebo": p, "seed": s, **good} for p in ("stock", "date") for s in range(10)]
        self.assertEqual(nds.informativeness_verdict(seeds=seeds)["outcome"], "PASS")
        seeds[-1] = {**seeds[-1], "passed": False}
        self.assertEqual(nds.informativeness_verdict(seeds=seeds)["outcome"], "FAIL")

    def test_c_is_strictly_positive(self):
        entry = {"placebo": "stock", "seed": 0, "half": "H1", "evaluable": True}
        self.assertEqual(nds.consistency_verdict(entries=[{**entry, "passed": False}])["outcome"],
                         "FAIL")

    def test_as_of_must_be_the_last_price_date(self):
        nds.check_as_of(as_of="2026-09-23", max_price_date="2026-09-23", historical=False)
        with self.assertRaisesRegex(ValueError, "not the last daily_prices date"):
            nds.check_as_of(as_of="2026-09-22", max_price_date="2026-09-23", historical=False)
        nds.check_as_of(as_of="2026-09-22", max_price_date="2026-09-23", historical=True)
        with self.assertRaisesRegex(ValueError, "after the last"):
            nds.check_as_of(as_of="2026-09-24", max_price_date="2026-09-23", historical=True)

    def test_a_short_pool_is_reported_and_never_borrowed(self):
        pools = {"A": [("A", "d1")], "B": [("B", "d1"), ("B", "d2"), ("B", "d3")]}
        draw = draw_matched(pools=pools, counts={"A": 2, "B": 2}, seed=0)
        self.assertEqual(draw["short"], [{"key": "A", "k": 2, "pool_size": 1}])
        self.assertEqual(len(draw["drawn"]), 3)
        self.assertEqual(draw_matched(pools=pools, counts={"A": 2, "B": 2}, seed=0), draw)


class SurgeFactsShapeTests(unittest.TestCase):
    """§1 的形狀鎖與比率閘門。

    閘門逐**詞**(以 ``_`` 切開)比對,不是子字串:``RANK_ISH`` 裡的 ``place`` 是
    ``placebo`` 的子字串,而 ``placebo_*`` 是 §1 寫死的鍵名。子字串閘門在這裡只會
    逼人去改一個凍結的名字;形狀鎖則保證不會有第 N+1 個鍵溜進來。
    """

    FACTS = surge_facts(date_from="2026-07-06", date_to="2026-09-22", events=1240,
                        hits=96, placebo_stock_hits=[41, 58, 50],
                        placebo_date_hits=[37, 55])

    def test_exactly_the_section_1_keys(self):
        self.assertEqual(tuple(self.FACTS), FACT_KEYS)
        self.assertEqual(sorted(self.FACTS["placebo_stock_hits"]), ["max", "min"])
        self.assertEqual(self.FACTS["placebo_stock_hits"], {"min": 41, "max": 58})
        self.assertEqual(self.FACTS["placebo_date_hits"], {"min": 37, "max": 55})

    def test_every_number_is_an_integer_and_nothing_is_a_rate(self):
        def walk(value):
            if isinstance(value, dict):
                for inner in value.values():
                    yield from walk(inner)
            else:
                yield value
        for value in walk(self.FACTS):
            self.assertNotIsInstance(value, (bool, float))
            self.assertIsInstance(value, (int, str))
        forbidden = set(RATIO_ISH + RANK_ISH) | {"rate", "prob", "probability", "percent",
                                                  "share", "win"}

        def keys(value):
            if isinstance(value, dict):
                for key, inner in value.items():
                    yield key
                    yield from keys(inner)
        for key in keys(self.FACTS):
            self.assertFalse(set(key.lower().split("_")) & forbidden, key)
        # 唯一帶 pct 的鍵是凍結的輸入參數,不是算出來的比率,值恆為 7。
        self.assertEqual([k for k in self.FACTS if "pct" in k], ["threshold_pct"])
        self.assertEqual(self.FACTS["threshold_pct"], 7)

    def test_no_events_or_no_placebo_means_no_claim(self):
        self.assertIsNone(surge_facts(date_from=None, date_to=None, events=0, hits=0,
                                      placebo_stock_hits=[1], placebo_date_hits=[1]))
        self.assertIsNone(surge_facts(date_from="a", date_to="b", events=5, hits=1,
                                      placebo_stock_hits=[], placebo_date_hits=[1]))


# ── 呼叫點:規則單獨測是對的,還要驗 assemble 真的照它接 ───────────────────
#
# 這一段是驗證者用變異測試逼出來的:把 e 改成讀儲存的 entry_date、讓段落跨過缺
# 評分的市場日、拿掉 has_close、把評估期從第一個價格日起算、移動 H1/H2 邊界——
# 這些錯誤實作先前全部通過整份測試,因為單元測試只驗函式本身,沒驗呼叫端餵它什麼。

_P = ["2026-02-23", "2026-02-24", "2026-02-25"]          # 評分開始前的價格日
_M = ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06",
      "2026-03-09", "2026-03-10"]                         # 評估期 7 天:H1 3 天、H2 4 天


def _mem_score(stock_id, day, *, final=80, has_close=1, entry=None, fwd=0.0):
    index = (_P + _M).index(day)
    if entry is None:
        entry = (_P + _M)[index + 1] if index + 1 < len(_P + _M) else None
    return {"stock_id": stock_id, "date": day, "final": final, "branch_score": 50,
            "turnover": 1, "has_close": has_close, "entry_date": entry,
            "fwd_1d": fwd if entry is not None else None}


def _mem_assemble(scores, *, bars_override=None):
    bars = {}
    stocks = {row["stock_id"] for row in scores}
    for stock_id in stocks:
        for day in _P + _M:
            bars[(stock_id, day)] = {"open": 100.0, "close": 100.0, "adj_factor": 1.0}
    bars.update(bars_override or {})
    scores = sorted(scores, key=lambda row: (row["date"], row["stock_id"]))
    return nds.assemble(as_of=_M[-1], run_number=1, market_days=_P + _M,
                        scores=scores, bars=bars, coverage={})


class CallSiteTests(unittest.TestCase):
    def test_halves_split_on_score_days_with_the_odd_day_in_h2(self):
        halves, half_of = nds.half_assigner(_M)
        self.assertEqual(halves["formation_market_days"], 3)
        self.assertEqual(half_of(_M[2]), "H1")          # 前半最後一天仍是 H1
        self.assertEqual(half_of(_M[3]), "H2")
        self.assertEqual(nds.evaluation_days(market_days=_P + _M, first_score_day=_M[0]), _M)

    def test_the_evaluation_period_starts_at_the_first_score_day(self):
        report = _mem_assemble([_mem_score("A", _M[0]), _mem_score("A", _M[2])])
        self.assertEqual(report["coverage"]["evaluation_from"], _M[0])
        self.assertEqual(report["halves"]["H1"], [_M[0], _M[2]])
        self.assertEqual(report["halves"]["H2_market_days"], 4)
        # _M[2] 是 H1 的最後一天:它的事件算 H1。
        self.assertEqual(report["sets"]["events_by_half"], {"H1": 2, "H2": 0})

    def test_a_market_day_without_any_scores_breaks_the_run(self):
        """_M[1] 有價格、沒有任何評分列:A 在 _M[0] 與 _M[2] 是兩個事件,不是一段。"""
        report = _mem_assemble([_mem_score("A", _M[0]), _mem_score("A", _M[2])])
        self.assertEqual(report["sets"]["events"], 2)

    def test_e_comes_from_the_calendar_not_the_stored_entry_date(self):
        """儲存的 entry_date 指向 t+2,而且 fwd_1d 與 t+2 自洽——仍然必須否決。"""
        rows = [_mem_score("C", _M[0], entry=_M[2], fwd=8.0)]
        report = _mem_assemble(rows, bars_override={
            ("C", _M[2]): {"open": 100.0, "close": 108.0, "adj_factor": 1.0}})
        self.assertEqual(report["refusals"]["events"]["R2_entry_shifted"], 1)
        self.assertEqual(report["sets"]["events"], 0)

    def test_a_row_without_a_close_on_t_is_not_on_the_list(self):
        """export 只列當日有收盤價的股票;沒有收盤價的高分列不可能被讀者看到。"""
        rows = [_mem_score("A", _M[0]), _mem_score("B", _M[0], final=99, has_close=0)]
        report = _mem_assemble(rows)
        self.assertEqual(report["sets"]["events"], 1)


# ── 端到端:暫存資料庫 ────────────────────────────────────────────────────

class _FixtureDB(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.old_url, self.old_dir = config.DB_URL, config.DATA_DIR
        self.db_path = self.tmp_path / "surge-battery.db"
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

    def write_fixture(self, *, stocks=_STOCKS, always_hit=False, always_listed=(),
                      corrupt=None):
        """``always_hit``:每一天收盤都是 110(兩臂都命中,檢定 B 必敗)。
        ``always_listed``:這些股票每一天都在榜上(一段只算一個事件)。
        ``corrupt``:(stock_id, day_index) 的儲存 fwd_1d 改錯,觸發 R2。
        """
        prices, scores = [], []
        for index, stock_id in enumerate(stocks):
            listed = [
                stock_id in always_listed or _on_list(index, d) for d in range(len(_DAYS))
            ]
            for d, day in enumerate(_DAYS):
                close = 110.0 if always_hit or (d > 0 and listed[d - 1]) else 100.0
                prices.append({"stock_id": stock_id, "date": day, "open": 100.0,
                               "close": close, "adj_factor": 1.0,
                               "turnover": 1_000_000_000})
            for d, day in enumerate(_DAYS):
                entry = _DAYS[d + 1] if d + 1 < len(_DAYS) else None
                fwd = None
                if entry is not None:
                    next_close = 110.0 if always_hit or listed[d] else 100.0
                    fwd = round((next_close / 100.0 - 1) * 100, 2)
                if corrupt == (stock_id, d):
                    fwd = 3.33
                scores.append({"stock_id": stock_id, "date": day,
                               "final": 80 if listed[d] else 50, "branch_score": 50,
                               "entry_date": entry, "fwd_1d": fwd})
        with db.get_engine().begin() as conn:
            conn.exec_driver_sql("DELETE FROM stocks")
            for stock_id in stocks:
                conn.exec_driver_sql(
                    "INSERT INTO stocks (id, name, market, type, is_active) "
                    "VALUES (?, ?, 'twse', 'stock', 1)", (stock_id, stock_id))
            conn.exec_driver_sql(
                "INSERT INTO stocks (id, name, market, type, is_active) "
                "VALUES ('0050', 'etf', 'twse', 'etf', 1)")
            for p in prices:
                conn.exec_driver_sql(
                    "INSERT INTO daily_prices (stock_id, date, open, close, adj_factor, "
                    "turnover) VALUES (?, ?, ?, ?, ?, ?)",
                    (p["stock_id"], p["date"], p["open"], p["close"], p["adj_factor"],
                     p["turnover"]))
            for s in scores:
                conn.exec_driver_sql(
                    "INSERT INTO daily_scores (stock_id, date, final, branch_score, "
                    "entry_date, fwd_1d) VALUES (?, ?, ?, ?, ?, ?)",
                    (s["stock_id"], s["date"], s["final"], s["branch_score"],
                     s["entry_date"], s["fwd_1d"]))
            # 一檔 ETF 的高分列:type != 'stock',不得上榜(R4)。
            conn.exec_driver_sql(
                "INSERT INTO daily_prices (stock_id, date, open, close, adj_factor, turnover) "
                "VALUES ('0050', ?, 100, 200, 1.0, 9999999999)", (_DAYS[0],))
            conn.exec_driver_sql(
                "INSERT INTO daily_scores (stock_id, date, final, branch_score) "
                "VALUES ('0050', ?, 99, 99)", (_DAYS[0],))
        db._engine.dispose()
        db._engine = None

    def run_battery(self):
        return build_next_day_surge_battery(as_of=_DAYS[-1])


class EndToEndTests(_FixtureDB):
    def test_the_constructed_signal_ships(self):
        self.write_fixture()
        report = self.run_battery()
        self.assertEqual(report["sets"]["events"], _EVENTS_MATURE)
        self.assertEqual(report["sets"]["hits"], _EVENTS_MATURE)
        self.assertEqual(report["refusals"]["events"]["R1_no_entry_day"], _EVENTS_LAST_DAY)
        for seed in report["tests"]["B"]["seeds"]:
            self.assertEqual(seed["h_p"], 0)
        self.assertEqual(len(report["tests"]["B"]["seeds"]), 20)
        self.assertEqual(len(report["tests"]["C"]["entries"]), 40)
        self.assertEqual(report["verdict"]["decision"], "SHIP")
        facts = report["facts_if_shipped"]
        self.assertEqual(facts["events"], _EVENTS_MATURE)
        self.assertEqual(facts["placebo_stock_hits"], {"min": 0, "max": 0})
        self.assertEqual(facts["placebo_date_hits"], {"min": 0, "max": 0})
        self.assertEqual(facts["from"], _DAYS[0])
        self.assertEqual(facts["to"], _DAYS[18])

    def test_the_etf_high_score_is_not_on_the_list(self):
        self.write_fixture()
        report = self.run_battery()
        # 0050 若上榜,第 0 天會多一個事件,而且它沒有進場日列(只有一天價格)。
        self.assertEqual(report["refusals"]["events"]["R1_no_entry_row"], 0)
        self.assertEqual(report["sets"]["events"], _EVENTS_MATURE)

    def test_a_signal_the_baseline_also_has_fails_b(self):
        self.write_fixture(always_hit=True)
        report = self.run_battery()
        self.assertTrue(report["tests"]["A"]["passed"])
        self.assertEqual(report["tests"]["B"]["outcome"], "FAIL")
        self.assertEqual(report["verdict"]["decision"], "DO NOT SHIP")
        self.assertEqual(report["verdict"]["reason"], "informativeness_failed")
        # 兩臂每一半都一樣多:差值 0 不是正號,C 也必須不過(嚴格大於)。
        self.assertEqual(report["tests"]["C"]["outcome"], "FAIL")

    def test_too_few_events_is_underpowered_not_refuted(self):
        self.write_fixture(stocks=_STOCKS[:3])
        report = self.run_battery()
        self.assertEqual(report["tests"]["A"]["outcome"], "UNDERPOWERED")
        self.assertEqual(report["verdict"]["reason"], "underpowered")

    def test_a_stock_always_on_the_list_leaves_its_pool_empty(self):
        """同股對照抽不滿 → NOT EVALUABLE,並逐項列出是哪一檔、哪一半。"""
        self.write_fixture(always_listed=(_STOCKS[0],))
        report = self.run_battery()
        self.assertTrue(report["tests"]["A"]["passed"])
        self.assertEqual(report["tests"]["B"]["outcome"], "NOT EVALUABLE")
        self.assertEqual(report["verdict"]["reason"], "not_evaluable")
        self.assertEqual(report["sets"]["placebo_short"]["stock"],
                         [{"key": [_STOCKS[0], "H1"], "k": 1, "pool_size": 0}])

    def test_a_corrupt_stored_return_is_refused_and_counted(self):
        self.write_fixture(corrupt=(_STOCKS[0], 0))
        report = self.run_battery()
        self.assertEqual(report["refusals"]["events"]["R2_fwd_mismatch"], 1)
        self.assertEqual(report["sets"]["events"], _EVENTS_MATURE - 1)

    def test_coverage_is_recorded(self):
        self.write_fixture()
        coverage = self.run_battery()["coverage"]
        self.assertEqual(coverage["daily_scores_first_date"], _DAYS[0])
        self.assertEqual(coverage["daily_scores_dates"], 20)
        self.assertEqual(coverage["daily_scores_rows"], 40 * 20 + 1)
        self.assertEqual(coverage["market_days_in_evaluation"], 20)


class ReadOnlyAndOutputTests(_FixtureDB):
    def test_the_battery_writes_nothing_to_the_database(self):
        self.write_fixture()
        before = hashlib.sha256(self.db_path.read_bytes()).hexdigest()
        out = self.tmp_path / "battery.json"
        report = write_next_day_surge_battery(as_of=_DAYS[-1], out=out)
        self.assertEqual(hashlib.sha256(self.db_path.read_bytes()).hexdigest(), before)
        self.assertTrue(report["metadata"]["read_only"])
        self.assertEqual(report["metadata"]["preregistration_commit"], "f8a57b5")
        written = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(written["verdict"], report["verdict"])

    def test_the_output_path_may_not_be_the_database(self):
        self.write_fixture()
        with self.assertRaisesRegex(ValueError, "must not be"):
            write_next_day_surge_battery(as_of=_DAYS[-1], out=str(self.db_path))

    def test_the_output_is_deterministic(self):
        self.write_fixture()
        first = self.tmp_path / "a.json"
        second = self.tmp_path / "b.json"
        write_next_day_surge_battery(as_of=_DAYS[-1], out=first)
        write_next_day_surge_battery(as_of=_DAYS[-1], out=second)
        self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_cli_runs_the_battery_and_prints_the_verdict(self):
        self.write_fixture()
        out = self.tmp_path / "cli.json"
        main(["next-day-surge-battery", "--as-of", _DAYS[-1], "--out", str(out)])
        written = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(written["metadata"]["run_number"], 1)
        self.assertEqual(written["verdict"]["decision"], "SHIP")


if __name__ == "__main__":
    unittest.main()
