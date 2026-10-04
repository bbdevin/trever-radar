# -*- coding: utf-8 -*-
"""`probe-branch-day`(docs/47 原則 3):分點全量爬由探測觸發,不是時間一到就爬。

鎖住三件事:
1. **不寫資料庫**:不寫 branch_trades、不記 import_logs(它在等待期間跑,不握 DB 鎖)。
2. 抽樣是 ``--top 0`` 目標池的**等距**樣本(與正式那一輪同一份池子),不是前 N 檔。
3. 門檻:ok ≥ threshold → exit 0;否則 75;NoDataError 與其他失敗都算沒到。

富邦請求一律 mock 掉(不連網)。
"""
import contextlib
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

from sqlalchemy import text as sql_text

import radar.config as config
import radar.db as db
from radar import cli, importer, schema
from radar.providers import NoDataError

DAY = "2026-10-02"
IDS = [f"{1000 + i}" for i in range(48)]   # 48 檔 active 普通股


class _TempDb(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._old = config.DB_URL, config.DATA_DIR
        config.DATA_DIR = tmp
        config.DB_URL = "sqlite:///" + (tmp / "t.db").as_posix()
        db._engine = None
        db.init_db()
        with db.get_engine().begin() as conn:
            for sid in IDS:
                conn.execute(schema.stocks.insert().values(
                    id=sid, name=sid, market="twse", type="stock", is_active=1))
                conn.execute(schema.daily_prices.insert().values(
                    stock_id=sid, date=DAY, close=10.0, adj_factor=1.0))
            # 不進池子的:ETF、下市、當天沒收盤價
            conn.execute(schema.stocks.insert().values(
                id="0050", name="ETF", market="twse", type="etf", is_active=1))
            conn.execute(schema.daily_prices.insert().values(
                stock_id="0050", date=DAY, close=10.0, adj_factor=1.0))
            conn.execute(schema.stocks.insert().values(
                id="9998", name="gone", market="twse", type="stock", is_active=0))
            conn.execute(schema.daily_prices.insert().values(
                stock_id="9998", date=DAY, close=10.0, adj_factor=1.0))

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old
        self._tmp.cleanup()

    def _counts(self):
        with db.get_engine().connect() as conn:
            return tuple(conn.execute(sql_text(f"SELECT COUNT(*) FROM {t}")).scalar()
                         for t in ("import_logs", "branch_trades_raw", "daily_prices", "stocks"))


def _fetch_ok_for(ok_ids, calls):
    def fake(sid, date, throttle=None):
        calls.append((sid, date, throttle))
        if sid in ok_ids:
            return [{"stock_id": sid}]
        if sid.endswith("7"):
            raise RuntimeError("mirror timeout")
        raise NoDataError("not yet")
    return fake


class EvenlySpaced(unittest.TestCase):
    def test_spreads_over_the_whole_pool(self):
        pool = [str(i) for i in range(100)]
        picks = importer._evenly_spaced(pool, 4)
        self.assertEqual(picks, ["0", "25", "50", "75"])

    def test_small_pool_is_taken_whole(self):
        self.assertEqual(importer._evenly_spaced(["a", "b"], 24), ["a", "b"])
        self.assertEqual(importer._evenly_spaced([], 24), [])

    def test_deterministic(self):
        pool = [str(i) for i in range(2672)]
        self.assertEqual(importer._evenly_spaced(pool, 24), importer._evenly_spaced(pool, 24))
        self.assertEqual(len(set(importer._evenly_spaced(pool, 24))), 24)


class ProbeBranchDay(_TempDb):
    def test_no_db_writes(self):
        before = self._counts()
        calls = []
        with mock.patch("radar.providers.fubon.fetch_branch_trades",
                        side_effect=_fetch_ok_for(set(IDS), calls)), \
             mock.patch.object(importer, "upsert_branch_trades") as upsert, \
             mock.patch.object(importer, "_log") as log:
            info = importer.probe_branch_day(sample=24, threshold=22, sleep_s=0)
        self.assertEqual(self._counts(), before)
        upsert.assert_not_called()
        log.assert_not_called()
        self.assertTrue(info["ready"])

    def test_samples_the_top0_pool_evenly_with_the_round_date(self):
        calls = []
        with mock.patch("radar.providers.fubon.fetch_branch_trades",
                        side_effect=_fetch_ok_for(set(), calls)):
            info = importer.probe_branch_day(sample=24, threshold=22, sleep_s=0.5)
        asked = [c[0] for c in calls]
        self.assertEqual(asked, importer._evenly_spaced(IDS, 24))
        self.assertEqual(info["pool"], 48, "ETF、下市股不進池子(與 --top 0 同一份)")
        self.assertNotIn("0050", asked)
        self.assertNotIn("9998", asked)
        self.assertEqual({c[1] for c in calls}, {"20261002"}, "預設 MAX(date) FROM daily_prices")
        self.assertEqual({c[2] for c in calls}, {0.5})

    def test_threshold(self):
        picks = importer._evenly_spaced(IDS, 24)
        for n_ok, ready in ((22, True), (21, False), (24, True), (0, False)):
            with self.subTest(n_ok=n_ok):
                with mock.patch("radar.providers.fubon.fetch_branch_trades",
                                side_effect=_fetch_ok_for(set(picks[:n_ok]), [])):
                    info = importer.probe_branch_day(sample=24, threshold=22, sleep_s=0)
                self.assertEqual(info["ok"], n_ok)
                self.assertEqual(info["ready"], ready)

    def test_cli_exit_codes_and_line(self):
        picks = importer._evenly_spaced(IDS, 24)
        for n_ok, code in ((22, None), (10, 75)):
            with self.subTest(n_ok=n_ok):
                out = io.StringIO()
                with mock.patch("radar.providers.fubon.fetch_branch_trades",
                                side_effect=_fetch_ok_for(set(picks[:n_ok]), [])), \
                     contextlib.redirect_stdout(out):
                    try:
                        cli.cmd_probe_branch_day(SimpleNamespace(
                            date=None, sample=24, threshold=22, sleep=0))
                        got = None
                    except SystemExit as e:
                        got = e.code
                self.assertEqual(got, code)
                self.assertRegex(out.getvalue(),
                                 rf"^branch-probe at=\d\d:\d\d date={DAY} ok={n_ok}/24 ",
                                 "一行可 grep 的探測結果")

    def test_small_pool_scales_the_threshold(self):
        with mock.patch("radar.providers.fubon.fetch_branch_trades",
                        side_effect=_fetch_ok_for(set(IDS[:11]), [])):
            info = importer.probe_branch_day(sample=96, threshold=88, sleep_s=0)
        self.assertEqual(info["sample"], 48)
        self.assertEqual(info["threshold"], 44)
        self.assertFalse(info["ready"])


if __name__ == "__main__":
    unittest.main()
