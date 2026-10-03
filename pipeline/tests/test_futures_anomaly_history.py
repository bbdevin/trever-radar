# -*- coding: utf-8 -*-
"""近 10 個期貨交易日的舉旗紀錄(docs/38 §7.19,post-data,只動呈現)。

守的事:
* 三態(缺 entries = 那天不主張;[] = 算過、沒有人舉旗),與今日名單同生共死;
* 恰好是 as_of 之前的 10 個期貨交易日,新到舊;
* 每一天都是 ``futures_volume_anomalies`` 本人算的(呼叫次數、日期、同一份條目);
* 「現貨量有沒有跟上」的三態(第 3 天跟上 → true + 日期;5 天都知道且沒有 → false;
  只過了 2 天 → null;有一天算不出來 → null);
* 形狀鎖、``spot_after`` 只有原始價格(沒有除法)、比率 / 名次 / 報酬閘門。

fixture 沿用 test_futures_export 的 120 個交易日發明資料。
"""
import json
import unittest
from unittest.mock import patch

import radar.db as db
from radar import schema
from radar.compute import futures_volume_anomaly as fva
from radar.compute.futures_volume_anomaly import (
    HISTORY_DAYS,
    HISTORY_ENTRY_KEYS,
    HISTORY_ENTRY_OPTIONAL_KEYS,
    SPOT_AFTER_KEYS,
    anomaly_history,
    spot_after,
    stock_anomaly_history,
)
from radar.compute.futures_volume_battery import FORWARD_SPOT_DAYS, WINDOW_DAYS
from radar.export.json_export import export_json
from tests.test_futures_export import (
    AD,
    BASE_LOTS,
    MULTIPLIER,
    RANK_ISH,
    RATIO_ISH,
    SPIKE_LOTS,
    SPOT_AHEAD,
    SPOT_SHARES,
    _DAYS,
    _NO_FUTURES_ROWS,
    _AnomalyFixture,
    _futures_surface,
    _offenders,
    _spec,
)

HISTORY_KEY = "futures_volume_anomaly_history"
HISTORY_META_KEY = "futures_volume_anomaly_history_meta"
STOCK_HISTORY_KEY = "anomaly_history"      # stocks/{id}.json 的 futures 底下

PRIOR = _DAYS[-1 - HISTORY_DAYS:-1]          # AD 之前的 10 個期貨交易日(舊到新)
FLAG = _DAYS[-10]                            # 2026-06-08(週一),不在 R4 排除窗內
FLAG_FWD = _DAYS[-9:-4]                      # 它之後的 5 個現貨交易日:06-09..06-15
LATE_FLAG = _DAYS[-2]                        # 2026-06-18:之後只有 06-19、06-22 兩天

# 價格欄位不准出現的字樣(``oi_change`` 是未平倉,不是價格,明文豁免)。
PRICE_ISH = ("pct", "ret", "change", "ratio")
PRICE_ISH_EXEMPT = {"oi_change"}


def _history_flag_spec(code="CCF", stock_id="2303", *, day=FLAG, spike=SPIKE_LOTS,
                       extra=None):
    """今天(AD)不舉旗,只在 ``day`` 舉旗:尖峰把之後每一天的前高墊高。"""
    return _spec(code, stock_id, today=BASE_LOTS, lots={day: spike, **(extra or {})})


class _HistoryFixture(_AnomalyFixture):
    def set_spot(self, stock_id, day, **values):
        """改寫某一天的現貨列(volume / high / low / close / adj_factor)。"""
        with db.get_engine().begin() as conn:
            conn.execute(schema.daily_prices.update().where(
                (schema.daily_prices.c.stock_id == stock_id)
                & (schema.daily_prices.c.date == day)
            ).values(**values))

    def history(self):
        return self.radar()[HISTORY_KEY]

    def entries_on(self, day):
        return next(h for h in self.history() if h["as_of"] == day)["entries"]


