"""WP-H3: Fugle 當日 1 分 K 降採樣與 spark_day 快取合併(不發網路)。"""
import os
import unittest

from radar.export.spark_day import attach_spark_day
from radar.providers.fugle import downsample_closes, parse_intraday_candles


class DownsampleTests(unittest.TestCase):
    def test_short_series_unchanged_length(self):
        xs = [10.0, 10.5, 11.0]
        self.assertEqual(downsample_closes(xs), [10.0, 10.5, 11.0])

    def test_keeps_first_and_last(self):
        xs = [float(i) for i in range(270)]
        out = downsample_closes(xs, n=60)
        self.assertLessEqual(len(out), 60)
        self.assertEqual(out[0], 0.0)
        self.assertEqual(out[-1], 269.0)


class ParseCandlesTests(unittest.TestCase):
    def test_parse_example_payload(self):
        payload = {
            "date": "2023-05-29",
            "symbol": "2330",
            "data": [
                {"date": "2023-05-29T09:00:00.000+08:00", "open": 574, "close": 572},
                {"date": "2023-05-29T09:01:00.000+08:00", "open": 572, "close": 571},
                {"date": "2023-05-29T09:02:00.000+08:00", "open": 572, "close": 570},
            ],
        }
        parsed = parse_intraday_candles(payload)
        self.assertEqual(parsed["date"], "2023-05-29")
        self.assertEqual(parsed["open"], 574.0)
        self.assertEqual(parsed["closes"], [572.0, 571.0, 570.0])

    def test_too_short_is_none(self):
        self.assertIsNone(parse_intraday_candles({"date": "2023-05-29", "data": [
            {"open": 1, "close": 1},
        ]}))


class AttachSparkDayTests(unittest.TestCase):
    def test_cache_hit_fetches_only_missing(self):
        union = {"2330": {"id": "2330"}, "2454": {"id": "2454"}}
        cache = {
            "date": "2026-08-19",
            "stocks": {"2330": {"open": 100.0, "closes": [100.0, 101.0, 99.5]}},
        }
        calls = []
        old = os.environ.get("FUGLE_API_KEY")
        os.environ["FUGLE_API_KEY"] = "test-key"
        try:
            n = attach_spark_day(
                union, "2026-08-19",
                today="2026-08-19",
                cache=cache,
                fetch_fn=lambda ids: calls.append(ids) or {},
                persist=False,
            )
        finally:
            if old is None:
                os.environ.pop("FUGLE_API_KEY", None)
            else:
                os.environ["FUGLE_API_KEY"] = old
        self.assertEqual(n, 1)
        self.assertEqual(union["2330"]["spark_day"], [100.0, 101.0, 99.5])
        self.assertEqual(union["2330"]["spark_open"], 100.0)
        self.assertNotIn("spark_day", union["2454"])
        self.assertEqual(calls, [["2454"]])

    def test_weekend_reuses_cache(self):
        union = {"2330": {"id": "2330"}}
        n = attach_spark_day(
            union, "2026-08-19",
            today="2026-08-20",
            cache={"date": "2026-08-19", "stocks": {
                "2330": {"open": 10.0, "closes": [10.0, 11.0]},
            }},
            fetch_fn=lambda ids: (_ for _ in ()).throw(AssertionError("should not fetch")),
            persist=False,
        )
        self.assertEqual(n, 1)
        self.assertEqual(union["2330"]["spark_open"], 10.0)

    def test_skip_fetch_when_not_today(self):
        union = {"2330": {"id": "2330"}}
        calls = []
        n = attach_spark_day(
            union, "2026-08-19",
            today="2026-08-20",
            cache={},
            fetch_fn=lambda ids: calls.append(ids) or {"2330": {
                "date": "2026-08-20", "open": 1, "closes": [1, 2],
            }},
            persist=False,
        )
        self.assertEqual(n, 0)
        self.assertEqual(calls, [])
        self.assertNotIn("spark_day", union["2330"])

    def test_fetch_fills_missing(self):
        union = {"2330": {"id": "2330"}}
        old = os.environ.get("FUGLE_API_KEY")
        os.environ["FUGLE_API_KEY"] = "test-key"
        try:
            n = attach_spark_day(
                union, "2026-08-19",
                today="2026-08-19",
                cache={"date": "2026-08-19", "stocks": {}},
                fetch_fn=lambda ids: {"2330": {
                    "date": "2026-08-19", "open": 50.0, "closes": [50.0, 51.0],
                }},
                persist=False,
            )
        finally:
            if old is None:
                os.environ.pop("FUGLE_API_KEY", None)
            else:
                os.environ["FUGLE_API_KEY"] = old
        self.assertEqual(n, 1)
        self.assertEqual(union["2330"]["spark_open"], 50.0)

    def test_no_key_does_not_fetch(self):
        union = {"2330": {"id": "2330"}}
        old = os.environ.pop("FUGLE_API_KEY", None)
        calls = []
        try:
            attach_spark_day(
                union, "2026-08-19",
                today="2026-08-19",
                cache={},
                fetch_fn=lambda ids: calls.append(ids) or {},
                persist=False,
            )
        finally:
            if old is not None:
                os.environ["FUGLE_API_KEY"] = old
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
