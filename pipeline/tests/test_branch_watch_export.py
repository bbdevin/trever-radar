"""docs/52 自選「特定分點」匯出:branches/watch/{index,sNN}.json。

驗證:當日列/未知列(null 不是 0)、估計仍持有(歸 0 不往負推、進場日)、60 交易日視窗、
同名多來源合併、停業分點排除、權證列不當作今天、門檻與每分點上限、個股摘要、
分片編號、逐位元可重現、沒有分點資料時的空形狀。
"""
import json
import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import radar.config as config
import radar.db as db
from radar import schema
from radar.export import branch_watch
from radar.export.branch_watch import (
    HOLD_MIN_LOTS,
    HOLD_TOP_PER_BRANCH,
    SHARDS,
    WINDOW_TRADING_DAYS,
    BranchWatchCollector,
    shard_of,
)
from radar.export.json_export import export_json
from radar.importer import upsert_branch_trades


def _trading_days(n: int, end: date) -> list[str]:
    out = []
    d = end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return sorted(out)


DAYS = _trading_days(70, date(2026, 10, 16))
AS_OF = DAYS[-1]
WF = DAYS[-WINDOW_TRADING_DAYS]            # 視窗下緣(含)
BEFORE = DAYS[-WINDOW_TRADING_DAYS - 1]    # 視窗外一天


def _row(sid, dt, key, name, buy, sell):
    return {"stock_id": sid, "date": dt, "branch_key": key, "branch_name": name,
            "buy_lots": buy, "sell_lots": sell, "net_lots": buy - sell, "pct": None}


