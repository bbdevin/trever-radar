"""`vps/scripts/repair-window.sh` 的守衛、順序與拒絕條件,由原始碼直接解析。

為什麼一支「手動跑幾次就退休」的腳本值得一個測試:它跑幾次不重要,重要的是它
**把一組只決定過一次的判斷寫了下來**——四個修復的先後(日K缺口必須先補,因為
帳本與前瞻報酬都從那些收盤價讀出來)、什麼情況下整個窗口不該開始(權證爬蟲沒被
暫停、距下一個排程寫入者不足 90 分鐘、鎖被占用)、以及一個連前置條件都擋不住的
拒絕(21:15–23:30 不碰 daily_margins,因為前三步會跑掉一個多小時,開跑時合格不
代表跑到第四步還合格)。

這些判斷如果只活在腳本裡而沒有人守著,下一次有人「順手」調整時就會被重新即興
發明一遍——而重新發明的時機,依定義是有人正盯著一個壞掉的正式資料庫、想趕快
把它修好的時候。那正是最不該重新推導「先跑哪一個」的時刻。

本檔和 test_cron_quiet_window.py / test_vps_lock_discipline.py 一樣**解析原始碼而
不執行它**:腳本要 docker、要 SQLite、要一顆正式資料庫才跑得動,但它要被守住的
性質全部寫在文字裡。
"""
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "vps" / "scripts" / "repair-window.sh"

LEDGER_DATES_EXPECTED = ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-07"]

# 註解裡提到 export-json 只是在說明「我們刻意不做」,不算呼叫;所以判準一律看
# 去掉註解之後的程式碼。整行註解直接丟掉,行尾註解要求 '#' 前面是空白——
# `${#LEDGER_DATES[@]}` 的 '#' 前面是 '{',不會被誤砍。
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


def _step_blocks(lines: list[str]) -> dict[int, tuple[int, int]]:
    """`# ===== step N:` 標頭切出來的四個區塊,值是 (起始行, 結束行) 皆 1-based。

    標頭本身是註解,所以在原檔文字上找,不在去註解的版本上找。
    """
    raw = SCRIPT.read_text(encoding="utf-8").splitlines()
    marker = re.compile(r"^#\s*=====\s*step\s*(\d)\s*:")
    starts: list[tuple[int, int]] = []
    for i, line in enumerate(raw, 1):
        m = marker.match(line)
        if m:
            starts.append((int(m.group(1)), i))
    blocks: dict[int, tuple[int, int]] = {}
    for idx, (step, start) in enumerate(starts):
        end = starts[idx + 1][1] - 1 if idx + 1 < len(starts) else len(raw)
        blocks[step] = (start, end)
    return blocks


