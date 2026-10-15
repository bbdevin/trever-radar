# -*- coding: utf-8 -*-
"""morning-index.sh(docs/49 §12.6.5):早上台指期夜盤上線的守衛與步驟。

兩層(同 test_tpex_http_resilience.py / test_adjust_incremental_script.py 的手法):
* 原始碼:source lib、宣告失敗後果、等鎖(短)、sync_code、輪詢走 poll_until、只跑窄 export(不跑
  export-json / bull board)、截止 08:40 早於 08:50 盤中 worker 與 09:00 mid-backfill-publish。
* bash 實跑(本機有 bash 才跑):把腳本複製到暫存目錄、旁邊放假 lib.sh(真的 set_round_consequence /
  run_step / poll_until 原文 + 假 radar/鎖/通知/時間),驗各條路徑的步驟與通知。
"""
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

SCRIPTS = Path(__file__).resolve().parents[2] / "vps" / "scripts"
SCRIPT = SCRIPTS / "morning-index.sh"
LIB = SCRIPTS / "lib.sh"


def _code(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


class MorningIndexSource(unittest.TestCase):
    code = _code(SCRIPT.read_text(encoding="utf-8"))

    def idx(self, needle):
        i = self.code.find(needle)
        self.assertNotEqual(i, -1, needle)
        return i

    def test_conventions(self):
        self.assertIn('source "$(dirname "$0")/lib.sh"', self.code)
        self.assertIn('morning-index.sh) echo "早上夜盤" ;;', LIB.read_text(encoding="utf-8"))
        self.assertLess(self.idx("set_round_consequence"), self.idx("acquire_db_lock_wait"))
        self.assertRegex(self.code, r'acquire_db_lock_wait "\$\{MORNING_LOCK_WAIT_SECS:-300\}"')
        self.assertLess(self.idx("acquire_db_lock_wait"), self.idx("sync_code"))
        self.assertLess(self.idx("sync_code"), self.idx('poll_until "tx-night"'))

    def test_weekend_guard_runs_before_the_lock(self):
        self.assertLess(self.idx('if [ "$(taipei_date +%u)" -gt 5 ]; then'), self.idx("acquire_db_lock_wait"))

    def test_narrow_export_only(self):
        self.assertNotIn("export-json", self.code)
        self.assertNotIn("build_bull_board", self.code)
        self.assertLess(self.idx("radar import-index --date"), self.idx("radar export-index"))
        self.assertLess(self.idx("radar export-index"), self.idx("deploy_data"))

    def test_deadline_is_before_the_0850_worker_and_0900_mid_publish(self):
        m = re.search(r'MORNING_DEADLINE="\$\{MORNING_DEADLINE:-(\d{4})\}"', self.code)
        self.assertIsNotNone(m)
        self.assertLessEqual(int(m.group(1)), 840)
        self.assertNotRegex(self.code, r"(?m)^\s*sleep\b", "輪詢只透過 poll_until(睡前放鎖)")

    def test_does_not_consult_the_scheduled_writer_overlay(self):
        # 2026-10-15:08:00–08:45 進了 lib.sh 的 WEEKDAY_SHORT_JOBS(讓長回補讓路)。
        # morning-index 自己不問這些守衛,所以不會因自己的槽而略過自己。
        for guard in ("minutes_until_next_scheduled_writer", "minutes_until_quiet_window",
                      "in_radar_quiet_window", "weekday_short_job_at"):
            self.assertNotIn(guard, self.code, guard)

    def test_its_slot_is_in_the_weekday_short_jobs_overlay(self):
        m = re.search(r'^WEEKDAY_SHORT_JOBS="\$\{WEEKDAY_SHORT_JOBS:-([0-9 -]*)\}"',
                      LIB.read_text(encoding="utf-8"), re.M)
        self.assertIsNotNone(m)
        slot = next((r for r in m.group(1).split() if r.startswith("0800-")), None)
        self.assertIsNotNone(slot, "08:00 morning-index must be reserved in WEEKDAY_SHORT_JOBS")
        deadline = int(re.search(r'MORNING_DEADLINE="\$\{MORNING_DEADLINE:-(\d{4})\}"', self.code).group(1))
        self.assertGreater(int(slot.split("-")[1]), deadline, "保留段要涵蓋最後一次輪詢之後的匯出/上線")

    def test_presence_is_logged_every_attempt(self):
        self.assertIn('echo "morning-index tx_night date=${TODAY} present=yes close=${close} at=', self.code)
        self.assertIn('echo "morning-index tx_night date=${TODAY} present=no at=', self.code)


def _real(name: str) -> str:
    m = re.search(rf"^{name}\(\) \{{.*?^\}}", LIB.read_text(encoding="utf-8"), re.S | re.M)
    assert m, name
    return m.group(0)


FAKE_LIB = r"""#!/usr/bin/env bash
record() { printf '%s\n' "$1" >> "$EV"; }
set -euo pipefail
trap 'record "err:$?:$BASH_COMMAND"' ERR
LOCKED=0
acquire_db_lock_wait() { LOCKED=1; record "lock-wait:$1"; }
db_lock_take() { LOCKED=1; }
release_db_lock() { LOCKED=0; record release; }
sleep() { record "sleep:$1:locked=$LOCKED"; }
sync_code() { record sync; }
notify() { record "notify:$2:$1"; }
notify_warn() { record "warn:$1"; }
notify_ok() { record "ok:$1"; }
deploy_data() { record "deploy:locked=$LOCKED"; return "${DEPLOY_RC:-0}"; }
CLOCK="$EVDIR/clock"; echo 0 > "$CLOCK"
taipei_date() {
  case "$*" in
    *+%u*) echo "${DOW:-2}" ;;
    *+%F*) echo 2026-10-13 ;;
    *+%Y%m%d*) echo 20261013 ;;
    *+%H%M*) n=$(( $(cat "$CLOCK") + 1 )); echo "$n" > "$CLOCK"; [ "$n" -gt "${DEADLINE_AFTER:-99}" ] && echo 0845 || echo 0800 ;;
    *+%H:%M*) echo 08:00 ;;
    *) echo 2026-10-13T08:00:00+08:00 ;;
  esac
}
IMPORTS="$EVDIR/imports"; echo 0 > "$IMPORTS"
radar() {
  record "radar:$*:locked=$LOCKED"
  case "$1" in
    import-index) echo $(( $(cat "$IMPORTS") + 1 )) > "$IMPORTS"; return "${IMPORT_RC:-75}" ;;
    export-index) return "${EXPORT_RC:-0}" ;;
  esac
  return 0
}
radar_ro_sql() {
  if [ "$(cat "$IMPORTS")" -ge "${NIGHT_AT:-1}" ]; then echo 48946.0; else echo ""; fi
}
SCRIPT_NAME=morning-index.sh
ROUND_FAIL_CONSEQUENCE=""
POLL_LOCK_WAIT_SECS=3600
"""


@unittest.skipUnless(shutil.which("bash"), "需要 bash")
class MorningIndexHarness(unittest.TestCase):
    def run_script(self, **env):
        with TemporaryDirectory() as tmp:
            d = Path(tmp) / "scripts"
            d.mkdir()
            shutil.copy2(SCRIPT, d / "morning-index.sh")
            (d / "lib.sh").write_text(
                FAKE_LIB + "\n".join(_real(n) for n in ("set_round_consequence", "run_step", "poll_until")) + "\n",
                encoding="utf-8", newline="\n")
            envs = " ".join(f"{k}={v}" for k, v in env.items())
            r = subprocess.run(["bash", "-c", f"EV=../events.log EVDIR=.. {envs} exec bash morning-index.sh"],
                               cwd=d, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=30, check=False)
            ev_path = Path(tmp) / "events.log"
            ev = ev_path.read_text(encoding="utf-8").splitlines() if ev_path.exists() else []
        return r, ev

    def test_night_present_on_first_attempt(self):
        r, ev = self.run_script(NIGHT_AT=1)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(ev, [
            "lock-wait:300", "sync",
            "radar:import-index --date 20261013:locked=1",
            "radar:export-index:locked=1",
            "deploy:locked=1",
            "ok:台指期夜盤（2026-10-13 05:00 收）已上線：48946.0",
        ])
        self.assertIn("morning-index tx_night date=2026-10-13 present=yes close=48946.0 at=08:00", r.stdout)
        self.assertRegex(r.stdout, r"poll tx-night ready at=08:00 attempts=1")

    def test_import_index_0_also_counts(self):
        r, ev = self.run_script(NIGHT_AT=1, IMPORT_RC=0)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("radar:export-index:locked=1", ev)

    def test_not_yet_then_present_releases_the_lock_while_waiting(self):
        r, ev = self.run_script(NIGHT_AT=2)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual([e for e in ev if e.startswith(("radar:", "release", "sleep", "deploy"))], [
            "radar:import-index --date 20261013:locked=1", "release", "sleep:600:locked=0",
            "radar:import-index --date 20261013:locked=1",
            "radar:export-index:locked=1", "deploy:locked=1",
        ])
        self.assertIn("present=no", r.stdout)
        self.assertIn("present=yes", r.stdout)

    def test_deadline_without_night_is_silent_and_publishes_nothing(self):
        r, ev = self.run_script(NIGHT_AT=99, DEADLINE_AFTER=2)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse([e for e in ev if e.startswith(("radar:export", "deploy", "ok:", "warn:", "notify:", "err:"))], ev)
        self.assertIn("morning-index: no tx_night for 2026-10-13 by 0840", r.stdout)
        self.assertRegex(r.stdout, r"poll tx-night deadline at=")

    def test_import_error_warns_and_stops(self):
        r, ev = self.run_script(IMPORT_RC=1)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse([e for e in ev if e.startswith(("radar:export", "deploy", "ok:", "notify:"))], ev)
        self.assertEqual(len([e for e in ev if e.startswith("warn:")]), 1, ev)
        self.assertIn("碼 1", next(e for e in ev if e.startswith("warn:")))

    def test_export_failure_warns_and_does_not_deploy(self):
        r, ev = self.run_script(NIGHT_AT=1, EXPORT_RC=2)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse([e for e in ev if e.startswith(("deploy", "ok:", "notify:"))], ev)
        self.assertTrue(any(e.startswith("warn:夜盤早上匯出失敗（碼 2）") for e in ev), ev)

    def test_deploy_failure_warns(self):
        r, ev = self.run_script(NIGHT_AT=1, DEPLOY_RC=9)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse([e for e in ev if e.startswith(("ok:", "notify:"))], ev)
        self.assertTrue(any(e.startswith("warn:夜盤早上上線失敗（碼 9）") for e in ev), ev)

    def test_weekend_does_nothing(self):
        r, ev = self.run_script(DOW=6)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(ev, [])
        self.assertIn("weekend", r.stdout)


if __name__ == "__main__":
    unittest.main()
