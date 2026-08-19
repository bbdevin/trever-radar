import unittest

from radar.compute.strategy_performance import (
    compute_strategy_performance_from_events,
    extract_strategy_codes,
    summarize_fwd_values,
    StrategyEvent,
)


class StrategyPerformanceUnitTests(unittest.TestCase):
    def test_extract_strategy_codes_alias(self):
        items = [
            {"code": "S1_REBOUND_RELAXED", "points": 15},
            {"code": "S2_BREAKOUT20"},
            {"code": "UNKNOWN"},
        ]
        codes = extract_strategy_codes(items)
        self.assertEqual(set(codes), {"S1_REBOUND", "S2_BREAKOUT20"})

    def test_summarize_fwd_values(self):
        # win_rate uses strictly > 0
        s = summarize_fwd_values([5.0, -1.0, 0.0])
        self.assertEqual(s["samples"], 3)
        self.assertAlmostEqual(s["win_rate"], 100.0 * 1 / 3, places=6)
        self.assertAlmostEqual(s["avg_ret"], (5.0 - 1.0 + 0.0) / 3, places=6)
        self.assertEqual(s["median_ret"], 0.0)

    def test_compute_strategy_performance_from_events_recent(self):
        # Two events, only one has fwd_20d.
        events_by_code = {
            "S2_BREAKOUT20": [
                StrategyEvent(date="2026-01-01", fwd_5d=1.0, fwd_10d=2.0, fwd_20d=None),
                StrategyEvent(date="2026-01-10", fwd_5d=-1.0, fwd_10d=None, fwd_20d=3.0),
            ]
        }
        perf = compute_strategy_performance_from_events(events_by_code, recent_events=1)
        p = perf["S2_BREAKOUT20"]

        # Horizon 5: both events are matured (2 samples)
        h5 = p["per_horizon"]["h5"]
        self.assertEqual(h5["samples"], 2)
        self.assertAlmostEqual(h5["win_rate"], 50.0, places=6)  # 1/2 > 0

        # Horizon 20: only one matured event (3.0%)
        h20 = p["per_horizon"]["h20"]
        self.assertEqual(h20["samples"], 1)
        self.assertAlmostEqual(h20["win_rate"], 100.0, places=6)
        self.assertAlmostEqual(h20["avg_ret"], 3.0, places=6)
        self.assertAlmostEqual(h20["median_ret"], 3.0, places=6)

        # Recent20 uses last matured event only (same 20d matured set)
        recent20 = p["recent20"]
        self.assertEqual(recent20["samples"], 1)
        self.assertAlmostEqual(recent20["win_rate"], 100.0, places=6)


if __name__ == "__main__":
    unittest.main()

