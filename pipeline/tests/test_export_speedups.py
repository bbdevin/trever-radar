"""export-json 提速(2026-10-15,docs/44 §3.5)的等價鎖:每個新路徑都與它取代的舊查詢/舊程式逐列相同。

* 權證分點窗口:一次掃描(_WarrantWindowScan)↔ 舊的三條查詢(區間彙總、逐日序列、持有估算)。
* 個股 active_warrants:預讀 + Python 排序(同額才退回單檔查詢)↔ 舊的單檔查詢。
* 個股分點日史:不 JOIN branch_dim 的主鍵範圍 ↔ 舊的 JOIN 查詢。
* 區間損益:新 branch_pnl_payload ↔ 舊實作(原文抄在下面)在隨機輸入上逐位元相同。
* write_atomic_if_changed:內容相同不重寫、不同就寫。

整份匯出的逐位元比對另由 pipeline/tools/export_parity.py 在合成庫上做(結果記在 docs/44 §3.5)。
"""
from __future__ import annotations

import json
import os
import random
import sqlite3
import unittest
from bisect import bisect_left
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import create_engine, text

from radar.compute import branch_interval_pnl as pnl
from radar.export import json_export as je
from radar.export.stock_parts import write_atomic_if_changed
from tools.make_synthetic_branch_db import build

# ---- 舊程式原文(2026-10-14 main,1a59c60)----------------------------------------------

OLD_Q1 = """
    SELECT b.branch_name, w.stock_id AS underlying_id, s.name AS underlying_name,
        b.stock_id AS warrant_id, w.name AS warrant_name, w.kind,
        SUM(CASE WHEN b.date >= :d1 THEN b.net_lots ELSE 0 END),
        SUM(CASE WHEN b.date >= :d1 THEN b.net_lots * CAST(ROUND(COALESCE(wd.close, 1.0) * 1000) AS INTEGER) ELSE 0 END),
        SUM(CASE WHEN b.date >= :d2 THEN b.net_lots ELSE 0 END),
        SUM(CASE WHEN b.date >= :d2 THEN b.net_lots * CAST(ROUND(COALESCE(wd.close, 1.0) * 1000) AS INTEGER) ELSE 0 END),
        SUM(CASE WHEN b.date >= :d5 THEN b.net_lots ELSE 0 END),
        SUM(CASE WHEN b.date >= :d5 THEN b.net_lots * CAST(ROUND(COALESCE(wd.close, 1.0) * 1000) AS INTEGER) ELSE 0 END),
        SUM(CASE WHEN b.date >= :d30 THEN b.net_lots ELSE 0 END),
        SUM(CASE WHEN b.date >= :d30 THEN b.net_lots * CAST(ROUND(COALESCE(wd.close, 1.0) * 1000) AS INTEGER) ELSE 0 END),
        SUM(CASE WHEN b.date >= :d120 THEN b.net_lots ELSE 0 END),
        SUM(CASE WHEN b.date >= :d120 THEN b.net_lots * CAST(ROUND(COALESCE(wd.close, 1.0) * 1000) AS INTEGER) ELSE 0 END)
    FROM branch_trades b
    JOIN warrants w ON w.id = b.stock_id
    JOIN stocks s ON s.id = w.stock_id
    LEFT JOIN warrant_daily wd ON wd.warrant_id = b.stock_id AND wd.date = b.date
    WHERE LENGTH(b.stock_id) = 6 AND b.date >= :d120 AND b.date <= :d1
      AND s.type = 'stock' AND s.name NOT LIKE '%指%'
    GROUP BY b.branch_name, w.stock_id, s.name, b.stock_id, w.name, w.kind
"""
OLD_DAILY = """
    SELECT b.branch_name, w.stock_id AS underlying_id, b.date,
           SUM(CASE WHEN w.kind = 'call'
                    THEN b.net_lots * CAST(ROUND(COALESCE(wd.close, 1.0) * 1000) AS INTEGER) ELSE 0 END) AS call_amt,
           SUM(CASE WHEN w.kind = 'put'
                    THEN b.net_lots * CAST(ROUND(COALESCE(wd.close, 1.0) * 1000) AS INTEGER) ELSE 0 END) AS put_amt
    FROM branch_trades b
    JOIN warrants w ON w.id = b.stock_id
    JOIN stocks s ON s.id = w.stock_id
    LEFT JOIN warrant_daily wd ON wd.warrant_id = b.stock_id AND wd.date = b.date
    WHERE LENGTH(b.stock_id) = 6 AND b.date >= :d120 AND b.date <= :d1
      AND s.type = 'stock' AND s.name NOT LIKE '%指%'
    GROUP BY b.branch_name, w.stock_id, b.date
    ORDER BY b.date
"""
OLD_POSITIONS = """
    SELECT w.stock_id, b.branch_name, b.stock_id, b.date, SUM(b.net_lots), MAX(wd.close)
    FROM branch_trades b
    JOIN warrants w ON w.id = b.stock_id
    JOIN stocks s ON s.id = w.stock_id
    LEFT JOIN warrant_daily wd ON wd.warrant_id = b.stock_id AND wd.date = b.date
    WHERE LENGTH(b.stock_id) = 6 AND b.date >= ? AND b.date <= ?
      AND s.type = 'stock' AND s.name NOT LIKE '%指%' AND w.kind IN ('call', 'put')
    GROUP BY w.stock_id, b.branch_name, b.stock_id, b.date
    ORDER BY 1, 2, 3, 4
"""
OLD_HISTORY = """
    SELECT r.date, d.branch_name, r.buy_lots, r.sell_lots, r.net_lots
    FROM branch_trades_raw r
    JOIN branch_dim d ON r.branch_id = d.id
    WHERE r.stock_id = :s AND r.date >= date(:d, '-730 days')
    ORDER BY r.date DESC, r.branch_id DESC
"""


