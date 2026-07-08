import unittest

from radar.compute.performance import forward_returns


class PerformanceTests(unittest.TestCase):
    def test_forward_returns_use_next_open_as_entry(self):
        candles = [
            {"date": "2026-01-02", "open": 100.0, "close": 101.0},
            {"date": "2026-01-05", "open": 102.0, "close": 103.0},
            {"date": "2026-01-06", "open": 104.0, "close": 105.0},
            {"date": "2026-01-07", "open": 106.0, "close": 108.0},
            {"date": "2026-01-08", "open": 109.0, "close": 111.0},
            {"date": "2026-01-09", "open": 112.0, "close": 114.0},
        ]

        perf = forward_returns(candles, "2026-01-02")

        self.assertEqual(perf["entry_date"], "2026-01-05")
        self.assertEqual(perf["entry_price"], 102.0)
        self.assertEqual(perf["fwd_1d"], 0.98)
        self.assertEqual(perf["fwd_3d"], 5.88)
        self.assertEqual(perf["fwd_5d"], 11.76)
        self.assertIsNone(perf["fwd_10d"])

    def test_no_future_candle_stays_pending(self):
        perf = forward_returns(
            [{"date": "2026-01-02", "open": 100.0, "close": 101.0}],
            "2026-01-02",
        )

        self.assertIsNone(perf)


if __name__ == "__main__":
    unittest.main()
