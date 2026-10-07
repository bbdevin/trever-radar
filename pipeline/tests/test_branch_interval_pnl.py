"""區間損益(估算)`pnl-avgcost-v1` 的手算夾具(docs/42)。

每個案例的數字都是手算的;改公式時這裡會先壞。
"""
import json
import random
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import radar.config as config
import radar.db as db
from radar.export.stock_parts import read_merged_stock
from radar import schema
from radar.compute.branch_interval_pnl import (
    DEFINITIONS_VERSION,
    MIN_BUY_LOTS,
    MIN_MAX_COST,
    TOP_N,
    branch_pnl_payload,
    simulate_pair,
)
from radar.export.json_export import export_json
from radar.importer import upsert_branch_trades


def _dates(n, start=1):
    # 2026-08-01 起連續日期字串;只需要可排序
    out = []
    for i in range(start, start + n):
        m, d = divmod(i - 1, 28)
        out.append(f"2026-{8 + m:02d}-{d + 1:02d}")
    return out


def _payload(trades, closes, *, as_of="2026-12-31", extra_dates=()):
    """trades: [(date, name, net)];closes: {date: close} 或 {date: (close, af)}。"""
    candles = []
    for d, v in closes.items():
        c, af = v if isinstance(v, tuple) else (v, 1.0)
        candles.append((d, c, af))
    rows = list(trades) + [(d, "_filler", 0) for d in extra_dates]
    return branch_pnl_payload(rows, sorted(candles), as_of_limit=as_of)


def _row(payload, name, window="all"):
    w = payload["windows"][window]
    for r in w["gainers"] + w["losers"]:
        if r["name"] == name:
            return r
    return None


class SimulateTests(unittest.TestCase):
    def test_single_buy_then_full_sell(self):
        # 買 100 張 @100,全賣 @120 → 已實現 100×20×1000 = 2,000,000;持股 0
        r = simulate_pair([(100, 100.0), (-100, 120.0)], 130.0)
        self.assertEqual(r.realized, 2_000_000)
        self.assertEqual(r.unrealized, 0)
        self.assertEqual(r.pos_lots, 0)
        self.assertEqual(r.max_cost, 10_000_000)
        self.assertEqual(r.sell_lots_unattributed, 0)

    def test_partial_sells_keep_avg(self):
        # 買 100@100、買 100@110 → 均價 105;賣 50@120 → 已實現 50×15×1000=750,000;
        # 剩 150 張,均價仍 105;現價 100 → 未實現 150×(−5)×1000 = −750,000
        r = simulate_pair([(100, 100.0), (100, 110.0), (-50, 120.0)], 100.0)
        self.assertAlmostEqual(r.avg_cost, 105.0)
        self.assertAlmostEqual(r.realized, 750_000)
        self.assertAlmostEqual(r.unrealized, -750_000)
        self.assertAlmostEqual(r.est_total, 0)
        self.assertEqual(r.pos_lots, 150)
        self.assertAlmostEqual(r.max_cost, 21_000_000)

    def test_rebuy_after_partial(self):
        # 買 100@100,賣 60@110(已實現 600,000),剩 40@100;再買 60@90 → 均價 (4000+5400)/100 = 94
        r = simulate_pair([(100, 100.0), (-60, 110.0), (60, 90.0)], 95.0)
        self.assertAlmostEqual(r.realized, 600_000)
        self.assertAlmostEqual(r.avg_cost, 94.0)
        self.assertEqual(r.pos_lots, 100)
        self.assertAlmostEqual(r.unrealized, 100 * 1 * 1000)
        # max_cost:t1 10,000,000;t2 4,000,000;t3 9,400,000
        self.assertAlmostEqual(r.max_cost, 10_000_000)

    def test_sells_before_any_buy_are_unattributed(self):
        r = simulate_pair([(-30, 100.0), (50, 100.0), (-80, 110.0)], 110.0)
        self.assertEqual(r.sell_lots_unattributed, 30 + 30)
        self.assertEqual(r.sell_lots_attributed, 50)
        self.assertEqual(r.pos_lots, 0)
        self.assertAlmostEqual(r.realized, 50 * 10 * 1000)
        self.assertEqual(r.unrealized, 0)

    def test_accounting_identity_random(self):
        rng = random.Random(20261003)
        for _ in range(500):
            seq = [(rng.choice([-1, 1]) * rng.randint(1, 400), rng.uniform(5, 900))
                   for _ in range(rng.randint(1, 60))]
            p_last = rng.uniform(5, 900)
            r = simulate_pair(seq, p_last)
            identity = r.sell_proceeds + r.pos_lots * p_last * 1000 - r.buy_cost
            self.assertAlmostEqual(r.est_total, identity, delta=1e-6 * max(1.0, abs(r.buy_cost)))
            self.assertGreaterEqual(r.pos_lots, 0)
            self.assertAlmostEqual(
                r.buy_lots - r.sell_lots_attributed, r.pos_lots, places=6)


