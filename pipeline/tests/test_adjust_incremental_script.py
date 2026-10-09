"""adjust-incremental.sh 的接線(2026-10-09):平日 13:15 還原因子日增量。

靜態解析腳本原始碼(同 test_build_cover_index_script.py 的作法),鎖住:
守衛順序與 adjust-backfill.sh 相同(安靜窗 / mid flag / 距下一個寫入者 > 30 分 /
`flock -n` 先於 pause)、EXIT trap 先於第一次呼叫 radar、三步驟順序、指標不帶
--days(全歷史)、不 export/deploy、成功通知只在有變動時發、crontab 那一行。
有可用 bash 時另外用真的 lib.sh 量 13:15 距下一個排程寫入者的分鐘數。
"""
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_cron_quiet_window import CRONTAB, parse_cron_jobs
from test_minutes_until_quiet_window import BASH_OK, minutes_until_writer

SCRIPTS = Path(__file__).resolve().parents[2] / "vps" / "scripts"
SCRIPT = SCRIPTS / "adjust-incremental.sh"
LIB = SCRIPTS / "lib.sh"


def _code_lines(text):
    """去掉純註解行(註解裡提到的指令不算)。"""
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


class AdjustIncrementalScriptTests(unittest.TestCase):
    raw = SCRIPT.read_text(encoding="utf-8")
    code = _code_lines(raw)

    def idx(self, needle):
        i = self.code.find(needle)
        self.assertNotEqual(i, -1, needle)
        return i

    def first_radar_call(self):
        m = re.search(r"\bradar(_timeout)?\s+(\d+\s+|\"\$\(secs_left\)\"\s+)?compute-", self.code)
        self.assertIsNotNone(m)
        return m.start()

    def test_sources_lib(self):
        self.assertIn('source "$(dirname "$0")/lib.sh"', self.code)

    def test_job_has_a_chinese_title(self):
        self.assertIn('adjust-incremental.sh) echo "還原因子日增量" ;;', LIB.read_text(encoding="utf-8"))

    def test_guards_run_before_the_lock_and_any_work(self):
        lock = self.idx("flock -n 9")
        for guard in ("if in_radar_quiet_window; then", 'if [ -f "$FLAG" ]; then',
                      "minutes_until_next_scheduled_writer)",
                      'if [ "$LEFT" -le "$MIN_LEFT_MIN" ]; then'):
            self.assertLess(self.idx(guard), lock, guard)
        self.assertIn('MIN_LEFT_MIN="${ADJUST_MIN_LEFT_MIN:-30}"', self.code)
        self.assertLess(lock, self.first_radar_call())

    def test_lock_is_non_blocking_and_taken_before_pausing_backfill(self):
        self.assertIn("exec 9>/tmp/radar-db.lock", self.code)
        self.assertNotIn("flock -w", self.code)
        self.assertNotIn("acquire_db_lock", self.code)
        self.assertLess(self.idx("flock -n 9"), self.idx("pause_bf_for_exclusive_writer"))

    def test_exit_trap_is_installed_before_pause_and_before_radar(self):
        trap = self.idx("trap 'adjust_incremental_cleanup' EXIT")
        self.assertLess(trap, self.idx("pause_bf_for_exclusive_writer"))
        self.assertLess(trap, self.first_radar_call())
        cleanup = self.code[self.idx("adjust_incremental_cleanup() {"):]
        cleanup = cleanup[:cleanup.index("\n}")]
        self.assertIn("resume_bf_paused_by_us", cleanup)

    def test_three_steps_in_order(self):
        select = self.idx("compute-adjustments --ex-dates-since \"$SINCE\" --print-ids")
        adjust = self.idx("compute-adjustments --ids \"$IDS\"")
        indicators = self.idx("compute-indicators --ids \"$IDS\"")
        self.assertLess(select, adjust)
        self.assertLess(adjust, indicators)
        self.assertIn('SINCE="${ADJUST_SINCE:-10}"', self.code)

    def test_indicators_are_full_history(self):
        line = next(ln for ln in self.code.splitlines() if "compute-indicators" in ln and "radar" in ln)
        self.assertNotIn("--days", line)
        self.assertNotIn("--all", line)

    def test_every_step_has_a_hard_time_limit(self):
        for ln in self.code.splitlines():
            if re.search(r"\bcompute-(adjustments|indicators)\b", ln) and "radar" in ln:
                self.assertIn("radar_timeout", ln, ln)

    def test_no_export_or_deploy(self):
        for word in ("export-json", "deploy_data", "build_bull_board", "sync_code"):
            self.assertNotIn(word, self.code, word)

    def test_success_notification_only_when_factors_changed(self):
        ok = self.idx("notify_ok")
        gate = self.code.rfind("if [", 0, ok)
        self.assertIn('[ "${CHANGED:-0}" -gt 0 ]', self.code[gate:ok])

    def test_failures_notify_high(self):
        for label in ("compute-adjustments FAILED", "compute-indicators FAILED", "select-ex-dates FAILED"):
            block = self.code[self.idx(label):]
            block = block[:block.index("exit")]
            self.assertIn('high "失敗"', block, label)

    def test_counts_are_logged(self):
        self.assertRegex(self.code, r"adjust-incremental summary: selected=\$\{SELECTED\} "
                                    r"adjusted=.* changed=.* failed=.* elapsed=")
        # 解析的是 CLI 實際印出的那兩行格式(test_adjust_incremental.py 鎖 CLI 端)
        self.assertIn("s/^changed: \\([0-9]*\\) stocks, \\([0-9]*\\) rows$/", self.code)
        self.assertIn("s/^adjustments: \\([0-9]*\\) stocks.*/", self.code)


