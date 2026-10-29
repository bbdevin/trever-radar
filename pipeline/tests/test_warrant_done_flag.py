"""權證分點回補的每日增量(2026-10-29,docs/30 §6.2):完成標記只代表「今天已完成」。

事故:10-25 補完 70 日深度後寫了空的完成標記,之後永久略過;10-27 起新的交易日只剩
日更輪的成交 ≥ 100 萬權證池(~580 檔 vs 全市場 ~1.6 萬檔)。現在標記內容是完成那天的
台北日期,隔天自動重問;由 crontab 每 20 分呼叫。"""
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FUNC = REPO_ROOT / "vps" / "scripts" / "warrant-done-flag.sh"
SCRIPT = REPO_ROOT / "vps" / "scripts" / "warrant-backfill.sh"
CRONTAB = REPO_ROOT / "vps" / "scripts" / "crontab.example"


def _bash_path(p: Path) -> str:
    s = str(p)
    if sys.platform == "win32" and re.match(r"^[A-Za-z]:\\", s):
        return "/mnt/" + s[0].lower() + s[2:].replace("\\", "/")
    return s


def _bash_ok() -> bool:
    if shutil.which("bash") is None:
        return False
    try:
        r = subprocess.run(["bash", "-c", "true"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


@unittest.skipUnless(_bash_ok(), "需要 bash(Windows 上是 WSL)")
class DoneForTodayHarness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.flag = Path(self.tmp.name) / "done-70d"

    def tearDown(self):
        self.tmp.cleanup()

    def done(self, today: str) -> bool:
        cmd = (f'set -euo pipefail; source "{_bash_path(FUNC)}"; '
               f'if warrant_done_for_today "{_bash_path(self.flag)}" "{today}"; then echo yes; else echo no; fi')
        r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip() == "yes"

    def test_missing_flag_is_not_done(self):
        self.assertFalse(self.done("2026-10-29"))

    def test_legacy_empty_flag_is_not_done(self):
        # 10-25 留下的空標記:不再代表永久完成,下一次照跑(補 10-27 起的新交易日)。
        self.flag.write_text("", encoding="utf-8")
        self.assertFalse(self.done("2026-10-29"))

    def test_yesterday_flag_is_not_done(self):
        self.flag.write_text("2026-10-28\n", encoding="utf-8")
        self.assertFalse(self.done("2026-10-29"))

    def test_today_flag_is_done(self):
        self.flag.write_text("2026-10-29\n", encoding="utf-8")
        self.assertTrue(self.done("2026-10-29"))

    def test_flag_without_trailing_newline_still_matches(self):
        self.flag.write_text("2026-10-29", encoding="utf-8")
        self.assertTrue(self.done("2026-10-29"))


class ScriptWiringTest(unittest.TestCase):
    def setUp(self):
        self.code = "\n".join(l for l in SCRIPT.read_text(encoding="utf-8").splitlines()
                              if not l.lstrip().startswith("#"))

    def test_script_sources_the_helper_and_uses_it(self):
        self.assertIn('source "$(dirname "$0")/warrant-done-flag.sh"', self.code)
        self.assertIn('warrant_done_for_today "$DONE_FLAG" "$TODAY"', self.code)
        # 舊的「存在即永久略過」不能回來。
        self.assertNotIn('if [ -f "$DONE_FLAG" ]; then\n  echo', self.code)

    def test_completion_writes_today_and_notifies_only_the_first_time(self):
        i_notify = self.code.index('if [ ! -f "$DONE_FLAG" ]; then')
        i_write = self.code.index('printf \'%s\\n\' "$TODAY" > "$DONE_FLAG"')
        self.assertLess(i_notify, i_write, "通知判斷要在寫標記之前,否則每天都會通知")
        block = self.code[i_notify:i_write]
        self.assertIn("notify_ok", block)
        self.assertIn("fi", block)

    def test_today_is_taken_before_the_skip_check(self):
        self.assertLess(self.code.index('TODAY="$(taipei_date +%F)"'),
                        self.code.index('warrant_done_for_today "$DONE_FLAG"'))


class CrontabTest(unittest.TestCase):
    def test_crontab_example_drives_the_backfill_every_20_minutes(self):
        active = [l for l in CRONTAB.read_text(encoding="utf-8").splitlines()
                  if l.strip() and not l.lstrip().startswith("#")]
        hits = [l for l in active if "vps/scripts/warrant-backfill.sh" in l]
        self.assertEqual(len(hits), 1, hits)
        self.assertTrue(hits[0].startswith("*/20 * * * *"), hits[0])
        self.assertIn(">> /home/huang/warrant-backfill.log", hits[0])


if __name__ == "__main__":
    unittest.main()
