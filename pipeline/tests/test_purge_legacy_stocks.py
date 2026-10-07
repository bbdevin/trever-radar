# -*- coding: utf-8 -*-
"""docs/44 §3.2 步驟 ③:一次性刪掉頂層舊單一檔 stocks/{id}.json。

只刪 stocks/ 這一層的 *.json;core/chips/hist(含 hist/index.json)一律不碰;
預設 dry-run;core 檔數少於要刪的舊檔數就拒絕。
"""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from tools import purge_legacy_stocks as purge


def _tree(root: Path, *, legacy: int, core: int) -> Path:
    stocks = root / "stocks"
    for d in ("core", "chips", "hist"):
        (stocks / d).mkdir(parents=True)
    for i in range(legacy):
        (stocks / f"{1000 + i}.json").write_text("x" * 10, encoding="utf-8")
    for i in range(core):
        (stocks / "core" / f"{1000 + i}.json").write_text("{}", encoding="utf-8")
        (stocks / "chips" / f"{1000 + i}.json").write_text("{}", encoding="utf-8")
    (stocks / "hist" / "1000.deadbeef.json").write_text("{}", encoding="utf-8")
    (stocks / "hist" / "index.json").write_text("{}", encoding="utf-8")
    return stocks


def _run(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = purge.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class PurgeLegacyStocksTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _split_files(self, stocks: Path) -> list[str]:
        return sorted(p.relative_to(stocks).as_posix()
                      for p in stocks.rglob("*.json") if p.parent != stocks)

    def test_dry_run_by_default_deletes_nothing(self):
        stocks = _tree(self.root, legacy=3, core=3)
        code, out, _ = _run(str(self.root))
        self.assertEqual(code, 0)
        self.assertIn("mode=dry-run", out)
        self.assertIn("legacy_files=3 legacy_bytes=30", out)
        self.assertEqual(len(list(stocks.glob("*.json"))), 3)

    def test_write_deletes_only_top_level_json(self):
        stocks = _tree(self.root, legacy=3, core=3)
        (stocks / "notes.txt").write_text("keep", encoding="utf-8")
        before = self._split_files(stocks)
        code, out, _ = _run(str(self.root), "--write")
        self.assertEqual(code, 0)
        self.assertIn("deleted=3 freed_bytes=30", out)
        self.assertEqual(list(stocks.glob("*.json")), [])
        self.assertEqual(self._split_files(stocks), before)       # core/chips/hist/index.json 原封不動
        self.assertIn("hist/index.json", before)
        self.assertTrue((stocks / "notes.txt").exists())

    def test_refuses_when_core_has_fewer_files_than_legacy(self):
        stocks = _tree(self.root, legacy=3, core=2)
        code, _, err = _run(str(self.root), "--write")
        self.assertEqual(code, 2)
        self.assertIn("REFUSED", err)
        self.assertEqual(len(list(stocks.glob("*.json"))), 3)

    def test_refuses_when_core_is_missing(self):
        stocks = self.root / "stocks"
        stocks.mkdir()
        (stocks / "2330.json").write_text("{}", encoding="utf-8")
        code, _, err = _run(str(self.root), "--write")
        self.assertEqual(code, 2)
        self.assertTrue((stocks / "2330.json").exists())

    def test_nothing_to_delete_is_success(self):
        _tree(self.root, legacy=0, core=2)
        code, out, _ = _run(str(self.root), "--write")
        self.assertEqual(code, 0)
        self.assertIn("nothing to delete", out)

    def test_missing_stocks_dir_is_an_error(self):
        code, _, _ = _run(str(self.root))
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
