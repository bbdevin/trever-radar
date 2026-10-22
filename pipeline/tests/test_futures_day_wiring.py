# -*- coding: utf-8 -*-
"""docs/38 §7.18 的接線狀態,由腳本原始碼直接解析(同 test_daily_rounds_step_notify.py 手法)。

1. 唯讀的發布時間量測 `probe-futures-day`(14:10/15:00/16:10 三輪取鎖前、寫
   ~/futures-probe.log)已量完,2026-10-07 依計畫整段移除:腳本、lib.sh 與 CLI 都不再有。
2. 會寫資料庫的 `import-futures-day` 自 2026-10-02 起接進 daily-insti.sh(16:10)與
   daily-branches.sh(16:30／22:30),裸呼叫、75 只記 log、不擋本輪。2026-10-22 起其他非 0
   也只在當天最後一次(22:30 第二輪)warn,法人輪與分點第一輪只記 log(後面還有輪會再試)。
"""
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "vps" / "scripts"

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


class ProbeIsGone(unittest.TestCase):
    def test_no_script_calls_the_probe(self):
        for p in sorted(SCRIPTS_DIR.glob("*.sh")):
            code = "\n".join(_code_lines(p))
            with self.subTest(script=p.name):
                self.assertNotIn("futures_probe", code)
                self.assertNotIn("probe-futures-day", code)

    def test_cli_has_no_probe_subcommand(self):
        cli = (REPO_ROOT / "pipeline" / "radar" / "cli.py").read_text(encoding="utf-8")
        self.assertNotIn("probe-futures-day", cli)


class ImportFuturesDayIsWired(unittest.TestCase):
    CALLERS = {"daily-branches.sh", "daily-insti.sh"}

    def _block(self, code: str, start: str) -> str:
        """從 start 那一行起,到同一層的 `fi` 為止(含)。"""
        i = code.index(start)
        indent = len(code[:i].rsplit("\n", 1)[-1])
        m = re.compile(rf"\n {{{indent}}}fi\n").search(code, i)
        self.assertIsNotNone(m)
        return code[i:m.end()]

    def test_exactly_these_scripts_call_it(self):
        callers = {p.name for p in sorted(SCRIPTS_DIR.glob("*.sh"))
                   if any("radar import-futures-day" in ln for ln in _code_lines(p))}
        self.assertEqual(callers, self.CALLERS)

    def test_call_is_bare_and_not_wrapped_in_the_failing_helper(self):
        for name in sorted(self.CALLERS):
            with self.subTest(script=name):
                lines = [ln for ln in _code_lines(SCRIPTS_DIR / name)
                         if "import-futures-day" in ln]
                self.assertEqual(len(lines), 1)
                # 分點輪帶 --date "$ROUND_DATE"(跨午夜仍是資料日,docs/47 §8.8);法人輪不會跨午夜。
                self.assertRegex(lines[0], r'if radar import-futures-day( --date "\$ROUND_DATE")?; then')
                self.assertNotIn("run_step_or_fail", lines[0])

    def test_insti_round_never_notifies_and_never_exits(self):
        """2026-10-22 降噪:法人輪不是最後一次機會(分點輪兩輪都會再試),75 與錯誤都只記 log。"""
        code = "\n".join(_code_lines(SCRIPTS_DIR / "daily-insti.sh"))
        m = re.search(r"^try_futures_day\(\) \{.*?^\}", code, re.S | re.M)
        self.assertIsNotNone(m)
        self.assertNotIn("notify", m.group(0))
        self.assertNotRegex(m.group(0), r"(?m)^\s*exit\b")

    def test_branch_rounds_75_is_quiet_and_only_the_last_round_warns(self):
        code = "\n".join(_code_lines(SCRIPTS_DIR / "daily-branches.sh"))
        block = self._block(code, 'if [ "$fd_rc" -eq 75 ]; then')
        pending, first_round, last_round = re.split(r"\n\s*elif [^\n]*\n", block)
        self.assertNotIn("notify", pending)
        self.assertNotIn("notify", first_round)
        self.assertIn("notify_warn", last_round)
        self.assertNotRegex(block, r"(?m)^\s*exit\b")
        self.assertIn('[ "$fd_rc" -ne 0 ] && [ "$BRANCH_ROUND_MODE" != "import" ]', block)

    def test_insti_calls_it_before_the_exit_75(self):
        lines = _code_lines(SCRIPTS_DIR / "daily-insti.sh")
        call = next(i for i, ln in enumerate(lines) if "radar import-futures-day" in ln)
        exit75 = next(i for i, ln in enumerate(lines) if re.search(r"\bexit 75\b", ln))
        self.assertLess(call, exit75)

    def test_branches_calls_it_after_import_daily(self):
        lines = _code_lines(SCRIPTS_DIR / "daily-branches.sh")
        imp = next(i for i, ln in enumerate(lines)
                   if re.search(r'run_step_or_fail(_unless)? "import-daily"', ln))
        call = next(i for i, ln in enumerate(lines) if "radar import-futures-day" in ln)
        self.assertGreater(call, imp)
        compute = next(i for i, ln in enumerate(lines)
                       if re.search(r'run_step_or_fail(_unless)? "compute-indicators"', ln))
        self.assertLess(call, compute)

    def test_the_gated_script_is_gone(self):
        self.assertFalse((SCRIPTS_DIR / "futures-day.sh").exists())


class RevisionWarnInMarginRound(unittest.TestCase):
    def test_margin_round_warns_on_changed_rows(self):
        code = "\n".join(_code_lines(SCRIPTS_DIR / "daily-margin.sh"))
        self.assertRegex(code, r"if radar import-futures \| tee \"\$FUTURES_OUT\"; then")
        self.assertIn("futures revision check:", code)
        self.assertRegex(code, r'"\$futures_changed" -gt 0 \]; then\s*\n\s*notify_warn')


if __name__ == "__main__":
    unittest.main()
