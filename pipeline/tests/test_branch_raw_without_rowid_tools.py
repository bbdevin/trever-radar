"""The offline WITHOUT ROWID conversion tools (docs/43) on a small production-layout DB.

Builds the pre-conversion layout (rowid table + PK autoindex + cover index,
rows appended date by date), converts it, and proves verify_db_equivalence
passes — then shows it fails when a single value or a single row differs, and
that the converter refuses the two unsafe inputs.
"""
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from tools import convert_branch_raw_without_rowid as conv
from tools import make_synthetic_branch_db as synth
from tools import verify_db_equivalence as ver


def _quiet(fn, *a, **kw):
    buf = StringIO()
    with redirect_stdout(buf):
        result = fn(*a, **kw)
    return result, buf.getvalue()


class ConvertAndVerifyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.old = cls.dir / "old.db"
        cls.new = cls.dir / "new.db"
        synth.build(cls.old, stocks=8, days=25, branches=12, warrants_per_stock=2)
        _quiet(conv.convert, cls.old, cls.new)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _copy(self, name):
        dst = self.dir / name
        shutil.copyfile(self.new, dst)
        return dst

    def test_old_fixture_has_the_production_layout(self):
        c = sqlite3.connect(self.old)
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master")}
        c.execute("SELECT rowid FROM branch_trades_raw LIMIT 1")  # rowid tables
        c.execute("SELECT rowid FROM daily_prices LIMIT 1")
        c.close()
        self.assertIn("ix_branch_trades_raw_stock_cover", names)
        self.assertIn("sqlite_autoindex_branch_trades_raw_1", names)
        self.assertIn("sqlite_autoindex_daily_prices_1", names)

    def test_converted_db_passes_verification(self):
        ok, out = _quiet(ver.verify, self.old, self.new)
        self.assertTrue(ok, out)
        self.assertIn("RESULT: PASS", out)
        c = sqlite3.connect(self.new)
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master")}
        mode = c.execute("PRAGMA journal_mode").fetchone()[0]
        for table in ("branch_trades_raw", "daily_prices"):
            with self.assertRaises(sqlite3.OperationalError):   # WITHOUT ROWID: no rowid
                c.execute(f"SELECT rowid FROM {table}")
        c.execute("SELECT rowid FROM daily_institutional LIMIT 1")  # untouched tables keep it
        c.close()
        self.assertNotIn("ix_branch_trades_raw_stock_cover", names)
        self.assertIn("ix_daily_prices_date", names)
        self.assertNotIn("ix_branch_trades_raw_date", names)
        self.assertIn("ix_branch_trades_raw_date_cover", names)
        self.assertIn("ix_branch_trades_raw_branch", names)
        self.assertEqual(mode, "wal")

    def test_no_cover_variant_keeps_the_old_date_index(self):
        out_db = self.dir / "new_plain.db"
        _quiet(conv.convert, self.old, out_db, cover=False)
        c = sqlite3.connect(out_db)
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master")}
        c.close()
        self.assertIn("ix_branch_trades_raw_date", names)
        self.assertNotIn("ix_branch_trades_raw_date_cover", names)
        ok, out = _quiet(ver.verify, self.old, out_db, integrity=False, cover=False)
        self.assertTrue(ok, out)
        ok, _ = _quiet(ver.verify, self.old, out_db, integrity=False)   # verified as the cover layout
        self.assertFalse(ok)

    def test_single_db_post_swap_check(self):
        ok, out = _quiet(ver.check_single, self.new, require_stats=False)
        self.assertTrue(ok, out)
        ok, _ = _quiet(ver.check_single, self.new, integrity=False)    # no ANALYZE → no sqlite_stat1
        self.assertFalse(ok)
        ok, _ = _quiet(ver.check_single, self.old, integrity=False, require_stats=False)  # still rowid
        self.assertFalse(ok)

    def test_page_size_and_analyze_variant_passes_with_expected_page_size(self):
        out_db = self.dir / "new_8k.db"
        _quiet(conv.convert, self.old, out_db, page_size=8192, analyze=True)
        ok, out = _quiet(ver.verify, self.old, out_db, expect_page_size=8192, integrity=False)
        self.assertTrue(ok, out)
        self.assertIn("sqlite_stat1: only in NEW", out)
        # ...and the default expectation (OLD's 4096) catches the page-size change
        ok, _ = _quiet(ver.verify, self.old, out_db, integrity=False)
        self.assertFalse(ok)

    def test_converting_only_one_table_is_verified_as_such(self):
        out_db = self.dir / "new_branch_only.db"
        _quiet(conv.convert, self.old, out_db, tables=("branch_trades_raw",))
        ok, out = _quiet(ver.verify, self.old, out_db, tables=("branch_trades_raw",), integrity=False)
        self.assertTrue(ok, out)
        # verifying it as if daily_prices had been converted must fail
        ok, _ = _quiet(ver.verify, self.old, out_db, integrity=False)
        self.assertFalse(ok)

    def _mutate(self, name, sql):
        bad = self._copy(name)
        c = sqlite3.connect(bad, isolation_level=None)
        c.execute(sql)
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        c.close()
        return bad

    def test_one_changed_value_fails(self):
        bad = self._mutate("bad_value.db", """
            UPDATE branch_trades_raw SET net_lots = net_lots + 1
            WHERE (stock_id, date, branch_id) =
                  (SELECT stock_id, date, branch_id FROM branch_trades_raw LIMIT 1 OFFSET 7)""")
        ok, out = _quiet(ver.verify, self.old, bad, integrity=False)
        self.assertFalse(ok)
        self.assertIn("table branch_trades_raw", out.split("RESULT: FAIL")[1])

    def test_one_value_changing_storage_class_fails(self):
        # 5 (INTEGER) vs 5.0 (REAL) must not compare equal.
        bad = self._mutate("bad_type.db", """
            UPDATE daily_prices SET volume = CAST(volume AS REAL) + 0.5
            WHERE (stock_id, date) = (SELECT stock_id, date FROM daily_prices LIMIT 1)""")
        ok, out = _quiet(ver.verify, self.old, bad, integrity=False)
        self.assertFalse(ok)
        self.assertIn("table daily_prices", out.split("RESULT: FAIL")[1])

    def test_one_missing_row_fails(self):
        bad = self._mutate("bad_row.db", """
            DELETE FROM branch_trades_raw WHERE (stock_id, date, branch_id) =
                (SELECT stock_id, date, branch_id FROM branch_trades_raw LIMIT 1)""")
        ok, out = _quiet(ver.verify, self.old, bad, integrity=False)
        self.assertFalse(ok)

    def test_compute_steps_give_identical_tables_on_both_layouts(self):
        """The fixture has same-name branch_keys trading the same stock on the same day,
        inserted in random order — the case that used to depend on row order."""
        from tools import compute_parity
        c = sqlite3.connect(self.old)
        dups = c.execute(
            "SELECT COUNT(*) FROM (SELECT 1 FROM branch_trades_raw r JOIN branch_dim d ON d.id = r.branch_id "
            "GROUP BY r.stock_id, r.date, d.branch_name HAVING COUNT(*) > 1)").fetchone()[0]
        c.close()
        self.assertGreater(dups, 0)
        rc, out = _quiet(compute_parity.main, [
            str(self.old), str(self.new), "--work", str(self.dir / "cparity"),
            "--steps", "compute-branch-stats;branch-point-in-time-persist;"
                       "branch-stock-pctile-counts;compute-scores"])
        self.assertEqual(rc, 0, out)
        self.assertIn("RESULT: PASS", out)

    def test_refuses_to_overwrite_output(self):
        with self.assertRaises(SystemExit):
            _quiet(conv.convert, self.old, self.new)

    def test_refuses_snapshot_with_unmerged_wal(self):
        snap = self.dir / "walsnap.db"
        shutil.copyfile(self.old, snap)
        Path(str(snap) + "-wal").write_bytes(b"x" * 100)
        with self.assertRaises(SystemExit):
            _quiet(conv.convert, snap, self.dir / "walsnap_out.db")

    def test_refuses_already_converted_input(self):
        with self.assertRaises(SystemExit):
            _quiet(conv.convert, self.new, self.dir / "twice.db")


if __name__ == "__main__":
    unittest.main()
