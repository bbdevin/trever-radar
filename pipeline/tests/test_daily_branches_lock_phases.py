# -*- coding: utf-8 -*-
"""docs/47 §8:分點輪的鎖相位與前置步驟的寬鬆分級——對**真的 lib.sh** 用 stub 量測。

兩類測試:

1. **stub harness**(需要 bash + flock + fuser;沒有就 skip):source 真的 lib.sh,
   把 `radar` / `notify` / `radar_ro_sql` 換成 stub,實際執行 helper 與鎖函式,斷言
   離開碼、通知、以及鎖在各相位的狀態(別的程序 `flock -n` 搶不搶得到、`fuser` 看不看得到)。
2. **原始碼解析**(同 test_daily_branches_exit_codes.py 手法):鎖的順序與相位寫在
   daily-branches.sh 的文字裡——DB 鎖 → 來源鎖;探測與抓取之間不重新拿鎖;寫入前拿鎖。
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
SCRIPT = SCRIPTS_DIR / "daily-branches.sh"
LIB = SCRIPTS_DIR / "lib.sh"

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


def _bash_path(p: Path) -> str:
    """Windows 上的 bash 是 WSL:D:\\x → /mnt/d/x。Linux 原樣。"""
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
source "__LIB__"
trap - ERR
# stubs(定義在 source 之後,蓋掉 lib.sh 的版本)
notify() { echo "NOTIFY pri=${2:-high} kind=${3:-} msg=$1"; }
radar() { echo "radar $*"; return "${RADAR_RC:-0}"; }
radar_ro_sql() { echo "${RO_SQL_OUT:-}"; }
set_round_consequence "測試用後果句"
"""


def _run_harness(body: str, env: dict | None = None) -> subprocess.CompletedProcess:
    """腳本寫成 UTF-8 暫存檔再 `bash <檔>`:Windows 上的 bash 是 WSL,argv 與環境變數
    都不會原樣傳進去(非 ASCII 會被吃掉、env 不傳遞),所以 env 也寫進腳本開頭。"""
    exports = "".join(f"export {k}={v!r}\n".replace("'", '"') for k, v in (env or {}).items())
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


