"""`vps/scripts/daily-branches.sh` 的離開碼判斷與完成標記,由原始碼直接解析。

背景:`import-branch-trades` 走的是 `_run` 的「never raise」路徑——它把
status='error' 記進 import_logs 之後仍然 return 0。這支腳本以前是裸的一行
呼叫,於是 `set -e` 看不到任何異常,compute → export → deploy 整條照跑,
把一批自己知道有問題的資料送上線。2026-09-14 22:54 就是這樣上線的
(rows=57265 status=error,理由 "1 stocks failed")。

修法不是「有錯就全擋」:那一天 1,988 檔裡只有 1 檔沒抓到,withhold 一整天
正確的 1,987 檔比讓那 1 檔的分點面板晚一天更糟,而且次日 17:40 會冪等補齊。
所以由 CLI 的離開碼分級,shell 顯式分支:

    0   全部標的都回來
    75  個別標的失敗、當日覆蓋率仍在帶內      → 上線,留紀錄
    76  這一輪一筆都沒抓到(來源掛了)         → 上線(當日可能已被前一輪填滿),叫醒人
    其他 覆蓋率掉出帶狀範圍                    → 不重算、不上線

和 test_safe_branch_stats_script.py / test_repair_window_script.py 同一手法:
不執行腳本(它要 docker、要 SQLite),要守住的性質全部寫在文字裡。
"""
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "vps" / "scripts" / "daily-branches.sh"
LIB = REPO_ROOT / "vps" / "scripts" / "lib.sh"

FULL_LINE_COMMENT = re.compile(r"^\s*#")
TRAILING_COMMENT = re.compile(r"(?<=\s)#.*$")


def _code_lines(path: Path) -> list[str]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if FULL_LINE_COMMENT.match(line):
            out.append("")
        else:
            out.append(TRAILING_COMMENT.sub("", line))
    return out


class TestDailyBranchesExitCodes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lines = _code_lines(SCRIPT)
        cls.code = "\n".join(cls.lines)
        cls.lib = "\n".join(_code_lines(LIB))

    def _index(self, needle: str) -> int:
        idx = self.code.find(needle)
        self.assertNotEqual(idx, -1, f"找不到 {needle!r}")
        return idx

    def test_exit_code_is_captured_explicitly_not_left_to_set_e(self):
        """必須 set +e 取 rc 再 set -e。

        靠 `set -e` 是不行的:它對 75 跟對 1 一樣直接中止,於是「可以上線」被
        當成「不可以上線」——方向剛好相反,而且是靜默的。
        """
        imp = self._index("radar import-branch-trades")
        before = self.code[max(0, imp - 400):imp]
        after = self.code[imp:imp + 200]
        self.assertIn("set +e", before, "取 rc 之前要先關掉 set -e")
        self.assertIn("branch_rc=$?", after, "要顯式接住離開碼")
        self.assertIn("set -e", self.code[imp:imp + 400], "取完 rc 要立刻恢復 set -e")

    def test_all_four_outcomes_are_handled(self):
        case_idx = self._index("case \"$branch_rc\"")
        block = self.code[case_idx:case_idx + 900]
        for arm in ("0)", "75)", "76)", "*)"):
            with self.subTest(arm=arm):
                self.assertIn(arm, block, f"離開碼 {arm} 沒有被處理")

    def test_75_and_76_continue_and_only_the_default_arm_exits(self):
        case_idx = self._index("case \"$branch_rc\"")
        block = self.code[case_idx:case_idx + 900]
        self.assertIn('exit "$branch_rc"', block, "不合格的那一支要中止整輪")
        # 唯一的 exit 必須落在 *) 這一支:75/76 若也 exit,就等於為了個別標的
        # 失敗而 withhold 一整天,正是這次要修掉的錯誤方向。
        default_arm = block[block.index("*)"):]
        self.assertIn('exit "$branch_rc"', default_arm)
        self.assertEqual(block.count('exit "$branch_rc"'), 1,
                         "只有 *) 那一支可以 exit;75/76 必須繼續")

    def test_76_is_high_priority_and_75_is_not(self):
        """76 = 來源整輪掛掉,要叫醒人;75 = 個別標的失敗,留紀錄即可。

        兩者都繼續上線,所以通知等級是它們唯一的差別——壓成同一級就等於把
        「來源死了」藏進日常雜訊裡。
        """
        case_idx = self._index("case \"$branch_rc\"")
        block = self.code[case_idx:case_idx + 900]
        arm75 = block[block.index("75)"):block.index("76)")]
        arm76 = block[block.index("76)"):block.index("*)")]
        self.assertIn("notify_warn", arm75, "75 用一般等級")
        self.assertNotIn("high", arm75)
        self.assertIn("high", arm76, "76 必須是 high,來源掛掉要叫醒人")

    def test_completion_marker_is_written_only_after_deploy(self):
        """完成標記是給夜間備援作業讀的,寫早了就是承諾一件還沒發生的事。"""
        deploy = self._index("deploy_data")
        marker = self._index("branch_round_marker")
        self.assertGreater(marker, deploy,
                           "標記必須在 deploy_data 之後才寫")
        compute = self._index("radar compute-branch-stats")
        self.assertGreater(marker, compute)

    def test_marker_path_is_shared_with_the_nightly_job(self):
        """兩支腳本必須用同一個函式產生路徑,各自寫死字串遲早會漂移。"""
        self.assertIn("branch_round_marker()", self.lib,
                      "路徑慣例應該放在 lib.sh")
        nightly = (REPO_ROOT / "vps" / "scripts" / "safe-branch-stats.sh").read_text(encoding="utf-8")
        self.assertIn("branch_round_marker", nightly,
                      "夜間作業要用同一個函式讀標記")
        self.assertNotIn("/tmp/radar-branch-round-", "\n".join(self.lines),
                         "daily-branches 不該自己寫死標記路徑")

    def test_marker_content_is_a_timestamp(self):
        """標記內容要是時間,不能只是空檔案——夜間作業靠它跟 run_at 比大小。"""
        marker_line = next(ln for ln in self.lines if "branch_round_marker" in ln)
        self.assertIn("taipei_date", marker_line,
                      "標記內容應該是台北時區的 ISO 時間")


if __name__ == "__main__":
    unittest.main()
