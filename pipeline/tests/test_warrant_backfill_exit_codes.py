"""`vps/scripts/warrant-backfill.sh` 的離開碼取法,由原始碼直接解析。

這支腳本合法地用了一個被 `daily-branches.sh`(commit 5cb7649)明文禁止的形狀:
`set +e; radar … | tee "$RUN_LOG"; rc=${PIPESTATUS[0]}; set -e`。表面上這正是
那次修法要改掉的寫法,但這裡不能改,理由有兩個,而且都是獨立成立的:

1. **它對 ERR trap 免疫,`daily-branches.sh` 不是。** lib.sh 在 source 時就呼叫
   了 `install_fail_trap`(把 ERR 接到 high 優先權通知),而 `set +e` **不會**讓
   這個 trap 安靜下來——這是 daily-branches 那次修法量到的事實。但本腳本在
   `source lib.sh` 之後、任何一句可能失敗的敘述之前,先執行了 `trap - ERR` 並
   且**再也沒有**呼叫 `install_fail_trap` 重新掛回去(檔頭註解講得很清楚:每個
   失敗點都自己 unpause 並留住 state,不靠 lib 的 ERR trap,免得同一次失敗發兩
   則通知)。trap 全程是空的,`set +e` 前後差別為零。

2. **改成 `if …; then` 形狀在這裡是真的會引入 bug,不是風格問題。** 這裡取碼的
   對象是一條**管線**(`radar … | tee "$RUN_LOG"`),不是單一指令。
   `if radar … | tee …; then` 拿到的是 `tee` 的離開碼,不是 CLI 的——在
   `pipefail` 下,兩者只在 `tee` 也成功時才會相同。而這支腳本最典型的失敗模式
   正是磁碟被回補寫滿(檔頭 `MIN_FREE_GB` 那整段講的就是這件事),那正是 `tee`
   會失敗的時候。CLI 乾淨停下回 75、但 `tee` 因為磁碟滿了回非 0,`if` 形狀會把
   75 誤讀成假的失敗 rc,直接送一則 high 優先權告警並 `exit`——而外層驅動迴圈
   `while bash warrant-backfill.sh; do sleep 180; done` 靠的正是這支腳本乾淨
   回傳,`exit` 會把整條回補迴圈打斷,不是只漏一次通知。

所以 `daily-branches.sh` 與本腳本合法地用兩種不同的取碼形狀,原因分別對應到
「trap 有沒有掛著」與「取碼對象是不是管線」——哪一種形狀合法完全看這兩件事,
不是任選其一的風格偏好。**把兩支腳本「統一」成同一種寫法,兩個方向都會壞**:
本腳本改成 `if`,磁碟滿時 75 會被讀成 1;daily-branches.sh 若改回
`set +e; …; rc=$?; set -e`,則會在每一個「個別標的失敗但仍可上線」的日子多送
一則假的 high 優先權告警(該檔已有測試守住那個方向)。這裡守住的是另一個方向。

和 test_daily_branches_exit_codes.py / test_repair_window_script.py 同一手法:
不執行腳本(它要 docker、要 SQLite、要一顆磁碟接近寫滿的環境才踩得到那個分
歧),要守住的性質全部寫在文字裡。獨立成檔而不是併進
test_daily_branches_exit_codes.py,是因為兩支腳本要守住的規則方向相反
(一個禁止 `set +e`、一個要求 `set +e`),混在同一個檔案裡容易讓人以為其中
一份是抄錯的,拆開才看得出這是兩個分別成立的結論。
"""
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "vps" / "scripts" / "warrant-backfill.sh"

FULL_LINE_COMMENT = re.compile(r"^\s*#")
TRAILING_COMMENT = re.compile(r"(?<=\s)#.*$")


def _code_lines() -> list[str]:
    out = []
    for line in SCRIPT.read_text(encoding="utf-8").splitlines():
        if FULL_LINE_COMMENT.match(line):
            out.append("")
        else:
            out.append(TRAILING_COMMENT.sub("", line))
    return out


