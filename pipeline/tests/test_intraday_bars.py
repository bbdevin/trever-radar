"""分K(docs/50):1 分 → 5 分聚合、快取/補抓上限、60 日裁切、離開聯集寬限、隔離、檔案格式。不發網路。"""
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from radar.export import intraday_bars as ib
from radar.export import spark_day
from radar.providers.fugle import candle_rows, parse_intraday_candles

TPE = timezone(timedelta(hours=8))


def row(day: str, hhmm: str, o, h, l, c, v=1):
    return {"date": f"{day}T{hhmm}:00.000+08:00", "open": o, "high": h, "low": l,
            "close": c, "volume": v}


def epoch(day: str, hhmm: str) -> int:
    y, m, d = (int(x) for x in day.split("-"))
    hh, mm = (int(x) for x in hhmm.split(":"))
    return int(datetime(y, m, d, hh, mm, tzinfo=TPE).timestamp())


def full_day(day: str, px: float = 100.0) -> list[dict]:
    """09:00..13:25 每分鐘一筆 + 13:30 收盤一筆。"""
    out = []
    t = datetime(2000, 1, 1, 9, 0)
    while t.strftime("%H:%M") <= "13:25":
        out.append(row(day, t.strftime("%H:%M"), px, px + 1, px - 1, px))
        t += timedelta(minutes=1)
    out.append(row(day, "13:30", px, px, px, px, 7))
    return out


def weekdays(n: int, end: str = "2026-10-08") -> list[str]:
    d = date.fromisoformat(end)
    out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return sorted(out)


class AggregateTests(unittest.TestCase):
    def test_one_minute_to_five(self):
        day = "2026-10-08"
        rows = [row(day, f"09:0{i}", 10 + i, 11 + i, 9 + i, 10.5 + i, 2) for i in range(10)]
        bars = ib.aggregate_5m(rows)[day]
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0], [epoch(day, "09:00"), 10, 15, 9, 14.5, 10])
        self.assertEqual(bars[1], [epoch(day, "09:05"), 15, 20, 14, 19.5, 10])
        # 標記 = 開始時間,台北 09:00 = UTC 01:00
        self.assertEqual(datetime.fromtimestamp(bars[0][0], timezone.utc).strftime("%H:%M"), "01:00")

    def test_close_auction_merges_into_1325(self):
        day = "2026-10-08"
        rows = [row(day, "13:25", 50, 51, 49, 50, 3), row(day, "13:29", 50, 52, 50, 51, 4),
                row(day, "13:30", 51.5, 51.5, 51.5, 51.5, 100),
                row(day, "08:59", 1, 1, 1, 1), row(day, "13:31", 9, 9, 9, 9), row(day, "14:30", 9, 9, 9, 9)]
        bars = ib.aggregate_5m(rows)[day]
        self.assertEqual(bars, [[epoch(day, "13:25"), 50, 52, 49, 51.5, 107]])

    def test_full_session_is_54_bars(self):
        day = "2026-10-08"
        bars = ib.aggregate_5m(full_day(day))[day]
        self.assertEqual(len(bars), 54)
        self.assertEqual(bars[0][0], epoch(day, "09:00"))
        self.assertEqual(bars[-1][0], epoch(day, "13:25"))
        self.assertEqual(bars[-1][5], 1 + 7)  # 13:25 那一分鐘 + 13:30 收盤

    def test_missing_minutes_leave_gaps(self):
        day = "2026-10-08"
        rows = [row(day, "09:10", 3, 3, 3, 3), row(day, "09:00", 1, 1, 1, 1), row(day, "09:03", 2, 2.5, 2, 2)]
        bars = ib.aggregate_5m(rows)[day]
        self.assertEqual([b[0] for b in bars], [epoch(day, "09:00"), epoch(day, "09:10")])
        self.assertEqual(bars[0][1:5], [1, 2.5, 1, 2])  # 未排序輸入也照時間取開收

    def test_close_label_shift(self):
        day = "2026-10-08"
        rows = [row(day, "09:05", 1, 2, 1, 2), row(day, "13:30", 5, 5, 5, 5)]
        bars = ib.aggregate_5m(rows, label_shift_min=-5)[day]
        self.assertEqual([b[0] for b in bars], [epoch(day, "09:00"), epoch(day, "13:25")])

    def test_multi_day_split(self):
        rows = [row("2026-10-07", "09:00", 1, 1, 1, 1), row("2026-10-08", "09:00", 2, 2, 2, 2)]
        self.assertEqual(sorted(ib.aggregate_5m(rows)), ["2026-10-07", "2026-10-08"])


