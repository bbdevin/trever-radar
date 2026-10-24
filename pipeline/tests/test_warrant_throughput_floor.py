"""warrant-backfill.sh 的吞吐地板(vps/scripts/warrant-throughput.sh):已到期權證的空
不再讓地板誤觸(2026-10-22 12:46 誤報,docs/30 §5.3),未到期部分真的塌陷仍要觸發。"""
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FUNC = REPO_ROOT / "vps" / "scripts" / "warrant-throughput.sh"
SCRIPT = REPO_ROOT / "vps" / "scripts" / "warrant-backfill.sh"


def _bash_path(p: Path) -> str:
    s = str(p)
    if sys.platform == "win32" and re.match(r"^[A-Za-z]:\\", s):
        return "/mnt/" + s[0].lower() + s[2:].replace("\\", "/")
    return s


def _bash_ok() -> bool:
    if shutil.which("bash") is None:
        return False
    try:
        r = subprocess.run(["bash", "-c", "command -v awk"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


@unittest.skipUnless(_bash_ok(), "需要 bash + awk(Windows 上是 WSL)")
class ThroughputVerdictHarness(unittest.TestCase):
    def verdict(self, rows, elapsed, empty_expired, requests=0, sleep=1.0, min_elapsed=600,
                min_rps=1.5):
        cmd = (f'set -euo pipefail; source "{_bash_path(FUNC)}"; '
               f"warrant_throughput_verdict {rows} {elapsed} {empty_expired} {requests} "
               f"{sleep} {min_elapsed} {min_rps}")
        r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        word, rps, live, cost = r.stdout.split()
        return word, float(rps), int(live)

    def test_incident_chunk_no_longer_trips_once_expired_empties_are_excluded(self):
        # 10-22 那塊的形狀,換成兩站確認後的時間:7,964 檔有列 ~1.05 s,
        # 5,770 個空(probe:幾乎全是已到期)各 2 次請求。列數 = 1.24 × 14,403。
        elapsed = int(7964 * 1.05 + 5770 * 2 * 1.05)
        rows = int(1.24 * 14403)
        requests = 7964 + 5770 * 2
        self.assertEqual(self.verdict(rows, elapsed, 0)[0], "collapse",
                         "不扣的話(舊判決)一定誤觸")
        word, rps, live = self.verdict(rows, elapsed, 5711, requests)
        self.assertEqual(word, "ok")
        self.assertGreater(rps, 1.5)

    # 2026-10-23 正式那塊(docs/30 §5.3):`clean-stop: rc=75, 14402s, fetched=2407,
    # empty=5805`,empty_expired=5458;舊判決印 `collapse 1.48 rows/s over 3486s`,
    # 反推列數 ∈ [1.475, 1.485) × 3486 → 取下界 5142。requests 當時沒印,取它的下界
    # fetched + 2 × empty = 14017(recovered/failed 只會再多幾次)。
    OCT23 = dict(rows=5142, elapsed=14402, empty_expired=5458)
    OCT23_REQUESTS = 2407 + 2 * 5805

    def test_oct23_chunk_reproduces_the_false_alarm_without_requests(self):
        """沒有 requests= 時退回「每次請求 = SLEEP」:就是 10-23 那則誤報,數字逐字重現。"""
        word, rps, live = self.verdict(**self.OCT23)
        self.assertEqual((word, rps, live), ("collapse", 1.48, 3486))

    def test_oct23_chunk_is_not_a_collapse_with_measured_request_cost(self):
        word, rps, live = self.verdict(**self.OCT23, requests=self.OCT23_REQUESTS)
        self.assertIn(word, {"ok", "skip"})
        self.assertEqual(word, "ok")
        self.assertGreater(rps, 1.5)
        # 剩下的 = 未到期部分的請求(2407 有列 + 347 個未到期空 × 2)× 實測 1.027 s
        self.assertAlmostEqual(live, (self.OCT23_REQUESTS - 2 * 5458) * 14402 / self.OCT23_REQUESTS,
                               delta=1)

    def test_real_collapse_on_unexpired_warrants_still_trips(self):
        # 未到期的空(中毒)不扣:同樣時間只寫了很少列 → 照樣觸發。
        self.assertEqual(self.verdict(rows=2000, elapsed=14000, empty_expired=50)[0], "collapse")
        self.assertEqual(self.verdict(rows=2000, elapsed=14000, empty_expired=50,
                                      requests=13500)[0], "collapse")

    def test_oct23_shape_with_poisoned_unexpired_warrants_still_trips(self):
        """同 10-23 的總量,但已到期的空只有 1,000 個、其餘 4,805 個空是未到期的(中毒)
        → 那些請求的時間全部留在分母,照樣觸發。"""
        word, rps, _ = self.verdict(rows=5142, elapsed=14402, empty_expired=1000,
                                    requests=self.OCT23_REQUESTS)
        self.assertEqual(word, "collapse")
        self.assertLess(rps, 1.5)

    def test_chunk_that_was_almost_all_expired_empties_is_skipped(self):
        word, _, live = self.verdict(rows=100, elapsed=8000, empty_expired=3900)
        self.assertEqual(word, "skip")
        self.assertLessEqual(live, 600)
        word, _, live = self.verdict(rows=100, elapsed=8000, empty_expired=3900, requests=7900)
        self.assertEqual(word, "skip")

    def test_unparsed_empty_expired_falls_back_to_the_old_verdict(self):
        self.assertEqual(self.verdict(rows=1000, elapsed=7200, empty_expired=0)[0], "collapse")
        self.assertEqual(self.verdict(rows=1000, elapsed=7200, empty_expired=0,
                                      requests=7000)[0], "collapse")
        self.assertEqual(self.verdict(rows=50000, elapsed=7200, empty_expired=0)[0], "ok")

    def test_inconsistent_requests_fall_back_to_the_sleep_lower_bound(self):
        """requests < 2 × empty_expired(欄位對不上)不可拿來扣超過 elapsed → 用 SLEEP 下界。"""
        self.assertEqual(self.verdict(**self.OCT23, requests=100),
                         self.verdict(**self.OCT23))

    def test_short_chunk_is_skipped_as_before(self):
        self.assertEqual(self.verdict(rows=0, elapsed=500, empty_expired=0)[0], "skip")

    def test_script_parses(self):
        r = subprocess.run(["bash", "-n", _bash_path(SCRIPT)], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)


class ThroughputWiringTests(unittest.TestCase):
    def test_script_sources_the_verdict_and_parses_empty_expired(self):
        code = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('source "$(dirname "$0")/warrant-throughput.sh"', code)
        self.assertIn("grep -oE 'empty_expired=[0-9]+'", code)
        self.assertIn('EMPTY_EXPIRED="${EMPTY_EXPIRED:-0}"', code, "解析不到 = 0 = 舊判決")
        self.assertIn("grep -oE 'requests=[0-9]+'", code)
        self.assertIn('REQUESTS="${REQUESTS:-0}"', code, "解析不到 = 0 = SLEEP 下界")
        self.assertIn('"$EMPTY_EXPIRED" "$REQUESTS" "$SLEEP"', code)
        self.assertRegex(code, r'if \[ "\$TP_VERDICT" = "collapse" \]; then\s+echo[^\n]*\n\s+: > "\$PAUSE_FILE"')
        self.assertIn("probe_backfill_empties.py report", code, "告警要指向唯讀報表")

    def test_cli_summary_line_still_matches_the_shell_greps(self):
        """CLI 摘要行改名,shell 會靜默拿到 0;這裡把兩邊釘在一起。"""
        src = (REPO_ROOT / "pipeline" / "radar" / "importer.py").read_text(encoding="utf-8")
        self.assertIn('empty_expired={empty_expired}', src)
        self.assertIn("requests={tally['requests']}", src)
        line = ("backfill-warrant-branches: fetched=12, complete_dates=1/2, empty=7, "
                "empty_expired=5, skipped_expired=3, recovered=0, failed=0, requests=22, "
                "stopped=None")
        self.assertEqual(re.findall(r"empty=[0-9]+", line), ["empty=7"])
        self.assertEqual(re.findall(r"empty_expired=[0-9]+", line), ["empty_expired=5"])
        self.assertEqual(re.findall(r"requests=[0-9]+", line), ["requests=22"])


if __name__ == "__main__":
    unittest.main()
