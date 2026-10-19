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
        self.assertEqual(entry, ["富邦-新店", shard_of("富邦-新店"), 1, 1, 1, 1])
        # 沒有匯入紀錄(測試庫)→ 不宣稱待補:complete,2454 今天沒列 = 無分點資料
        self.assertEqual(idx["coverage"], {"covered": 2, "expected": 3, "complete": True})
        rows = {r[0]: r for r in shard["branches"]["富邦-新店"]}
        self.assertEqual(sorted(rows), ["2317", "2330", "2454"])
        # 2330:300 → 賣 500 歸 0 → 200 → +120(兩來源合併)= 320;進場日 = 歸 0 後再轉正那天
        # 均價(估,第 10 欄):歸 0 後重算 = (200 × 1060 + 120 × 1069) / 320 = 1063.375
        self.assertEqual(rows["2330"], ["2330", 170, 50, 120, 320, DAYS[-10], 4, 120, AS_OF, 1063.38])
        # 2317:400 − 100 = 300,今天淨賣;賣超不改均價
        self.assertEqual(rows["2317"], ["2317", 0, 100, -100, 300, DAYS[-3], 2, 300, AS_OF, 200.0])
        # 2454:今天不在前 15 大 → 當日三欄 null(未知,不是 0)
        self.assertEqual(rows["2454"], ["2454", None, None, None, 500, DAYS[-20], 1, 500, DAYS[-20], 1200.0])
        # 沒有權證分點資料 → warrant null、分片 warrants 空
        self.assertIsNone(idx["warrant"])
        self.assertEqual(shard["warrants"], {})
        # 個股摘要:收盤、還原漲跌、20 日均量張
        self.assertEqual(shard["stocks"]["2330"], ["台積電", 1069.0, round(1 / 1068 * 100, 2), 30000, 1])
        self.assertEqual(shard["stocks"]["2317"], ["鴻海", 190.0, 0.0, 10000, 1])
        self.assertEqual(shard["stocks"]["2454"], ["聯發科", 1200.0, 0.0, 2000, branch_watch.TODAY_NO_DATA])

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
        self.assertEqual(entry[2:], [0, 0, 0, 0])
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


