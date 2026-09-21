"""個股期貨 export 契約(per-stock `futures` 區塊)。

只驗「是不是標的」這個事實,外加當日的量/未平倉。刻意**沒有**任何比率、均值、
名次——量能異常排行是後面的切片,需要 60 個交易日歷史與事先登記的否決條件。
最後一個測試就是守住這件事的閘門。

用即拋 SQLite,風格同 test_backfill_gaps.py / test_margin_export.py,不連網路。
"""
import json
import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import radar.config as config
import radar.db as db
from radar import schema
from radar.compute.futures_volume_anomaly import REASON_CODE, RISK_CODE
from radar.compute.futures_volume_battery import (
    ANOMALY_FACT_KEYS,
    WINDOW_DAYS,
    anomaly_facts,
    evaluate_contract_day,
)
from radar.compute.settlement_calendar import settlement_exclusion_set
from radar.export.json_export import export_json

D = "2026-09-15"      # 價格日 = export 日
P = "2026-09-14"
LIST_AS_OF = "2026-09-11"   # 清單刷新日,刻意早於價格日

RATIO_ISH = ("ratio", "avg", "mean", "rank", "score", "z")


def _contract(code, stock_id, *, last_seen=LIST_AS_OF, future=1, option=0, weekly=0):
    return {
        "contract_code": code, "stock_id": stock_id, "stock_name": "x",
        "is_stock_future": future, "is_stock_option": option,
        "is_weekly_option": weekly, "market": "twse",
        "first_seen": "2026-01-02", "last_seen": last_seen,
    }


def _daily(code, month, session, volume, oi, date=D):
    return {"contract_code": code, "date": date, "contract_month": month,
            "session": session, "volume": volume, "open_interest": oi}


class FuturesExportTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._old_url, self._old_dir = config.DB_URL, config.DATA_DIR
        config.DATA_DIR = tmp
        config.DB_URL = "sqlite:///" + (tmp / "t.db").as_posix()
        db._engine = None
        db.init_db()
        self._seed_prices()
        self.out = tmp / "out"

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old_url, self._old_dir
        self._tmp.cleanup()

    def _seed_prices(self):
        eng = db.get_engine()
        with eng.begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": "2303", "name": "聯電", "market": "twse", "type": "stock", "is_active": 1},
                {"id": "1565", "name": "精華", "market": "tpex", "type": "stock", "is_active": 1},
                {"id": "9999", "name": "非標的", "market": "twse", "type": "stock", "is_active": 1},
            ])
            rows = []
            for sid in ("2303", "1565", "9999"):
                for date, close in ((P, 50.0), (D, 51.0)):
                    rows.append({"stock_id": sid, "date": date, "close": close,
                                 "volume": 1000, "turnover": 51_000_000})
            conn.execute(schema.daily_prices.insert(), rows)

    def _seed_futures(self, contracts, daily=()):
        eng = db.get_engine()
        with eng.begin() as conn:
            if contracts:
                conn.execute(schema.futures_contracts.insert(), list(contracts))
            if daily:
                conn.execute(schema.futures_daily.insert(), list(daily))

    def _stock(self, sid):
        export_json(self.out)
        return json.loads((self.out / "stocks" / f"{sid}.json").read_text(encoding="utf-8"))

    # ── 事實本身 ────────────────────────────────────────────────
    def test_single_contract(self):
        self._seed_futures([_contract("CCF", "2303", option=1)])
        futures = self._stock("2303")["futures"]
        self.assertEqual(futures["version"], 1)
        self.assertEqual(futures["contracts"], [
            {"code": "CCF", "is_futures": True, "is_option": True, "is_weekly_option": False},
        ])

    def test_two_contracts_for_one_stock(self):
        """1565 同時是 2,000 股的 MYF 與 100 股的 OMF——所以鍵是契約代碼。"""
        self._seed_futures([_contract("MYF", "1565"), _contract("OMF", "1565")])
        codes = [c["code"] for c in self._stock("1565")["futures"]["contracts"]]
        self.assertEqual(codes, ["MYF", "OMF"])

    def test_not_an_underlying_is_an_empty_list_not_a_missing_key(self):
        """空陣列是一個正面主張:完整官方清單截至該日不含這檔。"""
        self._seed_futures([_contract("CCF", "2303")])
        futures = self._stock("9999")["futures"]
        self.assertEqual(futures["contracts"], [])
        self.assertEqual(futures["list_as_of"], LIST_AS_OF)

    def test_key_absent_entirely_before_the_first_import(self):
        """沒有鍵 = 「我們不知道」,不可以與 contracts: [] 塌成同一件事。"""
        stock = self._stock("2303")
        self.assertNotIn("futures", stock)

    def test_list_as_of_is_the_mapping_date_not_the_price_date(self):
        self._seed_futures([_contract("CCF", "2303", last_seen=LIST_AS_OF)])
        stock = self._stock("2303")
        self.assertEqual(stock["futures"]["list_as_of"], LIST_AS_OF)
        self.assertNotEqual(stock["futures"]["list_as_of"], D)

    # ── 當日數字 ────────────────────────────────────────────────
    def test_daily_omitted_when_no_row_for_the_export_date(self):
        self._seed_futures(
            [_contract("CCF", "2303")],
            [_daily("CCF", "202609", "一般", 500, 900, date=P)],
        )
        contract = self._stock("2303")["futures"]["contracts"][0]
        self.assertNotIn("daily", contract)

    def test_daily_sums_months_and_splits_sessions(self):
        self._seed_futures(
            [_contract("CCF", "2303")],
            [
                _daily("CCF", "202609", "一般", 500, 900),
                _daily("CCF", "202610", "一般", 100, 100),
                # 盤後沒有未平倉(來源給 '-')——存量不可以兩個時段相加。
                _daily("CCF", "202609", "盤後", 40, None),
            ],
        )
        daily = self._stock("2303")["futures"]["contracts"][0]["daily"]
        self.assertEqual(daily["date"], D)
        self.assertEqual(daily["volume"], 640)
        self.assertEqual(daily["open_interest"], 1000)
        self.assertEqual(daily["session_volume"], {"一般": 600, "盤後": 40})

    def test_session_volume_only_lists_sessions_that_actually_have_rows(self):
        """21:20 那一輪常只有一般時段;寫 盤後: 0 會把「未公布」謊報成「沒成交」。"""
        self._seed_futures(
            [_contract("CCF", "2303")],
            [_daily("CCF", "202609", "一般", 500, 900)],
        )
        daily = self._stock("2303")["futures"]["contracts"][0]["daily"]
        self.assertEqual(daily["session_volume"], {"一般": 500})

    def test_calendar_spread_rows_are_excluded_from_the_volume_sum(self):
        """'202609/202610' 是轉倉對敲,不是部位;拿掉過濾這個測試必須紅。"""
        self._seed_futures(
            [_contract("CCF", "2303")],
            [
                _daily("CCF", "202609", "一般", 500, 900),
                _daily("CCF", "202609/202610", "一般", 2541, None),
            ],
        )
        daily = self._stock("2303")["futures"]["contracts"][0]["daily"]
        self.assertEqual(daily["volume"], 500)
        self.assertEqual(daily["session_volume"], {"一般": 500})

    # ── freshness ──────────────────────────────────────────────
    def test_freshness_reports_futures_lag(self):
        self._seed_futures(
            [_contract("CCF", "2303")],
            [_daily("CCF", "202609", "一般", 500, 900, date=P)],
        )
        export_json(self.out)
        payload = json.loads((self.out / "radar.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["freshness"]["futures"], {"date": P, "stale": True})

    # ── 閘門 ────────────────────────────────────────────────────
    def test_payload_cannot_silently_gain_a_rate(self):
        """後面那個切片要加比率/名次,得自己動手並過 review,不能順手混進來。"""
        self._seed_futures(
            [_contract("CCF", "2303"), _contract("MYF", "1565")],
            [
                _daily("CCF", "202609", "一般", 500, 900),
                _daily("CCF", "202609", "盤後", 40, None),
                _daily("CCF", "202609/202610", "一般", 2541, None),
            ],
        )
        export_json(self.out)
        offenders = []

        def walk(node, path):
            if isinstance(node, dict):
                for key, value in node.items():
                    lowered = key.lower()
                    if any(bad in lowered for bad in RATIO_ISH):
                        offenders.append(f"{path}.{key}")
                    walk(value, f"{path}.{key}")
            elif isinstance(node, list):
                for i, value in enumerate(node):
                    walk(value, f"{path}[{i}]")

        for sid in ("2303", "1565", "9999"):
            stock = json.loads((self.out / "stocks" / f"{sid}.json").read_text(encoding="utf-8"))
            walk(stock["futures"], f"{sid}.futures")
        self.assertEqual(offenders, [])


# ══ 成交量異常切片(docs/38 §4 步驟 5) ═══════════════════════════════════
#
# 這一段的每一個數字都是**發明的**,而且是為了讓答案可以手算而發明的:一天 100 口
# 的底、候選日 500 口、現貨每天 1,000,000 股。所以 today / window_max /
# window_median 在寫測試的時候就已經是 500 / 100 / 100,不必跑一次再抄回來。
#
# 這個切片只有在 battery 判 SHIP 之後才允許存在(as_of 2026-09-17、run 1、
# |F_only| = 680 >= 30、十組 seed 全部過 2σ)。證據在
# docs/evidence/futures-volume-battery-20260921.json。

def _weekdays(start: date, count: int) -> list[str]:
    days: list[str] = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current.isoformat())
        current += timedelta(days=1)
    return days


# 2026-01-05(週一)起 120 個工作日,到 2026-06-19。期間內每一個第三個星期三都是
# 工作日,所以 R4 排除日是手算得出的四天一組(六月:06-12、15、16、17)。
# 120 天扣掉 24 個排除日還有 95 個比較日可用,湊得滿 60。
_DAYS = _weekdays(date(2026, 1, 5), 120)
AD = _DAYS[-1]                      # 2026-06-19,異常切片的 export 日(非排除日)
_JUNE_SETTLEMENT = "2026-06-17"     # 六月結算日,在候選日的比較窗口之內
_EXCLUDED = settlement_exclusion_set(
    date_from=_DAYS[0], date_to=AD, market_days=_DAYS,
)

BASE_LOTS = 100                     # 每一個比較日的一般時段口數
SPIKE_LOTS = 500                    # 候選日:嚴格大於 100,所以舉旗
SPOT_SHARES = 1_000_000             # 現貨天天同量 → 候選日**不是**現貨新高
MULTIPLIER = 2_000                  # 股/口,標準型
BASE_OI, TODAY_OI = 1_000, 1_210    # 未平倉較前日 +210 口

# 五個鍵、手算的五個值。第六個鍵不存在,這是 §1 表格的全部內容。
EXPECTED_FACTS = {
    "today": SPIKE_LOTS, "window_max": BASE_LOTS, "window_median": BASE_LOTS,
    "oi_change": TODAY_OI - BASE_OI, "window_days": WINDOW_DAYS,
}
EXPECTED_REASON = (
    "CCF 期貨一般時段成交 500 口,創 60 個比較日新高(前高 100 口、中位數 100 口),"
    "未平倉較前日 +210 口。"
)
EXPECTED_RISK = "量創高不代表方向;結算週已排除;盤後未計;現貨當日無同步創高。"


def _spec(code, stock_id, *, multiplier=MULTIPLIER, today=SPIKE_LOTS,
          lots=None, oi=None, days=None):
    """一個契約的完整口數/未平倉序列:平的底 + 候選日一個尖峰,再套上 overrides。"""
    days = _DAYS if days is None else days
    series = {day: BASE_LOTS for day in days}
    series[days[-1]] = today
    series.update(lots or {})
    interest = {day: BASE_OI for day in days}
    interest[days[-1]] = TODAY_OI
    interest.update(oi or {})
    return {"code": code, "stock_id": stock_id, "multiplier": multiplier,
            "lots": series, "oi": interest}


class _AnomalyFixture(unittest.TestCase):
    """120 個交易日的發明資料;每個測試自己決定要種哪幾個契約。"""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._old_url, self._old_dir = config.DB_URL, config.DATA_DIR
        config.DATA_DIR = tmp
        config.DB_URL = "sqlite:///" + (tmp / "t.db").as_posix()
        db._engine = None
        db.init_db()
        self.out = tmp / "out"

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old_url, self._old_dir
        self._tmp.cleanup()

    def seed(self, specs, *, days=None, spot_missing=()):
        """``spot_missing`` = {(stock_id, date)},用來戳出 R2b 的現貨缺口。"""
        days = _DAYS if days is None else days
        stock_ids = sorted({spec["stock_id"] for spec in specs})
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": sid, "name": f"F{sid}", "market": "twse",
                 "type": "stock", "is_active": 1}
                for sid in stock_ids
            ])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": sid, "date": day, "close": 50.0, "adj_factor": 1.0,
                 "volume": SPOT_SHARES, "turnover": 50_000_000}
                for sid in stock_ids for day in days
                if (sid, day) not in set(spot_missing)
            ])
            conn.execute(schema.futures_contracts.insert(), [
                {"contract_code": spec["code"], "stock_id": spec["stock_id"],
                 "stock_name": f"F{spec['stock_id']}", "is_stock_future": 1,
                 "is_stock_option": 0, "is_weekly_option": 0, "market": "twse",
                 "contract_multiplier": spec["multiplier"],
                 "first_seen": days[0], "last_seen": days[-1]}
                for spec in specs
            ])
            rows = []
            for spec in specs:
                for day in days:
                    lots = spec["lots"].get(day)
                    if lots is None:
                        continue        # 缺列 ≠ 0 口:這一天根本沒有列。
                    rows.append({
                        "contract_code": spec["code"], "date": day,
                        "contract_month": "202612", "session": "一般",
                        "volume": lots, "open_interest": spec["oi"].get(day),
                    })
                    # 盤後列與價差組合列都給一個大到不可能忽略的量:統計量若不小心
                    # 讀到它們,下面每一個期望值都會錯。
                    rows.append({
                        "contract_code": spec["code"], "date": day,
                        "contract_month": "202612", "session": "盤後",
                        "volume": 999_999, "open_interest": None,
                    })
                    rows.append({
                        "contract_code": spec["code"], "date": day,
                        "contract_month": "202612/202701", "session": "一般",
                        "volume": 888_888, "open_interest": None,
                    })
            conn.execute(schema.futures_daily.insert(), rows)

    def contracts(self, sid):
        export_json(self.out)
        payload = json.loads(
            (self.out / "stocks" / f"{sid}.json").read_text(encoding="utf-8"))
        return {c["code"]: c for c in payload["futures"]["contracts"]}


