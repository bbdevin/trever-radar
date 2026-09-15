"""`vps/scripts/safe-branch-stats.sh` 的計時、跳過與拒絕上線判準,由原始碼直接解析。

背景(讀 vps/scripts/safe-branch-stats.sh 檔頭與本次改動的 commit message):
本作業(00:05 台北,週二~六)的耗時從 93 分鐘一路長到 138 分鐘,但 log 只有一行
開始一行結束,長在哪一步無從歸因;另一晚 22:00 那輪(daily-branches.sh)的分點
匯入寫進 import_logs status='error',本作業仍照跑 stats/scores 並把結果上線
——一輪已知有壞資料的匯入照樣把資料送上網站。

三個判準都直接由原始碼驗證(和 test_repair_window_script.py / test_vps_lock_discipline.py
同一手法,不執行腳本——它要 docker、要 SQLite 才跑得動,但要守住的性質全部寫在文字裡):

1. 每個主要步驟(鎖等待、每個 radar 子指令、deploy)都用同一個計時 wrapper
   (`run_step`),做得到「done rc=... elapsed=...s」這行,失敗也要印。
2. 22:00 那輪(dataset='branch')的 import_logs 若當晚 status='ok',
   compute-branch-stats / compute-scores / export-json 三步驟要跳過;
   缺列或非 'ok' 一律走原本的完整補跑路徑。
3. 若那一列 status='error',不論(2)的判斷為何,deploy(上線)一律不得執行,
   且要用 notify_warn 等級告知——這是獨立於(2)的第二個閘門。
"""
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "vps" / "scripts" / "safe-branch-stats.sh"

FULL_LINE_COMMENT = re.compile(r"^\s*#")
TRAILING_COMMENT = re.compile(r"(?<=\s)#.*$")


def _code_lines() -> list[str]:
    """逐行的「去註解」版本,行號(index+1)與原檔對得起來。"""
    out = []
    for line in SCRIPT.read_text(encoding="utf-8").splitlines():
        if FULL_LINE_COMMENT.match(line):
            out.append("")
        else:
            out.append(TRAILING_COMMENT.sub("", line))
    return out


def _first_line(pattern: str, lines: list[str]) -> int | None:
    rx = re.compile(pattern)
    for i, line in enumerate(lines, 1):
        if rx.search(line):
            return i
    return None


