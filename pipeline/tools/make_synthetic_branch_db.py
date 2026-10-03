"""Build a synthetic radar.db in the *production* (pre-conversion) layout.

Rehearsal fixture for docs/43: the real schema from radar.schema + radar.db
migrations, but branch_trades_raw rebuilt the way production has it today —
a rowid table with the PK autoindex, ix_branch_trades_raw_date,
ix_branch_trades_raw_branch and the 1.24 GB cover index
ix_branch_trades_raw_stock_cover — and rows inserted date by date with the
branches of each stock in source (not branch_id) order, like the importer.

    cd pipeline
    python tools/make_synthetic_branch_db.py OUT.db [--stocks 60 --days 120 --branches 40]

Needs the pipeline venv (SQLAlchemy) because it uses radar.db.init_db().
"""
from __future__ import annotations

import argparse
import random
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SAMPLE_STOCKS = ["2330", "3105", "4967", "6488", "8299"]
COVER_INDEX_SQL = ("CREATE INDEX ix_branch_trades_raw_stock_cover ON branch_trades_raw "
                   "(stock_id, date, branch_id, net_lots, sell_lots, pct)")


def trading_days(n: int, end: date = date(2026, 10, 2)) -> list[str]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return sorted(out)


def init_schema(path: Path) -> None:
    import radar.config as config
    import radar.db as db
    old = (config.DB_URL, config.DATA_DIR, db._engine)
    config.DB_URL = "sqlite:///" + path.resolve().as_posix()
    config.DATA_DIR = path.resolve().parent
    db._engine = None
    try:
        db.init_db()
    finally:
        if db._engine is not None:
            db._engine.dispose()
        config.DB_URL, config.DATA_DIR, db._engine = old


ROWID_TABLES = ("branch_trades_raw", "daily_prices")


def to_production_layout(conn: sqlite3.Connection) -> None:
    """Rebuild the (empty) converted tables as rowid tables, plus the cover index."""
    for table in ROWID_TABLES:
        ddl = conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (table,)).fetchone()[0]
        idx = [r[0] for r in conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
            (table,))]
        rowid_ddl = ddl.rstrip()
        if rowid_ddl.upper().endswith("WITHOUT ROWID"):
            rowid_ddl = rowid_ddl[: -len("WITHOUT ROWID")].rstrip()
        conn.execute(f"DROP TABLE {table}")
        conn.execute(rowid_ddl)
        for sql in idx:
            if "ix_branch_trades_raw_date_cover" in sql:   # new layout; production has (date)
                sql = "CREATE INDEX ix_branch_trades_raw_date ON branch_trades_raw (date)"
            conn.execute(sql)
    conn.execute(COVER_INDEX_SQL)


