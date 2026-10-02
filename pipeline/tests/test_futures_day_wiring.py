# -*- coding: utf-8 -*-
"""docs/38 §7.18 的接線狀態,由腳本原始碼直接解析(同 test_daily_rounds_step_notify.py 手法)。

兩件事要同時成立:
1. 唯讀的 `probe-futures-day` 已掛進 14:10 / 15:00 / 16:10 三輪,而且**絕不影響本輪**:
   走 lib.sh 的 `futures_probe`(有逾時、不掛 data/、所有失敗都被 `||` 接住、永遠 return 0),
   位置在拿鎖之前(鎖被占略過、或 16:10 的 exit 75 提早收場的日子也量得到)。
2. 會寫資料庫的 `import-futures-day` **還沒有**接進任何輪——發布時間量測做完之前,
   它只存在於不被 cron、也不被任何腳本呼叫的 `futures-day.sh`。接上的那一天要改這裡。
"""
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "vps" / "scripts"
LIB = SCRIPTS_DIR / "lib.sh"
CRONTAB = SCRIPTS_DIR / "crontab.example"
GATED = "futures-day.sh"
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


class ImportFuturesDayIsNotWiredYet(unittest.TestCase):
    def test_no_script_but_the_gated_one_runs_import_futures_day(self):
        callers = [p.name for p in sorted(SCRIPTS_DIR.glob("*.sh"))
                   if any("import-futures-day" in ln for ln in _code_lines(p))]
        self.assertEqual(callers, [GATED],
                         "import-futures-day 在 docs/38 §7.18 量測完成前只能出現在 futures-day.sh")

    def test_gated_script_is_not_scheduled_or_called(self):
        cron_code = "\n".join(_code_lines(CRONTAB))
        self.assertNotIn(GATED, cron_code, "futures-day.sh 還不能進 crontab")
        for p in sorted(SCRIPTS_DIR.glob("*.sh")):
            if p.name == GATED:
                continue
            # lib.sh 的 job_zh 有一個 `futures-day.sh)` case 標籤(通知標題用),那不是呼叫。
            code = [ln for ln in _code_lines(p)
                    if not re.match(rf"^\s*{re.escape(GATED)}\)", ln)]
            with self.subTest(script=p.name):
                self.assertNotIn(GATED, "\n".join(code), f"{p.name} 不得呼叫 {GATED}")

    def test_gated_script_says_so_in_its_header(self):
        head = "\n".join((SCRIPTS_DIR / GATED).read_text(encoding="utf-8").splitlines()[:6])
        self.assertIn("GATED", head)
        self.assertIn("docs/38 §7.18", head)

    def test_gated_script_treats_75_as_pending_not_failure(self):
        code = "\n".join(_code_lines(SCRIPTS_DIR / GATED))
        self.assertRegex(code, r"if radar import-futures-day; then")
        self.assertRegex(code, r'"\$fd_rc" -eq 75 \]; then\s*\n\s*notify_skip')


class RevisionWarnInMarginRound(unittest.TestCase):
    def test_margin_round_warns_on_changed_rows(self):
        code = "\n".join(_code_lines(SCRIPTS_DIR / "daily-margin.sh"))
        self.assertRegex(code, r"if radar import-futures \| tee \"\$FUTURES_OUT\"; then")
        self.assertIn("futures revision check:", code)
        self.assertRegex(code, r'"\$futures_changed" -gt 0 \]; then\s*\n\s*notify_warn')


if __name__ == "__main__":
    unittest.main()
