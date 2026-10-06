"""Read-only diff: stored daily_scores vs. what today's scoring code would produce.

docs/20 Phase 2: S1-S10 used to add points to tech_score (and through it to
final); since 2026-07-10 strategies only write a reason (S11-S13 too).  Rows
written before that were never recomputed.  This tool shows what a full
recompute would change, without doing it:

    cd pipeline
    python tools/score_recompute_diff.py --out /tmp/score_diff.csv [--days 120]
        [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--tech-source recompute|stored]

How each stored (stock, date) is recomputed, entirely in memory:
  * technicals: radar.compute.indicators.compute_series over each stock's
    prices (WARMUP_BARS before the range, like the incremental production run)
    with the current adj_factor -> tech_score / volume_ratio / risks / ma5 /
    box_high60 exactly as compute-indicators would store them today.  The
    stored indicators_daily.tech_score of old dates still carries the strategy
    bonus, so reusing it would hide the very diff we look for.
    `--tech-source stored` reuses indicators_daily instead (isolates the
    scores layer).
  * the rest: radar.compute.scores.score_date, the same function compute-scores
    runs, scored "as of" each date (its 22 trading days ending at that date).

The DB is opened through URI mode=ro (radar.compute.read_only_sqlite): every
statement is a SELECT and SQLite itself refuses writes.  No lock is needed;
under WAL a reader never blocks the writer.

Memory: one date of scoring inputs at a time (the same footprint as one
compute-scores run) plus the recomputed technicals of the range (~a few
hundred bytes per stock-date, ~60-100 MB for 120 days of the full market).
The CSV is streamed; summary statistics are kept as value histograms.
"""
from __future__ import annotations

import argparse
import csv
import heapq
import math
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from radar.compute.indicators import WARMUP_BARS, compute_series  # noqa: E402
from radar.compute.read_only_sqlite import (  # noqa: E402
    get_read_only_sqlite_engine,
    safe_report_output_path,
)
from radar.compute.scores import score_date  # noqa: E402
from radar.export.json_export import SCORE_LIST_MIN_FINAL  # noqa: E402

REPORT = "score recompute diff"
FIELDS = ("final", "branch_score", "warrant_score", "tech_score", "inst_score",
          "theme_score", "risk_penalty")
REQUIRED_TABLES = ("daily_scores", "daily_prices", "stocks", "indicators_daily",
                   "warrant_stock_daily", "daily_institutional", "daily_margins",
                   "branch_trades_raw", "branch_dim", "stock_themes", "themes")


def _iso(s: str) -> str:
    s = s.replace("-", "")
    if len(s) != 8 or not s.isdigit():
        raise argparse.ArgumentTypeError(f"bad date {s!r}; use YYYY-MM-DD or YYYYMMDD")
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def target_dates(conn, days: int, date_from: str | None, date_to: str | None) -> list[str]:
    """Dates of daily_scores to compare, ascending."""
    where, params = [], {}
    if date_from:
        where.append("date >= :lo")
        params["lo"] = date_from
    if date_to:
        where.append("date <= :hi")
        params["hi"] = date_to
    sql = "SELECT DISTINCT date FROM daily_scores"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY date DESC"
    if not date_from:
        sql += " LIMIT :n"
        params["n"] = days
    return sorted(r[0] for r in conn.execute(text(sql), params))


def recompute_tech(engine, start: str, end: str, *, log=print) -> dict[str, dict[str, tuple]]:
    """{date: {stock_id: indicators row tuple}} for start..end, freshly computed.

    Tuple shape is what score_date reads from indicators_daily; reasons are left
    out (None) ??they only feed the reasons JSON, which this report ignores.
    """
    with engine.connect() as conn:
        lo = conn.execute(text(
            "SELECT MIN(date) FROM (SELECT DISTINCT date FROM daily_prices "
            "WHERE date < :s ORDER BY date DESC LIMIT :n)"),
            {"s": start, "n": WARMUP_BARS}).scalar() or start
        stock_ids = [r[0] for r in conn.execute(text(
            "SELECT id FROM stocks WHERE type = 'stock' ORDER BY id"))]
    out: dict[str, dict[str, tuple]] = {}
    t0 = time.monotonic()
    for i, sid in enumerate(stock_ids, 1):
        with engine.connect() as conn:
            rows = [dict(r._mapping) for r in conn.execute(text(
                "SELECT stock_id, date, open, high, low, close, adj_factor, volume "
                "FROM daily_prices WHERE stock_id = :sid AND date >= :lo AND date <= :hi "
                "AND close IS NOT NULL ORDER BY date"), {"sid": sid, "lo": lo, "hi": end})]
        for x in compute_series(rows):
            if x["date"] < start:
                continue
            out.setdefault(x["date"], {})[sid] = (
                sid, x["tech_score"], x["volume_ratio"], sys.intern(x["risks"]), None,
                x["ma5"], x["box_high60"])
        if i % 200 == 0 or i == len(stock_ids):
            el = time.monotonic() - t0
            log(f"tech {i}/{len(stock_ids)} stocks ({el:.0f}s, "
                f"ETA {el / i * (len(stock_ids) - i):.0f}s)")
    return out


