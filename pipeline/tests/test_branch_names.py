"""分點名稱正規化:亂碼、改名、停業(2026-10-02,使用者要求「改名或已不存在的分點
要移除或修改」)。fixture 的名稱取自正式資料查到的真實案例。"""
import contextlib
import io
import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import text

import radar.config as config
import radar.db as db
from radar import schema
from radar.branch_names import INACTIVE_DAYS, canonical_name, is_closed


class CanonicalNameTests(unittest.TestCase):
    def test_garbled_character_is_restored(self):
        """來源編碼沒有「犇」,寫成「(牛牛牛)」。"""
        self.assertEqual(canonical_name("(牛牛牛)亞證券"), "犇亞證券")
        self.assertEqual(canonical_name("(牛牛牛)亞-鑫豐"), "犇亞-鑫豐")

    def test_known_rename_maps_to_the_new_name(self):
        """9B17 台新-營業部 停在 2026-04-02,9B00 台新 自 04-07 起接續。"""
        self.assertEqual(canonical_name("台新-營業部"), "台新")

    def test_ordinary_names_are_untouched(self):
        for name in ("兆豐-嘉義", "台新-台北", "元大-西門(停)", "群益金鼎"):
            self.assertEqual(canonical_name(name), name)


class ClosedTests(unittest.TestCase):
    AS_OF = "2026-10-01"

    def test_marked_closed(self):
        self.assertTrue(is_closed("元大-西門(停)", "2026-09-30", self.AS_OF))

    def test_inactive_for_too_long(self):
        """凱基-天母理財:沒有標記,但最後一筆是 2024-12-20。"""
        self.assertTrue(is_closed("凱基-天母理財", "2024-12-20", self.AS_OF))
        edge = (date.fromisoformat(self.AS_OF) - timedelta(days=INACTIVE_DAYS)).isoformat()
        self.assertFalse(is_closed("某分點", edge, self.AS_OF))       # 剛好 120 天:仍算營業
        self.assertTrue(is_closed("某分點", None, self.AS_OF))

    def test_active(self):
        self.assertFalse(is_closed("兆豐-嘉義", "2026-09-30", self.AS_OF))


