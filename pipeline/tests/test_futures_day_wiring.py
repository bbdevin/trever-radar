# -*- coding: utf-8 -*-
"""docs/38 §7.18 的接線狀態,由腳本原始碼直接解析(同 test_daily_rounds_step_notify.py 手法)。

兩件事要同時成立:
1. 唯讀的 `probe-futures-day` 已掛進 14:10 / 15:00 / 16:10 三輪,而且**絕不影響本輪**:
   走 lib.sh 的 `futures_probe`(有逾時、不掛 data/、所有失敗都被 `||` 接住、永遠 return 0),
   位置在拿鎖之前(鎖被占略過、或 16:10 的 exit 75 提早收場的日子也量得到)。
2. 會寫資料庫的 `import-futures-day` 自 2026-10-02 起接進 daily-insti.sh(16:10)與
   daily-branches.sh(17:40／22:00),裸呼叫、75 只記 log、其他非 0 只 warn、不擋本輪。
"""
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "vps" / "scripts"
LIB = SCRIPTS_DIR / "lib.sh"
PROBED_ROUNDS = ("daily-market.sh", "daily-tpex-quotes.sh", "daily-insti.sh")

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


def _probe_body() -> str:
    lib = "\n".join(_code_lines(LIB))
    m = re.search(r"^futures_probe\(\)\s*\{(.*?)\n\}", lib, re.S | re.M)
    assert m, "lib.sh 裡找不到 futures_probe"
    return m.group(1)


class ProbeIsWiredAndHarmless(unittest.TestCase):
    def test_each_round_calls_the_probe_before_taking_the_lock(self):
        for name in PROBED_ROUNDS:
            with self.subTest(script=name):
                lines = [ln.strip() for ln in _code_lines(SCRIPTS_DIR / name)]
                self.assertIn("futures_probe", lines, f"{name} 沒有呼叫 futures_probe")
                probe = lines.index("futures_probe")
                lock = lines.index("acquire_db_lock")
                self.assertLess(probe, lock, "probe 要在拿鎖之前,鎖被占的日子也要量到")
                first_exit = next((i for i, ln in enumerate(lines)
                                   if re.search(r"\bexit\b|run_step_or_fail", ln)), len(lines))
                self.assertLess(probe, first_exit, "probe 要在任何提早收場之前")

    def test_probe_is_not_wrapped_in_a_failing_helper(self):
        for name in PROBED_ROUNDS:
            for ln in _code_lines(SCRIPTS_DIR / name):
                if "futures_probe" in ln or "probe-futures-day" in ln:
                    with self.subTest(script=name, line=ln.strip()):
                        self.assertEqual(ln.strip(), "futures_probe",
                                         "probe 只能裸呼叫 lib.sh 的 futures_probe")

    def test_probe_helper_has_a_hard_timeout(self):
        body = _probe_body()
        m = re.search(r"timeout\s+.*?\s(\d+)s\s", body, re.S)
        self.assertIsNotNone(m, "futures_probe 要有 timeout")
        self.assertLessEqual(int(m.group(1)), 60)

    def test_probe_helper_never_fails_the_round(self):
        body = _probe_body()
        self.assertRegex(body, r"\|\|\s*rc=\$\?", "docker 的離開碼要被 || 接住")
        self.assertRegex(body.strip().splitlines()[-1].strip(), r"^return 0$",
                         "最後一行必須是 return 0")
        self.assertNotIn("exit", body)
        self.assertNotRegex(body, r"\bnotify", "probe 失敗不通知")
        self.assertNotIn("set -e", body)

    def test_probe_container_cannot_reach_the_database(self):
        body = _probe_body()
        self.assertIn("probe-futures-day", body)
        self.assertNotIn("/app/data", body, "probe 的容器不掛 data/,物理上碰不到 radar.db")
        self.assertNotRegex(body, r"(?m)(^|\$\(|;)\s*radar(_timeout)?\s",
                            "不走 radar()/radar_timeout(會掛 data/)")
        self.assertNotIn("acquire_db_lock", body)

    def test_probe_logs_to_its_own_file(self):
        body = _probe_body()
        self.assertIn('tee -a "$FUTURES_PROBE_LOG"', body)
        lib = LIB.read_text(encoding="utf-8")
        self.assertRegex(lib, r'FUTURES_PROBE_LOG="\$\{FUTURES_PROBE_LOG:-\$\{HOME:-/tmp\}/futures-probe\.log\}"')


class ImportFuturesDayIsWired(unittest.TestCase):
    CALLERS = {"daily-branches.sh", "daily-insti.sh"}

    def _branch_blocks(self, name: str) -> tuple[str, str, str]:
        code = "\n".join(_code_lines(SCRIPTS_DIR / name))
        m = re.search(
            r'if \[ "\$fd_rc" -eq 75 \]; then\n(.*?)\nelif \[ "\$fd_rc" -ne 0 \]; then\n(.*?)\nfi\n',
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