def _old_simulate_pair(trades, p_last):
    pos = avg = realized = 0.0
    buy = sold_attr = sold_unattr = max_cost = 0.0
    buy_cost = proceeds = 0.0
    for net, price in trades:
        if net > 0:
            avg = (pos * avg + net * price) / (pos + net)
            pos += net
            buy += net
            buy_cost += net * price * 1000
        elif net < 0:
            sold = min(-net, pos)
            realized += sold * (price - avg) * 1000
            proceeds += sold * price * 1000
            pos -= sold
            sold_attr += sold
            sold_unattr += -net - sold
            if pos == 0:
                avg = 0.0
        max_cost = max(max_cost, pos * avg * 1000)
    unrealized = pos * (p_last - avg) * 1000
    return pnl.PairResult(realized=realized, unrealized=unrealized, pos_lots=pos, avg_cost=avg,
                          buy_lots=buy, sell_lots_attributed=sold_attr, sell_lots_unattributed=sold_unattr,
                          max_cost=max_cost, buy_cost=buy_cost, sell_proceeds=proceeds)


def _old_pnl_payload(branch_rows, candles, *, as_of_limit):
    by_branch, date_set = {}, set()
    for row in branch_rows:
        d, name, net = row[0], row[1], row[2]
        if d > as_of_limit or not name:
            continue
        date_set.add(d)
        per = by_branch.setdefault(name, {})
        per[d] = per.get(d, 0) + (net or 0)
    if not date_set:
        return None
    dates = sorted(date_set)
    as_of = dates[-1]
    prices = {}
    for c in candles:
        if c[1] is None:
            continue
        prices[c[0]] = (float(c[1]), float(c[2] or 1.0))
    last_dates = [d for d in prices if d <= as_of]
    last_close, af_last = prices[max(last_dates)] if last_dates else (None, None)
    branches = {}
    for name in sorted(by_branch):
        days = sorted(by_branch[name].items())
        px, moved = [], []
        for d, _ in days:
            hit = prices.get(d)
            if hit is None or af_last is None:
                px.append(None)
                moved.append(False)
            else:
                px.append(hit[0] * hit[1] / af_last)
                moved.append(abs(hit[1] - af_last) > 1e-9)
        branches[name] = ([d for d, _ in days], [n for _, n in days], px, moved)

    def window(days):
        win_dates = dates if days is None else dates[-days:]
        first = win_dates[0]
        considered, skipped = [], 0
        for name, (bd, nets, prs, mv) in branches.items():
            i0 = bisect_left(bd, first)
            if i0 >= len(bd):
                continue
            idx = [i for i in range(i0, len(bd)) if nets[i] != 0]
            if not idx:
                continue
            if last_close is None or any(prs[i] is None for i in idx):
                skipped += 1
                continue
            res = _old_simulate_pair([(nets[i], prs[i]) for i in idx], last_close)
            if res.buy_lots < pnl.MIN_BUY_LOTS or res.max_cost < pnl.MIN_MAX_COST:
                continue
            est = res.est_total
            considered.append({
                "name": name, "est_total": round(est), "realized": round(res.realized),
                "unrealized": round(res.unrealized), "pos_lots": round(res.pos_lots),
                "avg_cost": round(res.avg_cost, 2), "last_close": round(last_close, 2),
                "buy_lots": round(res.buy_lots), "sell_lots_attributed": round(res.sell_lots_attributed),
                "sell_lots_unattributed": round(res.sell_lots_unattributed),
                "visible_days": len(bd) - i0, "max_cost": round(res.max_cost),
                "ret_pct": round(est / res.max_cost * 100, 2) if res.max_cost else None,
                "af_adjusted": any(mv[i] for i in idx), "first_date": bd[i0], "last_date": bd[-1],
                "_est": est,
            })
        gain = sorted((r for r in considered if r["_est"] > 0), key=lambda r: (-r["_est"], r["name"]))
        loss = sorted((r for r in considered if r["_est"] < 0), key=lambda r: (r["_est"], r["name"]))
        strip = lambda rows: [{k: v for k, v in r.items() if k != "_est"} for r in rows[:pnl.TOP_N]]
        return {"window_days": len(win_dates), "first_date": first, "pairs_considered": len(considered),
                "pairs_skipped_missing_price": skipped, "n_gainers": len(gain), "n_losers": len(loss),
                "gainers": strip(gain), "losers": strip(loss)}

    return {"as_of": as_of, "definitions_version": pnl.DEFINITIONS_VERSION,
            "windows": {key: window(days) for key, days in pnl.WINDOWS}}