class PayloadTests(unittest.TestCase):
    def test_shape_and_full_round_trip(self):
        ds = _dates(3)
        p = _payload([(ds[0], "A", 100), (ds[2], "A", -100)], {ds[0]: 100.0, ds[1]: 110.0, ds[2]: 120.0})
        self.assertEqual(p["as_of"], ds[2])
        self.assertEqual(p["definitions_version"], DEFINITIONS_VERSION)
        self.assertEqual(set(p["windows"]), {"60", "240", "all"})
        row = _row(p, "A")
        self.assertEqual(row["est_total"], 2_000_000)
        self.assertEqual(row["realized"], 2_000_000)
        self.assertEqual(row["unrealized"], 0)
        self.assertEqual(row["pos_lots"], 0)
        self.assertEqual(row["last_close"], 120.0)
        self.assertEqual(row["buy_lots"], 100)
        self.assertEqual(row["sell_lots_attributed"], 100)
        self.assertEqual(row["visible_days"], 2)
        self.assertEqual(row["max_cost"], 10_000_000)
        self.assertEqual(row["ret_pct"], 20.0)
        self.assertFalse(row["af_adjusted"])
        self.assertEqual((row["first_date"], row["last_date"]), (ds[0], ds[2]))
        self.assertEqual(set(row), {
            "name", "est_total", "realized", "unrealized", "pos_lots", "avg_cost",
            "last_close", "buy_lots", "sell_lots_attributed", "sell_lots_unattributed",
            "visible_days", "max_cost", "ret_pct", "af_adjusted", "first_date", "last_date"})
        w = p["windows"]["all"]
        self.assertEqual(w["window_days"], 2)  # 只有 A 出現過的兩天是可見交易日
        self.assertEqual(w["first_date"], ds[0])
        self.assertEqual(w["pairs_considered"], 1)
        self.assertEqual(w["pairs_skipped_missing_price"], 0)

    def test_af_normalisation(self):
        # 買在 af=0.5 那天(close 200 → 換算 100),今日 af=1 close 120
        ds = _dates(2)
        p = _payload([(ds[0], "A", 100), (ds[1], "A", 0)], {ds[0]: (200.0, 0.5), ds[1]: (120.0, 1.0)})
        row = _row(p, "A")
        self.assertEqual(row["avg_cost"], 100.0)
        self.assertEqual(row["unrealized"], 2_000_000)
        self.assertTrue(row["af_adjusted"])

    def test_af_ratio_when_last_not_one(self):
        ds = _dates(2)
        p = _payload([(ds[0], "A", 100), (ds[1], "A", 0)], {ds[0]: (100.0, 2.0), ds[1]: (110.0, 2.0)})
        row = _row(p, "A")
        self.assertEqual(row["avg_cost"], 100.0)
        self.assertEqual(row["est_total"], 1_000_000)
        self.assertFalse(row["af_adjusted"])

    def test_missing_close_excluded_and_counted(self):
        ds = _dates(3)
        p = _payload(
            [(ds[0], "A", 100), (ds[1], "A", -10), (ds[0], "B", 100)],
            {ds[0]: 100.0, ds[2]: 100.0},
            extra_dates=[ds[2]],
        )
        w = p["windows"]["all"]
        self.assertEqual(w["pairs_skipped_missing_price"], 1)
        self.assertIsNone(_row(p, "A"))
        # B:買 100@100,現價 100 → est 0,達門檻(算 considered)但不在賺/賠清單
        self.assertEqual(w["pairs_considered"], 1)
        self.assertEqual(w["gainers"] + w["losers"], [])

    def test_zero_est_counts_as_considered_not_listed(self):
        ds = _dates(2)
        p = _payload([(ds[0], "B", 100)], {ds[0]: 100.0, ds[1]: 100.0}, extra_dates=[ds[1]])
        w = p["windows"]["all"]
        self.assertEqual(w["pairs_considered"], 1)
        self.assertEqual(w["gainers"], [])
        self.assertEqual(w["losers"], [])

    def test_trades_before_window_ignored(self):
        ds = _dates(62)
        # 窗口 60 = 最後 60 個可見日 → ds[2:];ds[0] 的買進不在 60 日窗口內
        trades = [(ds[0], "A", 100)] + [(d, "_f", 0) for d in ds[1:]] + [(ds[61], "A", -100)]
        closes = {d: 100.0 for d in ds}
        closes[ds[61]] = 150.0
        p = _payload(trades, closes)
        self.assertEqual(p["windows"]["60"]["window_days"], 60)
        self.assertEqual(p["windows"]["60"]["first_date"], ds[2])
        self.assertIsNone(_row(p, "A", "60"))  # 只剩一筆看不見來源的賣出
        self.assertEqual(_row(p, "A", "all")["est_total"], 5_000_000)

    def test_dates_after_as_of_ignored(self):
        ds = _dates(3)
        p = _payload([(ds[0], "A", 100), (ds[2], "A", -100)],
                     {d: 100.0 + i for i, d in enumerate(ds)}, as_of=ds[1], extra_dates=[ds[1]])
        self.assertEqual(p["as_of"], ds[1])
        self.assertEqual(_row(p, "A")["pos_lots"], 100)

    def test_thresholds(self):
        ds = _dates(2)
        closes = {ds[0]: 100.0, ds[1]: 110.0}
        # 49 張 → buy_lots 不足;50 張 @100 = 5,000,000 → 入選
        p = _payload([(ds[0], "LOW", MIN_BUY_LOTS - 1), (ds[0], "OK", MIN_BUY_LOTS)], closes, extra_dates=[ds[1]])
        self.assertIsNone(_row(p, "LOW"))
        self.assertIsNotNone(_row(p, "OK"))
        # 60 張 @10 = 600,000 < 1,000,000 → 不入選
        p = _payload([(ds[0], "CHEAP", 60)], {ds[0]: 10.0, ds[1]: 12.0}, extra_dates=[ds[1]])
        self.assertIsNone(_row(p, "CHEAP"))
        self.assertLess(60 * 10 * 1000, MIN_MAX_COST)

    def test_ordering_disjoint_and_capped(self):
        ds = _dates(2)
        trades, closes = [], {ds[0]: 100.0, ds[1]: 100.0}
        # 20 個賺、20 個賠:用不同買價(同一天只有一個價)→ 改成不同張數、同一價差方向
        for i in range(20):
            trades.append((ds[0], f"G{i:02d}", 100 + i))
            trades.append((ds[1], f"G{i:02d}", -(100 + i)))
        closes[ds[1]] = 110.0
        for i in range(20):
            trades.append((ds[1], f"L{i:02d}", 100 + i))
        closes_l = dict(closes)
        p = _payload(trades, closes_l)
        w = p["windows"]["all"]
        # G 在 ds0 買 @100、ds1 賣 @110 → 賺;L 在 ds1 買 @110,現價 110 → 0
        self.assertEqual(len(w["gainers"]), TOP_N)
        self.assertEqual(w["n_gainers"], 20)
        totals = [r["est_total"] for r in w["gainers"]]
        self.assertEqual(totals, sorted(totals, reverse=True))
        self.assertEqual(w["gainers"][0]["name"], "G19")
        names_g = {r["name"] for r in w["gainers"]}
        names_l = {r["name"] for r in w["losers"]}
        self.assertFalse(names_g & names_l)
        # 相同 est_total → 依名稱
        p2 = _payload([(ds[0], "B", 100), (ds[0], "A", 100)], {ds[0]: 100.0, ds[1]: 90.0}, extra_dates=[ds[1]])
        self.assertEqual([r["name"] for r in p2["windows"]["all"]["losers"]], ["A", "B"])
        self.assertEqual(p2["windows"]["all"]["losers"][0]["est_total"], -1_000_000)
        # 確定性:同輸入同輸出
        self.assertEqual(json.dumps(p, sort_keys=True), json.dumps(_payload(trades, closes_l), sort_keys=True))

    def test_no_rows_returns_none(self):
        self.assertIsNone(branch_pnl_payload([], [("2026-08-01", 100.0, 1.0)], as_of_limit="2026-08-01"))
        self.assertIsNone(branch_pnl_payload([("2026-09-01", "A", 5)], [], as_of_limit="2026-08-01"))