class BranchWatchWarrantExportTests(unittest.TestCase):
    """docs/52 §8:權證欄搭 _WarrantWindowScan 的逐日序列,不另掃;日期另帶、舊的不算今天。"""

    # 同一個種子庫(不繼承,免得把上面的測試再跑一次)
    setUp = BranchWatchExportTests.setUp
    tearDown = BranchWatchExportTests.tearDown
    _seed = BranchWatchExportTests._seed
    _export = BranchWatchExportTests._export

    def _seed_warrants(self, rows, days=None):
        days = days or DAYS[-5:]
        with db.get_engine().begin() as conn:
            conn.execute(schema.warrants.insert(), [
                {"id": "030001", "name": "台積電元大5C購01", "market": "twse", "kind": "call", "stock_id": "2330"},
                {"id": "030002", "name": "台積電凱基5C售01", "market": "twse", "kind": "put", "stock_id": "2330"},
                {"id": "030003", "name": "台積電統一5C牛01", "market": "twse", "kind": "bull", "stock_id": "2330"},
            ])
            conn.execute(schema.warrant_daily.insert(), [
                {"warrant_id": w, "date": dt, "close": 1.0, "volume": 1, "turnover": 2_000_000 if w == "030001" else 1000}
                for w in ("030001", "030002", "030003") for dt in days
            ])
            upsert_branch_trades(conn, rows)

    def _watch(self):
        wdir = self._export()
        idx = json.loads((wdir / "index.json").read_text(encoding="utf-8"))
        shards = {i: json.loads((wdir / f"s{i:02d}.json").read_text(encoding="utf-8")) for i in range(SHARDS)}
        warrants = {b: {r[0]: r for r in rows} for s in shards.values() for b, rows in s["warrants"].items()}
        return idx, shards, warrants

    def test_call_put_today_threshold_and_same_name(self):
        self._seed_warrants([
            # 富邦-新店:認購 +600 萬(收盤 1.0 × 1000 元/張 × 6000 張)、牛證 +900 萬(不算)
            _row("030001", AS_OF, "a1", "富邦-新店", 6000, 0),
            _row("030003", AS_OF, "a1", "富邦-新店", 9000, 0),
            # 永豐金-內湖(兩個來源頁,各 60 萬 < 門檻,同名合併 120 萬 ≥ 門檻);只買權證、沒有現股列
            _row("030001", AS_OF, "b1", "永豐金-內湖", 600, 0),
            _row("030001", AS_OF, "b2", "永豐金-內湖", 600, 0),
            # 元大-松江:認售 +300 萬、認購 −150 萬(上游配對門檻看「全部權證合計」,合計 150 萬才入選)
            _row("030002", AS_OF, "c1", "元大-松江", 3000, 0),
            _row("030001", AS_OF, "c1", "元大-松江", 0, 1500),
            # 凱基-台北:認購 +50 萬 < 門檻 → 不列
            _row("030001", AS_OF, "k1", "凱基-台北", 500, 0),
            # 停業分點不列
            _row("030001", AS_OF, "z1", "元大-西門(停)", 5000, 0),
        ])
        idx, shards, w = self._watch()
        self.assertEqual(idx["warrant"], {"data_date": AS_OF, "day": AS_OF, "counted": True, "complete": True,
                                          "min_amount": branch_watch.WARRANT_MIN_AMOUNT,
                                          "pool_turnover_min": branch_watch.NIGHTLY_WARRANT_TURNOVER_MIN})
        # 個股摘要第 6 欄:2330 當天有成交 ≥ 100 萬的認購 → 在夜間權證池(1);2317 沒有權證 → 0(權證:未收集)
        s0 = shards[names_of(idx)["富邦-新店"][1]]
        self.assertEqual(s0["stocks"]["2330"][5], 1)
        self.assertEqual(s0["stocks"]["2317"][5], 0)
        fb = w["富邦-新店"]["2330"]
        self.assertEqual(fb[1:3], [6_000_000, None])
        # 認購仍持有成本 600 萬 ≥ docs/51 篩選門檻 → 帶持有估算
        self.assertEqual(fb[3], 6_000_000)
        self.assertEqual(w["永豐金-內湖"]["2330"][1:3], [1_200_000, None])
        self.assertEqual(w["元大-松江"]["2330"][1:3], [-1_500_000, 3_000_000])
        self.assertNotIn("凱基-台北", w)
        self.assertNotIn("元大-西門(停)", w)
        # 只有權證的分點也進 index(才找得到分片),標的摘要也在那片
        names = {b[0]: b for b in idx["branches"]}
        self.assertIn("永豐金-內湖", names)
        s = shards[names["永豐金-內湖"][1]]
        self.assertEqual(s["stocks"]["2330"][0], "台積電")

    def test_stale_warrant_date_not_counted(self):
        # 權證分點只到前一天(權證晚一步匯入):列出那天的,counted=False
        self._seed_warrants([_row("030001", DAYS[-2], "a1", "富邦-新店", 3200, 0)], days=DAYS[-5:-1])
        idx, _shards, w = self._watch()
        self.assertEqual(idx["as_of"], AS_OF)
        self.assertEqual(idx["warrant"]["data_date"], DAYS[-2])
        self.assertEqual(idx["warrant"]["day"], DAYS[-2])
        self.assertFalse(idx["warrant"]["counted"])
        self.assertEqual(w["富邦-新店"]["2330"][1], 3_200_000)

    def test_warrant_ahead_of_stock_uses_stock_day(self):
        # 權證分點比現股新:取現股那一天的權證,不拿明天的權證當今天
        from sqlalchemy import text
        with db.get_engine().begin() as conn:
            conn.execute(text("DELETE FROM branch_trades_raw WHERE date = :d"), {"d": AS_OF})
        self._seed_warrants([
            _row("030001", DAYS[-3], "a1", "富邦-新店", 2000, 0),
            _row("030001", AS_OF, "a1", "富邦-新店", 0, 9000),
        ])
        idx, _shards, w = self._watch()
        self.assertEqual(idx["as_of"], DAYS[-3])
        self.assertEqual(idx["warrant"], {"data_date": AS_OF, "day": DAYS[-3], "counted": True, "complete": True,
                                          "min_amount": branch_watch.WARRANT_MIN_AMOUNT,
                                          "pool_turnover_min": branch_watch.NIGHTLY_WARRANT_TURNOVER_MIN})
        self.assertEqual(w["富邦-新店"]["2330"][1], 2_000_000)


    def test_incomplete_warrant_pool_not_counted(self):
        # 權證那一段最後一輪 incomplete(有權證抓失敗)→ 列出但不算今天;之後一輪 ok → 算
        self._seed_warrants([_row("030001", AS_OF, "a1", "富邦-新店", 3200, 0)])
        with db.get_engine().begin() as conn:
            conn.execute(schema.import_logs.insert(), [
                {"run_at": "2026-10-16T19:48:00+08:00", "source": "fubon", "dataset": "branch_warrant_pool",
                 "date": AS_OF, "rows": 10, "status": "incomplete", "error": "targets=3 done=2 empty=0 failed=1"}])
        idx, _shards, w = self._watch()
        self.assertEqual((idx["warrant"]["counted"], idx["warrant"]["complete"]), (False, False))
        self.assertEqual(w["富邦-新店"]["2330"][1], 3_200_000)
        with db.get_engine().begin() as conn:
            conn.execute(schema.import_logs.insert(), [
                {"run_at": "2026-10-16T22:44:00+08:00", "source": "fubon", "dataset": "branch_warrant_pool",
                 "date": AS_OF, "rows": 10, "status": "ok", "error": "targets=3 done=3 empty=0 failed=0"}])
        idx, _shards, _w = self._watch()
        self.assertEqual((idx["warrant"]["counted"], idx["warrant"]["complete"]), (True, True))


