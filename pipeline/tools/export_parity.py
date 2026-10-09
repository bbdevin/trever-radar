"""Functional parity: run the real `export-json` against OLD and NEW, diff the output.

    cd pipeline
    python tools/export_parity.py OLD.db NEW.db --work DIR [--self-check] [--parallel]
           [--old-code PIPELINE_DIR] [--new-code PIPELINE_DIR]
    python tools/export_parity.py DB --export-one OUT_DIR          # one read-only export
    python tools/export_parity.py --dirs LIVE_DIR NEW_DIR [--only-in-old-ok]
    python tools/export_parity.py --manifest EXPORT_DIR OUT.json   # small, ship between machines
    python tools/export_parity.py --compare-manifests OLD.json NEW.json [--only-in-old-ok]

The code under test is the same on both sides unless --old-code/--new-code
point at different pipeline/ checkouts (same DB twice + two code versions =
what a code change alone does to the output).

export_json() has no per-stock filter (it always writes every stock), so the
full export is run — it is also the strongest check, covering every page the
site reads.  Each export runs in its own subprocess with:

  * the engine opened through `file:...?mode=ro&immutable=1` (no write can
    reach either DB file), and
  * radar.db.init_db patched to a no-op (export_json calls it first; on a
    current snapshot it would be a no-op anyway, but it is the one code path
    that can write).

Comparison, per file under DIR/old and DIR/new:
  IDENTICAL   bytes equal
  TIMESTAMP   equal after dropping volatile keys (generated_at; plus any key
              --self-check found changing between two runs on the SAME DB);
              JSON object key order is ignored here (it is not data)
  ORDER-ONLY  same values, different list order (tie order — see docs/43 §2)
  VALUE       anything else; first differing JSON path is printed
  MISSING     file only on one side

Exit 0 = every file IDENTICAL/TIMESTAMP; 2 = only ORDER-ONLY differences;
1 = any VALUE/MISSING difference or an export failed.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1]
VOLATILE_KEYS = {"generated_at"}
SAMPLE_STOCKS = ["4967", "6488", "2330", "8299", "3105"]

RUNNER = r"""
import sys, sqlite3, time, json
from pathlib import Path
sys.path.insert(0, sys.argv[3])
db_path, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
uri = db_path.resolve().as_uri() + "?mode=ro&immutable=1"
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
import radar.config as config
import radar.db as db
# Non-DB input #1: spark_day.json is read from DATA_DIR (see NON_DB_INPUTS).
config.DATA_DIR = Path(sys.argv[4])
# Anything that bypasses get_engine() and opens config.DB_URL itself must fail
# loudly rather than read (or create) some other database.
config.DB_URL = "sqlite:///" + (Path(out_dir) / "no-such-dir" / "guard.db").as_posix()
db._engine = create_engine("sqlite://", creator=lambda: sqlite3.connect(uri, uri=True,
                           check_same_thread=False), poolclass=NullPool)
db.init_db = lambda: None
import radar.export.json_export as je
je.init_db = lambda: None
t0 = time.monotonic()
info = je.export_json(out_dir)
print(json.dumps({"seconds": round(time.monotonic() - t0, 1), "stocks": info.get("stocks"),
                  "date": info.get("date")}))
"""


# Everything export_json reads besides the database (audited 2026-10-04; docs/43 §6).
# Two exports are only comparable when all of these are the same on both sides:
NON_DB_INPUTS = """\
  1. DATA_DIR/spark_day.json   intraday spark cache (export/spark_day.py). Pinned: each run gets
                               its own fresh DATA_DIR holding a copy of --spark-cache (or nothing).
  2. FUGLE_API_KEY + Taipei date  with a key and today == price date, spark_day fetches from the
                               network and rewrites the cache (indices_intraday, docs/49 §12.5, uses
                               the same gate). Pinned: the key is removed from the env.
  3. radar/data/company_groups.json  repo file — same commit on both sides (--old-code/--new-code).
  4. wall clock                 only generated_at (ignored by the comparison).
  5. PYTHONHASHSEED             object key order in ~100 branches/track files. Pinned to 0.
  6. Python / SQLite version    float formatting and planner choices. Compare on ONE machine.
