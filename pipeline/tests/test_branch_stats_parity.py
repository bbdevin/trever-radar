# -*- coding: utf-8 -*-
"""compute-branch-stats 提速(docs/44 §3.6,2026-10-21)與改前逐值相同。

改的是逐檔那一段的**寫法**:讀取改到背景執行緒預讀(`_read_stocks`)、同名同日合併
不再每列組 dict(`_merge_rows_by_branch`)、隔日沖觀察吃一個只在查到時才組 dict 的視圖
(`_DaytradeView`)、前瞻報酬與買點分位依 (個股, 事件日) 快取(`_StockPrices`)。

這裡把**改前的逐檔迴圈原文**(`_reference_accumulate`,逐字取自 73c5401)當基準,在一個
刻意帶著麻煩的隨機庫上(同名不同 branch_key 同日多列、NULL 淨額/pct、缺開盤、還原因子、
沒有日K的分點日、停業分點)比對兩邊產出的三個結構:`last_seen`、`branch_aggs`(含插入
順序與每個累加欄位)、`stock_stats`(含插入順序)。插入順序要一樣,是因為它決定
`branch_stock_stats`/`branch_rankings` 的寫入順序,而沒有 ORDER BY 的讀者(例如
`_daytrade_pairs_by_stock`)看到的是寫入順序。

全尺寸的核對(合成庫 800 檔 × 500 日、1,040 萬列現股分點,WITHOUT ROWID＋ANALYZE,
三張寫入的表依實體順序逐列比對)記在 docs/44 §3.6。
"""
import contextlib
import io
import random
import unittest
from collections import defaultdict
from datetime import date as date_cls
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import text

import radar.config as config
import radar.db as db
from radar import schema
from radar.compute import compute_branch_stats as cbs
from radar.compute.branch_same_day import merge_by_date
from radar.compute.performance import forward_returns


def _reference_accumulate(conn, stock_ids, cutoff90, cutoff2y):
    """改前(73c5401)compute_all 的逐檔迴圈,原文照搬(只把累加器收成回傳值)。"""
    last_seen: dict[str, str] = {}
    branch_aggs: dict[str, cbs._BranchAgg] = {}
    stock_stats: dict[tuple[str, str], tuple] = {}
    for sid in stock_ids:
        prows = conn.execute(text(
            "SELECT date, open, close, adj_factor FROM daily_prices "
            "WHERE stock_id = :sid AND close IS NOT NULL ORDER BY date"
        ), {"sid": sid}).fetchall()
        trading_dates = [r[0] for r in prows]
        date_index = {d: i for i, d in enumerate(trading_dates)}
        adj_candles = [
            {"date": r[0], "open": (r[1] or 0) * (r[3] or 1.0),
             "close": (r[2] or 0) * (r[3] or 1.0)}
            for r in prows
        ]
        adj_close = [(r[2] or 0) * (r[3] or 1.0) for r in prows]
        close_by_date = {r[0]: r[2] for r in prows}

        strade_rows = conn.execute(text(
            "SELECT branch_name, date, net_lots, sell_lots, pct "
            "FROM branch_trades WHERE stock_id = :sid"
        ), {"sid": sid}).fetchall()

        rows_by_branch: dict[str, list[dict]] = defaultdict(list)
        for br, d, net, sell, pct in strade_rows:
            rows_by_branch[br].append({"date": d, "net": net, "sell": sell, "pct": pct})
        by_branch = {
            br: merge_by_date(rs, ("net", "sell", "pct"))
            for br, rs in rows_by_branch.items()
        }

        for br, datemap in by_branch.items():
            seen = max(datemap)
            if seen > last_seen.get(br, ""):
                last_seen[br] = seen
            qual_dates = sorted(
                d for d, row in datemap.items()
                if (row["net"] or 0) > 0 and row["pct"] is not None and row["pct"] >= cbs.QUAL_PCT
            )
            if not qual_dates:
                continue
            agg = branch_aggs.get(br)
            if agg is None:
                agg = cbs._BranchAgg()
                branch_aggs[br] = agg
            obs = cbs.daytrade_observations(qual_dates, datemap, trading_dates, date_index)
            st_daytrade, _ = cbs.daytrade_flag(obs)
            dt_obs, dt_paybacks = cbs.daytrade_counts(obs)
            agg.add_pair(st_daytrade)
            events = cbs.merge_consecutive_events(qual_dates, date_index)
            matured_vals: list[float] = []
            for ed in events:
                perf = forward_returns(adj_candles, ed)
                fwd5 = perf["fwd_5d"] if perf else None
                idx = date_index.get(ed)
                pctile = 0.5
                if idx is not None:
                    window = [c for c in adj_close[max(0, idx - 19):idx + 1] if c is not None]
                    if window:
                        pctile = cbs.price_percentile(adj_close[idx], min(window), max(window))
                agg.add_event(ed, fwd5, pctile, cutoff90, cutoff2y)
                if fwd5 is not None:
                    matured_vals.append(fwd5)
            win_rate = (100.0 * sum(1 for f in matured_vals if f > 0) / len(matured_vals)) if matured_vals else None
            avg_ret5 = (sum(matured_vals) / len(matured_vals)) if matured_vals else None
            amt = 0.0
            for qd in qual_dates:
                if qd >= cutoff90:
                    cl = close_by_date.get(qd)
                    if cl:
                        amt += (datemap[qd]["net"] or 0) * 1000 * cl
            agg.amount += amt
            stock_stats[(br, sid)] = (
                len(events), cbs._r1(win_rate), cbs._r2(avg_ret5), st_daytrade, qual_dates[-1],
                dt_obs, dt_paybacks,
            )
    return last_seen, branch_aggs, stock_stats