class FugleParseTests(unittest.TestCase):
    def test_intraday_parse_keeps_full_rows(self):
        payload = {"date": "2026-10-08", "data": [
            row("2026-10-08", "09:00", 10, 11, 9, 10.5, 5),
            row("2026-10-08", "09:01", 10.5, 11, 10, 10.8, 6),
            {"date": "2026-10-08T09:02:00.000+08:00", "open": None, "close": 1},
        ]}
        parsed = parse_intraday_candles(payload)
        self.assertEqual(len(parsed["rows"]), 2)
        self.assertEqual(parsed["rows"][0]["volume"], 5.0)
        self.assertEqual(parsed["closes"], [10.5, 10.8, 1.0])

    def test_candle_rows_skip_bad(self):
        self.assertEqual(candle_rows({"data": [{"open": 1}, {"date": "x", "open": "a", "high": 1, "low": 1, "close": 1}]}), [])


class _Env:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.out = root / "out"
        self.cdir = root / "cache"

    def file(self, sid):
        return self.out / "stocks" / "intraday" / f"{sid}.json"

    def read(self, sid):
        return json.loads(self.file(sid).read_text(encoding="utf-8"))

    def run(self, ids, price_date, tdays, **kw):
        kw.setdefault("minute_rows_by_id", {})
        kw.setdefault("fetch_hist", None)
        return ib.update_intraday(self.out, ids, price_date, trading_days=tdays, cdir=self.cdir, **kw)


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.env = _Env()

    def tearDown(self):
        self.env.tmp.cleanup()

    def test_today_from_minute_rows_without_requests(self):
        tdays = weekdays(3)
        today = tdays[-1]
        calls = []
        stats = self.env.run(["2330"], today, tdays,
                             minute_rows_by_id={"2330": full_day(today)},
                             fetch_hist=lambda *a: calls.append(a) or [])
        # 今天由 1 分 K 而來;前兩天缺 → 一次請求涵蓋整段
        self.assertEqual(calls, [("2330", tdays[0], tdays[1])])
        self.assertEqual(stats["today"], 1)
        f = self.env.read("2330")
        self.assertEqual(len(f["bars"]), 54)
        self.assertEqual((f["from"], f["to"]), (today, today))

    def test_backfill_cap_and_one_request_per_stock(self):
        tdays = weekdays(5)
        calls = []

        def fetch(sid, a, b):
            calls.append((sid, a, b))
            return [r for d in tdays for r in full_day(d)]
        stats = self.env.run(["A", "B", "C"], tdays[-1], tdays, fetch_hist=fetch, cap=2)
        self.assertEqual(stats["requests"], 2)
        self.assertEqual([c[0] for c in calls], ["A", "B"])
        self.assertEqual(calls[0][1:], (tdays[0], tdays[-1]))
        self.assertTrue(self.env.file("A").exists())
        self.assertFalse(self.env.file("C").exists())
        # 下一輪只補 C,A/B 已在快取
        calls.clear()
        self.env.run(["A", "B", "C"], tdays[-1], tdays, fetch_hist=fetch, cap=2)
        self.assertEqual([c[0] for c in calls], ["C"])

    def test_uncapped_backfill(self):
        tdays = weekdays(2)
        ids = [str(i) for i in range(130)]
        stats = self.env.run(ids, tdays[-1], tdays, cap=None,
                             fetch_hist=lambda s, a, b: [r for d in tdays for r in full_day(d)])
        self.assertEqual(stats["requests"], 130)

    def test_empty_days_confirmed_except_latest(self):
        tdays = weekdays(3)
        calls = []

        def fetch(sid, a, b):
            calls.append((a, b))
            return full_day(tdays[1])  # 只有中間那天有資料
        self.env.run(["X"], tdays[-1], tdays, fetch_hist=fetch)
        cache = json.loads((self.env.cdir / "X.json").read_text(encoding="utf-8"))["days"]
        self.assertEqual(cache[tdays[0]], [])          # 問過、沒有 → 記空,不再問
        self.assertEqual(len(cache[tdays[1]]), 54)
        self.assertNotIn(tdays[2], cache)              # 最新一天沒拿到 → 下輪再問
        self.env.run(["X"], tdays[-1], tdays, fetch_hist=fetch)
        self.assertEqual(calls[-1], (tdays[2], tdays[2]))

    def test_failed_fetch_records_nothing(self):
        tdays = weekdays(2)
        self.env.run(["X"], tdays[-1], tdays, fetch_hist=lambda *a: None)
        self.assertFalse((self.env.cdir / "X.json").exists())
        self.assertFalse(self.env.file("X").exists())

    def test_trim_to_60_days(self):
        tdays = weekdays(65)
        self.env.run(["2330"], tdays[-1], tdays,
                     fetch_hist=lambda s, a, b: [r for d in tdays for r in full_day(d)])
        f = self.env.read("2330")
        self.assertEqual(f["from"], tdays[5])
        self.assertEqual(len(f["bars"]), 60 * 54)
        # 再往後一天:最舊那天被裁掉(快取與檔案都是)
        nxt = (date.fromisoformat(tdays[-1]) + timedelta(days=1)).isoformat()
        tdays2 = tdays + [nxt]
        self.env.run(["2330"], nxt, tdays2, minute_rows_by_id={"2330": full_day(nxt)})
        f = self.env.read("2330")
        self.assertEqual((f["from"], f["to"]), (tdays2[-60], nxt))
        cache = json.loads((self.env.cdir / "2330.json").read_text(encoding="utf-8"))["days"]
        self.assertEqual(len(cache), 60)

    def test_file_format(self):
        tdays = weekdays(2)
        self.env.run(["2330"], tdays[-1], tdays,
                     fetch_hist=lambda s, a, b: [r for d in tdays for r in full_day(d, 1245.5)])
        text = self.env.file("2330").read_text(encoding="utf-8")
        self.assertNotIn(" ", text)
        f = json.loads(text)
        self.assertEqual(list(f), ["id", "tf", "from", "to", "adjusted", "bars"])
        self.assertEqual((f["id"], f["tf"], f["adjusted"]), ("2330", "5", False))
        self.assertEqual(f["bars"][0], [epoch(tdays[0], "09:00"), 1245.5, 1246.5, 1244.5, 1245.5, 5])
        ts = [b[0] for b in f["bars"]]
        self.assertEqual(ts, sorted(ts))
        self.assertEqual([p.name for p in self.env.file("2330").parent.iterdir()], ["2330.json"])  # 無殘留 tmp

    def test_unchanged_content_not_rewritten(self):
        tdays = weekdays(2)
        fetch = lambda s, a, b: [r for d in tdays for r in full_day(d)]  # noqa: E731
        self.assertEqual(self.env.run(["2330"], tdays[-1], tdays, fetch_hist=fetch)["written"], 1)
        self.assertEqual(self.env.run(["2330"], tdays[-1], tdays, fetch_hist=fetch)["written"], 0)

    def test_no_output_dirs_when_nothing_to_write(self):
        tdays = weekdays(2)
        self.env.run(["2330"], tdays[-1], tdays)
        self.assertFalse(self.env.out.exists())
        self.assertFalse(self.env.cdir.exists())

    def test_deletion_grace_period(self):
        tdays = weekdays(30)
        fetch = lambda s, a, b: [r for d in tdays for r in full_day(d)]  # noqa: E731
        start = 15
        self.env.run(["A", "B"], tdays[start], tdays[: start + 1], fetch_hist=fetch, cap=None)
        self.assertTrue(self.env.file("B").exists())
        # B 離開聯集:缺席第 1..10 個交易日仍保留,第 11 個刪除(檔案與快取)
        for k in range(1, 11):
            i = start + k
            self.env.run(["A"], tdays[i], tdays[: i + 1])
            self.assertTrue(self.env.file("B").exists(), f"absent day {k}")
        i = start + 11
        stats = self.env.run(["A"], tdays[i], tdays[: i + 1])
        self.assertFalse(self.env.file("B").exists())
        self.assertFalse((self.env.cdir / "B.json").exists())
        self.assertEqual(stats["deleted"], 2)
        self.assertTrue(self.env.file("A").exists())

    def test_reentering_union_resets_grace(self):
        tdays = weekdays(30)
        fetch = lambda s, a, b: [r for d in tdays for r in full_day(d)]  # noqa: E731
        self.env.run(["A", "B"], tdays[5], tdays[:6], fetch_hist=fetch, cap=None)
        for i in range(6, 14):
            self.env.run(["A"], tdays[i], tdays[: i + 1])
        self.env.run(["A", "B"], tdays[14], tdays[:15])           # 回到聯集 → 清掉缺席起日
        for i in range(15, 24):
            self.env.run(["A"], tdays[i], tdays[: i + 1])         # 再缺席 9 天
        self.assertTrue(self.env.file("B").exists())
        state = json.loads((self.env.cdir / "_state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["absent_since"], {"B": tdays[15]})


class IsolationTests(unittest.TestCase):
    def test_safe_wrapper_swallows_and_keeps_old_files(self):
        env = _Env()
        try:
            tdays = weekdays(2)
            env.run(["2330"], tdays[-1], tdays,
                    fetch_hist=lambda s, a, b: [r for d in tdays for r in full_day(d)])
            before = env.file("2330").read_text(encoding="utf-8")

            def boom(*a):
                raise RuntimeError("fugle down")
            # 讓快取讀不到 → 一定會呼叫 fetch → 例外
            (env.cdir / "2330.json").unlink()
            with self.assertLogs("radar.export.intraday_bars", level="WARNING"):
                res = ib.export_intraday_safe(env.out, ["2330"], tdays[-1], today=tdays[-1],
                                              trading_days=tdays, cdir=env.cdir,
                                              minute_rows_by_id={}, fetch_hist=boom)
            self.assertIsNone(res)
            self.assertEqual(env.file("2330").read_text(encoding="utf-8"), before)
        finally:
            env.tmp.cleanup()

    def test_gate_blocks_fetch_when_not_today(self):
        env = _Env()
        try:
            tdays = weekdays(2)
            calls = []
            ib.export_intraday_safe(env.out, ["2330"], tdays[-1], today="2099-01-01",
                                    trading_days=tdays, cdir=env.cdir, minute_rows_by_id={},
                                    fetch_hist=lambda *a: calls.append(a) or [])
            self.assertEqual(calls, [])
            self.assertFalse(env.out.exists())
        finally:
            env.tmp.cleanup()

    def test_gate_off_never_reads_api_key(self):
        old = os.environ.get("FUGLE_API_KEY")
        os.environ["FUGLE_API_KEY"] = "k"
        env = _Env()
        try:
            tdays = weekdays(2)
            stats = ib.export_intraday_safe(env.out, ["2330"], tdays[-1], today="2099-01-01",
                                            trading_days=tdays, cdir=env.cdir, minute_rows_by_id={})
            self.assertEqual(stats["requests"], 0)
        finally:
            env.tmp.cleanup()
            if old is None:
                os.environ.pop("FUGLE_API_KEY", None)
            else:
                os.environ["FUGLE_API_KEY"] = old

    def test_json_export_calls_safe_wrapper_once(self):
        src = (Path(ib.__file__).parent / "json_export.py").read_text(encoding="utf-8")
        self.assertEqual(src.count("export_intraday_safe(out, union, d)"), 1)
        self.assertNotIn("update_intraday(", src)


class SparkDayPassThroughTests(unittest.TestCase):
    def test_minute_rows_exposed_for_price_date(self):
        old = os.environ.get("FUGLE_API_KEY")
        os.environ["FUGLE_API_KEY"] = "k"
        try:
            rows = full_day("2026-10-08")
            union = {"2330": {"id": "2330"}}
            spark_day.attach_spark_day(
                union, "2026-10-08", today="2026-10-08", cache={},
                fetch_fn=lambda ids: {"2330": {"date": "2026-10-08", "open": 100.0,
                                               "closes": [100.0, 101.0], "rows": rows}},
                persist=False)
        finally:
            if old is None:
                os.environ.pop("FUGLE_API_KEY", None)
            else:
                os.environ["FUGLE_API_KEY"] = old
        self.assertEqual(spark_day.minute_rows("2026-10-08"), {"2330": rows})
        self.assertEqual(spark_day.minute_rows("2026-10-07"), {})
        self.assertNotIn("rows", union["2330"])


if __name__ == "__main__":
    unittest.main()
