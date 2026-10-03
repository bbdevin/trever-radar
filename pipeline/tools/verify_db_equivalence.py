"""Prove that a converted radar.db holds exactly the data of the original.

    python pipeline/tools/verify_db_equivalence.py OLD.db NEW.db \
        [--tables branch_trades_raw,daily_prices] [--expect-page-size 4096] [--skip-integrity]
    python pipeline/tools/verify_db_equivalence.py NEW.db --single     # VPS, after the swap

Both files are opened read-only and immutable (neither is ever written); a
non-empty -wal next to either is refused.  Checks, all of which must pass:

  1. PRAGMA integrity_check = ok on NEW (and quick_check on OLD);
     foreign_key_check results identical.
  2. header/pragmas: encoding, auto_vacuum, user_version, application_id
     identical; page_size == --expect-page-size (default: OLD's); NEW is in WAL
     mode (header bytes 18/19 = 2).
  3. schema: every table / index / view / trigger identical (name, type, table,
     SQL text) except the *expected* differences, which must be exactly:
       - each converted table: NEW SQL == OLD SQL + " WITHOUT ROWID"
       - ix_branch_trades_raw_stock_cover: in OLD only
       - ix_branch_trades_raw_date: in OLD only; ix_branch_trades_raw_date_cover: in NEW
         only, with exactly the DDL radar/schema.py emits (unless --no-cover)
       - sqlite_autoindex_<converted table>_1: may differ (it is the PK b-tree)
       - sqlite_stat1/sqlite_stat4: present only in NEW is allowed (--analyze);
         if both have it, rows for unconverted tables must match.
  4. data: for EVERY table, identical row count and identical content: a
     streaming SHA-256 over all rows in PRIMARY KEY order (rowid order for a
     table without a declared PK), each row as its type-exact repr, so 5 vs
     5.0 vs '5' differ.  Rowid tables other than the converted ones hash the
     rowid too, proving their implicit order is unchanged.  sqlite_sequence is
     compared as well.  Memory stays flat (fetchmany) on 32M rows.
  5. query plans on NEW: the per-stock reads seek the PRIMARY KEY.

Exit code 0 = PASS, 1 = FAIL.  Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
import time
from pathlib import Path

DEFAULT_TABLES = ("branch_trades_raw", "daily_prices")
try:   # one definition of the layout, shared with the converter
    from convert_branch_raw_without_rowid import layout_changes
except ImportError:  # imported as tools.verify_db_equivalence
    from tools.convert_branch_raw_without_rowid import layout_changes

DATE_IDX = "ix_branch_trades_raw_date"
COVER_IDX = "ix_branch_trades_raw_date_cover"
D = "'2026-10-02'"

# (label, table it needs, cover (True: only with the cover index, False: only without,
#  None: always), sql, one of these must appear in NEW's plan, substrings that must not).
# A seek through a date index is acceptable when it binds stock_id too: on a
# WITHOUT ROWID table every secondary index ends with the PK columns.
PLAN_CHECKS = [
    ("compute-branch-stats per-stock read", "branch_trades_raw", None,
     "SELECT branch_name, date, net_lots, sell_lots, pct FROM branch_trades WHERE stock_id = '2330'",
     ("USING PRIMARY KEY (stock_id=?)",), ("SCAN r",)),
    ("stock JSON branch_history (json_export, needs buy_lots)", "branch_trades_raw", None,
     "SELECT r.date, d.branch_name, r.buy_lots, r.sell_lots, r.net_lots FROM branch_trades_raw r "
     "JOIN branch_dim d ON r.branch_id = d.id WHERE r.stock_id = '2330' "
     f"AND r.date >= date({D}, '-730 days') ORDER BY r.date DESC, r.branch_id DESC",
     ("USING PRIMARY KEY (stock_id=? AND date>?)",), ("SCAN r",)),
    ("stock JSON day branches (json_export)", "branch_trades_raw", None,
     "SELECT d.branch_name, r.buy_lots, r.sell_lots, r.net_lots, r.pct FROM branch_trades_raw r "
     f"JOIN branch_dim d ON r.branch_id = d.id WHERE r.stock_id = '2330' AND r.date = {D} "
     "ORDER BY r.net_lots DESC, r.branch_id",
     ("USING PRIMARY KEY (stock_id=? AND date=?)", "(date=? AND stock_id=?)"), ("SCAN r",)),
    ("import gate: stocks with rows on a date (importer.py:1359)", "branch_trades_raw", True,
     "SELECT COUNT(DISTINCT b.stock_id) FROM branch_trades_raw b "
     f"JOIN stocks s ON s.id = b.stock_id AND s.type = 'stock' WHERE b.date = {D}",
     (f"{COVER_IDX} (date=?", "USING PRIMARY KEY (stock_id=? AND date=?)"), ("SCAN b",)),
    ("import gate (no cover)", "branch_trades_raw", False,
     "SELECT COUNT(DISTINCT b.stock_id) FROM branch_trades_raw b "
     f"JOIN stocks s ON s.id = b.stock_id AND s.type = 'stock' WHERE b.date = {D}",
     (f"{DATE_IDX} (date=?", "USING PRIMARY KEY (stock_id=? AND date=?)"), ("SCAN b",)),
    ("b3 warrant day branches (json_export.py wb)", "branch_trades_raw", True,
     "SELECT stock_id, branch_name, buy_lots, sell_lots, net_lots FROM branch_trades "
     f"WHERE date = {D} AND LENGTH(stock_id) = 6 ORDER BY stock_id, branch_key",
     (f"COVERING INDEX {COVER_IDX}",), ("SCAN r",)),
    # b4/b7: the code's own SQL (radar/branch_source.py pins the covering index)
    ("b4 scoring 20-day window (scores.py)", "branch_trades_raw", True,
     "SELECT r.stock_id, r.date, d.branch_key, d.branch_name, r.buy_lots, r.sell_lots, r.net_lots, r.pct "
     f"FROM branch_trades_raw r INDEXED BY {COVER_IDX} JOIN branch_dim d ON r.branch_id = d.id "
     f"WHERE r.date >= '2026-09-04' AND r.date <= {D} AND LENGTH(r.stock_id) = 4",
     (f"COVERING INDEX {COVER_IDX}",), ("ix_branch_trades_raw_branch", "SCAN r")),
    ("b7 pocket 20-day window (pocket.py)", "branch_trades_raw", True,
     "SELECT r.stock_id, r.date, d.branch_name, r.net_lots "
     f"FROM branch_trades_raw r INDEXED BY {COVER_IDX} JOIN branch_dim d ON r.branch_id = d.id "
     f"WHERE r.date >= '2026-09-04' AND r.date <= {D} AND LENGTH(r.stock_id) = 4",
     (f"COVERING INDEX {COVER_IDX}",), ("ix_branch_trades_raw_branch", "SCAN r")),
    ("c1 tracked detail (json_export _export_tracked_branch_history)", "branch_trades_raw", True,
     "SELECT b.branch_name, b.date, b.stock_id, SUM(b.net_lots) AS net_lots, AVG(b.pct) AS pct "
     "FROM branch_trades b JOIN stocks s ON s.id = b.stock_id AND s.type IN ('stock', 'etf') "
     "WHERE b.branch_name IN ('A', 'B', 'C') "
     f"AND b.date >= date({D}, '-' || 120 || ' days') AND b.date <= {D} "
     "GROUP BY b.branch_name, b.date, b.stock_id ORDER BY b.branch_name, b.date, b.stock_id",
     ("SEARCH r",), ("SEARCH r USING INDEX ix_branch_trades_raw_branch",)),
    ("stock JSON candles (full history)", "daily_prices", None,
     "SELECT p.date, p.open, p.high, p.low, p.close, p.volume, p.turnover, p.adj_factor "
     "FROM daily_prices p WHERE p.stock_id = '2330' AND p.close IS NOT NULL ORDER BY p.date",
     ("USING PRIMARY KEY (stock_id=?)",), ("SCAN p",)),
    ("stock JSON candles (600 bars)", "daily_prices", None,
     "SELECT p.date, p.close FROM daily_prices p WHERE p.stock_id = '2330' "
     "AND p.close IS NOT NULL ORDER BY p.date DESC LIMIT 600",
     ("USING PRIMARY KEY (stock_id=?)",), ("SCAN p",)),
]


def run_plan_checks(r, conn, tables, cover: bool) -> None:
    for label, needs, only, sql, must, must_not in PLAN_CHECKS:
        if needs not in tables or (only is not None and only != cover):
            continue
        try:
            plan = " | ".join(x[3] for x in conn.execute("EXPLAIN QUERY PLAN " + sql))
        except sqlite3.OperationalError as exc:   # e.g. no such index on the wrong layout
            r.fail(f"plan [{label}]: {exc}")
            continue
        good = any(m in plan for m in must) and not any(m in plan for m in must_not)
        r.check(good, f"plan [{label}]: {plan}")


def ro(path: Path) -> sqlite3.Connection:
    wal = Path(str(path) + "-wal")
    if wal.exists() and wal.stat().st_size > 0:
        raise SystemExit(f"refusing: {wal} is not empty; checkpoint(TRUNCATE) the DB first")
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    conn.execute("PRAGMA cache_size = -262144")
    return conn


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def norm(sql: str | None) -> str | None:
    return None if sql is None else " ".join(sql.split())


class Report:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.t0 = time.monotonic()

    def _p(self, tag: str, msg: str) -> None:
        print(f"[{time.monotonic() - self.t0:7.1f}s] {tag:5s} {msg}", flush=True)

    def ok(self, msg: str) -> None:
        self._p("PASS", msg)

    def fail(self, msg: str) -> None:
        self.fails.append(msg)
        self._p("FAIL", msg)

    def info(self, msg: str) -> None:
        self._p("", msg)

    def check(self, cond: bool, msg: str) -> None:
        (self.ok if cond else self.fail)(msg)


def header_journal(path: Path) -> str:
    with path.open("rb") as f:
        h = f.read(20)
    return "wal" if h[18] == 2 and h[19] == 2 else "rollback"


def has_rowid(conn: sqlite3.Connection, table: str) -> bool:
    try:
        conn.execute(f"SELECT rowid FROM {q(table)} LIMIT 0")
        return True
    except sqlite3.OperationalError:
        return False


def pk_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    cols = [r for r in conn.execute(f"PRAGMA table_xinfo({q(table)})") if r[6] == 0]
    return [c[1] for c in sorted((c for c in cols if c[5] > 0), key=lambda c: c[5])]


def table_digest(conn: sqlite3.Connection, table: str, with_rowid: bool) -> tuple[int, str]:
    cols = ", ".join(q(r[1]) for r in conn.execute(f"PRAGMA table_xinfo({q(table)})") if r[6] == 0)
    pk = pk_columns(conn, table)
    order = ", ".join(q(c) for c in pk) if pk else "rowid"
    sel = f"SELECT {'rowid, ' if with_rowid else ''}{cols} FROM {q(table)} ORDER BY {order}"
    for factory in (str, lambda b: b.decode("utf-8", "surrogateescape")):
        conn.text_factory = factory
        try:
            n, h = 0, hashlib.sha256()
            cur = conn.execute(sel)
            while True:
                rows = cur.fetchmany(20000)
                if not rows:
                    break
                for row in rows:
                    h.update(repr(row).encode("utf-8", "surrogatepass"))
                    h.update(b"\n")
                n += len(rows)
            return n, h.hexdigest()
        except sqlite3.OperationalError as exc:
            if "decode" not in str(exc).lower():
                raise
        finally:
            conn.text_factory = str
    raise RuntimeError("unreachable")


def master(conn: sqlite3.Connection) -> dict[str, tuple]:
    return {r[1]: (r[0], r[2], norm(r[3])) for r in conn.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master")}


def verify(old_path: Path, new_path: Path, *, tables: tuple[str, ...] = DEFAULT_TABLES,
           expect_page_size: int | None = None, integrity: bool = True, cover: bool = True) -> bool:
    drop_names, added = layout_changes(tables, cover)
    added_ddl = {n: norm(d) for n, d in added}
    r = Report()
    old, new = ro(old_path), ro(new_path)
    r.info(f"OLD {old_path} {old_path.stat().st_size:,} bytes")
    r.info(f"NEW {new_path} {new_path.stat().st_size:,} bytes; converted tables {list(tables)}")

    # 1) integrity
    if integrity:
        res = [x[0] for x in new.execute("PRAGMA integrity_check")]
        r.check(res == ["ok"], f"integrity_check NEW = {res[:5]}")
        res = [x[0] for x in old.execute("PRAGMA quick_check")]
        r.check(res == ["ok"], f"quick_check OLD = {res[:5]}")
    else:
        r.info("integrity_check skipped (--skip-integrity)")
    fk_old = sorted(old.execute("PRAGMA foreign_key_check").fetchall())
    fk_new = sorted(new.execute("PRAGMA foreign_key_check").fetchall())
    r.check(fk_old == fk_new, f"foreign_key_check identical ({len(fk_new)} rows)")

    # 2) pragmas / header
    for p in ("encoding", "auto_vacuum", "user_version", "application_id"):
        a, b = old.execute(f"PRAGMA {p}").fetchone()[0], new.execute(f"PRAGMA {p}").fetchone()[0]
        r.check(a == b, f"PRAGMA {p}: OLD={a} NEW={b}")
    ps_old, ps_new = old.execute("PRAGMA page_size").fetchone()[0], new.execute("PRAGMA page_size").fetchone()[0]
    want = expect_page_size or ps_old
    r.check(ps_new == want, f"PRAGMA page_size: OLD={ps_old} NEW={ps_new} (expected {want})")
    r.check(header_journal(new_path) == "wal",
            f"NEW journal mode in header = {header_journal(new_path)} (OLD {header_journal(old_path)})")
    r.info(f"NEW freelist_count = {new.execute('PRAGMA freelist_count').fetchone()[0]}; "
           f"OLD freelist_count = {old.execute('PRAGMA freelist_count').fetchone()[0]}")

    # 3) schema
    mo, mn = master(old), master(new)
    names = sorted(set(mo) | set(mn))
    autoindexes = {f"sqlite_autoindex_{t}_1" for t in tables}
    unexpected = []
    for name in names:
        a, b = mo.get(name), mn.get(name)
        if name in tables:
            r.check(a is not None and b is not None and b[2] == norm(a[2].rstrip().rstrip(";") + " WITHOUT ROWID"),
                    f"{name}: NEW DDL is OLD DDL + WITHOUT ROWID")
            r.check(has_rowid(old, name) and not has_rowid(new, name),
                    f"{name}: OLD is a rowid table, NEW is WITHOUT ROWID")
        elif name in drop_names:
            r.check(b is None, f"{name}: absent in NEW (OLD {'has' if a else 'lacks'} it)")
        elif name in added_ddl:
            r.check(a is None and b is not None and b[0] == "index" and b[2] == added_ddl[name],
                    f"{name}: only in NEW, with exactly the schema.py DDL (NEW={b})")
        elif name in autoindexes or name.startswith("sqlite_stat"):
            continue
        elif a != b:
            unexpected.append((name, a, b))
    for name, a, b in unexpected:
        r.fail(f"schema differs for {name}: OLD={a} NEW={b}")
    if not unexpected:
        r.ok(f"schema identical for all other objects ({len(names)} names compared)")

    # 4) data
    data_tables = sorted(n for n, v in mo.items() if v[0] == "table" and not n.startswith("sqlite_"))
    extra = sorted(n for n, v in mn.items() if v[0] == "table" and not n.startswith("sqlite_")
                   and n not in mo)
    for t in extra:
        r.fail(f"table {t}: only in NEW")
    for t in data_tables:
        t0 = time.monotonic()
        if t not in mn:
            r.fail(f"table {t}: missing in NEW")
            continue
        with_rowid = t not in tables and has_rowid(old, t) and has_rowid(new, t)
        n_old, h_old = table_digest(old, t, with_rowid)
        n_new, h_new = table_digest(new, t, with_rowid)
        r.check(n_old == n_new and h_old == h_new,
                f"table {t}: rows OLD={n_old:,} NEW={n_new:,} sha256 "
                f"{'equal ' + h_new[:16] if h_old == h_new else 'DIFFERENT'}"
                f"{' (incl. rowid)' if with_rowid else ' (PK order)'} [{time.monotonic() - t0:.1f}s]")
    if "sqlite_sequence" in mo or "sqlite_sequence" in mn:
        a = sorted(old.execute("SELECT * FROM sqlite_sequence")) if "sqlite_sequence" in mo else None
        b = sorted(new.execute("SELECT * FROM sqlite_sequence")) if "sqlite_sequence" in mn else None
        r.check(a == b, "sqlite_sequence identical")
    for st in ("sqlite_stat1", "sqlite_stat4"):
        if st in mn and st not in mo:
            r.info(f"{st}: only in NEW (ANALYZE variant) — planner statistics, not data")
        elif st in mo and st not in mn:
            r.fail(f"{st}: in OLD but missing in NEW")
        elif st in mo:
            ph = ", ".join("?" for _ in tables)
            a = sorted(old.execute(f"SELECT * FROM {st} WHERE tbl NOT IN ({ph})", tables))
            b = sorted(new.execute(f"SELECT * FROM {st} WHERE tbl NOT IN ({ph})", tables))
            r.check(a == b, f"{st} (unconverted tables) identical")

    for name in added_ddl:
        if name not in mn:
            r.fail(f"{name}: missing in NEW")

    # 5) plans on NEW
    run_plan_checks(r, new, tables, cover)

    old.close()
    new.close()
    print()
    if r.fails:
        print(f"RESULT: FAIL ({len(r.fails)} check(s) failed)")
        for f in r.fails:
            print(f"  - {f}")
        return False
    print("RESULT: PASS — NEW holds exactly OLD's data; only the expected layout differences.")
    return True


def check_single(path: Path, *, tables: tuple[str, ...] = DEFAULT_TABLES, integrity: bool = True,
                 cover: bool = True, require_stats: bool = True) -> bool:
    """Post-swap check on the VPS, where only the new file exists."""
    drop_names, added = layout_changes(tables, cover)
    r = Report()
    db = ro(path)
    r.info(f"DB {path} {path.stat().st_size:,} bytes")
    if integrity:
        res = [x[0] for x in db.execute("PRAGMA integrity_check")]
        r.check(res == ["ok"], f"integrity_check = {res[:5]}")
    res = [x[0] for x in db.execute("PRAGMA quick_check")]
    r.check(res == ["ok"], f"quick_check = {res[:5]}")
    r.check(header_journal(path) == "wal", f"journal mode in header = {header_journal(path)}")
    for t in tables:
        r.check(not has_rowid(db, t), f"{t} is WITHOUT ROWID")
        r.info(f"{t}: {db.execute(f'SELECT COUNT(*) FROM {q(t)}').fetchone()[0]:,} rows")
    names = {x[0] for x in db.execute("SELECT name FROM sqlite_master")}
    for idx in drop_names:
        r.check(idx not in names, f"{idx} absent")
    for idx, ddl in added:
        got = db.execute("SELECT sql FROM sqlite_master WHERE name = ?", (idx,)).fetchone()
        r.check(got is not None and norm(got[0]) == norm(ddl), f"{idx} present with the schema.py DDL")
    if require_stats:
        have = set()
        if "sqlite_stat1" in names:
            have = {x[0] for x in db.execute("SELECT DISTINCT tbl FROM sqlite_stat1")}
        r.check(all(t in have for t in tables),
                f"sqlite_stat1 covers {list(tables)} (has {sorted(have & set(tables))}) — production uses --analyze")
    run_plan_checks(r, db, tables, cover)
    db.close()
    print("\nRESULT: " + ("FAIL" if r.fails else "PASS"))
    return not r.fails


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("old", type=Path)
    ap.add_argument("new", type=Path, nargs="?",
                    help="omit together with --single to check one converted DB (VPS post-swap)")
    ap.add_argument("--single", action="store_true",
                    help="only OLD is given and it is the *converted* DB: integrity, WAL, "
                         "WITHOUT ROWID, dropped index, query plans")
    ap.add_argument("--tables", default=",".join(DEFAULT_TABLES))
    ap.add_argument("--expect-page-size", type=int, default=None,
                    help="page size NEW must have (default: same as OLD)")
    ap.add_argument("--skip-integrity", action="store_true",
                    help="skip integrity_check/quick_check (only for quick re-runs)")
    ap.add_argument("--no-cover", action="store_true",
                    help="NEW was converted with --no-cover (comparison variant)")
    ap.add_argument("--no-stats", action="store_true", help="with --single: do not require sqlite_stat1")
    a = ap.parse_args(argv)
    tables = tuple(t.strip() for t in a.tables.split(",") if t.strip())
    if a.single:
        return 0 if check_single(a.old, tables=tables, integrity=not a.skip_integrity,
                                 cover=not a.no_cover, require_stats=not a.no_stats) else 1
    if a.new is None:
        raise SystemExit("give OLD NEW, or one DB with --single")
    ok = verify(a.old, a.new, tables=tables, expect_page_size=a.expect_page_size,
                integrity=not a.skip_integrity, cover=not a.no_cover)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