class HistoryTriStateTests(_HistoryFixture):
    def test_absent_when_todays_list_was_never_computed(self):
        self.seed([_spec("CCF", "2303", lots=_NO_FUTURES_ROWS)])
        radar = self.radar()
        self.assertNotIn(HISTORY_KEY, radar)
        self.assertNotIn(HISTORY_META_KEY, radar)

    def test_the_ten_preceding_futures_days_newest_first(self):
        self.seed([_history_flag_spec()])
        self.assertEqual([h["as_of"] for h in self.history()], list(reversed(PRIOR)))
        self.assertNotIn(AD, [h["as_of"] for h in self.history()])

    def test_a_computed_day_with_nobody_flagged_is_an_empty_list(self):
        self.seed([_history_flag_spec()])
        days = {h["as_of"]: h for h in self.history()}
        # 06-12 是 R4 排除日:算過了,沒有人舉旗。
        self.assertEqual(days["2026-06-12"]["entries"], [])
        self.assertEqual([e["code"] for e in days[FLAG]["entries"]], ["CCF"])

    def test_a_day_the_rule_cannot_answer_has_no_entries_key(self):
        self.seed([_history_flag_spec()])
        real = fva.futures_volume_anomalies

        def undecidable_on_flag(conn, day, **kw):
            return None if day == FLAG else real(conn, day, **kw)

        with patch("radar.compute.futures_volume_anomaly.futures_volume_anomalies",
                   undecidable_on_flag):
            history = self.history()
        day = next(h for h in history if h["as_of"] == FLAG)
        self.assertEqual(day, {"as_of": FLAG})
        raw = (self.out / "radar.json").read_text(encoding="utf-8")
        self.assertNotIn('"entries": null', raw)

    def test_meta_reads_every_number_from_the_constants(self):
        self.seed([_history_flag_spec()])
        meta = self.radar()[HISTORY_META_KEY]
        self.assertEqual(meta, {
            "as_of": AD, "window_days": WINDOW_DAYS, "history_days": HISTORY_DAYS,
            "forward_days": FORWARD_SPOT_DAYS, "observed_through": SPOT_AHEAD,
        })


class HistoryUsesTheRuleItselfTests(_HistoryFixture):
    def test_one_rule_call_per_history_day_with_the_spot_calendar(self):
        self.seed([_history_flag_spec()])
        calls = []
        real = fva.futures_volume_anomalies

        def counting(conn, day, **kw):
            calls.append((day, kw.get("market_days_as_of")))
            return real(conn, day, **kw)

        with patch("radar.compute.futures_volume_anomaly.futures_volume_anomalies", counting):
            self.radar()
        self.assertEqual(calls, [(day, SPOT_AHEAD) for day in reversed(PRIOR)])

    def test_swapping_the_rule_changes_the_history(self):
        """規則換掉,紀錄必須跟著變——它沒有在家裡自己判斷創不創高。"""
        self.seed([_history_flag_spec()])
        with patch("radar.compute.futures_volume_anomaly.futures_volume_anomalies",
                   lambda conn, day, **kw: {}):
            history = self.history()
        self.assertTrue(all(h["entries"] == [] for h in history))

    def test_the_entry_is_the_same_entry_the_daily_list_would_carry(self):
        self.seed([_history_flag_spec()])
        entry = self.entries_on(FLAG)[0]
        with db.get_engine().connect() as conn:
            same_day = fva.anomaly_index(
                fva.futures_volume_anomalies(conn, FLAG, market_days_as_of=SPOT_AHEAD),
                stock_id_by_code={"CCF": "2303"}, multiplier_by_code={"CCF": MULTIPLIER},
            )
        for key, value in same_day[0].items():
            self.assertEqual(entry[key], value, key)
        self.assertEqual(entry["anomaly"]["today"], SPIKE_LOTS)

    def test_today_is_still_evaluated_exactly_once_by_the_export(self):
        self.seed([_history_flag_spec()])
        calls = []
        real = fva.futures_volume_anomalies

        def counting(conn, day, **kw):
            calls.append(day)
            return real(conn, day, **kw)

        with patch("radar.export.json_export.futures_volume_anomalies", counting):
            export_json(self.out)
        self.assertEqual(calls, [AD])

    def test_repeated_flags_are_not_merged(self):
        later = _DAYS[-8]       # 06-10,600 口 > 06-08 的 500 口
        self.seed([_history_flag_spec(extra={later: SPIKE_LOTS + 100})])
        flagged = [h["as_of"] for h in self.history() if h.get("entries")]
        self.assertEqual(flagged, [later, FLAG])

    def test_within_a_day_the_payload_order_is_kept(self):
        self.seed([
            _history_flag_spec("AAA", "2303", spike=300),
            _history_flag_spec("BBB", "1565", spike=SPIKE_LOTS),
        ])
        self.assertEqual([e["code"] for e in self.entries_on(FLAG)], ["BBB", "AAA"])


