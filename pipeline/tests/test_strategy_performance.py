import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import radar.config as config
import radar.db as db
from radar import schema
from radar.compute.strategy_performance import (
    compute_strategy_performance_from_events,
    dedupe_setup_episodes,
    extract_strategy_codes,
    fetch_strategy_events,
    summarize_fwd_values,
    StrategyEvent,
)


class StrategyPerformanceUnitTests(unittest.TestCase):
    def test_s4_setup_episode_dedupes_consecutive_trading_days(self):
        events = [
            StrategyEvent(date="2026-01-02", fwd_5d=1, fwd_10d=1, fwd_20d=1, stock_id="A"),
            StrategyEvent(date="2026-01-05", fwd_5d=2, fwd_10d=2, fwd_20d=2, stock_id="A"),
            StrategyEvent(date="2026-01-06", fwd_5d=3, fwd_10d=3, fwd_20d=3, stock_id="A"),
            StrategyEvent(date="2026-01-06", fwd_5d=4, fwd_10d=4, fwd_20d=4, stock_id="B"),
        ]
        kept = dedupe_setup_episodes(
            events, trading_dates=["2026-01-02", "2026-01-05", "2026-01-06"],
        )
        self.assertEqual([(e.stock_id, e.date) for e in kept], [("A", "2026-01-02"), ("B", "2026-01-06")])

    def test_s4_setup_episode_uses_complete_calendar_not_event_dates(self):
        # 01-05 is a trading day but has no daily_scores/fwd event. The two
        # S4 setup rows are therefore separate episodes, not consecutive.
        events = [
            StrategyEvent(date="2026-01-02", fwd_5d=1, fwd_10d=1, fwd_20d=1, stock_id="A"),
            StrategyEvent(date="2026-01-06", fwd_5d=2, fwd_10d=2, fwd_20d=2, stock_id="A"),
        ]
        kept = dedupe_setup_episodes(
            events, trading_dates=["2026-01-02", "2026-01-05", "2026-01-06"],
        )
        self.assertEqual([e.date for e in kept], ["2026-01-02", "2026-01-06"])

    def test_fetch_s4_setup_episode_uses_daily_price_calendar(self):
        with TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            old_url, old_dir = config.DB_URL, config.DATA_DIR
            try:
                config.DB_URL, config.DATA_DIR = "sqlite:///" + (tmp / "t.db").as_posix(), tmp
                db._engine = None
                db.init_db()
                with db.get_engine().begin() as conn:
                    conn.execute(schema.daily_prices.insert(), [
                        {"stock_id": "A", "date": date, "close": 100, "adj_factor": 1.0}
                        for date in ("2026-01-02", "2026-01-05", "2026-01-06")
                    ])
                    conn.execute(schema.daily_scores.insert(), [
                        {"stock_id": "A", "date": date, "final": 70, "fwd_5d": 1.0,
                         "reasons": '[{"code":"S4_COMPRESSION_SETUP_V2"}]'}
                        for date in ("2026-01-02", "2026-01-06")
                    ])
                events = fetch_strategy_events(min_date="2026-01-02")["S4_COMPRESSION_SETUP_V2"]
                self.assertEqual([event.date for event in events], ["2026-01-02", "2026-01-06"])
            finally:
                if db._engine is not None:
                    db._engine.dispose()
                db._engine = None
                config.DB_URL, config.DATA_DIR = old_url, old_dir

    def test_fetch_s4_setup_warms_up_left_boundary_then_crops_window(self):
        with TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            old_url, old_dir = config.DB_URL, config.DATA_DIR
            try:
                config.DB_URL, config.DATA_DIR = "sqlite:///" + (tmp / "t.db").as_posix(), tmp
                db._engine = None
                db.init_db()
                with db.get_engine().begin() as conn:
                    # 01-01 → 01-02 is one continuous setup episode. 01-05
                    # breaks it; 01-06 begins a new episode.
                    conn.execute(schema.daily_prices.insert(), [
                        {"stock_id": "A", "date": date, "close": 100, "adj_factor": 1.0}
                        for date in ("2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06")
                    ])
                    conn.execute(schema.daily_scores.insert(), [
                        {"stock_id": "A", "date": "2026-01-01", "final": 70, "fwd_5d": None,
                         "reasons": '[{"code":"S4_COMPRESSION_SETUP_V2"}]'},
                        {"stock_id": "A", "date": "2026-01-02", "final": 70, "fwd_5d": 1.0,
                         "reasons": '[{"code":"S4_COMPRESSION_SETUP_V2"}]'},
                        {"stock_id": "A", "date": "2026-01-06", "final": 70, "fwd_5d": 2.0,
                         "reasons": '[{"code":"S4_COMPRESSION_SETUP_V2"}]'},
                    ])
                events = fetch_strategy_events(min_date="2026-01-02")["S4_COMPRESSION_SETUP_V2"]
                # The 01-02 row is continuation-only and is excluded after
                # warm-up; 01-06 is the first row of a fresh in-window episode.
                self.assertEqual([event.date for event in events], ["2026-01-06"])
            finally:
                if db._engine is not None:
                    db._engine.dispose()
                db._engine = None
                config.DB_URL, config.DATA_DIR = old_url, old_dir

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