class AdjustIncrementalCronTests(unittest.TestCase):
    def test_crontab_slot_is_weekdays_13_15(self):
        jobs = [j for j in parse_cron_jobs(CRONTAB.read_text(encoding="utf-8"))
                if j["script"] == "adjust-incremental.sh"]
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual((job["hours"], job["minutes"], job["dows"]), ([13], [15], [1, 2, 3, 4, 5]))
        self.assertIn(">> /home/huang/radar-cron.log 2>&1", job["raw"])

    def test_adjust_backfill_is_still_not_scheduled(self):
        scripts = {j["script"] for j in parse_cron_jobs(CRONTAB.read_text(encoding="utf-8"))}
        self.assertNotIn("adjust-backfill.sh", scripts)


def _bash_path(p: Path) -> str:
    s = str(p)
    if sys.platform == "win32" and re.match(r"^[A-Za-z]:\\", s):
        return "/mnt/" + s[0].lower() + s[2:].replace("\\", "/")
    return s


def _harness_ok() -> bool:
    if shutil.which("bash") is None:
        return False
    try:
        r = subprocess.run(["bash", "-c", "command -v flock && command -v timeout"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


# 假 docker / curl / date:docker 依 radar 子指令回固定輸出並記錄呼叫;curl 記錄通知;
# date 把「台北現在」釘在週一 13:15(其他用法交給真的 date)。
STUB_DOCKER = r"""#!/usr/bin/env bash
if [ "$1" = "inspect" ]; then exit 1; fi
if [ "$1" = "pause" ] || [ "$1" = "unpause" ]; then exit 0; fi
args="$*"
sub="${args#*python -m radar }"
echo "$sub" >> "$STUB_DIR/calls"
case "$sub" in
  *--print-ids*) printf '%s\n' "$STUB_IDS" ;;
  compute-adjustments*)
    echo "adjust 2379 ok: 2 events, 120 price rows"
    echo "adjustments: 2 stocks, 2 events, 240 rows updated, ${STUB_FAILED:-0} failed"
    echo "changed: ${STUB_CHANGED:-1} stocks, 80 rows"
    echo "changed_ids=2379"
    exit "${STUB_ADJ_RC:-0}" ;;
  compute-indicators*) echo "indicators: 2 computed, 0 already fresh, 240 rows written" ;;
  *) echo "unexpected: $sub" >&2; exit 9 ;;
esac
"""
STUB_CURL = r"""#!/usr/bin/env bash
title=""; body=""
while [ $# -gt 0 ]; do
  case "$1" in
    -H) case "$2" in Title:*) title="${2#Title: }" ;; esac; shift 2 ;;
    -d) body="$2"; shift 2 ;;
    *) shift ;;
  esac
done
echo "${title} | ${body}" >> "$STUB_DIR/notify"
"""
STUB_DATE = r"""#!/usr/bin/env bash
case "$*" in
  *+%u*) echo 1 ;;
  *+%H%M*) echo 1315 ;;
  *+%d*) echo 05 ;;
  *) exec /bin/date "$@" ;;
esac
"""


@unittest.skipUnless(_harness_ok(), "需要 bash + flock + timeout(Windows 上是 WSL)")
class AdjustIncrementalHarness(unittest.TestCase):
    """真的跑 adjust-incremental.sh(真的 lib.sh),只把 docker/curl/date 換成 stub。"""

    def run_script(self, ids="2379,1268", **env):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            stub = tmp / "bin"
            stub.mkdir()
            for name, body in (("docker", STUB_DOCKER), ("curl", STUB_CURL), ("date", STUB_DATE)):
                (stub / name).write_text(body, encoding="utf-8", newline="\n")
            lock = "/tmp/radar-db.lock"
            env_lines = "".join(f'export {k}="{v}"\n' for k, v in env.items())
            wrapper = tmp / "run.sh"
            wrapper.write_text(
                "set -u\n"
                f'export STUB_DIR="{_bash_path(tmp)}"\n'
                f'export STUB_IDS="{ids}"\n'
                'export NTFY="test-topic"\n'
                'export MID_PUBLISH_FLAG="$STUB_DIR/no-such-flag"\n'
                'export TMPDIR="$STUB_DIR"\n'
                f"{env_lines}"
                f'chmod +x "$STUB_DIR/bin/"*\n'
                'export PATH="$STUB_DIR/bin:$PATH"\n'
                f': > "$STUB_DIR/calls"; : > "$STUB_DIR/notify"\n'
                f'bash "{_bash_path(SCRIPT)}"\n',
                encoding="utf-8", newline="\n")
            r = subprocess.run(["bash", _bash_path(wrapper)], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=120)
            calls = (tmp / "calls").read_text(encoding="utf-8").splitlines()
            notes = (tmp / "notify").read_text(encoding="utf-8").splitlines()
            leftovers = [p.name for p in tmp.iterdir() if p.name.startswith("adjust-incremental.")]
        self.assertNotIn(lock, r.stderr)
        return r, calls, notes, leftovers

    def test_happy_path_runs_three_steps_and_notifies_once(self):
        r, calls, notes, leftovers = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(calls, [
            "compute-adjustments --ex-dates-since 10 --print-ids",
            "compute-adjustments --ids 2379,1268",
            "compute-indicators --ids 2379,1268",
        ])
        self.assertIn("adjust-incremental summary: selected=2 adjusted=2 changed=1 changed_rows=80 "
                      "failed=0 quota_hit=0 indicators=2", r.stdout)
        self.assertEqual(len(notes), 1, notes)
        self.assertIn("還原因子日增量 · 成功", notes[0])
        self.assertEqual(leftovers, [], "暫存 log 要在 EXIT 清掉")

    def test_catch_up_since_a_date(self):
        r, calls, _, _ = self.run_script(ADJUST_SINCE="2026-09-04")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(calls[0], "compute-adjustments --ex-dates-since 2026-09-04 --print-ids")

    def test_nothing_changed_is_silent(self):
        r, calls, notes, _ = self.run_script(STUB_CHANGED="0")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(calls), 3)
        self.assertEqual(notes, [])

    def test_empty_selection_stops_after_the_selector(self):
        r, calls, notes, _ = self.run_script(ids="")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(calls, ["compute-adjustments --ex-dates-since 10 --print-ids"])
        self.assertIn("selected=0", r.stdout)
        self.assertEqual(notes, [])

    def test_adjustment_failure_notifies_high_and_skips_indicators(self):
        r, calls, notes, _ = self.run_script(STUB_ADJ_RC="3")
        self.assertEqual(r.returncode, 3)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(notes), 1, notes)
        self.assertIn("失敗", notes[0])

    def test_partial_failures_warn(self):
        r, _, notes, _ = self.run_script(STUB_FAILED="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(any("注意" in n and "1 檔失敗" in n for n in notes), notes)


@unittest.skipUnless(BASH_OK, "no usable bash (drives the real lib.sh; on Windows it needs WSL)")
class AdjustIncrementalBudgetTests(unittest.TestCase):
    def test_13_15_has_more_than_30_minutes_before_the_next_writer_every_weekday(self):
        for dow in range(1, 6):
            for dom in (1, 15, 16):
                with self.subTest(dow=dow, dom=dom):
                    self.assertGreater(minutes_until_writer(dow, 1315, dom), 30)


if __name__ == "__main__":
    unittest.main()
