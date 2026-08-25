"""margin_history export + margin_usage 榜(docs/34 Phase A1)."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import radar.config as config
import radar.db as db
from radar import schema
from radar.export.json_export import export_json

D = "2026-08-20"
P = "2026-08-19"


class MarginExportTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._old_url, self._old_dir = config.DB_URL, config.DATA_DIR
        config.DATA_DIR = tmp
        config.DB_URL = "sqlite:///" + (tmp / "t.db").as_posix()
        db._engine = None
        db.init_db()
        self._seed()
        self.out = tmp / "out"

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
                {"id": "2330", "name": "台積電", "market": "twse", "type": "stock", "is_active": 1},
                {"id": "2317", "name": "鴻海", "market": "twse", "type": "stock", "is_active": 1},
            ])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": "2330", "date": P, "close": 900.0, "volume": 1000, "turnover": 900_000_000},
                {"stock_id": "2330", "date": D, "close": 920.0, "volume": 1000, "turnover": 920_000_000},
                {"stock_id": "2317", "date": P, "close": 200.0, "volume": 1000, "turnover": 200_000_000},
                {"stock_id": "2317", "date": D, "close": 210.0, "volume": 1000, "turnover": 210_000_000},
            ])
            conn.execute(schema.daily_margins.insert(), [
                {"stock_id": "2330", "date": P, "margin_balance": 1000, "margin_prev": 980,
                 "margin_limit": 2000, "margin_buy": 50, "margin_sell": 10, "margin_repay": 20,
                 "short_balance": 10, "short_prev": 12},
                {"stock_id": "2330", "date": D, "margin_balance": 1020, "margin_prev": 1000,
                 "margin_limit": 2000, "margin_buy": 30, "margin_sell": 5, "margin_repay": 5,
                 "short_balance": 8, "short_prev": 10},
                {"stock_id": "2317", "date": D, "margin_balance": 800, "margin_prev": 750,
                 "margin_limit": 1000, "margin_buy": 100, "margin_sell": 20, "margin_repay": 30,
                 "short_balance": 5, "short_prev": 5},
            ])
            conn.execute(schema.daily_scores.insert(), [
                {"stock_id": "2330", "date": D, "final": 70},
                {"stock_id": "2317", "date": D, "final": 65},
            ])

    def test_margin_history_and_ranking_export(self):
        export_json(self.out)
        stock = json.loads((self.out / "stocks" / "2330.json").read_text(encoding="utf-8"))
        self.assertIn("margin_history", stock)
        hist = stock["margin_history"]
        self.assertEqual(len(hist), 2)
        latest = hist[0]
        self.assertEqual(latest["t"], D)
        self.assertEqual(latest["balance"], 1020)
        self.assertEqual(latest["buy"], 30)
        self.assertIsNotNone(latest["cost_est"])
        self.assertAlmostEqual(latest["usage"], 1020 / 2000, places=3)

        rank = json.loads((self.out / "rankings" / "margin_usage.json").read_text(encoding="utf-8"))
        self.assertEqual(rank["as_of"], D)
        self.assertGreaterEqual(len(rank["items"]), 2)
        self.assertEqual(rank["items"][0]["id"], "2317")  # 80% usage > 51%
        self.assertGreater(rank["items"][0]["usage"], rank["items"][1]["usage"])

    def test_ranking_keeps_stock_missing_quote_day_price(self):
        """資券日有價、quotes 日無價時仍應進榜(倉和類案例)。"""
        eng = db.get_engine()
        with eng.begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": "6538", "name": "倉和", "market": "tpex", "type": "stock", "is_active": 1},
            ])
            # 只有資券日有價;quotes 日 D 沒有 → 舊 INNER JOIN 會濾掉
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": "6538", "date": P, "close": 193.0, "volume": 1000, "turnover": 193_000_000},
            ])
            conn.execute(schema.daily_margins.insert(), [
                {"stock_id": "6538", "date": D, "margin_balance": 8497, "margin_prev": 8487,
                 "margin_limit": 9610, "margin_buy": 50, "short_balance": 0, "short_prev": 0},
            ])
            conn.execute(schema.daily_scores.insert(), [
                {"stock_id": "6538", "date": D, "final": 60},
            ])
        export_json(self.out)
        rank = json.loads((self.out / "rankings" / "margin_usage.json").read_text(encoding="utf-8"))
        ids = [x["id"] for x in rank["items"]]
        self.assertIn("6538", ids)
        row = next(x for x in rank["items"] if x["id"] == "6538")
        self.assertAlmostEqual(row["usage"], 8497 / 9610, places=3)
        self.assertEqual(rank["items"][0]["id"], "6538")  # ~88% 應居冠


if __name__ == "__main__":
    unittest.main()
