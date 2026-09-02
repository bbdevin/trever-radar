import json
import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sqlalchemy import event

import radar.config as config
import radar.db as db
from radar import schema
from radar.cli import main
from radar.compute.branch_point_in_time_report import get_read_only_engine
from radar.compute.branch_point_in_time_series import (
    build_branch_point_in_time_series,
    plan_as_of_walk,
    validate_series_window,
    write_branch_point_in_time_series,
)


def _market_days(start: date, count: int) -> list[str]:
    days: list[str] = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current.isoformat())
        current += timedelta(days=1)
    return days


class BranchPointInTimeSeriesTests(unittest.TestCase):
    """The fixture is built so each as_of window sees a different slice.

    Buy and sell episodes are still counted independently everywhere; nothing in
    these tests pairs a buy with a sell or asserts a profit or win rate.
    """

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.old_url, self.old_dir = config.DB_URL, config.DATA_DIR
        self.db_path = self.tmp_path / "series.db"
        config.DB_URL = "sqlite:///" + self.db_path.as_posix()
        self.series_db_url = config.DB_URL
        config.DATA_DIR = self.tmp_path
        db._engine = None
        db.init_db()
        self.days = _market_days(date(2026, 1, 5), 40)
        # Even market days close at 100, odd at 200, so any 20-day window spans
        # exactly 100..200 and a percentile is arithmetically predictable.
        a_close = {index: (100 if index % 2 == 0 else 200) for index in range(len(self.days))}
        a_close[24] = 200   # buy at the top of its window
        a_close[26] = 200   # sell at the top of its window
        a_close[29] = 50    # only ever read as a forward-five exit close
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": "A", "name": "Alpha", "market": "twse", "type": "stock"},
                {"id": "B", "name": "Beta", "market": "twse", "type": "stock"},
            ])
            prices = []
            for index, day in enumerate(self.days):
                prices.append({
                    "stock_id": "A", "date": day, "open": 100,
                    "close": a_close[index], "adj_factor": 1.0,
                })
                prices.append({
                    "stock_id": "B", "date": day, "open": 100,
                    "close": 100 if index % 2 == 0 else 200, "adj_factor": 1.0,
                })
            conn.execute(schema.daily_prices.insert(), prices)
            conn.execute(schema.tracked_branches.insert(), [
                {"branch_name": "STEADY", "source": "manual", "added_at": self.days[0]},
                {"branch_name": "SPORADIC", "source": "manual", "added_at": self.days[0]},
            ])
            conn.execute(schema.branch_dim.insert(), [
                {"id": 1, "branch_key": "steady", "branch_name": "STEADY"},
                {"id": 2, "branch_key": "sporadic", "branch_name": "SPORADIC"},
            ])
            conn.execute(schema.branch_trades_raw.insert(), [
                {"stock_id": "A", "date": self.days[20], "branch_id": 1, "net_lots": 10, "pct": 1.0, "source": "fixture"},
                {"stock_id": "A", "date": self.days[22], "branch_id": 1, "net_lots": -9, "pct": -1.0, "source": "fixture"},
                {"stock_id": "A", "date": self.days[24], "branch_id": 1, "net_lots": 11, "pct": 1.0, "source": "fixture"},
                {"stock_id": "A", "date": self.days[26], "branch_id": 1, "net_lots": -8, "pct": -1.0, "source": "fixture"},
                {"stock_id": "A", "date": self.days[28], "branch_id": 1, "net_lots": 12, "pct": 1.0, "source": "fixture"},
                # SPORADIC is observed on one market day only, so it enters the
                # series late and is genuinely absent from the early as_of dates.
                {"stock_id": "B", "date": self.days[33], "branch_id": 2, "net_lots": 7, "pct": 1.0, "source": "fixture"},
            ])
        self.expected_as_of = [self.days[index] for index in (30, 32, 34, 36, 38)]
        # A Saturday: the walk must never land on it.
        self.as_of_to_calendar = (
            date.fromisoformat(self.days[39]) + timedelta(days=1)
        ).isoformat()

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self.old_url, self.old_dir
        self.tmp.cleanup()

    def _series(self):
        return build_branch_point_in_time_series(
            as_of_from=self.days[30], as_of_to=self.as_of_to_calendar,
            step=2, window_days=10,
        )

    @staticmethod
    def _entity(report, key, name):
        return next(item for item in report[key] if item["branch_name"] == name)

    def test_as_of_walk_lands_only_on_market_trading_days(self):
        report = self._series()
        as_of_dates = report["coverage"]["as_of_dates"]
        self.assertEqual(as_of_dates, self.expected_as_of)
        self.assertTrue(set(as_of_dates) <= set(self.days))
        self.assertNotIn(self.as_of_to_calendar, as_of_dates)
        self.assertTrue(all(date.fromisoformat(day).weekday() < 5 for day in as_of_dates))
        self.assertEqual(report["coverage"]["as_of_dates_evaluated"], 5)
        self.assertEqual(report["coverage"]["market_trading_days_in_as_of_range"], 10)
        self.assertEqual(report["metadata"]["step_market_days"], 2)

    def test_trailing_window_boundary_is_inclusive_and_truncation_is_flagged(self):
        report = self._series()
        windows = {entry["as_of"]: entry for entry in report["per_as_of"]}
        for as_of in self.expected_as_of:
            self.assertEqual(windows[as_of]["window_market_days"], 10)
            self.assertEqual(windows[as_of]["window_to"], as_of)
            self.assertFalse(windows[as_of]["window_truncated"])
        self.assertEqual(windows[self.days[32]]["window_from"], self.days[23])
        # days[24] sits on the window's first-included boundary; days[22] falls
        # one market day outside it and must not be counted.
        self.assertEqual(windows[self.days[32]]["summary"]["buy_episode_count"], 2)
        self.assertEqual(windows[self.days[32]]["summary"]["sell_episode_count"], 1)
        self.assertEqual(windows[self.days[30]]["window_from"], self.days[21])
        self.assertEqual(windows[self.days[30]]["summary"]["sell_episode_count"], 2)

        short = build_branch_point_in_time_series(
            as_of_from=self.days[2], as_of_to=self.days[2], step=1, window_days=10,
        )
        entry = short["per_as_of"][0]
        self.assertTrue(entry["window_truncated"])
        self.assertEqual(entry["window_from"], self.days[0])
        self.assertEqual(entry["window_market_days"], 3)
        self.assertEqual(
            short["coverage"]["as_of_dates_with_truncated_window"], [self.days[2]],
        )
        self.assertEqual(
            short["coverage"]["as_of_dates_with_no_branch_stock_rows"], [self.days[2]],
        )
        self.assertEqual(short["branch_series"], [])

    def test_entity_present_in_only_some_as_of_dates_is_not_interpolated(self):
        report = self._series()
        sporadic = self._entity(report, "branch_series", "SPORADIC")
        self.assertEqual(sporadic["as_of_dates_evaluated"], 5)
        self.assertEqual(sporadic["as_of_dates_present"], 3)
        self.assertEqual(sporadic["as_of_dates_absent"], 2)
        self.assertEqual(sporadic["presence_rate_pct"], 60.0)
        self.assertEqual(
            sporadic["present_as_of_dates"],
            [self.days[34], self.days[36], self.days[38]],
        )
        self.assertEqual(
            sporadic["absent_as_of_dates"], [self.days[30], self.days[32]],
        )
        # Series are aligned with the present dates only; gaps are never filled.
        self.assertEqual(sporadic["buy_episode_count_series"], [1, 1, 1])
        self.assertEqual(sporadic["observed_trade_rows_series"], [1, 1, 1])

        steady = self._entity(report, "branch_series", "STEADY")
        self.assertEqual(steady["as_of_dates_present"], 4)
        self.assertEqual(steady["absent_as_of_dates"], [self.days[38]])
        self.assertEqual(steady["buy_episode_count_series"], [2, 2, 1, 1])
        self.assertEqual(steady["sell_episode_count_series"], [2, 1, 1, 0])

        pair = next(
            item for item in report["branch_stock_series"]
            if item["branch_name"] == "SPORADIC" and item["stock_id"] == "B"
        )
        self.assertEqual(pair["stock_name"], "Beta")
        self.assertEqual(pair["as_of_dates_absent"], 2)

    def test_dispersion_is_reported_alongside_central_tendency(self):
        report = self._series()
        steady = self._entity(report, "branch_series", "STEADY")
        low_buy = steady["rates"]["low_buy_rate"]
        self.assertEqual(low_buy["values"], [50.0, 50.0, 100.0, 100.0])
        stats = low_buy["stats"]
        self.assertEqual(stats["count"], 4)
        self.assertEqual(stats["mean"], 75.0)
        self.assertEqual(stats["min"], 50.0)
        self.assertEqual(stats["max"], 100.0)
        self.assertEqual(stats["range"], 50.0)
        self.assertGreater(stats["stdev"], 0.0)

        fwd5 = steady["rates"]["fwd5_positive_rate"]
        self.assertEqual(fwd5["values"], [0.0, 0.0, 100.0, 100.0])
        self.assertEqual(fwd5["stats"]["range"], 100.0)

        # A single observation has no defined sample spread and must say so
        # rather than presenting a bare mean.
        sporadic_fwd5 = self._entity(report, "branch_series", "SPORADIC")["rates"]["fwd5_positive_rate"]
        self.assertEqual(sporadic_fwd5["stats"]["count"], 1)
        self.assertIsNone(sporadic_fwd5["stats"]["stdev"])
        self.assertEqual(sporadic_fwd5["stats"]["mean"], 0.0)

        counts = steady["buy_episode_count_stats"]
        self.assertEqual((counts["min"], counts["max"], counts["range"]), (1.0, 2.0, 1.0))
        self.assertIsNotNone(counts["stdev"])

    def test_unknown_and_insufficient_counts_survive_aggregation(self):
        report = self._series()
        steady = self._entity(report, "branch_series", "STEADY")
        high_sell = steady["rates"]["high_sell_rate"]
        # The last present as_of window contains no sell episode at all, so the
        # rate is undefined there and must not be silently dropped.
        self.assertEqual(high_sell["as_of_dates_defined"], 3)
        self.assertEqual(high_sell["as_of_dates_undefined"], 1)
        self.assertEqual(high_sell["values"], [50.0, 100.0, 100.0])
        self.assertEqual(
            steady["low_buy_high_sell_status_counts"], {"evidence": 3, "insufficient": 1},
        )
        totals = steady["known_unknown_totals"]
        self.assertEqual(totals["fwd5_unknown_buy_episodes_total"], 2)
        self.assertEqual(totals["fwd5_unknown_buy_episodes_max_on_one_as_of"], 1)
        self.assertEqual(totals["fwd5_matured_buy_episodes_total"], 4)
        self.assertEqual(totals["buy_price_percentile_known_total"], 6)
        self.assertEqual(totals["buy_price_percentile_unknown_total"], 0)

        # A rate over one known episode must not read like one over many.
        self.assertEqual(steady["rates"]["low_buy_rate"]["episode_denominator_series"], [2, 2, 1, 1])
        self.assertEqual(steady["rates"]["low_buy_rate"]["episode_denominator_stats"]["min"], 1.0)
        self.assertEqual(steady["rates"]["low_buy_rate"]["episode_denominator_stats"]["max"], 2.0)
        self.assertEqual(steady["rates"]["low_buy_rate"]["pooled_denominator"], 6)
        self.assertEqual(steady["rates"]["low_buy_rate"]["pooled_numerator"], 4)
        self.assertEqual(steady["rates"]["low_buy_rate"]["pooled_rate"], 66.666667)

        sporadic = self._entity(report, "branch_series", "SPORADIC")
        sporadic_totals = sporadic["known_unknown_totals"]
        self.assertEqual(sporadic_totals["fwd5_unknown_buy_episodes_total"], 2)
        self.assertEqual(sporadic_totals["fwd5_matured_buy_episodes_total"], 1)
        self.assertEqual(sporadic["rates"]["fwd5_positive_rate"]["as_of_dates_undefined"], 2)
        self.assertEqual(report["metadata"]["buy_sell_pairing"], False)
        self.assertEqual(report["metadata"]["trade_profit_attribution"], False)

    def test_series_reads_are_select_only_and_leave_the_database_untouched(self):
        db._engine.dispose()
        db_before = self.db_path.read_bytes()
        wal_path = self.tmp_path / "series.db-wal"
        wal_before = wal_path.read_bytes() if wal_path.exists() else None

        statements: list[str] = []
        engine = get_read_only_engine()

        def capture(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement.lstrip().lower())

        event.listen(engine, "before_cursor_execute", capture)
        try:
            with patch(
                "radar.compute.branch_point_in_time_report.get_read_only_engine",
                return_value=engine,
            ), patch(
                "radar.compute.branch_point_in_time_series.get_read_only_engine",
                return_value=engine,
            ):
                out = self.tmp_path / "series.json"
                first = write_branch_point_in_time_series(
                    as_of_from=self.days[30], as_of_to=self.as_of_to_calendar,
                    step=2, window_days=10, out=out,
                )
                second = self._series()
        finally:
            event.remove(engine, "before_cursor_execute", capture)
            engine.dispose()

        self.assertEqual(first, second)
        self.assertTrue(statements)
        self.assertTrue(all(statement.startswith("select") for statement in statements))
        self.assertEqual(self.db_path.read_bytes(), db_before)
        if wal_before is not None:
            self.assertEqual(wal_path.read_bytes(), wal_before)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8")), first)
        self.assertEqual(first["metadata"]["read_only"], True)
        self.assertEqual(first["metadata"]["schema_changes"], False)

    def test_writer_rejects_database_and_sidecars_as_output(self):
        before = self.db_path.read_bytes()
        for candidate in (
            self.db_path,
            self.tmp_path / "series.db-wal",
            self.tmp_path / "series.db-shm",
            self.tmp_path / "series.db-journal",
        ):
            with self.assertRaisesRegex(ValueError, "must not"):
                write_branch_point_in_time_series(
                    as_of_from=self.days[30], as_of_to=self.days[38],
                    step=2, window_days=10, out=candidate,
                )
        self.assertEqual(self.db_path.read_bytes(), before)

    def test_missing_configured_db_is_not_created(self):
        missing = self.tmp_path / "missing.db"
        config.DB_URL = "sqlite:///" + missing.as_posix()
        try:
            with self.assertRaises(FileNotFoundError):
                self._series()
            self.assertFalse(missing.exists())
        finally:
            config.DB_URL = self.series_db_url

    def test_cli_writes_series_json(self):
        out = self.tmp_path / "cli_series.json"
        main([
            "branch-point-in-time-series",
            "--as-of-from", self.days[30],
            "--as-of-to", self.as_of_to_calendar,
            "--step", "2",
            "--window-days", "10",
            "--out", str(out),
        ])
        payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(payload["coverage"]["as_of_dates"], self.expected_as_of)
        self.assertEqual(payload["metadata"]["window_market_days"], 10)
        self.assertEqual(payload["coverage"]["branch_entity_count"], 2)

    def test_walk_planning_and_validation(self):
        trading_days = self.days
        plan = plan_as_of_walk(
            trading_days=trading_days, as_of_from=self.days[30],
            as_of_to=self.as_of_to_calendar, step=3, window_days=5,
        )
        self.assertEqual(
            [entry["as_of"] for entry in plan],
            [self.days[30], self.days[33], self.days[36], self.days[39]],
        )
        self.assertEqual(plan[0]["window_from"], self.days[26])

        with self.assertRaisesRegex(ValueError, "as-of-from must be"):
            validate_series_window(
                as_of_from="2026-02-02", as_of_to="2026-02-01", step=1, window_days=5,
            )
        with self.assertRaisesRegex(ValueError, "step must be"):
            validate_series_window(
                as_of_from="2026-02-01", as_of_to="2026-02-02", step=0, window_days=5,
            )
        with self.assertRaisesRegex(ValueError, "window-days must be"):
            validate_series_window(
                as_of_from="2026-02-01", as_of_to="2026-02-02", step=1, window_days=0,
            )
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            validate_series_window(
                as_of_from="2026/02/01", as_of_to="2026-02-02", step=1, window_days=5,
            )


if __name__ == "__main__":
    unittest.main()
