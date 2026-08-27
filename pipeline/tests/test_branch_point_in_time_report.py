import json
import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

import radar.config as config
import radar.db as db
from radar import schema
from radar.cli import main
from radar.compute.branch_point_in_time_report import (
    build_branch_point_in_time_report,
    get_read_only_engine,
    validate_report_window,
    write_branch_point_in_time_report,
)


def _market_days(start: date, count: int) -> list[str]:
    days: list[str] = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current.isoformat())
        current += timedelta(days=1)
    return days


class BranchPointInTimeReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.old_url, self.old_dir = config.DB_URL, config.DATA_DIR
        self.db_path = self.tmp_path / "report.db"
        config.DB_URL = "sqlite:///" + self.db_path.as_posix()
        self.report_db_url = config.DB_URL
        config.DATA_DIR = self.tmp_path
        db._engine = None
        db.init_db()
        self.days = _market_days(date(2026, 1, 2), 28)
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": "A", "name": "Alpha", "market": "twse", "type": "stock"},
                {"id": "B", "name": "Beta", "market": "twse", "type": "stock"},
            ])
            prices = []
            for index, day in enumerate(self.days):
                close = 100 if index % 2 == 0 else 200
                if index == 21:
                    close = 150
                if index == 26:
                    close = 110
                if index == 1:
                    close = None
                prices.append({"stock_id": "A", "date": day, "open": 100, "close": close, "adj_factor": 1.0})
                # B has an event-day price gap; A's bar still makes that day a
                # market trading day, so the missing value must remain unknown.
                prices.append({
                    "stock_id": "B", "date": day, "open": 100,
                    "close": None if index in (1, 21) else 100,
                    "adj_factor": 1.0,
                })
            conn.execute(schema.daily_prices.insert(), prices)
            conn.execute(schema.tracked_branches.insert(), [
                {"branch_name": "MANUAL", "source": "manual", "added_at": self.days[0]},
                {"branch_name": "MISSING_PRICE", "source": "manual", "added_at": self.days[0]},
                {"branch_name": "CALENDAR_BREAK", "source": "manual", "added_at": self.days[0]},
                {"branch_name": "MANUAL_FUTURE", "source": "manual", "added_at": "2026-12-31"},
                {"branch_name": "MANUAL_UNKNOWN", "source": "manual", "added_at": None},
            ])
            conn.execute(schema.branch_rankings.insert(), {
                "branch_name": "RANK_ONLY", "as_of": self.days[20], "rank_score": 70,
                "samples": 5, "source": "candidate",
            })
            conn.execute(schema.branch_dim.insert(), [
                {"id": 1, "branch_key": "manual", "branch_name": "MANUAL"},
                {"id": 2, "branch_key": "rank", "branch_name": "RANK_ONLY"},
                {"id": 3, "branch_key": "missing", "branch_name": "MISSING_PRICE"},
                {"id": 4, "branch_key": "calendar", "branch_name": "CALENDAR_BREAK"},
            ])
            conn.execute(schema.branch_trades_raw.insert(), [
                # 21/22 are adjacent market days and must form one buy episode.
                {"stock_id": "A", "date": self.days[21], "branch_id": 1, "net_lots": 10, "pct": 1.0, "source": "fixture"},
                {"stock_id": "A", "date": self.days[22], "branch_id": 1, "net_lots": 11, "pct": 1.2, "source": "fixture"},
                # This is a separate, un-matured buy episode (five following
                # market days do not exist at as_of).
                {"stock_id": "A", "date": self.days[25], "branch_id": 1, "net_lots": 12, "pct": 1.0, "source": "fixture"},
                # pct is absent: observed in coverage but not an event.
                {"stock_id": "A", "date": self.days[24], "branch_id": 1, "net_lots": 13, "pct": None, "source": "fixture"},
                # Negative pct must qualify for a sell by absolute value.
                {"stock_id": "A", "date": self.days[23], "branch_id": 1, "net_lots": -9, "pct": -1.0, "source": "fixture"},
                {"stock_id": "A", "date": self.days[21], "branch_id": 2, "net_lots": 8, "pct": 1.0, "source": "fixture"},
                {"stock_id": "B", "date": self.days[21], "branch_id": 3, "net_lots": 8, "pct": 1.0, "source": "fixture"},
                # day 1 exists in daily_prices but every close is null; it is
                # still a market-day calendar entry and splits these episodes.
                {"stock_id": "A", "date": self.days[0], "branch_id": 4, "net_lots": 8, "pct": 1.0, "source": "fixture"},
                {"stock_id": "A", "date": self.days[2], "branch_id": 4, "net_lots": 9, "pct": 1.0, "source": "fixture"},
            ])

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self.old_url, self.old_dir
        self.tmp.cleanup()

    def _report(self):
        return build_branch_point_in_time_report(
            as_of=self.days[-1], date_from=self.days[0], date_to=self.days[25],
        )

    def test_merges_market_day_episodes_and_uses_abs_sell(self):
        report = self._report()
        episodes = [
            item for item in report["episode_samples"]
            if item["branch_name"] == "MANUAL" and item["stock_id"] == "A"
        ]
        buys = [item for item in episodes if item["direction"] == "buy"]
        sells = [item for item in episodes if item["direction"] == "sell"]
        self.assertEqual([(item["start_date"], item["end_date"], item["trading_day_count"]) for item in buys], [
            (self.days[21], self.days[22], 2),
            (self.days[25], self.days[25], 1),
        ])
        self.assertEqual(len(sells), 1)
        self.assertEqual(sells[0]["start_date"], self.days[23])
        self.assertIsNone(sells[0]["low_buy"])
        self.assertIsInstance(sells[0]["high_sell"], bool)

    def test_percentile_uses_only_past_window_and_fwd_requires_maturity(self):
        report = self._report()
        first_buy = next(
            item for item in report["episode_samples"]
            if item["branch_name"] == "MANUAL" and item["direction"] == "buy"
            and item["start_date"] == self.days[21]
        )
        # The first 20 closes range 100..200 and event close is 150.  Later
        # values cannot change the point-in-time percentile.
        self.assertEqual(first_buy["price_percentile_20d"], 0.5)
        self.assertEqual(first_buy["fwd5_status"], "matured")
        self.assertAlmostEqual(first_buy["fwd5_pct"], 10.0)
        late_buy = next(
            item for item in report["episode_samples"]
            if item["branch_name"] == "MANUAL" and item["direction"] == "buy"
            and item["start_date"] == self.days[25]
        )
        self.assertEqual(late_buy["fwd5_status"], "unknown")
        self.assertEqual(late_buy["fwd5_reason"], "insufficient_mature_market_window")

    def test_missing_price_and_pct_stay_unknown_and_coverage_is_honest(self):
        report = self._report()
        missing = next(item for item in report["episode_samples"] if item["branch_name"] == "MISSING_PRICE")
        self.assertEqual(missing["price_percentile_status"], "unknown")
        self.assertEqual(missing["price_percentile_reason"], "missing_event_close")
        self.assertIsNone(missing["low_buy"])
        self.assertIsNone(missing["high_sell"])
        self.assertEqual(report["coverage"]["trade_rows_missing_pct"], 1)
        self.assertIn("must not be interpreted as no sell", report["coverage"]["branch_trade_capture_note"])

    def test_all_null_close_market_date_still_breaks_episodes(self):
        report = self._report()
        calendar_episodes = [
            item for item in report["episode_samples"]
            if item["branch_name"] == "CALENDAR_BREAK"
        ]
        self.assertEqual(
            [(item["start_date"], item["end_date"]) for item in calendar_episodes],
            [(self.days[0], self.days[0]), (self.days[2], self.days[2])],
        )
        self.assertEqual(report["coverage"]["market_trading_days_through_as_of"], len(self.days))

    def test_manual_universe_excludes_unknown_and_future_timestamps(self):
        report = self._report()
        coverage = report["coverage"]
        self.assertEqual(coverage["manual_tracked_unknown_timestamp_count"], 1)
        self.assertEqual(coverage["manual_tracked_unknown_timestamp_names"], ["MANUAL_UNKNOWN"])
        self.assertEqual(coverage["universe_source_counts"]["manual_tracked"], 3)

    def test_candidate_universe_fixed_output_and_read_only_sql(self):
        statements = []
        engine = get_read_only_engine()

        def capture(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement.lstrip().lower())

        event.listen(engine, "before_cursor_execute", capture)
        try:
            with patch("radar.compute.branch_point_in_time_report.get_read_only_engine", return_value=engine):
                first = self._report()
                second = self._report()
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        self.assertEqual(first, second)
        self.assertTrue(statements)
        self.assertTrue(all(statement.startswith("select") for statement in statements))
        sources = next(item["universe_sources"] for item in first["branch_stock_rows"] if item["branch_name"] == "RANK_ONLY")
        self.assertEqual(sources, ["ranking_identifiable"])
        self.assertEqual(first["metadata"]["read_only"], True)

    def test_writer_and_cli_emit_json(self):
        direct_out = self.tmp_path / "direct.json"
        report = write_branch_point_in_time_report(
            as_of=self.days[-1], date_from=self.days[0], date_to=self.days[25], out=direct_out,
        )
        self.assertEqual(json.loads(direct_out.read_text(encoding="utf-8")), report)
        cli_out = self.tmp_path / "cli.json"
        main([
            "branch-point-in-time-report", "--as-of", self.days[-1],
            "--from", self.days[0], "--to", self.days[25], "--out", str(cli_out),
        ])
        self.assertEqual(json.loads(cli_out.read_text(encoding="utf-8"))["metadata"]["as_of"], self.days[-1])

    def test_read_only_engine_rejects_dml(self):
        engine = get_read_only_engine()
        try:
            with engine.connect() as conn:
                with self.assertRaises(OperationalError):
                    conn.execute(text("UPDATE stocks SET name = 'mutated' WHERE id = 'A'"))
        finally:
            engine.dispose()

    def test_missing_configured_db_is_not_created(self):
        missing = self.tmp_path / "missing.db"
        config.DB_URL = "sqlite:///" + missing.as_posix()
        try:
            with self.assertRaises(FileNotFoundError):
                self._report()
            self.assertFalse(missing.exists())
        finally:
            config.DB_URL = self.report_db_url

    def test_writer_rejects_database_as_output_before_querying(self):
        before = self.db_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "must not be"):
            write_branch_point_in_time_report(
                as_of=self.days[-1], date_from=self.days[0], date_to=self.days[25], out=self.db_path,
            )
        self.assertEqual(self.db_path.read_bytes(), before)

    def test_window_validation(self):
        with self.assertRaisesRegex(ValueError, "from must be"):
            validate_report_window(as_of="2026-01-02", date_from="2026-01-03", date_to="2026-01-02")
        with self.assertRaisesRegex(ValueError, "to must be"):
            validate_report_window(as_of="2026-01-02", date_from="2026-01-01", date_to="2026-01-03")
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            validate_report_window(as_of="2026/01/02", date_from="2026-01-01", date_to="2026-01-02")


if __name__ == "__main__":
    unittest.main()
