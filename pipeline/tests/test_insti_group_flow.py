"""法人族群(docs/49 MVP):聚合純函式 + 種子 DB 匯出。"""
import json
import unittest
from datetime import datetime as real_datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import radar.config as config
import radar.db as db
from radar import schema
from radar.export import json_export
from radar.export.insti_group_flow import (
    IDENTITIES, OTHER_GROUP, THEME_TOP, aggregate, load_rows, serialize, trunc_lots,
)
from radar.export.json_export import export_json

D = "2026-10-07"
P = "2026-10-06"


def row(sid, industry="半導體", market="twse", foreign=0, trust=0, dealer=0, total=None,
        close=100.0, chg_pct=0.0, name=None):
    return {
        "id": sid, "name": name or f"股{sid}", "market": market, "industry": industry,
        "net": {"foreign": foreign, "trust": trust, "dealer": dealer,
                "total": foreign + trust + dealer if total is None else total},
        "close": close, "chg_pct": chg_pct,
    }


def agg(rows, memberships=None, as_of=D, data_date=D):
    return aggregate(rows, memberships or {}, as_of=as_of, data_date=data_date,
                     generated_at="2026-10-07T21:00:00+08:00")


def theme(name, data_date="2026-10-05", status="active"):
    return {"id": 1, "name": name, "source": "x", "source_updated_at": None,
            "data_date": data_date, "status": status}


