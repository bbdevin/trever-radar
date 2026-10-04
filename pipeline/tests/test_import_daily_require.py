# -*- coding: utf-8 -*-
"""`import-daily --require src:ds[:minfrac]` 的離開碼(docs/47 原則 1「輪詢到公布為止」)。

0  = 被要求的資料集全部 ok 且 rows>0(有 minfrac 時另須 ≥ minfrac × 前一個有資料日的 ok 列數)
75 = 至少一個還沒到(已寫入的照留,輪詢的 shell 放鎖、睡、再試)
1  = 任何 error(TPEx 520 例外:只有 tpex:quotes 被要求時才算「還沒到」)

import_daily 一律 stub 掉(不連網);previous_ok_rows 另以暫存 SQLite 驗它真的讀 import_logs。
"""
import contextlib
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import radar.config as config
import radar.db as db
from radar import cli, importer, schema

DATE = "20261002"


def _r(source, dataset, status="ok", rows=1000, **extra):
    return {"source": source, "dataset": dataset, "status": status, "rows": rows, **extra}


TPEX_520 = _r("tpex", "quotes", "error", 0, error="HTTP 520", error_kind="http", status_code=520)


def _exit(results, datasets, require, baseline=None):
    out, err = io.StringIO(), io.StringIO()
    with patch("radar.importer.import_daily", return_value=results), \
         patch("radar.importer.previous_ok_rows", return_value=baseline), \
         contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
         _CatchExit() as caught:
        cli.cmd_import_daily(SimpleNamespace(date=DATE, datasets=datasets, require=require))
    return caught.code, err.getvalue()


class _CatchExit:  # capture SystemExit and expose its code
    code = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is SystemExit:
            self.code = exc.code
            return True
        return False


class RequireExitCodes(unittest.TestCase):
    def test_required_dataset_empty_is_75(self):
        code, err = _exit([_r("twse", "quotes", "empty", 0), _r("tpex", "quotes", "empty", 0)],
                          "quotes", "twse:quotes")
        self.assertEqual(code, 75)
        self.assertIn("twse:quotes", err)

    def test_required_dataset_ok_is_0_even_if_another_source_is_empty(self):
        code, _ = _exit([_r("twse", "quotes"), _r("tpex", "quotes", "empty", 0)],
                        "quotes", "twse:quotes")
        self.assertEqual(code, 0)

    def test_below_minfrac_of_previous_day_is_75(self):
        code, err = _exit([_r("twse", "quotes"), _r("tpex", "quotes", rows=700)],
                          "quotes", "tpex:quotes:0.8", baseline=1000)
        self.assertEqual(code, 75)
        self.assertIn("previous 1000", err)

    def test_at_or_above_minfrac_is_0(self):
        code, _ = _exit([_r("twse", "quotes"), _r("tpex", "quotes", rows=800)],
                        "quotes", "tpex:quotes:0.8", baseline=1000)
        self.assertEqual(code, 0)

    def test_no_baseline_means_no_ratio_check(self):
        code, _ = _exit([_r("twse", "quotes"), _r("tpex", "quotes", rows=1)],
                        "quotes", "tpex:quotes:0.8", baseline=None)
        self.assertEqual(code, 0)

    def test_both_sources_required_one_missing_is_75(self):
        code, _ = _exit([_r("twse", "insti", "empty", 0), _r("tpex", "insti")],
                        "insti", "twse:insti,tpex:insti")
        self.assertEqual(code, 75)

    def test_a_real_error_is_still_1(self):
        code, _ = _exit([_r("twse", "insti", "error", 0, error="boom"), _r("tpex", "insti")],
                        "insti", "twse:insti,tpex:insti")
        self.assertEqual(code, 1)

    def test_tpex_520_is_pending_when_tpex_quotes_is_required(self):
        code, _ = _exit([_r("twse", "quotes"), TPEX_520], "quotes", "tpex:quotes:0.8",
                        baseline=1000)
        self.assertEqual(code, 75)

    def test_tpex_520_is_ignored_when_only_twse_is_required(self):
        code, _ = _exit([_r("twse", "quotes"), TPEX_520], "quotes", "twse:quotes")
        self.assertEqual(code, 0)

    def test_without_require_the_legacy_codes_are_unchanged(self):
        code, _ = _exit([_r("twse", "quotes"), TPEX_520], "quotes", None)
        self.assertEqual(code, 75, "舊的 tpex_520_only 75 不得被改動")
        code, _ = _exit([_r("twse", "quotes", "empty", 0), _r("tpex", "quotes", "empty", 0)],
                        "quotes", None)
        self.assertEqual(code, 0, "沒給 --require 時 empty 仍是 0(舊行為)")

    def test_require_outside_datasets_is_rejected(self):
        code, _ = _exit([], "quotes", "twse:insti")
        self.assertIsInstance(code, str)
        self.assertIn("--datasets", code)

    def test_bad_spec_is_rejected(self):
        for spec in ("twse", "nyse:quotes", "twse:foo", "twse:quotes:1.5", "twse:quotes:x"):
            with self.subTest(spec=spec):
                code, _ = _exit([], "quotes", spec)
                self.assertIsInstance(code, str)


class PreviousOkRows(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._old = config.DB_URL, config.DATA_DIR
        config.DATA_DIR = tmp
        config.DB_URL = "sqlite:///" + (tmp / "t.db").as_posix()
        db._engine = None
        db.init_db()

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old
        self._tmp.cleanup()

    def _log(self, date, rows, status="ok", source="tpex", dataset="quotes"):
        with db.get_engine().begin() as conn:
            conn.execute(schema.import_logs.insert().values(
                run_at="2026-10-01T15:00:00+08:00", source=source, dataset=dataset,
                date=date, rows=rows, status=status))

    def test_reads_the_latest_previous_day_and_its_max_ok_rows(self):
        self._log("2026-09-29", 900)
        self._log("2026-10-01", 0, status="empty")
        self._log("2026-10-01", 812)
        self._log("2026-10-01", 820)
        self._log("2026-10-02", 5000)            # same day: not a baseline
        self._log("2026-10-01", 9999, source="twse")  # other source
        self.assertEqual(importer.previous_ok_rows("tpex", "quotes", DATE), 820)

    def test_none_without_history(self):
        self.assertIsNone(importer.previous_ok_rows("tpex", "quotes", DATE))


if __name__ == "__main__":
    unittest.main()