"""


def run_export(db_path: Path, out_dir: Path, python: str, code: Path = PIPELINE,
               spark_cache: Path | None = None) -> subprocess.Popen:
    """Export db_path into out_dir with the radar package found in `code` (a pipeline/ dir)."""
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit(f"refusing to export into non-empty {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    data_dir = out_dir.parent / f"{out_dir.name}.datadir"
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True)
    if spark_cache is not None:
        shutil.copyfile(spark_cache, data_dir / "spark_day.json")
    log = open(out_dir.parent / f"{out_dir.name}.log", "w", encoding="utf-8")
    # PYTHONHASHSEED=0: some export dicts are built by iterating sets of strings,
    # so their key order differs between any two processes (even on the same DB).
    # A fixed seed makes both sides byte-comparable; it changes no value.
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONHASHSEED="0")
    env.pop("FUGLE_API_KEY", None)
    return subprocess.Popen([python, "-c", RUNNER, str(db_path), str(out_dir), str(code), str(data_dir)],
                            cwd=code, stdout=log, stderr=subprocess.STDOUT, env=env)


def wait(proc: subprocess.Popen, label: str, out_dir: Path) -> dict | None:
    rc = proc.wait()
    log = (out_dir.parent / f"{out_dir.name}.log").read_text(encoding="utf-8", errors="replace")
    last = [ln for ln in log.splitlines() if ln.startswith("{")]
    if rc != 0 or not last:
        print(f"export {label} FAILED rc={rc}; tail of log:\n" + "\n".join(log.splitlines()[-25:]))
        return None
    info = json.loads(last[-1])
    # the one-line "export timing: branch_history=1.2s candles=…" that export_json prints
    timing_line = [ln for ln in log.splitlines() if ln.startswith("export timing:")]
    info["timing"] = {k: float(v.rstrip("s")) for k, v in
                      (kv.split("=") for kv in timing_line[-1].split(":", 1)[1].split())} if timing_line else {}
    print(f"export {label}: {info['stocks']} stocks for {info['date']} in {info['seconds']}s "
          f"{info['timing'] or ''}")
    return info


def strip(obj, keys):
    if isinstance(obj, dict):
        return {k: strip(v, keys) for k, v in obj.items() if k not in keys}
    if isinstance(obj, list):
        return [strip(v, keys) for v in obj]
    return obj


def canon(obj):
    if isinstance(obj, dict):
        return {k: canon(v) for k, v in obj.items()}
    if isinstance(obj, list):
        items = [canon(v) for v in obj]
        return sorted(items, key=lambda v: json.dumps(v, sort_keys=True, ensure_ascii=False))
    return obj


def first_diff(a, b, path="$"):
    if type(a) is not type(b):
        return f"{path}: {type(a).__name__} {str(a)[:80]} != {type(b).__name__} {str(b)[:80]}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return f"{path}.{k}: only in {'NEW' if k not in a else 'OLD'}"
            d = first_diff(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: list length {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_diff(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    return None if a == b else f"{path}: {str(a)[:80]} != {str(b)[:80]}"


def volatile_keys(a, b, path=()) -> set[str]:
    """Keys whose values differ between two exports of the same DB."""
    out: set[str] = set()
    if isinstance(a, dict) and isinstance(b, dict):
        for k in set(a) & set(b):
            if a[k] != b[k]:
                if isinstance(a[k], (dict, list)) and type(a[k]) is type(b[k]):
                    out |= volatile_keys(a[k], b[k], path + (k,))
                else:
                    out.add(k)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for x, y in zip(a, b):
            out |= volatile_keys(x, y, path)
    return out


def files(root: Path) -> dict[str, Path]:
    return {p.relative_to(root).as_posix(): p for p in root.rglob("*") if p.is_file()}


def compare(old_dir: Path, new_dir: Path, ignore: set[str], sample: list[str]) -> dict[str, list]:
    fo, fn = files(old_dir), files(new_dir)
    result: dict[str, list] = {k: [] for k in ("IDENTICAL", "TIMESTAMP", "ORDER-ONLY", "VALUE", "MISSING")}
    for rel in sorted(set(fo) | set(fn)):
        if rel not in fo or rel not in fn:
            result["MISSING"].append((rel, "only in " + ("NEW" if rel not in fo else "OLD")))
            continue
        a, b = fo[rel].read_bytes(), fn[rel].read_bytes()
        if a == b:
            result["IDENTICAL"].append((rel, ""))
            continue
        if not rel.endswith(".json"):
            result["VALUE"].append((rel, "non-JSON bytes differ"))
            continue
        ja, jb = json.loads(a), json.loads(b)
        sa, sb = strip(ja, ignore), strip(jb, ignore)
        if sa == sb:
            result["TIMESTAMP"].append((rel, ""))
        elif canon(sa) == canon(sb):
            result["ORDER-ONLY"].append((rel, first_diff(sa, sb) or ""))
        else:
            result["VALUE"].append((rel, first_diff(sa, sb) or "differs"))
    print()
    for k, v in result.items():
        print(f"{k:11s} {len(v):6d} files")
    for k in ("MISSING", "VALUE", "ORDER-ONLY"):
        for rel, why in result[k][:40]:
            print(f"  {k}: {rel}  {why}")
        if len(result[k]) > 40:
            print(f"  ... {len(result[k]) - 40} more {k}")
    if sample:
        print("\nsample stocks:")
        status = {rel: k for k, v in result.items() for rel, _ in v}
        for sid in sample:
            hits = sorted(rel for rel in status if Path(rel).stem == sid)
            print(f"  {sid}: " + (", ".join(f"{rel}={status[rel]}" for rel in hits) or "no file (not in DB)"))
    return result


def manifest(root: Path, ignore: set[str]) -> dict[str, str]:
    """rel path -> sha256 of the file with volatile keys stripped (JSON) or of its bytes.

    Lets two machines compare exports by shipping a small JSON instead of the
    whole tree (the VPS post-swap export vs the PC's export of the snapshot)."""
    import hashlib
    out = {}
    for rel, p in sorted(files(root).items()):
        raw = p.read_bytes()
        if rel.endswith(".json"):
            try:
                # sort_keys: object key order is not data (and varies with the hash
                # seed in a few files); list order still counts.
                raw = json.dumps(strip(json.loads(raw), ignore), ensure_ascii=False,
                                 separators=(",", ":"), sort_keys=True).encode("utf-8")
            except ValueError:
                pass
        out[rel] = hashlib.sha256(raw).hexdigest()
    return out


def compare_manifests(a: dict[str, str], b: dict[str, str], only_in_old_ok: bool) -> int:
    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    diff = sorted(k for k in set(a) & set(b) if a[k] != b[k])
    same = len(set(a) & set(b)) - len(diff)
    print(f"identical {same}, different {len(diff)}, only in OLD {len(only_a)}, only in NEW {len(only_b)}")
    for k in diff[:40]:
        print(f"  DIFFERENT: {k}")
    for k in only_b[:20]:
        print(f"  only in NEW: {k}")
    for k in only_a[:20]:
        print(f"  only in OLD: {k}")
    if diff or only_b or (only_a and not only_in_old_ok):
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS — manifests match (volatile timestamps ignored)")
    return 0


def verdict(res: dict[str, list], only_in_old_ok: bool = False) -> int:
    missing = [m for m in res["MISSING"] if not (only_in_old_ok and m[1] == "only in OLD")]
    if res["VALUE"] or missing:
        print("RESULT: FAIL (value differences)")
        return 1
    if res["ORDER-ONLY"]:
        print("RESULT: ORDER-ONLY differences (same values, tie order changed) — see docs/43 §2")
        return 2
    print("RESULT: PASS — exports identical (ignoring volatile timestamps)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("old", type=Path, nargs="?")
    ap.add_argument("new", type=Path, nargs="?")
    ap.add_argument("--work", type=Path, help="empty scratch dir for the two exports")
    ap.add_argument("--export-one", type=Path, metavar="OUT",
                    help="only export OLD (read-only) into OUT and print the timing (VPS post-swap check)")
    ap.add_argument("--dirs", nargs=2, type=Path, metavar=("OLD_DIR", "NEW_DIR"),
                    help="only compare two existing export trees (e.g. web/public/data vs a fresh export)")
    ap.add_argument("--only-in-old-ok", action="store_true",
                    help="with --dirs/--compare-manifests: files only on the OLD side are not a failure")
    ap.add_argument("--manifest", nargs=2, type=Path, metavar=("DIR", "OUT_JSON"),
                    help="write a per-file hash manifest of an export tree (volatile keys stripped)")
    ap.add_argument("--compare-manifests", nargs=2, type=Path, metavar=("OLD_JSON", "NEW_JSON"))
    ap.add_argument("--self-check", action="store_true",
                    help="also export OLD a second time to learn which keys are volatile")
    ap.add_argument("--parallel", action="store_true",
                    help="run the exports concurrently (faster; timings then not comparable)")
    ap.add_argument("--sample", nargs="*", default=SAMPLE_STOCKS)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--spark-cache", type=Path, default=None,
                    help="copy of the VPS data/spark_day.json, given to every export run (non-DB input #1)")
    ap.add_argument("--list-inputs", action="store_true", help="print the non-DB inputs of export_json and exit")
    ap.add_argument("--old-code", type=Path, default=PIPELINE,
                    help="pipeline/ dir whose radar package exports OLD (default: this checkout)")
    ap.add_argument("--new-code", type=Path, default=PIPELINE,
                    help="pipeline/ dir whose radar package exports NEW (default: this checkout). "
                         "Same DB on both sides + different code = what a code change alone does.")
    ap.add_argument("--compare-only", action="store_true",
                    help="skip the exports; re-compare existing WORK/old and WORK/new")
    a = ap.parse_args(argv)

    if a.list_inputs:
        print(NON_DB_INPUTS)
        return 0
    if a.export_one:
        if not a.old:
            raise SystemExit("--export-one needs the DB path")
        info = wait(run_export(a.old, a.export_one, a.python, a.old_code, a.spark_cache), "one", a.export_one)
        return 0 if info else 1
    if a.dirs:
        res = compare(a.dirs[0], a.dirs[1], set(VOLATILE_KEYS), a.sample)
        return verdict(res, a.only_in_old_ok)
    if a.manifest:
        m = manifest(a.manifest[0], set(VOLATILE_KEYS))
        a.manifest[1].write_text(json.dumps(m, indent=0), encoding="utf-8")
        print(f"manifest of {len(m)} files -> {a.manifest[1]}")
        return 0
    if a.compare_manifests:
        ma, mb = (json.loads(p.read_text(encoding="utf-8")) for p in a.compare_manifests)
        return compare_manifests(ma, mb, a.only_in_old_ok)
    if not (a.old and a.new and a.work):
        raise SystemExit("give OLD NEW --work DIR (or --export-one / --dirs)")
    a.work.mkdir(parents=True, exist_ok=True)
    if a.compare_only:
        res = compare(a.work / "old", a.work / "new", set(VOLATILE_KEYS), a.sample)
        (a.work / "parity-report.json").write_text(json.dumps(
            {k: v for k, v in res.items() if k != "IDENTICAL"}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        return 1 if res["VALUE"] or res["MISSING"] else (2 if res["ORDER-ONLY"] else 0)
    jobs = [("old", a.old), ("new", a.new)] + ([("old_again", a.old)] if a.self_check else [])
    code = {"old": a.old_code, "new": a.new_code, "old_again": a.old_code}
    infos = {}
    if a.parallel:
        procs = [(lbl, run_export(db, a.work / lbl, a.python, code[lbl], a.spark_cache)) for lbl, db in jobs]
        for lbl, p in procs:
            infos[lbl] = wait(p, lbl, a.work / lbl)
    else:
        for lbl, db in jobs:
            infos[lbl] = wait(run_export(db, a.work / lbl, a.python, code[lbl], a.spark_cache), lbl, a.work / lbl)
    if any(v is None for v in infos.values()):
        return 1

    ignore = set(VOLATILE_KEYS)
    if a.self_check:
        fo, fa = files(a.work / "old"), files(a.work / "old_again")
        noisy = set()
        for rel in set(fo) & set(fa):
            x, y = fo[rel].read_bytes(), fa[rel].read_bytes()
            if x != y and rel.endswith(".json"):
                noisy |= volatile_keys(json.loads(x), json.loads(y))
        print(f"self-check: keys that change between two exports of the same DB: {sorted(noisy) or 'none'}")
        ignore |= noisy

    t0 = time.monotonic()
    res = compare(a.work / "old", a.work / "new", ignore, a.sample)
    print(f"\ncompared in {time.monotonic() - t0:.1f}s; ignored keys: {sorted(ignore)}")
    report = a.work / "parity-report.json"
    report.write_text(json.dumps({k: v for k, v in res.items() if k != "IDENTICAL"},
                                 ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"full list of non-identical files: {report}")
    return verdict(res)


if __name__ == "__main__":
    sys.exit(main())