class SpotFollowedTests(_HistoryFixture):
    def test_spot_follows_on_the_third_day(self):
        self.seed([_history_flag_spec()])
        self.set_spot("2303", FLAG_FWD[2], volume=SPOT_SHARES * 5)
        entry = self.entries_on(FLAG)[0]
        self.assertIs(entry["spot_followed"], True)
        self.assertEqual(entry["spot_followed_on"], FLAG_FWD[2])
        self.assertEqual(entry["forward_days_observed"], FORWARD_SPOT_DAYS)

    def test_five_known_days_without_a_new_high_is_false(self):
        self.seed([_history_flag_spec()])
        entry = self.entries_on(FLAG)[0]
        self.assertIs(entry["spot_followed"], False)
        self.assertNotIn("spot_followed_on", entry)
        self.assertEqual(entry["forward_days_observed"], 5)

    def test_two_elapsed_days_is_still_open(self):
        self.seed([_history_flag_spec(day=LATE_FLAG)])
        entry = self.entries_on(LATE_FLAG)[0]
        self.assertIsNone(entry["spot_followed"])
        self.assertEqual(entry["forward_days_observed"], 2)

    def test_a_day_whose_new_high_is_unknown_makes_it_null_not_false(self):
        self.seed([_history_flag_spec()])
        self.set_spot("2303", FLAG_FWD[1], volume=None)
        entry = self.entries_on(FLAG)[0]
        self.assertIsNone(entry["spot_followed"])
        self.assertEqual(entry["forward_days_observed"], 5)

    def test_the_follow_up_uses_the_batterys_own_functions(self):
        self.assertIs(fva.forward_spot_days,
                      __import__("radar.compute.futures_volume_battery",
                                 fromlist=["x"]).forward_spot_days)
        self.assertIs(fva.spot_new_high,
                      __import__("radar.compute.futures_volume_battery",
                                 fromlist=["x"]).spot_new_high)


class SpotAfterTests(_HistoryFixture):
    def test_raw_prices_after_the_flag_day(self):
        self.seed([_history_flag_spec()])
        self.set_spot("2303", FLAG_FWD[0], high=58.0, low=49.0)
        self.set_spot("2303", FLAG_FWD[3], low=45.5)
        after = self.entries_on(FLAG)[0]["spot_after"]
        days_after = len(_DAYS) - _DAYS.index(FLAG) - 1 + 1     # 至 06-19,再加 06-22
        self.assertEqual(after, {
            "flag_close": 50.0, "last_close": 50.0, "last_date": SPOT_AHEAD,
            "high": 58.0, "low": 45.5, "days": days_after, "ex_rights": False,
        })

    def test_ex_rights_is_flagged_when_the_factor_moves(self):
        self.seed([_history_flag_spec()])
        self.set_spot("2303", FLAG_FWD[0], adj_factor=0.95)
        self.assertIs(self.entries_on(FLAG)[0]["spot_after"]["ex_rights"], True)

    def test_production_shaped_ex_dividend_gap_is_not_detected(self):
        """production 的形狀:除息 100 → 95,兩列 adj_factor 都是 1.0(compute-adjustments
        不在排程裡)。偵測不到 → ex_rights 為假,原始價格照實給;前端因此每一句價格都
        標「未扣除權息」(futures.test.ts 鎖)。這裡鎖的是「我們不假裝偵測得到」。"""
        prices = [
            {"date": "2026-09-01", "close": 100.0, "high": 101.0, "low": 99.0, "adj_factor": 1.0},
            {"date": "2026-09-02", "close": 95.0, "high": 96.0, "low": 94.5, "adj_factor": 1.0},
        ]
        self.assertEqual(spot_after(prices, day="2026-09-01"), {
            "flag_close": 100.0, "last_close": 95.0, "last_date": "2026-09-02",
            "high": 96.0, "low": 94.5, "days": 1, "ex_rights": False,
        })

    def test_no_price_row_on_the_flag_day_means_no_key(self):
        self.assertIsNone(spot_after([{"date": "2026-06-09", "close": 1.0, "high": 1.0,
                                       "low": 1.0, "adj_factor": 1.0}], day="2026-06-08"))
        self.assertIsNone(spot_after([{"date": "2026-06-08", "close": None, "high": None,
                                       "low": None, "adj_factor": 1.0}], day="2026-06-08"))

    def test_no_day_after_yet_is_only_the_reference(self):
        prices = [{"date": "2026-06-08", "close": 12.3, "high": 12.5, "low": 12.0,
                   "adj_factor": 1.0}]
        self.assertEqual(spot_after(prices, day="2026-06-08"),
                         {"flag_close": 12.3, "days": 0})

    def test_the_key_set_is_exactly_seven_and_nothing_is_divided(self):
        self.seed([_history_flag_spec()])
        after = self.entries_on(FLAG)[0]["spot_after"]
        self.assertEqual(sorted(after), sorted(SPOT_AFTER_KEYS))
        for key in after:
            for bad in PRICE_ISH:
                self.assertNotIn(bad, key)