def _agg_state(aggs: dict) -> list:
    return [(br, tuple(getattr(a, s) for s in cbs._BranchAgg.__slots__)) for br, a in aggs.items()]


def _calendar(n: int) -> list[str]:
    out, d = [], date_cls(2026, 10, 2)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return sorted(out)


def _fill(conn, seed: int) -> None:
    rnd = random.Random(seed)
    cal = _calendar(90)
    sids = [str(1101 + 7 * i) for i in range(14)]
    conn.execute(schema.stocks.insert(), [
        {"id": s, "name": f"股{s}", "market": "twse", "type": "stock"} for s in sids]
        + [{"id": "0050", "name": "指數型", "market": "twse", "type": "stock"},
           {"id": "030001", "name": "權證", "market": "twse", "type": "warrant"}])
    prices = []
    for s in sids:
        close, adj = rnd.uniform(10, 500), 1.0
        for d in cal:
            if rnd.random() < 0.04:
                continue                                  # 停牌:分點列會落在沒有日K的日子
            close = max(1.0, close * (1 + rnd.uniform(-0.06, 0.06)))
            if rnd.random() < 0.01:
                adj = round(adj * rnd.uniform(0.9, 0.99), 6)   # 除權息:還原因子
            opn = None if rnd.random() < 0.03 else (0.0 if rnd.random() < 0.02 else round(close * 0.99, 2))
            prices.append({"stock_id": s, "date": d, "open": opn, "close": round(close, 2),
                           "adj_factor": adj, "volume": 1000})
    conn.execute(schema.daily_prices.insert(), prices)
    # 18 個分點、每 4 個有一個同名的第二 branch_key;一個名稱帶停業標記。
    dim, ids_of = [], defaultdict(list)
    for b in range(1, 19):
        name = "元大-西門(停)" if b == 5 else f"分點{b}"
        dim.append({"id": b, "branch_key": f"k{b}", "branch_name": name})
        ids_of[b].append(b)
        if b % 4 == 0:
            dim.append({"id": 100 + b, "branch_key": f"alias{b}", "branch_name": name})
            ids_of[b].append(100 + b)
    rnd.shuffle(dim)
    conn.execute(schema.branch_dim.insert(), dim)
    raw = []
    for s in sids + ["030001"]:
        for d in cal:
            for b in rnd.sample(range(1, 19), rnd.randint(2, 9)):
                if b == 5 and d > cal[30]:
                    continue                              # 停業:後段不再出現
                for bid in ids_of[b] if rnd.random() < 0.5 else ids_of[b][:1]:
                    buy, sell = rnd.choice([0, 1, 3, 20, 80]), rnd.choice([0, 2, 30, 90])
                    net = None if rnd.random() < 0.02 else buy - sell
                    pct = None if rnd.random() < 0.03 else round(rnd.uniform(-3, 4), 2)
                    raw.append({"stock_id": s, "date": d, "branch_id": bid, "buy_lots": buy,
                                "sell_lots": None if rnd.random() < 0.02 else sell,
                                "net_lots": net, "pct": pct, "source": "fixture"})
    conn.execute(schema.branch_trades_raw.insert(), raw)
    conn.execute(schema.tracked_branches.insert(), [
        {"branch_name": "分點3", "source": "manual"}, {"branch_name": "分點7", "source": "auto"},
        {"branch_name": "分點9", "source": "muted"}])


