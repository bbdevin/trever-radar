"""失敗的步驟必須自己講話:`run_step_or_fail`(lib.sh)的性質,由原始碼直接解析。

背景(defect):`lib.sh` 在 source 時就 `install_fail_trap`,裝上
`trap '… notify "執行到第 N 行失敗" high "失敗"' ERR`。那個 trap **不會**在
`radar` 子指令失敗時觸發——`radar` 是 shell **函式**,而 ERR trap 沒有 `set -E`
就不繼承進函式;bash 在 `radar` 內部的 `( exit "$rc" )` 就地帶著原碼結束。

用 lib.sh 的形狀(`radar()` 收尾 `( exit "$rc" ); return "$rc"` 與 `run_step`)
做的測量:

    A. radar X                       rc=9  ERR trap 不觸發  中止   ← 最早的寫法
    B. run_step "X" radar X          rc=9  ERR trap **觸發** 中止
    C. run_step "X" radar X || exit  rc=9  ERR trap 不觸發  中止   ← C 與 A 等價
    D. if run_step …; then/else      rc=0  ERR trap 不觸發  繼續
    E. run_step_or_fail "X" radar X  rc=9  ERR trap 不觸發  中止 + 一則通知

也就是說 `daily-branches.sh` 的 compute-branch-stats、compute-scores、
compute-performance、export-json、prune、deploy_data 以前**全部靜默失敗**:
腳本帶著離開碼死掉,只有 cron log 記得。22:00 那輪改成只匯入之後,17:40 是當天
唯一的重算與上線,靜默失敗等於網站停在昨天直到 00:05 夜間作業約 01:30 才補上,
而沒有任何人被告知。本專案最慘的一次事故正是四天靜默停擺
(`safe-branch-stats.sh` 對同一種情況早就送 high 通知)。

手法與 test_daily_branches_timing.py / test_daily_branches_exit_codes.py 相同:
不執行腳本(它要 docker、要 SQLite),要守住的性質全部寫在文字裡。
"""
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "vps" / "scripts"
SCRIPT = SCRIPTS_DIR / "daily-branches.sh"
NIGHTLY = SCRIPTS_DIR / "safe-branch-stats.sh"
LIB = SCRIPTS_DIR / "lib.sh"

FULL_LINE_COMMENT = re.compile(r"^\s*#")
TRAILING_COMMENT = re.compile(r"(?<=\s)#.*$")

# 必須自己發通知的九步(= 整輪除了分點匯入以外的每一步)。
# 分點匯入刻意不在這裡:它的 0/75/76/其他 分級自己就會通知,見下面的測試。
NOTIFYING_STEPS = (
    "import-daily",
    "compute-indicators",
    "seed-branches",
    "compute-branch-stats",
    "compute-scores",
    "compute-performance",
    "export-json",
    "prune",
    "deploy",
)


def _code_lines(path: Path) -> list[str]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if FULL_LINE_COMMENT.match(line):
            out.append("")
        else:
            out.append(TRAILING_COMMENT.sub("", line))
    return out