def names_of(idx):
    return {b[0]: b for b in idx["branches"]}


    def test_incomplete_warrant_pool_not_counted(self):
        # 權證那一段最後一輪 incomplete(有權證抓失敗)→ 列出但不算今天;之後一輪 ok → 算
        self._seed_warrants([_row("030001", AS_OF, "a1", "富邦-新店", 3200, 0)])
        with db.get_engine().begin() as conn:
            conn.execute(schema.import_logs.insert(), [
                {"run_at": "2026-10-16T19:48:00+08:00", "source": "fubon", "dataset": "branch_warrant_pool",
                 "date": AS_OF, "rows": 10, "status": "incomplete", "error": "targets=3 done=2 empty=0 failed=1"}])
        idx, _shards, w = self._watch()
        self.assertEqual((idx["warrant"]["counted"], idx["warrant"]["complete"]), (False, False))
        self.assertEqual(w["富邦-新店"]["2330"][1], 3_200_000)
        with db.get_engine().begin() as conn:
            conn.execute(schema.import_logs.insert(), [
                {"run_at": "2026-10-16T22:44:00+08:00", "source": "fubon", "dataset": "branch_warrant_pool",
                 "date": AS_OF, "rows": 10, "status": "ok", "error": "targets=3 done=3 empty=0 failed=0"}])
        idx, _shards, _w = self._watch()
        self.assertEqual((idx["warrant"]["counted"], idx["warrant"]["complete"]), (True, True))


def names_of(idx):
    return {b[0]: b for b in idx["branches"]}


class BranchWatchWarrantUnitTests(unittest.TestCase):
    def test_add_warrants_picks_day_and_threshold(self):
        col = BranchWatchCollector(AS_OF, WF)
        candles = [(AS_OF, 1, 1, 1, 10.0, 1000, 1, 1.0)]
        col.add_stock("2330", "台積電", [(AS_OF, "A", 10, 0, 10)], candles)
        daily = {
            ("2330", "A"): [[DAYS[-3], 5_000_000, 0], [AS_OF, 999_999, -1_000_000]],
            ("2330", "B"): [[DAYS[-3], 5_000_000, 0]],          # 今天沒列 → 不列(未知,不是 0)
        }
        held = [("A", "2330", "put", 10, 7_000_000) + (None,) * 20]
        col.add_warrants(AS_OF, daily, held)
        _index, shards = col.payloads()
        rows = shards[shard_of("A")]["warrants"]["A"]
        # 認購 999,999 < 門檻 → null;認售 −100 萬 = 門檻 → 列;認售持有成本帶上
        self.assertEqual(rows, [["2330", None, -1_000_000, None, None, 7_000_000, None]])
        self.assertNotIn("B", shards[shard_of("B")]["warrants"])

    def test_avg_cost_unknown_when_a_buy_day_has_no_close(self):
        col = BranchWatchCollector(AS_OF, WF)
        candles = [(AS_OF, 1, 1, 1, 10.0, 1000, 1, 1.0)]   # DAYS[-5] 沒有收盤
        col.add_stock("9999", "x", [(AS_OF, "B", 10, 0, 10), (DAYS[-5], "B", 200, 0, 200)], candles)
        _index, shards = col.payloads()
        self.assertIsNone(shards[shard_of("B")]["branches"]["B"][0][9])

    def test_avg_cost_restarts_after_flat(self):
        col = BranchWatchCollector(AS_OF, WF)
        candles = [(DAYS[-3], 1, 1, 1, 10.0, 1000, 1, 1.0), (DAYS[-2], 1, 1, 1, 20.0, 1000, 1, 1.0),
                   (AS_OF, 1, 1, 1, 30.0, 1000, 1, 1.0)]
        col.add_stock("9999", "x", [(AS_OF, "B", 100, 0, 100), (DAYS[-2], "B", 0, 300, -300),
                                    (DAYS[-3], "B", 200, 0, 200)], candles)
        _index, shards = col.payloads()
        row = shards[shard_of("B")]["branches"]["B"][0]
        self.assertEqual((row[4], row[9]), (100, 30.0))


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
        self.assertEqual(index["branches"], [["B", shard_of("B"), 0, 1, HOLD_TOP_PER_BRANCH, HOLD_TOP_PER_BRANCH + 5]])
        self.assertEqual([r[0] for r in rows], sorted(r[0] for r in rows))


