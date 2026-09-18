import random
import unittest

from radar.compute.performance import HORIZONS, forward_returns


def forward_returns_linear_oracle(candles: list[dict], signal_date: str) -> dict | None:
    """The pre-bisect implementation, kept verbatim as a parity oracle.

    Do not "tidy" this: its only job is to be the behaviour that the binary
    search in radar/compute/performance.py must reproduce exactly.
    """
    entry_idx = next(
        (i for i, c in enumerate(candles)
         if c["date"] > signal_date and c.get("open") and c["open"] > 0),
        None,
    )
    if entry_idx is None:
        return None

    entry = candles[entry_idx]
    entry_price = entry["open"]
    out = {
        "entry_date": entry["date"],
        "entry_price": round(entry_price, 4),
    }
    for horizon in HORIZONS:
        target_idx = entry_idx + horizon - 1
        close = candles[target_idx]["close"] if target_idx < len(candles) else None
        out[f"fwd_{horizon}d"] = (
            round((close / entry_price - 1) * 100, 2)
            if close is not None and entry_price > 0
            else None
        )
    return out


class _CountingCandle(dict):
    """A candle that records how many field reads the search performs."""

    reads = 0

    def __getitem__(self, key):
        type(self).reads += 1
        return super().__getitem__(key)

    def get(self, key, default=None):
        type(self).reads += 1
        return super().get(key, default)


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


