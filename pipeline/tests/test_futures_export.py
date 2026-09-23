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
from radar.compute.futures_volume_anomaly import (
    REASON_CODE,
    RISK_CODE,
    futures_volume_anomalies,
)
from radar.compute.futures_volume_battery import (
    ANOMALY_FACT_KEYS,
    WINDOW_DAYS,
    anomaly_facts,
    evaluate_contract_day,
)
from radar.compute.settlement_calendar import settlement_exclusion_set
from radar.export.json_export import export_json

D = "2026-09-15"      # 現貨價格日 = export 日
P = "2026-09-14"      # 前一個現貨交易日
# 期貨行情日 = **前一個交易日**,這是 production 的常態形狀(docs/38 §7.12):
# 餵源只給最新一份完整報告,而 21:20 那一輪最新的完整報告是前一天的。
# 這份 fixture 以前讓期貨與現貨同一天,於是整份綠色的測試放行了一個
# 「只有在現貨匯入失敗那天才顯示得出來」的功能。默認形狀從此是落後一天。
F = P
OLDER = "2026-09-10"        # 更早的期貨日:用來造「這個契約當天沒有列」
LIST_AS_OF = "2026-09-11"   # 清單刷新日,刻意早於價格日

RATIO_ISH = ("ratio", "avg", "mean", "rank", "score", "z")


def _contract(code, stock_id, *, last_seen=LIST_AS_OF, future=1, option=0, weekly=0):
    return {
        "contract_code": code, "stock_id": stock_id, "stock_name": "x",
        "is_stock_future": future, "is_stock_option": option,
        "is_weekly_option": weekly, "market": "twse",
        "first_seen": "2026-01-02", "last_seen": last_seen,
    }