class BranchWatchExportTests(unittest.TestCase):
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
            prices = []
            for i, dt in enumerate(DAYS):
                prices.append({"stock_id": "2330", "date": dt, "close": 1000.0 + i,
                               "volume": 30_000_000, "turnover": 1, "adj_factor": 1.0})
                prices.append({"stock_id": "2317", "date": dt, "close": 200.0,
                               "volume": 10_000_000, "turnover": 1, "adj_factor": 1.0})
                prices.append({"stock_id": "2454", "date": dt, "close": 1200.0,
                               "volume": 2_000_000, "turnover": 1, "adj_factor": 1.0})
            # 2317 今天除息:原始收盤 190、前一天還原後 190 → 漲跌 0,不是 −5%。
            prices[-2]["close"] = 190.0
            prices[-5]["adj_factor"] = 0.95
            conn.execute(schema.daily_prices.insert(), prices)
            upsert_branch_trades(conn, [
                # 富邦-新店:2330 視窗外買 999(不算)、視窗內買 300、賣 500(歸 0)、再買 200、今天買 100
                _row("2330", BEFORE, "a1", "富邦-新店", 999, 0),
                _row("2330", WF, "a1", "富邦-新店", 300, 0),
                _row("2330", DAYS[-30], "a1", "富邦-新店", 0, 500),
                _row("2330", DAYS[-10], "a1", "富邦-新店", 200, 0),
                _row("2330", AS_OF, "a1", "富邦-新店", 150, 50),
                # 同名另一個來源頁:今天再 +20(同日合併)
                _row("2330", AS_OF, "a2", "富邦-新店", 20, 0),
                # 2317:今天賣超
                _row("2317", DAYS[-3], "a1", "富邦-新店", 400, 0),
                _row("2317", AS_OF, "a1", "富邦-新店", 0, 100),
                # 2454:今天沒出現、估計仍持有 500 → 以 null 當日欄位輸出
                _row("2454", DAYS[-20], "a1", "富邦-新店", 500, 0),
                # 元大-松江:2454 今天沒出現、仍持有 50 < 門檻 → 不輸出列,但名稱進 index
                _row("2454", DAYS[-15], "c1", "元大-松江", 50, 0),
                # 停業分點不輸出
                _row("2330", AS_OF, "z1", "元大-西門(停)", 10, 0),
            ])

    def _export(self, name="out"):
        out = Path(self._tmp.name) / name
        export_json(out)
        return out / "branches" / "watch"

    def _shard_of(self, wdir, name):
        idx = json.loads((wdir / "index.json").read_text(encoding="utf-8"))
        entry = next(b for b in idx["branches"] if b[0] == name)
        return idx, entry, json.loads((wdir / f"s{entry[1]:02d}.json").read_text(encoding="utf-8"))

    def test_rows_holding_and_unknowns(self):
        wdir = self._export()
        idx, entry, shard = self._shard_of(wdir, "富邦-新店")
        self.assertEqual(idx["as_of"], AS_OF)  # 不是權證那一天
        self.assertEqual(idx["window_from"], WF)
        self.assertEqual(idx["window_days"], WINDOW_TRADING_DAYS)
        self.assertEqual(idx["shards"], SHARDS)
        self.assertEqual(entry, ["富邦-新店", shard_of("富邦-新店"), 1, 1, 1])
        rows = {r[0]: r for r in shard["branches"]["富邦-新店"]}
        self.assertEqual(sorted(rows), ["2317", "2330", "2454"])
        # 2330:300 → 賣 500 歸 0 → 200 → +120(兩來源合併)= 320;進場日 = 歸 0 後再轉正那天
        self.assertEqual(rows["2330"], ["2330", 170, 50, 120, 320, DAYS[-10], 4, 120, AS_OF])
        # 2317:400 − 100 = 300,今天淨賣
        self.assertEqual(rows["2317"], ["2317", 0, 100, -100, 300, DAYS[-3], 2, 300, AS_OF])
        # 2454:今天不在前 15 大 → 當日三欄 null(未知,不是 0)
        self.assertEqual(rows["2454"], ["2454", None, None, None, 500, DAYS[-20], 1, 500, DAYS[-20]])
        # 個股摘要:收盤、還原漲跌、20 日均量張
        self.assertEqual(shard["stocks"]["2330"], ["台積電", 1069.0, round(1 / 1068 * 100, 2), 30000])
        self.assertEqual(shard["stocks"]["2317"], ["鴻海", 190.0, 0.0, 10000])

    def test_warrant_rows_do_not_define_today(self):
        # 權證分點先到、現股分點還沒到的那段時間:今天仍是最後一個有現股列的日子。
        from sqlalchemy import text
        with db.get_engine().begin() as conn:
            conn.execute(text("DELETE FROM branch_trades_raw WHERE date = :d"), {"d": AS_OF})
            upsert_branch_trades(conn, [_row("030001", AS_OF, "a1", "富邦-新店", 10, 0)])
            self.assertEqual(branch_watch.latest_stock_branch_date(conn, AS_OF), DAYS[-3])
        wdir = self._export()
        idx = json.loads((wdir / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(idx["as_of"], DAYS[-3])

    def test_threshold_closed_and_index(self):
        wdir = self._export()
        idx, entry, shard = self._shard_of(wdir, "元大-松江")
        self.assertEqual(entry[2:], [0, 0, 0])
        self.assertNotIn("元大-松江", shard["branches"])
        names = [b[0] for b in idx["branches"]]
        self.assertEqual(names, sorted(names))
        self.assertNotIn("元大-西門(停)", names)
        self.assertEqual(idx["hold_min"], HOLD_MIN_LOTS)
        files = sorted(p.name for p in wdir.glob("*.json"))
        self.assertEqual(len(files), SHARDS + 1)

    def test_byte_stable(self):
        a = self._export("a")
        b = self._export("b")
        for p in sorted(a.glob("*.json")):
            self.assertEqual(p.read_bytes(), (b / p.name).read_bytes(), p.name)

    def test_stale_files_removed(self):
        wdir = self._export()
        (wdir / "s99.json").write_text("{}", encoding="utf-8")
        self._export()
        self.assertFalse((wdir / "s99.json").exists())


class BranchWatchEmptyTests(unittest.TestCase):
    def test_no_branch_data_shape(self):
        col = BranchWatchCollector(None, None)
        col.add_stock("2330", "台積電", [(AS_OF, "富邦-新店", 1, 0, 1)], [])
        index, shards = col.payloads()
        self.assertEqual(index["as_of"], None)
        self.assertEqual(index["window_from"], None)
        self.assertEqual(index["branches"], [])
        self.assertEqual(len(shards), SHARDS)
        self.assertTrue(all(s["branches"] == {} and s["stocks"] == {} for s in shards))


class BranchWatchCapTests(unittest.TestCase):
    def test_hold_top_cap_keeps_today_rows(self):
        col = BranchWatchCollector(AS_OF, WF)
        candles = [(AS_OF, 1, 1, 1, 10.0, 1000, 1, 1.0)]
        for i in range(HOLD_TOP_PER_BRANCH + 5):
            sid = f"{1000 + i}"
            col.add_stock(sid, sid, [(DAYS[-5], "B", HOLD_MIN_LOTS + i, 0, HOLD_MIN_LOTS + i)], candles)
        col.add_stock("9999", "x", [(AS_OF, "B", 0, 5, -5)], candles)
        index, shards = col.payloads()
        rows = shards[shard_of("B")]["branches"]["B"]
        held = [r for r in rows if r[3] is None]
        self.assertEqual(len(held), HOLD_TOP_PER_BRANCH)
        # 留下的是估計仍持有最大的那些
        self.assertEqual(min(r[4] for r in held), HOLD_MIN_LOTS + 5)
        self.assertIn("9999", [r[0] for r in rows])
        self.assertEqual(index["branches"], [["B", shard_of("B"), 0, 1, HOLD_TOP_PER_BRANCH]])
        self.assertEqual([r[0] for r in rows], sorted(r[0] for r in rows))


if __name__ == "__main__":
    unittest.main()