@unittest.skipUnless(_bash_available(), "需要 bash + flock + fuser")
class LenientPrestepHarness(unittest.TestCase):
    """run_step_or_fail_unless / run_step_or_warn 對真的 lib.sh 實測。"""

    def test_failed_prestep_with_data_already_in_db_warns_and_continues(self):
        """2026-10-06 的事故形狀:補抓回 1、今天的日K已在庫 → warn 一則、續跑、離開碼 0。"""
        r = _run_harness("""
pred_true() { return 0; }
run_step_or_fail_unless "import-daily" pred_true radar import-daily --datasets quotes,insti
echo CONTINUED
""", {"RADAR_RC": "1"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("CONTINUED", r.stdout)
        self.assertRegex(r.stdout, r"NOTIFY pri=default kind=注意 msg=import-daily 失敗（碼 1）")
        self.assertNotIn("pri=high", r.stdout)
        self.assertIn("step import-daily done rc=1", r.stdout, "計時行照常")

    def test_failed_prestep_without_todays_data_aborts_with_the_original_code(self):
        r = _run_harness("""
pred_false() { return 1; }
run_step_or_fail_unless "import-daily" pred_false radar import-daily --datasets quotes,insti
echo CONTINUED
""", {"RADAR_RC": "7"})
        self.assertEqual(r.returncode, 7, "帶原碼中止,不壓成 1")
        self.assertNotIn("CONTINUED", r.stdout)
        self.assertRegex(r.stdout, r"NOTIFY pri=high kind=失敗 msg=import-daily 失敗（碼 7）.*測試用後果句")

    def test_successful_prestep_is_silent(self):
        r = _run_harness("""
pred_false() { return 1; }
run_step_or_fail_unless "import-daily" pred_false radar import-daily
echo CONTINUED
""", {"RADAR_RC": "0"})
        self.assertEqual(r.returncode, 0)
        self.assertIn("CONTINUED", r.stdout)
        self.assertNotIn("NOTIFY", r.stdout)

    def test_prestep_without_declared_consequence_refuses_like_run_step_or_fail(self):
        r = _run_harness("""
ROUND_FAIL_CONSEQUENCE=""
pred_true() { return 0; }
run_step_or_fail_unless "import-daily" pred_true radar import-daily
echo CONTINUED
""")
        self.assertEqual(r.returncode, 78)
        self.assertNotIn("CONTINUED", r.stdout)

    def test_run_step_or_warn_never_aborts(self):
        r = _run_harness("""
run_step_or_warn "seed-branches" radar seed-branches
echo CONTINUED
""", {"RADAR_RC": "9"})
        self.assertEqual(r.returncode, 0)
        self.assertIn("CONTINUED", r.stdout)
        self.assertRegex(r.stdout, r"NOTIFY pri=default kind=注意 msg=seed-branches 失敗（碼 9）")

    def test_the_real_predicates_read_the_db_through_the_ro_query(self):
        """price_date_is_today / indicators_date_is_today:MAX(date) == 今天 → 0;否則 1;
        查不到 → 0(視為照常跑/已算過)。"""
        r = _run_harness("""
today="$(taipei_date +%F)"
RO_SQL_OUT="$today" price_date_is_today && echo P1
RO_SQL_OUT="2000-01-01" price_date_is_today || echo P2
RO_SQL_OUT="" price_date_is_today && echo P3
RO_SQL_OUT="$today" indicators_date_is_today && echo I1
RO_SQL_OUT="2000-01-01" indicators_date_is_today || echo I2
RO_SQL_OUT="" indicators_date_is_today && echo I3
""")
        for tag in ("P1", "P2", "P3", "I1", "I2", "I3"):
            self.assertIn(tag, r.stdout, r.stdout + r.stderr)


@unittest.skipUnless(_bash_available(), "需要 bash + flock + fuser")
class LockPhaseHarness(unittest.TestCase):
    """抓取相位真的不握鎖:別的程序 flock -n 搶得到;寫入前 db_lock_take 又拿得回來。"""

    def test_lock_is_free_while_released_and_retaken_before_commit(self):
        r = _run_harness("""
other_can_lock() { ( exec 7>"$RADAR_DB_LOCK_FILE"; flock -n 7 ) && echo "other:FREE" || echo "other:HELD"; }
db_lock_take 5 && echo "phase1 taken"
other_can_lock                      # 匯入/指標階段:別人搶不到
release_db_lock
other_can_lock                      # 探測 + 抓取階段:別人搶得到(資券輪、夜間作業都能進)
if fuser "$RADAR_DB_LOCK_FILE" >/dev/null 2>&1; then echo "fuser:SEEN"; else echo "fuser:UNSEEN"; fi
db_lock_take 5 && echo "phase3 retaken"
other_can_lock                      # 寫入 + 上線:別人又搶不到
""")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        lines = [ln for ln in r.stdout.splitlines() if ln.startswith(("other:", "fuser:", "phase"))]
        self.assertEqual(lines, [
            "phase1 taken", "other:HELD",
            "other:FREE",
            # fd 9 整輪開著:fuser 仍看得到 → mid-backfill-publish 在抓取相位會略過(文件化的保守行為)。
            "fuser:SEEN",
            "phase3 retaken", "other:HELD",
        ])

    def test_lock_wait_times_out_instead_of_waiting_forever(self):
        """每一次等鎖都有上限:別人握著時 db_lock_take 1 在 ~1 秒後回非 0,不會永遠等。"""
        r = _run_harness("""
( exec 7>"$RADAR_DB_LOCK_FILE"; flock 7; sleep 4 ) &
holder=$!
sleep 0.5
t0=$(date +%s)
if db_lock_take 1; then echo "took"; else echo "timeout rc=$?"; fi
echo "waited=$(( $(date +%s) - t0 ))"
wait $holder
""")
        self.assertIn("timeout rc=1", r.stdout, r.stdout + r.stderr)
        waited = int(re.search(r"waited=(\d+)", r.stdout).group(1))
        self.assertLessEqual(waited, 3)

    def test_non_blocking_source_lock_still_skips(self):
        """其他腳本(warrant-backfill、poc)的來源鎖仍是 flock -n:搶不到就 exit 0,不等。"""
        r = _run_harness("""
( exec 8>/tmp/radar-branch-source.lock; flock 8; sleep 3 ) &
holder=$!
sleep 0.5
notify_skip() { echo "SKIP: $1"; }
( acquire_branch_source_lock; echo "got source lock" ); echo "rc=$?"
wait $holder
""")
        self.assertIn("SKIP: 分點來源鎖占用", r.stdout, r.stdout + r.stderr)
        self.assertNotIn("got source lock", r.stdout)
        self.assertIn("rc=0", r.stdout)

    def test_second_round_waits_for_the_source_lock_then_gets_it(self):
        """MED 3(2026-10-07 驗證者):22:30 撞上還在抓的第一輪要**等**,不能略過。
        holder 握 2 秒就放;等鎖版在上限內拿到、印出等了幾秒。"""
        r = _run_harness("""
( exec 8>/tmp/radar-branch-source.lock; flock 8; sleep 2 ) &
holder=$!
sleep 0.3
acquire_branch_source_lock_wait 10; echo "rc=$?"
( exec 7>/tmp/radar-branch-source.lock; flock -n 7 ) && echo "other:FREE" || echo "other:HELD"
wait $holder
""")
        self.assertRegex(r.stdout, r"branch source lock acquired waited=[1-4]s", r.stdout + r.stderr)
        self.assertIn("rc=0", r.stdout)
        self.assertIn("other:HELD", r.stdout, "拿到之後就是獨占")
        self.assertNotIn("NOTIFY", r.stdout)

    def test_source_lock_wait_times_out_loudly_and_exits_zero(self):
        r = _run_harness("""
( exec 8>/tmp/radar-branch-source.lock; flock 8; sleep 4 ) &
holder=$!
sleep 0.3
( acquire_branch_source_lock_wait 1; echo "got it" ); echo "rc=$?"
wait $holder
""")
        self.assertNotIn("got it", r.stdout, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"NOTIFY pri=high kind=失敗 msg=分點來源鎖等滿 1 秒")
        self.assertIn("rc=0", r.stdout)


class LockPhasesInTheScript(unittest.TestCase):
    """daily-branches.sh 的鎖相位,由原始碼直接解析。"""

    @classmethod
    def setUpClass(cls):
        cls.lines = _code_lines(SCRIPT)
        cls.code = "\n".join(cls.lines)

    def _idx(self, needle: str) -> int:
        i = self.code.find(needle)
        self.assertNotEqual(i, -1, f"找不到 {needle!r}")
        return i

    def test_lock_order_is_source_then_db_and_both_waits_are_bounded(self):
        """來源鎖(等)→ DB 鎖(等)。反過來先握 DB 鎖再等來源鎖,第一輪要寫入時拿不到
        DB 鎖、第二輪拿不到來源鎖,兩輪互等到逾時。其他拿來源鎖的腳本都是 flock -n。"""
        src = self._idx("acquire_branch_source_lock_wait 5400")
        self.assertLess(src, self._idx("acquire_db_lock_wait 3600"))
        self.assertEqual(self.code.count("acquire_branch_source_lock"), 1)
        self.assertNotIn("\nacquire_branch_source_lock\n", self.code, "第二輪不可以用會略過的那版")
        for name in ("warrant-backfill.sh", "daily-warrant-branches-poc.sh"):
            code = "\n".join(_code_lines(SCRIPTS_DIR / name))
            with self.subTest(script=name):
                self.assertNotIn("acquire_branch_source_lock_wait", code,
                                 "握著 DB 鎖的腳本只准非阻塞地拿來源鎖")

    def test_containers_run_with_init_so_sigterm_reaches_python(self):
        """HIGH 2(2026-10-07 驗證者):python 是容器 PID 1,沒有 init 時 SIGTERM 被忽略,
        `timeout` 只殺得掉 docker CLI。radar() 與 radar_timeout() 都要 --init。"""
        lib = LIB.read_text(encoding="utf-8")
        # `docker run … \` 接下一行的 --env-file:看整個續行區塊(每行以 `\` 收尾)。
        blocks = re.findall(r"docker run --rm[^\n]*?\\\n(?:[^\n]*?\\\n)*[^\n]*", lib)
        wrapped = [b for b in blocks if "--env-file" in b]
        self.assertEqual(len(wrapped), 2, f"radar() 與 radar_timeout() 各一:{blocks}")
        for b in wrapped:
            self.assertRegex(b.splitlines()[0], r"docker run --rm --init", b)

    def test_stage_tmp_is_cleaned_on_every_exit_and_old_stages_are_purged(self):
        self.assertIn("trap 'branch_stage_cleanup' EXIT", self.code)
        trap = self._idx("trap 'branch_stage_cleanup' EXIT")
        self.assertLess(trap, self._idx("sync_code"), "要裝在第一次呼叫 radar 之前")
        # 第二次驗證的競賽:清理在拿到來源鎖**之後**——鎖拿到之前,今天的 .tmp 可能是還在抓的
        # 第一輪正在寫的檔。trap、立即清理、find 三者都要在來源鎖之後、DB 鎖之前。
        src = self._idx("acquire_branch_source_lock_wait 5400")
        find = self._idx("find \"$REPO/data\" -maxdepth 1 -name 'branch-stage-*.json*'")
        self.assertLess(src, trap)
        self.assertLess(src, find)
        self.assertLess(find, self._idx("acquire_db_lock_wait 3600"))
        self.assertEqual(self.code.count("branch_stage_cleanup"), 3, "定義、trap、立即清理各一")
        self.assertNotIn("branch_stage_cleanup", self.code[:src].replace("branch_stage_cleanup() {", ""),
                         "來源鎖之前不得呼叫清理")
        m = re.search(r"branch_stage_cleanup\(\)\s*\{(.*?)\n\}", self.code, re.S)
        self.assertIsNotNone(m)
        self.assertIn('"${STAGE_FILE_HOST}.tmp"', m.group(1))
        self.assertNotIn('rm -f "$STAGE_FILE_HOST"', m.group(1),
                         "暫存檔本體不在 EXIT 時刪:被砍掉時要留給第二輪續抓")
        self.assertRegex(self.code, r"find \"\$REPO/data\" -maxdepth 1 -name 'branch-stage-\*\.json\*' ! -name")
        gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("data/branch-stage-*.json*", gitignore)

    def test_probe_never_starts_on_a_single_mirror(self):
        """HIGH 1:一站就緒就開爬 = 單站 5 秒 × 2,700 檔 = 13,500 秒 > 9000 硬上限。
        10-08 起要 2 站(0.4 req/s,~112 分 < 上限;其餘站待命加入,docs/47 §8.8)。"""
        fn = re.search(r"branch_probe_attempt\(\)\s*\{(.*?)\n\}", self.code, re.S).group(1)
        for n in re.findall(r"need=(\d+)", fn):
            self.assertGreaterEqual(int(n), 2, "任何時刻都不准 1 站開爬")

    def test_consequence_is_rewritten_after_the_first_publish(self):
        """LOW-MED 4:第一段上線之後失敗,通知不能再說「網站仍是前一輪的內容」。"""
        first = self._publish_calls()[0]
        after = self.code.index("set_round_consequence", first)
        self.assertLess(after, self._idx("radar compute-branch-stats"))
        line = self.code[self.code.rfind("\n", 0, after) + 1:self.code.index("\n", after)]
        self.assertIn("已於第一段上線", line)
        self.assertIn("00:05", line)

    def test_fetch_runs_between_release_and_reacquire_and_commit_after_reacquire(self):
        release = self._idx("release_db_lock")
        fetch = self._idx('run_step_or_fail "fetch-branch-trades"')
        reacquire = self.code.index("acquire_db_lock_wait", release)
        commit = self._idx('if run_step "import-branch-trades" radar import-branch-trades --from-stage')
        self.assertLess(release, fetch, "抓取前先放 DB 鎖")
        self.assertLess(fetch, reacquire, "抓取期間不拿鎖")
        self.assertLess(reacquire, commit, "寫入前重新拿鎖")
        self.assertEqual(self.code.count("release_db_lock"), 1, "整輪只放一次鎖")
        self.assertEqual(self.code.count("acquire_db_lock_wait"), 2, "開輪一次、寫入前一次")

    def test_fetch_is_bounded_and_writes_nothing(self):
        line = next(ln for ln in self.lines if 'run_step_or_fail "fetch-branch-trades"' in ln)
        self.assertIn("radar_timeout 9000", line, "抓取要有硬上限")
        self.assertIn("--workers 5", line)
        self.assertIn('--stage-to "$STAGE_FILE"', line, "只抓不寫:結果落暫存檔")
        self.assertIn("--sleep 1.0", line, "全域間隔不變(單站 = 1.0 × 5 秒)")
        commit = next(ln for ln in self.lines if "import-branch-trades --from-stage" in ln)
        self.assertNotIn("--workers", commit)
        self.assertNotIn("--sleep", commit, "寫入步驟不碰網路")

    def test_every_lock_wait_has_a_timeout(self):
        for ln in self.lines:
            s = ln.strip()
            if s.startswith("acquire_db_lock_wait"):
                self.assertRegex(s, r"^acquire_db_lock_wait \d+$", f"等鎖要有秒數:{s}")
            self.assertFalse(s.startswith("acquire_db_lock\n"), "不用會略過整輪的 acquire_db_lock")
        self.assertNotIn("\nacquire_db_lock\n", self.code)

    def test_probe_releases_db_lock_but_keeps_the_source_lock(self):
        probe = self._idx('poll_until "branch-probe"')
        self.assertIn("POLL_HOLD_DB_LOCK=0", self.code[self.code.rfind("\n", 0, probe):probe])
        self.assertLess(self._idx("release_db_lock"), probe)
        self.assertNotIn("flock -u 8", self.code, "來源鎖整輪不放")

    def test_two_phase_publish_both_run_under_the_db_lock(self):
        reacquire = self.code.index("acquire_db_lock_wait", self._idx("release_db_lock"))
        for needle in ("radar compute-branch-stats", "radar compute-scores"):
            with self.subTest(step=needle.strip()):
                self.assertGreater(self._idx(needle), reacquire)
        calls = self._publish_calls()
        self.assertEqual(len(calls), 2)
        self.assertGreater(calls[0], reacquire)

    def _publish_calls(self) -> list[int]:
        """`publish_site` 被呼叫的位置(整行只有它,允許縮排;函式定義不算)。"""
        return [m.start() for m in re.finditer(r"(?m)^\s*publish_site$", self.code)]

    def test_fast_publish_is_gated_on_coverage_and_the_refresh_round_always_publishes(self):
        """docs/47 §8.8(10-08):第一段只在覆蓋率 ≥ 0.98 時先上線;只刷新評分的第二輪一律上線。"""
        self.assertIn('BRANCH_FAST_PUBLISH_MIN_RATIO="${BRANCH_FAST_PUBLISH_MIN_RATIO:-0.98}"', self.code)
        gate = self._idx('if [ "$FAST_PUBLISH" = 1 ]; then')
        calls = self._publish_calls()
        self.assertLess(gate, calls[0], "第一次上線在門檻之內")
        self.assertLess(calls[0], self.code.index("\nelse\n", gate))
        self.assertGreater(calls[1], self.code.index("\nfi\n", calls[0]), "第二次上線在門檻之外")
        guard = self._idx('if [ -s "$(branch_round_marker "$ROUND_DATE")" ]; then\n    SCORES_REFRESH=1')
        self.assertIn("FAST_PUBLISH=1", self.code[guard:self.code.index("else", guard)],
                      "刷新輪不看覆蓋率門檻")
        self.assertLess(self._idx("FAST_PUBLISH=0"), guard)
        self.assertLess(self._idx('COVERAGE_RATIO="$(branch_round_coverage_ratio'), self._idx("FAST_PUBLISH=0"))
        skipped = self.code[self.code.index("\nelse\n", gate):self.code.index("\nfi\n", calls[0])]
        self.assertIn("fast publish skipped", skipped)
        self.assertIn("notify_warn", skipped)

    def test_probe_requires_two_consecutive_passes_and_three_hosts_until_1900_then_two(self):
        """§8.8 第四次驗證:2 站只剩 ~5% 餘裕 → 19:00 前要 3 站,之後 2 站;抓取上限 9000 秒。"""
        line = next(ln for ln in self.lines if "probe-branch-day" in ln)
        self.assertIn('--min-ready-hosts "$need"', line)
        self.assertIn("--min-consecutive 2", line)
        m = re.search(r"branch_probe_attempt\(\)\s*\{(.*?)\n\}", self.code, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertIn("local need=3", body)
        self.assertRegex(body, r'-ge "\$BRANCH_PROBE_THREE_HOSTS_UNTIL" \]; then\n\s*need=2')
        self.assertIn('BRANCH_PROBE_THREE_HOSTS_UNTIL="${BRANCH_PROBE_THREE_HOSTS_UNTIL:-1900}"', self.code)
        self.assertIn('poll_until "branch-probe" 2030 600 branch_probe_attempt', self.code)
        fetch = next(ln for ln in self.lines if 'run_step_or_fail "fetch-branch-trades"' in ln)
        self.assertIn("radar_timeout 9000", fetch)
        # 「當天一定有人上線」:第二輪等來源鎖的上限要蓋過第一輪最壞收工(20:30 + 9000 s + ~50 分 ≈ 23:50)。
        self.assertIn("acquire_branch_source_lock_wait 5400", self.code)

    def test_probe_attempt_picks_three_hosts_before_the_cutoff_and_two_after(self):
        """stub harness:branch_probe_attempt 依台北時刻決定 --min-ready-hosts。"""
        if not _bash_available():
            self.skipTest("需要 bash")
        fn = re.search(r"(branch_probe_attempt\(\)\s*\{.*?\n\})", self.code, re.S).group(1)
        r = _run_harness(f"""
radar_timeout() {{ echo "ARGS $*"; }}
ROUND_DATE="2026-10-08"
BRANCH_PROBE_THREE_HOSTS_UNTIL=1900
{fn}
taipei_date() {{ echo 1859; }}; branch_probe_attempt
taipei_date() {{ echo 1900; }}; branch_probe_attempt
taipei_date() {{ echo 2029; }}; branch_probe_attempt
BRANCH_PROBE_THREE_HOSTS_UNTIL=2100
taipei_date() {{ echo 2029; }}; branch_probe_attempt
""")
        needs = re.findall(r"--min-ready-hosts (\d)", r.stdout)
        self.assertEqual(needs, ["3", "2", "2", "3"], r.stdout + r.stderr)

    def test_every_date_sensitive_call_uses_round_date_not_the_clock(self):
        """第五次驗證(2026-10-08):第二輪可能等鎖到 00:00 之後,台北「今天」= D+1。
        所有看日曆日的匯入/述詞/探測/抓取/評分一律帶 $ROUND_DATE。"""
        self.assertIn('radar import-daily --date "${ROUND_DATE//-/}" --datasets quotes,insti', self.code)
        self.assertIn('round_prices_present() { price_date_is_today "$ROUND_DATE"; }', self.code)
        self.assertIn('round_indicators_present() { indicators_date_is_today "$ROUND_DATE"; }', self.code)
        self.assertIn('if ! price_date_is_today "$ROUND_DATE"; then', self.code)
        self.assertIn('radar import-futures-day --date "$ROUND_DATE"', self.code)
        self.assertIn('probe-branch-day --date "${ROUND_DATE//-/}"', self.code)
        self.assertIn('import-branch-trades --date "${ROUND_DATE//-/}" --top 0', self.code)
        self.assertIn('radar compute-scores --date "${ROUND_DATE//-/}"', self.code)
        self.assertIn('--date "${ROUND_DATE//-/}" --require twse:margin,tpex:margin', self.code)
        # 不准再有不帶日期的「今天」判斷:預設版 price_date_is_today / indicators_date_is_today
        # 只能出現在帶 $ROUND_DATE 的那幾處。
        for fn in ("price_date_is_today", "indicators_date_is_today"):
            for m in re.finditer(fn + r"\b(?!\(\))", self.code):
                tail = self.code[m.end():m.end() + 16]
                self.assertTrue(tail.startswith(' "$ROUND_DATE"'),
                                f"{fn} 必須帶 $ROUND_DATE:…{self.code[m.start()-20:m.end()+16]!r}")
        # taipei_date 只准用在:定 ROUND_DATE、log 時戳、探測站數的時刻門檻、資券的 21:00 判斷。
        for ln in self.lines:
            if "taipei_date" not in ln:
                continue
            s = ln.strip()
            ok = (s.startswith("ROUND_DATE=") or "daily-branches start" in s or "daily-branches done" in s
                  or "BRANCH_PROBE_THREE_HOSTS_UNTIL" in s or "-ge 21" in s or "printf" in s)
            self.assertTrue(ok, f"taipei_date 出現在不該看時鐘的地方:{s}")

    @unittest.skipUnless(_bash_available(), "需要 bash + flock + fuser")
    def test_midnight_crossing_harness(self):
        """stub harness:開跑 10-08、拿到鎖時時鐘已是 10-09。述詞與休市判斷(腳本裡的原句)
        都要以 ROUND_DATE 問資料庫 → 不會誤判休市;預設版(問時鐘)才會誤判——這就是修掉的 bug。"""
        defs = "\n".join(ln for ln in self.lines
                         if ln.startswith(("round_prices_present()", "round_indicators_present()")))
        holiday = next(ln for ln in self.lines if ln.startswith("if ! price_date_is_today"))
        r = _run_harness(f"""
ROUND_DATE="2026-10-08"
taipei_date() {{ if [ "${{1:-}}" = "+%F" ]; then echo 2026-10-09; else TZ=Asia/Taipei date "$@"; fi; }}
RO_SQL_OUT="2026-10-08"
{defs}
round_prices_present && echo "PRED_PRICES_OK"
round_indicators_present && echo "PRED_IND_OK"
{holiday}
  echo "HOLIDAY_MISJUDGED"
fi
price_date_is_today || echo "CLOCK_DEFAULT_WOULD_MISJUDGE"
""")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("PRED_PRICES_OK", r.stdout)
        self.assertIn("PRED_IND_OK", r.stdout)
        self.assertNotIn("HOLIDAY_MISJUDGED", r.stdout, "跨午夜不可以誤判休市")
        self.assertIn("CLOCK_DEFAULT_WOULD_MISJUDGE", r.stdout, "對照:預設版問時鐘才會誤判")

    def test_futures_digest_lives_inside_publish_site_once(self):
        body = self.code[self._idx("publish_site() {"):self.code.index("\n}\n", self._idx("publish_site() {"))]
        self.assertIn("futures_digest", body)
        self.assertLess(body.index("deploy_data"), body.index("futures_digest"))
        self.assertEqual(sum(1 for ln in self.lines if ln.strip() == "futures_digest"), 1)

    def test_bf_guard_pauses_backfill_while_the_source_lock_is_held(self):
        """bf 容器打同五個鏡像站:分點輪握著來源鎖(含不握 DB 鎖的抓取相位)時 bf 要停。"""
        guard = "\n".join(_code_lines(SCRIPTS_DIR / "bf-cron-guard.sh"))
        self.assertIn("fuser /tmp/radar-branch-source.lock", guard)
        m = re.search(r"should_pause\(\)\s*\{(.*?)\}", guard)
        self.assertIsNotNone(m)
        self.assertIn("source_held", m.group(1))
        self.assertIn("lock_held", m.group(1))


if __name__ == "__main__":
    unittest.main()
