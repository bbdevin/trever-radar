# -*- coding: utf-8 -*-
"""2026-10-22 通知降噪:預期內／會自己好的狀況不再送「注意」,真的失敗照舊送。

對真的 lib.sh / 腳本原文做 bash 實測(本機有 bash 才跑;同 test_morning_index_script.py 手法):
* deploy_data:`wrangler deploy` 失敗才重試,最多 3 次、間隔 20 → 40 秒;用完回傳最後的碼。
* run_step_or_warn_pending:75 只寫 log;其他非零 warn 一則;永遠續跑。
* daily-insti.sh 的 try_futures_day:錯誤只記 log、最多試 FD_MAX_ERRORS 次。
原始碼層:14:05／14:45 的 import-index 用 _pending 版;16:00 法人輪(當天最後一次)照舊 warn。
"""
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

SCRIPTS = Path(__file__).resolve().parents[2] / "vps" / "scripts"
LIB_TEXT = (SCRIPTS / "lib.sh").read_text(encoding="utf-8")


def _fn(text: str, name: str) -> str:
    m = re.search(rf"^{name}\(\) \{{.*?^\}}", text, re.S | re.M)
    assert m, name
    return m.group(0)


def _line(text: str, prefix: str) -> str:
    m = re.search(rf"^{re.escape(prefix)}.*$", text, re.M)
    assert m, prefix
    return m.group(0)


def _bash(script: str, tmp: Path) -> subprocess.CompletedProcess:
    (tmp / "t.sh").write_text(script, encoding="utf-8", newline="\n")
    return subprocess.run(["bash", "t.sh"], cwd=tmp, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=30, check=False)


HAVE_BASH = shutil.which("bash") is not None


@unittest.skipUnless(HAVE_BASH, "需要 bash")
class DeployRetry(unittest.TestCase):
    """deploy_data 真的那一份 + 假 npx(依序回傳 NPX_RCS 的碼)+ 假 sleep。"""

    def run_deploy(self, rcs: str, call: str = 'if run_step "deploy" deploy_data; then echo "RC=0"; else echo "RC=$?"; fi'):
        with TemporaryDirectory() as t:
            tmp = Path(t)
            (tmp / "repo" / "cloudflare-data-worker" / "node_modules").mkdir(parents=True)
            script = "\n".join([
                "set -euo pipefail",
                'REPO="$PWD/repo"',
                'EV="$PWD/ev.log"',
                f'NPX_RCS="{rcs}"',
                "taipei_date() { echo 2026-10-22T08:00:00+08:00; }",
                'npx() { local rc; rc="${NPX_RCS%% *}"; NPX_RCS="${NPX_RCS#* }"; echo "npx:$*:$rc" >> "$EV"; return "$rc"; }',
                'sleep() { echo "sleep:$1" >> "$EV"; }',
                _line(LIB_TEXT, "DEPLOY_ATTEMPTS="),
                _line(LIB_TEXT, "DEPLOY_RETRY_SLEEPS="),
                _fn(LIB_TEXT, "run_step"),
                _fn(LIB_TEXT, "deploy_data"),
                ': > "$EV"',
                call,
                'echo "PWD_AFTER=$PWD"',
            ]) + "\n"
            r = _bash(script, tmp)
            ev = (tmp / "ev.log").read_text(encoding="utf-8").splitlines() if (tmp / "ev.log").exists() else []
            return r, ev, str(tmp / "repo")

    def test_first_attempt_ok_no_retry(self):
        r, ev, _ = self.run_deploy("0")
        self.assertIn("RC=0", r.stdout, r.stderr)
        self.assertEqual(ev, ["npx:wrangler deploy:0"])
        self.assertIn("deploy attempt 1/3 rc=0", r.stdout)

    def test_transient_failure_then_ok(self):
        r, ev, _ = self.run_deploy("1 0")
        self.assertIn("RC=0", r.stdout, r.stderr)
        self.assertEqual(ev, ["npx:wrangler deploy:1", "sleep:20", "npx:wrangler deploy:0"])
        self.assertIn("deploy attempt 1/3 rc=1", r.stdout)
        self.assertIn("deploy attempt 2/3 rc=0", r.stdout)

    def test_three_failures_return_last_code_after_20_40(self):
        r, ev, _ = self.run_deploy("1 7 9 0")
        self.assertIn("RC=9", r.stdout, r.stderr)
        self.assertEqual(ev, ["npx:wrangler deploy:1", "sleep:20", "npx:wrangler deploy:7",
                              "sleep:40", "npx:wrangler deploy:9"])
        self.assertRegex(r.stdout, r"PWD_AFTER=\S*/repo\n", "收尾要 cd 回 $REPO")

    def test_bare_call_still_aborts_with_the_code(self):
        r, ev, _ = self.run_deploy("9 9 9", call="deploy_data; echo REACHED")
        self.assertEqual(r.returncode, 9, r.stdout + r.stderr)
        self.assertNotIn("REACHED", r.stdout)
        self.assertEqual(len([e for e in ev if e.startswith("npx:")]), 3)

    def test_worst_case_sleep_is_bounded(self):
        attempts = int(re.search(r":-(\d+)", _line(LIB_TEXT, "DEPLOY_ATTEMPTS=")).group(1))
        sleeps = [int(x) for x in re.search(r':-([0-9 ]+)\}', _line(LIB_TEXT, "DEPLOY_RETRY_SLEEPS=")).group(1).split()]
        self.assertLessEqual(attempts, 3)
        self.assertLessEqual(sum(sleeps[: attempts - 1]), 60, "握 DB 鎖的輪多等的睡眠最多 60 秒")