class TestStepFailureNotify(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lines = _code_lines(SCRIPT)
        cls.code = "\n".join(cls.lines)
        cls.lib_lines = _code_lines(LIB)
        cls.lib = "\n".join(cls.lib_lines)
        cls.nightly = "\n".join(_code_lines(NIGHTLY))

    def _helper_body(self) -> str:
        m = re.search(r"run_step_or_fail\(\)\s*\{(.*?)\n\}", self.lib, re.S)
        self.assertIsNotNone(m, "lib.sh 裡找不到 run_step_or_fail")
        return m.group(1)

    def test_parser_is_not_vacuous(self):
        self.assertGreater(sum(1 for ln in self.lines if ln.strip()), 40,
                           "去註解之後剩下的程式碼太少,解析器可能壞了")

    # ── 一份實作 ──────────────────────────────────────────────────────
    def test_helper_is_defined_exactly_once_and_lives_in_lib(self):
        """九個呼叫點共用一份。複製成九份的下場跟 run_step 一樣:措辭漂移,
        而漂移之後就沒有「同一則通知講同一件事」這回事了。"""
        definers = [p.name for p in sorted(SCRIPTS_DIR.glob("*.sh"))
                    if re.search(r"^run_step_or_fail\(\)\s*\{", p.read_text(encoding="utf-8"),
                                 re.M)]
        self.assertEqual(["lib.sh"], definers,
                         f"run_step_or_fail 只能定義在 lib.sh 一處,實際:{definers}")
        self.assertEqual(self.lib.count("run_step_or_fail()"), 1)

    def test_the_notification_text_exists_only_in_the_helper(self):
        """呼叫端不得自己再寫一份失敗通知——那就是九份措辭的開始。"""
        for i, ln in enumerate(self.lines, 1):
            s = ln.strip()
            if not s.startswith("run_step_or_fail "):
                continue
            with self.subTest(line=i):
                self.assertNotIn("notify", s,
                                 f"第 {i} 行自己帶了通知,措辭應該只留在 lib.sh")

    # ── helper 的形狀 ────────────────────────────────────────────────
    def test_helper_runs_the_step_through_run_step(self):
        """通知是附加的,計時格式不能因此走樣:仍然要經過同一份 run_step,
        而且原封不動把 label 與指令傳過去(`"$@"` 的第一個就是 label)。"""
        body = self._helper_body()
        self.assertRegex(body, r'if\s+run_step\s+"\$@";\s*then',
                         "要用 if 包住 run_step 取碼")
        self.assertRegex(body, r'local\s+label="\$1"', "第一個參數是步驟名")
        self.assertNotIn("shift", body,
                         "不可以 shift:label 要連同指令一起交給 run_step")

    def test_exit_code_is_captured_in_the_else_arm_with_nothing_in_between(self):
        """碼要在失敗後**第一時間**取,中間夾任何一個指令都會把它換掉。

        也不可以寫成 `if run_step …; then return 0; fi; rc=$?`:那個 `$?` 讀到的
        是整個 if 複合指令的碼(條件不成立時是 0),不是 run_step 的碼,於是
        整輪會以 0 收場——比沒有通知更糟,因為 cron 會以為這輪成功了。
        """
        body = self._helper_body()
        m = re.search(r"\n\s*else\s*\n(.*?)\n\s*fi", body, re.S)
        self.assertIsNotNone(m, "取碼要寫在 if 的 else 那一支")
        first = next(ln.strip() for ln in m.group(1).splitlines() if ln.strip())
        self.assertEqual("rc=$?", first,
                         "else 的第一行就要取碼,前面不得有任何指令(連 echo 都不行)")
        self.assertNotIn("set +e", body,
                         "不可以用 set +e 取碼:ERR trap 在 set +e 之下仍會觸發")

    def test_helper_exits_with_the_original_code_not_a_literal(self):
        """離開碼是本輪的契約(test_daily_branches_exit_codes.py 釘住其中幾條),
        helper 不得把它壓成 1。"""
        body = self._helper_body()
        self.assertRegex(body, r'exit\s+"\$rc"', "要帶著原碼離開")
        self.assertNotRegex(body, r"exit\s+\d", "不可以用寫死的離開碼")

    def test_helper_exits_instead_of_returning_non_zero_to_the_top_level(self):
        """收尾必須是 `exit`,不是讓非零回到頂層。

        回到頂層 = set -e 中止 = ERR trap 觸發 = 同一次失敗送兩則通知
        (一則是 helper 指名步驟的,一則是 trap 只講行號的),正是 5cb7649
        修掉的雙重通知。實測:E 形狀 ERR trap 不觸發,通知恰好一則。
        """
        body = self._helper_body()
        tail = body[body.index("notify"):]
        self.assertRegex(tail, r'exit\s+"\$rc"')
        self.assertNotRegex(tail, r'return\s+"\$rc"',
                            "不可以 return 非零:那會把失敗丟回頂層觸發 ERR trap")
        # 成功那一支要早退,否則成功也會走到通知與 exit。
        self.assertRegex(body, r"then\s*\n\s*return 0", "成功要 return 0 早退")

    def test_notification_names_the_step_the_code_and_the_consequence(self):
        """措辭跟 safe-branch-stats.sh 的同類通知同一個語域:哪一步、哪個碼、
        後果是什麼。只說「失敗了」的通知會讓值班的人得自己去翻 cron log。"""
        body = self._helper_body()
        notify_line = next(ln for ln in body.splitlines() if "notify " in ln)
        self.assertIn("${label}", notify_line, "要指名是哪一步")
        self.assertIn("${rc}", notify_line, "要帶上離開碼")
        self.assertIn("high", notify_line, "失敗要叫醒人")
        self.assertIn('"失敗"', notify_line, "標題後綴用『失敗』")
        self.assertIn("本輪中止", notify_line, "要說整輪停在這裡")
        self.assertIn("未上線", notify_line, "要說沒有東西上線")
        self.assertRegex(notify_line, r"完成標記",
                         "要說不寫完成標記(那是 00:05 夜間作業會接手的依據)")
        self.assertIn("00:05", notify_line, "要說誰會接手")

    # ── 呼叫端 ────────────────────────────────────────────────────────
    def test_every_step_but_the_branch_import_uses_the_helper(self):
        for label in NOTIFYING_STEPS:
            with self.subTest(step=label):
                line = next((ln for ln in self.lines
                             if ln.strip().startswith(f'run_step_or_fail "{label}" ')), None)
                self.assertIsNotNone(
                    line,
                    f"{label} 失敗時沒有任何通知——正是這次要修的靜默失敗")

    def test_the_old_silent_shape_is_gone(self):
        """`|| exit "$?"` 與裸呼叫都是「靜默帶著碼死掉」,不得殘留。"""
        for i, ln in enumerate(self.lines, 1):
            s = ln.strip()
            with self.subTest(line=i):
                self.assertFalse(s.endswith('|| exit "$?"'),
                                 f'第 {i} 行仍是靜默失敗的舊形狀:{s}')

    def test_the_branch_import_is_not_routed_through_the_helper(self):
        """分點匯入**不准**用這個 helper:它的 0/75/76/其他 分級已經對每一種
        結果各有一則正確的通知。套上去等於每次非零都先被 helper 報成
        「本輪中止」再走 case——同一件事兩則,而且第一則對 75/76 是錯的
        (那兩種結果本來就繼續上線)。
        """
        imp = next(i for i, ln in enumerate(self.lines)
                   if "radar import-branch-trades" in ln)
        self.assertNotIn("run_step_or_fail", self.lines[imp])
        self.assertTrue(self.lines[imp].strip().startswith("if run_step "),
                        "匯入仍要自己用 if 接住碼")
        block = "\n".join(self.lines[imp:imp + 6])
        self.assertIn("branch_rc=$?", block)
        self.assertNotIn("run_step_or_fail", block)

    def test_the_nightly_job_is_untouched_by_this_helper(self):
        """`safe-branch-stats.sh` 每一步都已經自己顯式通知(stats 失敗 high 中止、
        帳本／分位／分數失敗 warn 續跑)。把它接到這個 helper 上會雙重通知,
        而且會把三個「刻意不中止」的步驟變成中止。"""
        self.assertNotIn("run_step_or_fail", self.nightly)
        self.assertIn('notify "分點統計失敗（碼 ${rc}），本輪中止" high "失敗"',
                      self.nightly, "夜間作業自己那則通知要留著")

    def test_prune_aborts_like_every_other_step_because_it_runs_before_deploy(self):
        """prune 與其他步驟同一個待遇(high + 中止),依據是**順序**。

        prune 排在 deploy_data **之前**,所以 prune 失敗的那一輪根本還沒上線:
        代價與 compute 失敗一模一樣,是「今天沒有任何一輪上線」。若哪天把 prune
        移到 deploy_data 之後,它就變成「資料已經在網站上,只差 DB 沒瘦身」,
        那時再用跟上線失敗同一級的警報叫醒人就不對了——本測試會在那個搬動發生時
        失敗,提醒重做一次這個判斷。
        """
        prune = self.code.index("radar prune")
        deploy = self.code.index("deploy_data")
        self.assertLess(prune, deploy,
                        "prune 若搬到 deploy_data 之後,它的通知等級要重新決定")


if __name__ == "__main__":
    unittest.main()