class AggregateTests(unittest.TestCase):
    def _market_rows(self):
        return [
            row("2330", foreign=8_210_400, close=600.0),
            row("2454", foreign=1_120_000, close=1300.0),
            row("2303", foreign=-2_050_999, close=45.0),
            row("2881", industry="金融保險", foreign=-5_000_000, close=80.0),
            row("2882", industry="金融保險", foreign=-3_000_500, close=60.0),
            row("2891", industry="金融保險", foreign=200_000, close=30.0),
            row("1101", industry="水泥工業", foreign=1_000, close=40.0),   # 只有 2 檔 → 其他
            row("1102", industry="水泥工業", foreign=-999, close=40.0),
            row("9999", industry="其他", foreign=4_500, close=10.0),       # 字面其他
            row("8888", industry=None, market="tpex", foreign=-1_500, close=20.0),
        ]

    def test_group_net_lots_equals_sum_of_members_and_market_identity(self):
        rows = self._market_rows()
        p = agg(rows)
        for ident in IDENTITIES:
            groups = p["groups"]["industry"][ident]
            other = p["groups"]["other"][ident]
            # 產業各組 + 其他 == 全市場(張數、估算金額都成立)
            self.assertEqual(sum(g["net_lots"] for g in groups) + other["net_lots"],
                             p["market"][ident]["net_lots"])
            self.assertEqual(sum(g["n"] for g in groups) + other["n"], len(rows))
            self.assertAlmostEqual(sum(g["amt_est"] for g in groups) + other["amt_est"],
                                   p["market"][ident]["amt_est"], delta=len(groups) + 1)
        semi = next(g for g in p["groups"]["industry"]["foreign"] if g["name"] == "半導體")
        # 族群 net_lots == Σ 成員 daily_institutional ÷1000(逐檔向零截斷)
        self.assertEqual(semi["net_lots"], 8_210 + 1_120 - 2_050)
        self.assertEqual(semi["net_lots"],
                         sum(m["net_lots"] for m in semi["buy_top"] + semi["sell_top"]))
        self.assertEqual(semi["amt_est"], round(8_210_400 * 600 + 1_120_000 * 1300 - 2_050_999 * 45))
        self.assertEqual((semi["n"], semi["buy_n"], semi["sell_n"]), (3, 2, 1))
        self.assertEqual(p["market"]["foreign"]["net_lots"],
                         sum(trunc_lots(r["net"]["foreign"]) for r in rows))

    def test_lots_truncate_toward_zero_and_odd_lots_are_neither_side(self):
        self.assertEqual([trunc_lots(v) for v in (-500, 500, -999, -1000, -1500, 1999, 0)],
                         [0, 0, 0, -1, -1, 1, 0])
        rows = [row("5001", foreign=-500, close=100.0), row("5002", foreign=-999, close=100.0),
                row("5003", foreign=2_000, close=100.0), row("5004", foreign=-1_500, close=100.0)]
        g = agg(rows)["groups"]["industry"]["foreign"][0]
        self.assertEqual((g["buy_n"], g["sell_n"]), (1, 1))
        self.assertEqual(g["net_lots"], 2 - 1)
        self.assertEqual([m["id"] for m in g["sell_top"]], ["5004"])
        self.assertEqual([m["id"] for m in g["buy_top"]], ["5003"])

    def test_minimum_group_size_merges_into_other(self):
        p = agg(self._market_rows())
        names = [g["name"] for g in p["groups"]["industry"]["foreign"]]
        self.assertEqual(sorted(names), ["半導體", "金融保險"])
        self.assertNotIn(OTHER_GROUP, names)
        other = p["groups"]["other"]["foreign"]
        self.assertEqual(other["name"], OTHER_GROUP)
        self.assertEqual(other["n"], 4)  # 水泥 2 + 字面其他 1 + 空白產業 1

    def test_sort_by_estimated_amount_then_lots_then_name(self):
        rows = [row(f"1{i:03d}", industry=ind, foreign=f, close=c)
                for i, (ind, f, c) in enumerate([
                    ("乙", 10_000, 100.0), ("乙", 0, 100.0), ("乙", 0, 100.0),
                    ("甲", 10_000, 100.0), ("甲", 0, 100.0), ("甲", 0, 100.0),
                    ("丙", 20_000, 50.0), ("丙", 0, 50.0), ("丙", 0, 50.0),   # 同金額、張數較多
                    ("丁", 50_000, 100.0), ("丁", 0, 1.0), ("丁", 0, 1.0),
                ])]
        p = agg(rows)
        names = [g["name"] for g in p["groups"]["industry"]["foreign"]]
        # 丁 金額最大;丙/甲/乙 同金額 1,000,000 → 丙 張數 20 > 10;甲 乙 同張數 → codepoint 升冪
        self.assertEqual(names[0], "丁")
        self.assertEqual(names[1], "丙")
        self.assertEqual(names[2:], sorted(["甲", "乙"]))

    def test_member_order_and_ties(self):
        rows = [row("2002", foreign=5_000), row("2001", foreign=5_000), row("2003", foreign=9_000),
                row("2004", foreign=1_000), row("2005", foreign=1_000), row("2006", foreign=2_000),
                row("2010", foreign=-3_000), row("2009", foreign=-3_000), row("2011", foreign=-1_000),
                row("2012", foreign=-7_000)]
        g = agg(rows)["groups"]["industry"]["foreign"][0]
        self.assertEqual([m["id"] for m in g["buy_top"]], ["2003", "2001", "2002", "2006", "2004"])
        self.assertEqual([m["id"] for m in g["sell_top"]], ["2012", "2009", "2010"])
        self.assertEqual((g["buy_n"], g["sell_n"]), (6, 4))

    def test_suspended_fallback_and_missing_close(self):
        # load_rows 已把停牌回退到最近收盤(由 DB 測試覆蓋);仍無收盤 → 金額 0、張數照算
        rows = [row("3001", foreign=2_000, close=50.0), row("3002", foreign=3_000, close=None),
                row("3003", foreign=1_000, close=10.0)]
        p = agg(rows)
        g = p["groups"]["industry"]["foreign"][0]
        self.assertEqual(g["net_lots"], 6)
        self.assertEqual(g["amt_est"], 2_000 * 50 + 1_000 * 10)
        self.assertEqual(g["amt_missing_n"], 1)
        self.assertEqual(p["amt_missing_n"], 1)
        self.assertNotIn("amt_missing_n", agg([row("1", close=1.0)] * 1)["groups"]["other"]["foreign"])

    def test_partial_and_stale(self):
        twse_only = agg([row("1", foreign=1000)], as_of=P, data_date=D)
        self.assertTrue(twse_only["stale"])
        self.assertEqual(twse_only["coverage"], {"twse": 1, "tpex": 0, "partial": True})
        both = agg([row("1"), row("2", market="tpex")])
        self.assertFalse(both["stale"])
        self.assertFalse(both["coverage"]["partial"])

    def test_theme_dedupe_future_threshold_and_stale_label(self):
        rows = [row("4001", foreign=100_000, close=100.0), row("4002", foreign=100_000, close=100.0),
                row("4003", foreign=100_000, close=100.0), row("4004", foreign=100_000, close=100.0)]
        memberships = {
            # 4001 同名題材出現兩次(兩個來源 id)→ 只算一次
            "4001": [theme("AI伺服器"), theme("AI伺服器"), theme("小題材")],
            "4002": [theme("AI伺服器"), theme("小題材")],
            "4003": [theme("AI伺服器", status="stale", data_date="2026-09-01")],
            # 未來 membership 不算
            "4004": [theme("AI伺服器", data_date="2026-10-20"), theme("小題材")],
        }
        p = agg(rows, memberships)
        groups = {g["name"]: g for g in p["groups"]["theme"]["foreign"]}
        ai = groups["AI伺服器"]
        self.assertEqual(ai["n"], 3)
        self.assertEqual(ai["net_lots"], 300)
        self.assertEqual(ai["cls_date"], "2026-09-01")
        self.assertNotIn("cls_date", groups["小題材"])
        # 題材重疊:合計不等於全市場,也不輸出題材合計
        self.assertNotIn("theme", p["market"])
        # 不足 3 檔不排名;|金額| < 1,000 萬不輸出
        small = agg(rows[:3], {"4001": [theme("T")], "4002": [theme("T")]})
        self.assertEqual(small["groups"]["theme"]["foreign"], [])
        tiny = agg([row(s, foreign=1_000, close=10.0) for s in ("1", "2", "3")],
                   {s: [theme("T")] for s in ("1", "2", "3")})
        self.assertEqual(tiny["groups"]["theme"]["foreign"], [])

    def test_theme_top_20_each_side(self):
        rows, memberships = [], {}
        for t in range(25):
            for k in range(3):
                for sign in (1, -1):
                    sid = f"{'B' if sign > 0 else 'S'}{t:02d}{k}"
                    rows.append(row(sid, foreign=sign * (t + 1) * 1_000_000, close=10.0))
                    memberships[sid] = [theme(f"{'買' if sign > 0 else '賣'}{t:02d}")]
        p = agg(rows, memberships)
        lst = p["groups"]["theme"]["foreign"]
        buys = [g for g in lst if g["amt_est"] > 0]
        sells = [g for g in lst if g["amt_est"] < 0]
        self.assertEqual((len(buys), len(sells)), (THEME_TOP, THEME_TOP))
        self.assertEqual(buys[0]["name"], "買24")
        self.assertEqual(min(sells, key=lambda g: g["amt_est"])["name"], "賣24")
        self.assertNotIn("買00", [g["name"] for g in buys])
        self.assertEqual(lst, sorted(lst, key=lambda g: (-g["amt_est"], -g["net_lots"], g["name"])))

    def test_budget_cuts_members_then_theme_groups(self):
        from radar.export import insti_group_flow as mod
        rows = [row(f"{i:04d}", foreign=(i - 10) * 1_000_000, close=100.0) for i in range(21)]
        kw = dict(as_of=D, data_date=D, generated_at="x")
        full = json.loads(mod.fit_budget(rows, {}, **kw))
        g = full["groups"]["industry"]["foreign"][0]
        self.assertEqual((len(g["buy_top"]), len(g["sell_top"])), (5, 3))
        small = len(serialize(aggregate(rows, {}, **kw, buy_top=3, sell_top=2)).encode())
        with mock.patch.object(mod, "MAX_RAW_BYTES", small):
            cut = json.loads(mod.fit_budget(rows, {}, **kw))
        g = cut["groups"]["industry"]["foreign"][0]
        self.assertEqual((len(g["buy_top"]), len(g["sell_top"])), (3, 2))
        with mock.patch.object(mod, "MAX_RAW_BYTES", 10), \
                self.assertLogs("radar.export.insti_group_flow", level="WARNING") as logs:
            last = json.loads(mod.fit_budget(rows, {}, **kw))
        self.assertIn("after last budget step", logs.output[0])
        self.assertEqual(len(last["groups"]["industry"]["foreign"][0]["buy_top"]), 3)
        # 恆等式不受成員裁切影響
        self.assertEqual(g["net_lots"], cut["market"]["foreign"]["net_lots"] - cut["groups"].get(
            "other", {}).get("foreign", {}).get("net_lots", 0))

    def test_serialization_is_compact_and_stable(self):
        rows = self._market_rows()
        a = serialize(agg(rows))
        b = serialize(agg(list(reversed(rows))))
        self.assertEqual(a, b)
        self.assertNotIn(": ", a)
        self.assertNotIn(", ", a)


class InstiFlowExportTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._old_url, self._old_dir = config.DB_URL, config.DATA_DIR
        config.DATA_DIR = tmp
        config.DB_URL = "sqlite:///" + (tmp / "t.db").as_posix()
        db._engine = None
        db.init_db()
        self.tmp = tmp
        self._seed()

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old_url, self._old_dir
        self._tmp.cleanup()

    def _seed(self, insti_date=D):
        stocks = [
            ("2330", "台積電", "twse", "stock", "半導體業"),
            ("2454", "聯發科", "twse", "stock", "半導體業"),
            ("2303", "聯電", "twse", "stock", "半導體業"),
            ("6488", "環球晶", "tpex", "stock", "半導體業"),   # 停牌:當日無價
            ("0050", "元大台灣50", "twse", "etf", None),
            ("2881", "富邦金", "twse", "stock", "金融保險業"),
        ]
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": s, "name": n, "market": m, "type": t, "industry": ind, "is_active": 1}
                for s, n, m, t, ind in stocks])
            prices = []
            for s, *_ in stocks:
                prices.append({"stock_id": s, "date": P, "close": 100.0, "volume": 1000, "turnover": 1e8})
                if s != "6488":
                    prices.append({"stock_id": s, "date": D, "close": 110.0, "volume": 1000, "turnover": 1e8})
            conn.execute(schema.daily_prices.insert(), prices)
            conn.execute(schema.daily_institutional.insert(), [
                {"stock_id": s, "date": insti_date, "foreign_net": f, "trust_net": 0,
                 "dealer_net": 0, "total_net": f}
                for s, f in [("2330", 5_000_000), ("2454", -1_000_000), ("2303", 2_000_000),
                             ("6488", 3_000_000), ("0050", 90_000_000), ("2881", -4_000_000)]])

    def _load(self):
        return json.loads((self.tmp / "out" / "rankings" / "insti_flow_1d.json").read_text(encoding="utf-8"))

    def test_export_writes_file_excluding_etf_with_suspended_fallback(self):
        export_json(self.tmp / "out")
        p = self._load()
        self.assertEqual((p["as_of"], p["data_date"], p["stale"]), (D, D, False))
        self.assertEqual(p["coverage"], {"twse": 4, "tpex": 1, "partial": False})
        # ETF 0050 的 90,000 張不進全市場
        self.assertEqual(p["market"]["foreign"]["net_lots"], 5000 - 1000 + 2000 + 3000 - 4000)
        semi = p["groups"]["industry"]["foreign"][0]
        self.assertEqual(semi["name"], "半導體業")
        # 6488 停牌:取前一日收盤 100 估金額,漲跌幅不給
        m6488 = next(m for m in semi["buy_top"] if m["id"] == "6488")
        self.assertEqual(m6488["amt_est"], 3_000_000 * 100)
        self.assertIsNone(m6488["chg_pct"])
        m2330 = next(m for m in semi["buy_top"] if m["id"] == "2330")
        self.assertEqual(m2330["chg_pct"], 10.0)
        self.assertEqual(p["amt_missing_n"], 0)
        # 金融保險 只有 1 檔 → 其他
        self.assertEqual(p["groups"]["other"]["foreign"]["n"], 1)
        raw = (self.tmp / "out" / "rankings" / "insti_flow_1d.json").read_text(encoding="utf-8")
        self.assertNotIn(": ", raw)
        self.assertFalse((self.tmp / "out" / "rankings" / "insti_flow_1d.json.tmp").exists())

    def test_load_rows_keeps_suspended_stock(self):
        with db.get_engine().connect() as conn:
            rows = load_rows(conn, D)
        self.assertEqual([r["id"] for r in rows], ["2303", "2330", "2454", "2881", "6488"])
        self.assertEqual(next(r for r in rows if r["id"] == "6488")["close"], 100.0)

    def test_stale_insti_date(self):
        with db.get_engine().begin() as conn:
            conn.execute(schema.daily_institutional.delete())
        self._seed_insti_only(P)
        export_json(self.tmp / "out")
        p = self._load()
        self.assertEqual((p["as_of"], p["data_date"], p["stale"]), (P, D, True))

    def _seed_insti_only(self, d):
        with db.get_engine().begin() as conn:
            conn.execute(schema.daily_institutional.insert(), [
                {"stock_id": "2330", "date": d, "foreign_net": 1000, "trust_net": 0,
                 "dealer_net": 0, "total_net": 1000}])

    def test_no_insti_no_file(self):
        with db.get_engine().begin() as conn:
            conn.execute(schema.daily_institutional.delete())
        export_json(self.tmp / "out")
        self.assertFalse((self.tmp / "out" / "rankings" / "insti_flow_1d.json").exists())

    def test_insti_failure_does_not_abort_export(self):
        out = self.tmp / "out"
        export_json(out)  # 先有一份舊檔
        self.assertTrue((out / "rankings" / "insti_flow_1d.json").exists())
        from radar.export import insti_group_flow as mod
        with mock.patch.object(mod, "load_rows", side_effect=RuntimeError("boom")), \
                self.assertLogs("radar.export.json_export", level="WARNING") as logs:
            export_json(out)
        self.assertIn("insti_flow export failed", "\n".join(logs.output))
        # 舊檔刪掉(舊的 stale 是當時算的),其餘檔照常寫完
        self.assertFalse((out / "rankings" / "insti_flow_1d.json").exists())
        for rel in ("radar.json", "meta.json", "stocks_index.json", "home/head.json",
                    "home/stocks.json"):
            self.assertTrue((out / rel).exists(), rel)
        self.assertTrue(any((out / "stocks" / "core").glob("*.json")))

    def test_margin_usage_failure_does_not_abort_export(self):
        out = self.tmp / "out"
        with mock.patch.object(json_export, "_export_margin_usage", side_effect=RuntimeError("boom")), \
                self.assertLogs("radar.export.json_export", level="WARNING"):
            export_json(out)
        self.assertTrue((out / "rankings" / "insti_flow_1d.json").exists())
        self.assertTrue((out / "stocks_index.json").exists())

    def test_radar_and_home_bytes_unchanged(self):
        """有沒有寫法人族群檔,radar.json 與 home/*.json 逐位元相同。"""
        fixed = real_datetime(2026, 10, 7, 21, 0, 0)

        class Frozen(real_datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed.replace(tzinfo=tz)

        def snapshot(out):
            files = [out / "radar.json", *sorted((out / "home").glob("*.json"))]
            return {f.relative_to(out).as_posix(): f.read_bytes() for f in files}

        with mock.patch.object(json_export, "datetime", Frozen):
            with mock.patch.object(json_export, "write_insti_flow", lambda *a, **k: None):
                export_json(self.tmp / "a")
            export_json(self.tmp / "b")
        a, b = snapshot(self.tmp / "a"), snapshot(self.tmp / "b")
        self.assertGreater(len(a), 1)
        self.assertEqual(a, b)
        self.assertFalse((self.tmp / "a" / "rankings" / "insti_flow_1d.json").exists())
        self.assertTrue((self.tmp / "b" / "rankings" / "insti_flow_1d.json").exists())


if __name__ == "__main__":
    unittest.main()
