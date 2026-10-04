"""權證分點列保留政策(docs/29 §2.4、docs/44 §6.4,2026-10-04 Planner 定案)。

branch_trades_raw 的 6 碼(權證)列跟 warrant_daily 共用同一條 war_cutoff,嚴格 `<` 刪除;
4 碼(個股/ETF)列永久保留。只在新版面(有 ix_branch_trades_raw_date_cover)啟用。
"""
import hashlib
import io
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import text

import radar.config as config
import radar.db as db
from radar import schema
from radar.prune import prune_db

N_DAYS = 160
WARRANT = "03001P"
STOCK = "2330"


def _trading_days(n):
    out, d = [], date(2026, 1, 1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


DAYS = _trading_days(N_DAYS)
# OFFSET 150 in the DESC list → the 10th oldest day; the 9 days before it are expired.
CUTOFF = DAYS[N_DAYS - 1 - 150]
EXPIRED = [d for d in DAYS if d < CUTOFF]  # ascending


class PruneWarrantBranchesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._old_url, self._old_dir = config.DB_URL, config.DATA_DIR
        config.DATA_DIR = tmp
        config.DB_URL = "sqlite:///" + (tmp / "t.db").as_posix()
        db._engine = None
        db.init_db()

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old_url, self._old_dir
        self._tmp.cleanup()

    # ---- helpers -------------------------------------------------------
    def _seed(self, warrant_dates=None):
        warrant_dates = set(DAYS if warrant_dates is None else warrant_dates)
        with db.get_engine().begin() as conn:
            conn.execute(schema.branch_dim.insert(), [
                {"id": 1, "branch_key": "b1", "broker_id": "9A00", "branch_name": "b1"},
                {"id": 2, "branch_key": "b2", "broker_id": "9A01", "branch_name": "b2"},
            ])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": STOCK, "date": d, "close": 100, "volume": 1, "turnover": 1} for d in DAYS])
            conn.execute(schema.warrant_daily.insert(), [
                {"warrant_id": WARRANT, "date": d, "close": 1, "volume": 1, "turnover": 1} for d in DAYS])
            rows = []
            for i, d in enumerate(DAYS):
                for b in (1, 2):
                    rows.append({"stock_id": STOCK, "date": d, "branch_id": b,
                                 "buy_lots": i, "sell_lots": b, "net_lots": i - b, "pct": 0.1})
                    rows.append({"stock_id": "0050", "date": d, "branch_id": b,
                                 "buy_lots": 1, "sell_lots": 1, "net_lots": 0, "pct": 0.2})
                    if d in warrant_dates:
                        rows.append({"stock_id": WARRANT, "date": d, "branch_id": b,
                                     "buy_lots": 5, "sell_lots": 0, "net_lots": 5, "pct": 1.0})
            conn.execute(schema.branch_trades_raw.insert(), rows)

    def _q(self, sql, **p):
        with db.get_engine().connect() as conn:
            return conn.execute(text(sql), p).fetchall()

    def _warrant_dates(self):
        return [r[0] for r in self._q(
            "SELECT DISTINCT date FROM branch_trades_raw WHERE LENGTH(stock_id)=6 ORDER BY date")]

    def _stock_hash(self):
        rows = self._q("SELECT stock_id, date, branch_id, buy_lots, sell_lots, net_lots, pct "
                       "FROM branch_trades_raw WHERE LENGTH(stock_id)=4 ORDER BY 1, 2, 3")
        return len(rows), hashlib.sha256(repr(rows).encode()).hexdigest()

    def _prune_logs(self):
        return self._q("SELECT date, rows, status, source FROM import_logs "
                       "WHERE dataset='warrant_branch_prune' ORDER BY date")

    def _prune(self, **kw):
        buf = io.StringIO()
        with redirect_stdout(buf):
            info = prune_db(**kw)
        return info, buf.getvalue()

    # ---- tests ---------------------------------------------------------
    def test_keeps_rows_at_or_after_war_cutoff_and_never_touches_stock_rows(self):
        self._seed()
        before = self._stock_hash()
        info, out = self._prune()

        self.assertEqual(self._warrant_dates(), [d for d in DAYS if d >= CUTOFF])
        self.assertEqual(self._stock_hash(), before)
        self.assertEqual(info["warrant_branches"]["deleted_rows"], 2 * len(EXPIRED))
        self.assertEqual(info["warrant_branches"]["dates"], EXPIRED[::-1])  # newest → oldest
        self.assertIsNone(info["warrant_branches"]["skipped_reason"])
        self.assertIsNotNone(info["warrant_branches"]["freelist_count"])
        self.assertFalse(info["dry_run"])
        self.assertIn(f"prune warrant-branch rows date={EXPIRED[-1]} deleted=2 elapsed=", out)

    def test_shares_the_warrant_daily_cutoff(self):
        """回歸鎖:權證分點列與 warrant_daily 的邊界必須是同一天。"""
        self._seed()
        self._prune()
        wd_min = self._q("SELECT MIN(date) FROM warrant_daily")[0][0]
        self.assertEqual(wd_min, CUTOFF)
        self.assertEqual(self._warrant_dates()[0], wd_min)

    def test_one_import_log_row_per_deleted_date(self):
        self._seed()
        self._prune()
        logs = self._prune_logs()
        self.assertEqual([r[0] for r in logs], EXPIRED)
        self.assertTrue(all(r[1] == 2 and r[2] == "ok" and r[3] == "prune" for r in logs))

    def test_max_dates_batches_newest_first_and_continues_next_run(self):
        self._seed()
        info, _ = self._prune(max_dates=2)
        self.assertEqual(info["warrant_branches"]["dates"], [EXPIRED[-1], EXPIRED[-2]])
        self.assertEqual(self._warrant_dates(), EXPIRED[:-2] + [d for d in DAYS if d >= CUTOFF])

        info, _ = self._prune(max_dates=2)
        self.assertEqual(info["warrant_branches"]["dates"], [EXPIRED[-3], EXPIRED[-4]])
        self.assertEqual(self._warrant_dates()[:len(EXPIRED) - 4], EXPIRED[:-4])

    def test_stops_after_three_consecutive_empty_dates(self):
        # newest→oldest over EXPIRED: e8 empty, e7 has rows, e6/e5/e4 empty → stop; e3.. untouched
        e = EXPIRED
        missing = {e[8], e[6], e[5], e[4]}
        self._seed(warrant_dates=[d for d in DAYS if d not in missing])
        info, _ = self._prune()
        self.assertEqual(info["warrant_branches"]["dates"], [e[7]])
        remaining = self._warrant_dates()
        self.assertNotIn(e[7], remaining)
        for d in e[:4]:
            self.assertIn(d, remaining)

    def test_dry_run_writes_nothing(self):
        self._seed()
        tables = ["branch_trades_raw", "warrant_daily", "indicators_daily", "import_logs"]
        before = {t: self._q(f"SELECT COUNT(*) FROM {t}")[0][0] for t in tables}
        info, out = self._prune(dry_run=True)
        after = {t: self._q(f"SELECT COUNT(*) FROM {t}")[0][0] for t in tables}
        self.assertEqual(before, after)
        self.assertEqual(self._prune_logs(), [])
        self.assertTrue(info["dry_run"])
        self.assertEqual(info["warrants"], len(EXPIRED))
        self.assertEqual(info["warrant_branches"]["deleted_rows"], 2 * len(EXPIRED))
        self.assertIn("would delete", out)

    def test_old_layout_without_date_cover_is_skipped(self):
        self._seed()
        with db.get_engine().begin() as conn:
            conn.execute(text("DROP INDEX ix_branch_trades_raw_date_cover"))
        info, out = self._prune()
        self.assertEqual(info["warrant_branches"]["skipped_reason"],
                         "no ix_branch_trades_raw_date_cover")
        self.assertIn("warrant-branch prune skipped: no ix_branch_trades_raw_date_cover", out)
        self.assertEqual(self._warrant_dates(), DAYS)
        self.assertEqual(self._prune_logs(), [])
        # warrant_daily still pruned as before
        self.assertEqual(self._q("SELECT MIN(date) FROM warrant_daily")[0][0], CUTOFF)

    def test_zero_disables(self):
        self._seed()
        info, out = self._prune(warrant_branches_days=0)
        self.assertIsNotNone(info["warrant_branches"]["skipped_reason"])
        self.assertIn("warrant-branch prune skipped", out)
        self.assertEqual(self._warrant_dates(), DAYS)


if __name__ == "__main__":
    unittest.main()