# ---- 種子庫 ---------------------------------------------------------------------------

class _SyntheticDb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = TemporaryDirectory()
        cls.db_path = Path(cls._tmp.name) / "s.db"
        build(cls.db_path, stocks=12, days=60, branches=24, warrants_per_stock=8, seed=7)
        with sqlite3.connect(cls.db_path) as c:
            # 一列 branch_dim 沒有的 branch_id:舊 JOIN 會丟掉它,新路徑也必須丟。
            c.execute("INSERT INTO branch_trades_raw (stock_id, date, branch_id, buy_lots, sell_lots, net_lots, pct, source) "
                      "SELECT '2330', MAX(date), 99999, 5, 0, 5, 0, 'x' FROM daily_prices")
            # 一檔權證整窗沒有收盤(COALESCE 1.0 路徑)
            c.execute("DELETE FROM warrant_daily WHERE warrant_id = (SELECT MIN(id) FROM warrants)")
        cls.engine = create_engine("sqlite:///" + cls.db_path.as_posix())

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        cls._tmp.cleanup()


class WarrantWindowScanTests(_SyntheticDb):
    def test_single_scan_reproduces_the_three_old_queries(self):
        min_amount = 300_000
        with self.engine.connect() as conn:
            dates = [r[0] for r in conn.exec_driver_sql(
                "SELECT DISTINCT date FROM daily_prices ORDER BY date DESC LIMIT 120")]
            d1, d120 = dates[0], dates[-1]
            prior = dates[1:]
            d2, d5, d30 = prior[0], prior[3], prior[28]
            starts = (d1, d2, d5, d30, d120)
            params = {"d1": d1, "d2": d2, "d5": d5, "d30": d30, "d120": d120}

            q1 = conn.execute(text(OLD_Q1), params).fetchall()
            grouped: dict[tuple, list] = {}
            for r in q1:
                grouped.setdefault((r[0], r[1], r[2]), []).append(r)
            charted_old = {
                key: rows for key, rows in grouped.items()
                if any(abs(sum(r[7 + 2 * i] for r in rows)) >= min_amount for i in range(5))
            }
            self.assertTrue(charted_old, "fixture should chart at least one pair")
            self.assertLess(len(charted_old), len(grouped), "fixture should also drop some pairs")

            info = je._warrant_info_for_positions(conn, d1, d5)
            scan = je._WarrantWindowScan(conn, d120=d120, d1=d1, starts=starts,
                                         warrant_info=info, min_amount=min_amount)
            fed = list(scan.position_rows())

            # 區間彙總:同一組配對、同一個順序(舊 GROUP BY 的排序 = (券商, 標的))、同樣的整數。
            self.assertEqual([(k[0], k[1]) for k in charted_old], sorted(scan.pairs))
            for (branch, u, _uname), rows in charted_old.items():
                got = scan.pairs[(branch, u)]
                self.assertEqual([r[3] for r in rows], [wid for wid, _v in got])
                for r, (wid, v) in zip(rows, got):
                    self.assertEqual(list(r[6:16]), v, (branch, u, wid))
                    self.assertEqual((r[4], r[5]), (info[wid].name, info[wid].kind))

            # 逐日序列:舊查詢只留入選配對的列。
            daily_old: dict[tuple, list] = {}
            for r in conn.execute(text(OLD_DAILY), params):
                if (r[0], r[1]) in {(k[0], k[1]) for k in charted_old}:
                    daily_old.setdefault((r[1], r[0]), []).append([r[2], int(r[3]), int(r[4])])
            self.assertEqual(daily_old, scan.daily)
            # 每檔裡券商的先後(第一次出現的順序)= (最早日, 券商名)。
            order_old: dict[str, list[str]] = {}
            for r in conn.execute(text(OLD_DAILY), params):
                if (r[0], r[1]) in {(k[0], k[1]) for k in charted_old}:
                    names = order_old.setdefault(r[1], [])
                    if r[0] not in names:
                        names.append(r[0])
            order_new: dict[str, list[str]] = {}
            for (u, branch), _s in sorted(scan.daily.items(), key=lambda kv: (kv[1][0][0], kv[0][1], kv[0][0])):
                order_new.setdefault(u, []).append(branch)
            self.assertEqual(order_old, order_new)

            # 持有估算的輸入列:舊查詢 + charted 過濾,逐列、同序。
            cur = conn.connection.cursor()
            old_pos = [tuple(r) for r in cur.execute(OLD_POSITIONS, (d120, d1))
                       if (r[1], r[0]) in {(k[0], k[1]) for k in charted_old}]
            cur.close()
            self.assertEqual(old_pos, [tuple(r) for r in fed])
            self.assertEqual(scan.rows_seen, len(old_pos))

            # 標的收盤只讀入選的標的,內容 = 舊的整窗讀取再篩。
            charted_sids = {k[1] for k in charted_old}
            old_under: dict[str, dict] = {}
            for sid, day, close in conn.exec_driver_sql(
                    "SELECT stock_id, date, close FROM daily_prices "
                    "WHERE date >= ? AND date <= ? AND close IS NOT NULL", (d120, d1)):
                if sid in charted_sids:
                    old_under.setdefault(sid, {})[day] = float(close)
            self.assertEqual(old_under, scan.under_by_sid)
            self.assertEqual({sid: (max(v), v[max(v)]) for sid, v in old_under.items()},
                             {sid: (day, float(c)) for sid, (day, c) in scan.under_last.items()})