class AnomalyFixtureSanityTests(unittest.TestCase):
    """手算出來的日曆事實。這些若不成立,底下每個測試都在驗錯的東西。"""

    def test_the_candidate_day_is_not_itself_a_settlement_window_day(self):
        self.assertNotIn(AD, _EXCLUDED)

    def test_june_settlement_day_is_excluded_and_sits_inside_the_window(self):
        self.assertIn(_JUNE_SETTLEMENT, _EXCLUDED)
        self.assertLess(_JUNE_SETTLEMENT, AD)


class AnomalyFactsTests(_AnomalyFixture):
    def test_a_flagged_contract_emits_the_five_hand_computed_facts(self):
        self.seed([_spec("CCF", "2303")])
        self.assertEqual(self.contracts("2303")["CCF"]["anomaly"], EXPECTED_FACTS)

    def test_five_keys_no_sixth_and_every_value_an_integer(self):
        """§4 步驟 5 指名要的那把鎖:第六個鍵要加,得自己動手並過 review。"""
        self.seed([_spec("CCF", "2303")])
        anomaly = self.contracts("2303")["CCF"]["anomaly"]
        self.assertEqual(sorted(anomaly), sorted(ANOMALY_FACT_KEYS))
        self.assertEqual(len(anomaly), 5)
        for key, value in anomaly.items():
            self.assertIsInstance(value, int, key)
            self.assertNotIsInstance(value, bool, key)

    def test_the_facts_are_exactly_what_the_battery_rule_produces(self):
        """同一份輸入,export 的區塊必須與 battery 那條規則的輸出逐字相同。

        export 若自己重寫一條規則,這個等號就是第一個會斷的地方。
        """
        self.seed([_spec("CCF", "2303")])
        outcome = evaluate_contract_day(
            today_volume=SPIKE_LOTS,
            window_volumes=[BASE_LOTS] * WINDOW_DAYS,
            multiplier=MULTIPLIER,
            spot_window_volumes=[SPOT_SHARES] * WINDOW_DAYS,
        )
        outcome["oi_change"] = TODAY_OI - BASE_OI
        self.assertEqual(self.contracts("2303")["CCF"]["anomaly"],
                         anomaly_facts(outcome))

    def test_the_export_goes_through_the_batterys_own_rule(self):
        """把 battery 的規則換掉,export 必須跟著改變答案。

        它若在自己家裡重新實作了一次「創 60 日新高」,這個測試會照樣綠——所以它
        測的正是「有沒有共用」,不是「算得對不對」。
        """
        self.seed([_spec("CCF", "2303")])
        calls = []

        def refuse_everything(**kwargs):
            calls.append(kwargs)
            return {"refusal": "R1_window_gap", "flag": False}

        with patch("radar.compute.futures_volume_battery.evaluate_contract_day",
                   refuse_everything):
            contract = self.contracts("2303")["CCF"]
        self.assertTrue(calls, "export never called the battery's rule")
        self.assertNotIn("anomaly", contract)

    def test_the_flag_is_strictly_greater_than_the_window_max(self):
        self.seed([_spec("CCF", "2303", today=BASE_LOTS)])
        self.assertNotIn("anomaly", self.contracts("2303")["CCF"])

    def test_one_lot_above_the_window_max_is_enough_to_flag(self):
        # 乘數 2,000 → 100 x (300 - 100) x 2,000 遠大於 1,000,000 股,R2b 不擋。
        self.seed([_spec("CCF", "2303", today=BASE_LOTS + 200)])
        self.assertEqual(
            self.contracts("2303")["CCF"]["anomaly"]["today"], BASE_LOTS + 200)

    def test_a_contract_with_no_regular_row_today_makes_no_claim(self):
        self.seed([_spec("CCF", "2303", lots={AD: None})])
        contract = self.contracts("2303")["CCF"]
        self.assertNotIn("anomaly", contract)
        self.assertNotIn("daily", contract)


