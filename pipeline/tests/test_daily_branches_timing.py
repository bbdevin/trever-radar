"""`vps/scripts/daily-branches.sh` 的每步計時與起訖標記,由原始碼直接解析。

背景:`compute-branch-stats` 是全系統最貴的一步(實測 4,627 秒 = 77 分鐘)。
c1616f0 把裡面的線性掃描換成二分搜尋,profiling 顯示 20 檔從 95.46s 降到 13.83s,
推算整步應該掉到約 11 分鐘——但這個宣稱到現在都還沒被正式機驗證過,而且**無從
驗證**:

* 夜間 `safe-branch-stats.sh` 有每步計時,可是改動之後它每晚都走跳過路徑
  (13 / 16 分鐘的兩晚都沒真的跑 compute-branch-stats);
* 當天唯一真的跑 compute 的那一輪 —— 17:40 的 `daily-branches.sh` —— 一行計時
  都沒有,連開始/結束都沒印,整輪在 cron log 裡連邊界都要靠交錯的輸出去拼。

也就是說,系統最貴的一步正好在它變成當天唯一一次的那一刻變成看不見的。
本檔把「看得見」釘成性質:計時 wrapper 只有一份(在 lib.sh,兩輪共用同一個格式,
一個 grep 就能比較同一步在兩輪的耗時)、每個主要步驟都經過它、整輪有起訖標記。

手法與 test_daily_branches_exit_codes.py / test_safe_branch_stats_script.py 相同:
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

# 本輪的每一個主要步驟:(run_step 的標籤, 這一步真正執行的指令)。
# 標籤刻意與 safe-branch-stats.sh 用同一套字面值(compute-branch-stats、
# compute-scores、export-json、deploy),兩輪才 grep 得出同一步的耗時對照。
STEPS = (
    ("import-daily", "radar import-daily"),
    ("compute-indicators", "radar compute-indicators"),
    ("seed-branches", "radar seed-branches"),
    ("import-branch-trades", "radar import-branch-trades"),
    ("compute-branch-stats", "radar compute-branch-stats"),
    ("compute-scores", "radar compute-scores"),
    ("compute-performance", "radar compute-performance"),
    ("export-json", "radar export-json"),
    ("prune", "radar prune"),
    ("deploy", "deploy_data"),
)


def _code_lines(path: Path) -> list[str]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if FULL_LINE_COMMENT.match(line):
            out.append("")
        else:
            out.append(TRAILING_COMMENT.sub("", line))
    return out


class TestDailyBranchesTiming(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lines = _code_lines(SCRIPT)
        cls.code = "\n".join(cls.lines)
        cls.lib = "\n".join(_code_lines(LIB))
        cls.nightly = "\n".join(_code_lines(NIGHTLY))

    def test_parser_is_not_vacuous(self):
        self.assertGreater(sum(1 for ln in self.lines if ln.strip()), 40,
                           "去註解之後剩下的程式碼太少,解析器可能壞了")
        self.assertIn("source", self.code, "腳本應該 source lib.sh")

    # ── 一份實作 ──────────────────────────────────────────────────────
    def test_run_step_is_defined_exactly_once_and_lives_in_lib(self):
        """兩支腳本共用同一份 wrapper,複製第二份遲早會讓兩輪的格式漂移,
        而漂移之後就沒有「同一個 grep 比較同一步」這回事了。"""
        definers = [p.name for p in sorted(SCRIPTS_DIR.glob("*.sh"))
                    if re.search(r"^run_step\(\)\s*\{", p.read_text(encoding="utf-8"),
                                 re.M)]
        self.assertEqual(["lib.sh"], definers,
                         f"run_step 只能定義在 lib.sh 一處,實際:{definers}")

    def test_both_rounds_use_the_shared_wrapper(self):
        self.assertIn("run_step ", self.code, "17:40 / 22:00 這輪要用共用 wrapper")
        self.assertIn("run_step ", self.nightly, "00:05 夜間作業要用同一份")

    def test_shared_wrapper_keeps_the_if_shape_and_returns_the_raw_code(self):
        """wrapper 內部必須用 if 取碼,不可以是 set +e。

        lib.sh 在 source 時就 install_fail_trap,而 `set +e` **不會**讓 ERR trap
        安靜下來。本輪的分點匯入靠 run_step 回傳的原碼做 0/75/76 分級,若 wrapper
        改用 set +e 取碼,每個「個別標的失敗但仍可上線」的日子都會多一則 high
        假故障,把 75/76 的分級整個抵銷掉。
        """
        m = re.search(r"run_step\(\)\s*\{(.*?)\n\}", self.lib, re.S)
        self.assertIsNotNone(m, "lib.sh 裡找不到 run_step")
        body = m.group(1)
        self.assertRegex(body, r'if\s+"\$@";\s*then', "要用 if 取碼,不可用 set +e")
        self.assertNotIn("set +e", body)
        self.assertRegex(body, r"return\s+\"\$rc\"", "要忠實回傳原始離開碼")

    # ── 每一步都看得見 ────────────────────────────────────────────────
    def test_every_major_step_is_wrapped(self):
        for label, cmd in STEPS:
            with self.subTest(step=label):
                line = next((ln for ln in self.lines if cmd in ln), None)
                self.assertIsNotNone(line, f"找不到 {cmd} 這一步")
                self.assertRegex(
                    line.strip(), r'^(if )?run_step "' + re.escape(label) + '" ',
                    f"{cmd} 應該經過 run_step「{label}」,才有與夜間同格式的計時",
                )

    def test_labels_match_the_nightly_so_one_grep_compares_both_rounds(self):
        """兩輪都會跑的步驟必須用同一個標籤字面值——這次改動的整個重點就是
        `grep 'step compute-branch-stats done'` 可以一次拿到兩輪的耗時。"""
        for label in ("compute-branch-stats", "compute-scores", "export-json", "deploy"):
            with self.subTest(step=label):
                self.assertIn(f'run_step "{label}"', self.code)
                self.assertIn(f'run_step "{label}"', self.nightly)

    def test_wrapping_does_not_add_a_failure_notification(self):
        """裸的 `run_step X` 會改變通知行為,所以每個呼叫都必須落在
        `if` 的測試式裡或 `|| exit "$?"` 的左邊。

        改動前:`radar X` 的失敗發生在 radar **函式內部**(lib.sh 的
        `( exit "$rc" )`),而 ERR trap 不繼承進函式,於是 bash 當場帶著原碼結束,
        一則通知都不發。改成裸的 `run_step X` 之後,失敗變成在**頂層**回傳非零,
        set -e 中止時 ERR trap 就會觸發,每一次 OOM 都多一則 high「執行到第 N 行
        失敗」。那是行為改變,不是加計時——這次只要能見度,不順手改通知策略。
        """
        for i, ln in enumerate(self.lines, 1):
            s = ln.strip()
            if not s.startswith(("run_step ", "if run_step ")):
                continue
            with self.subTest(line=i):
                self.assertTrue(
                    s.startswith("if run_step ") or s.endswith('|| exit "$?"'),
                    f'第 {i} 行的 run_step 是裸呼叫,會讓失敗多送一則 ERR 通知:{s}',
                )

    def test_exit_codes_are_unchanged_by_the_wrapper(self):
        """分點匯入的離開碼是本輪唯一的判斷依據,包 wrapper 不得動到它。

        `if run_step … ; then branch_rc=0; else branch_rc=$?; fi` 這個相鄰形狀
        (成功那支明確設 0、失敗那支接住原碼)必須原封不動——run_step 的
        `return "$rc"` 逐位元回傳,所以 0/75/76/其他 的分級讀到的還是原碼。
        """
        imp = next(i for i, ln in enumerate(self.lines)
                   if "radar import-branch-trades" in ln)
        self.assertTrue(self.lines[imp].strip().startswith("if "),
                        "匯入仍要寫成 `if …; then`(ERR trap 對 if 的測試式免疫)")
        block = "\n".join(self.lines[imp:imp + 6])
        self.assertIn("branch_rc=0", block)
        self.assertIn("branch_rc=$?", block)
        self.assertNotIn("set +e", block)

    # ── 整輪的邊界 ────────────────────────────────────────────────────
    def test_round_has_start_and_done_markers(self):
        self.assertIn('echo "=== daily-branches start $(taipei_date -Is) ==="', self.code,
                      "整輪要有開始標記,cron log 才定位得到這一輪")
        self.assertIn('echo "=== daily-branches done $(taipei_date -Is) ==="', self.code,
                      "整輪要有結束標記")

    def test_start_marker_precedes_every_step(self):
        start = next(i for i, ln in enumerate(self.lines)
                     if "daily-branches start" in ln)
        first_step = next(i for i, ln in enumerate(self.lines) if "run_step " in ln)
        self.assertLess(start, first_step, "開始標記要在第一步之前")
        lock = next(i for i, ln in enumerate(self.lines)
                    if ln.strip() == "acquire_db_lock")
        self.assertLess(start, lock,
                        "開始標記要在搶鎖之前:搶不到而略過的那一輪也該看得到起點")

    def test_both_rounds_print_a_done_marker(self):
        """第二輪(BRANCH_ROUND_MODE=import)平常在匯入後就結束,它也要印結束標記,
        否則只匯入的那些夜晚在 log 裡依舊沒有邊界,兩輪就比不了。"""
        done = [i for i, ln in enumerate(self.lines) if "daily-branches done" in ln]
        self.assertGreaterEqual(len(done), 2,
                                "完整鏈收尾與 import 模式早退各要印一次結束標記")
        guard = next(i for i, ln in enumerate(self.lines)
                     if 'if [ "$BRANCH_ROUND_MODE" = "import" ]' in ln)
        early_exit = next(i for i, ln in enumerate(self.lines)
                          if i > guard and ln.strip() == "exit 0")
        self.assertTrue(any(guard < i < early_exit for i in done),
                        "import 模式那支 exit 0 之前要先印結束標記")
        self.assertGreater(done[-1], next(i for i, ln in enumerate(self.lines)
                                          if 'run_step "deploy"' in ln),
                           "完整鏈的結束標記要在最後一步之後")


if __name__ == "__main__":
    unittest.main()