class PerStockQueryTests(_SyntheticDb):
    def test_branch_history_rows_equal_the_old_join(self):
        with self.engine.connect() as conn:
            d = conn.exec_driver_sql("SELECT MAX(date) FROM daily_prices").scalar()
            names = je._BranchNames(conn)
            sids = [r[0] for r in conn.exec_driver_sql("SELECT id FROM stocks")] + ["9999"]
            for sid in sids:
                old = [tuple(r) for r in conn.execute(text(OLD_HISTORY), {"s": sid, "d": d})]
                self.assertEqual(old, je._branch_history_rows(conn, sid, d, names), sid)
            # 開頭讀表之後才出現的分點(並行寫入):舊 JOIN 看得到,新路徑查不到時重讀一次也要看得到。
            conn.exec_driver_sql("INSERT INTO branch_dim (id, branch_key, broker_id, branch_name) "
                                 "VALUES (88888, 'late', '9999', '晚到分點')")
            conn.exec_driver_sql("INSERT INTO branch_trades_raw (stock_id, date, branch_id, buy_lots, "
                                 "sell_lots, net_lots, pct, source) VALUES ('2330', ?, 88888, 1, 0, 1, 0, 'x')", (d,))
            old = [tuple(r) for r in conn.execute(text(OLD_HISTORY), {"s": "2330", "d": d})]
            self.assertIn("晚到分點", [r[1] for r in old])
            self.assertEqual(old, je._branch_history_rows(conn, "2330", d, names))
            conn.rollback()

    def test_active_warrants_equal_the_old_query_including_ties(self):
        with self.engine.connect() as conn:
            d = conn.exec_driver_sql("SELECT MAX(date) FROM daily_prices").scalar()
            sids = [r[0] for r in conn.exec_driver_sql("SELECT id FROM stocks")] + ["9999"]

            def check():
                cands = je._active_warrant_candidates(conn, d)
                for sid in sids:
                    old = [tuple(r) for r in conn.execute(text(je._ACTIVE_WARRANTS_SQL), {"s": sid, "d": d})]
                    self.assertEqual(old, [tuple(r) for r in je._active_warrants_for(conn, sid, d, cands)], sid)

            check()
            # 同額:兩檔權證同一個成交金額 → 走退回單檔查詢的路徑,結果仍與舊查詢相同。
            conn.exec_driver_sql(
                "UPDATE warrant_daily SET turnover = 777, volume = 1000 WHERE date = ? AND warrant_id IN "
                "(SELECT id FROM warrants WHERE stock_id = '2330' ORDER BY id DESC LIMIT 2)", (d,))
            cands = je._active_warrant_candidates(conn, d)
            top = sorted(cands["2330"], key=lambda r: r[8], reverse=True)[:13]
            self.assertLess(len({r[8] for r in top}), len(top), "fixture must contain a tie")
            check()
            conn.rollback()


