"""回歸測試:docs/30 §3 bug——backfill_warrant_branches 每個歷史日期須各自
撈當天真正有交易的權證清單,不能用「最新交易日」的清單往回查(權證壽命短,
半年前的權證早已下市不在今天清單,今天的權證半年前也還沒發行)。
"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import radar.config as config
import radar.db as db
from radar import schema
from radar.importer import backfill_warrant_branches

OLD, NEW = "2026-01-05", "2026-01-06"  # OLD=較舊日期,NEW=較新(=MAX(date))


class BackfillWarrantBranchesDateScopedTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
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
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": "2330", "date": OLD, "close": 100, "volume": 1, "turnover": 1},
                {"stock_id": "2330", "date": NEW, "close": 100, "volume": 1, "turnover": 1},
            ])
            # WA:只在 OLD 有交易(半年前發行、NEW 之前已下市) — 舊版全域清單抓不到它
            # WB:只在 NEW 有交易(NEW 才發行,OLD 那天根本不存在) — 舊版會誤用它去查 OLD
            conn.execute(schema.warrants.insert(), [
                {"id": "WA", "name": "warrant-old", "market": "twse", "kind": "call"},
                {"id": "WB", "name": "warrant-new", "market": "twse", "kind": "call"},
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


if __name__ == "__main__":
    unittest.main()
