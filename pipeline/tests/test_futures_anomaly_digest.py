# -*- coding: utf-8 -*-
"""每日期貨量異常推播(docs/38 §7.19):CLI、措辭、與 16:10／17:40／22:00 的接線。

接線的部分照 test_futures_day_wiring.py 的手法直接解析腳本原始碼,另外在有 bash 的
環境用假的 docker / curl 實跑一次 lib.sh 的 ``futures_digest``,鎖住「永不失敗」與
「同一個期貨行情日只送一次」。
"""
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from radar.cli import main
from radar.export.futures_digest import (
    NEXT_DAY_EVIDENCE,
    SITE_URL,
    build_digest,
    contract_label,
    contract_labels,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "vps" / "scripts"
LIB = SCRIPTS_DIR / "lib.sh"
EVIDENCE = REPO_ROOT / "docs" / "evidence" / "next-day-futures-signal-battery-20261002.json"
FULL_LINE_COMMENT = re.compile(r"^\s*#")
TRAILING_COMMENT = re.compile(r"(?<=\s)#.*$")

META = {"as_of": "2026-10-02", "window_days": 60}


def _entry(stock_id, code, multiplier, spot_new_high):
    return {"stock_id": stock_id, "code": code, "multiplier": multiplier,
            "anomaly": {"today": 500, "window_max": 100, "window_median": 100,
                        "window_days": 60},
            "reasons": [], "risks": [], "spot_new_high": spot_new_high}


class _Out(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name)
        (self.out / "stocks_index.json").write_text(json.dumps(
            [["2303", "聯電", "twse", "stock", ""], ["1565", "精華", "tpex", "stock", ""]],
            ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, radar):
        (self.out / "radar.json").write_text(json.dumps(radar, ensure_ascii=False),
                                             encoding="utf-8")

    def cli(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["futures-anomaly-digest", "--out", str(self.out)])
        return buf.getvalue()


class DigestContentTests(_Out):
    def test_silent_when_the_list_is_absent(self):
        self.write({"data_date": "2026-10-02"})
        self.assertIsNone(build_digest(self.out))
        self.assertEqual(self.cli(), "")

    def test_silent_when_the_list_is_empty(self):
        self.write({"futures_volume_anomalies": [], "futures_volume_anomalies_meta": META})
        self.assertIsNone(build_digest(self.out))
        self.assertEqual(self.cli(), "")

    def test_the_message_verbatim(self):
        self.write({
            "futures_volume_anomalies": [
                _entry("2303", "CCF", 2000, False),
                _entry("1565", "OMF", 100, False),
                _entry("1565", "MYF", 2000, True),
                _entry("2330", "CDF", 2000, None),
            ],
            "futures_volume_anomalies_meta": META,
        })
        title, body = build_digest(self.out)
        self.assertEqual(title, "期貨量異常 · 2026-10-02")
        self.assertEqual(body, (
            "2026-10-02 有 4 個契約一般時段成交量創 60 日新高，其中 2 個現貨當日尚未同步創高："
            "聯電 2303（個股期貨）、精華 1565（小型個股期貨）。"
            "回測只證明現貨量在 5 日內跟上的次數比平常多，不是漲跌"
            "（漲 ≥3% 81 次／跌 ≥3% 112 次，共 551 次）。\n"
            "https://radar.techtrever.com/?tab=futures"
        ))
        self.assertEqual(self.cli(), f"{title}\n{body}\n")

    def test_no_lagging_contract_drops_the_list(self):
        self.write({"futures_volume_anomalies": [_entry("2303", "CCF", 2000, True)],
                    "futures_volume_anomalies_meta": META})
        _, body = build_digest(self.out)
        self.assertIn("其中 0 個現貨當日尚未同步創高。回測", body)

    def test_a_missing_name_shows_only_the_id(self):
        self.write({"futures_volume_anomalies": [_entry("2330", "CDF", 2000, False)],
                    "futures_volume_anomalies_meta": META})
        _, body = build_digest(self.out)
        self.assertIn("：2330（個股期貨）。", body)

    def test_the_raw_contract_code_never_appears(self):
        self.write({"futures_volume_anomalies": [_entry("2303", "CCF", 2000, False)],
                    "futures_volume_anomalies_meta": META})
        title, body = build_digest(self.out)
        self.assertNotIn("CCF", title + body)

    def test_the_window_comes_from_the_meta(self):
        self.write({"futures_volume_anomalies": [_entry("2303", "CCF", 2000, False)],
                    "futures_volume_anomalies_meta": {"as_of": "2026-10-02", "window_days": 7}})
        self.assertIn("創 7 日新高", build_digest(self.out)[1])

    def test_no_date_no_message(self):
        self.write({"futures_volume_anomalies": [_entry("2303", "CCF", 2000, False)],
                    "futures_volume_anomalies_meta": {"window_days": 60}})
        self.assertIsNone(build_digest(self.out))

    def test_the_site_url_is_the_production_domain(self):
        self.assertEqual(SITE_URL, "https://radar.techtrever.com/?tab=futures")
        self.assertIn("https://radar.techtrever.com", (REPO_ROOT / "README.md").read_text(
            encoding="utf-8"))

    def test_the_evidence_numbers_match_the_committed_run(self):
        signal = json.loads(EVIDENCE.read_text(encoding="utf-8"))["companion"]["signal"]
        self.assertEqual(NEXT_DAY_EVIDENCE,
                         {"events": signal["n"], "up3": signal["hits"],
                          "down3": signal["drops"]})


BANNED_COPY = ("大漲", "噴", "極品", "機率", "勝率", "看多", "看空", "買進")


class DigestWordingGateTests(_Out):
    """推播的措辭閘門:沒有喊單詞;% 只出現在鎖住的回測句裡的「≥3%」。推播不帶價格 %。"""

    def _message(self):
        self.write({"futures_volume_anomalies": [_entry("2303", "CCF", 2000, False),
                                                 _entry("1565", "OMF", 100, True)],
                    "futures_volume_anomalies_meta": META})
        return "\n".join(build_digest(self.out))

    def test_no_banned_word(self):
        message = self._message()
        for bad in BANNED_COPY:
            self.assertNotIn(bad, message)

    def test_percent_only_inside_the_backtest_sentence(self):
        message = self._message()
        self.assertEqual(message.count("≥3%"), 2)
        self.assertNotIn("%", message.replace("≥3%", ""))

    def test_the_module_literals_carry_no_banned_word(self):
        import ast
        src = (REPO_ROOT / "pipeline" / "radar" / "export" / "futures_digest.py").read_text(
            encoding="utf-8")
        literals = [n.value for n in ast.walk(ast.parse(src))
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        self.assertTrue(literals)
        for literal in literals:
            for bad in BANNED_COPY:
                self.assertNotIn(bad, literal)


class ContractLabelTests(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(contract_label(2000, "2303"), "個股期貨")
        self.assertEqual(contract_label(100, "1565"), "小型個股期貨")
        self.assertEqual(contract_label(10000, "0050"), "指數基金期貨")
        self.assertEqual(contract_label(1000, "2303"), "期貨（每口 1,000 股）")
        self.assertEqual(contract_label(None, "2303"), "期貨")
        self.assertNotIn("ETF", contract_label(10000, "0050"))

    def test_two_contracts_of_one_stock_never_share_a_name(self):
        labels = contract_labels([
            {"stock_id": "0050", "code": "NYF", "multiplier": 10000},
            {"stock_id": "0050", "code": "NZF", "multiplier": 1000},
            {"stock_id": "2303", "code": "AAF"},
            {"stock_id": "2303", "code": "BBF"},
            {"stock_id": "1565", "code": "MYF", "multiplier": 2000},
            {"stock_id": "1565", "code": "OMF", "multiplier": 100},
        ])
        self.assertEqual(labels[("0050", "NYF")], "指數基金期貨（每口 10,000 股）")
        self.assertEqual(labels[("0050", "NZF")], "指數基金期貨（每口 1,000 股）")
        self.assertEqual(labels[("2303", "AAF")], "期貨（第 1 個契約）")
        self.assertEqual(labels[("2303", "BBF")], "期貨（第 2 個契約）")
        self.assertEqual(labels[("1565", "MYF")], "個股期貨")
        self.assertEqual(labels[("1565", "OMF")], "小型個股期貨")


# ── 接線(腳本原始碼) ────────────────────────────────────────────────────────

def _code_lines(path: Path) -> list[str]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        out.append("" if FULL_LINE_COMMENT.match(line) else TRAILING_COMMENT.sub("", line))
    return out


def _digest_body() -> str:
    lib = "\n".join(_code_lines(LIB))
    m = re.search(r"^futures_digest\(\)\s*\{(.*?)\n\}", lib, re.S | re.M)
    assert m, "lib.sh 裡找不到 futures_digest"
    return m.group(1)


class DigestWiringTests(unittest.TestCase):
    CALLERS = {"daily-insti.sh", "daily-branches.sh"}

    def test_exactly_these_rounds_send_it(self):
        callers = {p.name for p in sorted(SCRIPTS_DIR.glob("*.sh"))
                   if p.name != "lib.sh"
                   and any(ln.strip() == "futures_digest" for ln in _code_lines(p))}
        self.assertEqual(callers, self.CALLERS)

    def test_it_runs_after_the_deploy_and_bare(self):
        for name in sorted(self.CALLERS):
            with self.subTest(script=name):
                lines = [ln.strip() for ln in _code_lines(SCRIPTS_DIR / name)]
                deploy = lines.index('run_step_or_fail "deploy" deploy_data')
                call = lines.index("futures_digest")
                self.assertGreater(call, deploy, "推播講的必須是已經上線的那一份")
                self.assertEqual(sum(1 for ln in lines if "futures_digest" in ln), 1)
                self.assertFalse(any("futures-anomaly-digest" in ln for ln in lines),
                                 "只能經過 lib.sh 的 futures_digest")

    def test_the_helper_never_fails_the_round(self):
        body = _digest_body()
        self.assertRegex(body, r"\|\|\s*rc=\$\?")
        self.assertRegex(body, r"timeout\s+.*?\s60s\s")
        self.assertEqual(body.strip().splitlines()[-1].strip(), "return 0")
        self.assertNotRegex(body, r"(?m)^\s*exit\b")
        self.assertNotIn("set -e", body)
        self.assertIn("notify_warn", body)

    def test_the_helper_cannot_reach_the_database(self):
        body = _digest_body()
        self.assertIn("futures-anomaly-digest", body)
        self.assertNotIn("/app/data", body)
        self.assertIn('"$REPO/web/public/data":/app/web/public/data:ro', body)
        self.assertNotRegex(body, r"(?m)(^|\$\(|;)\s*radar(_timeout)?\s")
        self.assertNotIn("acquire_db_lock", body)

    def test_the_helper_dedupes_by_the_futures_day(self):
        body = _digest_body()
        self.assertIn('marker="${FUTURES_DIGEST_DIR}/.futures-digest-${as_of}"', body)
        self.assertRegex(body, r'if \[ -e "\$marker" \]; then')
        lib = LIB.read_text(encoding="utf-8")
        self.assertIn('FUTURES_DIGEST_DIR="${FUTURES_DIGEST_DIR:-${HOME:-/tmp}}"', lib)

    def test_notify_is_untouched(self):
        """各輪在 set -e 底下呼叫 notify,它必須永遠成功;推播的確認走另一個 helper。"""
        lib = "\n".join(_code_lines(LIB))
        m = re.search(r"^notify\(\)\s*\{(.*?)\n\}", lib, re.S | re.M)
        self.assertIsNotNone(m)
        self.assertIn('title="$(job_zh) · ${kind}"', m.group(1))
        self.assertNotIn("$4", m.group(1))
        self.assertIn('>/dev/null || true', m.group(1))

    def test_the_marker_is_written_only_after_a_confirmed_send(self):
        body = _digest_body()
        self.assertRegex(
            body,
            r'if futures_digest_send "\$body" "\$title"; then\s*\n\s*: > "\$marker" \|\| true\s*\n\s*else',
        )
        self.assertEqual(body.count(': > "$marker"'), 1)
        lib = "\n".join(_code_lines(LIB))
        m = re.search(r"^futures_digest_send\(\)\s*\{(.*?)\n\}", lib, re.S | re.M)
        self.assertIsNotNone(m, "lib.sh 裡找不到 futures_digest_send")
        self.assertIn("curl -sf", m.group(1))
        self.assertNotIn("|| true", m.group(1), "它必須回傳 curl 的結果")

    def test_old_markers_are_cleaned_up(self):
        self.assertRegex(_digest_body(),
                         r"find \"\$FUTURES_DIGEST_DIR\" .*-name '\.futures-digest-\*' -mtime \+14")


BASH = shutil.which("bash")


def _bash_works() -> bool:
    if not BASH:
        return False
    try:
        return subprocess.run([BASH, "-c", "echo ok"], capture_output=True, text=True,
                              timeout=20).stdout.strip() == "ok"
    except Exception:  # noqa: BLE001 - WSL 啟動器在沒有發行版時會失敗
        return False


@unittest.skipUnless(_bash_works(), "需要可用的 bash")
class DigestHelperBehaviourTests(unittest.TestCase):
    """假的 docker / curl,實跑 ``futures_digest``:失敗不中止、同一天只送一次。"""

    @staticmethod
    def _for_bash(path: Path) -> str:
        """Windows 上 PATH 的 bash 是 WSL,看不懂 `d:\\...`(同 test_minutes_until_quiet_window)。"""
        if os.name == "nt":
            drive, rest = os.path.splitdrive(str(path))
            return "/mnt/" + drive[0].lower() + rest.replace("\\", "/")
        return str(path)

    def _run(self, docker_stdout: str, docker_rc: int, home: Path, runs: int = 1,
             curl_rc: int = 0, pre: str = "") -> str:
        (home / "docker.out").write_text(docker_stdout, encoding="utf-8", newline="\n")
        h = self._for_bash(home)
        script = f"""
source '{self._for_bash(LIB)}' >/dev/null 2>&1
export HOME='{h}' NTFY=test FUTURES_DIGEST_DIR='{h}'
docker() {{ cat '{h}/docker.out'; return {docker_rc}; }}
timeout() {{ shift 3; "$@"; }}
curl() {{ printf 'CURL %s\\n' "$*" >> '{h}/curl.log'; return {curl_rc}; }}
{pre}
for i in $(seq 1 {runs}); do futures_digest; done
echo ROUND_CONTINUES
"""
        # 寫成檔案再跑:經過 WSL 啟動器的 `bash -c` 會把 $(...) 弄壞。
        (home / "run.sh").write_text(script, encoding="utf-8", newline="\n")
        res = subprocess.run([BASH, f"{h}/run.sh"], capture_output=True, timeout=60)
        out = res.stdout.decode("utf-8", "replace")
        self.assertIn("ROUND_CONTINUES", out, res.stderr.decode("utf-8", "replace"))
        log = home / "curl.log"
        return log.read_text(encoding="utf-8") if log.exists() else ""

    def _home(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def test_sends_once_per_futures_day(self):
        home = self._home()
        sent = self._run("期貨量異常 · 2026-10-02\n內文\nhttps://x", 0, home, runs=2)
        self.assertEqual(sent.count("CURL"), 1)
        self.assertIn("Title: 期貨量異常 · 2026-10-02", sent)
        self.assertTrue((home / ".futures-digest-2026-10-02").exists())

    def test_a_failed_send_leaves_no_marker_and_is_retried(self):
        home = self._home()
        sent = self._run("期貨量異常 · 2026-10-02\n內文\nhttps://x", 0, home, runs=2, curl_rc=22)
        self.assertEqual(sent.count("Title: 期貨量異常 · 2026-10-02"), 2, "失敗要在下一輪重送")
        self.assertFalse((home / ".futures-digest-2026-10-02").exists())

    def test_markers_older_than_14_days_are_deleted(self):
        home = self._home()
        pre = (f"touch -d '20 days ago' '{self._for_bash(home)}/.futures-digest-2026-09-01'\n"
               f"touch -d '3 days ago' '{self._for_bash(home)}/.futures-digest-2026-09-29'")
        self._run("", 0, home, pre=pre)
        self.assertFalse((home / ".futures-digest-2026-09-01").exists())
        self.assertTrue((home / ".futures-digest-2026-09-29").exists())

    def test_silent_when_there_is_nothing(self):
        self.assertEqual(self._run("", 0, self._home()), "")

    def test_a_failure_warns_and_the_round_continues(self):
        sent = self._run("", 1, self._home())
        self.assertIn("CURL", sent)
        self.assertIn("期貨量異常摘要產生失敗", sent)
