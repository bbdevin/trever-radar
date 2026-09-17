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

    def _marker_write_line(self) -> str:
        """**寫**標記的那一行。

        `branch_round_marker` 現在在腳本裡出現兩次:第二輪用 `-s` **讀**它決定
        今天要不要接手,收工時才**寫**它。要談「什麼時候寫」就必須指名帶
        重導向的那一行,不能拿第一個出現的位置當成寫入點。
        """
        line = next((ln for ln in self.lines
                     if "branch_round_marker" in ln and ">" in ln), None)
        self.assertIsNotNone(line, "找不到寫標記的那一行")
        return line

    def _marker_write_index(self) -> int:
        return self.code.index(self._marker_write_line())

    def test_exit_code_is_taken_via_if_so_the_err_trap_stays_quiet(self):
        """取離開碼要用 if/then/else,不可以用 `set +e; …; rc=$?; set -e`。

        兩種寫法都拿得到碼,差別在 ERR trap。lib.sh 在 source 時就呼叫了
        install_fail_trap,而 `set +e` **不會**讓 ERR trap 安靜下來——實測:

            set -euo pipefail; trap '...' ERR
            set +e; bash -c 'exit 75'; rc=$?; set -e   -> ERR TRAP FIRED
            if bash -c 'exit 75'; then …; else rc=$?; fi -> 不觸發

        用錯的那一種,每一個「個別標的失敗但仍可上線」的日子都會多送一則 high
        優先權的「執行到第 N 行失敗」,把正常結果講成故障,也就把 75(一般)與
        76(high)的分級整個抵銷掉。這正是這個專案一直在對抗的警報疲勞。
        """
        imp = next(i for i, ln in enumerate(self.lines)
                   if "radar import-branch-trades" in ln)
        self.assertTrue(self.lines[imp].strip().startswith("if radar import-branch-trades"),
                        "匯入要寫成 `if radar import-branch-trades …; then`")

        # `set +e` 不可以在匯入附近重新出現——那是被實測否決的寫法。
        window = self.code[max(0, self._index("radar import-branch-trades") - 300):
                           self._index("case \"$branch_rc\"")]
        self.assertNotIn("set +e", window,
                         "不可以退回 set +e 取碼:ERR trap 仍會誤報失敗")

        # then/else 兩支都要把碼接住:少了 then 那支,成功時 branch_rc 會沿用
        # 上一輪的舊值(或在 set -u 下直接炸掉)。
        block = "\n".join(self.lines[imp:imp + 6])
        self.assertIn("branch_rc=0", block, "成功那支要明確設 0")
        self.assertIn("branch_rc=$?", block, "失敗那支要接住真正的碼")

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
        marker = self._marker_write_index()
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

        for marker_line in [ln for ln in self.lines if "branch_round_marker" in ln]:
            with self.subTest(line=marker_line.strip()):
                # 讀與寫都要用同一個開跑日:第二輪查的標記若用「現在」算日曆日,
                # 跨午夜之後會去找一個明天的、永遠不存在的標記而誤判要接手。
                self.assertIn("$ROUND_DATE", marker_line,
                              "標記必須用開跑時定下的日期")
                self.assertNotIn("$(taipei_date +%F)", marker_line,
                                 "不可以在用到標記的當下才算日曆日 —— 跨午夜就會錯")

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
        self.assertGreater(self._marker_write_index(), guard,
                           "寫標記必須在 import 模式離開之後,只匯入的那輪不得寫")
        # 守衛與離開之間不可以夾帶寫標記的動作。這裡**讀**標記是新增的備援判斷,
        # 允許;帶重導向的**寫**才是被禁止的那件事。
        block = self.code[guard:self.code.index("fi", guard)]
        self.assertIn("exit 0", block, "import 模式要在這裡結束本輪")
        self.assertNotIn(">", block,
                         "只匯入那一支不得寫任何東西進標記檔")

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

    # ── 第二輪備援:17:40 沒上線的日子由 22:00 接手 ──────────────────────
    def _guard_block(self) -> str:
        """模式守衛從 `if` 到它自己的 `fi`(含內層的標記判斷)。"""
        guard = self._mode_guard()
        return self.code[guard:self.code.index("notify_warn", guard)]

    def test_second_round_publishes_only_when_today_has_not_published(self):
        """22:00 那輪的早退改成有條件:今天有完成標記才停,沒有就接手完整鏈。

        2026-09-17 是這條規則的來由:17:40 那輪覆蓋率 902/1956 = 46%,掉出 0.5
        地板而正確地扣留——但那輪的計數是 1412 ok / 1054 empty / 0 failed,來源
        健康,只是 18:30 太早。22:00 純匯入,於是整天沒有任何一輪上線,第一個
        發布者變成 00:05 的夜間作業(約 01:30)。資料在 22:00 早就填齊了。
        """
        block = self._guard_block()
        self.assertIn("branch_round_marker", block,
                      "早退必須以今天的完成標記為條件")
        self.assertIn("exit 0", block)
        # 早退包在標記判斷裡:沒有標記就落不到 exit,而是繼續往下跑完整鏈。
        inner = block.index("branch_round_marker")
        self.assertLess(inner, block.index("exit 0"),
                        "exit 0 必須在標記判斷之內,不能無條件執行")

    def test_marker_test_is_non_empty_not_mere_existence(self):
        """用 `-s` 不用 `-f`:標記內容是完成時刻,空檔案代表寫的過程出了事。

        把空檔案當成「今天上線過」,結果是這一天連備援都被關掉——正是備援唯一
        要擋的那個情況。
        """
        line = next(ln for ln in self._guard_block().splitlines()
                    if "branch_round_marker" in ln)
        self.assertIn("-s ", line, "標記判斷要用 -s(非空)")
        self.assertNotIn("-f ", line, "-f 會把空標記檔當成已上線")

    def test_fallback_is_after_the_exit_code_case_so_an_unfit_round_exits_first(self):
        """接手的前提是**這一輪自己的資料合格**。

        守衛必須落在離開碼 case 之後:第二輪若自己也掉出地板,要在 case 的 `*)`
        就 exit,絕不能走到這裡來、帶著一份不合格的資料接手上線。備援的用處是
        補上一輪的缺,不是繞過閘門。
        """
        case_idx = self._index('case "$branch_rc"')
        esac = self.code.index("esac", case_idx)
        self.assertLess(esac, self._mode_guard(),
                        "守衛必須整個落在離開碼 case 收尾之後")
        self.assertIn('exit "$branch_rc"', self.code[case_idx:esac],
                      "不合格要在 case 裡就中止,走不到備援")

    def test_the_full_chain_is_not_duplicated_into_the_fallback(self):
        """備援是「不 exit、繼續往下走」,不是把整條鏈複製一份到 if 裡面。

        複製的下場和離開碼分級複製一模一樣:兩份會漂移,而漂移的結果是某一條
        路徑悄悄少做了一步(少算一張表、少部署一次),而且不會有人發現。
        """
        for step in ("radar compute-branch-stats", "radar compute-scores",
                     "radar compute-performance", "radar export-json",
                     "radar prune", "deploy_data"):
            with self.subTest(step=step):
                self.assertEqual(self.code.count(step), 1,
                                 f"{step} 在腳本裡只能出現一次")

    def test_unfit_notification_is_graded_by_round_from_one_case_arm(self):
        """不合格通知按輪次分級,但仍然只有一份 `*)`。

        第一輪掉到地板以下不需要任何人動手——第二輪會接手——把它報成 high
        「失敗」,就是 75/76 那段註解一直在對抗的「把一個正常結果講成故障」。
        第二輪掉到地板以下才要叫醒人:今天沒有任何一輪上線。
        """
        case_idx = self._index('case "$branch_rc"')
        block = self.code[case_idx:self.code.index("esac", case_idx)]
        arm = block[block.index("*)"):]
        self.assertEqual(block.count("*)"), 1, "`*)` 只能有一份")
        self.assertNotIn("high", arm,
                         "優先權不可以寫死在分支裡,要由變數帶進來")
        for var in ("unfit_pri", "unfit_kind", "unfit_tail"):
            with self.subTest(var=var):
                self.assertRegex(arm, r"\$\{?" + var,
                                 f"{var} 要在唯一那份 `*)` 裡用到")

        # 選措辭的地方:import(第二輪)= high;其他(第一輪 / 手動)= 不是 high。
        sel = self._index('case "$BRANCH_ROUND_MODE"')
        self.assertLess(sel, case_idx, "措辭要在進離開碼 case 之前就選好")
        sel_block = self.code[sel:self.code.index("esac", sel)]
        second = sel_block[sel_block.index("import)"):sel_block.index("*)")]
        first = sel_block[sel_block.index("*)"):]
        self.assertIn('unfit_pri="high"', second,
                      "第二輪不合格 = 今天沒有任何一輪上線,要叫醒人")
        self.assertNotIn("high", first,
                         "第一輪不合格有備援接手,不可以送 high")
        self.assertIn('unfit_pri="default"', first)

    def test_header_says_the_mode_name_is_narrower_than_the_behaviour(self):
        """`BRANCH_ROUND_MODE=import` 有時會跑完整鏈,名字比行為窄。

        沒有改名是因為改名要再動一次正式機 crontab(使用者的決定)。那就必須把
        真正的意思寫在標題註解裡——讀的人不該從程式碼裡自己發現這件事。
        """
        header = SCRIPT.read_text(encoding="utf-8").split('BRANCH_ROUND_MODE="')[0]
        self.assertIn("第二輪", header, "要講明 import 的意思是『當天第二輪』")
        self.assertIn("完成標記", header,
                      "要講明續不續跑完整鏈是看今天有沒有完成標記")
        # 只說明行為還不夠:改動前的標題註解一樣會提到「第二輪」與「完成標記」。
        # 真正非講不可的是**名字與行為不一致**這件事本身,以及為什麼不改名——
        # 沒有這一句,下一個讀 crontab 的人只會看到 `import` 三個字。
        self.assertRegex(header, r"名字.{0,20}窄|窄.{0,20}名字",
                         "要直說這個變數名比它的行為窄")
        self.assertRegex(header, r"(不改名|改名).{0,80}crontab",
                         "要講明不改名的理由:改名要再動一次正式機 crontab")

    def test_marker_content_is_a_timestamp(self):
        """標記內容要是時間,不能只是空檔案——夜間作業靠它跟 run_at 比大小。

        注意這裡跟上一個測試要的是兩件不同的事:檔**名**用開跑日(資料日),
        檔**內容**用收工當下的時刻(才能跟匯入的 run_at 比先後)。
        """
        self.assertIn("taipei_date -Is", self._marker_write_line(),
                      "標記內容應該是台北時區的 ISO 時間")


if __name__ == "__main__":
    unittest.main()
