# -*- coding: utf-8 -*-
"""docs/38 §7.18 的接線狀態,由腳本原始碼直接解析(同 test_daily_rounds_step_notify.py 手法)。

1. 唯讀的發布時間量測 `probe-futures-day`(14:10/15:00/16:10 三輪取鎖前、寫
   ~/futures-probe.log)已量完,2026-10-07 依計畫整段移除:腳本、lib.sh 與 CLI 都不再有。
2. 會寫資料庫的 `import-futures-day` 自 2026-10-02 起接進 daily-insti.sh(16:10)與
   daily-branches.sh(17:40／22:00),裸呼叫、75 只記 log、其他非 0 只 warn、不擋本輪。
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

    def _branch_blocks(self, name: str) -> tuple[str, str, str]:
        code = "\n".join(_code_lines(SCRIPTS_DIR / name))
        # docs/47 起這段可能包在函式(daily-insti 的 try_futures_day)或 if 裡,允許縮排。
        m = re.search(
            r'if \[ "\$fd_rc" -eq 75 \]; then\n(.*?)\n\s*elif \[ "\$fd_rc" -ne 0 \]; then\n(.*?)\n\s*fi\n',
            code, re.S)
        self.assertIsNotNone(m, f"{name} 找不到 75 / 其他非 0 的分級區塊")
        return code, m.group(1), m.group(2)

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
                self.assertIn("if radar import-futures-day; then", lines[0])
                self.assertNotIn("run_step_or_fail", lines[0])

    def test_75_is_quiet_and_other_failures_only_warn(self):
        for name in sorted(self.CALLERS):
            with self.subTest(script=name):
                _, pending, failed = self._branch_blocks(name)
                self.assertNotIn("notify", pending)
                self.assertNotRegex(pending, r"(?m)^\s*exit\b")
                self.assertIn("notify_warn", failed)
                self.assertNotRegex(failed, r"(?m)^\s*exit\b")

    def test_insti_calls_it_before_the_exit_75(self):
        lines = _code_lines(SCRIPTS_DIR / "daily-insti.sh")
        call = next(i for i, ln in enumerate(lines) if "radar import-futures-day" in ln)
        exit75 = next(i for i, ln in enumerate(lines) if re.search(r"\bexit 75\b", ln))
        self.assertLess(call, exit75)

    def test_branches_calls_it_after_import_daily(self):
        lines = _code_lines(SCRIPTS_DIR / "daily-branches.sh")
        imp = next(i for i, ln in enumerate(lines) if 'run_step_or_fail "import-daily"' in ln)
        call = next(i for i, ln in enumerate(lines) if "radar import-futures-day" in ln)
        self.assertGreater(call, imp)
        compute = next(i for i, ln in enumerate(lines)
                       if 'run_step_or_fail "compute-indicators"' in ln)
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