class BranchPnlEquivalenceTests(unittest.TestCase):
    def test_new_payload_is_identical_to_the_old_implementation_on_random_inputs(self):
        rnd = random.Random(20261015)
        days = [f"2026-{m:02d}-{d:02d}" for m in range(1, 13) for d in range(1, 29)]
        for case in range(300):
            n_days = rnd.randint(1, len(days))
            dset = sorted(rnd.sample(days, n_days))
            names = [f"分點{i}" for i in range(rnd.randint(1, 12))] + [""]
            rows = []
            for d in dset:
                for name in rnd.sample(names, rnd.randint(0, len(names))):
                    net = rnd.choice([0, 0, 1, -1, 30, -30, 120, -120, 400, -400, None])
                    if case % 7 == 0 and net:
                        net = net + 0.5          # 非整數淨額:不走後綴和預篩
                    rows.append((d, name, net))
                    if rnd.random() < 0.1:
                        rows.append((d, name, rnd.choice([5, -5])))   # 同名同日多列
            candles = []
            af = 1.0
            for d in dset:
                if rnd.random() < 0.05:
                    continue                      # 缺價
                if rnd.random() < 0.03:
                    af *= rnd.choice([0.9, 1.1])  # 除權息
                close = None if rnd.random() < 0.02 else round(rnd.uniform(10, 900), 2)
                candles.append((d, close, af))
            as_of = rnd.choice(dset)
            old = _old_pnl_payload(rows, candles, as_of_limit=as_of)
            new = pnl.branch_pnl_payload(rows, candles, as_of_limit=as_of)
            self.assertEqual(json.dumps(old, ensure_ascii=False), json.dumps(new, ensure_ascii=False), case)

    def test_simulate_pair_matches_old_on_random_sequences(self):
        rnd = random.Random(7)
        for _ in range(2000):
            seq = [(rnd.choice([-300, -50, -1, 0, 1, 50, 300, 2.5, -2.5]), round(rnd.uniform(1, 500), 3))
                   for _ in range(rnd.randint(0, 40))]
            self.assertEqual(_old_simulate_pair(seq, 123.45), pnl.simulate_pair(seq, 123.45))


class WriteIfChangedTests(unittest.TestCase):
    def test_skips_identical_content_and_writes_changes(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.json"
            self.assertTrue(write_atomic_if_changed(p, '{"a":"台"}'))
            os.utime(p, (1_000_000, 1_000_000))
            self.assertFalse(write_atomic_if_changed(p, '{"a":"台"}'))
            self.assertEqual(p.stat().st_mtime, 1_000_000, "identical content must not be rewritten")
            self.assertTrue(write_atomic_if_changed(p, '{"a":"積"}'))      # same size, different bytes
            self.assertEqual(p.read_text(encoding="utf-8"), '{"a":"積"}')
            self.assertTrue(write_atomic_if_changed(p, '{"a":1}'))         # different size
            self.assertEqual(p.read_bytes(), b'{"a":1}')
            self.assertEqual(sorted(x.name for x in Path(tmp).iterdir()), ["a.json"])


if __name__ == "__main__":
    unittest.main()