class _Db:
    def __enter__(self):
        self.tmp = TemporaryDirectory()
        self.old = (config.DB_URL, config.DATA_DIR)
        config.DB_URL = "sqlite:///" + (Path(self.tmp.name) / "t.db").as_posix()
        config.DATA_DIR = Path(self.tmp.name)
        db._engine = None
        db.init_db()
        return db.get_engine()

    def __exit__(self, *exc):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self.old
        self.tmp.cleanup()


class AccumulateParityTests(unittest.TestCase):
    def test_new_loop_matches_the_old_loop_value_for_value_and_in_order(self):
        for seed in (1, 2, 3):
            with self.subTest(seed=seed), _Db() as engine:
                with engine.begin() as conn:
                    _fill(conn, seed)
                with engine.connect() as conn:
                    stock_ids = [r[0] for r in conn.execute(text(
                        "SELECT s.id FROM stocks s WHERE s.type = 'stock' AND s.name NOT LIKE '%指%' "
                        "AND EXISTS (SELECT 1 FROM branch_trades b WHERE b.stock_id = s.id) ORDER BY s.id"))]
                    as_of = conn.execute(text("SELECT MAX(date) FROM branch_trades")).scalar()
                    cutoff2y = (date_cls.fromisoformat(as_of) - timedelta(days=730)).isoformat()
                    # 夾具只有 90 個交易日:90 日 cutoff 取在中段,讓兩邊都有事件
                    cutoff90 = sorted({r[0] for r in conn.execute(text(
                        "SELECT date FROM daily_prices"))})[45]
                    ref = _reference_accumulate(conn, stock_ids, cutoff90, cutoff2y)

                last_seen, aggs, stats = {}, {}, {}
                with contextlib.closing(cbs._read_stocks(engine, stock_ids)) as reads:
                    got_ids = []
                    for sid, prows, srows, _r, _w in reads:
                        got_ids.append(sid)
                        cbs._accumulate_stock(sid, prows, srows, cutoff90, cutoff2y,
                                              last_seen, aggs, stats)
                self.assertEqual(got_ids, stock_ids)
                self.assertEqual(last_seen, ref[0])
                self.assertEqual(list(last_seen), list(ref[0]))
                self.assertEqual(_agg_state(aggs), _agg_state(ref[1]))
                self.assertEqual(list(stats.items()), list(ref[2].items()))
                # 夾具真的有走到麻煩的路徑
                self.assertTrue(any(s[3] is not None for s in stats.values()))
                self.assertTrue(any(a.n_matured < a.n_events for a in aggs.values()))

    def test_compute_all_runs_end_to_end(self):
        with _Db() as engine:
            with engine.begin() as conn:
                _fill(conn, 7)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cbs.compute_all()
            with engine.connect() as conn:
                n = conn.execute(text("SELECT COUNT(*) FROM branch_stock_stats")).scalar()
                closed = conn.execute(text(
                    "SELECT COUNT(*) FROM branch_rankings WHERE branch_name LIKE '%(停)%'")).scalar()
        self.assertGreater(n, 0)
        self.assertEqual(closed, 0)
        line = next(ln for ln in out.getvalue().splitlines() if ln.startswith("branch stats timing:"))
        self.assertRegex(line, r"\bread-wait=\d+s\b")


