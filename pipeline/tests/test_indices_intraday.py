"""docs/49 §12.5:大盤當日 1 分線(indices_intraday.json)——解析、聚合、閘門、隔離、檔案格式(不發網路)。"""
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from radar.export import indices_intraday as ii

TPE = ZoneInfo("Asia/Taipei")
DAY = "2026-10-08"


def ep(hhmm: str, day: str = DAY) -> int:
    y, m, d = (int(x) for x in day.split("-"))
    hh, mm = (int(x) for x in hhmm.split(":"))
    return int(datetime(y, m, d, hh, mm, tzinfo=TPE).timestamp())


def fugle_payload(rows, day=DAY):
    return {"date": day, "type": "INDEX", "symbol": "IX0001", "data": [
        {"date": f"{day}T{t}:00.000+08:00", "open": c, "high": c, "low": c, "close": c} for t, c in rows]}


class ParseTests(unittest.TestCase):
    def test_fugle_candles_epoch_is_taipei_minute_start(self):
        s = ii.parse_fugle_candles(fugle_payload([("09:00", 49806.37), ("09:01", 49783.06), ("13:30", 49900)]),
                                   DAY, "twse")
        self.assertEqual(s, [[ep("09:00"), 49806.37], [ep("09:01"), 49783.06], [ep("13:30"), 49900]])
        # 09:00 台北 = 01:00Z;前端 chartTimeOf(twWallKey) 換回 09:00
        self.assertEqual(s[0][0], int(datetime(2026, 10, 8, 1, 0, tzinfo=ZoneInfo("UTC")).timestamp()))
        self.assertIsInstance(s[2][1], int)  # 整數價寫成 int 省位元組

    def test_session_window_and_other_days_dropped(self):
        rows = [("08:59", 1.0), ("09:00", 2.0), ("13:30", 3.0), ("13:31", 4.0)]
        self.assertEqual([p[1] for p in ii.parse_fugle_candles(fugle_payload(rows), DAY, "twse")], [2, 3])
        # 台指期一般時段 08:45–13:45
        rows = [("08:44", 1.0), ("08:45", 2.0), ("13:45", 3.0), ("13:46", 4.0)]
        self.assertEqual([p[1] for p in ii.parse_fugle_candles(fugle_payload(rows), DAY, "tx")], [2, 3])
        # 別天的列不算
        self.assertEqual(ii.parse_fugle_candles(fugle_payload([("09:00", 1.0)], "2026-10-07"), DAY, "twse"), [])

    def test_bad_rows_and_empty_payload(self):
        p = {"data": [{"date": "bad", "close": 1}, {"date": f"{DAY}T09:00:00+08:00", "close": None},
                      {"date": f"{DAY}T09:01:00+08:00", "close": "x"}, {"date": f"{DAY}T09:02:00+08:00", "close": 0},
                      {"date": f"{DAY}T09:03:00+08:00", "close": "430.5"}]}
        self.assertEqual(ii.parse_fugle_candles(p, DAY, "tpex"), [[ep("09:03"), 430.5]])
        self.assertEqual(ii.parse_fugle_candles(None, DAY, "tpex"), [])

    def test_twse_5s_aggregates_to_last_value_per_minute(self):
        payload = {"stat": "OK", "fields": ["時間", "發行量加權股價指數", "未含金融保險股指數"], "data": [
            ["09:00:00", "49,806.37", "1"], ["09:00:05", "49,783.06", "1"], ["09:00:55", "49,700.00", "1"],
            ["09:01:00", "49,710.10", "1"], ["13:30:00", "49,900.00", "1"], ["13:33:00", "1.00", "1"],
            ["bad", "1", "1"],
        ]}
        self.assertEqual(ii.parse_twse_5s(payload, DAY),
                         [[ep("09:00"), 49700], [ep("09:01"), 49710.1], [ep("13:30"), 49900]])
        self.assertEqual(ii.parse_twse_5s({"stat": "很抱歉,沒有符合條件的資料!"}, DAY), [])
        self.assertEqual(ii.parse_twse_5s({"stat": "OK", "fields": ["時間"], "data": []}, DAY), [])

    def test_tx_symbol_and_near_month_rule(self):
        self.assertEqual(ii.tx_symbol("202610"), "TXFJ6")
        self.assertEqual(ii.tx_symbol("202701"), "TXFA7")
        self.assertEqual(ii.tx_symbol("202612"), "TXFL6")
        self.assertIsNone(ii.tx_symbol("2026/10"))
        self.assertIsNone(ii.tx_symbol(None))
        # 2026-10 第三個週三 = 10/21:當天仍是 10 月,隔天換 11 月
        self.assertEqual(ii.near_month_by_rule("2026-10-21"), "202610")
        self.assertEqual(ii.near_month_by_rule("2026-10-22"), "202611")
        self.assertEqual(ii.near_month_by_rule("2026-12-31"), "202701")
        self.assertEqual(ii.near_month_by_rule("2026-09-16"), "202609")  # 09/16 是 9 月結算日


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.target = self.out / "market" / ii.OUT_FILE
        self.calls: list[str] = []

    def tearDown(self):
        self.tmp.cleanup()

    def fetchers(self, **series):
        def make(m):
            def fn(day):
                self.calls.append(m)
                return series.get(m, [])
            return fn
        return {m: make(m) for m in ii.MARKETS}

    S = [[ep("09:00"), 100], [ep("09:01"), 101.5]]

    def test_writes_compact_file_in_market_order(self):
        st = ii.update_indices_intraday(self.out, DAY, today=DAY,
                                        fetchers=self.fetchers(tx=self.S, twse=self.S, tpex=[[1, 2]]))
        text = self.target.read_text(encoding="utf-8")
        data = json.loads(text)
        self.assertEqual(data, {"date": DAY, "series": {"twse": self.S, "tx": self.S}})  # tpex 只有 1 點 → 不出
        self.assertNotIn(" ", text)
        self.assertEqual(list(data["series"]), ["twse", "tx"])
        self.assertTrue(st["written"])
        self.assertEqual(sorted(st["fetched"]), ["twse", "tx"])
        self.assertFalse(list(self.target.parent.glob("*.tmp-*")))

    def test_gate_today_must_equal_price_date(self):
        st = ii.update_indices_intraday(self.out, DAY, today="2026-10-09", fetchers=self.fetchers(twse=self.S))
        self.assertEqual(self.calls, [])
        self.assertFalse(self.target.exists())
        self.assertEqual(st["skip"], "today=2026-10-09")

    def test_gate_needs_fugle_key(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FUGLE_API_KEY", None)
            st = ii.update_indices_intraday(self.out, DAY, today=DAY)
        self.assertEqual(st["skip"], "no FUGLE_API_KEY")
        self.assertFalse(self.target.exists())

    def test_once_per_day_and_only_missing_refetched(self):
        ii.update_indices_intraday(self.out, DAY, today=DAY, fetchers=self.fetchers(twse=self.S, tpex=self.S))
        self.assertEqual(self.calls, ["twse", "tpex", "tx"])
        self.calls.clear()
        # 第二輪:只補 tx
        ii.update_indices_intraday(self.out, DAY, today=DAY, fetchers=self.fetchers(twse=[], tx=self.S))
        self.assertEqual(self.calls, ["tx"])
        self.assertEqual(list(json.loads(self.target.read_text("utf-8"))["series"]), ["twse", "tpex", "tx"])
        self.calls.clear()
        # 第三輪:三個都齊 → 不打
        st = ii.update_indices_intraday(self.out, DAY, today=DAY, fetchers=self.fetchers())
        self.assertEqual(self.calls, [])
        self.assertEqual(st["skip"], "complete")

    def test_keeps_only_latest_day_and_keeps_old_file_when_nothing_fetched(self):
        ii.update_indices_intraday(self.out, "2026-10-07", today="2026-10-07",
                                   fetchers=self.fetchers(twse=[[ep("09:00", "2026-10-07"), 1], [ep("09:01", "2026-10-07"), 2]]))
        # 新的一天什麼都沒抓到:舊檔留著(前端照檔內 date 標日期)
        ii.update_indices_intraday(self.out, DAY, today=DAY, fetchers=self.fetchers())
        self.assertEqual(json.loads(self.target.read_text("utf-8"))["date"], "2026-10-07")
        # 抓到了:整檔換成新的一天,舊日序列不留
        ii.update_indices_intraday(self.out, DAY, today=DAY, fetchers=self.fetchers(tpex=self.S))
        self.assertEqual(json.loads(self.target.read_text("utf-8")), {"date": DAY, "series": {"tpex": self.S}})

    def test_isolation_exception_is_logged_not_raised(self):
        def boom(day):
            raise RuntimeError("source down")
        self.target.parent.mkdir(parents=True)
        self.target.write_text('{"date":"2026-10-07","series":{}}', encoding="utf-8")
        with self.assertLogs("radar.export.indices_intraday", level="WARNING"):
            r = ii.export_indices_intraday_safe(self.out, DAY, today=DAY, fetchers={"twse": boom})
        self.assertIsNone(r)
        self.assertEqual(self.target.read_text("utf-8"), '{"date":"2026-10-07","series":{}}')

    def test_default_fetchers_twse_falls_back_to_official_5s_table(self):
        five_s = {"stat": "OK", "fields": ["時間", "發行量加權股價指數"],
                  "data": [["09:00:00", "100.00"], ["09:01:00", "101.00"]]}
        with mock.patch("radar.providers.fugle._get_json", return_value=None) as fg, \
                mock.patch("radar.http.get_json", return_value=five_s) as tw:
            f = ii.default_fetchers("k", "202610")
            self.assertEqual(f["twse"](DAY), [[ep("09:00"), 100], [ep("09:01"), 101]])
            self.assertEqual(f["tpex"](DAY), [])
            self.assertEqual(f["tx"](DAY), [])
        urls = [c.args[0] for c in fg.call_args_list]
        self.assertTrue(urls[0].endswith("/stock/intraday/candles/" + ii.FUGLE_TWSE_INDEX))
        self.assertTrue(urls[1].endswith("/stock/intraday/candles/" + ii.FUGLE_TPEX_INDEX))
        self.assertTrue(urls[2].endswith("/futopt/intraday/candles/TXFJ6"))
        self.assertEqual(tw.call_args.args[1], {"date": "20261008", "response": "json"})


if __name__ == "__main__":
    unittest.main()
