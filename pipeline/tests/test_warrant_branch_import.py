"""All-market warrant-branch pool, safety cap, resume state, and CLI wiring."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import radar.cli as cli
import radar.config as config
import radar.db as db
from radar import schema
import radar.importer as importer
from radar.importer import import_warrant_branch_trades
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

    def test_dry_run_is_strictly_read_only(self):
        db_path = Path(config.DB_URL.removeprefix("sqlite:///"))
        before_mtime = db_path.stat().st_mtime_ns
        with patch("radar.importer.init_db", side_effect=AssertionError("dry-run must not init DB")):
            info = import_warrant_branch_trades("20260828", market="all", top=10,
                                                 state_file=self.state, dry_run=True)
        self.assertTrue(info["dry_run"])
        self.assertFalse(self.state.exists(), "dry-run must not create resume state")
        self.assertEqual(db_path.stat().st_mtime_ns, before_mtime)

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

        with patch("radar.importer.backfill_warrant_branches",
                   return_value={"stopped": None}) as backfill:
            cli.main(["backfill-warrant-branches", "--market", "tpex", "--top", "99"])
        self.assertEqual(backfill.call_args.args[-1], "tpex")

        with patch("radar.importer.backfill_warrant_branches",
                   return_value={"stopped": None}) as legacy_backfill:
            cli.main(["backfill-warrant-branches", "--days", "1"])
        self.assertEqual(legacy_backfill.call_args.args[0], 200)
        self.assertEqual(legacy_backfill.call_args.args[-1], "twse")

        with patch("radar.importer.backfill_warrant_branches",
                   return_value={"stopped": "time budget reached"}):
            with self.assertRaisesRegex(SystemExit, "backfill incomplete"):
                cli.main(["backfill-warrant-branches", "--days", "1"])

        script = Path(__file__).parents[2] / "vps" / "scripts" / "daily-branches.sh"
        self.assertIn("--warrants 200", script.read_text(encoding="utf-8"))
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
