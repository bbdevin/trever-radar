"""回歸測試:docs/30 §3 bug——backfill_warrant_branches 每個歷史日期須各自
撈當天真正有交易的權證清單,不能用「最新交易日」的清單往回查(權證壽命短,
半年前的權證早已下市不在今天清單,今天的權證半年前也還沒發行)。
"""
import json
import os
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zoneinfo import ZoneInfo

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

    def test_timeout_is_incomplete_not_error(self):
        """時間預算用完是設計上的正常分塊停止,不是故障。

        以前這裡記成 `error`,於是每一塊都在 import_logs 留下一列假失敗——實測
        production 連三列 `error`,理由全是 "time budget reached"。那條訊號因此
        100% 是雜訊,真的壞掉時反而看不出來。
        """
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
        self.assertEqual(row[0], "incomplete")
        # 停止理由不可以因為降級成 incomplete 就被丟掉——那是唯一記得「為什麼停」的地方。
        self.assertIn("time budget reached", row[1])

    def test_real_failure_still_records_error(self):
        """`too many failures at ...` 是真故障,必須留在 `error`。

        這是三態拆分唯一真正有風險的地方:若把它一起降級成 incomplete,就等於
        把「來源壞了」與「時間到了」再次壓成同一個字,只是換個方向壞掉。
        """
        from radar.importer import _warrant_backfill_status

        self.assertEqual(_warrant_backfill_status(None), "ok")
        self.assertEqual(_warrant_backfill_status("time budget reached at 2026-01-06"), "incomplete")
        self.assertEqual(_warrant_backfill_status("resume required: 3 date(s) remain incomplete"), "incomplete")
        self.assertEqual(_warrant_backfill_status("too many failures at 2026-01-06"), "error")

    def test_cli_exit_code_and_db_status_come_from_one_tuple(self):
        """離開碼與 import_logs 狀態必須出自同一份可續跑理由清單。

        兩層各留一份 tuple 時,漂移的結果是離開碼說「可續跑、75、繼續」而資料庫
        說「失敗」——比原本的 bug 更難查。
        """
        from radar import cli
        from radar.importer import WARRANT_RESUMABLE_STOPS, _warrant_backfill_status

        self.assertFalse(hasattr(cli, "_WARRANT_RESUMABLE_STOPS"),
                         "cli 不可以再自己留一份")
        for stopped in WARRANT_RESUMABLE_STOPS:
            self.assertEqual(_warrant_backfill_status(stopped), "incomplete")

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
        # 「還有日期沒跑完、下次續跑」同樣是可續跑停點,不是故障。
        self.assertEqual(first_log[0], "incomplete")
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

    def _seed_fresh_date(self, d_iso, warrant_id="WD"):
        with db.get_engine().begin() as conn:
            conn.execute(schema.daily_prices.insert(), {
                "stock_id": "2330", "date": d_iso, "close": 100, "volume": 1, "turnover": 1,
            })
            conn.execute(schema.warrants.insert(), {
                "id": warrant_id, "name": "warrant-fresh", "market": "twse",
                "kind": "call", "stock_id": "2330",
            })
            conn.execute(schema.warrant_daily.insert(), {
                "warrant_id": warrant_id, "date": d_iso, "close": 1,
                "volume": 1, "turnover": 5000,
            })

    def test_dates_newer_than_min_age_are_not_visited(self):
        """尚未發布的日期不可以被爬——它會被記成永不重試的 `empty`。

        `fubon.fetch_branch_trades` 在頁面解析出零列時一律丟 `NoDataError`,
        呼叫端分不出「當天真的沒有分點成交」與「MoneyDJ 還沒發布這一天」。
        當天的 warrant_daily 是 16:10 那輪寫的(約 1.8 萬個目標),分點頁第一次
        日更是 17:40 且實測曾延到 22:00,所以傍晚的一塊會把最新日期整批寫成
        終端 empty 而且回報成功。每日 target hash 救不了:它只在目標清單變動時
        改變,不會因為鏡像後來開始供資料而改變。
        """
        today = datetime.now(ZoneInfo(config.TZ)).date()
        fresh = today.isoformat()
        self._seed_fresh_date(fresh)

        calls = []
        with patch("radar.providers.fubon.fetch_branch_trades",
                   side_effect=lambda sid, date, throttle=None: calls.append((sid, date)) or []):
            result = backfill_warrant_branches(
                top=200, days=10, sleep_s=0, state_file=self.state_base,
            )
        self.assertNotIn("WD", {sid for sid, _ in calls},
                         "今天的日期不該被造訪:分不出未發布與真的沒有")
        self.assertFalse(self._state_path(fresh).exists(),
                         "沒被造訪的日期不該留下 state 檔")
        self.assertIsNone(result["stopped"],
                          "頭部被壓後仍算完整,不該回報成續跑")

        # 明確放行(min_age_days=0)時才會抓到它——證明擋下來的是這個參數本身。
        calls.clear()
        with patch("radar.providers.fubon.fetch_branch_trades",
                   side_effect=lambda sid, date, throttle=None: calls.append((sid, date)) or []):
            backfill_warrant_branches(
                top=200, days=10, sleep_s=0, state_file=self.state_base, min_age_days=0,
            )
        self.assertIn("WD", {sid for sid, _ in calls})

    def test_min_age_also_holds_the_legacy_path_back(self):
        fresh = datetime.now(ZoneInfo(config.TZ)).date().isoformat()
        self._seed_fresh_date(fresh)
        calls = []
        with patch("radar.providers.fubon.fetch_branch_trades",
                   side_effect=lambda sid, date, throttle=None: calls.append(sid) or []):
            backfill_warrant_branches(top=200, days=10, sleep_s=0)
        self.assertNotIn("WD", calls)

    def test_yesterday_is_old_enough_to_crawl(self):
        yesterday = (datetime.now(ZoneInfo(config.TZ)).date() - timedelta(days=1)).isoformat()
        self._seed_fresh_date(yesterday)
        calls = []
        with patch("radar.providers.fubon.fetch_branch_trades",
                   side_effect=lambda sid, date, throttle=None: calls.append(sid) or []):
            backfill_warrant_branches(top=200, days=10, sleep_s=0, state_file=self.state_base)
        self.assertIn("WD", calls, "落後一個日曆日就夠;不是把頭部無限往後推")

    def test_empty_count_is_reported(self):
        """`empty=` 是終端 empty 中毒唯一看得見的訊號,必須進摘要行與回傳值。"""
        with patch("radar.providers.fubon.fetch_branch_trades",
                   side_effect=NoDataError("valid empty")):
            state = backfill_warrant_branches(
                top=200, days=1, sleep_s=0, state_file=self.state_base,
            )
            legacy = backfill_warrant_branches(top=200, days=1, sleep_s=0)
        self.assertEqual(state["empty"], 1)
        self.assertEqual(legacy["empty"], 1)

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