class AnomalyRefusalTests(_AnomalyFixture):
    """五條否決各一個**真的把它點著**的案例。否決 = 整個區塊不輸出,不是 0/null。"""

    def test_r1_a_missing_row_inside_the_window_emits_no_block(self):
        gap = _DAYS[-2]
        self.assertNotIn(gap, _EXCLUDED)    # 真的落在比較窗口裡,不是被 R4 跳過
        self.seed([_spec("CCF", "2303", lots={gap: None}),
                   _spec("MYF", "1565")])
        contracts = self.contracts("2303") | self.contracts("1565")
        self.assertNotIn("anomaly", contracts["CCF"])
        self.assertIn("anomaly", contracts["MYF"])      # 對照:歷史完整就舉旗

    def test_r1_too_little_history_emits_no_block(self):
        days = _DAYS[-40:]          # 湊不滿 60 個比較日
        self.seed([_spec("CCF", "2303", days=days)], days=days)
        self.assertNotIn("anomaly", self.contracts("2303")["CCF"])

    def test_r2a_a_zero_median_emits_no_block_even_on_a_huge_spike(self):
        quiet = {day: 0 for day in _DAYS[:-1]}
        self.seed([_spec("CCF", "2303", lots=quiet)])
        self.assertNotIn("anomaly", self.contracts("2303")["CCF"])

    def test_r2b_an_unknown_multiplier_emits_no_block_and_is_never_2000(self):
        self.seed([_spec("CCF", "2303", multiplier=None),
                   _spec("MYF", "1565")])
        contracts = self.contracts("2303") | self.contracts("1565")
        self.assertNotIn("anomaly", contracts["CCF"])
        self.assertIn("anomaly", contracts["MYF"])

    def test_r2b_a_hole_in_the_spot_ruler_emits_no_block(self):
        hole = _DAYS[-2]
        self.seed([_spec("CCF", "2303"), _spec("MYF", "1565")],
                  spot_missing=[("1565", hole)])
        contracts = self.contracts("2303") | self.contracts("1565")
        self.assertIn("anomaly", contracts["CCF"])
        self.assertNotIn("anomaly", contracts["MYF"])

    def test_r2b_an_immaterial_new_high_emits_no_block(self):
        # 小型契約:100 x (101 - 100) x 100 = 10,000 股 < 1,000,000 股的 1%。
        # 創了高,但換成股當量連現貨日常量的百分之一都不到。
        self.seed([_spec("OMF", "2303", multiplier=100, today=BASE_LOTS + 1)])
        self.assertNotIn("anomaly", self.contracts("2303")["OMF"])

    def test_a_material_new_high_on_the_same_small_contract_does_flag(self):
        # 對照組:同一個乘數 100,今天 500 口 → 100 x 400 x 100 = 4,000,000 股。
        self.seed([_spec("OMF", "2303", multiplier=100)])
        self.assertIn("anomaly", self.contracts("2303")["OMF"])


