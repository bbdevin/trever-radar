"""`vps/scripts/mid-backfill-publish.sh` 的離開碼取法,由原始碼直接解析。

這是三支腳本裡的第三種情況,獨立成檔而不是併進另外兩個檔,理由和
test_warrant_backfill_exit_codes.py 當初拆開的理由一樣:三支腳本守住的規則方向
互不相同,混在一起會讓人以為其中一份抄錯了。這一支真正特別的地方是**它自己會把
ERR trap 重新武裝回來**——另外兩支都沒有這個動作(daily-branches.sh 從頭到尾靠
lib.sh 裝的那份;warrant-backfill.sh 則 `trap - ERR` 之後永遠不再掛回),所以
「re-arm 之後不准有 `set +e` 取碼」這條規則只有在這個檔案裡談得起來。

本腳本的形狀:

    trap - ERR              # 開頭:前段的各種「跳過」不該觸發 high 通知
    …skip 判斷…
    install_fail_trap       # 正式步驟開始,把 ERR trap 重新武裝回來
    …
    radar compute-branch-stats   ← 取碼點,在 re-arm **之後**

修法前這裡寫的是 `set +e; radar compute-branch-stats; rc=$?; set -e`。`set +e`
**不會**讓 ERR trap 安靜下來(實測:

    set -euo pipefail; trap '...' ERR
    set +e; bash -c 'exit 75'; rc=$?; set -e      -> ERR TRAP FIRED
    if bash -c 'exit 75'; then …; else rc=$?; fi  -> 不觸發

),於是 stats 的任何一次失敗都會同時送出 lib.sh 的 high 優先權「執行到第 N 行
失敗」與腳本自己那則 notify_warn ——一次失敗兩則通知,而且把一個刻意壓成一般
等級的結果(stats 失敗不炸整輪,匯出上線照跑)講成故障。正是 daily-branches.sh
commit 5cb7649 修掉的同一個缺陷,也正是這個專案一直在對抗的警報疲勞。

為什麼這裡能用 `if`、warrant-backfill.sh 卻不能:那支取碼的對象是一條**管線**
(`radar … | tee "$RUN_LOG"`),`if` 會拿到 `tee` 的離開碼;這支是**單一指令**,
沒有這個問題。合法的形狀完全由「trap 有沒有武裝」與「取碼對象是不是管線」兩件事
決定,不是風格偏好——所以這裡也釘住「這個呼叫不可以變成管線」。

和 test_daily_branches_exit_codes.py / test_warrant_backfill_exit_codes.py 同一
手法:不執行腳本(它要 docker、要 SQLite、要一顆跑得動 stats 的機器),要守住的
性質全部寫在文字裡。
"""
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "vps" / "scripts" / "mid-backfill-publish.sh"
LIB = REPO_ROOT / "vps" / "scripts" / "lib.sh"

FULL_LINE_COMMENT = re.compile(r"^\s*#")
TRAILING_COMMENT = re.compile(r"(?<=\s)#.*$")

STATS_CALL = "radar compute-branch-stats"


def _code_lines(path: Path) -> list[str]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if FULL_LINE_COMMENT.match(line):
            out.append("")
        else:
            out.append(TRAILING_COMMENT.sub("", line))
    return out


