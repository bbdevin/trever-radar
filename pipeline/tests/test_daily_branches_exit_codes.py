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
        self.assertIn("set +e", before, "取 rc 之前要先關掉 set -e")
        self.assertIn("set -e", self.code[imp:imp + 400], "取完 rc 要立刻恢復 set -e")

        # `$?` 只保留「上一個」指令的離開碼。中間插進任何一行——哪怕是 echo——
        # 都會把它洗掉,而且洗掉之後腳本照跑、測試照過、只有離開碼靜默變成 0,
        # 也就是「不合格的一天」會被當成「完全正常」送上線。所以這裡驗的是
        # **緊鄰**,不是「附近找得到」。
        idx = next(i for i, ln in enumerate(self.lines)
                   if "radar import-branch-trades" in ln)
        following = [ln.strip() for ln in self.lines[idx + 1:] if ln.strip()]
        self.assertTrue(following, "import 之後應該還有東西")
        self.assertEqual(following[0], "branch_rc=$?",
                         "`branch_rc=$?` 必須緊接在 import 之後,中間不可以有任何指令")

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

    def test_marker_is_named_for_the_round_date_captured_at_start(self):
        """標記檔名用的日期必須在**開跑時**取,不能等收工才算。

        實測 2026-09-15 那輪:22:00 起跑,compute-branch-stats 跑了 74 分鐘,
        deploy 收在隔天 00:25。用收工當下的日曆日命名會得到 `2026-09-16`,
        而夜間作業找的是 `2026-09-15`,標記永遠對不上 —— 而「跨過午夜」正是
        這個標記存在的理由(夜間作業 00:05 撞上的就是還沒收工的那一輪)。
        它在容易的情況下能動,在唯一需要它的情況下失效。
        """
        capture = next((i for i, ln in enumerate(self.lines)
                        if ln.strip().startswith("ROUND_DATE=")), None)
        self.assertIsNotNone(capture, "應該在開頭就把本輪日期定下來")
        self.assertIn("taipei_date +%F", self.lines[capture])

        imp = next(i for i, ln in enumerate(self.lines)
                   if "radar import-branch-trades" in ln)
        self.assertLess(capture, imp, "日期要在任何長工作之前就取好")

        marker_line = next(ln for ln in self.lines if "branch_round_marker" in ln)
        self.assertIn("$ROUND_DATE", marker_line,
                      "標記必須用開跑時定下的日期")
        self.assertNotIn("$(taipei_date +%F)", marker_line,
                         "不可以在寫標記的當下才算日曆日 —— 跨午夜就會錯")

    # ── BRANCH_ROUND_MODE:22:00 那輪只匯入 ────────────────────────────
    def _mode_guard(self) -> int:
        """import 模式那道守衛在原始碼裡的位置。"""
        return self._index('if [ "$BRANCH_ROUND_MODE" = "import" ]')

    def test_mode_defaults_to_the_full_chain_when_unset(self):
        """未設環境變數(手動執行、17:40 那輪)必須跟改動前一模一樣。

        預設值寫成 `:-full`,而守衛比的是 `= "import"`:兩邊都要求「只有明確
        設成 import 才縮短」,任何拼錯、空字串、其他值都落回完整鏈——縮短是
        要明講的決定,不能因為變數沒傳到就靜默發生(那會讓網站整天不更新)。
        """
        decl = next((ln for ln in self.lines
                     if ln.strip().startswith("BRANCH_ROUND_MODE=")), None)
        self.assertIsNotNone(decl, "應該在開頭把模式定下來")
        self.assertIn('${BRANCH_ROUND_MODE:-full}', decl,
                      "未設時的預設必須是完整鏈")
        guard_line = next(ln for ln in self.lines if "BRANCH_ROUND_MODE" in ln
                          and "if" in ln)
        self.assertIn('= "import"', guard_line,
                      "守衛要是『等於 import 才縮短』,不能是『不等於 full 就縮短』")

    def test_import_only_mode_does_not_write_the_completion_marker(self):
        """這是整組改動裡最重要的一條。

        標記的意思是「算完**而且**上線了」。只匯入的那一輪兩件都沒做;若它也
        寫標記,00:05 的夜間備援作業會看到標記而整夜略過,於是這一天從頭到尾
        沒有任何一輪算過分點統計——備援在唯一需要它的情況下被自己關掉。
        """
        guard = self._mode_guard()
        marker = self._index("branch_round_marker")
        self.assertGreater(marker, guard,
                           "寫標記必須在 import 模式離開之後,只匯入的那輪不得寫")
        # 守衛與離開之間不可以夾帶寫標記的動作。
        block = self.code[guard:self.code.index("fi", guard)]
        self.assertIn("exit 0", block, "import 模式要在這裡結束本輪")
        self.assertNotIn("branch_round_marker", block)

    def test_import_only_mode_skips_every_compute_and_publish_step(self):
        """只匯入的那一輪不得重算、不得匯出、不得上線。"""
        guard = self._mode_guard()
        for step in (
            "radar compute-branch-stats",
            "radar compute-scores",
            "radar compute-performance",
            "radar export-json",
            "radar prune",
            "deploy_data",
        ):
            with self.subTest(step=step):
                self.assertGreater(
                    self._index(step), guard,
                    f"{step} 必須落在 import 模式離開之後",
                )

    def test_import_only_mode_still_runs_the_imports(self):
        """只匯入不等於什麼都不做:22:00 這一輪存在的理由就是把當晚較晚才
        補齊的分點與法人資料寫進 DB。"""
        guard = self._mode_guard()
        for step in (
            "radar import-daily --datasets quotes,insti",
            "radar compute-indicators",
            "radar seed-branches",
            "radar import-branch-trades",
        ):
            with self.subTest(step=step):
                self.assertLess(
                    self._index(step), guard,
                    f"{step} 在兩個模式都要跑,必須在模式守衛之前",
                )

    def test_exit_code_branching_is_one_implementation_shared_by_both_modes(self):
        """0/75/76/其他 的分級只能有一份,而且要在模式分岔**之前**。

        複製成兩份(完整鏈一份、import 一份)是最容易發生也最難發現的退化:
        兩份會漂移,漂移的後果是某一個模式悄悄把不合格的一天當成正常照跑。
        """
        self.assertEqual(self.code.count('case "$branch_rc"'), 1,
                         "離開碼分級只能有一份實作")
        self.assertEqual(self.code.count("branch_rc=$?"), 1,
                         "取離開碼也只能有一處")
        case_idx = self._index('case "$branch_rc"')
        guard = self._mode_guard()
        self.assertLess(case_idx, guard,
                        "case 必須在模式分岔之前,兩個模式才走得到同一份")
        # 匯入到 case 收尾之間不得出現任何模式判斷,否則就是把分級藏進某一個模式裡。
        imp = self._index("radar import-branch-trades")
        esac = self.code.index("esac", case_idx)
        self.assertNotIn("BRANCH_ROUND_MODE", self.code[imp:esac],
                         "離開碼分級不得被模式條件包住")

    def test_import_only_success_notification_says_nothing_was_published(self):
        """通知要講清楚「只匯入、沒上線」,否則值班的人會以為網站更新了。"""
        guard = self._mode_guard()
        block = self.code[guard:self.code.index("fi", guard)]
        self.assertIn("notify_ok", block, "只匯入也算本輪成功,要發成功通知")
        self.assertRegex(block, r"僅匯入|只匯入", "通知要說明本輪只做了匯入")
        self.assertIn("未上線", block, "通知要明講沒有上線")

    def test_marker_content_is_a_timestamp(self):
        """標記內容要是時間,不能只是空檔案——夜間作業靠它跟 run_at 比大小。

        注意這裡跟上一個測試要的是兩件不同的事:檔**名**用開跑日(資料日),
        檔**內容**用收工當下的時刻(才能跟匯入的 run_at 比先後)。
        """
        marker_line = next(ln for ln in self.lines if "branch_round_marker" in ln)
        self.assertIn("taipei_date -Is", marker_line,
                      "標記內容應該是台北時區的 ISO 時間")


if __name__ == "__main__":
    unittest.main()