def _daily(code, month, session, volume, oi, date=F):
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
    def test_daily_omitted_when_the_contract_has_no_row_on_the_futures_date(self):
        """期貨行情日由**整張表**的最後一天決定;個別契約那天沒有列就整個 daily 省略。"""
        self._seed_futures(
            [_contract("CCF", "2303"), _contract("MYF", "1565")],
            [
                _daily("CCF", "202609", "一般", 500, 900),
                _daily("MYF", "202609", "一般", 300, 400, date=OLDER),
            ],
        )
        export_json(self.out)
        self.assertIn("daily", self._stock("2303")["futures"]["contracts"][0])
        self.assertNotIn("daily", self._stock("1565")["futures"]["contracts"][0])

    def test_the_block_is_anchored_on_the_futures_date_not_the_price_date(self):
        """§7.12:切片的日期是期貨行情日。錨在現貨日的話這裡整個 daily 都不存在。"""
        self._seed_futures(
            [_contract("CCF", "2303")],
            [_daily("CCF", "202609", "一般", 500, 900)],
        )
        futures = self._stock("2303")["futures"]
        self.assertEqual(futures["daily_as_of"], F)
        self.assertNotEqual(futures["daily_as_of"], D)
        self.assertEqual(futures["contracts"][0]["daily"]["date"], F)

    def test_daily_as_of_and_daily_date_are_locked_together(self):
        """兩個日期一個來源:``daily.date`` 與 ``daily_as_of`` 不得各自漂移。"""
        self._seed_futures(
            [_contract("CCF", "2303")],
            [_daily("CCF", "202609", "一般", 500, 900)],
        )
        futures = self._stock("2303")["futures"]
        self.assertEqual(futures["contracts"][0]["daily"]["date"],
                         futures["daily_as_of"])

    def test_daily_as_of_is_absent_when_there_is_no_futures_day_at_all(self):
        """一列行情都沒有 = 沒有行情日。缺鍵,不是 null——null 是「未知的那一天」。"""
        self._seed_futures([_contract("CCF", "2303")])
        futures = self._stock("2303")["futures"]
        self.assertNotIn("daily_as_of", futures)
        raw = (self.out / "stocks" / "2303.json").read_text(encoding="utf-8")
        self.assertNotIn("daily_as_of", raw)

    def test_daily_as_of_is_not_the_list_refresh_date(self):
        """行情日與清單刷新日是兩件事,所以這個鍵不叫裸的 as_of。"""
        self._seed_futures(
            [_contract("CCF", "2303")],
            [_daily("CCF", "202609", "一般", 500, 900)],
        )
        futures = self._stock("2303")["futures"]
        self.assertEqual(futures["list_as_of"], LIST_AS_OF)
        self.assertEqual(futures["daily_as_of"], F)
        self.assertNotEqual(futures["list_as_of"], futures["daily_as_of"])

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
        self.assertEqual(daily["date"], F)
        self.assertEqual(daily["volume"], 640)
        self.assertEqual(daily["open_interest"], 1000)
        self.assertEqual(daily["session_volume"], {"一般": 600, "盤後": 40})

    def test_session_volume_only_lists_sessions_that_actually_have_rows(self):
        """缺時段是例外(21:20 拿到的那份前一日報告兩個時段都在),但缺了就是缺了:
        寫 盤後: 0 會把「這份報告沒有這個時段」謊報成「盤後沒人交易」。"""
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

    def test_daily_carries_no_oi_change_when_there_is_only_one_futures_day(self):
        """「前一個期貨交易日」不存在 → 沒有差值可算,整個鍵省略(不是 0)。"""
        self._seed_futures(
            [_contract("CCF", "2303")],
            [_daily("CCF", "202609", "一般", 500, 900)],
        )
        daily = self._stock("2303")["futures"]["contracts"][0]["daily"]
        self.assertNotIn("oi_change", daily)

    # ── freshness ──────────────────────────────────────────────
    def test_the_normal_one_day_lag_is_not_stale(self):
        """落後一個交易日是**常態**,不是舊資料(§7.12)。

        以前這裡拿 ``d`` 去比,``stale`` 於是天天為真,首頁天天承諾
        「個股期貨資料尚未更新,稍後自動補齊」——而這條管線補不了:餵源沒有
        日期參數,漏掉的那天只能跑 backfill-futures。
        """
        self._seed_futures(
            [_contract("CCF", "2303")],
            [_daily("CCF", "202609", "一般", 500, 900)],
        )
        export_json(self.out)
        payload = json.loads((self.out / "radar.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["freshness"]["futures"], {"date": F, "stale": False})
        self.assertNotIn("個股期貨", "".join(payload["summary_text"]))

    def test_falling_behind_the_previous_trading_day_is_stale(self):
        self._seed_futures(
            [_contract("CCF", "2303")],
            [_daily("CCF", "202609", "一般", 500, 900, date=OLDER)],
        )
        export_json(self.out)
        payload = json.loads((self.out / "radar.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["freshness"]["futures"],
                         {"date": OLDER, "stale": True})

    def test_a_stale_futures_day_is_kept_out_of_the_auto_backfill_sentence(self):
        """那句話承諾「稍後自動補齊」,而期貨補不了——所以它不在那句話裡。"""
        self._seed_futures(
            [_contract("CCF", "2303")],
            [_daily("CCF", "202609", "一般", 500, 900, date=OLDER)],
        )
        export_json(self.out)
        payload = json.loads((self.out / "radar.json").read_text(encoding="utf-8"))
        joined = "".join(payload["summary_text"])
        self.assertNotIn("個股期貨", joined)
        self.assertNotIn("futures", joined)

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
AD = _DAYS[-1]                      # 2026-06-19,**期貨**行情日(非排除日)
# 現貨比期貨多一個交易日——這是 production 的常態形狀(docs/38 §7.12),而且是
# 這份 fixture 唯一最重要的一行。以前兩邊最後一天相同,於是整份綠色的測試放行了
# 一個結構上不可能顯示的功能:export 拿現貨日去問期貨,而那一天永遠沒有期貨列。
SPOT_AHEAD = _weekdays(date(2026, 6, 20), 1)[0]     # 2026-06-22(週一)= export 日
_SPOT_DAYS = _DAYS + [SPOT_AHEAD]
_JUNE_SETTLEMENT = "2026-06-17"     # 六月結算日,在候選日的比較窗口之內
_EXCLUDED = settlement_exclusion_set(
    date_from=_DAYS[0], date_to=AD, market_days=_SPOT_DAYS,
)


def _spot_days(days: list[str]) -> list[str]:
    """期貨日曆 → 現貨日曆:多一個交易日。"""
    tail = date.fromisoformat(days[-1]) + timedelta(days=1)
    return days + _weekdays(tail, 1)

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


# 「一列期貨行情都沒有」= 真正的「沒有算過」。**不是**「期貨落後 export 日」,
# 那個是 production 的常態形狀(§7.12)。
_NO_FUTURES_ROWS = {day: None for day in _DAYS}


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

    def seed(self, specs, *, days=None, spot_missing=(), spot_ahead=True):
        """``spot_missing`` = {(stock_id, date)},用來戳出 R2b 的現貨缺口。

        ``spot_ahead`` 預設為真:現貨比期貨多一個交易日,這是 production 的形狀。
        關掉它是為了測「現貨也停在同一天」那個**例外**(現貨匯入失敗的那一天),
        不是為了方便——預設不可以是那個例外。
        """
        days = _DAYS if days is None else days
        price_days = _spot_days(days) if spot_ahead else list(days)
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
                for sid in stock_ids for day in price_days
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
            if rows:        # 一列都沒有 = 這份 fixture 根本沒有期貨行情日
                conn.execute(schema.futures_daily.insert(), rows)

    def contracts(self, sid):
        export_json(self.out)
        payload = json.loads(
            (self.out / "stocks" / f"{sid}.json").read_text(encoding="utf-8"))
        return {c["code"]: c for c in payload["futures"]["contracts"]}

    def radar(self):
        export_json(self.out)
        return json.loads((self.out / "radar.json").read_text(encoding="utf-8"))


class AnomalyFixtureSanityTests(unittest.TestCase):
    """手算出來的日曆事實。這些若不成立,底下每個測試都在驗錯的東西。"""

    def test_the_candidate_day_is_not_itself_a_settlement_window_day(self):
        self.assertNotIn(AD, _EXCLUDED)

    def test_june_settlement_day_is_excluded_and_sits_inside_the_window(self):
        self.assertIn(_JUNE_SETTLEMENT, _EXCLUDED)
        self.assertLess(_JUNE_SETTLEMENT, AD)

    def test_the_default_shape_is_spot_one_trading_day_ahead_of_futures(self):
        """這份 fixture 的形狀本身就是一條被守住的事實(§7.12)。

        兩邊最後一天相同時,整個切片只有在現貨匯入失敗那一天才顯示得出來,
        而那正是上線後從未顯示過的原因。預設形狀退回去,這裡就是紅的。
        """
        self.assertEqual(_SPOT_DAYS[-1], SPOT_AHEAD)
        self.assertNotEqual(_SPOT_DAYS[-1], AD)
        self.assertEqual(_SPOT_DAYS[:-1], _DAYS)
        self.assertEqual(_spot_days(_DAYS), _SPOT_DAYS)


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

    def test_a_contract_with_no_regular_row_that_day_makes_no_claim(self):
        """行情日由**整張表**決定(MYF 撐著 AD),CCF 那天沒有列就什麼都不主張。"""
        self.seed([_spec("CCF", "2303", lots={AD: None}), _spec("MYF", "1565")])
        contract = self.contracts("2303")["CCF"]
        self.assertNotIn("anomaly", contract)
        self.assertNotIn("daily", contract)
        self.assertIn("daily", self.contracts("1565")["MYF"])   # 對照組


class AnomalyDateAnchorTests(_AnomalyFixture):
    """整個 futures 切片錨在**期貨行情日**,而不是 export 日(docs/38 §7.12)。

    這一組測試是這個 bug 的正身。production 的形狀永遠是「現貨比期貨新一天」,
    而 export 拿現貨日去問期貨:``contracts[].daily`` 的 ``WHERE date = :d`` 撈不到
    任何一列,``futures_volume_anomalies`` 的 ``futures_days[-1] != as_of`` 一律
    回傳「沒有算過」。市場層級的鍵因此**從未**出現過,而閘門唯一會放行的日子是
    現貨匯入失敗的那一天。整份測試是綠的,因為 fixture 讓兩邊同一天。
    """

    def test_the_market_key_exists_under_the_production_shape(self):
        self.seed([_spec("CCF", "2303")])
        radar = self.radar()
        self.assertNotEqual(radar["data_date"], AD)     # 現貨真的比期貨新一天
        self.assertIn(INDEX_KEY, radar)
        self.assertEqual([e["code"] for e in radar[INDEX_KEY]], ["CCF"])

    def test_the_meta_date_is_the_futures_day_not_the_data_date(self):
        self.seed([_spec("CCF", "2303")])
        radar = self.radar()
        self.assertEqual(radar[META_KEY]["as_of"], AD)
        self.assertNotEqual(radar[META_KEY]["as_of"], radar["data_date"])

    def test_the_meta_date_and_the_freshness_date_are_one_variable(self):
        """同一個 f_date 餵兩個地方。分成兩個來源,這個等號就是第一個會斷的。"""
        self.seed([_spec("CCF", "2303")])
        radar = self.radar()
        self.assertEqual(radar[META_KEY]["as_of"], radar["freshness"]["futures"]["date"])

    def test_the_per_stock_daily_is_populated_under_the_production_shape(self):
        """``contracts[].daily`` 也從來沒有被填過——沒有 UI 讀它,所以沒有症狀。"""
        self.seed([_spec("CCF", "2303")])
        contract = self.contracts("2303")["CCF"]
        self.assertEqual(contract["daily"]["date"], AD)
        self.assertEqual(contract["daily"]["volume"], SPIKE_LOTS + 999_999)
        self.assertEqual(contract["daily"]["session_volume"],
                         {"一般": SPIKE_LOTS, "盤後": 999_999})

    def test_daily_as_of_is_present_and_equals_the_daily_date(self):
        self.seed([_spec("CCF", "2303")])
        export_json(self.out)
        futures = json.loads(
            (self.out / "stocks" / "2303.json").read_text(encoding="utf-8"))["futures"]
        self.assertEqual(futures["daily_as_of"], AD)
        self.assertEqual(futures["contracts"][0]["daily"]["date"],
                         futures["daily_as_of"])

    def test_a_stock_with_no_daily_row_still_carries_the_futures_day(self):
        """日期是**明講的**,不是從 daily 推出來的:沒有 daily 的股票也答得出來。"""
        self.seed([_spec("CCF", "2303"), _spec("MYF", "1565", lots={AD: None})])
        export_json(self.out)
        futures = json.loads(
            (self.out / "stocks" / "1565.json").read_text(encoding="utf-8"))["futures"]
        self.assertNotIn("daily", futures["contracts"][0])
        self.assertEqual(futures["daily_as_of"], AD)

    def test_the_slice_still_works_when_spot_import_failed_and_dates_match(self):
        """現貨也停在同一天(現貨匯入失敗)時照樣算——修的是錨點,不是換一個錯。"""
        self.seed([_spec("CCF", "2303")], spot_ahead=False)
        radar = self.radar()
        self.assertEqual(radar["data_date"], AD)
        self.assertEqual(radar[META_KEY]["as_of"], AD)
        self.assertEqual([e["code"] for e in radar[INDEX_KEY]], ["CCF"])
        # 期貨反而追上現貨當然不是「舊」。stale 的意思是「連前一個交易日都沒
        # 跟上」,不是「不等於前一個交易日」(§7.12)。
        self.assertEqual(radar["freshness"]["futures"], {"date": AD, "stale": False})


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


class DailyOpenInterestChangeTests(_AnomalyFixture):
    """``daily.oi_change``:**每一個**契約-日都給,不只舉旗的那些(docs/38 §7.14)。

    部位是在建還是在減,是這個切片唯一講得出方向的事實,而它與旗標無關——
    一天約 320 個契約有 ``daily``,其中舉旗的通常只有個位數。
    """

    def test_a_normal_unflagged_contract_day_still_carries_oi_change(self):
        """沒有創高 = 沒有 anomaly 區塊,但未平倉的日變化照樣是一個事實。"""
        self.seed([_spec("CCF", "2303", today=BASE_LOTS)])
        contract = self.contracts("2303")["CCF"]
        self.assertNotIn("anomaly", contract)       # 真的沒舉旗
        self.assertEqual(contract["daily"]["oi_change"], TODAY_OI - BASE_OI)

    def test_a_flagged_contract_has_one_number_in_two_places_not_two_numbers(self):
        """舉旗時 ``daily.oi_change`` 與 ``anomaly.oi_change`` 必須逐字相同。

        兩個同名的數字並排顯示,任何一邊自己再算一次就是兩個會漂走的真相。
        """
        self.seed([_spec("CCF", "2303")])
        contract = self.contracts("2303")["CCF"]
        self.assertEqual(contract["daily"]["oi_change"],
                         contract["anomaly"]["oi_change"])

    def test_oi_change_is_omitted_entirely_when_today_is_null(self):
        self.seed([_spec("CCF", "2303", oi={AD: None})])
        daily = self.contracts("2303")["CCF"]["daily"]
        self.assertNotIn("oi_change", daily)
        self.assertIsNone(daily["open_interest"])

    def test_oi_change_is_omitted_entirely_when_the_previous_day_is_null(self):
        self.seed([_spec("CCF", "2303", oi={_DAYS[-2]: None})])
        self.assertNotIn("oi_change", self.contracts("2303")["CCF"]["daily"])

    def test_an_omitted_oi_change_is_never_written_as_zero_or_null(self):
        """缺值與 0 在畫面上長得一樣,只靠「那一列在不在」分辨(§7.1)。"""
        self.seed([_spec("CCF", "2303", oi={AD: None}, today=BASE_LOTS)])
        self.contracts("2303")
        raw = (self.out / "stocks" / "2303.json").read_text(encoding="utf-8")
        self.assertNotIn('"oi_change"', raw)

    def test_a_real_zero_is_written_as_zero(self):
        """未平倉一口都沒變是一個**觀測**,不是缺值——它必須是 0,不是缺鍵。"""
        self.seed([_spec("CCF", "2303", oi={AD: BASE_OI}, today=BASE_LOTS)])
        daily = self.contracts("2303")["CCF"]["daily"]
        self.assertEqual(daily["oi_change"], 0)
        raw = (self.out / "stocks" / "2303.json").read_text(encoding="utf-8")
        self.assertIn('"oi_change": 0', raw)

    def test_the_previous_day_comes_from_the_shared_oi_change_function(self):
        """不是第二次實作的「前一個期貨交易日」,是 battery 那一個函式本人。"""
        from radar.compute import futures_volume_battery
        from radar.export import json_export
        self.assertIs(json_export.oi_change, futures_volume_battery.oi_change)

        self.seed([_spec("CCF", "2303", today=BASE_LOTS)])
        with patch("radar.export.json_export.oi_change", lambda *a, **k: 7_777):
            daily = self.contracts("2303")["CCF"]["daily"]
        self.assertEqual(daily["oi_change"], 7_777)

    def test_the_previous_day_skips_calendar_gaps_instead_of_counting_back_one_date(self):
        """前一個**期貨交易日**不是前一個日曆日:週末與停市日都要跳過。

        AD 是週五(2026-06-19),前一個期貨交易日是週四;若有人用日期減一天,
        這裡拿到的會是缺值而不是 210。
        """
        self.assertEqual(date.fromisoformat(AD).weekday(), 4)
        self.seed([_spec("CCF", "2303", today=BASE_LOTS)])
        self.assertEqual(self.contracts("2303")["CCF"]["daily"]["oi_change"], 210)

    def test_the_after_hours_session_does_not_reach_the_open_interest_change(self):
        """§1 的口徑是一般時段。這份 fixture 反事實地給盤後列一個未平倉數字
        (來源實際上永遠是 '-' → NULL),差值必須一動也不動。"""
        self.seed([_spec("CCF", "2303", today=BASE_LOTS)])
        self._give_the_after_hours_rows_an_open_interest()
        daily = self.contracts("2303")["CCF"]["daily"]
        self.assertEqual(daily["oi_change"], TODAY_OI - BASE_OI)

    def _give_the_after_hours_rows_an_open_interest(self):
        """反事實:來源哪天不再對盤後未平倉給 '-'。今天給的一律是 NULL。"""
        with db.get_engine().begin() as conn:
            conn.execute(schema.futures_daily.update().where(
                (schema.futures_daily.c.contract_code == "CCF")
                & (schema.futures_daily.c.session == "盤後")
            ).values(open_interest=500_000))

    def test_the_after_hours_session_does_not_reach_the_open_interest_level(self):
        """未平倉的**水位**也只讀一般時段(docs/38 §7.15)。

        這一條與上面那一條是同一個口徑的兩半,而在今天的資料上兩種寫法答案相同:
        來源對盤後未平倉一律給 '-'(NULL),所以「跨時段相加」恰好等於「只取一般
        時段」。恰好相同不是一個理由——未平倉是**存量不是流量**,同一天兩個時段的
        水位相加沒有意義。來源哪天開始給盤後未平倉,相加的寫法就會無聲地翻倍,而
        ``oi_change``(本來就只讀一般時段)仍然是對的,同一張卡片上的兩個數字會
        互相矛盾。這個測試就是那一天:它反事實地給盤後列一個未平倉,水位必須一動
        也不動。回到相加,這裡會是 501,210。
        """
        self.seed([_spec("CCF", "2303", today=BASE_LOTS)])
        self._give_the_after_hours_rows_an_open_interest()
        daily = self.contracts("2303")["CCF"]["daily"]
        self.assertEqual(daily["open_interest"], TODAY_OI)
        # 而且水位與日變化仍然是同一個口徑的兩半,不會一個動一個不動。
        self.assertEqual(daily["oi_change"], TODAY_OI - BASE_OI)

    def test_the_level_and_the_change_read_the_same_session(self):
        """兩者同一句 SQL:把一般時段的未平倉抽掉,兩個鍵必須一起消失。

        只有水位跨時段相加的寫法會在這裡留下一個 500,000 的水位配上一個缺席的
        日變化——一個講得出位階、卻講不出位階從哪來的契約。
        """
        self.seed([_spec("CCF", "2303", today=BASE_LOTS)])
        self._give_the_after_hours_rows_an_open_interest()
        with db.get_engine().begin() as conn:
            conn.execute(schema.futures_daily.update().where(
                (schema.futures_daily.c.contract_code == "CCF")
                & (schema.futures_daily.c.session == "一般")
            ).values(open_interest=None))
        daily = self.contracts("2303")["CCF"]["daily"]
        self.assertIsNone(daily["open_interest"])
        self.assertNotIn("oi_change", daily)


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


INDEX_KEY = "futures_volume_anomalies"
META_KEY = "futures_volume_anomalies_meta"

# 名次的各種寫法。§5 不做跨契約排序,所以名單有**順序**沒有**名次**:任何一個
# 這樣的鍵出現在條目裡,都等於偷偷把一份短名單變成一張排行榜。
RANK_ISH = ("rank", "position", "order", "seq", "index", "score", "top", "place")


class AnomalyMarketIndexTests(_AnomalyFixture):
    """市場層級的今日名單(docs/38 §7.5)。§1「名單短到能逐檔看」要的就是這一份。"""

    def test_the_key_is_absent_when_there_is_no_futures_day_at_all(self):
        """一天期貨行情都沒有 → 沒有算過。沒有算過就不該有任何主張。

        (以前這一條寫的是「期貨落後 export 日」,而那是 production 的**常態**,
        不是「沒有算過」——那個誤解就是這個功能從未顯示過的原因,見 §7.12。)
        """
        self.seed([_spec("CCF", "2303", lots=_NO_FUTURES_ROWS)])
        self.assertNotIn(INDEX_KEY, self.radar())

    def test_an_uncomputed_day_is_not_written_as_an_empty_list(self):
        """塌成 [] 就等於把「不知道」講成「今天沒有異常」——正是三態要擋的那件事。"""
        self.seed([_spec("CCF", "2303", lots=_NO_FUTURES_ROWS)])
        self.radar()
        raw = (self.out / "radar.json").read_text(encoding="utf-8")
        self.assertNotIn(f'"{INDEX_KEY}"', raw)

    def test_an_undecidable_settlement_window_makes_no_claim_at_all(self):
        """R4 邊緣:算不出排除窗口時**不主張**,絕不當成「沒有被排除」(§7.13)。

        候選日 06-15 的下一個結算日是 06-17,但日曆只到 06-16,``settlement_date``
        因此回 ``None``,而舊的 ``settlement_exclusion_days`` 把那個 ``None`` 變成
        一個空清單——與「這個月沒有排除日」看起來一模一樣。battery 帶著事後日曆
        跑,那個塌陷永遠不會發生;export 永遠坐在尾巴上,它會發生,方向是把該
        排除的日子放上榜。這裡的 CCF 在舊行為下會舉旗(它有尖峰、歷史也夠)。
        """
        days = _DAYS[:_DAYS.index("2026-06-15") + 1]
        # 帶著完整日曆,這一天**是**排除日(所以正確答案是「不上榜」);
        # 而這個 fixture 的日曆停在 06-16,答不出來。
        self.assertIn(days[-1], _EXCLUDED)
        self.seed([_spec("CCF", "2303", days=days)], days=days)
        radar = self.radar()
        self.assertNotIn(INDEX_KEY, radar)
        self.assertNotIn(META_KEY, radar)
        contract = self.contracts("2303")["CCF"]
        self.assertNotIn("anomaly", contract)
        # 但 daily 與行情日照舊:那兩個不是 R4 的主張,不受連坐。
        self.assertEqual(contract["daily"]["date"], days[-1])

    def test_the_market_day_calendar_uses_the_spot_date_not_the_futures_date(self):
        """R4 的日曆讀到**現貨**日,白拿現貨已經有的那一天先見之明(§7.13)。

        期貨停在 06-16、現貨已經到 06-17(= 六月結算日):讀現貨日答得出來
        ——06-16 在排除窗口裡,所以是「算過了、沒有人舉旗」;只讀期貨日就答
        不出來,整個鍵消失。兩者差的就是那一天。
        """
        days = _DAYS[:_DAYS.index("2026-06-16") + 1]
        self.assertEqual(_spot_days(days)[-1], _JUNE_SETTLEMENT)
        self.seed([_spec("CCF", "2303", days=days)], days=days)
        self.assertEqual(self.radar()[INDEX_KEY], [])

    def test_the_same_candidate_does_claim_once_the_calendar_reaches_the_settlement(self):
        """對照組:日曆長到蓋住結算日,同一個候選日就答得出來了——而答案是排除。"""
        days = _DAYS[:_DAYS.index("2026-06-15") + 1]
        self.seed([_spec("CCF", "2303", days=days)],
                  days=_DAYS[:_DAYS.index(_JUNE_SETTLEMENT) + 1], spot_ahead=False)
        radar = self.radar()
        self.assertEqual(radar[INDEX_KEY], [])      # 算過了:R4 排除,沒有人舉旗

    def test_a_computed_day_with_nothing_flagged_is_an_empty_list(self):
        """算過了、今天沒有契約舉旗:這是一個有日期的正面主張,不是沒有鍵。"""
        self.seed([_spec("CCF", "2303", today=BASE_LOTS)])
        radar = self.radar()
        self.assertIn(INDEX_KEY, radar)
        self.assertEqual(radar[INDEX_KEY], [])

    def test_a_flagged_contract_is_one_entry_with_the_five_fields(self):
        self.seed([_spec("CCF", "2303")])
        entries = self.radar()[INDEX_KEY]
        self.assertEqual(len(entries), 1)
        self.assertEqual(sorted(entries[0]),
                         ["anomaly", "code", "reasons", "risks", "stock_id"])
        self.assertEqual(entries[0]["stock_id"], "2303")
        self.assertEqual(entries[0]["code"], "CCF")

    def test_the_entries_reuse_the_per_stock_structures_verbatim(self):
        """條目不是攤平的變體:同一份 anomaly / reasons / risks,逐字相同。"""
        self.seed([_spec("CCF", "2303")])
        entry = self.radar()[INDEX_KEY][0]
        contract = self.contracts("2303")["CCF"]
        self.assertEqual(entry["anomaly"], contract["anomaly"])
        self.assertEqual(entry["reasons"], contract["reasons"])
        self.assertEqual(entry["risks"], contract["risks"])
        self.assertEqual(entry["anomaly"], EXPECTED_FACTS)
        self.assertEqual(entry["reasons"],
                         [{"code": REASON_CODE, "text": EXPECTED_REASON}])
        self.assertEqual(entry["risks"], [{"code": RISK_CODE, "text": EXPECTED_RISK}])

    def test_the_order_is_today_minus_window_max_descending(self):
        # window_max 三個都是 100,所以差額就是 today − 100:400 / 200 / 200。
        self.seed([
            _spec("AAA", "2303", today=300),
            _spec("BBB", "1565", today=500),
            _spec("CCC", "2317", today=300),
        ])
        entries = self.radar()[INDEX_KEY]
        self.assertEqual([e["code"] for e in entries], ["BBB", "AAA", "CCC"])
        self.assertEqual(
            [e["anomaly"]["today"] - e["anomaly"]["window_max"] for e in entries],
            [400, 200, 200],
        )

    def test_ties_are_broken_by_code_ascending_so_the_file_is_deterministic(self):
        """AAA 與 CCC 差額相同;若不用 code 收尾,檔案就會隨 dict 順序飄。"""
        self.seed([
            _spec("CCC", "2317", today=300),
            _spec("AAA", "2303", today=300),
        ])
        self.assertEqual([e["code"] for e in self.radar()[INDEX_KEY]], ["AAA", "CCC"])

    def test_the_entries_carry_no_rank_or_position_key(self):
        """§5:不做跨契約排序。順序可以有,名次不可以有。"""
        self.seed([_spec("AAA", "2303"), _spec("BBB", "1565")])
        offenders = []
        for entry in self.radar()[INDEX_KEY]:
            for key in entry:
                if any(bad in key.lower() for bad in RANK_ISH):
                    offenders.append(key)
            # 而且鍵就是那五個,一個不多:第六個鍵要加,得自己動手並過 review。
            self.assertEqual(sorted(entry),
                             ["anomaly", "code", "reasons", "risks", "stock_id"])
        self.assertEqual(offenders, [])

    def test_the_index_cannot_silently_gain_a_rate(self):
        self.seed([_spec("CCF", "2303")])
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

        walk(self.radar()[INDEX_KEY], INDEX_KEY)
        self.assertEqual(offenders, [])

    def test_two_contracts_on_one_stock_both_appear(self):
        """1565 的 MYF(2,000 股/口)與 OMF(100 股/口)可以同一天都舉旗。

        單位是契約不是股票;依股票去重會把其中一個吞掉。
        """
        self.seed([_spec("MYF", "1565"), _spec("OMF", "1565", multiplier=100)])
        entries = self.radar()[INDEX_KEY]
        self.assertEqual([(e["stock_id"], e["code"]) for e in entries],
                         [("1565", "MYF"), ("1565", "OMF")])

    def test_a_refused_contract_never_reaches_the_index(self):
        """否決 = 不是一個異常,市場名單與個股區塊在這件事上必須一致。"""
        self.seed([_spec("CCF", "2303", multiplier=None), _spec("MYF", "1565")])
        self.assertEqual([e["code"] for e in self.radar()[INDEX_KEY]], ["MYF"])

    def test_the_index_and_the_per_stock_blocks_come_from_one_computation(self):
        """整個 export 只呼叫規則一次。有人加第二趟,這裡就是紅的。"""
        self.seed([_spec("CCF", "2303"), _spec("MYF", "1565")])
        calls = []

        def counting(conn, as_of, **kwargs):
            calls.append(as_of)
            return futures_volume_anomalies(conn, as_of, **kwargs)

        with patch("radar.export.json_export.futures_volume_anomalies", counting):
            export_json(self.out)
        self.assertEqual(len(calls), 1, f"rule evaluated {len(calls)} times")
        radar = json.loads((self.out / "radar.json").read_text(encoding="utf-8"))
        by_code = {}
        for sid in ("2303", "1565"):
            payload = json.loads(
                (self.out / "stocks" / f"{sid}.json").read_text(encoding="utf-8"))
            by_code.update({c["code"]: c for c in payload["futures"]["contracts"]})
        for entry in radar[INDEX_KEY]:
            self.assertEqual(entry["anomaly"], by_code[entry["code"]]["anomaly"])
            self.assertEqual(entry["reasons"], by_code[entry["code"]]["reasons"])
            self.assertEqual(entry["risks"], by_code[entry["code"]]["risks"])


class AnomalyIndexMetaTests(_AnomalyFixture):
    """名單的隨附事實 ``futures_volume_anomalies_meta``(docs/38 §7.11)。

    它存在的唯一理由是 §7.5 的**空陣列**那一態:那一態裡一個 ``anomaly`` 區塊都
    沒有,而 §7.10 不准 UI 寫死 60。所以「今天沒有契約創 60 個比較日新高」這句話
    只能靠這個鍵才講得出來。
    """

    def test_the_meta_key_is_absent_when_the_day_was_never_computed(self):
        """沒有名單就沒有 meta:一個沒有名單的孤兒 window_days 不主張任何事。"""
        self.seed([_spec("CCF", "2303", lots=_NO_FUTURES_ROWS)])
        radar = self.radar()
        self.assertNotIn(INDEX_KEY, radar)
        self.assertNotIn(META_KEY, radar)
        raw = (self.out / "radar.json").read_text(encoding="utf-8")
        self.assertNotIn(META_KEY, raw)

    def test_a_computed_day_with_nothing_flagged_still_carries_the_window(self):
        """空名單那一態:名單是 [],但比較窗口與**是哪一天**仍然講得出來。"""
        self.seed([_spec("CCF", "2303", today=BASE_LOTS)])
        radar = self.radar()
        self.assertEqual(radar[INDEX_KEY], [])
        self.assertEqual(radar[META_KEY], {"as_of": AD, "window_days": WINDOW_DAYS})

    def test_a_flagged_day_carries_the_same_window_as_every_entry(self):
        self.seed([_spec("CCF", "2303"), _spec("MYF", "1565")])
        radar = self.radar()
        self.assertEqual(radar[META_KEY], {"as_of": AD, "window_days": WINDOW_DAYS})
        for entry in radar[INDEX_KEY]:
            self.assertEqual(entry["anomaly"]["window_days"], radar[META_KEY]["window_days"])

    def test_the_window_comes_from_the_rules_constant_not_a_second_literal(self):
        """把常數換掉,輸出必須跟著變。

        這裡不是在驗 60 是多少(§3.5 已經凍結了它,``test_futures_volume_battery``
        也鎖了),而是在驗這個鍵**沒有自己寫一個 60**。若有人在這裡打了字面值,
        底下的 7 就永遠拿不到,測試紅。
        """
        self.seed([_spec("CCF", "2303", today=BASE_LOTS)])
        with patch("radar.compute.futures_volume_anomaly.WINDOW_DAYS", 7):
            radar = self.radar()
        self.assertEqual(radar[META_KEY], {"as_of": AD, "window_days": 7})

    def test_the_meta_key_is_exactly_one_date_and_one_integer(self):
        """§5:名單有順序沒有名次。meta 也不是名次或評分的落腳處。"""
        self.seed([_spec("CCF", "2303")])
        meta = self.radar()[META_KEY]
        self.assertEqual(sorted(meta), ["as_of", "window_days"])
        self.assertIsInstance(meta["window_days"], int)
        self.assertNotIsInstance(meta["window_days"], bool)
        self.assertIsInstance(meta["as_of"], str)
        for bad in RANK_ISH + RATIO_ISH:
            for key in meta:
                self.assertNotIn(bad, key.lower())

    def test_meta_is_derived_from_the_index_so_it_cannot_appear_alone(self):
        from radar.compute.futures_volume_anomaly import anomaly_index_meta
        self.assertIsNone(anomaly_index_meta(None, as_of=AD))
        self.assertEqual(anomaly_index_meta([], as_of=AD),
                         {"as_of": AD, "window_days": WINDOW_DAYS})
        self.assertEqual(anomaly_index_meta([{"code": "CCF"}], as_of=AD),
                         {"as_of": AD, "window_days": WINDOW_DAYS})


DIRECTION_KEY = "futures_open_interest_direction"


class MarketOpenInterestDirectionTests(_AnomalyFixture):
    """市場層級的未平倉方向計數(docs/38 §7.15)。

    這個鍵**沒有**經過 §3 的 battery,而那不是疏漏:它是**描述性**的——它只說
    今天有幾個契約的未平倉比前一個期貨交易日高,沒有說那代表什麼、也沒有說今天
    算不算不尋常,所以沒有東西可以被否證,也就沒有東西需要被檢定。§1 的旗標相反,
    它主張「這個旗標告訴你一些事」,那是一個資訊性主張,所以 §3 先拿它去否證。
    豁免只在它保持描述性的時候成立,所以底下有幾個測試守的不是數字而是**形狀**:
    沒有門檻、沒有旗標、沒有比率、沒有淨額、沒有名次。
    """

    # ── 三態 ────────────────────────────────────────────────────
    def test_the_key_is_absent_when_there_is_no_futures_day_at_all(self):
        self.seed([_spec("CCF", "2303", lots=_NO_FUTURES_ROWS)])
        self.assertNotIn(DIRECTION_KEY, self.radar())

    def test_an_uncomputed_day_is_not_written_as_zeros(self):
        """「沒有算過」與「四個都是 0」是兩件事,不可以塌成同一種表示。"""
        self.seed([_spec("CCF", "2303", lots=_NO_FUTURES_ROWS)])
        self.radar()
        raw = (self.out / "radar.json").read_text(encoding="utf-8")
        self.assertNotIn(DIRECTION_KEY, raw)

    def test_a_computed_day_with_no_direction_at_all_still_carries_the_key(self):
        """唯一一個契約判不出方向:三個計數是 0,但**我們數過了**。

        這一態與上面那一態在畫面上講的是完全不同的兩句話,分辨它們的只有鍵在不在
        ——與 §7.1 的 ``oi_change`` 是同一個陷阱,換到市場層級再出現一次。
        """
        self.seed([_spec("CCF", "2303", oi={AD: None})])
        self.assertEqual(self.radar()[DIRECTION_KEY], {
            "as_of": AD, "increased": 0, "decreased": 0,
            "unchanged": 0, "undetermined": 1,
        })

    # ── 計數本身 ────────────────────────────────────────────────
    def test_the_counts_under_a_mixed_fixture(self):
        """五個契約、五種命運,手算:增 1 / 減 1 / 平 1 / 判不出 2。"""
        self.seed([
            _spec("AAA", "2303"),                               # +210
            _spec("BBB", "1565", oi={AD: BASE_OI - 50}),        # −50
            _spec("CCC", "2317", oi={AD: BASE_OI}),             # 0
            _spec("DDD", "2330", oi={AD: None}),                # 今天沒有數字
            _spec("EEE", "2454", lots={AD: None}),              # 今天根本沒有列
        ])
        self.assertEqual(self.radar()[DIRECTION_KEY], {
            "as_of": AD, "increased": 1, "decreased": 1,
            "unchanged": 1, "undetermined": 2,
        })

    def test_a_zero_change_is_unchanged_not_undetermined(self):
        """「一口都沒變」是一個觀測,「不知道」不是。兩者絕不同一格。"""
        self.seed([_spec("CCF", "2303", oi={AD: BASE_OI}),
                   _spec("MYF", "1565", oi={AD: None})])
        direction = self.radar()[DIRECTION_KEY]
        self.assertEqual(direction["unchanged"], 1)
        self.assertEqual(direction["undetermined"], 1)

    def test_undeterminable_contracts_are_counted_not_silently_dropped(self):
        """四個計數的和必須等於契約總數——判不出來的那些沒有從分母消失。

        丟掉它們會讓「今天 1 個契約增加」這句話讀起來像是一個近乎全體的事實,
        而實際上今天有 3 個契約根本沒有答案。判不出來的成因依 R1 有未掛牌 /
        未公布 / 匯入失敗三種,三者不可分辨,所以只數,不分類。
        """
        specs = [
            _spec("AAA", "2303"),
            _spec("BBB", "1565", oi={AD: None}),
            _spec("CCC", "2317", lots={AD: None}),
            _spec("DDD", "2330", oi={_DAYS[-2]: None}),         # 前一日沒有數字
        ]
        self.seed(specs)
        direction = self.radar()[DIRECTION_KEY]
        self.assertEqual(direction["undetermined"], 3)
        self.assertEqual(
            sum(direction[key] for key in
                ("increased", "decreased", "unchanged", "undetermined")),
            len(specs),
        )

    def test_a_contract_with_no_row_today_is_undetermined_not_unchanged(self):
        """沒有列 ≠ 沒有變動(R1)。那是「不知道」,不是「一口都沒變」。"""
        self.seed([_spec("CCF", "2303", lots={AD: None}), _spec("MYF", "1565")])
        direction = self.radar()[DIRECTION_KEY]
        self.assertEqual(direction["unchanged"], 0)
        self.assertEqual(direction["undetermined"], 1)

    def test_the_counts_agree_with_the_per_stock_numbers(self):
        """市場層級的方向與個股卡片上那個數字是同一次計算,不是第二次。"""
        self.seed([_spec("AAA", "2303"), _spec("BBB", "1565", oi={AD: BASE_OI - 50})])
        radar = self.radar()
        contracts = self.contracts("2303") | self.contracts("1565")
        self.assertEqual(contracts["AAA"]["daily"]["oi_change"], 210)
        self.assertEqual(contracts["BBB"]["daily"]["oi_change"], -50)
        self.assertEqual(radar[DIRECTION_KEY]["increased"], 1)
        self.assertEqual(radar[DIRECTION_KEY]["decreased"], 1)

    def test_the_direction_comes_from_the_shared_oi_change_function(self):
        """方向由 battery 的 :func:`oi_change` 本人決定,不是這裡重數一次昨天。"""
        self.seed([_spec("AAA", "2303"), _spec("BBB", "1565", oi={AD: BASE_OI - 50})])
        with patch("radar.export.json_export.oi_change", lambda *a, **k: -1):
            radar = self.radar()
        self.assertEqual(radar[DIRECTION_KEY]["decreased"], 2)
        self.assertEqual(radar[DIRECTION_KEY]["increased"], 0)

    def test_the_after_hours_session_does_not_reach_the_direction(self):
        """口徑與 ``oi_change`` 完全相同:一般時段。盤後給了數字也不動。"""
        self.seed([_spec("CCF", "2303", oi={AD: BASE_OI})])
        with db.get_engine().begin() as conn:
            conn.execute(schema.futures_daily.update().where(
                schema.futures_daily.c.session == "盤後"
            ).values(open_interest=500_000))
        self.assertEqual(self.radar()[DIRECTION_KEY]["unchanged"], 1)

    # ── 形狀(豁免 battery 的條件) ──────────────────────────────
    def test_the_date_is_the_futures_day_and_matches_the_other_two(self):
        self.seed([_spec("CCF", "2303")])
        radar = self.radar()
        self.assertEqual(radar[DIRECTION_KEY]["as_of"], AD)
        self.assertNotEqual(radar[DIRECTION_KEY]["as_of"], radar["data_date"])
        self.assertEqual(radar[DIRECTION_KEY]["as_of"],
                         radar["freshness"]["futures"]["date"])
        self.assertEqual(radar[DIRECTION_KEY]["as_of"], radar[META_KEY]["as_of"])

    def test_the_key_is_exactly_one_date_and_four_integers(self):
        """第五個計數、一個總數、一個比率、一個旗標——任何一個出現,這裡就紅。

        總數刻意不給:相加由讀的人做,同 §1 那五個整數的紀律。
        """
        self.seed([_spec("CCF", "2303")])
        direction = self.radar()[DIRECTION_KEY]
        self.assertEqual(sorted(direction), [
            "as_of", "decreased", "increased", "unchanged", "undetermined",
        ])
        self.assertIsInstance(direction["as_of"], str)
        for key in ("increased", "decreased", "unchanged", "undetermined"):
            self.assertIsInstance(direction[key], int, key)
            self.assertNotIsInstance(direction[key], bool, key)

    def test_the_key_cannot_silently_gain_a_rate_or_a_rank(self):
        """既有的 ``test_payload_cannot_silently_gain_a_rate`` 只走個股的 futures
        區塊,``test_the_index_cannot_silently_gain_a_rate`` 只走市場層級的名單
        ——這個鍵是 radar.json 的第三個入口,兩個閘門都照不到它。所以補這一把。
        """
        self.seed([_spec("CCF", "2303")])
        offenders = []

        def walk(node, path):
            if isinstance(node, dict):
                for key, value in node.items():
                    if any(bad in key.lower() for bad in RANK_ISH + RATIO_ISH):
                        offenders.append(f"{path}.{key}")
                    walk(value, f"{path}.{key}")
            elif isinstance(node, list):
                for i, value in enumerate(node):
                    walk(value, f"{path}[{i}]")

        walk(self.radar()[DIRECTION_KEY], DIRECTION_KEY)
        self.assertEqual(offenders, [])

    def test_no_flag_or_verdict_ever_reaches_the_payload(self):
        """描述性 = 只有計數。門檻、旗標、判語是資訊性主張,那需要一份 battery。"""
        self.seed([_spec("AAA", "2303"), _spec("BBB", "1565")])
        self.radar()
        raw = (self.out / "radar.json").read_text(encoding="utf-8")
        for verdict in ("偏多", "偏空", "異常", "unusual", "net", "pct",
                        "total", "threshold", "flag", "signal"):
            self.assertNotIn(verdict, raw.split(f'"{DIRECTION_KEY}"')[1][:200])

    # ── 與名單的獨立性 ──────────────────────────────────────────
    def test_it_survives_a_day_whose_anomaly_list_makes_no_claim(self):
        """§7.13:R4 算不出結算窗口 → 名單整個不主張。未平倉的方向與結算窗口
        毫無關係,跟著消失就是連坐——而這正是它不住在名單的 meta 裡的理由。
        """
        days = _DAYS[:_DAYS.index("2026-06-15") + 1]
        self.seed([_spec("CCF", "2303", days=days)], days=days)
        radar = self.radar()
        self.assertNotIn(INDEX_KEY, radar)
        self.assertNotIn(META_KEY, radar)
        self.assertEqual(radar[DIRECTION_KEY], {
            "as_of": days[-1], "increased": 1, "decreased": 0,
            "unchanged": 0, "undetermined": 0,
        })

    def test_it_counts_contracts_that_never_reach_the_anomaly_list(self):
        """計數涵蓋全部契約,名單只有舉旗的那些——兩個鍵的母體不同。"""
        self.seed([_spec("AAA", "2303"), _spec("BBB", "1565", today=BASE_LOTS)])
        radar = self.radar()
        self.assertEqual([e["code"] for e in radar[INDEX_KEY]], ["AAA"])
        self.assertEqual(radar[DIRECTION_KEY]["increased"], 2)

    def test_the_anomaly_meta_did_not_absorb_the_counts(self):
        """名單的 meta 仍然只有一個日期與一個整數(§7.11 的鎖原封不動)。"""
        self.seed([_spec("CCF", "2303")])
        self.assertEqual(sorted(self.radar()[META_KEY]), ["as_of", "window_days"])


class AnomalyIndexOrderingTests(unittest.TestCase):
    """排序本身,不經過資料庫。

    export 那一條路上 ``load_contracts`` 已經 ORDER BY contract_code,所以同分的
    兩個契約本來就照代碼進 dict——拿掉 ``code`` 這個收尾,穩定排序照樣給對的答案。
    也就是說那個 tiebreak 在 export 層級**不可證偽**。這裡直接餵一個相反順序的
    dict,讓它變成可證偽的。
    """

    @staticmethod
    def _entry(today):
        return {"anomaly": {"today": today, "window_max": 100,
                            "window_median": 100, "window_days": WINDOW_DAYS},
                "reasons": [], "risks": []}

    def test_ties_fall_back_to_code_even_when_the_input_is_reverse_ordered(self):
        from radar.compute.futures_volume_anomaly import anomaly_index
        ordered = anomaly_index(
            {"CCC": self._entry(300), "AAA": self._entry(300)},
            stock_id_by_code={"CCC": "2317", "AAA": "2303"},
        )
        self.assertEqual([e["code"] for e in ordered], ["AAA", "CCC"])

    def test_none_stays_none_and_empty_stays_empty(self):
        from radar.compute.futures_volume_anomaly import anomaly_index
        self.assertIsNone(anomaly_index(None, stock_id_by_code={}))
        self.assertEqual(anomaly_index({}, stock_id_by_code={}), [])


if __name__ == "__main__":
    unittest.main()
