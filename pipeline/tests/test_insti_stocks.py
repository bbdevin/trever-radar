"""法人買賣超個股(docs/49 §9):排行純函式、連續日數、種子 DB 匯出與隔離。"""
import json
import math
import unittest
from datetime import datetime as real_datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import radar.config as config
import radar.db as db
from radar import schema
from radar.export import json_export
from radar.export import insti_stocks as mod
from radar.export.insti_group_flow import IDENTITIES
from radar.export.json_export import export_json

D = "2026-10-07"
P = "2026-10-06"
PP = "2026-10-05"


def row(sid, foreign=0, trust=0, dealer=0, close=100.0, market="twse", industry="半導體業"):
    return {
        "id": sid, "name": f"股{sid}", "market": market, "industry": industry,
        "net": {"foreign": foreign, "trust": trust, "dealer": dealer,
                "total": foreign + trust + dealer},
        "close": close, "chg_pct": 1.0,
    }


def lots0(shares):
    """獨立重算:向零截斷(不用模組的 trunc_lots)。"""
    return int(math.trunc(shares / 1000))


class RankTests(unittest.TestCase):
    def test_sides_ranked_by_amount_with_ties(self):
        rows = [
            row("1003", foreign=10_000, close=100.0),   # 1,000,000
            row("1001", foreign=20_000, close=50.0),    # 1,000,000,張數多 → 前
            row("1002", foreign=10_000, close=100.0),   # 同金額同張數 → 代號 1002 < 1003
            row("1004", foreign=5_000, close=1000.0),   # 5,000,000 → 第一
            row("2001", foreign=-3_000, close=100.0),
            row("2002", foreign=-3_000, close=100.0),
            row("2003", foreign=-1_000, close=900.0),   # -900,000 → 最負
            row("3001", foreign=-999, close=100.0),     # 零股:不算賣超
            row("3002", foreign=500, close=100.0),      # 零股:不算買超
        ]
        r = mod.rank(rows)["foreign"]
        self.assertEqual([x["id"] for x in r["buy"]], ["1004", "1001", "1002", "1003"])
        self.assertEqual([x["id"] for x in r["sell"]], ["2003", "2001", "2002"])
        self.assertEqual((r["buy_n"], r["sell_n"]), (4, 3))
        top = r["buy"][0]
        self.assertEqual((top["net_lots"], top["amt_est"], top["ind"]), (5, 5_000_000, "半導體業"))
        # 輸入順序不影響輸出
        self.assertEqual(mod.rank(list(reversed(rows))), mod.rank(rows))

    def test_top_n_and_missing_close_last(self):
        rows = [row(f"{i:04d}", trust=(i + 1) * 1000, close=10.0) for i in range(40)]
        rows.append(row("9999", trust=900_000, close=None))
        r = mod.rank(rows)["trust"]
        self.assertEqual(len(r["buy"]), mod.TOP_N)
        self.assertEqual(r["buy_n"], 41)
        self.assertEqual(r["buy"][0]["id"], "0039")
        self.assertNotIn("9999", [x["id"] for x in r["buy"]])
        small = mod.rank(rows, top_n=50)["trust"]["buy"]
        self.assertEqual(small[-1]["id"], "9999")
        self.assertEqual((small[-1]["amt_est"], small[-1]["amt_missing"]), (0, True))
        self.assertNotIn("amt_missing", small[0])

    def test_streak(self):
        dates = [D, P, PP]
        hist = {
            ("A", D): {"foreign": 2000}, ("A", P): {"foreign": 1000}, ("A", PP): {"foreign": 3000},
            ("B", D): {"foreign": -2000}, ("B", P): {"foreign": -1500}, ("B", PP): {"foreign": 5000},
            ("C", D): {"foreign": 2000}, ("C", PP): {"foreign": 3000},          # 中間缺列 → 1
            ("E", D): {"foreign": 2000}, ("E", P): {"foreign": 999},           # 零股 → 1
        }
        self.assertEqual(mod.streak(hist, "A", "foreign", dates), 3)
        self.assertEqual(mod.streak(hist, "B", "foreign", dates), 2)
        self.assertEqual(mod.streak(hist, "C", "foreign", dates), 1)
        self.assertEqual(mod.streak(hist, "E", "foreign", dates), 1)
        self.assertEqual(mod.streak(hist, "Z", "foreign", dates), 0)
        self.assertEqual(mod.streak(hist, "A", "foreign", []), 0)

    def test_partial_stale_and_compact(self):
        p = mod.build([row("1", foreign=1000)], {}, [], as_of=P, data_date=D, generated_at="x")
        self.assertTrue(p["stale"])
        self.assertEqual(p["coverage"], {"twse": 1, "tpex": 0, "partial": True})
        self.assertEqual(p["ranks"]["foreign"]["buy"][0]["streak"], 0)
        s = mod.serialize(p)
        self.assertNotIn(": ", s)
        self.assertNotIn(", ", s)


