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


class TrackedBranchHistoryExportTests(unittest.TestCase):
    """docs/24 §3 B1:追蹤分點近 120 日明細 export(branches/track/*.json + index)。"""

    AS_OF = "2026-07-10"

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
                {"id": "2330", "name": "台積電", "market": "twse", "type": "stock", "is_active": 1},
                {"id": "2317", "name": "鴻海", "market": "twse", "type": "stock", "is_active": 1},
                {"id": "2454", "name": "聯發科", "market": "twse", "type": "stock", "is_active": 1},
            ])
            # 07-09 有值;07-10 中 2454 close 為 NULL,用來驗證「期末收盤取最近有值日」的回退。
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": "2330", "date": "2026-07-09", "close": 1080.0, "volume": 1000, "turnover": 100},
                {"stock_id": "2317", "date": "2026-07-09", "close": 205.0, "volume": 1000, "turnover": 100},
                {"stock_id": "2454", "date": "2026-07-09", "close": 1200.0, "volume": 1000, "turnover": 100},
                {"stock_id": "2330", "date": "2026-07-10", "close": 1085.0, "volume": 1000, "turnover": 100},
                {"stock_id": "2317", "date": "2026-07-10", "close": 210.0, "volume": 1000, "turnover": 100},
                {"stock_id": "2454", "date": "2026-07-10", "close": None, "volume": 1000, "turnover": 100},
            ])
            conn.execute(schema.tracked_branches.insert(), [
                {"branch_name": "凱基-台北", "source": "manual"},
                {"branch_name": "富邦-新竹", "source": "auto"},
            ])
            # 分點交易:凱基/富邦 追蹤,元大 未追蹤(不應產檔)。
            conn.execute(schema.branch_trades.insert(), [
                # 凱基-台北:含賣超(net 負)、pct null、與 120 日視窗外的一列。
                {"stock_id": "2330", "date": "2026-07-09", "branch_key": "k1", "branch_name": "凱基-台北",
                 "buy_lots": 200, "sell_lots": 0, "net_lots": 200, "pct": 0.8},
                {"stock_id": "2330", "date": "2026-07-10", "branch_key": "k1", "branch_name": "凱基-台北",
                 "buy_lots": 500, "sell_lots": 150, "net_lots": 350, "pct": 1.2},
                {"stock_id": "2317", "date": "2026-07-10", "branch_key": "k1", "branch_name": "凱基-台北",
                 "buy_lots": 100, "sell_lots": 300, "net_lots": -200, "pct": None},
                {"stock_id": "2330", "date": "2026-02-01", "branch_key": "k1", "branch_name": "凱基-台北",
                 "buy_lots": 999, "sell_lots": 0, "net_lots": 999, "pct": 5.0},
                # 富邦-新竹
                {"stock_id": "2317", "date": "2026-07-06", "branch_key": "f1", "branch_name": "富邦-新竹",
                 "buy_lots": 50, "sell_lots": 50, "net_lots": 0, "pct": 0.0},
                {"stock_id": "2454", "date": "2026-07-08", "branch_key": "f1", "branch_name": "富邦-新竹",
                 "buy_lots": 300, "sell_lots": 100, "net_lots": 200, "pct": 2.1},
                # 元大-土城(未追蹤)
                {"stock_id": "2330", "date": "2026-07-10", "branch_key": "y1", "branch_name": "元大-土城",
                 "buy_lots": 400, "sell_lots": 0, "net_lots": 400, "pct": 3.3},
            ])

    def _run(self):
        out = Path(self._tmp.name) / "out"
        export_json(out)
        return out / "branches" / "track"

    def test_index_and_untracked_excluded(self):
        import hashlib
        track = self._run()
        index = json.loads((track / "index.json").read_text(encoding="utf-8"))

        # 兩個追蹤分點,依 branch_name 升冪(凱 U+51F1 < 富 U+5BCC)
        self.assertEqual([e["branch_name"] for e in index], ["凱基-台北", "富邦-新竹"])
        self.assertEqual([e["source"] for e in index], ["manual", "auto"])
        self.assertEqual([e["rows_count"] for e in index], [3, 2])          # 凱基 120 日外的列被排除
        self.assertEqual([e["first_date"] for e in index], ["2026-07-09", "2026-07-06"])

        # 未追蹤分點不產檔,也不在 index
        self.assertNotIn("元大-土城", [e["branch_name"] for e in index])
        untracked_file = hashlib.sha1("元大-土城".encode("utf-8")).hexdigest()[:16] + ".json"
        self.assertFalse((track / untracked_file).exists())

        # index 的 file 欄與實際檔名一致且存在於檔案系統
        for e in index:
            expected = hashlib.sha1(e["branch_name"].encode("utf-8")).hexdigest()[:16] + ".json"
            self.assertEqual(e["file"], expected)
            self.assertTrue((track / e["file"]).exists())

    def test_rows_format_sorting_and_window(self):
        track = self._run()
        index = json.loads((track / "index.json").read_text(encoding="utf-8"))
        kfile = next(e["file"] for e in index if e["branch_name"] == "凱基-台北")
        p = json.loads((track / kfile).read_text(encoding="utf-8"))

        self.assertEqual(p["branch_name"], "凱基-台北")
        self.assertEqual(p["source"], "manual")
        self.assertEqual(p["as_of"], self.AS_OF)
        self.assertEqual(p["days"], 120)
        self.assertNotIn("truncated", p)                                   # 未超量

        # 依 date 升冪、[date, stock_id, net_lots(帶正負), pct(可 null)]
        self.assertEqual(p["rows"], [
            ["2026-07-09", "2330", 200, 0.8],
            ["2026-07-10", "2317", -200, None],
            ["2026-07-10", "2330", 350, 1.2],
        ])
        # 120 日視窗外(2026-02-01, net 999)被排除
        self.assertNotIn("2026-02-01", [r[0] for r in p["rows"]])

    def test_stocks_lookup_name_and_close(self):
        track = self._run()
        index = json.loads((track / "index.json").read_text(encoding="utf-8"))

        kfile = next(e["file"] for e in index if e["branch_name"] == "凱基-台北")
        kp = json.loads((track / kfile).read_text(encoding="utf-8"))
        self.assertEqual(set(kp["stocks"]), {"2330", "2317"})
        self.assertEqual(kp["stocks"]["2330"], {"name": "台積電", "close": 1085.0})
        self.assertEqual(kp["stocks"]["2317"], {"name": "鴻海", "close": 210.0})

        ffile = next(e["file"] for e in index if e["branch_name"] == "富邦-新竹")
        fp = json.loads((track / ffile).read_text(encoding="utf-8"))
        # 2454 於 as_of(07-10)close 為 NULL → 回退取最近有值日 07-09 的 1200.0
        self.assertEqual(fp["stocks"]["2454"], {"name": "聯發科", "close": 1200.0})


if __name__ == "__main__":
    unittest.main()
