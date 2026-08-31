import os
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sqlalchemy import event

import radar.config as config
import radar.db as db
from radar import schema
from radar.compute.phase2_diff_report import build_phase2_diff_report
from radar.compute.read_only_sqlite import get_read_only_sqlite_engine
from radar.compute.strategy_performance import (
    build_phase3_strategy_performance_report,
    fetch_strategy_events,
)


class ReadOnlyReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.old_url, self.old_dir = config.DB_URL, config.DATA_DIR
        self.db_path = self.tmp_path / "report.db"
        config.DB_URL = "sqlite:///" + self.db_path.as_posix()
        config.DATA_DIR = self.tmp_path
        db._engine = None
        db.init_db()
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), {
                "id": "A", "name": "Alpha", "market": "twse", "type": "stock",
            })
            conn.execute(schema.daily_prices.insert(), {
                "stock_id": "A", "date": "2026-01-02", "open": 100,
                "close": 101, "adj_factor": 1.0,
            })
            conn.execute(schema.indicators_daily.insert(), {
                "stock_id": "A", "date": "2026-01-02",
                "reasons": '[{"code":"S2_BREAKOUT20","points":20}]',
            })
            conn.execute(schema.daily_scores.insert(), {
                "stock_id": "A", "date": "2026-01-02", "tech_score": 50,
                "inst_score": 50, "final": 50, "risk_penalty": 0,
                "fwd_5d": 2.0, "fwd_10d": 3.0, "fwd_20d": 4.0,
            })

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self.old_url, self.old_dir
        self.tmp.cleanup()

    def test_active_wal_reports_do_not_init_or_mutate_database_or_sidecars(self):
        protected_before = {"database": self.db_path.read_bytes()}
        sidecars_before = {
            suffix: (
                (self.tmp_path / f"report.db{suffix}").exists(),
                (self.tmp_path / f"report.db{suffix}").read_bytes()
                if (self.tmp_path / f"report.db{suffix}").exists() else None,
            )
            for suffix in ("-wal", "-journal")
        }
        self.assertTrue(sidecars_before["-wal"][0], "fixture must exercise active WAL")
        self.assertGreater(
            len(sidecars_before["-wal"][1]), 32,
            "fixture must retain uncheckpointed WAL frames",
        )
        self.assertTrue((self.tmp_path / "report.db-shm").is_file(), "fixture must exercise active SHM")
        sidecars_before["-shm"] = (
            True, (self.tmp_path / "report.db-shm").read_bytes(),
        )
        statements: list[str] = []
        engine = get_read_only_sqlite_engine(
            report_name="test", required_tables=("daily_scores", "indicators_daily", "daily_prices", "stocks"),
        )

        def capture(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement.lstrip().lower())

        event.listen(engine, "before_cursor_execute", capture)
        try:
            with patch("radar.db.init_db", side_effect=AssertionError("report must not initialise DB")):
                with patch(
                    "radar.compute.strategy_performance.get_read_only_sqlite_engine",
                    return_value=engine,
                ):
                    events = fetch_strategy_events(min_date="2026-01-02")
            self.assertEqual(len(events["S2_BREAKOUT20"]), 1)
        finally:
            event.remove(engine, "before_cursor_execute", capture)
            engine.dispose()

        phase2_engine = get_read_only_sqlite_engine(
            report_name="test", required_tables=("daily_scores", "indicators_daily", "stocks"),
        )
        event.listen(phase2_engine, "before_cursor_execute", capture)
        try:
            with patch("radar.db.init_db", side_effect=AssertionError("report must not initialise DB")):
                with patch(
                    "radar.compute.phase2_diff_report.get_read_only_sqlite_engine",
                    return_value=phase2_engine,
                ):
                    info = build_phase2_diff_report("20260102", str(self.tmp_path / "diff.md"))
            self.assertEqual(info["rows"], 1)
        finally:
            event.remove(phase2_engine, "before_cursor_execute", capture)
            phase2_engine.dispose()

        self.assertTrue(statements)
        self.assertTrue(all(statement.startswith("select") for statement in statements))
        self.assertEqual(self.db_path.read_bytes(), protected_before["database"])
        sidecars_after = {
            suffix: (
                (self.tmp_path / f"report.db{suffix}").exists(),
                (self.tmp_path / f"report.db{suffix}").read_bytes()
                if (self.tmp_path / f"report.db{suffix}").exists() else None,
            )
            for suffix in ("-wal", "-shm", "-journal")
        }
        self.assertEqual(sidecars_after["-wal"], sidecars_before["-wal"])
        self.assertEqual(sidecars_after["-journal"], sidecars_before["-journal"])
        # SQLite's mode=ro WAL reader may update SHM reader-lock/read-mark
        # coordination. It must never remove or truncate that coordination file.
        self.assertTrue(sidecars_after["-shm"][0])
        self.assertGreaterEqual(
            len(sidecars_after["-shm"][1]), len(sidecars_before["-shm"][1]),
        )

    def test_missing_database_fails_without_creating_a_file(self):
        missing = self.tmp_path / "missing.db"
        config.DB_URL = "sqlite:///" + missing.as_posix()
        try:
            with self.assertRaisesRegex(FileNotFoundError, "does not exist"):
                fetch_strategy_events()
            with self.assertRaisesRegex(FileNotFoundError, "does not exist"):
                build_phase2_diff_report(out=str(self.tmp_path / "never.md"))
            self.assertFalse(missing.exists())
        finally:
            config.DB_URL = "sqlite:///" + self.db_path.as_posix()

    def test_non_sqlite_and_missing_table_fail_closed(self):
        invalid = self.tmp_path / "not-sqlite.db"
        invalid.write_text("not a sqlite database", encoding="utf-8")
        config.DB_URL = "sqlite:///" + invalid.as_posix()
        try:
            with self.assertRaisesRegex(ValueError, "not a valid SQLite"):
                fetch_strategy_events()
        finally:
            config.DB_URL = "postgresql://example.invalid/radar"

        try:
            with self.assertRaisesRegex(ValueError, "physical SQLite"):
                build_phase2_diff_report(out=str(self.tmp_path / "never.md"))
        finally:
            config.DB_URL = "sqlite:///" + self.db_path.as_posix()

        empty = self.tmp_path / "empty.db"
        conn = sqlite3.connect(empty)
        try:
            conn.execute("VACUUM")
        finally:
            conn.close()
        config.DB_URL = "sqlite:///" + empty.as_posix()
        try:
            with self.assertRaisesRegex(RuntimeError, "missing required SQLite table"):
                fetch_strategy_events()
            with self.assertRaisesRegex(RuntimeError, "missing required SQLite table"):
                build_phase2_diff_report(out=str(self.tmp_path / "never.md"))
        finally:
            config.DB_URL = "sqlite:///" + self.db_path.as_posix()

    def test_reports_reject_database_as_output(self):
        before = self.db_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "must not be"):
            build_phase2_diff_report("20260102", str(self.db_path))
        with self.assertRaisesRegex(ValueError, "must not be"):
            build_phase3_strategy_performance_report(
                date_from="2026-01-02", out=str(self.db_path),
            )
        self.assertEqual(self.db_path.read_bytes(), before)

    def test_reports_reject_database_hardlink_and_sidecars_as_output(self):
        hardlink = self.tmp_path / "report-hardlink.db"
        os.link(self.db_path, hardlink)
        with self.assertRaisesRegex(ValueError, "alias"):
            build_phase2_diff_report("20260102", str(hardlink))

        symlink = self.tmp_path / "report-symlink.db"
        try:
            os.symlink(self.db_path, symlink)
        except OSError as exc:
            self.skipTest(f"symlinks unavailable in this environment: {exc}")
        with self.assertRaisesRegex(ValueError, "database"):
            build_phase3_strategy_performance_report(
                date_from="2026-01-02", out=str(symlink),
            )

        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = self.tmp_path / f"report.db{suffix}"
            with self.assertRaisesRegex(ValueError, "sidecar"):
                build_phase2_diff_report("20260102", str(sidecar))

        wal_hardlink = self.tmp_path / "report-wal-hardlink.db"
        os.link(self.tmp_path / "report.db-wal", wal_hardlink)
        with self.assertRaisesRegex(ValueError, "sidecar"):
            build_phase2_diff_report("20260102", str(wal_hardlink))
        with self.assertRaisesRegex(ValueError, "sidecar"):
            build_phase3_strategy_performance_report(
                date_from="2026-01-02", out=str(wal_hardlink),
            )


if __name__ == "__main__":
    unittest.main()