class TestRepairWindowScript(unittest.TestCase):
    def setUp(self):
        self.lines = _code_lines()
        self.code = "\n".join(self.lines)
        self.blocks = _step_blocks(self.lines)

    def test_parser_is_not_vacuous(self):
        """解析器壞掉時不能靜悄悄地全部通過。"""
        self.assertTrue(SCRIPT.exists(), f"{SCRIPT} 不存在")
        self.assertEqual(
            [1, 2, 3, 4], sorted(self.blocks),
            f"應該正好切出四個 step 區塊,實際是 {sorted(self.blocks)}",
        )
        self.assertIn("source", self.code, "腳本應該 source lib.sh")
        # 去註解不能把整支腳本吃光。
        self.assertGreater(
            sum(1 for line in self.lines if line.strip()), 150,
            "去註解之後剩下的程式碼太少,解析器可能壞了",
        )

    def test_steps_appear_in_the_fixed_order(self):
        starts = [self.blocks[n][0] for n in (1, 2, 3, 4)]
        self.assertEqual(sorted(starts), starts,
                         f"四個步驟在檔案裡的順序不對:{starts}")

    # ── 前置條件:權證暫停檔 ────────────────────────────────────────────
    def test_pause_file_is_a_precondition_and_never_created(self):
        """暫停檔「不存在」是拒絕理由;腳本絕不自己建立它。

        自己建立等於讓人在沒想過那支六週長跑的情況下開窗:它會在我們的步驟之間
        搶走 DB 鎖,而前後量測就不再是本窗口造成的差額。
        """
        guard = _first_line(r'\[\s*!\s*-f\s*"\$PAUSE_FILE"\s*\]', self.lines)
        self.assertIsNotNone(guard, "找不到「暫停檔不存在就拒絕」的前置條件")

        # 守衛之後幾行內要有印出的理由,以及 exit 0(拒絕不是失敗)。
        window = "\n".join(self.lines[guard - 1:guard + 6])
        self.assertRegex(window, r"\becho\b", "拒絕必須印出原因")
        self.assertRegex(window, r"\bexit 0\b", "前置條件不成立要以 exit 0 離開")

        creations = [
            f"{i}: {line.strip()}"
            for i, line in enumerate(self.lines, 1)
            if re.search(r'(:\s*>\s*|touch\s+|>\s*)"?\$\{?PAUSE_FILE', line)
            and not re.search(r'-f\s*"\$PAUSE_FILE"', line)
        ]
        self.assertEqual(
            [], creations,
            "腳本不得建立權證暫停檔,只能要求它已經存在:\n" + "\n".join(creations),
        )

    def test_min_minutes_floor_is_ninety(self):
        self.assertIn('REPAIR_MIN_MINUTES:-90', self.code,
                      "距下一個排程寫入者的地板應為 90 分鐘(步驟 1 與 3 的預估耗時 + 餘裕)")
        self.assertIn("minutes_until_next_scheduled_writer", self.code,
                      "時間守衛要問「還剩多久」,不是「現在幾點」")

    def test_quiet_window_is_a_precondition(self):
        self.assertIsNotNone(
            _first_line(r"^\s*if\s+in_radar_quiet_window", self.lines),
            "安靜窗內不得開窗(排程日更優先)",
        )

    # ── 前置條件:先搶鎖、後 pause ──────────────────────────────────────
    def test_db_lock_is_taken_before_pausing_backfill_containers(self):
        """順序不可對調(理由同 adjust-backfill.sh):搶不到鎖是常態,先 pause 會
        產生大量無謂的 pause/unpause,並提高撞上 guard 與 cleanup 之間
        state-cache race 的機率。"""
        lock = _first_line(r"^\s*exec\s+9>\s*/tmp/radar-db\.lock\s*$", self.lines)
        flock = _first_line(r"flock\s+-n\s+9", self.lines)
        pause = _first_line(r"^\s*pause_bf_containers\s*$", self.lines)
        self.assertIsNotNone(lock, "找不到 /tmp/radar-db.lock 的 fd 9")
        self.assertIsNotNone(flock, "鎖必須是 flock -n(絕不等待)")
        self.assertIsNotNone(pause, "找不到 pause_bf_containers 呼叫")
        self.assertLess(lock, pause,
                        f"必須先搶鎖(:{lock})再 pause 回補容器(:{pause})")
        self.assertLess(flock, pause,
                        f"flock -n(:{flock})必須在 pause(:{pause})之前判定")

    def test_unpause_is_chained_onto_the_exit_trap_before_pausing(self):
        chain = _first_line(r"chain_exit_trap\s+'unpause_bf_containers'", self.lines)
        pause = _first_line(r"^\s*pause_bf_containers\s*$", self.lines)
        self.assertIsNotNone(chain, "unpause 必須掛在 EXIT trap 上")
        self.assertLess(chain, pause, "EXIT trap 要在 pause 之前掛好,失敗才不會留下被 pause 的容器")

    # ── 步驟 2:四個日期,固定順序 ──────────────────────────────────────
    def test_ledger_dates_are_a_constant_in_the_decided_order(self):
        m = re.search(r"LEDGER_DATES_DEFAULT=\(([^)]*)\)", self.code)
        self.assertIsNotNone(m, "步驟 2 的 as-of 清單應該是單一個陣列常數")
        self.assertEqual(
            LEDGER_DATES_EXPECTED, m.group(1).split(),
            "四個 as-of 日期與順序是 2026-09-14 拍板的結果,不得改動",
        )
        self.assertIn("REPAIR_LEDGER_DATES", self.code, "清單要可由環境變數覆寫")

    def test_ledger_dates_are_validated_as_trading_days_before_running(self):
        start, end = self.blocks[2]
        block = "\n".join(self.lines[start - 1:end])
        validate = block.index("daily_prices")
        invoke = block.index("branch-point-in-time-persist")
        self.assertLess(
            validate, invoke,
            "每個 as-of 要先驗證是交易日,才開始呼叫 branch-point-in-time-persist",
        )

    # ── 步驟 4:21:15–23:30 硬性拒絕 ────────────────────────────────────
    def test_margin_step_refuses_the_daily_margin_window(self):
        self.assertIn("MARGIN_EXCLUDE_FROM:-2115", self.code)
        self.assertIn("MARGIN_EXCLUDE_TO:-2330", self.code)

        start, end = self.blocks[4]
        block = "\n".join(self.lines[start - 1:end])
        self.assertRegex(
            block,
            r'\$NOW_HHMM"?\s*-ge\s*"?\$MARGIN_EXCLUDE_FROM.*\n?.*-le\s*"?\$MARGIN_EXCLUDE_TO',
            "步驟 4 必須在 21:15–23:30 之間拒絕(daily-margin.sh 寫同一張表)",
        )
        self.assertRegex(block, r"skip_step step4", "拒絕要印出理由,不是靜默跳過")

        # 時鐘要在步驟 4 真的要跑的時候才讀:前三步會跑掉一個多小時,開跑時合格
        # 不代表跑到這裡還合格。
        clock = _first_line(r"^\s*NOW_HHMM=", self.lines)
        self.assertIsNotNone(clock, "找不到步驟 4 的時鐘讀取")
        self.assertGreater(
            clock, self.blocks[3][0],
            "NOW_HHMM 必須在步驟 3 之後才讀,否則量的是開窗時刻而不是步驟 4 的時刻",
        )

    # ── 每一步都以前一步為前提 ──────────────────────────────────────────
    def test_each_step_is_gated_on_the_previous_one(self):
        for step in (2, 3, 4):
            with self.subTest(step=step):
                start, end = self.blocks[step]
                block = "\n".join(self.lines[start - 1:end])
                self.assertRegex(
                    block, rf'gate_clear\s+"step{step - 1}"',
                    f"步驟 {step} 必須以步驟 {step - 1} 沒有失敗為前提",
                )

    def test_a_failure_stops_the_remaining_steps_without_rolling_back(self):
        """fail_step 要留下 state、發高優先通知、非零離開——而且不碰前面的步驟。"""
        m = re.search(r"fail_step\(\)\s*\{(.*?)\n\}", self.code, re.S)
        self.assertIsNotNone(m, "找不到 fail_step")
        body = m.group(1)
        self.assertIn("persist_state", body, "失敗要把已完成的步驟寫進 state")
        self.assertRegex(body, r"notify\s+.*high", "失敗要發高優先通知")
        self.assertRegex(body, r'exit\s+"\$rc"', "失敗要以非零離開")
        for undo in ("rollback", "DELETE FROM", "DROP "):
            self.assertNotIn(undo, body, f"失敗不得回滾前面的步驟(發現 {undo!r})")

    # ── 不 export、不 deploy ────────────────────────────────────────────
    def test_nothing_is_published(self):
        """發布是另一個決定,不該搭這班車;下一輪排程自己會帶上線。"""
        offenders = [
            f"{i}: {line.strip()}"
            for i, line in enumerate(self.lines, 1)
            if re.search(r"\b(export-json|deploy_data|sync_code)\b", line)
        ]
        self.assertEqual(
            [], offenders,
            "修復窗不得 export / deploy / sync_code:\n" + "\n".join(offenders),
        )

    # ── 拒絕一律要有理由 ────────────────────────────────────────────────
    def test_every_refusal_prints_a_reason(self):
        silent = []
        for i, line in enumerate(self.lines, 1):
            if not re.match(r"^\s*exit 0\s*$", line):
                continue
            window = [x for x in self.lines[max(0, i - 6):i - 1] if x.strip()]
            if not any("echo" in x for x in window):
                silent.append(f"{i}: exit 0 前面沒有印出任何原因")
        self.assertEqual([], silent, "\n" + "\n".join(silent))


if __name__ == "__main__":
    unittest.main()
