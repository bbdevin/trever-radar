# -*- coding: utf-8 -*-
"""docs/50 §3.1(2026-10-19):各日更輪在 export 之前「放 DB 鎖 → fetch-intraday → 拿回鎖」。

1. **stub harness**(需要 bash + flock + fuser;沒有就 skip):source 真的 lib.sh,把 `radar_timeout`
   / `notify` 換成 stub,實際執行 prefetch_intraday,斷言抓取那一刻 DB 鎖是空的(別的程序搶得到)、
   抓取鎖是握著的、回來時 DB 鎖又在手上;失敗/排隊逾時只 warn 照常續跑;拿不回 DB 鎖照
   acquire_db_lock_wait 的契約 high + exit 0;RADAR_EXPORT_FETCH=1 = 舊行為(不放鎖、不抓)。
2. **原始碼解析**:五支日更輪的 export-json 前一行就是 prefetch_intraday(裸呼叫),
   分點輪每輪只抓一次(第一次上線之前)。
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "vps" / "scripts"
LIB = SCRIPTS_DIR / "lib.sh"
ROUNDS = ("daily-market.sh", "daily-tpex-quotes.sh", "daily-insti.sh", "daily-margin.sh")

FULL_LINE_COMMENT = re.compile(r"^\s*#")
TRAILING_COMMENT = re.compile(r"(?<=\s)#.*$")


def _code_lines(path: Path) -> list[str]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        out.append("" if FULL_LINE_COMMENT.match(line) else TRAILING_COMMENT.sub("", line))
    return out


def _bash_path(p: Path) -> str:
    s = str(p)
    if sys.platform == "win32" and re.match(r"^[A-Za-z]:\\", s):
        return "/mnt/" + s[0].lower() + s[2:].replace("\\", "/")
    return s


def _bash_available() -> bool:
    if shutil.which("bash") is None:
        return False
    try:
        r = subprocess.run(["bash", "-c", "command -v flock && command -v fuser"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


HARNESS_PRELUDE = r"""
set -u
export HOME=/tmp
export NTFY=""
export RADAR_DB_LOCK_FILE="$(mktemp /tmp/radar-test-lock.XXXXXX)"
export INTRADAY_FETCH_LOCK_FILE="$(mktemp /tmp/radar-test-fetch-lock.XXXXXX)"
source "__LIB__"
trap - ERR
notify() { echo "NOTIFY pri=${2:-high} kind=${3:-} msg=$1"; }
other_db() { ( exec 7>"$RADAR_DB_LOCK_FILE"; flock -n 7 ) && echo "db:FREE" || echo "db:HELD"; }
other_fetch() { ( exec 5>"$INTRADAY_FETCH_LOCK_FILE"; flock -n 5 ) && echo "fetchlock:FREE" || echo "fetchlock:HELD"; }
radar_timeout() {
  echo "FETCH secs=$1 cmd=$2"
  other_db
  other_fetch
  if [ -n "${GRAB_DB_DURING_FETCH:-}" ]; then
    ( exec 7>"$RADAR_DB_LOCK_FILE"; flock 7; sleep 4 ) &
    sleep 0.5
  fi
  return "${FETCH_RC:-0}"
}
"""


def _run_harness(body: str, env: dict | None = None) -> subprocess.CompletedProcess:
    exports = "".join(f'export {k}="{v}"\n' for k, v in (env or {}).items())
    script = exports + HARNESS_PRELUDE.replace("__LIB__", _bash_path(LIB)) + "\n" + body
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False, encoding="utf-8",
                                     newline="\n") as fh:
        fh.write(script)
        path = Path(fh.name)
    try:
        return subprocess.run(["bash", _bash_path(path)], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=120)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _marks(stdout: str) -> list[str]:
    keep = ("db:", "fetchlock:", "FETCH ", "rc=", "NOTIFY", "CONTINUED", "taken")
    return [ln for ln in stdout.splitlines() if ln.startswith(keep)]


@unittest.skipUnless(_bash_available(), "需要 bash + flock + fuser")
class PrefetchHarness(unittest.TestCase):
    def test_fetch_runs_without_the_db_lock_and_returns_holding_it(self):
        r = _run_harness("""