class AnomalySettlementWindowTests(_AnomalyFixture):
    """R4 兩側一起排除:候選日不得上榜,排除日也不得進比較窗口。"""

    def test_the_settlement_window_is_excluded_from_the_candidate_day(self):
        days = _DAYS[:_DAYS.index(_JUNE_SETTLEMENT) + 1]
        self.assertIn(days[-1], _EXCLUDED)
        self.seed([_spec("CCF", "2303", days=days)], days=days)
        self.assertNotIn("anomaly", self.contracts("2303")["CCF"])

    def test_the_settlement_window_is_excluded_from_the_comparison_window(self):
        """結算日的轉倉尖峰若進了窗口,window_max 會被抬到 9,999,旗標就不會舉。"""
        self.seed([_spec("CCF", "2303", lots={_JUNE_SETTLEMENT: 9_999})])
        self.assertEqual(self.contracts("2303")["CCF"]["anomaly"], EXPECTED_FACTS)


class AnomalyOpenInterestTests(_AnomalyFixture):
    def test_oi_change_is_today_minus_the_previous_futures_trading_day(self):
        self.seed([_spec("CCF", "2303")])
        self.assertEqual(
            self.contracts("2303")["CCF"]["anomaly"]["oi_change"], 210)

    def test_oi_change_is_omitted_entirely_when_today_is_null(self):
        self.seed([_spec("CCF", "2303", oi={AD: None})])
        anomaly = self.contracts("2303")["CCF"]["anomaly"]
        self.assertNotIn("oi_change", anomaly)
        self.assertEqual(sorted(anomaly), sorted(
            key for key in ANOMALY_FACT_KEYS if key != "oi_change"))

    def test_oi_change_is_omitted_entirely_when_yesterday_is_null(self):
        self.seed([_spec("CCF", "2303", oi={_DAYS[-2]: None})])
        self.assertNotIn("oi_change", self.contracts("2303")["CCF"]["anomaly"])

    def test_an_omitted_oi_change_is_never_written_as_zero_or_null(self):
        self.seed([_spec("CCF", "2303", oi={AD: None})])
        self.contracts("2303")
        raw = (self.out / "stocks" / "2303.json").read_text(encoding="utf-8")
        self.assertNotIn('"oi_change"', raw)


