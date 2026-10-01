"""build-branch-cover-index.sh 的結構守則(2026-10-01)。

第一版整晚 12 小時沒建成:權證回補每 3 分鐘試一次鎖、一拿就是 240 分鐘,這支每
5 分鐘才看一次,每個空檔都被先搶走。改用回補的維運暫停檔;而那個檔也是回補自己
在吞吐塌陷時給人看的告警,所以只能刪自己建的那一份。
"""
import re
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "vps" / "scripts" / "build-branch-cover-index.sh"


class CoverIndexScriptTests(unittest.TestCase):
    code = SCRIPT.read_text(encoding="utf-8")

    def idx(self, needle):
        i = self.code.find(needle)
        self.assertNotEqual(i, -1, needle)
        return i

    def test_backfill_is_paused_before_waiting_for_the_lock(self):
        self.assertLess(self.idx(': > "$PAUSE_FILE"'), self.idx("flock -n 9"))

    def test_a_preexisting_pause_file_is_never_removed(self):
        """回補在吞吐塌陷時建的暫停檔是告警,刪了等於把告警靜音。"""
        self.assertIn('if [ ! -e "$PAUSE_FILE" ]; then', self.code)
        self.assertIn("PAUSE_OWNED=1", self.code)
        self.assertRegex(self.code, r'release_pause\(\)\s*\{\s*if \[ "\$PAUSE_OWNED" = 1 \]')
        # 刪暫停檔只能透過 release_pause
        removals = [ln for ln in self.code.splitlines()
                    if 'rm -f "$PAUSE_FILE"' in ln and not ln.lstrip().startswith("#")]
        self.assertEqual(len(removals), 1)
        self.assertIn("PAUSE_OWNED", removals[0])

    def test_every_exit_trap_releases_the_pause(self):
        traps = re.findall(r"^trap '([^']*)' EXIT", self.code, re.M)
        self.assertTrue(traps)
        for t in traps:
            self.assertIn("release_pause", t)

    def test_disk_and_window_guards_precede_the_build(self):
        build = self.idx('db_py "CREATE INDEX IF NOT EXISTS')   # 檔頭註解也提到這句
        self.assertLess(self.idx("NEED_FREE_BYTES"), build)
        self.assertLess(self.idx("minutes_until_next_scheduled_writer"), build)
        self.assertLess(self.idx("pause_bf_containers"), build)

    def test_giving_up_is_written_to_the_log_not_only_notified(self):
        """第一版放棄時只發通知,log 停在「開始等待」,看不出它已經結束。"""
        block = self.code[self.idx("WAIT_UNTIL\" ]"):self.idx("exit 75")]
        self.assertIn("echo", block)


if __name__ == "__main__":
    unittest.main()