def _trade(stock_id, day, key, name, net):
    return {"stock_id": stock_id, "date": day, "branch_key": key, "branch_name": name,
            "buy_lots": max(net, 0), "sell_lots": max(-net, 0), "net_lots": net, "pct": 0}


class ExportKeyTests(unittest.TestCase):
    DATES = ("2026-08-03", "2026-08-04", "2026-08-05")

    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._old = (config.DB_URL, config.DATA_DIR)
        config.DATA_DIR = tmp
        config.DB_URL = "sqlite:///" + (tmp / "t.db").as_posix()
        db._engine = None
        db.init_db()
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": "2330", "name": "台積電", "market": "twse", "type": "stock", "is_active": 1},
                {"id": "2317", "name": "鴻海", "market": "twse", "type": "stock", "is_active": 1},
            ])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": sid, "date": day, "close": 100.0 + i * 10, "volume": 1_000_000, "turnover": 1}
                for sid in ("2330", "2317") for i, day in enumerate(self.DATES)
            ])
            # 13 個分點同一天 → 裁剪後的 branch_history 只留 12 個;損益要用未裁剪的
            upsert_branch_trades(conn, [
                _trade("2330", self.DATES[0], f"k{i}", f"分點{i:02d}", 100 + i) for i in range(13)
            ] + [_trade("2330", self.DATES[-1], "z", "分點00", -1)])

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old
        self._tmp.cleanup()

    def _export(self):
        out = Path(self._tmp.name) / "out"
        out.mkdir(parents=True, exist_ok=True)
        export_json(out)
        return {sid: read_merged_stock(out / "stocks", sid)
                for sid in ("2330", "2317")}

    def test_key_present_with_untrimmed_rows_and_omitted_without_branches(self):
        p = self._export()
        self.assertNotIn("branch_pnl_est", p["2317"])
        est = p["2330"]["branch_pnl_est"]
        self.assertEqual(est["as_of"], self.DATES[-1])
        w = est["windows"]["all"]
        # 13 個分點都看得到(第 13 小的「分點00」只在裁剪前存在)
        self.assertEqual(w["pairs_considered"], 13)
        self.assertEqual(w["n_gainers"], 13)
        first_day = next(d for d in p["2330"]["branch_history"] if d["t"] == self.DATES[0])
        self.assertNotIn("分點00", {b["n"] for b in first_day["branches"]})
        # 分點00:買 100@100、賣 1@120 → 已實現 20,000;剩 99 張,現價 120 → 未實現 1,980,000
        row = next(r for r in w["gainers"] if r["name"] == "分點00")
        self.assertEqual(row["realized"], 20_000)
        self.assertEqual(row["unrealized"], 1_980_000)


if __name__ == "__main__":
    unittest.main()