def _quantile(hist: Counter, q: float):
    """Nearest-rank quantile of a value histogram."""
    n = sum(hist.values())
    if not n:
        return None
    rank = max(1, math.ceil(q * n - 1e-9))
    seen = 0
    for v in sorted(hist):
        seen += hist[v]
        if seen >= rank:
            return v
    return None


def _median(hist: Counter):
    n = sum(hist.values())
    if not n:
        return None
    vals = sorted(hist)
    def nth(k):  # 0-based
        seen = 0
        for v in vals:
            seen += hist[v]
            if seen > k:
                return v
    return (nth((n - 1) // 2) + nth(n // 2)) / 2


def _mean(hist: Counter):
    n = sum(hist.values())
    return sum(v * c for v, c in hist.items()) / n if n else None


class Diff:
    """Accumulates the comparison with bounded memory and streams changed rows."""

    def __init__(self, writer, threshold: int = SCORE_LIST_MIN_FINAL, top: int = 20):
        self.w = writer
        self.threshold = threshold
        self.top_n = top
        self.compared = self.changed = 0
        self.only_stored = self.only_new = 0
        self.only_stored_listed = self.only_new_listed = 0
        self.enter = self.exit = 0
        self.absdiff = {f: Counter() for f in FIELDS}
        self.null_mismatch = Counter()
        self.top: list[tuple] = []          # min-heap of (|final diff|, date, sid, old, new)
        self.w.writerow(["date", "stock_id", "status", "list_cross"]
                        + [f"{p}_{f}" for f in FIELDS for p in ("stored", "new", "diff")])

    def _row(self, d, sid, status, cross, old, new):
        cells = [d, sid, status, cross]
        for f in FIELDS:
            o = old.get(f) if old else None
            n = new.get(f) if new else None
            cells += [o, n, (n - o) if o is not None and n is not None else None]
        self.w.writerow(["" if c is None else c for c in cells])

    def add_date(self, d: str, stored: dict[str, dict], new: dict[str, dict]) -> tuple[int, int]:
        compared = changed = 0
        for sid in sorted(stored.keys() | new.keys()):
            old, nw = stored.get(sid), new.get(sid)
            if nw is None:
                self.only_stored += 1
                listed = old["final"] >= self.threshold
                self.only_stored_listed += listed
                self._row(d, sid, "only_stored", "exit" if listed else "", old, None)
                continue
            if old is None:
                self.only_new += 1
                listed = nw["final"] >= self.threshold
                self.only_new_listed += listed
                self._row(d, sid, "only_recomputed", "enter" if listed else "", None, nw)
                continue
            compared += 1
            differs = False
            for f in FIELDS:
                o, n = old.get(f), nw.get(f)
                if o is None and n is None:
                    continue
                if o is None or n is None:
                    self.null_mismatch[f] += 1
                    differs = True
                    continue
                a = abs(n - o)
                self.absdiff[f][a] += 1
                differs |= a != 0
            if not differs:
                continue
            changed += 1
            was, now = old["final"] >= self.threshold, nw["final"] >= self.threshold
            cross = "enter" if now and not was else "exit" if was and not now else ""
            self.enter += cross == "enter"
            self.exit += cross == "exit"
            self._row(d, sid, "changed", cross, old, nw)
            # (date, stock) is unique, so the dicts are never compared.
            item = (abs(nw["final"] - old["final"]), d, sid, old, nw)
            if len(self.top) < self.top_n:
                heapq.heappush(self.top, item)
            elif item[:3] > self.top[0][:3]:
                heapq.heapreplace(self.top, item)
        self.compared += compared
        self.changed += changed
        return compared, changed

    def summary_lines(self) -> list[str]:
        L = []
        share = self.changed / self.compared if self.compared else 0.0
        L.append(f"rows compared (stored & recomputed): {self.compared}")
        L.append(f"rows changed (any score field): {self.changed} ({share:.1%})")
        L.append(f"rows only stored (would no longer be scored): {self.only_stored}"
                 f" (of which final>={self.threshold}: {self.only_stored_listed})")
        L.append(f"rows only recomputed (would newly be scored): {self.only_new}"
                 f" (of which final>={self.threshold}: {self.only_new_listed})")
        L.append(f"list threshold final>={self.threshold} crossings among compared rows: "
                 f"enter {self.enter}, exit {self.exit} "
                 f"(the 40-row cap and the score_list_gate withholding are not modelled)")
        L.append("")
        L.append(f"{'field':<14}{'n':>9}{'changed':>9}{'mean|d|':>9}{'median':>8}"
                 f"{'p95':>6}{'max':>6}{'null<>val':>10}")
        for f in FIELDS:
            h = self.absdiff[f]
            n = sum(h.values())
            nz = n - h.get(0, 0)
            mean, med, p95 = _mean(h), _median(h), _quantile(h, 0.95)
            mx = max(h) if h else None
            fmt = lambda v, w, p=0: f"{v:>{w}.{p}f}" if v is not None else f"{'-':>{w}}"  # noqa: E731
            L.append(f"{f:<14}{n:>9}{nz:>9}{fmt(mean, 9, 2)}{fmt(med, 8, 1)}"
                     f"{fmt(p95, 6)}{fmt(mx, 6)}{self.null_mismatch[f]:>10}")
        L.append("")
        L.append(f"top {self.top_n} movers by |final diff| (stored -> recomputed):")
        L.append(f"{'date':<11}{'stock':<7}{'final':>10}{'tech':>10}{'branch':>10}"
                 f"{'warrant':>10}{'inst':>10}{'theme':>10}{'risk':>9}")

        def pair(o, n):
            s = lambda v: "na" if v is None else str(v)  # noqa: E731
            return f"{s(o)}>{s(n)}"
        for absd, d, sid, old, nw in sorted(self.top, key=lambda t: (-t[0], t[1], t[2])):
            L.append(f"{d:<11}{sid:<7}"
                     + "".join(f"{pair(old.get(f), nw.get(f)):>10}" for f in
                               ("final", "tech_score", "branch_score", "warrant_score",
                                "inst_score", "theme_score"))
                     + f"{pair(old.get('risk_penalty'), nw.get('risk_penalty')):>9}")
        return L


def _score_fields(row) -> dict:
    return {f: row[f] for f in FIELDS}


def run(out: str, days: int = 120, date_from: str | None = None, date_to: str | None = None,
        tech_source: str = "recompute", log=print) -> Diff:
    out_path = safe_report_output_path(out, report_name=REPORT)
    engine = get_read_only_sqlite_engine(report_name=REPORT, required_tables=REQUIRED_TABLES)
    try:
        with engine.connect() as conn:
            dates = target_dates(conn, days, date_from, date_to)
            if not dates:
                raise RuntimeError("no daily_scores dates in the requested range")
            price_dates = [r[0] for r in conn.execute(text(
                "SELECT DISTINCT date FROM daily_prices WHERE date <= :hi ORDER BY date DESC"),
                {"hi": dates[-1]})]
        log(f"{REPORT}: {len(dates)} dates {dates[0]}..{dates[-1]}, tech={tech_source}, "
            f"list threshold final>={SCORE_LIST_MIN_FINAL}")

        t0 = time.monotonic()
        tech = recompute_tech(engine, dates[0], dates[-1], log=log) \
            if tech_source == "recompute" else None
        log(f"tech ready ({time.monotonic() - t0:.0f}s)")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", newline="", encoding="utf-8") as fh:
            diff = Diff(csv.writer(fh))
            t1 = time.monotonic()
            for k, d in enumerate(dates, 1):
                if d not in price_dates:
                    log(f"[{k}/{len(dates)}] {d} skipped: no daily_prices on that date")
                    continue
                di = price_dates.index(d)
                window = price_dates[di:di + 22]          # what compute-scores saw on d
                with engine.connect() as conn:
                    new = {r["stock_id"]: _score_fields(r) for r in score_date(
                        conn, d, window,
                        tech=(tech.pop(d, {}) if tech is not None else None))}
                    stored = {r.stock_id: _score_fields(r._mapping) for r in conn.execute(text(
                        "SELECT stock_id, " + ", ".join(FIELDS)
                        + " FROM daily_scores WHERE date = :d"), {"d": d})}
                compared, changed = diff.add_date(d, stored, new)
                fh.flush()
                el = time.monotonic() - t1
                log(f"[{k}/{len(dates)}] {d} compared={compared} changed={changed} "
                    f"({el:.0f}s, ETA {el / k * (len(dates) - k):.0f}s)")
    finally:
        engine.dispose()
    log("")
    for line in diff.summary_lines():
        log(line)
    log("")
    log(f"changed rows CSV: {out_path}")
    return diff


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True, help="CSV of changed rows (never the DB)")
    ap.add_argument("--days", type=int, default=120,
                    help="last N daily_scores dates when --from is not given (default 120)")
    ap.add_argument("--from", dest="date_from", type=_iso)
    ap.add_argument("--to", dest="date_to", type=_iso)
    ap.add_argument("--tech-source", choices=("recompute", "stored"), default="recompute",
                    help="recompute technicals from prices (default) or reuse indicators_daily")
    a = ap.parse_args(argv)
    run(a.out, a.days, a.date_from, a.date_to, a.tech_source,
        log=lambda s: print(s, flush=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
