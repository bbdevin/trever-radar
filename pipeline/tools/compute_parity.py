"""Compute parity: run the nightly compute steps on copies of OLD and NEW, compare every table.

    cd pipeline
    python tools/compute_parity.py OLD.db NEW.db --work DIR [--steps "compute-branch-stats;compute-scores"]

export_parity proves the *export* is identical; this proves the *compute* steps
are too — i.e. that their output is a function of the data and not of the
physical row order (docs/43 §1).  Both inputs are only read (copied with
shutil); the steps run on the copies under WORK/old and WORK/new, each through
the real CLI (`python -m radar …`) with RADAR_DB_URL pointing at its copy and
PYTHONHASHSEED=0.

After the steps, every table of the two copies is compared: row count + SHA-256
over all rows in PRIMARY KEY order, leaving out columns whose name ends in
"_at" (computed_at, updated_at, fwd_updated_at: wall-clock stamps).  The
excluded columns are printed.

Non-DB inputs of the default steps (audited 2026-10-04), and how they are pinned:
  * "today": none of the steps reads the wall clock for its *values* — the as-of
    date is MAX(date) of daily_prices / branch_trades in the DB; indicators
    `--days 5` counts trading dates in the DB.  The clock only fills computed_at /
    updated_at / fwd_updated_at / run_at, which are excluded ("*_at").
  * env: FUGLE_API_KEY / RADAR_FINMIND_TOKEN removed (no step should fetch;
    removing them makes that certain); PYTHONHASHSEED=0; RADAR_DATA_DIR = the
    copy's own directory (no stray cache files).
  * code: the same pipeline/ checkout on both sides (or --old-code/--new-code).
  * Python/SQLite: one machine runs both sides.

Exit 0 = every table identical; 1 = any difference or a step failed.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1]
# The 00:05 safe-branch-stats chain plus the incremental indicators of the daily rounds.
DEFAULT_STEPS = (
    "compute-indicators --all --days 5",
    "compute-branch-stats",
    "branch-point-in-time-persist",
    "branch-stock-pctile-counts",
    "compute-scores",
)


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def copy_db(src: Path, dst: Path) -> None:
    wal = Path(str(src) + "-wal")
    if wal.exists() and wal.stat().st_size > 0:
        raise SystemExit(f"refusing: {wal} is not empty; checkpoint first")
    if dst.exists():
        raise SystemExit(f"refusing to overwrite {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


def run_steps(db: Path, steps: list[str], python: str, label: str,
              code: Path = PIPELINE) -> dict[str, float] | None:
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONHASHSEED="0",
               RADAR_DB_URL="sqlite:///" + db.resolve().as_posix(),
               RADAR_DATA_DIR=str(db.parent.resolve()))
    for key in ("FUGLE_API_KEY", "RADAR_FINMIND_TOKEN"):   # no network, whatever the steps
        env.pop(key, None)
    timings = {}
    log = db.parent / f"{label}.log"
    with log.open("w", encoding="utf-8") as fh:
        for step in steps:
            t0 = time.monotonic()
            rc = subprocess.call([python, "-m", "radar", *step.split()], cwd=code,
                                 stdout=fh, stderr=subprocess.STDOUT, env=env)
            timings[step] = time.monotonic() - t0
            print(f"  {label}: {step} rc={rc} {timings[step]:.1f}s", flush=True)
            if rc != 0:
                print(f"step failed; see {log}")
                return None
    return timings


def digest(conn: sqlite3.Connection, table: str) -> tuple[int, str, list[str]]:
    cols = [r for r in conn.execute(f"PRAGMA table_xinfo({q(table)})") if r[6] == 0]
    keep = [c[1] for c in cols if not c[1].endswith("_at")]
    skipped = [c[1] for c in cols if c[1].endswith("_at")]
    pk = [c[1] for c in sorted((c for c in cols if c[5] > 0), key=lambda c: c[5])]
    order = ", ".join(q(c) for c in pk) if pk else ", ".join(q(c) for c in keep)
    h, n = hashlib.sha256(), 0
    cur = conn.execute(f"SELECT {', '.join(q(c) for c in keep)} FROM {q(table)} ORDER BY {order}")
    while True:
        rows = cur.fetchmany(20000)
        if not rows:
            break
        for row in rows:
            h.update(repr(row).encode("utf-8", "surrogatepass"))
            h.update(b"\n")
        n += len(rows)
    return n, h.hexdigest(), skipped


def count_row_diffs(a: sqlite3.Connection, b: sqlite3.Connection, table: str) -> dict[str, int]:
    """Merge-join both sides in PK order: rows only in OLD / only in NEW / same PK but changed."""
    cols = [r for r in a.execute(f"PRAGMA table_xinfo({q(table)})") if r[6] == 0]
    keep = [c[1] for c in cols if not c[1].endswith("_at")]
    pk = [c[1] for c in sorted((c for c in cols if c[5] > 0), key=lambda c: c[5])] or keep
    sel = (f"SELECT {', '.join(q(c) for c in pk)}, {', '.join(q(c) for c in keep)} "
           f"FROM {q(table)} ORDER BY {', '.join(q(c) for c in pk)}")
    ia, ib = a.execute(sel), b.execute(sel)
    n = len(pk)
    out = {"only_old": 0, "only_new": 0, "changed": 0}
    ra, rb = ia.fetchone(), ib.fetchone()
    while ra is not None or rb is not None:
        ka = ra[:n] if ra is not None else None
        kb = rb[:n] if rb is not None else None
        if kb is None or (ka is not None and ka < kb):
            out["only_old"] += 1
            ra = ia.fetchone()
        elif ka is None or kb < ka:
            out["only_new"] += 1
            rb = ib.fetchone()
        else:
            out["changed"] += ra != rb
            ra, rb = ia.fetchone(), ib.fetchone()
    return out


def compare(old: Path, new: Path) -> bool:
    a = sqlite3.connect(old.resolve().as_uri() + "?mode=ro", uri=True)
    b = sqlite3.connect(new.resolve().as_uri() + "?mode=ro", uri=True)
    ta = {r[0] for r in a.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    tb = {r[0] for r in b.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    ok = ta == tb
    if not ok:
        print(f"FAIL  table sets differ: only OLD {sorted(ta - tb)}, only NEW {sorted(tb - ta)}")
    for t in sorted(ta & tb):
        na, ha, skipped = digest(a, t)
        nb, hb, _ = digest(b, t)
        same = na == nb and ha == hb
        ok &= same
        detail = "" if same else f" — {count_row_diffs(a, b, t)}"
        print(f"{'PASS' if same else 'FAIL'}  {t}: rows {na:,} / {nb:,}"
              f"{detail}{f' (ignored {skipped})' if skipped else ''}")
    a.close()
    b.close()
    return ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("old", type=Path)
    ap.add_argument("new", type=Path)
    ap.add_argument("--work", type=Path, required=True, help="scratch dir (gets two DB copies)")
    ap.add_argument("--steps", default=";".join(DEFAULT_STEPS),
                    help="';'-separated radar CLI commands (default: %(default)s)")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--old-code", type=Path, default=PIPELINE,
                    help="pipeline/ dir whose radar package computes OLD (default: this checkout)")
    ap.add_argument("--new-code", type=Path, default=PIPELINE,
                    help="pipeline/ dir for NEW; same DB twice + two code versions = what the code change alone does")
    a = ap.parse_args(argv)
    steps = [s.strip() for s in a.steps.split(";") if s.strip()]
    sides = {"old": a.work / "old" / "radar.db", "new": a.work / "new" / "radar.db"}
    for label, src in (("old", a.old), ("new", a.new)):
        t0 = time.monotonic()
        copy_db(src, sides[label])
        print(f"copied {label} in {time.monotonic() - t0:.1f}s")
    code = {"old": a.old_code, "new": a.new_code}
    for label, db in sides.items():
        if run_steps(db, steps, a.python, label, code[label]) is None:
            return 1
    for db in sides.values():   # fold the WAL in so the read-only compare sees everything
        c = sqlite3.connect(db)
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        c.close()
    print()
    ok = compare(sides["old"], sides["new"])
    print("\nRESULT: " + ("PASS — compute output identical on both layouts" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
