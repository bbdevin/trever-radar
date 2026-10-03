"""Offline rebuild of radar.db with selected tables as WITHOUT ROWID tables.

docs/43_branch_raw_without_rowid_runbook.md is the procedure this belongs to.

    python pipeline/tools/convert_branch_raw_without_rowid.py SNAPSHOT.db OUT.db \
        [--tables branch_trades_raw,daily_prices] [--page-size 4096|8192] [--analyze] [--no-cover]

Production (docs/43): --page-size 4096 --analyze, cover on (the default):
ix_branch_trades_raw_date is replaced by ix_branch_trades_raw_date_cover.

* SNAPSHOT.db is opened read-only and immutable (it is never written).  It must
  be a checkpointed snapshot: a non-empty SNAPSHOT.db-wal next to it is refused,
  because an immutable open would silently ignore those frames.
* OUT.db must not exist.  The build happens in OUT.db.partial (a stale partial
  from an interrupted run is deleted and rebuilt from scratch); OUT.db only
  appears, via rename, after every step succeeded.
* Every object is recreated from its own DDL in sqlite_master, so column types,
  defaults, NOT NULL and constraint text are byte-for-byte the source's.  Each
  target table gets the same DDL with " WITHOUT ROWID" appended and is filled in
  PK order, one value of the first PK column at a time (progress is printed).
  The cover index ix_branch_trades_raw_stock_cover is not recreated; each
  target's PK autoindex disappears by construction (the table *is* the PK b-tree).
* Every other rowid table keeps its exact rowids, so its implicit order is unchanged.
* encoding / auto_vacuum / user_version / application_id come from the source;
  page_size is --page-size (default 4096 = production).  The result is in WAL
  mode, like production.  --analyze runs a full ANALYZE at the end (planner
  statistics; production has none today).

Standard library only (python3 + sqlite3), so it runs on Windows or the VPS.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

DEFAULT_TABLES = ("branch_trades_raw", "daily_prices")
DROPPED_INDEXES = ("ix_branch_trades_raw_stock_cover",)
# Final layout (Planner 2026-10-04): branch_trades_raw's plain (date) index is replaced
# by a covering, date-contiguous copy so date-sliced reads are index-only.  The DDL is
# byte-for-byte what SQLAlchemy emits for radar/schema.py (a test pins that).
COVER_DROPPED = {"branch_trades_raw": ("ix_branch_trades_raw_date",)}
COVER_ADDED = {"branch_trades_raw": (
    ("ix_branch_trades_raw_date_cover",
     "CREATE INDEX ix_branch_trades_raw_date_cover ON branch_trades_raw "
     "(date, stock_id, branch_id, buy_lots, sell_lots, net_lots, pct)"),
)}


def layout_changes(tables: tuple[str, ...], cover: bool) -> tuple[tuple[str, ...], list[tuple[str, str]]]:
    """(index names to drop, [(name, ddl) to add]) for this conversion."""
    dropped = list(DROPPED_INDEXES)
    added: list[tuple[str, str]] = []
    if cover:
        for t in tables:
            dropped += COVER_DROPPED.get(t, ())
            added += COVER_ADDED.get(t, ())
    return tuple(dropped), added
INTERNAL_COPY = ("sqlite_sequence", "sqlite_stat1")


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def ro_uri(path: Path) -> str:
    return path.resolve().as_uri() + "?mode=ro&immutable=1"


def refuse_unchecked_wal(path: Path) -> None:
    wal = Path(str(path) + "-wal")
    if wal.exists() and wal.stat().st_size > 0:
        raise SystemExit(
            f"refusing: {wal} is not empty ({wal.stat().st_size} bytes). The snapshot must be "
            "taken after PRAGMA wal_checkpoint(TRUNCATE); an immutable read would ignore those frames.")


def fmt_bytes(n: int) -> str:
    return f"{n / 1024 ** 3:.2f} GiB ({n:,} bytes)"


class Progress:
    def __init__(self) -> None:
        self.t0 = time.monotonic()

    def log(self, msg: str) -> None:
        print(f"[{time.monotonic() - self.t0:8.1f}s] {msg}", flush=True)


def table_columns(conn: sqlite3.Connection, schema: str, table: str) -> list[tuple]:
    # table_xinfo: hidden=0 normal, 1 hidden virtual-table col, 2/3 generated columns.
    return [r for r in conn.execute(f"PRAGMA {schema}.table_xinfo({q(table)})") if r[6] == 0]


def has_rowid(conn: sqlite3.Connection, schema: str, table: str) -> bool:
    try:
        conn.execute(f"SELECT rowid FROM {schema}.{q(table)} LIMIT 0")
        return True
    except sqlite3.OperationalError:
        return False


def rowid_alias(cols: list[tuple]) -> bool:
    pk = [c for c in cols if c[5] > 0]
    return len(pk) == 1 and (pk[0][2] or "").strip().upper() == "INTEGER"


def without_rowid_ddl(sql: str) -> str:
    return sql.rstrip().rstrip(";") + " WITHOUT ROWID"


def convert(src: Path, out: Path, *, tables: tuple[str, ...] = DEFAULT_TABLES,
            page_size: int = 4096, analyze: bool = False, vacuum: bool = True, cover: bool = True,
            progress: Progress | None = None) -> dict:
    p = progress or Progress()
    src, out = Path(src), Path(out)
    if not src.is_file():
        raise SystemExit(f"source not found: {src}")
    if out.exists():
        raise SystemExit(f"refusing to overwrite existing output: {out}")
    if page_size not in (512, 1024, 2048, 4096, 8192, 16384, 32768, 65536):
        raise SystemExit(f"invalid page size {page_size}")
    refuse_unchecked_wal(src)
    partial = Path(str(out) + ".partial")
    vac = Path(str(out) + ".vacuum")
    for stale in (partial, vac):
        for suffix in ("", "-journal", "-wal", "-shm"):
            f = Path(str(stale) + suffix)
            if f.exists():
                p.log(f"removing stale {f.name} from an interrupted run")
                f.unlink()

    p.log(f"source {src} = {fmt_bytes(src.stat().st_size)}")
    srcc = sqlite3.connect(ro_uri(src), uri=True)
    pragmas = {k: srcc.execute(f"PRAGMA {k}").fetchone()[0]
               for k in ("page_size", "encoding", "auto_vacuum", "user_version", "application_id",
                         "page_count", "freelist_count")}
    master = srcc.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY rowid").fetchall()
    srcc.close()
    p.log(f"source pragmas {pragmas}; target page_size {page_size}; tables {list(tables)}")

    by_name = {r[1]: r for r in master}
    for t in tables:
        if t not in by_name or by_name[t][0] != "table":
            raise SystemExit(f"source has no table {t}")
        sql = by_name[t][3].rstrip().rstrip(";")
        if sql.upper().replace(" ", "").endswith("WITHOUTROWID"):
            raise SystemExit(f"{t} is already WITHOUT ROWID; nothing to convert")
        if "PRIMARY KEY" not in sql.upper():
            raise SystemExit(f"{t} has no PRIMARY KEY clause; WITHOUT ROWID needs one")
    for r in master:
        if r[3] and r[3].lstrip().upper().startswith("CREATE VIRTUAL TABLE"):
            raise SystemExit(f"virtual table {r[1]} is not supported by this tool")

    all_tables = [r for r in master if r[0] == "table" and not r[1].startswith("sqlite_")]
    drop_names, added = layout_changes(tables, cover)
    for name, _ddl in added:
        if name in by_name:
            raise SystemExit(f"source already has {name}; refusing to convert twice")
    indexes = [r for r in master if r[0] == "index" and r[3] is not None
               and r[1] not in drop_names]
    views = [r for r in master if r[0] == "view"]
    triggers = [r for r in master if r[0] == "trigger"]
    internal = {r[1] for r in master if r[0] == "table" and r[1].startswith("sqlite_")}
    unknown_internal = internal - set(INTERNAL_COPY)
    if unknown_internal:
        p.log(f"WARNING: internal tables not copied (rebuilt by SQLite or unused): {sorted(unknown_internal)}")
    dropped = [r[1] for r in master if r[1] in drop_names]
    p.log(f"objects: {len(all_tables)} tables, {len(indexes)} indexes, {len(views)} views, "
          f"{len(triggers)} triggers; dropping {dropped or 'nothing'}; "
          f"adding {[n for n, _ in added] or 'nothing'}")

    dst = sqlite3.connect(partial.resolve().as_uri(), uri=True, isolation_level=None)
    dst.execute(f"PRAGMA page_size = {page_size}")
    dst.execute(f"PRAGMA encoding = '{pragmas['encoding']}'")
    dst.execute(f"PRAGMA auto_vacuum = {int(pragmas['auto_vacuum'])}")
    dst.execute("PRAGMA journal_mode = OFF")      # scratch file: a crash means rebuild
    dst.execute("PRAGMA synchronous = OFF")
    dst.execute("PRAGMA cache_size = -1048576")   # 1 GiB page cache for the build
    dst.execute("PRAGMA temp_store = FILE")
    dst.execute("ATTACH DATABASE ? AS src", (ro_uri(src),))

    # 1) tables (data before indexes: bulk-built indexes are packed and faster)
    for _type, name, _tbl, sql in all_tables:
        dst.execute(without_rowid_ddl(sql) if name in tables else sql)
    if dst.execute("PRAGMA page_size").fetchone()[0] != page_size:
        raise SystemExit("page_size did not take effect")

    rows_by_table: dict[str, int] = {}
    for _type, name, _tbl, _sql in all_tables:
        t0 = time.monotonic()
        cols = table_columns(dst, "src", name)
        names = ", ".join(q(c[1]) for c in cols)
        dst.execute("BEGIN")
        if name in tables:
            n = _copy_clustered(dst, name, cols, p)
        else:
            if has_rowid(dst, "src", name) and not rowid_alias(cols):
                dst.execute(f"INSERT INTO main.{q(name)} (rowid, {names}) "
                            f"SELECT rowid, {names} FROM src.{q(name)} ORDER BY rowid")
            else:
                dst.execute(f"INSERT INTO main.{q(name)} ({names}) SELECT {names} FROM src.{q(name)}")
            n = dst.execute(f"SELECT COUNT(*) FROM main.{q(name)}").fetchone()[0]
        dst.execute("COMMIT")
        rows_by_table[name] = n
        p.log(f"table {name}: {n:,} rows in {time.monotonic() - t0:.1f}s")

    if "sqlite_sequence" in internal:
        # The copy itself advanced AUTOINCREMENT counters; the source's values win.
        dst.execute("DELETE FROM main.sqlite_sequence")
        dst.execute("INSERT INTO main.sqlite_sequence SELECT * FROM src.sqlite_sequence")

    # 2) indexes, 3) views, 4) triggers — in source creation order
    for _type, name, _tbl, sql in indexes:
        t0 = time.monotonic()
        dst.execute(sql)
        p.log(f"index {name} built in {time.monotonic() - t0:.1f}s")
    for name, ddl in added:
        t0 = time.monotonic()
        dst.execute(ddl)
        p.log(f"index {name} (new) built in {time.monotonic() - t0:.1f}s")
    for _type, name, _tbl, sql in views + triggers:
        dst.execute(sql)
    p.log(f"{len(views)} views, {len(triggers)} triggers created")

    if analyze:
        t0 = time.monotonic()
        dst.execute("ANALYZE main")
        p.log(f"ANALYZE (all tables) in {time.monotonic() - t0:.1f}s")
    elif "sqlite_stat1" in internal:
        # Keep the source's planner statistics; only the converted tables are re-analyzed.
        for t in tables:
            dst.execute(f"ANALYZE main.{q(t)}")
        placeholders = ", ".join("?" for _ in tables)
        dst.execute(f"DELETE FROM main.sqlite_stat1 WHERE tbl NOT IN ({placeholders})", tables)
        dst.execute(f"INSERT INTO main.sqlite_stat1 SELECT * FROM src.sqlite_stat1 "
                    f"WHERE tbl NOT IN ({placeholders})", tables)
        p.log("sqlite_stat1 copied (converted tables re-analyzed)")

    dst.execute(f"PRAGMA user_version = {int(pragmas['user_version'])}")
    dst.execute(f"PRAGMA application_id = {int(pragmas['application_id'])}")
    dst.execute("DETACH DATABASE src")
    built = partial.stat().st_size
    free = dst.execute("PRAGMA freelist_count").fetchone()[0]
    p.log(f"built {partial.name}: {fmt_bytes(built)}, freelist pages {free}")

    final = partial
    if vacuum:
        t0 = time.monotonic()
        dst.execute("VACUUM INTO ?", (str(vac),))
        dst.close()
        partial.unlink()
        final = vac
        p.log(f"VACUUM INTO {vac.name}: {fmt_bytes(vac.stat().st_size)} in {time.monotonic() - t0:.1f}s")
    else:
        dst.close()

    fin = sqlite3.connect(final.resolve().as_uri(), uri=True, isolation_level=None)
    mode = fin.execute("PRAGMA journal_mode = WAL").fetchone()[0]
    fin.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    fin.close()
    for suffix in ("-wal", "-shm"):
        f = Path(str(final) + suffix)
        if f.exists() and f.stat().st_size == 0:
            f.unlink()
    if mode.lower() != "wal":
        raise SystemExit(f"could not set WAL mode on {final} (got {mode})")
    os.replace(final, out)
    size = out.stat().st_size
    p.log(f"DONE {out} = {fmt_bytes(size)} (source {fmt_bytes(src.stat().st_size)}, "
          f"saved {fmt_bytes(src.stat().st_size - size)})")
    return {"rows": rows_by_table, "size": size, "pragmas": pragmas, "dropped": dropped,
            "tables": list(tables), "page_size": page_size, "analyze": analyze}


def _copy_clustered(dst: sqlite3.Connection, name: str, cols: list[tuple], p: Progress) -> int:
    """Insert in PK order, one value of the first PK column at a time, so the
    b-tree is built by appends and progress can be printed for 32M-row tables."""
    pk = [c[1] for c in sorted((c for c in cols if c[5] > 0), key=lambda c: c[5])]
    names = ", ".join(q(c[1]) for c in cols)
    lead, rest = pk[0], pk[1:]
    nulls = dst.execute(
        f"SELECT COUNT(*) FROM src.{q(name)} WHERE " + " OR ".join(f"{q(c)} IS NULL" for c in pk)
    ).fetchone()[0]
    if nulls:
        raise SystemExit(f"{name} has {nulls} rows with a NULL key column; WITHOUT ROWID forbids that")
    keys = [r[0] for r in dst.execute(
        f"SELECT DISTINCT {q(lead)} FROM src.{q(name)} ORDER BY {q(lead)}")]
    total = 0
    last = time.monotonic()
    order = ", ".join(q(c) for c in rest) or "1"
    stmt = (f"INSERT INTO main.{q(name)} ({names}) SELECT {names} FROM src.{q(name)} "
            f"WHERE {q(lead)} = ? ORDER BY {order}")
    for i, key in enumerate(keys, 1):
        total += dst.execute(stmt, (key,)).rowcount
        if time.monotonic() - last >= 15 or i == len(keys):
            p.log(f"  {name}: {i:,}/{len(keys):,} {lead} values, {total:,} rows")
            last = time.monotonic()
    return total


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("source", type=Path, help="checkpointed snapshot (opened read-only)")
    ap.add_argument("output", type=Path, help="new database path (must not exist)")
    ap.add_argument("--tables", default=",".join(DEFAULT_TABLES),
                    help="comma-separated tables to rebuild WITHOUT ROWID (default: %(default)s)")
    ap.add_argument("--page-size", type=int, default=4096, choices=(4096, 8192))
    ap.add_argument("--analyze", action="store_true", help="run a full ANALYZE at the end")
    ap.add_argument("--no-vacuum", action="store_true",
                    help="skip the final VACUUM INTO (faster; file may be slightly larger)")
    ap.add_argument("--no-cover", action="store_true",
                    help="keep ix_branch_trades_raw_date, do not build ix_branch_trades_raw_date_cover "
                         "(comparison variant only; production uses the cover)")
    args = ap.parse_args(argv)
    tables = tuple(t.strip() for t in args.tables.split(",") if t.strip())
    convert(args.source, args.output, tables=tables, page_size=args.page_size,
            analyze=args.analyze, vacuum=not args.no_vacuum, cover=not args.no_cover)
    return 0


if __name__ == "__main__":
    sys.exit(main())