class TestMidBackfillPublishExitCodes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = SCRIPT.read_text(encoding="utf-8")
        cls.lines = _code_lines(SCRIPT)
        cls.code = "\n".join(cls.lines)
        cls.lib = "\n".join(_code_lines(LIB))

    def _index(self, needle: str) -> int:
        idx = self.code.find(needle)
        self.assertNotEqual(idx, -1, f"找不到 {needle!r}")
        return idx

    def _line_index(self, needle: str) -> int:
        idx = next((i for i, ln in enumerate(self.lines) if needle in ln), None)
        self.assertIsNotNone(idx, f"找不到含 {needle!r} 的那一行")
        return idx

    def test_parser_is_not_vacuous(self):
        """解析器壞掉時不能靜悄悄地全部通過。"""
        self.assertTrue(SCRIPT.exists(), f"{SCRIPT} 不存在")
        self.assertGreater(
            sum(1 for line in self.lines if line.strip()), 60,
            "去註解之後剩下的程式碼太少,解析器可能壞了",
        )

    def test_the_err_trap_is_deliberately_re_armed_before_the_real_steps(self):
        """`install_fail_trap` 這一次重新武裝必須留著,而且要在 stats 之前。

        本檔其他測試守的都是「trap 武裝著,所以不能用 set +e 取碼」。如果有人
        把 install_fail_trap 拿掉,那些測試會突然變成在守一個不存在的問題——而
        且拿掉本身就是錯的修法方向:前段的 skip 判斷之所以先 `trap - ERR`,正
        是因為「略過」不該送 high;正式步驟(pause 容器、export、deploy)一旦失
        敗則**必須**叫醒人。用「把告警關掉」換「通知不重複」是把問題藏起來,不
        是修掉它。
        """
        self.assertIn("install_fail_trap", self.code,
                      "正式步驟開始前必須重新武裝 ERR trap,不可以靜悄悄拿掉")
        self.assertIn("install_fail_trap", self.lib,
                      "install_fail_trap 的定義應該在 lib.sh")
        disarm = self._index("trap - ERR")
        rearm = self._index("install_fail_trap")
        stats = self._index(STATS_CALL)
        self.assertLess(disarm, rearm, "先 disarm(跳過段)再 re-arm(正式段)")
        self.assertLess(rearm, stats,
                        "re-arm 必須在 compute-branch-stats 之前——這正是取碼形狀"
                        "受限的原因")

    def test_no_set_plus_e_exit_code_capture_survives_after_the_re_arm(self):
        """re-arm 之後不得再出現 `set +e` 式的取碼——這就是被修掉的缺陷本身。

        `set +e` 擋得住 `set -e` 的終止,擋不住 ERR trap。trap 武裝著的區段裡用
        它取碼,等於一次失敗發兩則通知(lib 的 high + 腳本自己的 notify_warn)。
        """
        rearm = self._line_index("install_fail_trap")
        after = "\n".join(self.lines[rearm:])
        self.assertNotIn("set +e", after,
                         "install_fail_trap 之後不可以有 set +e:ERR trap 仍會誤報")
        # 每一處取碼都必須緊接在 `else` 之後——那是 if 形狀唯一合法的取碼位置。
        # 出現在別處就代表是裸跑之後才取,也就是 set +e 那種形狀的殘留。
        captures = [i for i, ln in enumerate(self.lines)
                    if i >= rearm and re.search(r"\brc=\$\?", ln)]
        self.assertTrue(captures, "找不到任何取碼點,測試可能在守一個已消失的呼叫")
        for i in captures:
            with self.subTest(line=i + 1):
                self.assertEqual(self.lines[i - 1].strip(), "else",
                                 f"第 {i + 1} 行的 rc=$? 不在 if 的 else 支裡")

    def test_the_stats_exit_code_is_taken_via_if_then_else(self):
        """取碼要寫成 `if radar …; then rc=0; else rc=$?; fi`。

        兩支都要接住:少了 then 那支,成功時 `rc` 會沿用上一輪的舊值,或在
        `set -u` 下直接炸掉。
        """
        call = self._line_index(STATS_CALL)
        self.assertTrue(self.lines[call].strip().startswith(f"if {STATS_CALL}"),
                        f"呼叫要寫成 `if {STATS_CALL}; then`")
        block = "\n".join(self.lines[call:call + 5])
        self.assertIn("rc=0", block, "成功那支要明確設 0")
        self.assertIn("rc=$?", block, "失敗那支要接住真正的碼")

    def test_the_capture_is_adjacent_to_the_command(self):
        """`rc=$?` 與呼叫之間不能夾任何其他指令。

        `$?` 執行完下一個指令就會被覆蓋——即使只是插入一行 `echo`,取到的也不再
        是 CLI 的離開碼。這裡 `else` 是 shell 關鍵字不是指令,所以形狀必須是
        呼叫 / then / rc=0 / else / rc=$? 這五行緊貼著。
        """
        call = self._line_index(STATS_CALL)
        shape = [ln.strip() for ln in self.lines[call:call + 5]]
        self.assertEqual(shape[1], "rc=0")
        self.assertEqual(shape[2], "else")
        self.assertEqual(shape[3], "rc=$?")
        self.assertEqual(shape[4], "fi")

    def test_the_call_is_a_simple_command_not_a_pipeline(self):
        """這個呼叫不可以變成管線——`if` 形狀的正當性完全建立在它是單一指令上。

        一旦有人加上 `| tee …`,`if` 拿到的就是 `tee` 的離開碼,而不是 CLI 的,
        跟 warrant-backfill.sh 當初必須改用 `${PIPESTATUS[0]}` 的理由一模一樣。
        那時候正確的修法是換成 PIPESTATUS(並處理 trap 仍武裝的問題),不是原樣
        留著 `if`。
        """
        call_line = self.lines[self._line_index(STATS_CALL)]
        self.assertNotIn("|", call_line,
                         "compute-branch-stats 的呼叫必須是單一指令,不得接管線")
        self.assertNotIn("PIPESTATUS", self.code,
                         "沒有管線就不該出現 PIPESTATUS")

    def test_downstream_handling_of_each_exit_code_is_unchanged(self):
        """0 → stats=ok;非 0 → 記下碼、發一般等級通知、**繼續**匯出上線。

        修的是通知重複,不是行為。stats 失敗不炸整輪是這支腳本刻意的設計(檔頭
        寫明 VPS 只有 ~1.7G RAM,stats 本來就容易 OOM);如果修法順手讓它改成
        exit,回補中途上線就再也不會在 stats 失敗的日子刷新網站了。
        """
        call = self._index(STATS_CALL)
        tail = self.code[call:]
        branch = tail[tail.index('if [ "$rc" -eq 0 ]'):]
        ok_arm = branch[:branch.index("else")]
        fail_arm = branch[branch.index("else"):branch.index("fi", branch.index("else"))]
        self.assertIn('STATS_NOTE="ok"', ok_arm, "rc=0 要記成 ok")
        self.assertIn("failed_rc_${rc}", fail_arm, "非 0 要把碼記進 STATS_NOTE")
        self.assertIn("notify_warn", fail_arm, "非 0 發一般等級通知")
        self.assertNotIn("high", fail_arm,
                         "stats 失敗不是 high——整輪仍會匯出上線")
        self.assertNotIn("exit", fail_arm,
                         "stats 失敗不得中止本輪,匯出與 deploy 必須照跑")
        # export / deploy 確實落在 stats 分支之後,而且只有一份。
        for step in ("radar export-json", "deploy_data"):
            with self.subTest(step=step):
                self.assertEqual(self.code.count(step), 1)
                self.assertGreater(self._index(step), call)

    def test_the_comment_explains_why_warrant_backfill_keeps_set_plus_e(self):
        """註解必須講明為什麼三支腳本形狀不同,否則下一個人會來「統一」它們。

        這正是 test_warrant_backfill_exit_codes.py 存在的理由,反方向也要擋:
        有人看到 warrant-backfill.sh 用 `set +e`,把這裡改回去,兩則通知就回來了。
        """
        head = self.raw[:self.raw.index(f"if {STATS_CALL}")]
        comment = head[head.rindex("compute-branch-stats (mem="):]
        self.assertIn("warrant-backfill.sh", comment,
                      "要指名另一支腳本,讀的人才知道那個不一致是刻意的")
        self.assertIn("PIPESTATUS", comment, "要指出管線取碼的理由")
        self.assertRegex(comment, r"管線|pipeline")
        self.assertRegex(comment, r"ERR trap|install_fail_trap",
                         "要講明這裡的限制來自 trap 被重新武裝")


if __name__ == "__main__":
    unittest.main()