class TestWarrantBackfillExitCodes(unittest.TestCase):
    def setUp(self):
        self.lines = _code_lines()
        self.code = "\n".join(self.lines)

    def _index(self, needle: str) -> int:
        idx = self.code.find(needle)
        self.assertNotEqual(idx, -1, f"找不到 {needle!r}")
        return idx

    def test_parser_is_not_vacuous(self):
        """解析器壞掉時不能靜悄悄地全部通過。"""
        self.assertTrue(SCRIPT.exists(), f"{SCRIPT} 不存在")
        self.assertGreater(
            sum(1 for line in self.lines if line.strip()), 150,
            "去註解之後剩下的程式碼太少,解析器可能壞了",
        )

    def test_err_trap_is_disarmed_before_the_first_radar_invocation(self):
        """`trap - ERR` 必須在第一次呼叫 `radar` 之前就生效。

        這是本腳本的 `set +e` 之所以安全的唯一理由:trap 是空的,`set +e` 開不
        開對它沒有差別。如果 disarm 落在第一次 radar 呼叫之後,中間這段仍然
        是全程 armed 的 `set +e`——正是 daily-branches.sh 那次修法否決掉的
        寫法。
        """
        trap_idx = self._index("trap - ERR")
        radar_idx = self._index("radar backfill-warrant-branches")
        self.assertLess(trap_idx, radar_idx,
                        "`trap - ERR` 必須落在第一次呼叫 radar 之前")

    def test_install_fail_trap_is_never_called_in_the_script_body(self):
        """腳本自己的本文絕不可以重新呼叫 `install_fail_trap` 把 ERR trap 掛回去。

        `lib.sh` 在被 source 的當下就會呼叫一次 `install_fail_trap`——這是
        `source lib.sh` 本身帶來的,不算腳本本文重新掛回。危險的是腳本在
        `trap - ERR` **之後**自己又呼叫一次:那樣 trap 就重新武裝,而下面的
        `set +e; … | tee …; rc=${PIPESTATUS[0]}; set -e` 就變回對 ERR trap
        無效的危險寫法,一次失敗會被通知兩次(lib 的 high 優先權 ERR trap +
        腳本自己在 `case "$VERDICT"` 分支裡發的那則)。
        """
        self.assertNotIn("install_fail_trap", self.code,
                         "warrant-backfill.sh 本文不得呼叫 install_fail_trap"
                         "——一旦重新武裝 ERR trap,後面的 set +e 取碼就不再安全")

    def test_exit_code_is_captured_from_pipestatus_not_dollar_question(self):
        """取碼要用 `${PIPESTATUS[0]}`,不能用裸的 `$?`。

        取碼的對象是一條管線(`radar … | tee "$RUN_LOG"`),`$?` 拿到的會是
        `tee` 的離開碼,不是 CLI 的——兩者只在 `tee` 也成功時才會相同,而磁碟
        被回補寫滿(這支腳本最典型的失敗模式)正是 `tee` 會失敗、兩者分歧的
        時候。
        """
        self.assertIn("rc=${PIPESTATUS[0]}", self.code,
                      "離開碼必須以 ${PIPESTATUS[0]} 取自管線的第一段")
        self.assertNotRegex(self.code, r"radar backfill-warrant-branches[\s\S]*?\brc=\$\?",
                            "不可以在這條管線之後改用裸的 $? 取碼")

    def test_pipestatus_capture_is_adjacent_to_the_pipeline(self):
        """`rc=${PIPESTATUS[0]}` 與管線之間不能夾任何其他指令。

        `PIPESTATUS` 跟 `$?` 一樣,執行完下一個指令就會被覆蓋——即使只是插入
        一行 `echo`,取到的也不再是 CLI 那條管線的結果。
        """
        pipe_line = next(i for i, ln in enumerate(self.lines)
                         if "radar backfill-warrant-branches" in ln)
        tee_line = next(i for i, ln in enumerate(self.lines)
                        if i >= pipe_line and ln.strip().endswith('| tee "$RUN_LOG"'))
        rc_line = next(i for i, ln in enumerate(self.lines)
                       if "rc=${PIPESTATUS[0]}" in ln)
        between = [ln for ln in self.lines[tee_line + 1:rc_line] if ln.strip()]
        self.assertEqual(
            [], between,
            f"rc=${{PIPESTATUS[0]}} 與管線之間不可以夾其他指令,實際夾了:{between}",
        )
        self.assertEqual(rc_line, tee_line + 1,
                         "rc=${PIPESTATUS[0]} 必須緊接在管線那一行之後")

    def test_pipeline_is_wrapped_in_set_plus_e_around_the_capture(self):
        """`set +e` … `set -e` 必須包住整條管線與取碼,不能省。

        沒有 `set +e`,`radar … | tee …` 在 `pipefail`(lib.sh 開的)下一旦非
        零就會被 `set -e` 直接終止腳本,連 case/verdict 分級與 state 保留都
        走不到,等於把「乾淨停下可續跑」也當成腳本層級的致命錯誤處理掉。
        """
        pipe_idx = self._index("radar backfill-warrant-branches")
        rc_idx = self._index("rc=${PIPESTATUS[0]}")
        window = self.code[max(0, pipe_idx - 200):rc_idx + 50]
        self.assertIn("set +e", window, "管線前必須先 set +e")
        self.assertIn("set -e", self.code[rc_idx:rc_idx + 50],
                      "取完碼之後必須立刻 set -e 恢復")

    def test_converting_the_call_site_to_if_then_would_be_caught(self):
        """釘住「不可以改成 if 形狀」這個具體的退化方向。

        這是最可能被「跟 daily-branches.sh 統一寫法」這個念頭引入的改動:把
        `set +e; radar … | tee …; rc=${PIPESTATUS[0]}; set -e` 改成
        `if radar … | tee …; then rc=0; else rc=$?; fi`。這支測試直接檢查
        呼叫那一行不是以 `if` 開頭、而且取碼用的是 `PIPESTATUS` 不是 `$?`——
        兩個條件任一個被那種改動觸犯就會失敗,對稱於
        test_daily_branches_exit_codes.py 裡反方向的
        `test_exit_code_is_taken_via_if_so_the_err_trap_stays_quiet`。
        """
        call_line = next(ln for ln in self.lines
                         if "radar backfill-warrant-branches" in ln)
        self.assertFalse(
            call_line.strip().startswith("if "),
            "呼叫不可以寫成 `if radar backfill-warrant-branches …; then`——"
            "取到的會是 tee 的離開碼,磁碟寫滿時會把乾淨停下(75)誤讀成失敗",
        )
        rc_line = next(ln for ln in self.lines if "rc=" in ln and "PIPESTATUS" in ln)
        self.assertNotIn("$?", rc_line)


if __name__ == "__main__":
    unittest.main()