class AnomalyTextTests(_AnomalyFixture):
    """§4 步驟 5 的兩段範本,逐字。"""

    def test_the_trigger_reason_is_the_pre_registered_template(self):
        self.seed([_spec("CCF", "2303")])
        reasons = self.contracts("2303")["CCF"]["reasons"]
        self.assertEqual(reasons, [{"code": REASON_CODE, "text": EXPECTED_REASON}])

    def test_the_risk_line_is_the_pre_registered_template(self):
        self.seed([_spec("CCF", "2303")])
        risks = self.contracts("2303")["CCF"]["risks"]
        self.assertEqual(risks, [{"code": RISK_CODE, "text": EXPECTED_RISK}])

    def test_the_risk_line_says_the_spot_did_make_its_own_new_high(self):
        self.seed([_spec("CCF", "2303")])
        with db.get_engine().begin() as conn:
            conn.execute(schema.daily_prices.update().where(
                (schema.daily_prices.c.stock_id == "2303")
                & (schema.daily_prices.c.date == AD)
            ).values(volume=SPOT_SHARES * 5))
        self.assertEqual(
            self.contracts("2303")["CCF"]["risks"][0]["text"],
            "量創高不代表方向;結算週已排除;盤後未計;現貨當日有同步創高。",
        )

    def test_the_reason_drops_the_oi_clause_when_oi_change_is_omitted(self):
        self.seed([_spec("CCF", "2303", oi={AD: None})])
        self.assertEqual(
            self.contracts("2303")["CCF"]["reasons"][0]["text"],
            "CCF 期貨一般時段成交 500 口,創 60 個比較日新高"
            "(前高 100 口、中位數 100 口)。",
        )

    def test_a_contract_without_an_anomaly_carries_no_reason_or_risk(self):
        self.seed([_spec("CCF", "2303", today=BASE_LOTS)])
        contract = self.contracts("2303")["CCF"]
        self.assertNotIn("reasons", contract)
        self.assertNotIn("risks", contract)


class AnomalyRateGateTests(_AnomalyFixture):
    """新的切片也要過 `test_payload_cannot_silently_gain_a_rate` 的同一把閘門。"""

    def test_the_anomaly_block_cannot_silently_gain_a_rate(self):
        self.seed([_spec("CCF", "2303")])
        self.contracts("2303")
        offenders = []

        def walk(node, path):
            if isinstance(node, dict):
                for key, value in node.items():
                    if any(bad in key.lower() for bad in RATIO_ISH):
                        offenders.append(f"{path}.{key}")
                    walk(value, f"{path}.{key}")
            elif isinstance(node, list):
                for i, value in enumerate(node):
                    walk(value, f"{path}[{i}]")

        payload = json.loads(
            (self.out / "stocks" / "2303.json").read_text(encoding="utf-8"))
        walk(payload["futures"], "2303.futures")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
