"""Benchmark the WITHOUT ROWID layouts against today's production layout.

    cd pipeline
    python tools/bench_branch_raw.py OLD.db --variant 4k=NEW_4k.db --variant 4k+stats=NEW_4k_an.db \
        --variant 8k=NEW_8k.db --variant 8k+stats=NEW_8k_an.db [--runs 3] [--cases a1,b4,...]
        [--write --tmp DIR] [--export --work DIR] [--json OUT.json]

Every file is opened read-only + immutable (case d writes to temp copies only).

Approximating the VPS (1.7 GB RAM, cold cache) on a fast PC:
  * each timed run opens a fresh connection with PRAGMA cache_size=-2000
    (2 MB = the pipeline's default, so SQLite re-fetches evicted pages) and mmap_size=0;
  * "KiB" = distinct bytes the query touches: SQLITE_DBSTATUS_CACHE_MISS ×
    page_size on one extra run with a 1 GiB cache (nothing evicted, so every
    miss is a new page) — what a cold disk must deliver, independent of this
    PC's SSD/RAM and comparable across 4K/8K pages;
  * "re-read KiB" = the same counter on the first small-cache run: bytes pulled
    from the OS including re-reads (syscall/CPU pressure; reported, not judged);
  * each case runs --runs times; first run and median are reported.
The OS file cache is not flushed (Windows has no unprivileged way), so the ms
columns are CPU-bound here; on the VPS, cold I/O adds to them — weigh "KiB".

Rule (planner, 2026-10-03): a case that is >2× slower (median ms) or touches >2×
the distinct bytes on a variant is a regression; the bench then retries it with
INDEXED BY / NOT INDEXED hints (the view is inlined so the hint reaches
branch_trades_raw).  A regression no hint brings back to ≤2× makes that variant
"不可上線".  A hint that does fix it still needs a code change to ship.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import sqlite3
import statistics
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1]
FIXED_STOCKS = ["4967", "6488", "2330", "8299", "3105"]
VIEW_SQL = ("SELECT r.stock_id, r.date, d.branch_key, d.broker_id, d.branch_name, r.buy_lots, "
            "r.sell_lots, r.net_lots, r.pct, r.source FROM branch_trades_raw r {hint} "
            "JOIN branch_dim d ON r.branch_id = d.id")
BRANCH_HINTS = ("NOT INDEXED", "INDEXED BY ix_branch_trades_raw_date_cover", "INDEXED BY ix_branch_trades_raw_date",
                "INDEXED BY ix_branch_trades_raw_branch")
PRICE_HINTS = ("NOT INDEXED", "INDEXED BY ix_daily_prices_date")

# (id, label, sql, scope) — scope "stock" runs once per sample stock, "once" runs once.
CASES = [
    # a. per-stock (clustered reads should win)
    ("a1", "compute-branch-stats 逐檔讀 (compute_branch_stats.py:327)",
     "SELECT branch_name, date, net_lots, sell_lots, pct FROM branch_trades WHERE stock_id = :sid", "stock"),
    ("a2", "個股 branch_history 730 日,含 buy_lots (json_export.py:2195)",
     "SELECT date, branch_name, buy_lots, sell_lots, net_lots FROM branch_trades "
     "WHERE stock_id = :sid AND date >= date(:d, '-730 days') ORDER BY date DESC", "stock"),
    ("a3", "個股當日分點 (json_export.py:2184)",
     "SELECT branch_name, buy_lots, sell_lots, net_lots, pct FROM branch_trades "
     "WHERE stock_id = :sid AND date = :d ORDER BY net_lots DESC", "stock"),
    ("a4", "v2 shadow 逐檔 date<=as_of (branch_ranking_v2_shadow.py:216)",
     "SELECT branch_name, date, net_lots, sell_lots, pct FROM branch_trades "
     "WHERE stock_id = :sid AND date <= :d", "stock"),
    ("a5", "K 線全歷史 (json_export.py:2162)",
     "SELECT p.date, p.open, p.high, p.low, p.close, p.volume, p.turnover, p.adj_factor "
     "FROM daily_prices p WHERE p.stock_id = :sid AND p.close IS NOT NULL ORDER BY p.date", "stock"),
    ("a6", "K 線 600 根 (json_export.py:2167)",
     "SELECT p.date, p.open, p.high, p.low, p.close, p.volume, p.turnover, p.adj_factor "
     "FROM daily_prices p WHERE p.stock_id = :sid AND p.close IS NOT NULL "
     "ORDER BY p.date DESC LIMIT 600", "stock"),
    # b. date-sliced (clustered-by-stock tables are expected to lose here)
    ("b1", "匯入覆蓋閘 COUNT(DISTINCT stock) 某日 (importer.py:1359)",
     "SELECT COUNT(DISTINCT b.stock_id) FROM branch_trades_raw b "
     "JOIN stocks s ON s.id = b.stock_id AND s.type = 'stock' WHERE b.date = :d", "once"),
    ("b2", "匯入略過檢查 DISTINCT stock 某日 (importer.py:798)",
     "SELECT DISTINCT stock_id FROM branch_trades WHERE date = :d", "once"),
    ("b3", "權證當日分點 (json_export.py:2105)",
     "SELECT stock_id, branch_name, buy_lots, sell_lots, net_lots FROM branch_trades "
     "WHERE date = :d AND LENGTH(stock_id) = 6 ORDER BY stock_id, branch_key", "once"),
    ("b4", "評分 20 日窗全市場分點 (scores.py:493)",
     "SELECT r.stock_id, r.date, d.branch_key, d.branch_name, r.buy_lots, r.sell_lots, r.net_lots, r.pct "
     "FROM {date_window} WHERE r.date >= :d20 AND r.date <= :d AND LENGTH(r.stock_id) = 4", "once"),
    ("b5", "評分 11 日價格全市場 (scores.py:444)",
     "SELECT stock_id, date, open, high, low, close, volume FROM daily_prices p "
     "WHERE date >= :d10 AND date <= :d AND close IS NOT NULL", "once"),
    ("b6", "評分 20 日均成交額 GROUP BY (scores.py:457)",
     "SELECT stock_id, AVG(turnover) FROM daily_prices p WHERE date >= :d20 AND date < :d "
     "GROUP BY stock_id", "once"),
    ("b7", "口袋 20 日分點窗 (pocket.py:414)",
     "SELECT r.stock_id, r.date, d.branch_name, r.net_lots FROM {date_window} "
     "WHERE r.date >= :d19 AND r.date <= :d AND LENGTH(r.stock_id) = 4", "once"),
    ("b8", "口袋 20 日成交量 IN (pocket.py:431)",
     "SELECT stock_id, date, volume FROM daily_prices p WHERE date >= :d19 AND date <= :d "
     "AND stock_id IN ({stock_in})", "once"),
    ("b9", "匯出主查詢 當日全市場 (json_export.py:1369)",
     "SELECT p.stock_id, p.close, p.turnover, pp.close, p5.close, a.avg_vol20 "
     "FROM daily_prices p JOIN stocks s ON s.id = p.stock_id AND s.type = 'stock' "
     "LEFT JOIN daily_prices pp ON pp.stock_id = p.stock_id AND pp.date = :d1 "
     "LEFT JOIN daily_prices p5 ON p5.stock_id = p.stock_id AND p5.date = :d5 "
     "LEFT JOIN (SELECT stock_id, AVG(volume) AS avg_vol20 FROM daily_prices "
     "WHERE date >= :d20 AND date < :d GROUP BY stock_id) a ON a.stock_id = p.stock_id "
     "WHERE p.date = :d AND p.close IS NOT NULL ORDER BY p.stock_id", "once"),
    ("b10", "export latest(branch_trades) MAX(date) (json_export.py:1302)",
     "SELECT MAX(date) FROM branch_trades WHERE date <= :d", "once"),
    ("b11", "權證分點 bd1 MAX(date) (json_export.py:2430)",
     "SELECT MAX(b.date) FROM branch_trades b JOIN warrants w ON w.id = b.stock_id "
     "JOIN stocks s ON s.id = w.stock_id WHERE LENGTH(b.stock_id) = 6 AND b.date >= :d119 "
     "AND b.date <= :d AND s.type = 'stock' AND s.name NOT LIKE '%指%'", "once"),
    ("b12", "權證分點 120 日 GROUP BY 主查詢 (json_export.py:2449)",
     "SELECT b.branch_name, w.stock_id, s.name, b.stock_id, w.name, w.kind, "
     "SUM(CASE WHEN b.date >= :d THEN b.net_lots ELSE 0 END), "
     "SUM(CASE WHEN b.date >= :d4 THEN b.net_lots * CAST(ROUND(COALESCE(wd.close, 1.0) * 1000) AS INTEGER) ELSE 0 END), "
     "SUM(CASE WHEN b.date >= :d119 THEN b.net_lots * CAST(ROUND(COALESCE(wd.close, 1.0) * 1000) AS INTEGER) ELSE 0 END) "
     "FROM branch_trades b JOIN warrants w ON w.id = b.stock_id JOIN stocks s ON s.id = w.stock_id "
     "LEFT JOIN warrant_daily wd ON wd.warrant_id = b.stock_id AND wd.date = b.date "
     "WHERE LENGTH(b.stock_id) = 6 AND b.date >= :d119 AND b.date <= :d "
     "AND s.type = 'stock' AND s.name NOT LIKE '%指%' "
     "GROUP BY b.branch_name, w.stock_id, s.name, b.stock_id, w.name, w.kind", "once"),
    ("b13", "權證分點每日圖 120 日 (json_export.py:2549)",
     "SELECT b.branch_name, w.stock_id, b.date, "
     "SUM(CASE WHEN w.kind = 'call' THEN b.net_lots * CAST(ROUND(COALESCE(wd.close, 1.0) * 1000) AS INTEGER) ELSE 0 END) "
     "FROM branch_trades b JOIN warrants w ON w.id = b.stock_id JOIN stocks s ON s.id = w.stock_id "
     "LEFT JOIN warrant_daily wd ON wd.warrant_id = b.stock_id AND wd.date = b.date "
     "WHERE LENGTH(b.stock_id) = 6 AND b.date >= :d119 AND b.date <= :d "
     "AND s.type = 'stock' AND s.name NOT LIKE '%指%' "
     "GROUP BY b.branch_name, w.stock_id, b.date ORDER BY b.date", "once"),
    ("b14", "權證異動 40 日 (json_export.py:2397)",
     "SELECT b.branch_name, b.stock_id, SUM(b.net_lots), SUM(b.buy_lots), COUNT(*), MAX(b.date) "
     "FROM branch_trades b JOIN warrants w ON w.id = b.stock_id LEFT JOIN stocks s ON s.id = w.stock_id "
     "WHERE LENGTH(b.stock_id) = 6 AND b.date >= :d39 GROUP BY b.branch_name, b.stock_id "
     "HAVING SUM(b.net_lots) >= 300 ORDER BY SUM(b.net_lots) DESC LIMIT 60", "once"),
    ("b15", "分點×個股分位 490 日 依股票排序 (branch_stock_pctile_counts.py:368)",
     "SELECT b.stock_id, b.branch_name, b.date, b.net_lots, b.sell_lots, b.pct FROM branch_trades b "
     "JOIN stocks s ON s.id = b.stock_id WHERE s.type = 'stock' AND b.date >= :d489 AND b.date <= :d "
     "ORDER BY b.stock_id, b.branch_name, b.date, b.branch_key", "once"),
    ("b16", "PIT 帳本 60 日 依股票排序 (branch_point_in_time_persist.py:261)",
     "SELECT b.stock_id, b.branch_name, b.date, b.net_lots, b.pct FROM branch_trades b "
     "JOIN stocks s ON s.id = b.stock_id WHERE s.type = 'stock' AND b.date >= :d59 AND b.date <= :d "
     "ORDER BY b.stock_id, b.branch_name, b.date, b.branch_key", "once"),
    # c. per-branch
    ("c1", "追蹤分點明細 names×120 日 (json_export.py:2730)",
     "SELECT b.branch_name, b.date, b.stock_id, SUM(b.net_lots), AVG(b.pct) FROM branch_trades b "
     "JOIN stocks s ON s.id = b.stock_id AND s.type IN ('stock', 'etf') "
     "WHERE b.branch_name IN ({names}) AND b.date >= date(:d, '-120 days') AND b.date <= :d "
     "GROUP BY b.branch_name, b.date, b.stock_id ORDER BY b.branch_name, b.date, b.stock_id", "once"),
    ("c2", "追蹤當日異動 (json_export.py:2367)",
     "SELECT b.branch_name, b.stock_id, s.name, b.buy_lots, b.sell_lots, b.net_lots, b.pct "
     "FROM branch_trades b JOIN stocks s ON s.id = b.stock_id WHERE b.date = :d "
     "AND b.branch_name IN (SELECT branch_name FROM tracked_branches WHERE COALESCE(source, '') <> 'muted') "
     "ORDER BY b.branch_name, b.net_lots DESC, b.stock_id, b.branch_key", "once"),
    ("c3", "單一分點 branch_id 120 日 (ix_branch_trades_raw_branch)",
     "SELECT stock_id, date, buy_lots, sell_lots, net_lots FROM branch_trades_raw b "
     "WHERE branch_id = :bid AND date >= date(:d, '-120 days')", "once"),
]


class PageReads:
    """Pages SQLite fetched from the file (SQLITE_DBSTATUS_CACHE_MISS), via ctypes.

    Python's sqlite3 does not expose sqlite3_db_status.  The connection's
    sqlite3* is the first field after PyObject_HEAD (CPython layout); it is
    validated with sqlite3_db_filename and the column is disabled on mismatch.
    """
    CACHE_MISS = 8

    def __init__(self) -> None:
        self.lib = None
        try:
            import ctypes
            import os
            import _sqlite3
            if sys.platform == "win32":
                lib = ctypes.CDLL(os.path.join(sys.base_prefix, "DLLs", "sqlite3.dll"))
            else:
                lib = ctypes.CDLL(_sqlite3.__file__)
            lib.sqlite3_db_status.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                              ctypes.POINTER(ctypes.c_int),
                                              ctypes.POINTER(ctypes.c_int), ctypes.c_int]
            lib.sqlite3_db_filename.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
            lib.sqlite3_db_filename.restype = ctypes.c_char_p
            self.ctypes, self.lib = ctypes, lib
        except Exception as exc:  # pragma: no cover - platform dependent
            print(f"(page-read counter unavailable: {exc})")

    def _db(self, conn: sqlite3.Connection, path: Path):
        if self.lib is None:
            return None
        c = self.ctypes
        ptr = c.c_void_p.from_address(id(conn) + 2 * c.sizeof(c.c_void_p)).value
        try:
            name = self.lib.sqlite3_db_filename(ptr, b"main")
        except Exception:
            return None
        if not name or Path(name.decode()).resolve() != path.resolve():
            return None
        return ptr

    def read(self, conn: sqlite3.Connection, path: Path, reset: bool = True) -> int | None:
        ptr = self._db(conn, path)
        if ptr is None:
            return None
        cur, hi = self.ctypes.c_int(0), self.ctypes.c_int(0)
        self.lib.sqlite3_db_status(ptr, self.CACHE_MISS, self.ctypes.byref(cur),
                                   self.ctypes.byref(hi), 1 if reset else 0)
        return cur.value


PAGES: PageReads | None = None


def ro(path: Path, cache_kib: int) -> sqlite3.Connection:
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    conn.execute(f"PRAGMA cache_size = -{cache_kib}")
    conn.execute("PRAGMA mmap_size = 0")
    return conn


def context(path: Path, n_random: int, seed: int) -> dict:
    c = ro(path, 65536)
    d = c.execute("SELECT MAX(date) FROM branch_trades_raw").fetchone()[0]
    days = [r[0] for r in c.execute(
        "SELECT DISTINCT date FROM daily_prices WHERE date <= ? ORDER BY date DESC LIMIT 490", (d,))]

    def back(n):  # the n-th trading day before d (0 = d)
        return days[min(n, len(days) - 1)]

    have = [r[0] for r in c.execute(
        "SELECT s.id FROM stocks s WHERE s.type = 'stock' AND EXISTS "
        "(SELECT 1 FROM branch_trades_raw b WHERE b.stock_id = s.id) ORDER BY s.id")]
    rnd = random.Random(seed)
    fixed = [s for s in FIXED_STOCKS if s in have]
    pool = [s for s in have if s not in fixed]
    sample = fixed + rnd.sample(pool, min(n_random, len(pool)))
    names = [r[0] for r in c.execute(
        "SELECT branch_name FROM tracked_branches WHERE COALESCE(source,'') <> 'muted' "
        "ORDER BY branch_name LIMIT 30")]
    if not names:
        names = [r[0] for r in c.execute("SELECT branch_name FROM branch_dim ORDER BY id LIMIT 30")]
    bid = c.execute("SELECT branch_id FROM branch_trades_raw WHERE date = ? "
                    "GROUP BY branch_id ORDER BY COUNT(*) DESC LIMIT 1", (d,)).fetchone()[0]
    pocket = [r[0] for r in c.execute(
        "SELECT stock_id FROM daily_prices WHERE date = ? ORDER BY turnover DESC LIMIT 400", (d,))]
    c.close()
    params = {"d": d, **{f"d{n}": back(n) for n in (1, 4, 5, 10, 19, 20, 39, 59, 119, 489)}}
    return {"params": params, "stocks": sample, "names": names, "bid": bid, "pocket": pocket}


def build_cases(ctx: dict, only: set[str] | None) -> list[tuple]:
    names_sql = ", ".join(f":n{i}" for i in range(len(ctx["names"])))
    stock_in = ", ".join(f":s{i}" for i in range(len(ctx["pocket"])))
    extra = {**{f"n{i}": n for i, n in enumerate(ctx["names"])},
             **{f"s{i}": s for i, s in enumerate(ctx["pocket"])}, "bid": ctx["bid"]}
    base = {**ctx["params"], **extra}
    out = []
    for cid, label, sql, scope in CASES:
        if only and cid not in only:
            continue
        sql = sql.format(names=names_sql, stock_in=stock_in, date_window="{date_window}")
        psets = ([dict(base, sid=s) for s in ctx["stocks"]] if scope == "stock" else [base])
        out.append((cid, label, sql, psets))
    return out


def render(sql: str, conn: sqlite3.Connection) -> str:
    """{date_window} = radar/branch_source.py's FROM clause for this file's layout."""
    if "{date_window}" not in sql:
        return sql
    has = conn.execute("SELECT 1 FROM sqlite_master WHERE type='index' "
                       "AND name='ix_branch_trades_raw_date_cover'").fetchone()
    hint = " INDEXED BY ix_branch_trades_raw_date_cover" if has else ""
    return sql.replace("{date_window}", f"branch_trades_raw r{hint} JOIN branch_dim d ON r.branch_id = d.id")


def run_once(path: Path, sql: str, psets: list[dict], cache_kib: int, count_pages: bool):
    conn = ro(path, cache_kib)
    sql = render(sql, conn)
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    if count_pages:
        PAGES.read(conn, path)
    t0 = time.perf_counter()
    rows = 0
    for p in psets:
        cur = conn.execute(sql, p)
        while True:
            chunk = cur.fetchmany(5000)
            if not chunk:
                break
            rows += len(chunk)
    ms = (time.perf_counter() - t0) * 1000
    kib = None
    if count_pages:
        pages = PAGES.read(conn, path)
        kib = None if pages is None else pages * page_size / 1024
    plan = " | ".join(r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + sql, psets[0]))
    conn.close()
    return ms, rows, kib, plan


def measure(path: Path, sql: str, psets: list[dict], runs: int, cache_kib: int) -> dict:
    """ms: median over `runs` with the small cache.  kib: distinct bytes the query
    touches (one extra run with a 1 GiB cache, so nothing is evicted and every
    cache miss is a different page = what a cold disk must deliver).  reread_kib:
    bytes fetched from the OS with the small cache (re-reads included) — the
    syscall/CPU pressure on a memory-starved box, reported, not judged."""
    times, reread, rows, plan = [], None, 0, ""
    for i in range(runs):
        ms, rows, k, plan = run_once(path, sql, psets, cache_kib, count_pages=(i == 0))
        times.append(ms)
        if i == 0:
            reread = k
    _, _, distinct, _ = run_once(path, sql, psets, 1048576, count_pages=True)
    return {"first": times[0], "median": statistics.median(times), "rows": rows,
            "kib": distinct, "reread_kib": reread, "plan": plan}


def hinted(sql: str, hint: str) -> str | None:
    """Apply `hint` to the converted table the query reads, or None if it reads neither."""
    if "INDEXED BY ix_daily" in hint or (hint == "NOT INDEXED" and "daily_prices p" in sql
                                        and "branch_trades" not in sql):
        new = re.sub(r"daily_prices p\b", f"daily_prices p {hint}", sql, count=1)
        return new if new != sql else None
    if "branch_trades_raw b" in sql:
        return sql.replace("branch_trades_raw b", f"branch_trades_raw b {hint}", 1)
    new = re.sub(r"\b(FROM|JOIN)\s+branch_trades\b(?!_)",
                 lambda m: f"{m.group(1)} ({VIEW_SQL.format(hint=hint)})", sql)
    return new if new != sql else None


def ratio(a, b):
    return (b / a) if a else (float("inf") if b else 1.0)


def bench_reads(old: Path, variants: list[tuple[str, Path]], cases, runs: int, cache_kib: int):
    results = []
    for cid, label, sql, psets in cases:
        res = {"id": cid, "case": label, "old": measure(old, sql, psets, runs, cache_kib), "variants": {}}
        line = f"  {cid} old {res['old']['median']:.1f}ms"
        for vname, vpath in variants:
            m = measure(vpath, sql, psets, runs, cache_kib)
            o = res["old"]
            t_r = ratio(o["median"], m["median"])
            b_r = ratio(o["kib"], m["kib"]) if o["kib"] is not None and m["kib"] is not None else None
            m["time_ratio"], m["bytes_ratio"] = t_r, b_r
            if m["rows"] != o["rows"]:
                m["warning"] = f"row count {m['rows']} != OLD {o['rows']}"
            worst = max(t_r, b_r or 0)
            if worst > 2:
                m["hints"] = []
                for hint in dict.fromkeys(BRANCH_HINTS + PRICE_HINTS):
                    hs = hinted(sql, hint)
                    if hs is None:
                        continue
                    try:
                        hm = measure(vpath, hs, psets, runs, cache_kib)
                    except sqlite3.OperationalError as exc:
                        m["hints"].append({"hint": hint, "error": str(exc)})
                        continue
                    hm["time_ratio"] = ratio(o["median"], hm["median"])
                    hm["bytes_ratio"] = (ratio(o["kib"], hm["kib"])
                                         if o["kib"] is not None and hm["kib"] is not None else None)
                    hm["hint"] = hint
                    hm["fixes"] = max(hm["time_ratio"], hm["bytes_ratio"] or 0) <= 2 and hm["rows"] == o["rows"]
                    m["hints"].append(hm)
                m["fixed_by"] = next((h["hint"] for h in m["hints"] if h.get("fixes")), None)
            res["variants"][vname] = m
            line += f" | {vname} {m['median']:.1f}ms ({t_r:.2f}×{'' if b_r is None else f', {b_r:.2f}× bytes'})"
        print(line, flush=True)
        results.append(res)
    return results


def next_weekday(iso: str) -> str:
    d = date.fromisoformat(iso) + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.isoformat()


def bench_write(dbs: list[tuple[str, Path]], tmp: Path, days: int) -> dict:
    """On a temp copy of each DB: append `days` new trading days of branch rows and
    one day of prices via radar.db.upsert (the importer's path), then re-upsert the
    last branch day (the 22:00 round's conflict path).  Time + file growth."""
    sys.path.insert(0, str(PIPELINE))
    from sqlalchemy import create_engine
    from radar import schema
    from radar.db import upsert

    out = {}
    for name, src in dbs:
        dst = tmp / f"write_{re.sub(r'[^A-Za-z0-9]', '_', name)}.db"
        shutil.copyfile(src, dst)
        eng = create_engine("sqlite:///" + dst.resolve().as_posix())
        with eng.begin() as conn:
            d = conn.exec_driver_sql("SELECT MAX(date) FROM branch_trades_raw").scalar()
            bcols = [c.name for c in schema.branch_trades_raw.columns]
            brows = [dict(zip(bcols, r)) for r in conn.exec_driver_sql(
                f"SELECT {', '.join(bcols)} FROM branch_trades_raw WHERE date = ? ORDER BY stock_id", (d,))]
            pd_ = conn.exec_driver_sql("SELECT MAX(date) FROM daily_prices").scalar()
            pcols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(daily_prices)")]
            prows = [dict(zip(pcols, r)) for r in conn.exec_driver_sql(
                f"SELECT {', '.join(pcols)} FROM daily_prices WHERE date = ? ORDER BY stock_id", (pd_,))]
        steps, size0, new_day = {}, dst.stat().st_size, d

        def step(label, table, rows):
            nonlocal size0
            t0 = time.perf_counter()
            with eng.begin() as conn:
                conn.exec_driver_sql("PRAGMA cache_size=-2000")
                upsert(conn, table, rows)
            ms = (time.perf_counter() - t0) * 1000
            wal = Path(str(dst) + "-wal")
            wal_b = wal.stat().st_size if wal.exists() else 0
            with eng.begin() as conn:
                conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
            steps[label] = {"rows": len(rows), "ms": ms, "wal_bytes": wal_b,
                            "growth": dst.stat().st_size - size0}
            size0 = dst.stat().st_size

        for i in range(days):
            new_day = next_weekday(new_day)
            for r in brows:
                r["date"] = new_day
            step(f"branch_new_day_{i + 1}", schema.branch_trades_raw, brows)
        for r in brows:
            r["pct"] = (r["pct"] or 0) + 0.01
        step("branch_reupsert_last_day", schema.branch_trades_raw, brows)
        pday = next_weekday(pd_)
        for r in prows:
            r["date"] = pday
        step("prices_new_day", schema.daily_prices, prows)
        eng.dispose()
        for f in (dst, Path(str(dst) + "-wal"), Path(str(dst) + "-shm")):
            if f.exists():
                f.unlink()
        out[name] = steps
        print(f"  write {name}: " + ", ".join(
            f"{k} {v['ms']:.0f}ms +{v['growth'] / 1048576:.1f}MiB" for k, v in steps.items()), flush=True)
    return out


GATE_PER_STOCK_SHRINK = {"a2": 0.35, "a5": 0.35, "a6": 0.35}   # G1: must shrink to ≤ 0.35× KiB
GATE_PER_STOCK_FLAT = {"a1": 1.10, "a4": 1.10}                  # G1: must not grow > 1.10× KiB
GATE_REREAD_CASES = ("b3", "b4", "b5", "b6", "b7", "b9", "c1", "c2")   # G2 small-cache re-reads


def evaluate_gates(reads, writes, exports, vn) -> dict[str, list[str]]:
    """Planner gates (docs/43 §6.1). Returns {variant: [failure, ...]}; empty list = pass.

    G1 per-stock: a2/a5/a6 distinct KiB ≤ 0.35× OLD; a1/a4 ≤ 1.10× OLD.
    G2 every case: KiB ≤ 1.10×OLD + 256 KiB AND median ms ≤ max(1.25×OLD, OLD+50 ms);
       b3 b4 b5 b6 b7 b9 c1 c2: re-read KiB (2 MB cache) ≤ 1.5× OLD.
    G4 export (if --export): seconds ≤ 0.60× OLD; each `export timing:` segment except
       write ≤ 1.25× OLD (segments under 1 s on both sides are ignored as noise).
    G5 writes (if --write): every step ms ≤ 2.0× OLD.
    """
    fails: dict[str, list[str]] = {n: [] for n in vn}
    for r in reads:
        o, cid = r["old"], r["id"]
        for n in vn:
            m = r["variants"][n]
            if o["kib"] is not None and m["kib"] is not None:
                if cid in GATE_PER_STOCK_SHRINK and m["kib"] > GATE_PER_STOCK_SHRINK[cid] * o["kib"]:
                    fails[n].append(f"G1 {cid}: {m['kib']:,.0f} KiB > {GATE_PER_STOCK_SHRINK[cid]}× {o['kib']:,.0f}")
                if cid in GATE_PER_STOCK_FLAT and m["kib"] > GATE_PER_STOCK_FLAT[cid] * o["kib"]:
                    fails[n].append(f"G1 {cid}: {m['kib']:,.0f} KiB > {GATE_PER_STOCK_FLAT[cid]}× {o['kib']:,.0f}")
                if m["kib"] > 1.10 * o["kib"] + 256:
                    fails[n].append(f"G2 {cid}: {m['kib']:,.0f} KiB > 1.10×{o['kib']:,.0f}+256")
            if m["median"] > max(1.25 * o["median"], o["median"] + 50):
                fails[n].append(f"G2 {cid}: {m['median']:.1f} ms > max(1.25×, +50 ms) of {o['median']:.1f}")
            if (cid in GATE_REREAD_CASES and o["reread_kib"] is not None and m["reread_kib"] is not None
                    and m["reread_kib"] > 1.5 * o["reread_kib"]):
                fails[n].append(f"G2 {cid}: re-read {m['reread_kib']:,.0f} KiB > 1.5× {o['reread_kib']:,.0f}")
    if exports.get("old"):
        eo = exports["old"]
        for n in vn:
            en = exports.get(n)
            if not en:
                fails[n].append("G4: export failed")
                continue
            if en["seconds"] > 0.60 * eo["seconds"]:
                fails[n].append(f"G4: export {en['seconds']:.1f}s > 0.60× {eo['seconds']:.1f}s")
            for seg, v_old in eo.get("timing", {}).items():
                v_new = en.get("timing", {}).get(seg)
                if seg == "write" or v_new is None or max(v_old, v_new) < 1.0:
                    continue
                if v_new > 1.25 * v_old:
                    fails[n].append(f"G4: export segment {seg} {v_new:.1f}s > 1.25× {v_old:.1f}s")
    if writes.get("old"):
        wo = writes["old"]
        for n in vn:
            for step, v in writes.get(n, {}).items():
                if v["ms"] > 2.0 * wo[step]["ms"]:
                    fails[n].append(f"G5 {step}: {v['ms']:.0f} ms > 2.0× {wo[step]['ms']:.0f}")
    return fails


def fmt(v, spec=".1f"):
    return "—" if v is None else format(v, spec)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("old", type=Path)
    ap.add_argument("--variant", action="append", default=[], metavar="NAME=PATH",
                    help="a converted DB to compare (repeatable)")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--cache-kib", type=int, default=2000, help="PRAGMA cache_size in KiB (default 2000)")
    ap.add_argument("--random", type=int, default=35, help="random stocks added to the fixed five")
    ap.add_argument("--seed", type=int, default=43)
    ap.add_argument("--cases", default="", help="comma-separated case ids (default: all)")
    ap.add_argument("--write", action="store_true", help="case d: temp copies + upserts")
    ap.add_argument("--write-days", type=int, default=5)
    ap.add_argument("--tmp", type=Path, help="scratch dir for case d copies")
    ap.add_argument("--export", action="store_true", help="case e: full export-json per DB")
    ap.add_argument("--work", type=Path, help="scratch dir for case e exports (must be empty)")
    ap.add_argument("--json", type=Path, help="also write all numbers here")
    a = ap.parse_args(argv)
    variants = []
    for v in a.variant:
        name, _, path = v.partition("=")
        variants.append((name, Path(path)))
    if not variants:
        raise SystemExit("give at least one --variant NAME=PATH")

    global PAGES
    PAGES = PageReads()
    ctx = context(a.old, a.random, a.seed)
    only = {c.strip() for c in a.cases.split(",") if c.strip()} or None
    cases = build_cases(ctx, only)
    print(f"as_of={ctx['params']['d']} stocks={len(ctx['stocks'])} cache={a.cache_kib}KiB runs={a.runs}")
    print(f"OLD {a.old.stat().st_size:,} B; " + "; ".join(f"{n} {p.stat().st_size:,} B" for n, p in variants))
    reads = bench_reads(a.old, variants, cases, a.runs, a.cache_kib)

    writes = {}
    if a.write:
        tmp = a.tmp or Path(tempfile.mkdtemp(prefix="bench_branch_raw_"))
        tmp.mkdir(parents=True, exist_ok=True)
        writes = bench_write([("old", a.old)] + variants, tmp, a.write_days)

    exports = {}
    if a.export:
        if not a.work:
            raise SystemExit("--export needs --work")
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import export_parity as ep
        for name, path in [("old", a.old)] + variants:
            sub = a.work / f"bench_{re.sub(r'[^A-Za-z0-9]', '_', name)}"
            exports[name] = ep.wait(ep.run_export(path, sub, sys.executable), name, sub)

    # ── report ───────────────────────────────────────────────────────────
    vn = [n for n, _ in variants]
    print("\n| 案例 | OLD ms | OLD KiB | " + " | ".join(f"{n} ms (×) | {n} KiB (×)" for n in vn) + " | 列數 |")
    print("|---|---:|---:|" + "---:|---:|" * len(vn) + "---:|")
    for r in reads:
        o = r["old"]
        cells = []
        for n in vn:
            m = r["variants"][n]
            flag = " ⚠" if max(m["time_ratio"], m["bytes_ratio"] or 0) > 2 else ""
            cells.append(f"{m['median']:.1f} ({m['time_ratio']:.2f}){flag} | "
                         f"{fmt(m['kib'], ',.0f')} ({fmt(m['bytes_ratio'], '.2f')})")
        print(f"| {r['id']} {r['case']} | {o['median']:.1f} | {fmt(o['kib'], ',.0f')} | "
              + " | ".join(cells) + f" | {o['rows']:,} |")

    print("\n重讀位元組(2 MB 快取,含被擠出後重抓;只報告):")
    def rr(a, b):
        return ratio(a, b) if a is not None and b is not None else None

    for r in reads:
        o = r["old"]
        print(f"  {r['id']}: OLD {fmt(o['reread_kib'], ',.0f')} KiB; " + "; ".join(
            f"{n} {fmt(r['variants'][n]['reread_kib'], ',.0f')} "
            f"({fmt(rr(o['reread_kib'], r['variants'][n]['reread_kib']), '.2f')}×)" for n in vn))

    print("\n回歸(>2×)與提示重試:")
    verdict = {}
    for n in vn:
        blockers = []
        for r in reads:
            m = r["variants"][n]
            if max(m["time_ratio"], m["bytes_ratio"] or 0) <= 2:
                continue
            fixed = m.get("fixed_by")
            tried = ", ".join(
                f"{h['hint']}→{h['time_ratio']:.2f}×/{fmt(h.get('bytes_ratio'), '.2f')}×" if "error" not in h
                else f"{h['hint']}→error" for h in m.get("hints", []))
            print(f"  [{n}] {r['id']} {r['case']}: {m['time_ratio']:.2f}× ms, "
                  f"{fmt(m['bytes_ratio'], '.2f')}× bytes; 提示: {tried or '無可用'}; "
                  f"{'可用 ' + fixed + ' 修(需改程式)' if fixed else '無法以提示修正'}")
            if not fixed:
                blockers.append(r["id"])
        verdict[n] = blockers
    for n in vn:
        print(f"  結論 {n}: " + ("可上線(無未解回歸)" if not verdict[n]
                                 else f"不可上線:{', '.join(verdict[n])} 回歸 >2× 且提示修不好"))

    print("\n查詢計畫:")
    for r in reads:
        print(f"- {r['id']} OLD: {r['old']['plan']}")
        for n in vn:
            print(f"  {' ' * len(r['id'])} {n}: {r['variants'][n]['plan']}")

    if writes:
        print("\n| 寫入步驟 | 列數 | " + " | ".join(f"{n} ms | {n} 檔案增長" for n in writes) + " |")
        print("|---|---:|" + "---:|---:|" * len(writes))
        first = next(iter(writes.values()))
        for step in first:
            cells = " | ".join(f"{w[step]['ms']:.0f} | +{w[step]['growth'] / 1048576:.1f} MiB"
                               for w in writes.values())
            print(f"| {step} | {first[step]['rows']:,} | {cells} |")
    if exports:
        print("\nexport-json(PC 單次計時雜訊大,僅供參考;VPS 以 radar-cron.log 為準):")
        for n, info in exports.items():
            if info:
                print(f"  {n}: {info['seconds']:.1f}s, {info['stocks']} 檔")

    gate_fails = evaluate_gates(reads, writes, exports, vn)
    print("\n閘門(G1 逐檔、G2 每案例、G4 匯出、G5 寫入;docs/43 §6.1):")
    for n in vn:
        if gate_fails[n]:
            print(f"  {n}: FAIL ({len(gate_fails[n])})")
            for f in gate_fails[n]:
                print(f"     - {f}")
        else:
            print(f"  {n}: PASS"
                  + ("" if exports else "(未跑 --export,G4 未檢)") + ("" if writes else "(未跑 --write,G5 未檢)"))

    if a.json:
        a.json.write_text(json.dumps({"context": {k: v for k, v in ctx.items() if k != "pocket"},
                                      "reads": reads, "writes": writes, "exports": exports,
                                      "verdict": verdict, "gates": gate_fails},
                                     ensure_ascii=False, indent=1),
                          encoding="utf-8")
        print(f"\nnumbers: {a.json}")
    print("注意:ms 為 PC(OS 快取未清)CPU 為主的時間;VPS 冷快取以 KiB 欄為準。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