class ForwardReturnsParityTests(unittest.TestCase):
    """The binary-search entry lookup must equal the old linear scan, always."""

    def assert_parity(self, candles, signal_date, msg=""):
        expected = forward_returns_linear_oracle(candles, signal_date)
        actual = forward_returns(candles, signal_date)
        self.assertEqual(actual, expected, msg or f"signal_date={signal_date!r}")
        return actual

    # --- hand-built edge cases -------------------------------------------

    def test_empty_and_single_element_lists(self):
        self.assertIsNone(self.assert_parity([], "2026-01-05"))
        one = [{"date": "2026-01-05", "open": 10.0, "close": 11.0}]
        self.assertIsNone(self.assert_parity(one, "2026-01-05"))
        self.assertIsNone(self.assert_parity(one, "2026-01-06"))
        self.assertIsNotNone(self.assert_parity(one, "2026-01-01"))

    def test_signal_date_before_all_after_all_and_exactly_equal(self):
        candles = [
            {"date": "2026-01-02", "open": 100.0, "close": 101.0},
            {"date": "2026-01-05", "open": 102.0, "close": 103.0},
            {"date": "2026-01-06", "open": 104.0, "close": 105.0},
        ]
        before = self.assert_parity(candles, "2025-12-31")
        self.assertEqual(before["entry_date"], "2026-01-02")
        equal = self.assert_parity(candles, "2026-01-02")
        self.assertEqual(equal["entry_date"], "2026-01-05")
        self.assertIsNone(self.assert_parity(candles, "2026-02-01"))

    def test_first_valid_open_several_days_after_signal(self):
        # The case a naive "bisect and take that index" rewrite gets wrong.
        candles = [
            {"date": "2026-01-02", "open": 100.0, "close": 101.0},
            {"date": "2026-01-05", "open": 0.0, "close": 103.0},
            {"date": "2026-01-06", "open": None, "close": 105.0},
            {"date": "2026-01-07", "close": 108.0},            # open missing
            {"date": "2026-01-08", "open": 109.0, "close": 111.0},
            {"date": "2026-01-09", "open": 112.0, "close": 114.0},
        ]
        perf = self.assert_parity(candles, "2026-01-02")
        self.assertEqual(perf["entry_date"], "2026-01-08")
        self.assertEqual(perf["entry_price"], 109.0)

    def test_every_open_after_signal_is_unusable(self):
        candles = [
            {"date": "2026-01-02", "open": 100.0, "close": 101.0},
            {"date": "2026-01-05", "open": 0.0, "close": 103.0},
            {"date": "2026-01-06", "open": None, "close": 105.0},
            {"date": "2026-01-07", "close": 108.0},
        ]
        self.assertIsNone(self.assert_parity(candles, "2026-01-02"))

    def test_duplicate_dates(self):
        # Unreachable from the repo's callers (daily_prices has a
        # (stock_id, date) primary key and every caller reads one stock via
        # ORDER BY date), but forward_returns is a public pure function, so
        # bisect_right must still land past the whole run of equal dates.
        candles = [
            {"date": "2026-01-05", "open": 100.0, "close": 101.0},
            {"date": "2026-01-05", "open": 102.0, "close": 103.0},
            {"date": "2026-01-05", "open": 104.0, "close": 105.0},
            {"date": "2026-01-06", "open": 106.0, "close": 107.0},
            {"date": "2026-01-06", "open": 108.0, "close": 109.0},
        ]
        perf = self.assert_parity(candles, "2026-01-05")
        self.assertEqual(perf["entry_date"], "2026-01-06")
        self.assertEqual(perf["entry_price"], 106.0)
        self.assert_parity(candles, "2026-01-04")
        self.assert_parity(candles, "2026-01-06")

    def test_negative_open_is_skipped_like_the_old_scan(self):
        candles = [
            {"date": "2026-01-02", "open": 100.0, "close": 101.0},
            {"date": "2026-01-05", "open": -5.0, "close": 103.0},
            {"date": "2026-01-06", "open": 104.0, "close": 105.0},
        ]
        perf = self.assert_parity(candles, "2026-01-02")
        self.assertEqual(perf["entry_date"], "2026-01-06")

    # --- randomised parity ------------------------------------------------

    def test_randomised_parity_against_linear_oracle(self):
        rng = random.Random(20260918)
        for case in range(3000):
            length = rng.choice([0, 1, 2, 3, 5, 12, 40, 120])
            day = rng.randrange(1, 200)
            candles = []
            for _ in range(length):
                day += rng.choice([1, 1, 1, 2, 3, 7])
                candle = {"date": f"2026-{1 + day // 28:02d}-{1 + day % 28:02d}"}
                roll = rng.random()
                if roll < 0.12:
                    pass                                  # open key missing
                elif roll < 0.22:
                    candle["open"] = None
                elif roll < 0.30:
                    candle["open"] = 0.0
                elif roll < 0.33:
                    candle["open"] = -rng.uniform(1, 50)   # nonsense but truthy
                else:
                    candle["open"] = round(rng.uniform(5, 500), 4)
                candle["close"] = (
                    None if rng.random() < 0.05 else round(rng.uniform(5, 500), 4)
                )
                candles.append(candle)

            if candles and rng.random() < 0.7:
                signal_date = rng.choice(candles)["date"]
            else:
                signal_date = f"2026-{rng.randrange(1, 13):02d}-{rng.randrange(1, 29):02d}"

            with self.subTest(case=case):
                self.assert_parity(candles, signal_date)

    # --- complexity pin ---------------------------------------------------

    def test_entry_lookup_does_not_scan_the_history(self):
        """Fails loudly if anyone reintroduces a linear scan from index 0."""
        candles = [
            _CountingCandle(
                date=f"2026-{i:06d}",  # lexicographically ascending, like ISO dates
                open=100.0 + i,
                close=101.0 + i,
            )
            for i in range(4000)
        ]
        _CountingCandle.reads = 0
        perf = forward_returns(candles, candles[3900]["date"])
        # candles[3900]["date"] above costs one read; discount it.
        reads = _CountingCandle.reads - 1
        self.assertEqual(perf["entry_date"], candles[3901]["date"])
        # log2(4000) ~= 12 probes, plus a handful of field reads on the entry
        # and horizon candles. A linear scan would need ~3900.
        self.assertLess(
            reads, 40,
            f"entry lookup inspected {reads} candle fields; a binary search "
            "should need ~20 on a 4000-candle history",
        )


if __name__ == "__main__":
    unittest.main()
