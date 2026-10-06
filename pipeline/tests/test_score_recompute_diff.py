"""tools/score_recompute_diff.py: read-only recompute diff of daily_scores (docs/20 Phase 2)."""
import contextlib
import csv
import io
import json
import random
import sqlite3
import unittest
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import text

import radar.config as config
import radar.db as db
from radar import schema
from radar.compute.indicators import compute_indicators
from radar.compute.read_only_sqlite import get_read_only_sqlite_engine
from radar.compute.scores import compute_scores
from tools import score_recompute_diff as tool

STOCKS = ["2330", "2317", "3105", "4967", "6488"]


def _weekdays(n, end=date(2026, 10, 2)):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return sorted(out)


# Exactly 22 price dates: compute-scores reads the latest 22, so for every one of
# them its window equals the "as of that date" window the tool uses.
DATES = _weekdays(22)
SCORED = DATES[-5:]


def _seed(conn):
    rnd = random.Random(20261006)
    conn.execute(schema.stocks.insert(), [
        {"id": s, "name": f"S{s}", "market": "twse", "type": "stock"} for s in STOCKS])
    conn.execute(schema.themes.insert(), {"id": "T1", "name": "Theme", "source": "fubon"})
    conn.execute(schema.stock_themes.insert(), [{"theme_id": "T1", "stock_id": s} for s in STOCKS])
    conn.execute(schema.branch_dim.insert(), [
        {"id": i + 1, "branch_key": f"9{i:03d}", "broker_id": f"9{i:03d}",
         "branch_name": f"B{i}"} for i in range(6)])
    prices, insti, margins, warrants, branches = [], [], [], [], []
    for s in STOCKS:
        close = rnd.uniform(50, 300)
        for d in DATES:
            prev = close
            close = round(prev * rnd.uniform(0.95, 1.06), 2)
            vol = rnd.randint(2_000, 9_000) * 1000
            prices.append({
                "stock_id": s, "date": d, "open": round(prev * rnd.uniform(0.99, 1.03), 2),
                "high": round(max(prev, close) * 1.02, 2), "low": round(min(prev, close) * 0.98, 2),
                "close": close, "adj_factor": 1.0, "volume": vol,
                "turnover": int(vol * close)})
            insti.append({"stock_id": s, "date": d,
                          "foreign_net": rnd.randint(-300, 600) * 1000,
                          "trust_net": rnd.randint(-100, 300) * 1000,
                          "dealer_net": 0, "total_net": rnd.randint(-300, 900) * 1000})
            margins.append({"stock_id": s, "date": d, "margin_balance": rnd.randint(1000, 5000),
                            "margin_limit": 10_000, "short_balance": rnd.randint(500, 3000),
                            "short_prev": rnd.randint(500, 3000)})
            warrants.append({"stock_id": s, "date": d,
                             "call_turnover": rnd.randint(1, 20) * 1_000_000,
                             "call_volume": rnd.randint(100, 2000) * 1000,
                             "put_turnover": rnd.randint(0, 5) * 1_000_000})
            for b in range(1, 7):
                net = rnd.randint(-200, 400)
                branches.append({"stock_id": s, "date": d, "branch_id": b,
                                 "buy_lots": max(net, 0) + 10, "sell_lots": max(-net, 0) + 10,
                                 "net_lots": net, "pct": 1.0, "source": "fubon"})
    conn.execute(schema.daily_prices.insert(), prices)
    conn.execute(schema.daily_institutional.insert(), insti)
    conn.execute(schema.daily_margins.insert(), margins)
    conn.execute(schema.warrant_stock_daily.insert(), warrants)
    conn.execute(schema.branch_trades_raw.insert(), branches)