class _DB(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.old = config.DB_URL, config.DATA_DIR
        config.DB_URL = "sqlite:///" + (Path(self.tmp.name) / "t.db").as_posix()
        config.DATA_DIR = Path(self.tmp.name)
        db._engine = None
        db.init_db()

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self.old
        self.tmp.cleanup()


class MigrationTests(_DB):
    def test_existing_names_are_fixed_once_and_tracking_follows(self):
        with db.get_engine().begin() as conn:
            conn.execute(schema.branch_dim.insert(), [
                {"id": 1, "branch_key": "6010", "broker_id": "6010", "branch_name": "(牛牛牛)亞證券"},
                {"id": 2, "branch_key": "9B17", "broker_id": "9B00", "branch_name": "台新-營業部"},
                {"id": 3, "branch_key": "9B00", "broker_id": "9B00", "branch_name": "台新"},
                {"id": 4, "branch_key": "7001", "broker_id": "7000", "branch_name": "兆豐-嘉義"},
            ])
            conn.execute(schema.tracked_branches.insert(), [
                {"branch_name": "(牛牛牛)亞證券", "source": "manual"},
                {"branch_name": "台新-營業部", "source": "auto"},
                {"branch_name": "台新", "source": "manual"},
            ])
            changed = db._normalize_branch_names(conn)
            again = db._normalize_branch_names(conn)
            names = dict(conn.execute(text("SELECT id, branch_name FROM branch_dim")).fetchall())
            tracked = dict(conn.execute(text("SELECT branch_name, source FROM tracked_branches")).fetchall())
        self.assertEqual(changed, 2)
        self.assertEqual(again, 0, "冪等:每一輪都會跑,第二次不得再改")
        self.assertEqual(names, {1: "犇亞證券", 2: "台新", 3: "台新", 4: "兆豐-嘉義"})
        # 改名的追蹤跟著改;新名已在追蹤裡(手動)→ 舊名那一列移除,不覆寫使用者的設定。
        self.assertEqual(tracked, {"犇亞證券": "manual", "台新": "manual"})

    def test_renamed_history_merges_under_one_name(self):
        """兩段歷史日期不重疊;view 讀 branch_dim 的名稱,所以合成一家。"""
        from radar.importer import upsert_branch_trades
        with db.get_engine().begin() as conn:
            upsert_branch_trades(conn, [
                {"stock_id": "2330", "date": "2026-04-02", "branch_key": "9B17", "broker_id": "9B00",
                 "branch_name": "台新-營業部", "buy_lots": 1, "sell_lots": 0, "net_lots": 1, "pct": 0},
                {"stock_id": "2330", "date": "2026-04-07", "branch_key": "9B00", "broker_id": "9B00",
                 "branch_name": "台新", "buy_lots": 2, "sell_lots": 0, "net_lots": 2, "pct": 0},
            ])
            rows = conn.execute(text(
                "SELECT branch_name, COUNT(*), SUM(net_lots) FROM branch_trades GROUP BY branch_name"
            )).fetchall()
        self.assertEqual([tuple(r) for r in rows], [("台新", 2, 3)])

    def test_a_new_garbled_branch_lands_already_fixed(self):
        from radar.importer import upsert_branch_trades
        with db.get_engine().begin() as conn:
            upsert_branch_trades(conn, [
                {"stock_id": "2330", "date": "2026-10-01", "branch_key": "6012", "broker_id": "6010",
                 "branch_name": "(牛牛牛)亞-網路", "buy_lots": 1, "sell_lots": 0, "net_lots": 1, "pct": 0},
            ])
            name = conn.execute(text("SELECT branch_name FROM branch_dim WHERE branch_key='6012'")).scalar()
        self.assertEqual(name, "犇亞-網路")


class RankingExcludesClosedTests(_DB):
    def test_a_closed_branch_never_reaches_the_rankings(self):
        """元大-西門(停) 曾以 26 筆樣本排第一。停業分點不進排行、不自動追蹤。"""
        from radar.compute.compute_branch_stats import MIN_RANK_EVENTS, compute_all

        days = [(date(2026, 9, 1) + timedelta(days=i)).isoformat() for i in range(30)]
        qual = days[::3][:MIN_RANK_EVENTS + 1]       # 不相鄰 → 每一天都是一個事件
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": "1101", "name": "台泥", "market": "twse", "type": "stock"}])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": "1101", "date": d, "open": 10, "close": 10, "volume": 1000} for d in days])
            conn.execute(schema.branch_dim.insert(), [
                {"id": 1, "branch_key": "a", "branch_name": "正常分點"},
                {"id": 2, "branch_key": "b", "branch_name": "元大-西門(停)"},
            ])
            conn.execute(schema.branch_trades_raw.insert(), [
                {"stock_id": "1101", "date": d, "branch_id": bid, "buy_lots": 10, "sell_lots": 0,
                 "net_lots": 10, "pct": 2.0, "source": "fixture"}
                for d in qual for bid in (1, 2)])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            compute_all()
        with db.get_engine().connect() as conn:
            ranked = [r[0] for r in conn.execute(text("SELECT branch_name FROM branch_rankings"))]
            tracked = [r[0] for r in conn.execute(text("SELECT branch_name FROM tracked_branches"))]
        self.assertIn("正常分點", ranked)
        self.assertNotIn("元大-西門(停)", ranked)
        self.assertNotIn("元大-西門(停)", tracked)
        self.assertIn("1 closed branches excluded", out.getvalue())


class ExportHidesClosedFromOldSnapshotsTests(_DB):
    def test_an_old_snapshot_with_a_closed_branch_is_filtered_on_export(self):
        """新快照已不含停業分點;舊快照在下一次重算前仍會被讀到——匯出端再擋一次。"""
        import json
        from radar.export.json_export import export_json
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": "1101", "name": "台泥", "market": "twse", "type": "stock"}])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": "1101", "date": "2026-10-01", "close": 10, "volume": 1, "turnover": 1}])
            conn.execute(schema.branch_rankings.insert(), [
                {"branch_name": "元大-西門(停)", "as_of": "2026-10-01", "rank_score": 48.3,
                 "samples": 26, "matured_samples": 26, "style": "swing", "source": "candidate"},
                {"branch_name": "兆豐-嘉義", "as_of": "2026-10-01", "rank_score": 40.0,
                 "samples": 100, "matured_samples": 100, "style": "swing", "source": "candidate"},
            ])
        out = Path(self.tmp.name) / "out"
        export_json(out)
        payload = json.loads((out / "branches" / "rankings.json").read_text(encoding="utf-8"))
        names = [r["branch_name"] for r in payload["rankings"]]
        self.assertEqual(names, ["兆豐-嘉義"])


if __name__ == "__main__":
    unittest.main()