db_lock_take 5 && echo "taken"
other_db
prefetch_intraday; echo "rc=$?"
other_db
other_fetch
if fuser "$RADAR_DB_LOCK_FILE" >/dev/null 2>&1; then echo "fuser:SEEN"; fi
""")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(_marks(r.stdout), [
            "taken", "db:HELD",
            "FETCH secs=900 cmd=fetch-intraday", "db:FREE", "fetchlock:HELD",  # 抓取那一刻
            "rc=0", "db:HELD", "fetchlock:FREE",                                 # 回來時
        ])
        self.assertIn("step fetch-intraday done rc=0", r.stdout, "計時行(與其他步驟同格式)")
        self.assertIn("fuser:SEEN", r.stdout, "fd 9 整輪開著:mid-backfill-publish 照舊略過")
        self.assertNotIn("NOTIFY", r.stdout)

    def test_fetch_failure_warns_and_continues_with_the_lock_retaken(self):
        r = _run_harness("""
db_lock_take 5
prefetch_intraday; echo "rc=$?"
other_db
echo CONTINUED
""", {"FETCH_RC": "1"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"NOTIFY pri=default kind=注意 msg=當日分時／分K 抓取未完成（碼 1）")
        self.assertNotIn("pri=high", r.stdout)
        self.assertEqual(_marks(r.stdout)[-3:], ["rc=0", "db:HELD", "CONTINUED"])

    def test_timeout_code_is_just_a_warning_too(self):
        r = _run_harness("db_lock_take 5\nprefetch_intraday\necho CONTINUED\n", {"FETCH_RC": "124"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("（碼 124）", r.stdout)
        self.assertIn("CONTINUED", r.stdout)

    def test_rollback_switch_keeps_the_lock_and_skips_the_fetch(self):
        r = _run_harness("""
db_lock_take 5
prefetch_intraday; echo "rc=$?"
other_db
""", {"RADAR_EXPORT_FETCH": "1"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("FETCH ", r.stdout)
        self.assertIn("fetch-intraday skipped: RADAR_EXPORT_FETCH=1", r.stdout)
        self.assertEqual(_marks(r.stdout), ["rc=0", "db:HELD"])

    def test_concurrent_fetch_queues_on_the_fetch_lock_then_gives_up_softly(self):
        """另一輪還在抓:排隊等抓取鎖;等滿 → 75、不抓、warn,照常拿回 DB 鎖 export。"""
        r = _run_harness("""
( exec 5>"$INTRADAY_FETCH_LOCK_FILE"; flock 5; sleep 4 ) &
holder=$!
sleep 0.5
db_lock_take 5
prefetch_intraday; echo "rc=$?"
other_db
wait $holder
""", {"INTRADAY_FETCH_LOCK_WAIT_SECS": "1"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("FETCH ", r.stdout)
        self.assertRegex(r.stdout, r"NOTIFY pri=default kind=注意 msg=.*（碼 75）")
        self.assertEqual(_marks(r.stdout)[-2:], ["rc=0", "db:HELD"])

    def test_concurrent_fetch_that_finishes_in_time_is_waited_for(self):
        r = _run_harness("""
( exec 5>"$INTRADAY_FETCH_LOCK_FILE"; flock 5; sleep 1 ) &
holder=$!
sleep 0.3
db_lock_take 5
prefetch_intraday; echo "rc=$?"
wait $holder
""", {"INTRADAY_FETCH_LOCK_WAIT_SECS": "10"})
        self.assertIn("FETCH secs=900 cmd=fetch-intraday", r.stdout, r.stdout + r.stderr)
        self.assertNotIn("NOTIFY", r.stdout)

    def test_db_lock_not_retaken_in_time_is_loud_and_exits_zero(self):
        """放鎖期間別人拿走 DB 鎖且超過上限:與分點輪寫入前等鎖同一個處置(high + exit 0),
        不在沒有鎖的情況下 export。"""
        r = _run_harness("""
