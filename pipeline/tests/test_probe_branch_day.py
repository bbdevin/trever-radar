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
import re
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


def _fetch_ok_for(ok_ids, calls, ok_hosts=None):
    """``ok_hosts`` 給定時只有那些站回得出列(其他站一律「還沒公布」)。"""
    def fake(sid, date, throttle=None, host=None):
        calls.append((sid, date, throttle, host))
        if ok_hosts is not None and host not in ok_hosts:
            raise NoDataError("not yet on this mirror")
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
        from radar.providers import fubon

        picks = importer._evenly_spaced(IDS, 24)
        asked = [c[0] for c in calls]
        # 逐站探測(docs/47 §8):每一站各問同一批等距樣本一次,釘在那一站。
        self.assertEqual(sorted(set(asked)), sorted(picks))
        for host in fubon.MIRROR_HOSTS:
            with self.subTest(host=host):
                self.assertEqual([c[0] for c in calls if c[3] == host], picks,
                                 "每一站都要問完同一批樣本、同一個順序")
        self.assertEqual(len(calls), len(picks) * len(fubon.MIRROR_HOSTS))
        self.assertEqual(info["pool"], 48, "ETF、下市股不進池子(與 --top 0 同一份)")
        self.assertNotIn("0050", asked)
        self.assertNotIn("9998", asked)
        self.assertEqual({c[1] for c in calls}, {"20261002"}, "預設 MAX(date) FROM daily_prices")
        # 單站間隔 = 全域間隔 × 站數:五站平行時每一站看到的節奏與循序輪替相同。
        self.assertEqual({c[2] for c in calls}, {0.5 * len(fubon.MIRROR_HOSTS)})

    def test_one_ready_mirror_is_enough_and_is_named(self):
        """五站各自更新時間可能不同:只要有一站達門檻就可以開始爬,而且要說是哪一站。"""
        from radar.providers import fubon

        early = fubon.MIRROR_HOSTS[2]
        with mock.patch("radar.providers.fubon.fetch_branch_trades",
                        side_effect=_fetch_ok_for(set(IDS), [], ok_hosts={early})):
            info = importer.probe_branch_day(sample=24, threshold=22, sleep_s=0)
        self.assertTrue(info["ready"])
        self.assertEqual(info["ready_hosts"], [early])
        self.assertEqual(info["ok"], 24, "ok 是各站裡最好的那一站")
        self.assertEqual(info["mirrors"][early], 24)
        self.assertEqual(sum(info["mirrors"].values()), 24, "其他四站都是 0")

    def test_min_ready_hosts_gates_the_start_of_the_crawl(self):
        """HIGH 1(2026-10-07 驗證者):只有一站就緒時不能開爬(單站 5 秒 × 2,000 檔 =
        10,000 秒 > 7200 硬上限)。daily-branches.sh 要求 3 站;站數上限夾在站總數。"""
        from radar.providers import fubon

        two = set(fubon.MIRROR_HOSTS[:2])
        with mock.patch("radar.providers.fubon.fetch_branch_trades",
                        side_effect=_fetch_ok_for(set(IDS), [], ok_hosts=two)):
            info3 = importer.probe_branch_day(sample=24, threshold=22, sleep_s=0, min_ready_hosts=3)
            info2 = importer.probe_branch_day(sample=24, threshold=22, sleep_s=0, min_ready_hosts=2)
            info9 = importer.probe_branch_day(sample=24, threshold=22, sleep_s=0, min_ready_hosts=9)
        self.assertEqual(sorted(info3["ready_hosts"]), sorted(two))
        self.assertFalse(info3["ready"], "兩站就緒、要求三站 → 還不能爬(75)")
        self.assertTrue(info2["ready"])
        self.assertEqual(info9["min_ready_hosts"], len(fubon.MIRROR_HOSTS), "夾在站總數")
        self.assertFalse(info9["ready"])
        with mock.patch("radar.providers.fubon.fetch_branch_trades",
                        side_effect=_fetch_ok_for(set(IDS), [])):
            self.assertTrue(importer.probe_branch_day(sample=24, threshold=22, sleep_s=0,
                                                      min_ready_hosts=9)["ready"], "五站全到")

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
                            date=None, sample=24, threshold=22, sleep=0, min_ready_hosts=1))
                        got = None
                    except SystemExit as e:
                        got = e.code
                self.assertEqual(got, code)
                self.assertRegex(out.getvalue(),
                                 rf"(?m)^branch-probe at=\d\d:\d\d date={DAY} ok={n_ok}/24 ",
                                 "一行可 grep 的探測結果")
                # 逐站各一行:明天的 cron log 才量得出每一站幾點先有今天的資料。
                self.assertRegex(out.getvalue(),
                                 rf"(?m)^branch-probe mirror=https://\S+ at=\d\d:\d\d "
                                 rf"date={DAY} ok={n_ok}/24 ready=[01]$")
                self.assertEqual(
                    len(re.findall(r"(?m)^branch-probe mirror=", out.getvalue())), 5)

    def test_small_pool_scales_the_threshold(self):
        with mock.patch("radar.providers.fubon.fetch_branch_trades",
                        side_effect=_fetch_ok_for(set(IDS[:11]), [])):
            info = importer.probe_branch_day(sample=96, threshold=88, sleep_s=0)
        self.assertEqual(info["sample"], 48)
        self.assertEqual(info["threshold"], 44)
        self.assertFalse(info["ready"])


if __name__ == "__main__":
    unittest.main()
