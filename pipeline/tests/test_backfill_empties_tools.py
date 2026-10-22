"""tools/probe_backfill_empties.py(report,不連網)與 tools/unrecord_warrant_empties.py:
撤銷工具預設 dry-run、不碰 DB、apply 才改檔且留備份;範圍與 --scope 只動該動的 empty。"""
import contextlib
import io
import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import radar.config as config
from tools import probe_backfill_empties as probe
from tools import unrecord_warrant_empties as unrec


class BackfillEmptiesToolsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.db = self.tmp / "radar.db"
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE warrants (id TEXT PRIMARY KEY, market TEXT, maturity_date TEXT)")
        conn.executemany("INSERT INTO warrants VALUES (?,?,?)", [
            ("LIVE", "twse", "2099-01-01"), ("GONE", "tpex", "2020-01-01"), ("OKW", "twse", None)])
        conn.commit()
        conn.close()
        self.base = self.tmp / "wb.json"
        self.state = {"version": 1, "date": "2026-08-12", "market": "all", "target_hash": "h",
                      "target_count": 3, "results": {
                          "LIVE": {"status": "empty", "error": "no branch rows @https://a.example bytes=9"},
                          "GONE": {"status": "empty", "error": "old msg"},
                          "OKW": {"status": "ok", "rows": 5}}}
        self.path = self.tmp / "wb-2026-08-12-all.json"
        self.path.write_text(json.dumps(self.state), encoding="utf-8")
        # 範圍外的日期:不可以被動到。
        self.other = self.tmp / "wb-2026-07-01-all.json"
        self.other.write_text(json.dumps(dict(self.state, date="2026-07-01")), encoding="utf-8")
        self.db_before = self.db.read_bytes()
        # 寫 state 用 importer 的 _atomic_json_write,它會先確認目標不是設定中的 DB。
        self._old_url = config.DB_URL
        config.DB_URL = "sqlite:///" + self.db.as_posix()

    def tearDown(self):
        config.DB_URL = self._old_url
        self._tmp.cleanup()

    def _run(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = unrec.run(["--state-base", str(self.base), "--db", str(self.db),
                            "--from", "2026-08-01", "--to", "2026-08-31", *extra])
        return rc, out.getvalue()

    def test_dry_run_is_the_default_and_changes_nothing(self):
        before = self.path.read_bytes()
        rc, out = self._run("--scope", "live")
        self.assertEqual(rc, 0)
        self.assertIn("dry-run", out)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.tmp.glob("*.pre-unrecord-*")), [])

    def test_apply_removes_only_selected_empties_and_keeps_a_backup(self):
        rc, _ = self._run("--scope", "live", "--apply")
        self.assertEqual(rc, 0)
        res = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertNotIn("LIVE", res["results"], "撤銷 = 移除,下次回補當 pending 重抓")
        self.assertEqual(res["results"]["GONE"]["status"], "empty", "已到期的不在 live 範圍")
        self.assertEqual(res["results"]["OKW"]["status"], "ok")
        self.assertEqual(res["unrecorded"][0]["count"], 1)
        backups = list(self.tmp.glob("wb-2026-08-12-all.json.pre-unrecord-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(json.loads(backups[0].read_text(encoding="utf-8")), self.state)
        self.assertEqual(json.loads(self.other.read_text(encoding="utf-8"))["results"]["LIVE"]["status"],
                         "empty", "範圍外日期不動")
        self.assertEqual(self.db.read_bytes(), self.db_before, "DB 只讀")

    def test_host_filter(self):
        self._run("--host-contains", "b.example", "--apply")
        res = json.loads(self.path.read_text(encoding="utf-8"))["results"]
        self.assertEqual(res["LIVE"]["status"], "empty")
        self._run("--host-contains", "a.example", "--apply")
        res = json.loads(self.path.read_text(encoding="utf-8"))["results"]
        self.assertNotIn("LIVE", res)
        self.assertIn("GONE", res)

    def test_report_splits_empties_by_market_and_expiry(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            probe.main(["report", "--state-base", str(self.base), "--db", str(self.db),
                        "--from", "2026-08-01", "--to", "2026-08-31"])
        text = out.getvalue()
        self.assertIn("2026-08-12", text)
        self.assertNotIn("2026-07-01", text)
        self.assertIn("empty twse=1 tpex=1 expired_now=1 live=1", text)
        self.assertIn("a.example: 1", text)
        self.assertEqual(self.db.read_bytes(), self.db_before)


if __name__ == "__main__":
    unittest.main()
