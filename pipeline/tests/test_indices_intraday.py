"""docs/49 §12.5:大盤當日 1 分線(indices_intraday.json)——解析、聚合、閘門、隔離、檔案格式(不發網路)。"""
import io
import json
import os
import zipfile
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
        urls = [c.args[0] for c in fg.call_args_list]
        self.assertEqual(len(urls), 2)  # 沒有 futopt 請求(免費方案 403)
        self.assertTrue(urls[0].endswith("/stock/intraday/candles/" + ii.FUGLE_TWSE_INDEX))
        self.assertTrue(urls[1].endswith("/stock/intraday/candles/" + ii.FUGLE_TPEX_INDEX))
        self.assertEqual(tw.call_args.args[1], {"date": "20261008", "response": "json"})

    def test_default_fetchers_tx_from_taifex_zip_and_unpublished_page(self):
        zblob = io.BytesIO()
        with zipfile.ZipFile(zblob, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("Daily_2026_10_08.csv", FIXTURE.read_bytes())
        resp = mock.Mock(status_code=200, content=zblob.getvalue(), headers={"Content-Type": "application/zip"})
        with mock.patch("requests.Session.get", return_value=resp) as g:
            s = ii.default_fetchers("k", "202610")["tx"](DAY)
        self.assertEqual(g.call_args.args[0],
                         "https://www.taifex.com.tw/file/taifex/Dailydownload/DailydownloadCSV/Daily_2026_10_08.zip")
        self.assertEqual(s[-1], [ep("13:44"), 49349])
        # 還沒公布:站方回 200 + HTML 錯誤頁 → 安靜地當沒有
        html = mock.Mock(status_code=200, content=b"<!DOCTYPE html><html>...", headers={"Content-Type": "text/html"})
        with mock.patch("requests.Session.get", return_value=html):
            self.assertEqual(ii.default_fetchers("k", "202610")["tx"](DAY), [])
        with mock.patch("requests.Session.get", side_effect=OSError("down")):
            self.assertEqual(ii.default_fetchers("k", "202610")["tx"](DAY), [])


FIXTURE = Path(__file__).parent / "fixtures" / "taifex_daily_tx_20261008_trim.csv"


class TaifexDailyTests(unittest.TestCase):
    """TAIFEX Daily_2026_10_08.zip 的裁切版(原始 Big5 位元組;322 列:一般時段 220 列含開盤集合競價與收盤前
    最後 25 筆,另有前一晚夜盤、凌晨夜盤、價差、遠月、小台/微台與其他商品各十幾列)。"""

    @classmethod
    def setUpClass(cls):
        cls.lines = FIXTURE.read_bytes().decode("cp950").splitlines()

    def test_header_is_the_documented_one(self):
        self.assertEqual([h.strip() for h in self.lines[0].split(",")],
                         ["成交日期", "商品代號", "到期月份(週別)", "成交時間", "成交價格", "成交數量(B+S)",
                          "近月價格", "遠月價格", "開盤集合競價"])

    def test_parity_last_day_session_trade_equals_official_close(self):
        # market_indices tx 2026-10-08 一般時段收盤 49349(futDataDown);逐筆最後一筆 13:44:59 49349
        s = ii.parse_taifex_daily_tx(self.lines, DAY, "202610")
        self.assertEqual(s[-1], [ep("13:44"), 49349])
        self.assertEqual(s[0], [ep("08:45"), s[0][1]])
        self.assertTrue(all(ep("08:45") <= t <= ep("13:45") for t, _ in s))
        self.assertEqual([t for t, _ in s], sorted({t for t, _ in s}))
        self.assertTrue(all(isinstance(v, int) for _, v in s))

    def test_night_session_spreads_other_months_and_products_excluded(self):
        s = ii.parse_taifex_daily_tx(self.lines, DAY, "202610")
        day_rows = [r.split(",") for r in self.lines[1:]]
        tx_day = [r for r in day_rows if r[1].strip() == "TX" and r[0] == "20261008" and r[2].strip() == "202610"
                  and "084500" <= r[3].strip().zfill(6) <= "134500"]
        # 每分鐘一點,值 = 該分鐘最後一筆
        last_by_min: dict[str, int] = {}
        for r in tx_day:
            last_by_min[r[3].strip().zfill(6)[:4]] = int(r[4])
        self.assertEqual([v for _, v in s], [last_by_min[k] for k in sorted(last_by_min)])
        # 夜盤(前一晚 15:00 起、凌晨 00:00–05:00)與價差真的在 fixture 裡,而且沒被算進來
        self.assertTrue(any(r[1].strip() == "TX" and r[0] == "20261007" for r in day_rows))
        self.assertTrue(any(r[1].strip() == "TX" and r[0] == "20261008" and r[3].strip().zfill(6) < "084500"
                            for r in day_rows))
        self.assertTrue(any(r[1].strip() == "TX" and "/" in r[2] for r in day_rows))

    def test_opening_auction_row_counts_as_the_0845_trade(self):
        auction = [r.split(",") for r in self.lines[1:] if r.split(",")[1].strip() == "TX"
                   and r.split(",")[0] == "20261008" and r.split(",")[2].strip() == "202610"
                   and r.rstrip().endswith("*")]
        self.assertEqual([(a[3].strip(), a[4].strip()) for a in auction], [("084500", "49480")])
        # 只有開盤那一筆時,08:45 那點就是集合競價價
        only = [self.lines[0], ",".join(auction[0])]
        self.assertEqual(ii.parse_taifex_daily_tx(only, DAY, "202610"), [[ep("08:45"), 49480]])

    def test_near_month_default_and_other_month(self):
        auto = ii.parse_taifex_daily_tx(self.lines, DAY, None)
        self.assertEqual(auto, ii.parse_taifex_daily_tx(self.lines, DAY, "202610"))  # 最小月份 = 近月
        far = ii.parse_taifex_daily_tx(self.lines, DAY, "202611")
        self.assertTrue(far and far[-1][1] != 49349)
        self.assertEqual(ii.parse_taifex_daily_tx(self.lines, "2026-10-09", "202610"), [])

    def test_zip_reader(self):
        zblob = io.BytesIO()
        with zipfile.ZipFile(zblob, "w") as zf:
            zf.writestr("Daily_2026_10_08.csv", FIXTURE.read_bytes())
        self.assertEqual(ii.read_taifex_daily_zip(zblob.getvalue()), self.lines)
        self.assertIsNone(ii.read_taifex_daily_zip(b"<html>not yet</html>"))


if __name__ == "__main__":
    unittest.main()