class BranchWatchThresholdTests(unittest.TestCase):
    """當日沒出現的列:≥ 100 張,或 ≥ 20 日均量且 ≥ 20 張(小型股的相對大部位)。"""

    def _rows_for(self, hold, avg_lots):
        col = BranchWatchCollector(AS_OF, WF)
        candles = [(AS_OF, 1, 1, 1, 10.0, avg_lots * 1000, 1, 1.0)]
        col.add_stock("9999", "x", [(DAYS[-5], "B", hold, 0, hold)], candles)
        _index, shards = col.payloads()
        return shards[shard_of("B")]["branches"].get("B", [])

    def test_small_cap_relative_holding_listed(self):
        self.assertEqual(len(self._rows_for(80, 30)), 1)
        self.assertEqual(len(self._rows_for(50, 60)), 0)     # 未達均量、也未達 100
        self.assertEqual(len(self._rows_for(15, 10)), 0)     # 達均量但低於 20 張地板
        self.assertEqual(len(self._rows_for(100, 5000)), 1)  # 100 張絕對門檻

    def test_coverage_uses_pool_and_complete_flag(self):
        candles = [(AS_OF, 1, 1, 1, 10.0, 1000, 1, 1.0)]
        for complete, pending_state in ((False, branch_watch.TODAY_PENDING), (True, branch_watch.TODAY_NO_DATA)):
            col = BranchWatchCollector(AS_OF, WF, pool={"1", "2", "3"}, complete=complete)
            col.add_stock("1", "a", [(AS_OF, "B", 1, 0, 1)], candles)          # 池內、今天有列
            col.add_stock("2", "b", [(DAYS[-3], "B", 500, 0, 500)], candles)   # 池內、今天沒列
            col.add_stock("3", "c", [], candles)                               # 池內、完全沒分點列
            col.add_stock("0050", "ETF", [(DAYS[-3], "B", 500, 0, 500)], candles)  # 不在池(ETF)
            index, shards = col.payloads()
            self.assertEqual(index["coverage"], {"covered": 1, "expected": 3, "complete": complete})
            stocks = shards[shard_of("B")]["stocks"]
            self.assertEqual(stocks["1"][4], branch_watch.TODAY_HAS_ROWS)
            self.assertEqual(stocks["2"][4], pending_state)
            # ETF 永遠不是「尚未匯入」:匯入端從不抓 ETF
            self.assertEqual(stocks["0050"][4], branch_watch.TODAY_NO_DATA)