@unittest.skipUnless(HAVE_BASH, "需要 bash")
class RunStepOrWarnPending(unittest.TestCase):
    def run_rc(self, rc: int):
        with TemporaryDirectory() as t:
            tmp = Path(t)
            script = "\n".join([
                "set -euo pipefail",
                "trap 'echo ERRTRAP' ERR",
                "taipei_date() { echo 2026-10-22T14:07:00+08:00; }",
                'notify_warn() { echo "WARN:$1"; }',
                'notify() { echo "NOTIFY:$1"; }',
                f"radar() {{ return {rc}; }}",
                _fn(LIB_TEXT, "run_step"),
                _fn(LIB_TEXT, "run_step_or_warn_pending"),
                'run_step_or_warn_pending "import-index" radar import-index',
                "echo CONTINUED",
            ]) + "\n"
            return _bash(script, tmp)

    def test_ok_is_silent(self):
        r = self.run_rc(0)
        self.assertIn("CONTINUED", r.stdout)
        self.assertNotIn("WARN:", r.stdout)

    def test_75_is_log_only(self):
        r = self.run_rc(75)
        self.assertIn("CONTINUED", r.stdout, r.stderr)
        self.assertNotIn("WARN:", r.stdout)
        self.assertNotIn("NOTIFY:", r.stdout)
        self.assertNotIn("ERRTRAP", r.stdout)
        self.assertIn("import-index pending (rc=75)", r.stdout)

    def test_real_error_still_warns_once(self):
        r = self.run_rc(1)
        self.assertIn("CONTINUED", r.stdout)
        self.assertEqual(r.stdout.count("WARN:"), 1, r.stdout)
        self.assertIn("WARN:import-index 失敗（碼 1）", r.stdout)
        self.assertNotIn("ERRTRAP", r.stdout)


@unittest.skipUnless(HAVE_BASH, "需要 bash")
class InstiFuturesDayIsQuiet(unittest.TestCase):
    INSTI = (SCRIPTS / "daily-insti.sh").read_text(encoding="utf-8")

    def run_attempts(self, rcs: str, n: int):
        with TemporaryDirectory() as t:
            tmp = Path(t)
            script = "\n".join([
                "set -euo pipefail",
                "trap 'echo ERRTRAP' ERR",
                'notify_warn() { echo "WARN:$1"; }',
                'notify() { echo "NOTIFY:$1"; }',
                f'RCS="{rcs}"',
                'radar() { local rc; rc="${RCS%% *}"; RCS="${RCS#* }"; echo "radar:$1:$rc"; return "$rc"; }',
                _line(self.INSTI, "FD_DONE=0"),
                _line(self.INSTI, "FD_ERRORS=0"),
                _line(self.INSTI, "FD_MAX_ERRORS="),
                _fn(self.INSTI, "try_futures_day"),
                *(['if [ "$FD_DONE" = "0" ]; then try_futures_day; fi'] * n),
                'echo "FD_DONE=$FD_DONE"',
            ]) + "\n"
            return _bash(script, tmp)

    def test_errors_are_not_notified_and_stop_after_two(self):
        r = self.run_attempts("1 1 0 0", 4)
        self.assertNotIn("WARN:", r.stdout)
        self.assertNotIn("NOTIFY:", r.stdout)
        self.assertNotIn("ERRTRAP", r.stdout)
        self.assertEqual(r.stdout.count("radar:import-futures-day"), 2, r.stdout)
        self.assertIn("FD_DONE=1", r.stdout)

    def test_error_then_success_on_next_attempt(self):
        r = self.run_attempts("1 0 0", 3)
        self.assertEqual(r.stdout.count("radar:import-futures-day"), 2, r.stdout)
        self.assertNotIn("WARN:", r.stdout)

    def test_pending_keeps_trying(self):
        r = self.run_attempts("75 75 75 0", 4)
        self.assertEqual(r.stdout.count("radar:import-futures-day"), 4, r.stdout)
        self.assertNotIn("WARN:", r.stdout)


class SourceWiring(unittest.TestCase):
    def read(self, name):
        return (SCRIPTS / name).read_text(encoding="utf-8")

    def test_early_rounds_do_not_warn_on_index_pending(self):
        for name in ("daily-market.sh", "daily-tpex-quotes.sh"):
            self.assertIn('run_step_or_warn_pending "import-index" radar import-index', self.read(name), name)

    def test_insti_round_is_the_last_index_import_and_still_warns_on_75(self):
        self.assertIn('run_step_or_warn "import-index" radar import-index', self.read("daily-insti.sh"))

    def test_no_stale_1730_branch_round_promises_in_insti(self):
        code = "\n".join(ln for ln in self.read("daily-insti.sh").splitlines() if not ln.lstrip().startswith("#"))
        self.assertNotIn("17:30 分點輪", code)
        self.assertNotIn("待17:30", code)

    def test_branch_round_futures_failure_warns_only_on_the_last_round(self):
        text = self.read("daily-branches.sh")
        self.assertIn('elif [ "$fd_rc" -ne 0 ] && [ "$BRANCH_ROUND_MODE" != "import" ]; then', text)


if __name__ == "__main__":
    unittest.main()
