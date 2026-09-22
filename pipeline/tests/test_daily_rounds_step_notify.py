"""四支日更輪(14:10 / 15:00 / 16:10 / 21:20)每一步失敗都要自己講話,由原始碼直接解析。

背景(defect,與 test_step_failure_notify.py 同一個):`lib.sh` 在 source 時就
`install_fail_trap`,但那個 ERR trap **不會**在 `radar X` 失敗時觸發——`radar` 與
`deploy_data` 都是 shell **函式**,而 ERR trap 沒有 `set -E` 就不繼承進函式。
對真的 lib.sh 做的測量(stub docker 回 9):

    裸 `radar X`                     rc=9  ERR trap 不觸發  中止  零通知
    `run_step "X" radar X`           rc=9  ERR trap **觸發** 中止  一則「執行到第 N 行」
    `run_step_or_fail "X" radar X`   rc=9  ERR trap 不觸發  中止  一則指名步驟的 high

af327f1 只修了 daily-branches.sh。其餘四輪的裸呼叫是同一個洞:

* `daily-market.sh`(14:10,全日最大的一輪)除了三個週一補充之外**完全沒有失敗
  的聲音**——import/aggregate/indicators/scores/export/deploy 全部靜默。
* `daily-tpex-quotes.sh`(15:00)六步全裸,同樣零通知。
* `daily-insti.sh`(16:10)第一個日K匯入自己分級(exit 75 那條),但法人匯入與
  其後五步全裸。
* `daily-margin.sh`(21:20)`import-futures` 自己分級,其餘六步全裸。

修法是共用 `run_step_or_fail`,但那個 helper 原本的句尾寫死了 daily-branches 的
收尾契約(「不寫完成標記,00:05 夜間作業會重算」)。四輪都沒有完成標記,00:05 的
夜間作業也只重算分點統計——照抄會在最需要準確的那一則通知裡說謊。所以後半句
參數化成 `set_round_consequence`,每一輪自己講自己的後果,忘記宣告的腳本會在
第一步就帶著 high 通知 exit(不是靜默繼承別人的句子)。

手法與 test_step_failure_notify.py / test_daily_branches_timing.py 相同:不執行
腳本(要 docker、要 SQLite),要守住的性質全部寫在文字裡。
"""
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "vps" / "scripts"
LIB = SCRIPTS_DIR / "lib.sh"

FULL_LINE_COMMENT = re.compile(r"^\s*#")
TRAILING_COMMENT = re.compile(r"(?<=\s)#.*$")

# 這次要修的四輪(daily-branches.sh 在 af327f1 已修,由 test_step_failure_notify.py 守)。
ROUNDS = ("daily-market.sh", "daily-tpex-quotes.sh", "daily-insti.sh", "daily-margin.sh")

# 每一輪必須經過 run_step_or_fail 的步驟:(標籤, 那一行裡一定看得到的指令片段)。
HELPER_STEPS = {
    "daily-market.sh": (
        ("import-daily", "radar import-daily --datasets quotes"),
        ("aggregate-warrants", "radar aggregate-warrants"),
        ("compute-indicators", "radar compute-indicators"),
        ("compute-scores", "radar compute-scores"),
        ("export-json", "radar export-json"),
        ("deploy", "deploy_data"),
    ),
    "daily-tpex-quotes.sh": (
        ("import-daily", "radar import-daily --datasets quotes"),
        ("aggregate-warrants", "radar aggregate-warrants"),
        ("compute-indicators", "radar compute-indicators"),
        ("compute-scores", "radar compute-scores"),
        ("export-json", "radar export-json"),
        ("deploy", "deploy_data"),
    ),
    "daily-insti.sh": (
        ("import-insti", "radar import-daily --datasets insti"),
        ("aggregate-warrants", "radar aggregate-warrants"),
        ("compute-indicators", "radar compute-indicators"),
        ("compute-scores", "radar compute-scores"),
        ("export-json", "radar export-json"),
        ("deploy", "deploy_data"),
    ),
    "daily-margin.sh": (
        ("import-daily", "radar import-daily --datasets quotes,margin"),
        ("import-margin-retry", "radar import-daily --datasets margin --date"),
        ("compute-scores", "radar compute-scores"),
        ("compute-performance", "radar compute-performance"),
        ("export-json", "radar export-json"),
        ("deploy", "deploy_data"),
    ),
}

