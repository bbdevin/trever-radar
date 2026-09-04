"""All-market warrant-branch pool, safety cap, resume state, and CLI wiring."""
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import radar.cli as cli
import radar.config as config
import radar.db as db
from radar import schema
import radar.importer as importer
from radar.importer import import_branch_trades, import_warrant_branch_trades
from radar.providers import NoDataError


DATE = "2026-08-28"


class WarrantBranchImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        self.old_url, self.old_dir = config.DB_URL, config.DATA_DIR
        config.DATA_DIR = root
        config.DB_URL = "sqlite:///" + (root / "test.db").as_posix()
        db._engine = None
        db.init_db()
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": "1111", "name": "ordinary", "market": "twse", "type": "stock", "is_active": 1},
                {"id": "2222", "name": "ordinary otc", "market": "tpex", "type": "stock", "is_active": 1},
                {"id": "0050", "name": "ETF", "market": "twse", "type": "etf", "is_active": 1},
                {"id": "3333", "name": "inactive", "market": "twse", "type": "stock", "is_active": 0},
            ])
            conn.execute(schema.warrants.insert(), [
                {"id": "TW", "name": "twse call", "market": "twse", "kind": "call", "stock_id": "1111"},
                {"id": "TP", "name": "tpex put", "market": "tpex", "kind": "put", "stock_id": "2222"},
                {"id": "ETF", "name": "etf call", "market": "twse", "kind": "call", "stock_id": "0050"},
                {"id": "INACTIVE", "name": "inactive", "market": "twse", "kind": "call", "stock_id": "3333"},
                {"id": "ZERO_VOL", "name": "zero volume", "market": "tpex", "kind": "call", "stock_id": "2222"},
                {"id": "ZERO_TURN", "name": "zero turnover", "market": "tpex", "kind": "put", "stock_id": "2222"},
                {"id": "BULL", "name": "bull", "market": "twse", "kind": "bull", "stock_id": "1111"},
            ])
            conn.execute(schema.warrant_daily.insert(), [
                {"warrant_id": "TW", "date": DATE, "close": 1, "volume": 1, "turnover": 10},
                {"warrant_id": "TP", "date": DATE, "close": 1, "volume": 1, "turnover": 20},
                {"warrant_id": "ETF", "date": DATE, "close": 1, "volume": 1, "turnover": 99},
                {"warrant_id": "INACTIVE", "date": DATE, "close": 1, "volume": 1, "turnover": 99},
                {"warrant_id": "ZERO_VOL", "date": DATE, "close": 1, "volume": 0, "turnover": 99},
                {"warrant_id": "ZERO_TURN", "date": DATE, "close": 1, "volume": 1, "turnover": 0},
                {"warrant_id": "BULL", "date": DATE, "close": 1, "volume": 1, "turnover": 99},
            ])
        self.state = root / "state.json"

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self.old_url, self.old_dir
        self.tmp.cleanup()

    def test_twse_tpex_combined_pool_excludes_etf_and_zero_turnover(self):
        info = import_warrant_branch_trades("20260828", market="all", top=10,
                                            state_file=self.state, dry_run=True)
        self.assertEqual(info["targets"], 2)
        self.assertEqual(info["market_counts"], {"twse": 1, "tpex": 1})

    def test_market_filter_and_cap_fail_closed(self):
        twse = import_warrant_branch_trades("20260828", market="twse", top=1,
                                             state_file=self.state, dry_run=True)
        self.assertEqual(twse["targets"], 1)
        with self.assertRaisesRegex(RuntimeError, "refuse to silently truncate"):
            import_warrant_branch_trades("20260828", market="all", top=1,
                                         state_file=self.state, dry_run=True)

    def test_legacy_warrant_top_n_and_turnover_threshold_pool(self):
        """Threshold mode is inclusive, active-stock TWSE call/put-only, and replaces Top-N."""
        with db.get_engine().begin() as conn:
            conn.execute(schema.warrants.insert(), [
                {"id": "BELOW", "name": "below", "market": "twse", "kind": "call", "stock_id": "1111"},
                {"id": "CALL_EQ", "name": "call equal", "market": "twse", "kind": "call", "stock_id": "1111"},
                {"id": "PUT_ABOVE", "name": "put above", "market": "twse", "kind": "put", "stock_id": "1111"},
                {"id": "TPEX_HIGH", "name": "tpex high", "market": "tpex", "kind": "call", "stock_id": "2222"},
                {"id": "TW_TO_TPEX", "name": "listed warrant on otc stock", "market": "twse", "kind": "call", "stock_id": "2222"},
                {"id": "ETF_HIGH", "name": "etf high", "market": "twse", "kind": "call", "stock_id": "0050"},
                {"id": "INACTIVE_HIGH", "name": "inactive high", "market": "twse", "kind": "put", "stock_id": "3333"},
                {"id": "UNMAPPED_HIGH", "name": "unmapped high", "market": "twse", "kind": "call", "stock_id": "9999"},
                {"id": "NULL_STOCK_HIGH", "name": "null stock high", "market": "twse", "kind": "put", "stock_id": None},
            ])
            conn.execute(schema.warrant_daily.insert(), [
                {"warrant_id": "BELOW", "date": DATE, "close": 1, "volume": 1, "turnover": 999_999},
                {"warrant_id": "CALL_EQ", "date": DATE, "close": 1, "volume": 1, "turnover": 1_000_000},
                {"warrant_id": "PUT_ABOVE", "date": DATE, "close": 1, "volume": 1, "turnover": 1_000_001},
                {"warrant_id": "TPEX_HIGH", "date": DATE, "close": 1, "volume": 1, "turnover": 2_000_000},
                {"warrant_id": "TW_TO_TPEX", "date": DATE, "close": 1, "volume": 1, "turnover": 1_500_000},
                {"warrant_id": "ETF_HIGH", "date": DATE, "close": 1, "volume": 1, "turnover": 1_000_000},
                {"warrant_id": "INACTIVE_HIGH", "date": DATE, "close": 1, "volume": 1, "turnover": 1_000_000},
                {"warrant_id": "UNMAPPED_HIGH", "date": DATE, "close": 1, "volume": 1, "turnover": 1_000_000},
                {"warrant_id": "NULL_STOCK_HIGH", "date": DATE, "close": 1, "volume": 1, "turnover": 1_000_000},
            ])

        with patch("radar.providers.fubon.fetch_branch_trades", return_value=[]) as fetch:
            import_branch_trades("20260828", top=0, warrants=200, sleep_s=0,
                                 warrant_turnover_min=1_000_000)
        threshold_targets = [call.args[0] for call in fetch.call_args_list]
        self.assertEqual(set(threshold_targets), {"CALL_EQ", "PUT_ABOVE", "TW_TO_TPEX"})
        self.assertNotIn("BELOW", threshold_targets)  # 999,999 is below the inclusive floor.
        self.assertNotIn("TPEX_HIGH", threshold_targets)
        for excluded in ("ETF_HIGH", "INACTIVE_HIGH", "UNMAPPED_HIGH", "NULL_STOCK_HIGH"):
            self.assertNotIn(excluded, threshold_targets)

        with patch("radar.providers.fubon.fetch_branch_trades", return_value=[]) as fetch:
            import_branch_trades("20260828", top=0, warrants=2, sleep_s=0)
        # Omitting the new parameter preserves the existing Top-N contract.
        self.assertEqual([call.args[0] for call in fetch.call_args_list], ["TW_TO_TPEX", "PUT_ABOVE"])

        with patch("radar.providers.fubon.fetch_branch_trades", return_value=[]):
            import_branch_trades("20260828", top=0, warrants=0, sleep_s=0,
                                 warrant_turnover_min=0)
        with self.assertRaisesRegex(ValueError, ">= 0"):
            import_branch_trades("20260828", top=0, warrants=0, sleep_s=0,
                                 warrant_turnover_min=-1)

    def test_dry_run_is_strictly_read_only(self):
        db_path = Path(config.DB_URL.removeprefix("sqlite:///"))
        before_mtime = db_path.stat().st_mtime_ns
        with patch("radar.importer.init_db", side_effect=AssertionError("dry-run must not init DB")):
            info = import_warrant_branch_trades("20260828", market="all", top=10,
                                                 state_file=self.state, dry_run=True)
        self.assertTrue(info["dry_run"])
        self.assertFalse(self.state.exists(), "dry-run must not create resume state")
        self.assertEqual(db_path.stat().st_mtime_ns, before_mtime)

    def test_dry_run_disposes_read_only_engine_when_latest_date_is_missing(self):
        engine = MagicMock()
        conn = engine.connect.return_value.__enter__.return_value
        conn.execute.return_value.scalar.return_value = None
        with patch(
            "radar.compute.branch_point_in_time_report.get_read_only_engine",
            return_value=engine,
        ):
            with self.assertRaisesRegex(RuntimeError, "no warrant_daily date"):
                import_warrant_branch_trades(
                    date=None, market="all", top=10, state_file=self.state, dry_run=True,
                )
        engine.dispose.assert_called_once_with()
        engine.connect.return_value.__exit__.assert_called_once()

    def test_dry_run_disposes_read_only_engine_when_target_read_raises(self):
        engine = MagicMock()
        conn = engine.connect.return_value.__enter__.return_value
        conn.execute.side_effect = RuntimeError("read failed")
        with patch(
            "radar.compute.branch_point_in_time_report.get_read_only_engine",
            return_value=engine,
        ):
            with self.assertRaisesRegex(RuntimeError, "read failed"):
                import_warrant_branch_trades(
                    date="20260828", market="all", top=10, state_file=self.state, dry_run=True,
                )
        engine.dispose.assert_called_once_with()
        engine.connect.return_value.__exit__.assert_called_once()

    def test_custom_state_rejects_database_sidecars_and_database_alias(self):
        db_path = Path(config.DB_URL.removeprefix("sqlite:///"))
        for protected in (db_path, *(db_path.with_name(f"{db_path.name}{suffix}") for suffix in ("-wal", "-shm", "-journal"))):
            with self.assertRaisesRegex(ValueError, "--state-file"):
                import_warrant_branch_trades(
                    "20260828", market="all", top=10, state_file=protected, dry_run=True,
                )

        alias = Path(self.tmp.name) / "database-hardlink.json"
        os.link(db_path, alias)
        with self.assertRaisesRegex(ValueError, "alias"):
            import_warrant_branch_trades(
                "20260828", market="all", top=10, state_file=alias, dry_run=True,
            )

        symlink = Path(self.tmp.name) / "database-symlink.json"
        try:
            os.symlink(db_path, symlink)
        except OSError:
            pass  # Windows may not grant this test process symlink privilege.
        else:
            with self.assertRaisesRegex(ValueError, "database"):
                import_warrant_branch_trades(
                    "20260828", market="all", top=10, state_file=symlink, dry_run=True,
                )

        # Existing WAL sidecars are protected by inode too, not just by their
        # literal names.  init_db keeps this test database in active WAL mode.
        wal_path = db_path.with_name(f"{db_path.name}-wal")
        self.assertTrue(wal_path.is_file())
        wal_alias = Path(self.tmp.name) / "wal-hardlink.json"
        os.link(wal_path, wal_alias)
        with self.assertRaisesRegex(ValueError, "sidecar"):
            import_warrant_branch_trades(
                "20260828", market="all", top=10, state_file=wal_alias, dry_run=True,
            )

    def test_explicit_invalid_state_is_rejected_before_init_db(self):
        db_path = Path(config.DB_URL.removeprefix("sqlite:///"))
        before = db_path.read_bytes()
        alias = Path(self.tmp.name) / "database-init-hardlink.json"
        os.link(db_path, alias)
        for protected in (db_path, db_path.with_name(f"{db_path.name}-wal"), alias):
            with patch("radar.importer.init_db", side_effect=AssertionError("must not initialise")):
                with self.assertRaisesRegex(ValueError, "--state-file"):
                    import_warrant_branch_trades(
                        "20260828", market="all", top=10, state_file=protected,
                    )
            self.assertEqual(db_path.read_bytes(), before)

    def test_atomic_state_ignores_malicious_legacy_temp_files(self):
        db_path = Path(config.DB_URL.removeprefix("sqlite:///"))
        wal_path = db_path.with_name(f"{db_path.name}-wal")
        self.assertTrue(wal_path.is_file(), "fixture must exercise active WAL")
        before_db, before_wal = db_path.read_bytes(), wal_path.read_bytes()

        hardlink_state = Path(self.tmp.name) / "hardlink-state.json"
        hardlink_tmp = hardlink_state.with_name(f"{hardlink_state.name}.tmp")
        os.link(db_path, hardlink_tmp)
        symlink_state = Path(self.tmp.name) / "symlink-state.json"
        symlink_tmp = symlink_state.with_name(f"{symlink_state.name}.tmp")
        try:
            os.symlink(wal_path, symlink_tmp)
        except OSError:
            symlink_state = None  # Symlink permission is platform-dependent.

        with patch("radar.importer.init_db", return_value=None), \
             patch("radar.importer._log"), \
             patch("radar.providers.fubon.fetch_branch_trades", side_effect=NoDataError("valid empty")):
            hardlink_info = import_warrant_branch_trades(
                "20260828", market="all", top=10, sleep_s=0, state_file=hardlink_state,
            )
            if symlink_state is not None:
                symlink_info = import_warrant_branch_trades(
                    "20260828", market="all", top=10, sleep_s=0, state_file=symlink_state,
                )

        self.assertTrue(hardlink_info["complete"])
        self.assertTrue(json.loads(hardlink_state.read_text(encoding="utf-8"))["results"])
        self.assertTrue(os.path.samefile(hardlink_tmp, db_path), "old fixed temp is untouched")
        self.assertFalse(list(hardlink_state.parent.glob(f".{hardlink_state.name}.*.tmp")))
        if symlink_state is not None:
            self.assertTrue(symlink_info["complete"])
            self.assertTrue(os.path.samefile(symlink_tmp, wal_path), "old fixed temp is untouched")
            self.assertFalse(list(symlink_state.parent.glob(f".{symlink_state.name}.*.tmp")))
        self.assertEqual(db_path.read_bytes(), before_db)
        self.assertEqual(wal_path.read_bytes(), before_wal)

    def test_timeout_is_logged_as_error_not_empty(self):
        with patch("radar.importer.time.monotonic", side_effect=[0.0, 61.0]), \
             patch("radar.providers.fubon.fetch_branch_trades") as fetch:
            info = import_warrant_branch_trades("20260828", top=10, sleep_s=0,
                                                 max_minutes=1, state_file=self.state)
        self.assertFalse(info["complete"])
        self.assertIsNotNone(info["stopped"])
        fetch.assert_not_called()
        with db.get_engine().connect() as conn:
            row = conn.exec_driver_sql(
                "SELECT status, error FROM import_logs WHERE dataset='warrant_branch' "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        self.assertEqual(row[0], "error")
        self.assertIn("time budget reached", row[1])

    def test_resume_skips_ok_and_empty_but_retries_error(self):
        calls = []

        def fetch_once(stock_id, date, throttle=None):
            calls.append(stock_id)
            if stock_id == "TW":
                raise NoDataError("valid empty")
            raise RuntimeError("temporary source outage")

        with patch("radar.providers.fubon.fetch_branch_trades", side_effect=fetch_once):
            first = import_warrant_branch_trades("20260828", top=10, sleep_s=0,
                                                  state_file=self.state)
        self.assertFalse(first["complete"])
        saved = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(saved["results"]["TW"]["status"], "empty")
        self.assertEqual(saved["results"]["TP"]["status"], "error")

        def fetch_retry(stock_id, date, throttle=None):
            calls.append(stock_id)
            return [{"stock_id": stock_id, "date": DATE, "branch_key": "b", "branch_name": "branch",
                     "broker_id": "001", "buy_lots": 1, "sell_lots": 0, "net_lots": 1, "pct": 1.0}]

        with patch("radar.providers.fubon.fetch_branch_trades", side_effect=fetch_retry):
            second = import_warrant_branch_trades("20260828", top=10, sleep_s=0,
                                                   state_file=self.state)
        self.assertTrue(second["complete"])
        self.assertEqual(calls.count("TW"), 1, "empty is a completed source response")
        self.assertEqual(calls.count("TP"), 2, "errors remain retryable")

    def test_successes_checkpoint_in_batches_and_default_state_is_per_date(self):
        rows = [{"stock_id": "x", "date": DATE, "branch_key": "batch", "branch_name": "branch",
                 "broker_id": "001", "buy_lots": 1, "sell_lots": 0, "net_lots": 1, "pct": 1.0}]
        with patch("radar.providers.fubon.fetch_branch_trades", return_value=rows), \
             patch("radar.importer._atomic_json_write", wraps=importer._atomic_json_write) as checkpoint:
            info = import_warrant_branch_trades("20260828", top=10, sleep_s=0)
        self.assertTrue(info["complete"])
        self.assertTrue(info["state_file"].endswith("warrant-branch-state-2026-08-28.json"))
        self.assertEqual(checkpoint.call_count, 2, "initial + final; do not rewrite per normal target")

    def test_cli_wiring_passes_warrant_flags(self):
        with patch("radar.importer.import_warrant_branch_trades", return_value={"complete": True}) as imp:
            cli.main(["import-warrant-branch-trades", "--market", "tpex", "--top", "9", "--dry-run"])
        self.assertEqual(imp.call_args.kwargs["market"], "tpex")
        self.assertEqual(imp.call_args.kwargs["top"], 9)
        self.assertTrue(imp.call_args.kwargs["dry_run"])

        with patch("radar.importer.import_branch_trades", return_value={}) as legacy:
            cli.main(["import-branch-trades", "--top", "0", "--warrants", "0"])
        self.assertEqual(legacy.call_args.kwargs["warrants"], 0)
        self.assertIsNone(legacy.call_args.kwargs["warrant_turnover_min"])

        with patch("radar.importer.import_branch_trades", return_value={}) as threshold:
            cli.main(["import-branch-trades", "--top", "0", "--warrant-turnover-min", "1000000"])
        self.assertEqual(threshold.call_args.kwargs["warrant_turnover_min"], 1_000_000)

        with self.assertRaisesRegex(ValueError, ">= 0"):
            cli.main(["import-branch-trades", "--warrant-turnover-min", "-1"])

        with patch("radar.importer.backfill_warrant_branches",
                   return_value={"stopped": None}) as backfill:
            cli.main(["backfill-warrant-branches", "--market", "tpex", "--top", "99", "--state-file", "resume.json"])
        self.assertEqual(backfill.call_args.args[-1], "tpex")
        self.assertEqual(backfill.call_args.kwargs["state_file"], "resume.json")

        with patch("radar.importer.backfill_warrant_branches",
                   return_value={"stopped": None}) as legacy_backfill:
            cli.main(["backfill-warrant-branches", "--days", "1"])
        self.assertEqual(legacy_backfill.call_args.args[0], 200)
        self.assertEqual(legacy_backfill.call_args.args[-1], "twse")

        # 可續跑的停止用 75、真失敗用 1。驅動腳本要靠離開碼分辨這兩件事,
        # 不能去比對訊息字面——那等於把 shell 綁在一個 Python f-string 上。
        for stopped in ("time budget reached at 2026-09-01",
                        "resume required: 3 date(s) remain incomplete"):
            with self.subTest(stopped=stopped):
                with patch("radar.importer.backfill_warrant_branches",
                           return_value={"stopped": stopped}):
                    with self.assertRaises(SystemExit) as ctx:
                        cli.main(["backfill-warrant-branches", "--days", "1"])
                self.assertEqual(ctx.exception.code,
                                 cli.WARRANT_BACKFILL_INCOMPLETE_EXIT)

        with patch("radar.importer.backfill_warrant_branches",
                   return_value={"stopped": "too many failures at 2026-09-01: 31"}):
            with self.assertRaises(SystemExit) as ctx:
                cli.main(["backfill-warrant-branches", "--days", "1"])
        self.assertEqual(ctx.exception.code, 1,
                         "抓取連續失敗是真失敗,不可以和『時間到了』共用離開碼")

        script = Path(__file__).parents[2] / "vps" / "scripts" / "daily-branches.sh"
        script_text = script.read_text(encoding="utf-8")
        self.assertIn("--warrant-turnover-min 1000000", script_text)
        self.assertNotIn("--warrants 200", script_text)
        poc = Path(__file__).parents[2] / "vps" / "scripts" / "daily-warrant-branches-poc.sh"
        poc_text = poc.read_text(encoding="utf-8")
        self.assertIn("radar_timeout", poc_text)
        self.assertNotIn("WARRANT_BRANCH_DEPLOY", poc_text)
        dry_run_block = poc_text.split('if [ "${WARRANT_BRANCH_DRY_RUN:-0}" = "1" ]', 1)[1]
        dry_run_block = dry_run_block.split("fi", 1)[0]
        self.assertNotIn("sync_code", dry_run_block)
        self.assertLess(poc_text.index("pause_bf_for_exclusive_writer"), poc_text.index("acquire_db_lock"))


if __name__ == "__main__":
    unittest.main()