class BranchWatchImportStatusTests(unittest.TestCase):
    """完成與否照匯入端的 import_logs(_finish_branch_import 一輪寫 branch＋branch_coverage 兩列)。"""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._old_url, self._old_dir = config.DB_URL, config.DATA_DIR
        config.DATA_DIR = tmp
        config.DB_URL = "sqlite:///" + (tmp / "t.db").as_posix()
        db._engine = None
        db.init_db()
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": "2330", "name": "台積電", "market": "twse", "type": "stock", "is_active": 1},
                {"id": "2454", "name": "聯發科", "market": "twse", "type": "stock", "is_active": 1},
                {"id": "0050", "name": "元大台灣50", "market": "twse", "type": "etf", "is_active": 1},
            ])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": sid, "date": dt, "close": 100.0, "volume": 1_000_000, "turnover": 1, "adj_factor": 1.0}
                for sid in ("2330", "2454", "0050") for dt in DAYS[-25:]
            ])
            upsert_branch_trades(conn, [
                _row("2330", AS_OF, "a1", "富邦-新店", 100, 0),
                # 2454:池內,今天沒列(確認空或尚未匯入,由匯入紀錄決定)
                _row("2454", DAYS[-5], "a1", "富邦-新店", 300, 0),
                # 0050:ETF,窗口內有舊列、今天沒列;匯入端不抓 ETF
                _row("0050", DAYS[-5], "a1", "富邦-新店", 300, 0),
            ])

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old_url, self._old_dir
        self._tmp.cleanup()

    def _log_round(self, status, expected, run_at="2026-10-16T21:20:05+08:00", cov_run_at=None):
        with db.get_engine().begin() as conn:
            conn.execute(schema.import_logs.insert(), [
                {"run_at": run_at, "source": "fubon", "dataset": "branch", "date": AS_OF,
                 "rows": 30, "status": status, "error": None},
                {"run_at": cov_run_at or run_at, "source": "fubon", "dataset": "branch_coverage",
                 "date": AS_OF, "rows": 1, "status": "ok",
                 "error": f"expected={expected} ratio=0.5000 done=1 empty=1"},
            ])

    def _export(self):
        out = Path(self._tmp.name) / "out"
        export_json(out)
        wdir = out / "branches" / "watch"
        idx = json.loads((wdir / "index.json").read_text(encoding="utf-8"))
        entry = next(b for b in idx["branches"] if b[0] == "富邦-新店")
        shard = json.loads((wdir / f"s{entry[1]:02d}.json").read_text(encoding="utf-8"))
        return idx, shard

    def test_full_import_with_etf_and_confirmed_empty_has_no_banner(self):
        # 整池那一輪 status=ok(每個目標都有答案)→ 完成:分母不含 ETF,2454 是確認空,不是待補
        self._log_round("ok", 2, cov_run_at="2026-10-16T21:20:06+08:00")
        idx, shard = self._export()
        self.assertEqual(idx["coverage"], {"covered": 1, "expected": 2, "complete": True})
        self.assertEqual(shard["stocks"]["2454"][4], branch_watch.TODAY_NO_DATA)
        self.assertEqual(shard["stocks"]["0050"][4], branch_watch.TODAY_NO_DATA)
        self.assertEqual(shard["stocks"]["2330"][4], branch_watch.TODAY_HAS_ROWS)

    def test_partial_import_marks_pool_stocks_pending(self):
        self._log_round("incomplete", 2)
        idx, shard = self._export()
        self.assertEqual(idx["coverage"], {"covered": 1, "expected": 2, "complete": False})
        self.assertEqual(shard["stocks"]["2454"][4], branch_watch.TODAY_PENDING)
        # ETF 不在匯入池:匯入未完成也不是「尚未匯入」
        self.assertEqual(shard["stocks"]["0050"][4], branch_watch.TODAY_NO_DATA)

    def test_ok_round_that_did_not_target_whole_pool_is_not_complete(self):
        self._log_round("ok", 1)   # --top/--ids 那種局部輪
        idx, _ = self._export()
        self.assertFalse(idx["coverage"]["complete"])

    def test_import_complete_reads_logs(self):
        with db.get_engine().connect() as conn:
            self.assertIsNone(branch_watch.import_complete(conn, AS_OF, 2))
        self._log_round("error", 2)
        with db.get_engine().connect() as conn:
            self.assertFalse(branch_watch.import_complete(conn, AS_OF, 2))
        self._log_round("ok", 2, run_at="2026-10-16T22:44:00+08:00")
        with db.get_engine().connect() as conn:
            self.assertTrue(branch_watch.import_complete(conn, AS_OF, 2))

    def test_naive_run_at_mixed_with_aware_does_not_crash(self):
        """一列沒帶時區的 run_at 不可讓整個 export 掛掉(verifier 2026-10-19);naive 當台北時間。"""
        self._log_round("error", 2, run_at="2026-10-16T19:00:00+08:00")
        self._log_round("ok", 2, run_at="2026-10-16T21:20:05", cov_run_at="2026-10-16T21:20:06+08:00")
        with db.get_engine().connect() as conn:
            self.assertTrue(branch_watch.import_complete(conn, AS_OF, 2))


if __name__ == "__main__":
    unittest.main()