# 刻意**不**走 helper 的呼叫:它們已經有自己的分級與通知,套上去會雙重通知,
# 而且第一則對「刻意續跑」的那些碼是錯的。
GRADED_EXCLUSIONS = {
    "daily-insti.sh": (
        # 第一個日K匯入:0 / 75(TPEx HTTP 520,保留已入庫行情續跑)/ 其他(high + 中止)
        "radar import-daily --datasets quotes",
        # 權證主檔:抓不到就 warn 並略過,不得擋法人上線
        "radar import-warrant-master",
    ),
    "daily-margin.sh": (
        # 個股期貨:75 = 只有一般時段已公布,warn-and-continue(docs/38 R3)
        "radar import-futures",
    ),
}


def _code_lines(path: Path) -> list[str]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if FULL_LINE_COMMENT.match(line):
            out.append("")
        else:
            out.append(TRAILING_COMMENT.sub("", line))
    return out


class TestDailyRoundsStepNotify(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lines = {name: _code_lines(SCRIPTS_DIR / name) for name in ROUNDS}
        cls.code = {name: "\n".join(v) for name, v in cls.lines.items()}
        cls.lib = "\n".join(_code_lines(LIB))

    def _consequence_line(self, name: str) -> str:
        line = next((ln for ln in self.lines[name]
                     if ln.strip().startswith("set_round_consequence ")), None)
        self.assertIsNotNone(line, f"{name} 沒有宣告本輪失敗的後果")
        return line.strip()

    def test_parser_is_not_vacuous(self):
        for name in ROUNDS:
            with self.subTest(script=name):
                self.assertGreater(sum(1 for ln in self.lines[name] if ln.strip()), 8,
                                   "去註解之後剩下的程式碼太少,解析器可能壞了")

    # ── 每一步都有聲音 ────────────────────────────────────────────────
    def test_every_bare_step_now_goes_through_the_helper(self):
        for name, steps in HELPER_STEPS.items():
            for label, cmd in steps:
                with self.subTest(script=name, step=label):
                    want = f'run_step_or_fail "{label}" '
                    line = next((ln for ln in self.lines[name]
                                 if ln.strip().startswith(want) and cmd in ln), None)
                    self.assertIsNotNone(
                        line,
                        f"{name} 的 {cmd} 失敗時沒有任何通知——正是這次要修的靜默失敗")

    def test_no_bare_radar_or_deploy_call_survives(self):
        """裸的 `radar …` / `deploy_data` 開頭那一行就是靜默失敗的形狀本身。

        允許的形狀只有兩種:`run_step_or_fail …`(helper 自己通知並帶原碼 exit),
        或包在 `if` 的測試式裡自己分級(daily-insti 的日K與權證主檔、
        daily-margin 的個股期貨)。
        """
        for name in ROUNDS:
            for i, ln in enumerate(self.lines[name], 1):
                s = ln.strip()
                with self.subTest(script=name, line=i):
                    self.assertFalse(
                        re.match(r"^(radar|radar_timeout|deploy_data)(\s|$)", s),
                        f"{name}:{i} 仍是裸呼叫,失敗一則通知都不會發:{s}")

    def test_graded_calls_are_not_routed_through_the_helper(self):
        """已經自己分級的呼叫**不准**套 helper:每一次非零都會先被 helper 報成
        「本輪中止」再走原本的分級,同一件事兩則,而且第一則對刻意續跑的那些碼
        (insti 的 75、futures 的 75、權證主檔的任何失敗)是錯的。"""
        for name, cmds in GRADED_EXCLUSIONS.items():
            for cmd in cmds:
                with self.subTest(script=name, cmd=cmd):
                    line = next((ln for ln in self.lines[name]
                                 if cmd in ln and "run_step_or_fail" not in ln), None)
                    self.assertIsNotNone(line, f"{name} 找不到 {cmd}")
                    self.assertNotIn("run_step_or_fail", line)
                    self.assertTrue(line.strip().startswith("if "),
                                    f"{cmd} 要自己用 if 接住碼:{line.strip()}")

    def test_graded_paths_keep_their_own_exit_codes(self):
        """離開碼是契約的一部分,這次改動不得動到任何一條既有路徑。"""
        insti = self.code["daily-insti.sh"]
        self.assertIn('exit "$quotes_rc"', insti, "日K非 0 非 75 要帶原碼中止")
        self.assertIn("exit 75", insti, "TPEx 520 那條仍以 75 收場(本輪不發布)")
        margin = self.code["daily-margin.sh"]
        self.assertIn('exit "$futures_rc"', margin, "期貨非 0 非 75 要帶原碼中止")
        for name in ROUNDS:
            with self.subTest(script=name):
                self.assertNotIn("exit 1", self.code[name],
                                 "不可以把任何路徑壓成 1")

    # ── 每一輪講自己的後果 ────────────────────────────────────────────
    def test_every_round_declares_its_own_consequence_before_its_first_step(self):
        for name in ROUNDS + ("daily-branches.sh",):
            script_lines = (self.lines.get(name)
                            or _code_lines(SCRIPTS_DIR / name))
            with self.subTest(script=name):
                decl = next((i for i, ln in enumerate(script_lines)
                             if ln.strip().startswith("set_round_consequence ")), None)
                self.assertIsNotNone(decl, f"{name} 沒有宣告本輪失敗的後果")
                first = next((i for i, ln in enumerate(script_lines)
                              if "run_step_or_fail" in ln), None)
                self.assertIsNotNone(first)
                self.assertLess(decl, first,
                                "宣告要在第一步之前——否則第一步就會撞上守衛")

    def test_no_round_inherits_the_branches_sentence(self):
        """每一輪的後果句必須是自己的。

        daily-branches 那句「不寫完成標記,00:05 夜間作業會重算」對這四輪全部是假的:
        四輪都沒有完成標記,而 00:05 的 safe-branch-stats.sh 只重算分點統計,
        不會重抓日K、法人或資券。抄過去等於叫值班的人回去睡覺。

        注意這裡禁的是**那一句**,不是「00:05」四個字:daily-margin 正是要點名
        00:05 那一輪「只重算分點」,好說明為什麼沒有人會補資券。
        """
        branches = "00:05 夜間作業會重算"
        for name in ROUNDS:
            with self.subTest(script=name):
                line = self._consequence_line(name)
                self.assertNotIn("完成標記", line,
                                 f"{name} 沒有完成標記這回事")
                self.assertNotIn(branches, line,
                                 f"{name} 的補救者不是 00:05 的夜間作業")
        # 那一句只准出現在它真正成立的那一支裡。
        # 只看程式碼:lib.sh 的註解引用這一句來解釋為什麼要參數化,那是說明不是通知。
        owners = [p.name for p in sorted(SCRIPTS_DIR.glob("*.sh"))
                  if branches in "\n".join(_code_lines(p))]
        self.assertEqual(["daily-branches.sh"], owners,
                         f"daily-branches 的收尾契約被抄到別處:{owners}")

    def test_the_five_consequences_are_pairwise_distinct(self):
        """兩輪講同一句,就代表其中至少一句是抄的(它們的補救者本來就不同)。"""
        texts = {}
        for name in ROUNDS + ("daily-branches.sh",):
            script_lines = (self.lines.get(name)
                            or _code_lines(SCRIPTS_DIR / name))
            line = next(ln for ln in script_lines
                        if ln.strip().startswith("set_round_consequence "))
            texts[name] = line.strip()
        self.assertEqual(len(set(texts.values())), len(texts),
                         f"有兩輪共用同一句後果:{texts}")

    def test_each_consequence_names_who_picks_it_up(self):
        """後果句要能回答「我現在要不要爬起來」。依據(crontab.example + 各腳本):

        * 14:10 失敗 → 15:00 的 daily-tpex-quotes.sh 是這六步的逐步同款,會整套重跑。
        * 15:00 失敗 → 16:10 的 daily-insti.sh 會再抓一次上櫃日K並重算上線。
        * 16:10 失敗 → 17:40 的 daily-branches.sh 第一步就匯 quotes,insti,並跑完整鏈。
        * 21:20 失敗 → **沒有人**。全 vps/scripts 只有本檔、backfill-margin.sh
          (週日一次性)與 manual-catchup.sh(手動)碰得到 margin;22:00 匯的是
          quotes,insti,00:05 只重算分點。所以這一句必須明講要人工補。
        """
        self.assertIn("15:00", self._consequence_line("daily-market.sh"))
        self.assertIn("16:10", self._consequence_line("daily-tpex-quotes.sh"))
        self.assertIn("17:40", self._consequence_line("daily-insti.sh"))
        margin = self._consequence_line("daily-margin.sh")
        self.assertRegex(margin, r"沒有任何排程|沒有人",
                         "21:20 是四輪裡唯一沒有後續補救者的")
        self.assertIn("人工", margin, "要明講得有人動手")

    def test_margin_is_really_the_only_scheduled_importer_of_margin_data(self):
        """上面那句話的依據本身要被釘住:哪天有人新增了一輪會補資券,
        daily-margin 的後果句就必須跟著改,而這條測試會先失敗提醒。"""
        importers = []
        for path in sorted(SCRIPTS_DIR.glob("*.sh")):
            for ln in _code_lines(path):
                if (re.search(r"--datasets\s+\S*margin", ln)
                        or re.search(r"\bradar backfill-margin\b", ln)):
                    importers.append(path.name)
                    break
        self.assertEqual(
            sorted(set(importers)),
            # 其中只有 daily-margin.sh 在 crontab 裡每天跑;backfill-margin.sh 是
            # 週日一次性(有 DONE flag,補的是 240 日歷史),manual-catchup.sh 與
            # repair-window.sh 都是人工工具——正是後果句說的「要人工補抓」。
            ["backfill-margin.sh", "daily-margin.sh", "manual-catchup.sh",
             "repair-window.sh"],
            f"會匯入資券的腳本變了,daily-margin 的後果句要重寫:{importers}")
        cron = (SCRIPTS_DIR / "crontab.example").read_text(encoding="utf-8")
        for manual in ("manual-catchup.sh", "repair-window.sh"):
            with self.subTest(script=manual):
                self.assertNotIn(manual, cron,
                                 f"{manual} 若進了 crontab,就不再是『人工』補")

    # ── 每步計時(順帶,但這是 14:10 那輪第一次有耗時可看)──────────────
    def test_the_timing_format_is_the_shared_one(self):
        """helper 內部走的是 lib.sh 的同一份 run_step,所以四輪的
        `step X start/done rc= elapsed=` 與 17:40 / 00:05 是同一個格式,
        一個 grep 就能比較同一步在不同輪的耗時。"""
        m = re.search(r"run_step_or_fail\(\)\s*\{(.*?)\n\}", self.lib, re.S)
        self.assertIsNotNone(m)
        self.assertRegex(m.group(1), r'if\s+run_step\s+"\$@";\s*then')

    # ── deploy_data 必須回報自己的離開碼 ──────────────────────────────
    def test_deploy_data_reports_its_own_exit_code(self):
        """`deploy_data` 被 helper 包在 `if` 的測試式裡跑,而 if 的測試式整段關掉
        set -e(連同被呼叫函式內部一起關)。舊寫法的最後一行是 `cd "$REPO"`,於是
        `npx wrangler deploy` 失敗之後函式照樣往下跑、回傳 cd 的 0——整輪把「沒上線」
        報成成功,還會寫完成標記、發 notify_ok,00:05 的夜間備援看到標記就整夜略過。
        實測(stub npx 回 9):裸呼叫 rc=9 中止,包進 run_step 則 rc=0 繼續。
        所以它必須像 radar() 一樣自己接住碼。
        """
        m = re.search(r"deploy_data\(\)\s*\{(.*?)\n\}", self.lib, re.S)
        self.assertIsNotNone(m, "lib.sh 裡找不到 deploy_data")
        body = m.group(1)
        self.assertRegex(body, r'npx wrangler deploy \|\| rc=\$\?',
                         "deploy 的失敗要就地接住,不能靠 set -e")
        self.assertRegex(body, r'\(\s*exit "\$rc"\s*\)',
                         "裸呼叫時要就地帶著原碼中止(與 radar() 同形)")
        self.assertRegex(body, r'return "\$rc"',
                         "被 if 包住時要忠實回傳原碼")
        tail = [ln.strip() for ln in body.splitlines() if ln.strip()][-1]
        self.assertEqual('return "$rc"', tail,
                         "最後一行不可以是 cd——那會用 cd 的 0 蓋掉 deploy 的失敗")


if __name__ == "__main__":
    unittest.main()
