"""回歸測試:docs/30 §3 bug——backfill_warrant_branches 每個歷史日期須各自
撈當天真正有交易的權證清單,不能用「最新交易日」的清單往回查(權證壽命短,
半年前的權證早已下市不在今天清單,今天的權證半年前也還沒發行)。
"""
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import radar.config as config
import radar.db as db
from radar import schema
from radar.importer import backfill_warrant_branches
from radar.providers import NoDataError

OLD, NEW = "2026-01-05", "2026-01-06"  # OLD=較舊日期,NEW=較新(=MAX(date))


class BackfillWarrantBranchesDateScopedTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.tmp_path = tmp
        self.state_base = tmp / "resume.json"
        self._old_url, self._old_dir = config.DB_URL, config.DATA_DIR
        config.DATA_DIR = tmp
        config.DB_URL = "sqlite:///" + (tmp / "t.db").as_posix()
        db._engine = None
        db.init_db()
        self._seed()

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old_url, self._old_dir
        self._tmp.cleanup()

    def _seed(self):
        eng = db.get_engine()
        with eng.begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": "2330", "name": "ordinary", "market": "twse", "type": "stock", "is_active": 1},
            ])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": "2330", "date": OLD, "close": 100, "volume": 1, "turnover": 1},
                {"stock_id": "2330", "date": NEW, "close": 100, "volume": 1, "turnover": 1},
            ])
            # WA:只在 OLD 有交易(半年前發行、NEW 之前已下市) — 舊版全域清單抓不到它
            # WB:只在 NEW 有交易(NEW 才發行,OLD 那天根本不存在) — 舊版會誤用它去查 OLD
            conn.execute(schema.warrants.insert(), [
                {"id": "WA", "name": "warrant-old", "market": "twse", "kind": "call", "stock_id": "2330"},
                {"id": "WB", "name": "warrant-new", "market": "twse", "kind": "call", "stock_id": "2330"},
            ])
            conn.execute(schema.warrant_daily.insert(), [
                {"warrant_id": "WA", "date": OLD, "close": 1, "volume": 1, "turnover": 1000},
                {"warrant_id": "WB", "date": NEW, "close": 1, "volume": 1, "turnover": 1000},
            ])

    def test_each_date_queries_its_own_active_warrants(self):
        calls = []

        def fake_fetch(stock_id, date, throttle=None):
            calls.append((stock_id, date))
            return [{
                "stock_id": stock_id, "date": OLD if date.startswith("20260105") else NEW,
                "branch_key": "b1", "branch_name": "分點1", "broker_id": "999",
                "buy_lots": 1, "sell_lots": 0, "net_lots": 1, "pct": 1.0,
            }]

        with patch("radar.providers.fubon.fetch_branch_trades", side_effect=fake_fetch):
            result = backfill_warrant_branches(top=200, days=2, sleep_s=0)

        fetched_ids = {sid for sid, _ in calls}
        # 舊版 bug:targets 只用 MAX(date)=NEW 那天的清單(=WB),OLD 那天也會拿 WB 去查
        # (查不到歷史、白跑),永遠抓不到 WA。修正後 OLD 抓 WA、NEW 抓 WB,各自正確。
        self.assertIn("WA", fetched_ids, "OLD 日期應抓到當天真正在市的 WA")
        self.assertIn("WB", fetched_ids, "NEW 日期應抓到當天真正在市的 WB")
        self.assertEqual(result["fetched"], 2)
        self.assertIsNone(result["stopped"])

    def test_legacy_default_keeps_twse_top_n_limit(self):
        with db.get_engine().begin() as conn:
            conn.execute(schema.warrants.insert(), {
                "id": "WC", "name": "warrant-higher-turnover", "market": "twse",
                "kind": "put", "stock_id": "2330",
            })
            conn.execute(schema.warrant_daily.insert(), {
                "warrant_id": "WC", "date": NEW, "close": 1,
                "volume": 1, "turnover": 2000,
            })

        calls = []

        def fake_fetch(stock_id, date, throttle=None):
            calls.append(stock_id)
            return []

        with patch("radar.providers.fubon.fetch_branch_trades", side_effect=fake_fetch):
            result = backfill_warrant_branches(top=1, days=1, sleep_s=0)

        self.assertEqual(calls, ["WC"])
        self.assertEqual(result["fetched"], 1)

    def test_explicit_all_market_uses_top_as_fail_closed_cap(self):
        with db.get_engine().begin() as conn:
            conn.execute(schema.warrants.insert(), {
                "id": "WC", "name": "warrant-higher-turnover", "market": "twse",
                "kind": "put", "stock_id": "2330",
            })
            conn.execute(schema.warrant_daily.insert(), {
                "warrant_id": "WC", "date": NEW, "close": 1,
                "volume": 1, "turnover": 2000,
            })

        with self.assertRaisesRegex(RuntimeError, "refuse to silently truncate"):
            backfill_warrant_branches(top=1, days=1, sleep_s=0, market="all")

        with self.assertRaisesRegex(RuntimeError, "refuse to silently truncate"):
            backfill_warrant_branches(
                top=1, days=1, sleep_s=0, market="all", state_file=self.state_base,
            )
        self.assertFalse((self.tmp_path / "resume-2026-01-06-all.json").exists())

    def test_timeout_is_failure_and_import_log_is_error(self):
        with patch("radar.importer.time.monotonic", side_effect=[0.0, 61.0]), \
             patch("radar.providers.fubon.fetch_branch_trades") as fetch:
            result = backfill_warrant_branches(
                top=200, days=1, sleep_s=0, max_minutes=1
            )

        self.assertIsNotNone(result["stopped"])
        fetch.assert_not_called()
        with db.get_engine().connect() as conn:
            row = conn.exec_driver_sql(
                "SELECT status, error FROM import_logs "
                "WHERE dataset='warrant_branch_hist' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        self.assertEqual(row[0], "error")
        self.assertIn("time budget reached", row[1])

    def _state_path(self, date, market="twse"):
        return self.tmp_path / f"resume-{date}-{market}.json"

    def test_state_empty_response_is_not_fetched_again(self):
        with patch("radar.providers.fubon.fetch_branch_trades", side_effect=NoDataError("valid empty")) as fetch:
            first = backfill_warrant_branches(
                top=200, days=1, sleep_s=0, state_file=self.state_base,
            )
        state_path = self._state_path("2026-01-06")
        self.assertFalse(self.state_base.exists(), "base is a naming seed, never a giant state file")
        self.assertEqual(first["fetched"], 0)
        self.assertEqual(json.loads(state_path.read_text(encoding="utf-8"))["results"]["WB"]["status"], "empty")
        with patch("radar.providers.fubon.fetch_branch_trades") as retry:
            backfill_warrant_branches(top=200, days=1, sleep_s=0, state_file=self.state_base)
        retry.assert_not_called()
        self.assertEqual(fetch.call_count, 1)

    def test_state_error_retries_and_existing_db_rows_are_ok(self):
        with patch("radar.providers.fubon.fetch_branch_trades", side_effect=RuntimeError("temporary")) as first:
            incomplete = backfill_warrant_branches(
                top=200, days=1, sleep_s=0, state_file=self.state_base,
            )
        self.assertEqual(first.call_count, 1)
        self.assertIn("resume required", incomplete["stopped"])
        with db.get_engine().connect() as conn:
            first_log = conn.exec_driver_sql(
                "SELECT status, error FROM import_logs "
                "WHERE dataset='warrant_branch_hist' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        self.assertEqual(first_log[0], "error")
        self.assertIn("resume required", first_log[1])
        with patch("radar.providers.fubon.fetch_branch_trades", return_value=[]) as second:
            retry = backfill_warrant_branches(top=200, days=1, sleep_s=0, state_file=self.state_base)
        self.assertEqual(second.call_count, 1)
        self.assertEqual(retry["fetched"], 1)
        self.assertIsNone(retry["stopped"])
        with db.get_engine().connect() as conn:
            second_log = conn.exec_driver_sql(
                "SELECT status FROM import_logs "
                "WHERE dataset='warrant_branch_hist' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        self.assertEqual(second_log[0], "ok")

        with db.get_engine().begin() as conn:
            conn.execute(schema.branch_dim.insert(), {"id": 77, "branch_key": "known", "branch_name": "known"})
            conn.execute(schema.branch_trades_raw.insert(), {
                "stock_id": "WB", "date": NEW, "branch_id": 77, "net_lots": 1, "pct": 1.0,
            })
        other_base = self.tmp_path / "db-existing.json"
        with patch("radar.providers.fubon.fetch_branch_trades") as fetch:
            backfill_warrant_branches(top=200, days=1, sleep_s=0, state_file=other_base)
        fetch.assert_not_called()
        existing = self.tmp_path / "db-existing-2026-01-06-twse.json"
        self.assertEqual(json.loads(existing.read_text(encoding="utf-8"))["results"]["WB"]["source"], "existing_db")

    def test_state_scope_resets_only_changed_date_and_market(self):
        with patch("radar.providers.fubon.fetch_branch_trades", side_effect=NoDataError("empty")):
            backfill_warrant_branches(top=200, days=2, sleep_s=0, state_file=self.state_base)
        old_state = self._state_path("2026-01-05")
        new_state = self._state_path("2026-01-06")
        old_hash = json.loads(old_state.read_text(encoding="utf-8"))["target_hash"]
        with db.get_engine().begin() as conn:
            conn.execute(schema.warrants.insert(), {
                "id": "WC", "name": "newer pool member", "market": "twse", "kind": "put", "stock_id": "2330",
            })
            conn.execute(schema.warrant_daily.insert(), {
                "warrant_id": "WC", "date": NEW, "close": 1, "volume": 1, "turnover": 2000,
            })
        calls = []
        with patch("radar.providers.fubon.fetch_branch_trades", side_effect=lambda sid, *_args, **_kwargs: calls.append(sid) or (_ for _ in ()).throw(NoDataError("empty"))):
            backfill_warrant_branches(top=2, days=2, sleep_s=0, state_file=self.state_base)
        self.assertEqual(set(calls), {"WB", "WC"}, "only NEW pool hash is invalidated")
        self.assertEqual(json.loads(old_state.read_text(encoding="utf-8"))["target_hash"], old_hash)

        with db.get_engine().begin() as conn:
            conn.execute(schema.warrants.insert(), {
                "id": "TP", "name": "tpex pool", "market": "tpex", "kind": "call", "stock_id": "2330",
            })
            conn.execute(schema.warrant_daily.insert(), {
                "warrant_id": "TP", "date": NEW, "close": 1, "volume": 1, "turnover": 3000,
            })
        with patch("radar.providers.fubon.fetch_branch_trades", side_effect=NoDataError("empty")):
            backfill_warrant_branches(top=10, days=1, sleep_s=0, market="all", state_file=self.state_base)
        self.assertTrue(self._state_path("2026-01-06", "all").is_file(), "market has an independent state scope")

    def test_state_base_rejects_database_and_sidecars(self):
        db_path = Path(config.DB_URL.removeprefix("sqlite:///"))
        for protected in (db_path, *(db_path.with_name(f"{db_path.name}{suffix}") for suffix in ("-wal", "-shm", "-journal"))):
            with self.assertRaisesRegex(ValueError, "--state-file"):
                backfill_warrant_branches(top=200, days=1, sleep_s=0, state_file=protected)

        # The base itself is harmless here, but its per-date derived output is
        # a DB alias.  The actual file that would be written must be checked.
        derived_base = self.tmp_path / "derived.json"
        derived_alias = self.tmp_path / "derived-2026-01-06-twse.json"
        os.link(db_path, derived_alias)
        with self.assertRaisesRegex(ValueError, "alias"):
            backfill_warrant_branches(top=200, days=1, sleep_s=0, state_file=derived_base)

    def test_explicit_state_base_is_rejected_before_init_db(self):
        db_path = Path(config.DB_URL.removeprefix("sqlite:///"))
        before = db_path.read_bytes()
        alias = self.tmp_path / "backfill-database-hardlink.json"
        os.link(db_path, alias)
        for protected in (db_path, db_path.with_name(f"{db_path.name}-wal"), alias):
            with patch("radar.importer.init_db", side_effect=AssertionError("must not initialise")):
                with self.assertRaisesRegex(ValueError, "--state-file"):
                    backfill_warrant_branches(top=200, days=1, sleep_s=0, state_file=protected)
            self.assertEqual(db_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