class HelperParityTests(unittest.TestCase):
    def test_merge_rows_by_branch_equals_merge_by_date(self):
        rnd = random.Random(11)
        for _ in range(200):
            rows = []
            for _ in range(rnd.randint(0, 60)):
                rows.append((rnd.choice("ABCD"), f"2026-01-{rnd.randint(1, 9):02d}",
                             rnd.choice([None, -5, 0, 3, 12]),
                             rnd.choice([None, 0, 4, 9]),
                             rnd.choice([None, 0.5, 1.0, 2.25, -1.5, 3])))
            ref_groups: dict[str, list[dict]] = defaultdict(list)
            for br, d, net, sell, pct in rows:
                ref_groups[br].append({"date": d, "net": net, "sell": sell, "pct": pct})
            ref = {br: merge_by_date(rs, ("net", "sell", "pct")) for br, rs in ref_groups.items()}
            got = cbs._merge_rows_by_branch(rows)
            self.assertEqual(list(got), list(ref))
            for br in ref:
                self.assertEqual(set(got[br]), set(ref[br]))
                for d, v in ref[br].items():
                    g = got[br][d]
                    exp = (v["net"], v["sell"], v["pct"])
                    self.assertEqual(g, exp)
                    self.assertEqual([type(x) for x in g], [type(x) for x in exp])

    def test_stock_prices_event_equals_inline_formula(self):
        rnd = random.Random(5)
        cal = _calendar(60)
        prows = []
        for d in cal:
            if rnd.random() < 0.1:
                continue
            prows.append((d, rnd.choice([None, 0.0, round(rnd.uniform(5, 50), 2)]),
                          round(rnd.uniform(5, 50), 2), rnd.choice([None, 1.0, 0.93])))
        dates = [r[0] for r in prows]
        index = {d: i for i, d in enumerate(dates)}
        candles = [{"date": r[0], "open": (r[1] or 0) * (r[3] or 1.0),
                    "close": (r[2] or 0) * (r[3] or 1.0)} for r in prows]
        adj_close = [(r[2] or 0) * (r[3] or 1.0) for r in prows]
        sp = cbs._StockPrices(prows)
        for ed in cal + ["2020-01-01", "2030-01-01"]:
            perf = forward_returns(candles, ed)
            fwd5 = perf["fwd_5d"] if perf else None
            idx = index.get(ed)
            pctile = 0.5
            if idx is not None:
                window = [c for c in adj_close[max(0, idx - 19):idx + 1] if c is not None]
                if window:
                    pctile = cbs.price_percentile(adj_close[idx], min(window), max(window))
            self.assertEqual(sp.event(ed, index), (fwd5, pctile))
            self.assertEqual(sp.event(ed, index), (fwd5, pctile))      # 快取命中

    def test_daytrade_view_feeds_the_shared_observation_builder_identically(self):
        cal = _calendar(10)
        index = {d: i for i, d in enumerate(cal)}
        datemap = {cal[0]: (5, 0, 2.0), cal[1]: (3, 4, 1.5), cal[3]: (None, 9, 1.0),
                   cal[4]: (7, None, 1.1), cal[9]: (2, 1, 1.0)}
        as_dicts = {d: {"net": v[0], "sell": v[1], "pct": v[2]} for d, v in datemap.items()}
        qual = [cal[0], cal[1], cal[3], cal[4], cal[9], "2026-12-31"]
        self.assertEqual(
            cbs.daytrade_observations(qual, cbs._DaytradeView(datemap), cal, index),
            cbs.daytrade_observations(qual, as_dicts, cal, index))


class ReaderThreadTests(unittest.TestCase):
    def test_reader_error_is_raised_in_the_caller(self):
        class Boom:
            def raw_connection(self):
                raise RuntimeError("boom")
        with self.assertRaisesRegex(RuntimeError, "boom"):
            list(cbs._read_stocks(Boom(), ["1101"]))

    def test_closing_early_stops_the_reader(self):
        with _Db() as engine:
            with engine.begin() as conn:
                _fill(conn, 3)
            ids = [str(1101 + 7 * i) for i in range(14)]
            gen = cbs._read_stocks(engine, ids)
            first = next(gen)
            self.assertEqual(first[0], ids[0])
            gen.close()                                   # 不得卡住(背景執行緒卡在 put)
            import threading
            self.assertFalse([t for t in threading.enumerate() if t.name == "branch-stats-reader"])


if __name__ == "__main__":
    unittest.main()