def _quiet(fn, *a, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


class ScoreRecomputeDiffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.old_url, self.old_dir = config.DB_URL, config.DATA_DIR
        self.db_path = self.tmp_path / "radar.db"
        config.DB_URL = "sqlite:///" + self.db_path.as_posix()
        config.DATA_DIR = self.tmp_path
        db._engine = None
        db.init_db()
        with db.get_engine().begin() as conn:
            _seed(conn)
        # The production path writes the "stored" side.
        _quiet(compute_indicators, all_stocks=True)
        for d in SCORED:
            compute_scores(d.replace("-", ""))
        self.out = self.tmp_path / "diff.csv"

    def tearDown(self):
        self._close_writer()
        config.DB_URL, config.DATA_DIR = self.old_url, self.old_dir
        self.tmp.cleanup()

    def _close_writer(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None

    def _run(self, **kw):
        lines: list[str] = []
        diff = tool.run(str(self.out), days=len(SCORED), log=lines.append, **kw)
        return diff, lines

    def _csv(self):
        with open(self.out, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    def test_freshly_computed_scores_have_no_diff(self):
        for source in ("recompute", "stored"):
            with self.subTest(tech_source=source):
                diff, lines = self._run(tech_source=source)
                self.assertGreater(diff.compared, 10)
                self.assertEqual(diff.changed, 0)
                self.assertEqual((diff.only_stored, diff.only_new), (0, 0))
                self.assertEqual(self._csv(), [])
                self.assertTrue(any(l.startswith("rows compared") for l in lines))

    def test_stored_row_with_legacy_strategy_points_is_detected(self):
        # Pre-2026-07-10 shape: compute-indicators added S-strategy points into
        # tech_score, and compute-scores carried them into final.  Rebuild one
        # stored row that way through the real production path.
        d, sid = SCORED[2], "3105"
        with db.get_engine().begin() as conn:
            tech_now = conn.execute(text(
                "SELECT tech_score FROM indicators_daily WHERE stock_id=:s AND date=:d"),
                {"s": sid, "d": d}).scalar()
            legacy = [{"code": "S2_BREAKOUT20", "points": 30, "text": "legacy"}]
            conn.execute(text(
                "UPDATE indicators_daily SET tech_score=:t, reasons=:r "
                "WHERE stock_id=:s AND date=:d"),
                {"t": tech_now + 30, "r": json.dumps(legacy), "s": sid, "d": d})
        compute_scores(d.replace("-", ""))
        with db.get_engine().connect() as conn:
            stored = conn.execute(text(
                "SELECT tech_score, final FROM daily_scores WHERE stock_id=:s AND date=:d"),
                {"s": sid, "d": d}).one()
        self.assertEqual(stored.tech_score, tech_now + 30)

        diff, _ = self._run()
        self.assertEqual(diff.changed, 1)
        rows = self._csv()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["date"], row["stock_id"], row["status"]), (d, sid, "changed"))
        self.assertEqual(int(row["diff_tech_score"]), -30)
        self.assertEqual(int(row["new_tech_score"]), tech_now)
        self.assertLess(int(row["diff_final"]), 0)
        self.assertEqual(int(row["stored_final"]), stored.final)
        self.assertEqual(diff.absdiff["tech_score"][30], 1)
        self.assertEqual(diff.top[0][1:3], (d, sid))
        # Reusing the stale indicators reproduces the stale score: that is why
        # technicals are recomputed from prices by default.
        self.assertEqual(self._run(tech_source="stored")[0].changed, 0)

    def _snapshot(self):
        # -shm is SQLite's reader-lock coordination, which a mode=ro WAL reader
        # may touch (see read_only_sqlite); DB and WAL content must not change.
        return {p.name: (p.stat().st_mtime_ns, p.read_bytes())
                for p in self.tmp_path.iterdir()
                if p.name in ("radar.db", "radar.db-wal", "radar.db-journal")}

    def test_never_writes_and_connection_is_read_only(self):
        # 1) Active writer, uncheckpointed WAL frames: DB and WAL untouched.
        before = self._snapshot()
        self.assertGreater(len(before["radar.db-wal"][1]), 32, "fixture must have WAL frames")
        self._run()
        self.assertEqual(self._snapshot(), before)

        # 2) Writer gone (its last close checkpoints and removes the WAL): the DB
        # file is untouched; a WAL a reader has to open must stay empty.
        self._close_writer()
        before = self._snapshot()
        self.assertNotIn("radar.db-wal", before)
        self._run()
        after = self._snapshot()
        self.assertEqual(after["radar.db"], before["radar.db"])
        self.assertEqual(after.get("radar.db-wal", (0, b""))[1], b"")
        self.assertNotIn("radar.db-journal", after)

        engine = get_read_only_sqlite_engine(report_name="t", required_tables=("daily_scores",))
        try:
            with engine.connect() as conn:
                with self.assertRaises(Exception) as ctx:
                    conn.execute(text("UPDATE daily_scores SET final = 0"))
            self.assertIsInstance(ctx.exception.orig, sqlite3.OperationalError)
            self.assertIn("readonly", str(ctx.exception.orig))
        finally:
            engine.dispose()
        self.assertEqual(self.db_path.stat().st_mtime_ns, before["radar.db"][0])

    def test_out_must_not_be_the_database(self):
        with self.assertRaisesRegex(ValueError, "must not be"):
            tool.run(str(self.db_path), days=1, log=lambda s: None)


class DiffAccumulatorTests(unittest.TestCase):
    def _row(self, final, tech=50, **kw):
        r = {f: 0 for f in tool.FIELDS}
        r.update(final=final, tech_score=tech, **kw)
        return r

    def test_crossings_row_set_changes_and_stats(self):
        buf = io.StringIO()
        diff = tool.Diff(csv.writer(buf), threshold=65)
        stored = {"A": self._row(70, 80), "B": self._row(60), "C": self._row(40),
                  "D": self._row(66), "E": self._row(50, warrant_score=None)}
        new = {"A": self._row(60, 60), "B": self._row(65), "C": self._row(40),
               "F": self._row(80), "E": self._row(50, warrant_score=10)}
        self.assertEqual(diff.add_date("2026-10-01", stored, new), (4, 3))
        self.assertEqual((diff.enter, diff.exit), (1, 1))          # B enters, A exits
        self.assertEqual((diff.only_stored, diff.only_stored_listed), (1, 1))   # D
        self.assertEqual((diff.only_new, diff.only_new_listed), (1, 1))         # F
        self.assertEqual(diff.null_mismatch["warrant_score"], 1)
        self.assertEqual(diff.absdiff["final"], Counter({0: 2, 10: 1, 5: 1}))
        self.assertEqual(tool._median(diff.absdiff["final"]), 2.5)
        self.assertEqual(tool._quantile(diff.absdiff["final"], 0.95), 10)
        self.assertEqual([t[2] for t in sorted(diff.top, reverse=True)][:2], ["A", "B"])
        rows = list(csv.DictReader(io.StringIO(buf.getvalue())))
        self.assertEqual({r["stock_id"]: r["status"] for r in rows},
                         {"A": "changed", "B": "changed", "E": "changed",
                          "D": "only_stored", "F": "only_recomputed"})
        self.assertTrue(any("enter 1, exit 1" in l for l in diff.summary_lines()))


if __name__ == "__main__":
    unittest.main()