def build(out: Path, *, stocks: int = 60, days: int = 120, branches: int = 40,
          warrants_per_stock: int = 3, seed: int = 20261003) -> dict:
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out}")
    rnd = random.Random(seed)
    init_schema(out)
    conn = sqlite3.connect(out, isolation_level=None)
    conn.execute("BEGIN")
    to_production_layout(conn)

    sids = list(SAMPLE_STOCKS)
    n = 1101
    while len(sids) < stocks:
        if str(n) not in sids:
            sids.append(str(n))
        n += 7
    dates = trading_days(days)
    conn.executemany(
        "INSERT INTO stocks (id, name, market, type, industry, is_active) VALUES (?,?,?,?,?,1)",
        [(s, f"股{s}", "twse" if i % 2 else "tpex", "stock", f"ind{i % 5}") for i, s in enumerate(sids)])

    prices, insti, margins = [], [], []
    last_close = {}
    for s in sids:
        close = rnd.uniform(20, 900)
        for d in dates:
            close = max(1.0, close * (1 + rnd.uniform(-0.05, 0.05)))
            hi, lo = close * 1.02, close * 0.98
            vol = rnd.randint(200, 50000) * 1000
            prices.append((s, d, round(close * 0.995, 2), round(hi, 2), round(lo, 2),
                           round(close, 2), 1.0, vol, int(vol * close), rnd.randint(100, 9000)))
            insti.append((s, d, *(rnd.randint(-900, 900) * 1000 for _ in range(3)), 0))
            margins.append((s, d, rnd.randint(0, 20000), rnd.randint(0, 20000), 50000,
                            rnd.randint(0, 900), rnd.randint(0, 900), rnd.randint(0, 50),
                            rnd.randint(0, 3000), rnd.randint(0, 3000), rnd.randint(0, 90),
                            rnd.randint(0, 90), rnd.randint(0, 9)))
        last_close[s] = close
    # Production appends one trading day at a time — TWSE quotes (14:10) before
    # TPEx (15:00), each in code order — so rowid order is date-major, not stock-major.
    market_of = {s: ("twse" if i % 2 else "tpex") for i, s in enumerate(sids)}
    day_major = lambda r: (r[1], market_of[r[0]] != "twse", r[0])  # noqa: E731
    prices.sort(key=day_major)
    insti.sort(key=day_major)
    margins.sort(key=day_major)
    conn.executemany("INSERT INTO daily_prices (stock_id, date, open, high, low, close, adj_factor, "
                     "volume, turnover, transactions) VALUES (?,?,?,?,?,?,?,?,?,?)", prices)
    conn.executemany("INSERT INTO daily_institutional (stock_id, date, foreign_net, trust_net, "
                     "dealer_net, total_net) VALUES (?,?,?,?,?,?)", insti)
    conn.executemany("INSERT INTO daily_margins (stock_id, date, margin_balance, margin_prev, "
                     "margin_limit, margin_buy, margin_sell, margin_repay, short_balance, short_prev, "
                     "short_buy, short_sell, short_repay) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", margins)

    wids = []
    for i, s in enumerate(sids):
        for k in range(warrants_per_stock):
            wid = f"{(i * warrants_per_stock + k) % 99999 + 30000:06d}"
            wids.append((wid, s, "call" if k % 2 == 0 else "put"))
    conn.executemany(
        "INSERT INTO warrants (id, name, market, kind, stock_id, strike, exercise_ratio, maturity_date, issuer) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        [(w, f"權{w}", "twse", kind, s, 100.0, 0.1, "2027-06-30", "元大") for w, s, kind in wids])
    wd, wsd = [], {}
    for w, s, kind in wids:
        for d in dates:
            close = round(rnd.uniform(0.2, 5), 2)
            v = rnd.randint(0, 500) * 1000
            wd.append((w, d, close, v, int(v * close), rnd.randint(0, 99)))
            agg = wsd.setdefault((s, d), [0, 0, 0, 0, 0, 0])
            off = 0 if kind == "call" else 3
            agg[off] += int(v * close); agg[off + 1] += v; agg[off + 2] += 1 if v else 0
    conn.executemany("INSERT INTO warrant_daily (warrant_id, date, close, volume, turnover, transactions) "
                     "VALUES (?,?,?,?,?,?)", wd)
    conn.executemany("INSERT INTO warrant_stock_daily (stock_id, date, call_turnover, call_volume, "
                     "call_count, put_turnover, put_volume, put_count) VALUES (?,?,?,?,?,?,?,?)",
                     [(s, d, *v) for (s, d), v in wsd.items()])

    brokers = ["凱基", "元大", "富邦", "群益金鼎", "摩根大通", "美林", "永豐金", "國泰"]
    dim = []
    for b in range(1, branches + 1):
        broker = brokers[b % len(brokers)]
        dim.append((b, f"{9200 + b}{b:04d}", f"{9200 + b}", f"{broker}-分{b}"))
    # Same branch NAME under a second branch_key (other source page / renamed and
    # merged by canonical_name): every 8th branch gets an alias key, and below the
    # alias sometimes trades the same stock on the same day — the case whose
    # handling must not depend on row order (docs/43 §1).
    alias_of = {}
    for b in range(1, branches + 1, 8):
        alias_id = branches + 1 + len(alias_of)
        alias_of[b] = alias_id
        name = next(n for i, _k, _br, n in dim if i == b)
        dim.append((alias_id, f"A{alias_id:04d}{b:04d}", f"{9200 + b}", name))
    # branch_dim ids are assigned in first-seen order in production, so shuffle them
    rnd.shuffle(dim)
    conn.executemany("INSERT INTO branch_dim (id, branch_key, broker_id, branch_name) VALUES (?,?,?,?)", dim)
    conn.executemany("INSERT INTO tracked_branches (branch_name, source, note, added_at) VALUES (?,?,?,?)",
                     [(name, "manual" if i % 3 else "auto", None, "2026-09-01") for i, name in
                      enumerate(dict.fromkeys(dim[i][3] for i in range(0, len(dim), 4)))])

    raw = 0
    for d in dates:                      # append date by date, like the daily import
        day_rows = []
        for s in sids + [w for w, _s, _k in wids]:
            k = min(branches, rnd.randint(3, 15) if len(s) == 4 else rnd.randint(0, 4))
            for b in rnd.sample(range(1, branches + 1), k):   # source order, not branch_id order
                buy = rnd.choice([0, 0, 1, 2, 5, 10, 20, 50, 120, 300])
                sell = rnd.choice([0, 0, 1, 2, 5, 10, 20, 50, 120, 300])
                row = (s, d, b, buy, sell, buy - sell,
                       round(rnd.uniform(0, 8), 2), "fubon" if len(s) == 4 else "moneydj")
                if b in alias_of and rnd.random() < 0.5:
                    a_buy, a_sell = rnd.choice([0, 1, 5, 50]), rnd.choice([0, 2, 20])
                    alias = (s, d, alias_of[b], a_buy, a_sell, a_buy - a_sell,
                             round(rnd.uniform(0, 3), 2), "moneydj")
                    day_rows.extend([row, alias] if rnd.random() < 0.5 else [alias, row])
                else:
                    day_rows.append(row)
        conn.executemany("INSERT INTO branch_trades_raw (stock_id, date, branch_id, buy_lots, sell_lots, "
                         "net_lots, pct, source) VALUES (?,?,?,?,?,?,?,?)", day_rows)
        raw += len(day_rows)

    d = dates[-1]
    conn.executemany(
        "INSERT INTO daily_scores (stock_id, date, branch_score, warrant_score, tech_score, inst_score, "
        "risk_penalty, final, reasons, risks) VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(s, d, rnd.randint(0, 40), rnd.randint(0, 30), rnd.randint(0, 30), rnd.randint(0, 20), 0,
          rnd.randint(30, 95), "[]", "[]") for s in sids])
    conn.executemany(
        "INSERT INTO import_logs (run_at, source, dataset, date, rows, status) VALUES (?,?,?,?,?,?)",
        [(f"{d}T18:00:00+08:00", "twse", ds, d, 100, "ok") for d in dates[-5:]
         for ds in ("quotes", "insti", "margin", "branches")])
    conn.execute("COMMIT")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    return {"stocks": len(sids), "warrants": len(wids), "dates": len(dates), "branch_rows": raw}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out", type=Path)
    ap.add_argument("--stocks", type=int, default=60)
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--branches", type=int, default=40)
    ap.add_argument("--warrants-per-stock", type=int, default=3)
    ap.add_argument("--seed", type=int, default=20261003)
    a = ap.parse_args()
    info = build(a.out, stocks=a.stocks, days=a.days, branches=a.branches,
                 warrants_per_stock=a.warrants_per_stock, seed=a.seed)
    print(f"built {a.out}: {info}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