class InstiStocksExportTests(unittest.TestCase):
    STOCKS = [
        ("2330", "台積電", "twse", "stock", "半導體業"),
        ("2454", "聯發科", "twse", "stock", "半導體業"),
        ("2303", "聯電", "twse", "stock", "半導體業"),
        ("6488", "環球晶", "tpex", "stock", "半導體業"),   # 停牌:當日無價
        ("0050", "元大台灣50", "twse", "etf", None),
        ("2881", "富邦金", "twse", "stock", "金融保險業"),
        ("2882", "國泰金", "twse", "stock", "金融保險業"),
    ]
    # (stock_id, date) → foreign_net;trust = foreign // 2(整數),dealer = -1500
    INSTI = {
        D: {"2330": 5_000_000, "2454": -1_000_000, "2303": 2_000_000, "6488": 3_000_000,
            "0050": 90_000_000, "2881": -4_000_000, "2882": -4_000_000},
        P: {"2330": 1_000_000, "2454": -2_000_000, "2303": -500, "6488": 1_000,
            "0050": 1_000_000, "2881": -1_000, "2882": 7_000},
        PP: {"2330": 9_000, "2454": -3_000, "2303": 1_000, "6488": 1_000,
             "0050": 1_000, "2881": -1_000, "2882": -1_000},
    }

    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._old_url, self._old_dir = config.DB_URL, config.DATA_DIR
        config.DATA_DIR = tmp
        config.DB_URL = "sqlite:///" + (tmp / "t.db").as_posix()
        db._engine = None
        db.init_db()
        self.tmp = tmp
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": s, "name": n, "market": m, "type": t, "industry": ind, "is_active": 1}
                for s, n, m, t, ind in self.STOCKS])
            prices = []
            for s, *_ in self.STOCKS:
                prices.append({"stock_id": s, "date": P, "close": 100.0, "volume": 1000, "turnover": 1e8})
                if s != "6488":
                    close = 200.0 if s == "2882" else 110.0
                    prices.append({"stock_id": s, "date": D, "close": close, "volume": 1000, "turnover": 1e8})
            conn.execute(schema.daily_prices.insert(), prices)
            conn.execute(schema.daily_institutional.insert(), [
                {"stock_id": s, "date": d, "foreign_net": f, "trust_net": f // 2,
                 "dealer_net": -1500, "total_net": f + f // 2 - 1500}
                for d, m in self.INSTI.items() for s, f in m.items()])

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old_url, self._old_dir
        self._tmp.cleanup()

    def _path(self, out=None):
        return (out or self.tmp / "out") / "rankings" / mod.FILE_1D

    def _expected(self, ident):
        """獨立重算:直接從種子表算 (id, lots, amt),不經模組。"""
        closes = {s: (200.0 if s == "2882" else 110.0) for s, *_ in self.STOCKS}
        closes["6488"] = 100.0  # 停牌回退前一日收盤
        out = []
        for s, f in self.INSTI[D].items():
            if s == "0050":
                continue
            shares = {"foreign": f, "trust": f // 2, "dealer": -1500,
                      "total": f + f // 2 - 1500}[ident]
            out.append((s, lots0(shares), round(shares * closes[s])))
        buy = sorted((x for x in out if x[1] > 0), key=lambda x: (-x[2], -x[1], x[0]))
        sell = sorted((x for x in out if x[1] < 0), key=lambda x: (x[2], x[1], x[0]))
        return buy, sell

    def test_export_values_recomputed_independently(self):
        export_json(self.tmp / "out")
        raw = self._path().read_text(encoding="utf-8")
        p = json.loads(raw)
        self.assertEqual((p["as_of"], p["data_date"], p["stale"]), (D, D, False))
        self.assertEqual(p["coverage"], {"twse": 5, "tpex": 1, "partial": False})
        self.assertEqual(p["streak_days"], 3)
        for ident in IDENTITIES:
            buy, sell = self._expected(ident)
            got = p["ranks"][ident]
            self.assertEqual([(r["id"], r["net_lots"], r["amt_est"]) for r in got["buy"]], buy, ident)
            self.assertEqual([(r["id"], r["net_lots"], r["amt_est"]) for r in got["sell"]], sell, ident)
            self.assertEqual((got["buy_n"], got["sell_n"]), (len(buy), len(sell)))
        ids = {r["id"] for v in p["ranks"].values() for side in ("buy", "sell") for r in v[side]}
        self.assertNotIn("0050", ids)  # ETF 排除
        f = {r["id"]: r for r in p["ranks"]["foreign"]["buy"] + p["ranks"]["foreign"]["sell"]}
        # 2881/2882 同張數 −4,000;2882 收盤較高 → 金額更負排前
        self.assertEqual([r["id"] for r in p["ranks"]["foreign"]["sell"]], ["2882", "2881", "2454"])
        self.assertIsNone(f["6488"]["chg_pct"])
        self.assertEqual(f["2330"]["chg_pct"], 10.0)
        # 連續日數:2330 三日皆買;2454 三日皆賣;2303 前一日零股 → 1;2882 前一日反向 → 1
        self.assertEqual({k: f[k]["streak"] for k in ("2330", "2454", "2303", "2882", "6488")},
                         {"2330": 3, "2454": 3, "2303": 1, "2882": 1, "6488": 3})
        self.assertNotIn(": ", raw)
        self.assertFalse(self._path().with_suffix(".json.tmp").exists())

    def test_stale_and_partial(self):
        with db.get_engine().begin() as conn:
            conn.execute(schema.daily_institutional.delete().where(
                schema.daily_institutional.c.date == D))
            conn.execute(schema.daily_institutional.delete().where(
                schema.daily_institutional.c.stock_id == "6488"))
        export_json(self.tmp / "out")
        p = json.loads(self._path().read_text(encoding="utf-8"))
        self.assertEqual((p["as_of"], p["data_date"], p["stale"]), (P, D, True))
        self.assertEqual(p["coverage"], {"twse": 5, "tpex": 0, "partial": True})

    def test_no_insti_no_file(self):
        with db.get_engine().begin() as conn:
            conn.execute(schema.daily_institutional.delete())
        export_json(self.tmp / "out")
        self.assertFalse(self._path().exists())

    def test_failure_removes_stale_file_and_keeps_others(self):
        out = self.tmp / "out"
        export_json(out)
        self.assertTrue(self._path().exists())
        with mock.patch.object(mod, "load_history", side_effect=RuntimeError("boom")), \
                self.assertLogs("radar.export.json_export", level="WARNING") as logs:
            export_json(out)
        self.assertIn("insti_stocks export failed", "\n".join(logs.output))
        self.assertFalse(self._path().exists())
        for rel in ("radar.json", "meta.json", "stocks_index.json", "home/head.json",
                    "home/stocks.json", "rankings/insti_flow_1d.json"):
            self.assertTrue((out / rel).exists(), rel)

    def test_flow_failure_does_not_block_stocks_file(self):
        from radar.export import insti_group_flow
        with mock.patch.object(insti_group_flow, "fit_budget", side_effect=RuntimeError("boom")), \
                self.assertLogs("radar.export.json_export", level="WARNING"):
            export_json(self.tmp / "out")
        self.assertTrue(self._path().exists())

    def test_other_outputs_byte_identical(self):
        """有沒有寫個股檔,radar.json、home/*.json、insti_flow_1d.json 逐位元相同。"""
        fixed = real_datetime(2026, 10, 7, 21, 0, 0)

        class Frozen(real_datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed.replace(tzinfo=tz)

        def snapshot(out):
            files = [out / "radar.json", out / "rankings" / "insti_flow_1d.json",
                     *sorted((out / "home").glob("*.json"))]
            return {f.relative_to(out).as_posix(): f.read_bytes() for f in files}

        with mock.patch.object(json_export, "datetime", Frozen):
            with mock.patch.object(json_export, "write_insti_stocks", lambda *a, **k: None):
                export_json(self.tmp / "a")
            export_json(self.tmp / "b")
        a, b = snapshot(self.tmp / "a"), snapshot(self.tmp / "b")
        self.assertGreater(len(a), 2)
        self.assertEqual(a, b)
        self.assertFalse(self._path(self.tmp / "a").exists())
        self.assertTrue(self._path(self.tmp / "b").exists())


if __name__ == "__main__":
    unittest.main()