class HistoryShapeTests(_HistoryFixture):
    def test_the_entry_key_set_is_locked(self):
        self.seed([_history_flag_spec()])
        self.set_spot("2303", FLAG_FWD[2], volume=SPOT_SHARES * 5)
        entry = self.entries_on(FLAG)[0]
        required = set(HISTORY_ENTRY_KEYS)
        self.assertTrue(required <= set(entry), required - set(entry))
        self.assertTrue(set(entry) - required <= set(HISTORY_ENTRY_OPTIONAL_KEYS),
                        set(entry) - required)
        self.assertEqual(sorted(entry), sorted(
            HISTORY_ENTRY_KEYS + ("spot_followed_on", "spot_after")))

    def test_each_day_is_exactly_as_of_and_optional_entries(self):
        self.seed([_history_flag_spec()])
        for day in self.history():
            self.assertTrue(set(day) <= {"as_of", "entries"}, day)

    def test_no_rank_or_ratio_key_anywhere_on_the_history(self):
        self.seed([_history_flag_spec(), _history_flag_spec("BBB", "1565")])
        export_json(self.out)
        surface = _futures_surface(self.out)
        self.assertTrue(any(path.endswith(HISTORY_KEY) for path in surface))
        self.assertEqual(_offenders(surface), [])

    def test_no_price_derived_key_anywhere_on_the_history(self):
        """pct / ret / change / ratio:除法留給讀的人(前端那一個純函式)。"""
        self.seed([_history_flag_spec()])
        radar = self.radar()
        keys = []

        def walk(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    keys.append(key)
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(radar[HISTORY_KEY])
        walk(radar[HISTORY_META_KEY])
        self.assertIn("spot_followed", keys)       # 閘門真的走到了條目
        self.assertIn("flag_close", keys)
        offenders = [k for k in keys if k not in PRICE_ISH_EXEMPT
                     and any(bad in k.lower() for bad in PRICE_ISH + RATIO_ISH + RANK_ISH)]
        self.assertEqual(offenders, [])


class HistoryUnitTests(unittest.TestCase):
    def test_none_as_of_is_none(self):
        self.assertIsNone(anomaly_history(None, as_of=None, spot_date="2026-06-22"))

    def test_stock_slice_keeps_each_days_tri_state(self):
        meta = {"as_of": "2026-06-22"}
        e1 = {"stock_id": "2303", "code": "CCF"}
        e2 = {"stock_id": "1565", "code": "MYF"}
        history = [
            {"as_of": "2026-06-19", "entries": [e2, e1]},
            {"as_of": "2026-06-18"},
            {"as_of": "2026-06-17", "entries": []},
        ]
        self.assertEqual(stock_anomaly_history(history, meta, "2303"), {
            "meta": meta,
            "days": [
                {"as_of": "2026-06-19", "entries": [e1]},
                {"as_of": "2026-06-18"},
                {"as_of": "2026-06-17", "entries": []},
            ],
        })
        self.assertIsNone(stock_anomaly_history(None, meta, "2303"))
        self.assertIsNone(stock_anomaly_history(history, None, "2303"))


class StockHistoryExportTests(_HistoryFixture):
    """個股 JSON 的 ``futures.anomaly_history``(docs/38 §7.20):radar.json 那一份切出
    這一檔,不重算;每一天的三態原樣保留;沒有算過就整個鍵不輸出。"""

    def stock(self, sid):
        return json.loads(
            (self.out / "stocks" / f"{sid}.json").read_text(encoding="utf-8"))

    def test_shape_and_identity_with_radar_json(self):
        self.seed([_history_flag_spec(), _history_flag_spec("BBB", "1565")])
        self.set_spot("2303", FLAG_FWD[2], volume=SPOT_SHARES * 5)
        radar = self.radar()
        for sid in ("2303", "1565"):
            with self.subTest(sid=sid):
                block = self.stock(sid)["futures"][STOCK_HISTORY_KEY]
                self.assertEqual(sorted(block), ["days", "meta"])
                self.assertEqual(block["meta"], radar[HISTORY_META_KEY])
                self.assertEqual([d["as_of"] for d in block["days"]],
                                 [h["as_of"] for h in radar[HISTORY_KEY]])
                for mine, market in zip(block["days"], radar[HISTORY_KEY]):
                    self.assertTrue(set(mine) <= {"as_of", "entries"}, mine)
                    self.assertEqual("entries" in mine, "entries" in market)
                    if "entries" in market:
                        self.assertEqual(
                            mine["entries"],
                            [e for e in market["entries"] if e["stock_id"] == sid])
        flagged = next(d for d in self.stock("2303")["futures"][STOCK_HISTORY_KEY]["days"]
                       if d["as_of"] == FLAG)
        self.assertEqual([e["code"] for e in flagged["entries"]], ["CCF"])
        self.assertIs(flagged["entries"][0]["spot_followed"], True)
        self.assertIn("spot_after", flagged["entries"][0])

    def test_unflagged_days_are_kept_as_empty_lists(self):
        self.seed([_history_flag_spec()])
        self.radar()
        days = self.stock("2303")["futures"][STOCK_HISTORY_KEY]["days"]
        self.assertEqual(len(days), HISTORY_DAYS)
        self.assertEqual(sum(1 for d in days if d.get("entries")), 1)
        self.assertTrue(all(d["entries"] == [] for d in days
                            if d["as_of"] != FLAG and "entries" in d))

    def test_a_day_the_rule_cannot_answer_has_no_entries_key_here_too(self):
        self.seed([_history_flag_spec()])
        real = fva.futures_volume_anomalies

        def undecidable_on_flag(conn, day, **kw):
            return None if day == FLAG else real(conn, day, **kw)

        with patch("radar.compute.futures_volume_anomaly.futures_volume_anomalies",
                   undecidable_on_flag):
            export_json(self.out)
        days = self.stock("2303")["futures"][STOCK_HISTORY_KEY]["days"]
        self.assertEqual(next(d for d in days if d["as_of"] == FLAG), {"as_of": FLAG})

    def test_absent_when_the_history_was_never_computed(self):
        self.seed([_spec("CCF", "2303", lots=_NO_FUTURES_ROWS)])
        self.radar()
        self.assertNotIn(STOCK_HISTORY_KEY, self.stock("2303").get("futures", {}))

    def test_the_history_is_not_recomputed_per_stock(self):
        self.seed([_history_flag_spec(), _history_flag_spec("BBB", "1565")])
        calls = []
        real = fva.futures_volume_anomalies

        def counting(conn, day, **kw):
            calls.append(day)
            return real(conn, day, **kw)

        with patch("radar.compute.futures_volume_anomaly.futures_volume_anomalies", counting):
            export_json(self.out)
        self.assertEqual(calls, list(reversed(PRIOR)))


if __name__ == "__main__":
    unittest.main()
