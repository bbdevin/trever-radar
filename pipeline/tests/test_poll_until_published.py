# -*- coding: utf-8 -*-
"""docs/47 原則 1/4:輪詢到公布為止,絕不握著 DB 鎖等來源;搶不到鎖就等、不略過。

兩層:
* 原始碼解析(與 test_daily_rounds_step_notify.py 同手法):lib.sh 的 poll_until 有截止、
  75 之後先 `flock -u` 放鎖才 sleep;五支日更輪都用 acquire_db_lock_wait;分點探測等待期間
  不握 DB 鎖;data-backfill.sh 仍維持 flock -n(可續跑,讓路一晚零損失)。
* bash 實跑(本機有 bash/WSL 才跑):source 真的 lib.sh,用假指令(先 75 後 0)驗輪詢,
  並在 sleep 當下從另一個程序 `flock -n` 驗鎖確實是放開的。
"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "vps" / "scripts"
LIB = SCRIPTS / "lib.sh"

FULL_LINE_COMMENT = re.compile(r"^\s*#")
TRAILING_COMMENT = re.compile(r"(?<=\s)#.*$")
ROUNDS = ("daily-market.sh", "daily-tpex-quotes.sh", "daily-insti.sh",
          "daily-branches.sh", "daily-margin.sh")


def _code(path: Path) -> str:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        out.append("" if FULL_LINE_COMMENT.match(line) else TRAILING_COMMENT.sub("", line))
    return "\n".join(out)


def _fn(name: str) -> str:
    m = re.search(rf"^{name}\(\)\s*\{{(.*?)^\}}", _code(LIB), re.S | re.M)
    assert m, f"lib.sh 裡找不到 {name}()"
    return m.group(1)


class PollUntilSource(unittest.TestCase):
    def test_deadline_and_greppable_lines(self):
        body = _fn("poll_until")
        self.assertIn("dl_min", body, "要有截止時刻")
        self.assertIn("return 75", body, "截止仍未到 → 75")
        self.assertIn("poll ${label} ready at=", body)
        self.assertIn("poll ${label} deadline at=", body)
        self.assertIn("attempts=", body)

    def test_lock_is_released_after_every_75_before_sleeping(self):
        body = _fn("poll_until")
        rel = body.index("release_db_lock")
        for m in re.finditer(r"\bsleep\b", body):
            self.assertLess(rel, m.start(), "sleep 之前必須先放鎖")
        self.assertIn("flock -u 9", _fn("release_db_lock"))
        # 每一次嘗試前都重新拿鎖(會等,不會略過)。
        self.assertRegex(body, r"db_lock_take")
        self.assertIn("flock -w", _fn("db_lock_take"))

    def test_other_codes_return_immediately_with_the_raw_code(self):
        body = _fn("poll_until")
        self.assertRegex(body, r'if \[ "\$rc" -ne 75 \]; then')
        self.assertIn('return "$rc"', body)

    def test_radar_poll_0_is_single_attempt(self):
        body = _fn("poll_until")
        self.assertIn('"${RADAR_POLL:-1}" = "0"', body)

    def test_acquire_db_lock_wait_waits_then_alarms(self):
        body = _fn("acquire_db_lock_wait")
        self.assertIn("db_lock_take", body)
        self.assertRegex(body, r'notify "[^"]*" high "失敗"')
        self.assertIn("exit 0", body)
        self.assertNotIn("flock -n", body, "搶不到要等,不是略過")


class RoundsUseTheWaitingLock(unittest.TestCase):
    def test_every_daily_round_waits_for_the_lock(self):
        for name in ROUNDS + ("weekly-refdata.sh",):
            with self.subTest(script=name):
                lines = [ln.strip() for ln in _code(SCRIPTS / name).splitlines()]
                self.assertTrue(any(re.fullmatch(r"acquire_db_lock_wait \d+", ln) for ln in lines))
                self.assertNotIn("acquire_db_lock", lines, "不得再用會略過的 flock -n")

    def test_data_backfill_keeps_the_non_blocking_lock(self):
        lines = [ln.strip() for ln in _code(SCRIPTS / "data-backfill.sh").splitlines()]
        self.assertIn("acquire_db_lock", lines, "深歷史回補維持 flock -n(讓路一晚零損失)")

    def test_never_sleep_in_a_round_while_holding_the_lock(self):
        """輪詢只能透過 poll_until;腳本本身不准自己寫 sleep 迴圈。"""
        for name in ROUNDS:
            with self.subTest(script=name):
                self.assertNotRegex(_code(SCRIPTS / name), r"(?m)^\s*sleep\b")

    def test_branch_probe_runs_without_the_db_lock(self):
        code = _code(SCRIPTS / "daily-branches.sh")
        probe = code.index("probe-branch-day")
        line = code[code.rfind("\n", 0, probe) + 1:code.index("\n", probe)]
        self.assertIn("POLL_HOLD_DB_LOCK=0 poll_until", line)
        self.assertIn(" 2030 900 ", line, "17:30 起每 15 分鐘,最晚 20:30")
        self.assertLess(code.rfind("release_db_lock", 0, probe), probe)
        self.assertGreater(code.rfind("release_db_lock", 0, probe), -1,
                           "探測前要先放 DB 鎖")
        after = code[probe:code.index("radar import-branch-trades")]
        self.assertRegex(after, r"acquire_db_lock_wait \d+", "全量爬之前要重新拿鎖")
        self.assertIn('"${BRANCH_PROBE:-1}" != "0"', code, "BRANCH_PROBE=0 = 舊行為")

    def test_deadline_is_checked_before_the_lock_is_released(self):
        body = _fn("poll_until")
        self.assertLess(body.index("return 75"), body.index("release_db_lock"),
                        "截止回 75 必須在放鎖之前(回 75 時仍握著鎖)")

    def test_non_trading_day_is_decided_only_after_the_round_imported_quotes(self):
        """先匯入、再判斷休市:前幾輪壞掉時,這些輪自己的日K匯入是當天的補救;
        匯入之前就判斷會把整天靜默丟掉(2026-10-04 驗證者)。判斷成立要 warn。"""
        for name, imp in (("daily-branches.sh", 'run_step_or_fail "import-daily" radar import-daily --datasets quotes,insti'),
                          ("daily-margin.sh", "if radar import-daily --datasets quotes; then")):
            with self.subTest(script=name):
                code = _code(SCRIPTS / name)
                guard = code.index("if ! price_date_is_today")
                self.assertLess(code.index(imp), guard)
                self.assertEqual(code.count("price_date_is_today"), 1)
                self.assertIn("notify_warn", code[guard:guard + 300])
        nightly = _code(SCRIPTS / "safe-branch-stats.sh")
        guard = nightly.index("price_date_is_today")
        self.assertLess(nightly.index('BRANCH_ROW="$(branch_import_row'), guard,
                        "夜間作業要先看那一天有沒有任何分點匯入")
        line = nightly[nightly.rfind("\n", 0, guard):nightly.index("\n", guard)]
        self.assertIn('-z "$BRANCH_STATUS"', line, "有任何分點匯入紀錄就照舊全跑")
        self.assertIn("notify_warn", nightly[guard:guard + 400])

    def test_monday_refdata_still_runs_when_the_market_round_does_not_publish(self):
        code = _code(SCRIPTS / "daily-market.sh")
        self.assertIn("refdata_catchup() {", code)
        dl = code.index('"$quotes_rc" -eq 75')
        self.assertIn("refdata_catchup", code[dl:code.index("exit 0", dl)])
        nc = code.index('echo "publish skipped: no change"')
        self.assertIn("refdata_catchup", code[nc:code.index("exit 0", nc)])
        self.assertGreater(code.rindex("refdata_catchup"), code.index("deploy_data"))

    def test_branch_round_margin_needs_both_markets_and_margin_round_checks_both(self):
        code = _code(SCRIPTS / "daily-branches.sh")
        line = next(ln for ln in code.splitlines() if "--datasets margin" in ln)
        self.assertIn("--require twse:margin,tpex:margin", line)
        margin = _code(SCRIPTS / "daily-margin.sh")
        body = margin[margin.index("margin_is_today() {"):]
        body = body[:body.index("\n}")]
        self.assertIn("COUNT(DISTINCT source)", body)
        self.assertIn("-ge 2", body)
        self.assertNotIn("MAX(date) FROM daily_margins", body)

    def test_second_branch_round_skips_when_first_round_was_complete(self):
        code = _code(SCRIPTS / "daily-branches.sh")
        self.assertIn("publish skipped: first round complete", code)
        skip = code.index("publish skipped: first round complete")
        self.assertGreater(skip, code.index("radar import-futures-day"),
                           "第二輪收工前仍要做期貨當日的最後一次重試")
        self.assertLess(skip, code.index("radar compute-indicators"))
        self.assertIn("coverage_ratio=", code[code.index("printf '%s\\ncoverage_ratio="):])


def _bash_path(p: Path) -> str:
    if os.name == "nt":
        drive, rest = os.path.splitdrive(str(p))
        return "/mnt/" + drive[0].lower() + rest.replace("\\", "/")
    return str(p)


BASH = shutil.which("bash")


def _bash(script: str):
    # 腳本寫成檔案再交給 bash:Windows 的 bash.exe(WSL)會把 `-c` 字串裡的雙引號弄壞。
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "smoke.sh"
        path.write_text(script, encoding="utf-8", newline="\n")
        return subprocess.run([BASH, _bash_path(path)], capture_output=True, text=True,
                              timeout=120)


def _bash_ok() -> bool:
    if not BASH:
        return False
    try:
        r = _bash("command -v flock >/dev/null && echo ok")
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and r.stdout.strip() == "ok"


_PRELUDE = r'''
set -e
TMPD="$(mktemp -d)"
export RADAR_DB_LOCK_FILE="$TMPD/radar-db.lock"
source "{lib}"
trap - ERR
COUNT="$TMPD/count"
echo 0 > "$COUNT"
fake() {{  # 第 N 次之前回 75,之後回 0
  local n; n=$(( $(cat "$COUNT") + 1 )); echo "$n" > "$COUNT"
  [ "$n" -ge "$1" ] && return 0 || return 75
}}
sleep() {{  # 驗:睡的當下別的程序拿得到鎖 = 沒有握著鎖等
  if flock -n "$RADAR_DB_LOCK_FILE" true; then echo LOCK_FREE_DURING_SLEEP; else echo LOCK_HELD_DURING_SLEEP; fi
  command sleep 0
}}
'''


@unittest.skipUnless(_bash_ok(), "需要 bash + flock(Linux 或 WSL)")
class PollUntilSmoke(unittest.TestCase):
    def _run(self, body: str):
        script = _PRELUDE.format(lib=_bash_path(LIB)) + body
        r = _bash(script)
        return r.returncode, r.stdout, r.stderr

    def test_75_then_0_is_ready_on_the_second_attempt(self):
        rc, out, err = self._run(
            'if poll_until demo 2359 1 fake 2; then echo RC=0; else echo RC=$?; fi\n'
            'if flock -n "$RADAR_DB_LOCK_FILE" true; then echo HELD=no; else echo HELD=yes; fi\n')
        self.assertEqual(rc, 0, err)
        self.assertIn("RC=0", out)
        self.assertRegex(out, r"poll demo ready at=\d\d:\d\d attempts=2")
        self.assertIn("LOCK_FREE_DURING_SLEEP", out)
        self.assertNotIn("LOCK_HELD_DURING_SLEEP", out)
        self.assertIn("HELD=yes", out, "到齊時仍握著鎖,呼叫端接著 compute")

    def test_deadline_returns_75_still_holding_the_lock(self):
        """截止回 75 時仍握著鎖:呼叫端之後還會寫 DB(insti 的部分上線、週一題材補跑)。
        2026-10-04 驗證者抓到舊版在截止前先放鎖,之後的寫入全部沒有鎖。"""
        rc, out, err = self._run(
            'if poll_until demo 0000 1 fake 99; then echo RC=0; else echo RC=$?; fi\n'
            'if flock -n "$RADAR_DB_LOCK_FILE" true; then echo HELD=no; else echo HELD=yes; fi\n')
        self.assertEqual(rc, 0, err)
        self.assertIn("RC=75", out)
        self.assertRegex(out, r"poll demo deadline at=\d\d:\d\d attempts=1")
        self.assertIn("HELD=yes", out)

    def test_deadline_after_sleeping_relocks_before_returning(self):
        """睡過一次(放了鎖)之後才到截止:下一次嘗試前已重新拿鎖,所以回 75 時仍握著。"""
        rc, out, err = self._run(
            # $(taipei_date …) 跑在子 shell,計數要放檔案。
            'echo 0 > "$TMPD/clock"\n'
            'taipei_date() { if [ "$1" = "+%H%M" ]; then n=$(( $(cat "$TMPD/clock") + 1 )); '
            'echo "$n" > "$TMPD/clock"; [ "$n" -ge 2 ] && echo 2359 || echo 0000; '
            'else command date "$@"; fi; }\n'
            'if poll_until demo 2358 1 fake 99; then echo RC=0; else echo RC=$?; fi\n'
            'if flock -n "$RADAR_DB_LOCK_FILE" true; then echo HELD=no; else echo HELD=yes; fi\n')
        self.assertEqual(rc, 0, err)
        self.assertIn("RC=75", out)
        self.assertIn("LOCK_FREE_DURING_SLEEP", out)
        self.assertRegex(out, r"attempts=2")
        self.assertIn("HELD=yes", out)

    def test_other_codes_pass_through(self):
        rc, out, err = self._run(
            'boom() { return 3; }\n'
            'if poll_until demo 2359 1 boom; then echo RC=0; else echo RC=$?; fi\n')
        self.assertEqual(rc, 0, err)
        self.assertIn("RC=3", out)

    def test_radar_poll_0_is_one_attempt_treated_as_ready(self):
        rc, out, err = self._run(
            'export RADAR_POLL=0\n'
            'if poll_until demo 2359 1 fake 99; then echo RC=0; else echo RC=$?; fi\n'
            'echo CALLS=$(cat "$COUNT")\n')
        self.assertEqual(rc, 0, err)
        self.assertIn("RC=0", out)
        self.assertIn("CALLS=1", out)
        self.assertNotIn("LOCK_", out, "單次模式不睡")

    def test_probe_mode_never_touches_the_db_lock(self):
        rc, out, err = self._run(
            'exec 7>"$RADAR_DB_LOCK_FILE"; flock -n 7  # 別人握著 DB 鎖\n'
            'if POLL_HOLD_DB_LOCK=0 poll_until probe 2359 1 fake 2; then echo RC=0; else echo RC=$?; fi\n')
        self.assertEqual(rc, 0, err)
        self.assertIn("RC=0", out, "探測不需要 DB 鎖,別人握著也照跑")


if __name__ == "__main__":
    unittest.main()