db_lock_take 5
prefetch_intraday
echo CONTINUED
""", {"GRAB_DB_DURING_FETCH": "1", "PREFETCH_RELOCK_WAIT_SECS": "1"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("CONTINUED", r.stdout, "拿不回鎖就不能往下 export")
        self.assertRegex(r.stdout, r"NOTIFY pri=high kind=失敗 msg=資料庫鎖等滿 1 秒")

    def test_switch_reaches_the_container_env_file(self):
        r = _run_harness("""
radar_secret_env_new
cat "$RADAR_SECRET_ENV_FILE"
radar_secret_env_cleanup
""", {"RADAR_EXPORT_FETCH": "1", "FUGLE_API_KEY": "k"})
        self.assertIn("RADAR_EXPORT_FETCH=1", r.stdout, r.stdout + r.stderr)
        self.assertIn("FUGLE_API_KEY=k", r.stdout)


class PrefetchWiringInTheScripts(unittest.TestCase):
    def _prev_code_line(self, lines: list[str], i: int) -> str:
        j = i - 1
        while j >= 0 and not lines[j].strip():
            j -= 1
        return lines[j].strip()

    def test_every_round_prefetches_right_before_export(self):
        for name in ROUNDS:
            with self.subTest(script=name):
                lines = _code_lines(SCRIPTS_DIR / name)
                calls = [i for i, ln in enumerate(lines) if "prefetch_intraday" in ln]
                self.assertEqual(len(calls), 1, "每輪一次")
                self.assertEqual(lines[calls[0]].strip(), "prefetch_intraday",
                                 "裸呼叫:不包 run_step_or_fail(它自己 warn-and-continue)")
                export = next(i for i, ln in enumerate(lines)
                              if 'run_step_or_fail "export-json" radar export-json' in ln)
                self.assertEqual(self._prev_code_line(lines, export), "prefetch_intraday",
                                 "export 的前一步:聯集要在 compute/import-index 寫完之後才選")
                code = "\n".join(lines)
                self.assertLess(code.rindex("radar compute-scores"), code.index("prefetch_intraday"))

    def test_branch_round_prefetches_once_before_the_first_publish(self):
        lines = _code_lines(SCRIPTS_DIR / "daily-branches.sh")
        code = "\n".join(lines)
        body = re.search(r"publish_site\(\) \{\n(.*?)\n\}", code, re.S).group(1)
        self.assertRegex(body, r'if \[ "\$INTRADAY_PREFETCHED" = 0 \]; then\n\s+prefetch_intraday\n'
                               r'\s+INTRADAY_PREFETCHED=1\n\s+fi\n\s+run_step_or_fail "export-json" radar export-json')
        self.assertLess(code.index("INTRADAY_PREFETCHED=0"), code.index("publish_site() {"))
        self.assertEqual(code.count("prefetch_intraday"), 1)
        # 放/拿 DB 鎖時握著分點來源鎖:與抓分點那一段同一個鎖序(來源 → DB)。
        first_call = re.search(r"(?m)^\s*publish_site$", code).start()
        self.assertLess(code.index("acquire_branch_source_lock_wait"), first_call)

    def test_fetch_intraday_only_runs_through_the_helper(self):
        for p in SCRIPTS_DIR.glob("*.sh"):
            if p.name == "lib.sh":
                continue
            with self.subTest(script=p.name):
                self.assertNotIn("fetch-intraday", "\n".join(_code_lines(p)))
        lib = "\n".join(_code_lines(LIB))
        fn = re.search(r"prefetch_intraday\(\) \{\n(.*?)\n\}", lib, re.S).group(1)
        self.assertLess(fn.index("release_db_lock"), fn.index("fetch_intraday_queued"))
        self.assertLess(fn.index("fetch_intraday_queued"), fn.index("acquire_db_lock_wait"))
        q = re.search(r"fetch_intraday_queued\(\) \{\n(.*?)\n\}", lib, re.S).group(1)
        self.assertIn('radar_timeout "$FETCH_INTRADAY_TIMEOUT_SECS" fetch-intraday', q, "抓取有硬上限")
        self.assertIn('flock -w "$INTRADAY_FETCH_LOCK_WAIT_SECS" 6', q, "抓取彼此排隊、等待有上限")


if __name__ == "__main__":
    unittest.main()
