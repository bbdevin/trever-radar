"""sectors[].subs(產業下鑽子題材)聚合口徑的最小種子 DB 驗證。

種子:半導體(2330/2303/2454/3105)+ 電子零組件(2317),兩個交易日。
題材:矽晶圓(2330,2303)、BBU(2454)、半導體(同名)、AI伺服器(2330,2454,2317)。
驗證:≥2 檔門檻、同名題材排除、金額只計產業內成分、vs20 以 (產業,題材) 口徑、
top 依金額排序且只含產業內成分、題材模式不帶 subs。
"""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import radar.config as config
import radar.db as db
from radar import schema
from radar.export.json_export import export_json

D = "2026-07-09"
P = "2026-07-08"


class SectorSubsExportTests(unittest.TestCase):
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
            conn.execute(schema.stocks.insert(), [
                {"id": "2330", "name": "台積電", "market": "twse", "type": "stock", "industry": "半導體", "is_active": 1},
                {"id": "2303", "name": "聯電", "market": "twse", "type": "stock", "industry": "半導體", "is_active": 1},
                {"id": "2454", "name": "聯發科", "market": "twse", "type": "stock", "industry": "半導體", "is_active": 1},
                {"id": "3105", "name": "穩懋", "market": "tpex", "type": "stock", "industry": "半導體", "is_active": 1},
                {"id": "2317", "name": "鴻海", "market": "twse", "type": "stock", "industry": "電子零組件", "is_active": 1},
            ])
            # (close_prev, turnover_prev, close_today, turnover_today)
            prices = {
                "2330": (1000.0, 200, 1050.0, 400),   # +5%
                "2303": (50.0, 100, 47.5, 100),       # -5%
                "2454": (1200.0, 150, 1200.0, 300),   # 0%
                "3105": (100.0, 50, 101.0, 50),       # +1%
                "2317": (200.0, 250, 210.0, 500),     # +5%
            }
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": sid, "date": dt, "close": c, "volume": 1000, "turnover": t}
                for sid, (cp, tp, cd, td) in prices.items()
                for dt, c, t in ((P, cp, tp), (D, cd, td))
            ])
            conn.execute(schema.themes.insert(), [
                {"id": "T1", "name": "矽晶圓", "source": "fubon"},
                {"id": "T2", "name": "BBU", "source": "fubon"},
                {"id": "T3", "name": "半導體", "source": "fubon"},      # 與產業同名 → 排除
                {"id": "T4", "name": "AI伺服器", "source": "fubon"},
            ])
            conn.execute(schema.stock_themes.insert(), [
                {"theme_id": "T1", "stock_id": "2330"},
                {"theme_id": "T1", "stock_id": "2303"},
                {"theme_id": "T2", "stock_id": "2454"},                  # 產業內僅 1 檔 → 排除
                {"theme_id": "T3", "stock_id": "2330"},
                {"theme_id": "T3", "stock_id": "2303"},
                {"theme_id": "T3", "stock_id": "2454"},
                {"theme_id": "T4", "stock_id": "2330"},
                {"theme_id": "T4", "stock_id": "2454"},
                {"theme_id": "T4", "stock_id": "2317"},                  # 跨產業成分不計入半導體
            ])

    def test_sector_subs_aggregation(self):
        out = Path(self._tmp.name) / "out"
        export_json(out)
        radar = json.loads((out / "radar.json").read_text(encoding="utf-8"))

        semi = next(s for s in radar["sectors"] if s["name"] == "半導體")
        # 既有欄位不變(非 breaking)
        for key in ("name", "turnover", "share", "vs20", "avg_chg", "up", "down", "top"):
            self.assertIn(key, semi)
        self.assertEqual(semi["turnover"], 850)

        subs = semi["subs"]
        self.assertEqual([x["name"] for x in subs], ["AI伺服器", "矽晶圓"])  # 金額排序,BBU/同名排除

        ai = subs[0]
        self.assertEqual(ai["turnover"], 700)            # 只計 2330+2454,不含跨產業的 2317
        self.assertEqual(ai["vs20"], 2.0)                # 700 / (200+150)
        self.assertEqual(ai["avg_chg"], 2.5)             # (5.0 + 0.0) / 2
        self.assertEqual((ai["up"], ai["down"]), (1, 0))
        self.assertEqual([t["id"] for t in ai["top"]], ["2330", "2454"])
        self.assertEqual(ai["top"][0]["chg_pct"], 5.0)

        si = subs[1]
        self.assertEqual(si["turnover"], 500)
        self.assertEqual(si["vs20"], 1.67)               # 500 / (200+100)
        self.assertEqual(si["avg_chg"], 0.0)
        self.assertEqual((si["up"], si["down"]), (1, 1))
        self.assertEqual([t["id"] for t in si["top"]], ["2330", "2303"])

        # 電子零組件:AI伺服器僅 1 檔 → 無 subs 欄位
        elec = next(s for s in radar["sectors"] if s["name"] == "電子零組件")
        self.assertNotIn("subs", elec)

        # 題材模式(themes)不帶 subs
        self.assertTrue(all("subs" not in t for t in radar.get("themes", [])))


if __name__ == "__main__":
    unittest.main()