class TestSafeBranchStatsScript(unittest.TestCase):
    def setUp(self):
        self.lines = _code_lines()
        self.code = "\n".join(self.lines)

    def test_parser_is_not_vacuous(self):
        self.assertTrue(SCRIPT.exists(), f"{SCRIPT} 不存在")
        self.assertIn("source", self.code, "腳本應該 source lib.sh")
        self.assertGreater(
            sum(1 for line in self.lines if line.strip()), 100,
            "去註解之後剩下的程式碼太少,解析器可能壞了",
        )

    # ── 判準 1:計時 ────────────────────────────────────────────────────
    def test_run_step_helper_logs_start_done_and_elapsed(self):
        m = re.search(r"run_step\(\)\s*\{(.*?)\n\}", self.code, re.S)
        self.assertIsNotNone(m, "找不到 run_step 計時 wrapper")
        body = m.group(1)
        self.assertRegex(body, r'echo\s+"step\s+\$\{?label\}?\s+start', "run_step 要印出起始時間")
        self.assertRegex(body, r'echo\s+"step\s+\$\{?label\}?\s+done\s+rc=', "run_step 要印出離開碼")
        self.assertIn("elapsed=", body, "run_step 要印出耗時")
        self.assertRegex(body, r"return\s+\"\$rc\"", "run_step 要忠實回傳原始離開碼")

    def test_every_radar_subcommand_and_deploy_go_through_run_step(self):
        for label in (
            "compute-branch-stats",
            "branch-point-in-time-persist",
            "branch-stock-pctile-counts",
            "compute-scores",
            "export-json",
            "deploy",
        ):
            with self.subTest(step=label):
                self.assertIn(
                    f'run_step "{label}"', self.code,
                    f"{label} 應該透過 run_step 呼叫,才有統一格式的計時",
                )

    def test_lock_wait_has_its_own_start_and_elapsed(self):
        self.assertIn("step lock-wait start", self.code)
        self.assertIn("step lock-wait done rc=0 elapsed=", self.code)
        self.assertIn("step lock-wait done rc=1 elapsed=", self.code,
                      "拿不到鎖(gave up)那個分支也要記一次 done/elapsed")
        # 既有的量測行不得被拿掉——docs 明講這是唯一能驗證 22:00 尾巴長度的方式。
        self.assertIn('waited $(( $(date +%s) - _lock_t0 ))s for radar-db.lock', self.code)

    # ── 判準 2:22:00 status='ok' 時跳過三個重算步驟 ───────────────────────
    def test_today_means_taipei_yesterday_for_the_evening_row(self):
        """00:05 起跑,對應的是「昨晚 22:00」那一輪,不是行事曆上的今天。"""
        line = _first_line(r"BRANCH_IMPORT_DATE=", self.lines)
        self.assertIsNotNone(line, "找不到 BRANCH_IMPORT_DATE 的計算")
        stmt = self.lines[line - 1]
        self.assertIn("TZ=Asia/Taipei", stmt)
        self.assertRegex(stmt, r"date\s+-d\s+'yesterday'", "應該取台北時區的昨天,不是今天")

    def test_query_is_readonly_and_scoped_to_branch_dataset(self):
        self.assertIn("mode=ro", self.code, "查 import_logs 應該用唯讀連線,不佔寫鎖")
        self.assertIn("uri=True", self.code)
        self.assertIn("dataset='branch'", self.code)
        self.assertIn("ORDER BY id DESC LIMIT 1", self.code,
                      "同一天 17:40/22:00 都可能各寫一列,要挑最新的一列")

    def test_evening_ok_flag_only_set_on_exact_status_ok(self):
        line = _first_line(r'EVENING_BRANCH_OK=1', self.lines)
        self.assertIsNotNone(line, "找不到 EVENING_BRANCH_OK 的設定")
        guard = self.lines[line - 1]
        self.assertIn('"$BRANCH_STATUS" = "ok"', guard,
                      "只有精確等於 'ok' 才算晚上那輪成功,其餘一律不算")
        default_line = _first_line(r"^\s*EVENING_BRANCH_OK=0\s*$", self.lines)
        self.assertIsNotNone(default_line, "EVENING_BRANCH_OK 應該預設為 0(缺列/非 ok 都保守走完整路徑)")
        self.assertLess(default_line, line, "預設值要先設,再由 ok 分支覆寫成 1")

    def test_the_three_redundant_steps_are_gated_on_evening_ok(self):
        for label in ("compute-branch-stats", "compute-scores", "export-json"):
            with self.subTest(step=label):
                idx = self.code.index(f'run_step "{label}"')
                window = self.code[max(0, idx - 400):idx]
                self.assertIn(
                    'EVENING_BRANCH_OK', window,
                    f'{label} 的呼叫前面應該看得到 EVENING_BRANCH_OK 的判斷',
                )

    def test_pit_and_pctile_are_not_skipped_by_evening_ok(self):
        """PIT 與 pair-pctile 不在「三步驟」名單裡:22:00 那輪根本不會呼叫它們,
        跟 22:00 是否成功無關,不該被 EVENING_BRANCH_OK 連坐跳過。"""
        for label in ("branch-point-in-time-persist", "branch-stock-pctile-counts"):
            with self.subTest(step=label):
                idx = self.code.index(f'run_step "{label}"')
                # 往前找到包住這個呼叫的最近一個 if,只看該 if 的判斷式本身。
                head = self.code[:idx]
                guard_start = head.rindex("if [")
                guard_line = head[guard_start:head.index("\n", guard_start)]
                self.assertNotIn(
                    "EVENING_BRANCH_OK", guard_line,
                    f"{label} 的守衛不應該是 EVENING_BRANCH_OK",
                )

    def test_missing_or_non_ok_row_runs_the_full_sequence(self):
        """row 缺失(空字串)或任何非 'ok' 的狀態,都要落到 run_step 那個分支
        (而不是被跳過),這就是本腳本存在的 fallback。"""
        idx = self.code.index('run_step "compute-branch-stats"')
        # 呼叫前必須是 elif(EVENING_BRANCH_OK 不成立時才走到這裡)。
        window = self.code[max(0, idx - 200):idx]
        self.assertIn("elif", window)
        self.assertNotIn("BRANCH_STATUS} = \"error\"", window.replace(" ", ""))

    # ── 判準 3:22:00 status='error' 時不得上線 ─────────────────────────
    def test_deploy_is_refused_when_evening_status_is_error(self):
        deploy_idx = self.code.index('run_step "deploy"')
        head = self.code[:deploy_idx]
        error_if = head.rindex('if [ "$BRANCH_STATUS" = "error" ]')
        between = head[error_if:deploy_idx]
        self.assertIn("elif", between,
                      "deploy 應該掛在『status=error』判斷式的 elif/else,而非平行的另一個 if")
        self.assertNotIn('run_step "deploy"', head[error_if:head.index("elif", error_if)],
                         "error 分支本身不得呼叫 deploy")

    def test_withheld_publish_notifies_as_a_warning_not_silently(self):
        idx = self.code.index('if [ "$BRANCH_STATUS" = "error" ]')
        block = self.code[idx:idx + 400]
        self.assertIn("notify_warn", block,
                      "撤回上線要用 notify_warn 等級告知,而不是靜默略過")
        self.assertRegex(block, r"echo\b", "撤回上線也要在 log 裡留一行原因")

    def test_export_json_and_deploy_are_gated_independently(self):
        """rule 2(evening ok 跳過重算)與 rule 3(error 不上線)是兩個獨立判斷,
        不能被合併成同一個 if——一個決定要不要重算,另一個決定能不能上線。"""
        export_idx = self.code.index('run_step "export-json"')
        deploy_idx = self.code.index('run_step "deploy"')
        # 兩者中間必須各自起頭一個新的 if,而不是共用同一個 if/elif 鏈。
        between = self.code[export_idx:deploy_idx]
        self.assertRegex(
            between, r'if\s+\[\s*"\$BRANCH_STATUS"\s*=\s*"error"\s*\]',
            "export-json 與 deploy 之間應該另起一個看 status=error 的 if",
        )

    # ── 不得動到的東西 ────────────────────────────────────────────────
    def test_lock_wait_bound_is_unchanged(self):
        self.assertIn('LOCK_WAIT_SECS="${LOCK_WAIT_SECS:-3000}"', self.code,
                      "50 分鐘的等鎖上限不得被這次改動動到")
        self.assertIn('flock -w "$LOCK_WAIT_SECS" 9', self.code)

    def test_fd9_is_still_closed_before_spawning_daemons(self):
        hold = _first_line(r"^\s*exec\s+9>\s*/tmp/radar-db\.lock\s*$", self.lines)
        close = _first_line(r"^\s*exec\s+9>&-\s*$", self.lines)
        spawn = _first_line(r"^\s*nohup\b.*[^>&]&\s*$", self.lines)
        self.assertIsNotNone(hold, "找不到 fd 9 的持有")
        self.assertIsNotNone(close, "找不到 exec 9>&- 釋放鎖")
        self.assertIsNotNone(spawn, "找不到補起常駐 daemon 的 nohup")
        self.assertLess(hold, close, "先持鎖")
        self.assertLess(close, spawn, "起 daemon 之前必須先放鎖,否則 fd 9 被繼承")


if __name__ == "__main__":
    unittest.main()
