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
        self.assertIn("pocket", radar["lists"])
        self.assertEqual(radar["lists"]["pocket"], [])


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
            from pipeline.radar.importer import upsert_branch_trades
            upsert_branch_trades(conn, [
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

class S4PhaseJsonExportTests(unittest.TestCase):
    """S4 V2 is additive: keep the legacy selector and expose phase detail."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._old_url, self._old_dir = config.DB_URL, config.DATA_DIR
        config.DATA_DIR = tmp
        config.DB_URL = "sqlite:///" + (tmp / "t.db").as_posix()
        db._engine = None
        db.init_db()
        reasons = {
            "1001": [{"code": "S4_VOLATILITY_CONTRACTION", "text": "legacy"}],
            "1002": [{"code": "S4_COMPRESSION_SETUP_V2", "text": "setup", "value": 24}],
        }
        reasons.update({
            str(2000 + i): [{"code": "S4_COMPRESSION_BREAKOUT_V2", "text": "breakout", "value": 136}]
            for i in range(42)
        })
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": sid, "name": sid, "market": "twse", "type": "stock", "is_active": 1}
                for sid in reasons
            ])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": sid, "date": date, "open": 100, "high": 101, "low": 99,
                 "close": 100 if date.endswith("01") else 101, "volume": 1000,
                 # Legacy/setup must not enter score, hot, surge, strong, or
                 # weak lists; their later presence in radar.stocks proves
                 # the phase-union lookup loop, not an incidental list union.
                 "turnover": 0 if sid in {"1001", "1002"} else 100_000_000}
                for sid in reasons for date in ("2026-08-01", "2026-08-04")
            ])
            conn.execute(schema.daily_scores.insert(), [
                {"stock_id": sid, "date": "2026-08-04",
                 "final": 0 if sid in {"1001", "1002"} else 70,
                 "reasons": json.dumps(rs), "risks": "[]"}
                for sid, rs in reasons.items()
            ])

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old_url, self._old_dir
        self._tmp.cleanup()

    def test_s4_union_phase_and_old_json_contract(self):
        out = Path(self._tmp.name) / "out"
        export_json(out)
        radar = json.loads((out / "radar.json").read_text(encoding="utf-8"))
        # The existing union selector remains capped at 40 breakout rows.
        self.assertEqual(len(radar["strategies"]["S4_VOLATILITY_CONTRACTION"]), 40)
        phases = radar["strategy_phases"]["S4_VOLATILITY_CONTRACTION"]
        self.assertEqual(len(phases["breakout"]), 40)
        self.assertEqual(phases["setup"], ["1002"])
        self.assertEqual(phases["legacy"], ["1001"])
        self.assertTrue({
            "S4_VOLATILITY_CONTRACTION",
            "S4_COMPRESSION_SETUP_V2",
            "S4_COMPRESSION_BREAKOUT_V2",
        }.issubset(radar["strategy_meta"]))
        # A2 lifecycle metadata is a versioned, additive contract.  It must
        # not rely on a DB migration or a particular performance result.
        for meta in radar["strategy_meta"].values():
            self.assertIn(meta["status"], {"active", "shadow", "retired"})
            self.assertRegex(meta["effective_date"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertTrue(meta["rationale"])
            self.assertTrue(meta["decision_ref"])
            self.assertGreaterEqual(meta["version"], 1)
        # Lifecycle v2 restores S2/S5 to the principal selector as Shadow.
        # This is metadata-only: no strategy formula or score contract changes.
        self.assertEqual(radar["strategy_meta"]["S2_BREAKOUT20"]["status"], "shadow")
        self.assertEqual(radar["strategy_meta"]["S5_PULLBACK_SUPPORT"]["status"], "shadow")
        self.assertEqual(radar["strategy_meta"]["S2_BREAKOUT20"]["effective_date"], "2026-08-27")
        self.assertEqual(radar["strategy_meta"]["S5_PULLBACK_SUPPORT"]["version"], 2)
        self.assertFalse(any(meta["status"] == "retired" for meta in radar["strategy_meta"].values()))
        signals = {s["id"]: s.get("strategy_signals") for s in radar["stocks"]}
        self.assertEqual(signals["2000"][0]["phase"], "breakout")
        self.assertEqual(signals["1002"][0]["phase"], "setup")
        non_strategy_ids = set().union(*radar["lists"].values())
        self.assertTrue({"1001", "1002"}.isdisjoint(non_strategy_ids))
        self.assertTrue({"1001", "1002"}.isdisjoint(radar["strategies"]["S4_VOLATILITY_CONTRACTION"]))
        # Even when the selector cap is entirely breakout, every emitted
        # phase ID resolves through radar.stocks for the frontend lookup.
        # In particular, 1001/1002 can only have arrived via phase union.
        self.assertTrue(set(phases["breakout"] + phases["setup"] + phases["legacy"]).issubset(signals))
        # No S4-only item is promoted into the global Armed/Triggered lists.
        self.assertEqual(radar["lists"]["armed"], [])
        self.assertEqual(radar["lists"]["triggered"], [])


class ArmedStateExportContractTests(unittest.TestCase):
    """A1: state lookup completeness and stale-warrant source boundaries."""

    DATES = ("2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07", "2026-08-10")
    D = DATES[-1]

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
        # Keep 56 higher-ranked S12 rows ahead of state_only in all legacy
        # selectors (including the S12 top-40), so its presence proves the
        # state-union lookup rather than an incidental legacy selector.
        high_ids = [f"h{i:02}" for i in range(41)]
        low_ids = [f"l{i:02}" for i in range(15)]
        ids = high_ids + low_ids + ["state_only", "current_only", "stale_only", "branch_stale"]
        s12 = json.dumps([{"code": "S12_BRANCH_ACCUMULATION", "text": "branch"}])
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": sid, "name": sid, "market": "twse", "type": "stock", "is_active": 1}
                for sid in ids
            ])
            price_rows = []
            for sid in ids:
                if sid in high_ids:
                    today_close, turnover = 103.0, 200_000_000
                elif sid in low_ids:
                    today_close, turnover = 100.5, 200_000_000
                else:
                    today_close, turnover = 101.0, 100_000_000
                price_rows.extend({
                    "stock_id": sid, "date": dt,
                    "close": today_close if dt == self.D else 100.0,
                    "volume": 1000, "turnover": turnover,
                } for dt in self.DATES)
            conn.execute(schema.daily_prices.insert(), price_rows)
            conn.execute(schema.daily_scores.insert(), [
                {"stock_id": sid, "date": self.D, "final": 70, "reasons": s12, "risks": "[]"}
                for sid in high_ids + low_ids
            ] + [
                {"stock_id": "state_only", "date": self.D, "final": 0, "reasons": s12, "risks": "[]"},
                {"stock_id": "branch_stale", "date": self.D, "final": 0, "reasons": s12, "risks": "[]"},
            ])

    def _export(self):
        out = Path(self._tmp.name) / "out"
        export_json(out)
        return json.loads((out / "radar.json").read_text(encoding="utf-8"))

    def _replace_warrants(self, rows):
        with db.get_engine().begin() as conn:
            conn.execute(schema.warrant_stock_daily.delete())
            conn.execute(schema.warrant_stock_daily.insert(), rows)

    def test_state_only_ids_resolve_with_existing_payload_contract(self):
        radar = self._export()
        legacy_ids = set().union(*(radar["lists"][key] for key in (
            "score", "hot", "surge", "strong", "weak", "warrant", "pocket",
        )))
        self.assertNotIn("state_only", legacy_ids)
        self.assertNotIn("state_only", radar["strategies"]["S12_BRANCH_ACCUMULATION"])
        stocks = {s["id"]: s for s in radar["stocks"]}
        state_ids = set().union(*(radar["lists"][key] for key in ("armed", "triggered", "extended", "faded")))
        self.assertTrue(state_ids.issubset(stocks))
        self.assertEqual(stocks["state_only"]["state"], "armed")
        self.assertEqual(stocks["state_only"]["sources"], ["branch"])
        self.assertIn("spark", stocks["state_only"])

    def test_current_warrant_remains_a_today_source_and_ranked(self):
        self._replace_warrants([
            {"stock_id": "current_only", "date": "2026-08-07", "call_turnover": 10_000_000},
            {"stock_id": "current_only", "date": self.D, "call_turnover": 20_000_000},
        ])
        radar = self._export()
        current = next(s for s in radar["stocks"] if s["id"] == "current_only")
        self.assertFalse(radar["freshness"]["warrant"]["stale"])
        self.assertEqual(current["sources"], ["warrant"])
        self.assertEqual(current["state"], "armed")
        self.assertIn("current_only", radar["lists"]["warrant"])

    def test_stale_warrant_keeps_payload_and_rank_but_not_today_source(self):
        self._replace_warrants([
            {"stock_id": "stale_only", "date": "2026-08-08", "call_turnover": 20_000_000},
            {"stock_id": "stale_only", "date": "2026-08-07", "call_turnover": 10_000_000},
            {"stock_id": "branch_stale", "date": "2026-08-08", "call_turnover": 20_000_000},
            {"stock_id": "branch_stale", "date": "2026-08-07", "call_turnover": 10_000_000},
        ])
        radar = self._export()
        stocks = {s["id"]: s for s in radar["stocks"]}
        stale = stocks["stale_only"]
        branch_stale = stocks["branch_stale"]
        self.assertTrue(radar["freshness"]["warrant"]["stale"])
        self.assertIsNotNone(stale["warrant"])
        self.assertIn("stale_only", radar["lists"]["warrant"])
        self.assertEqual(stale["sources"], [])
        self.assertIsNone(stale["state"])
        self.assertEqual(branch_stale["sources"], ["branch"])
        self.assertEqual(branch_stale["state"], "armed")

    def test_mixed_warrant_dates_keep_per_stock_stale_payload_honest(self):
        self._replace_warrants([
            {"stock_id": "current_only", "date": "2026-08-07", "call_turnover": 10_000_000},
            {"stock_id": "current_only", "date": self.D, "call_turnover": 20_000_000},
            {"stock_id": "stale_only", "date": "2026-08-08", "call_turnover": 20_000_000},
            {"stock_id": "stale_only", "date": "2026-08-07", "call_turnover": 10_000_000},
        ])
        radar = self._export()
        stocks = {s["id"]: s for s in radar["stocks"]}
        current = stocks["current_only"]
        stale = stocks["stale_only"]
        self.assertEqual(radar["freshness"]["warrant"]["date"], self.D)
        self.assertTrue(radar["freshness"]["warrant"]["stale"])
        self.assertTrue(radar["freshness"]["warrant"]["partial_stale"])
        self.assertEqual(radar["freshness"]["warrant"]["stale_stock_count"], 1)
        self.assertEqual(current["sources"], ["warrant"])
        self.assertEqual(current["state"], "armed")
        self.assertIsNotNone(stale["warrant"])
        self.assertIn("stale_only", radar["lists"]["warrant"])
        self.assertEqual(stale["sources"], [])
        self.assertIsNone(stale["state"])


if __name__ == "__main__":
    unittest.main()
