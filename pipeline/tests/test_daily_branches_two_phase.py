# -*- coding: utf-8 -*-
"""docs/47 §8.10:分點輪的兩段式抓取(股票池先上線、權證池背景抓、第二段之前寫入)。

**真的執行** `vps/scripts/daily-branches.sh`(需要 bash;沒有就 skip):把腳本複製到暫存的
`vps/scripts/`,旁邊放一份假的 lib.sh——它 source 真的 lib.sh,再把會碰 docker／網路／正式
路徑的函式換成 stub(`radar`、`radar_timeout`、`radar_ro_sql`、`deploy_data`、`sync_code`…),
`REPO` 指到暫存目錄。DB 鎖用真的 flock(暫存鎖檔)。每個 stub 把事件追加到同一個事件檔,
斷言事件的**先後**:

* 第一輪:股票抓 → 權證背景抓起跑 → 股票寫入 → 評分 → **第一段上線**(權證還在抓)→
  排行統計(docs/44 §3.6:不讀權證列,與還在跑的抓取重疊)→ 等權證 → 權證寫入 →
  第二段上線 → 完成標記。
* 權證段失敗(抓取 124、寫入 76)→ 第一段、第二段照常上線,只 warn,不寫權證。
* 股票不合格 → 中止;背景的權證抓取被 TERM 收掉(不帶著來源鎖活過本輪)。
* 22:30:兩段都完整 → 收工;只缺權證 → 不抓股票、權證在評分之前寫入、上線一次;
  股票覆蓋率 < 1 但權證 ok → 只抓股票。
* 背景抓取的子 shell 沒有帶著 fd 9(DB 鎖)。
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


def _bash_path(p: Path) -> str:
    s = str(p)
    if sys.platform == "win32" and re.match(r"^[A-Za-z]:\\", s):
        return "/mnt/" + s[0].lower() + s[2:].replace("\\", "/")
    return s


def _bash_available() -> bool:
    if shutil.which("bash") is None:
        return False
    try:
        r = subprocess.run(["bash", "-c", "command -v flock && command -v pkill"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


# 假 lib.sh:先 source 真的,再蓋掉碰外界的函式。__REAL_LIB__ / __T__ 由測試代入。
FAKE_LIB = r"""
export RADAR_DB_LOCK_FILE="__T__/db.lock"
export NTFY=""
source "__REAL_LIB__"
REPO="__T__"
EV="__T__/events"
ev() { echo "$*" >> "$EV"; }
notify() { ev "NOTIFY pri=${2:-high} kind=${3:-} msg=$1"; }
sync_code() { :; }
acquire_branch_source_lock_wait() { ev "source-lock"; }
prefetch_intraday() { :; }
build_bull_board() { :; }
futures_digest() { :; }
deploy_data() { ev "deploy"; }
branch_round_marker() { echo "__T__/marker-$1.done"; }
radar_ro_sql() {
  case "$1" in
    *"MAX(date) FROM daily_prices"*|*"MAX(date) FROM indicators_daily"*) TZ=Asia/Taipei date +%F ;;
    *futures-day*) echo 1 ;;
    *branch_coverage*) echo "expected=1960 ratio=${COV_RATIO:-1.0000} done=1960 empty=0" ;;
    *branch_warrant_pool*) echo "${WPOOL_STATUS:-}" ;;
    *"dataset = 'insti'"*) ev "insti-check"; echo "${INSTI_SOURCES:-2}" ;;
    *) echo "" ;;
  esac
}
radar() {
  ev "radar $*"
  case "$*" in
    *"--datasets insti --require"*) return "${STUB_INSTI_RC:-0}" ;;
    *"--from-stage"*warrants*) return "${STUB_WIMPORT_RC:-0}" ;;
    *"--from-stage"*) return "${STUB_SIMPORT_RC:-0}" ;;
  esac
  return 0
}
radar_timeout() {
  shift
  case "$*" in
    *"--phase warrants"*)
      if [ -e "/proc/$BASHPID/fd/9" ]; then ev "bg-fd9=open"; else ev "bg-fd9=closed"; fi
      ev "warrant-fetch-start"
      sleep "${STUB_WFETCH_SECS:-2}" || { ev "warrant-fetch-terminated"; return 143; }
      ev "warrant-fetch-end"
      return "${STUB_WFETCH_RC:-0}" ;;
    *"--phase stocks"*)
      ev "stock-fetch $*"
      return 0 ;;
  esac
  ev "radar_timeout $*"
  return 0
}
"""


@unittest.skipUnless(_bash_available(), "需要 bash + flock + pkill")
class TwoPhaseRound(unittest.TestCase):
    def _run(self, env: dict | None = None, marker: str | None = None,
             insti_missing: bool = False) -> tuple[list[str], str]:
        tmp = Path(tempfile.mkdtemp(prefix="radar-2phase-"))
        try:
            scripts = tmp / "vps" / "scripts"
            scripts.mkdir(parents=True)
            (tmp / "data").mkdir()
            shutil.copy(SCRIPT, scripts / "daily-branches.sh")
            t = _bash_path(tmp)
            (scripts / "lib.sh").write_text(
                FAKE_LIB.replace("__REAL_LIB__", _bash_path(LIB)).replace("__T__", t),
                encoding="utf-8", newline="\n")
            exports = "".join(f'export {k}="{v}"\n' for k, v in (env or {}).items())
            pre = ""
            if marker is not None:
                pre = (f'printf "%s\\ncoverage_ratio={marker}\\n" "$(date -Is)" > '
                       f'"{t}/marker-$(TZ=Asia/Taipei date +%F).done"\n')
            if insti_missing:
                pre += f'echo first-round > "{t}/marker-$(TZ=Asia/Taipei date +%F).done.insti-missing"\n'
            runner = tmp / "run.sh"
            runner.write_text(
                exports + "export BRANCH_PROBE=0\n" + pre
                + f'bash "{t}/vps/scripts/daily-branches.sh"\necho "RC=$?"\n',
                encoding="utf-8", newline="\n")
            r = subprocess.run(["bash", _bash_path(runner)], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=120)
            ev_path = tmp / "events"
            events = ev_path.read_text(encoding="utf-8").splitlines() if ev_path.exists() else []
            markers = list(tmp.glob("marker-*.done"))
            self.marker_text = markers[0].read_text(encoding="utf-8") if markers else None
            self.insti_marker = bool(list(tmp.glob("marker-*.done.insti-missing")))
            return events, r.stdout + r.stderr
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @staticmethod
    def _first(events: list[str], pred) -> int:
        return next(i for i, e in enumerate(events) if pred(e))

    @staticmethod
    def _all(events: list[str], pred) -> list[int]:
        return [i for i, e in enumerate(events) if pred(e)]

    def test_first_round_publishes_stocks_before_the_warrant_fetch_ends(self):
        ev, out = self._run({"STUB_WFETCH_SECS": "3"})
        self.assertIn("RC=0", out, out)
        stock_fetch = self._first(ev, lambda e: e.startswith("stock-fetch"))
        self.assertIn("--top 0 --phase stocks", ev[stock_fetch])
        self.assertNotIn("--warrant-turnover-min", ev[stock_fetch], "股票段不接權證")
        w_start = self._first(ev, lambda e: e == "warrant-fetch-start")
        w_end = self._first(ev, lambda e: e == "warrant-fetch-end")
        stock_import = self._first(ev, lambda e: e.startswith("radar import-branch-trades --from-stage")
                                   and "warrants" not in e)
        w_import = self._first(ev, lambda e: "--from-stage" in e and "warrants" in e)
        scores = self._first(ev, lambda e: e.startswith("radar compute-scores"))
        stats = self._first(ev, lambda e: e.startswith("radar compute-branch-stats"))
        deploys = self._all(ev, lambda e: e == "deploy")
        self.assertEqual(len(deploys), 2, ev)
        self.assertLess(stock_fetch, w_start, "股票抓完才開始抓權證(同一時間只有一條抓取)")
        self.assertLess(stock_import, scores)
        self.assertLess(deploys[0], w_end, "第一段上線不等權證")
        self.assertLess(w_end, w_import)
        self.assertLess(deploys[0], w_import)
        # docs/44 §3.6:排行統計不讀權證列,排在權證收尾之前,與還在跑的權證抓取重疊;
        # 第二段匯出仍在權證寫入之後,看到最終資料。
        self.assertLess(deploys[0], stats, "排行統計不在第一段上線的路徑上")
        self.assertLess(stats, w_import, "排行統計先算,不空等權證抓取")
        exports = self._all(ev, lambda e: e.startswith("radar export-json"))
        self.assertEqual(len(exports), 2, ev)
        self.assertLess(w_import, exports[1], "第二段匯出看到權證")
        self.assertLess(exports[1], deploys[1])
        self.assertIn("bg-fd9=closed", ev, "背景抓取不得帶著 DB 鎖的 fd 9")
        self.assertIn("releasing the DB lock while waiting", out)
        self.assertIn("[warrants] ", out, "背景抓取的 log 收回來時加前綴倒進本輪 log")
        self.assertIsNotNone(self.marker_text)
        self.assertIn("coverage_ratio=1.0000", self.marker_text)
        self.assertFalse([e for e in ev if "kind=注意" in e or "pri=high" in e], ev)

    def test_warrant_fetch_failure_warns_and_both_publishes_still_happen(self):
        ev, out = self._run({"STUB_WFETCH_SECS": "0", "STUB_WFETCH_RC": "124"})
        self.assertIn("RC=0", out, out)
        self.assertEqual(len(self._all(ev, lambda e: e == "deploy")), 2)
        self.assertFalse([e for e in ev if "--from-stage" in e and "warrants" in e],
                         "抓取失敗不寫權證")
        warn = [e for e in ev if e.startswith("NOTIFY") and "權證分點抓取未完成（碼 124）" in e]
        self.assertEqual(len(warn), 1, ev)
        self.assertIn("pri=default kind=注意", warn[0])
        self.assertIn("22:30 第二輪會重抓", warn[0])
        self.assertIn("radar compute-branch-stats", ev)
        self.assertIsNotNone(self.marker_text, "權證失敗不影響完成標記")

    def test_warrant_import_dead_feed_warns_only(self):
        ev, out = self._run({"STUB_WFETCH_SECS": "0", "STUB_WIMPORT_RC": "76"})
        self.assertIn("RC=0", out, out)
        warn = [e for e in ev if "權證分點這一段一筆都沒抓到（碼 76）" in e]
        self.assertEqual(len(warn), 1, ev)
        self.assertNotIn("pri=high", warn[0])
        self.assertEqual(len(self._all(ev, lambda e: e == "deploy")), 2)

    def test_unfit_stock_import_stops_the_background_warrant_fetch(self):
        ev, out = self._run({"STUB_WFETCH_SECS": "30", "STUB_SIMPORT_RC": "1"})
        self.assertIn("RC=1", out, out)
        self.assertNotIn("deploy", ev)
        self.assertIn("warrant-fetch-start", ev)
        self.assertNotIn("warrant-fetch-end", ev, "sleep 被 TERM 掉,沒有等 30 秒")
        self.assertIn("warrant-fetch-terminated", ev, "TERM 送到了抓取(真機是 timeout → 容器)")
        self.assertIn("stopping pid=", out)
        self.assertFalse([e for e in ev if "--from-stage" in e and "warrants" in e])

    def test_second_round_skips_when_both_phases_are_complete(self):
        ev, out = self._run({"BRANCH_ROUND_MODE": "import", "WPOOL_STATUS": "ok"}, marker="1.0000")
        self.assertIn("RC=0", out, out)
        self.assertIn("publish skipped: first round complete", out)
        self.assertFalse([e for e in ev if "fetch" in e or e == "deploy"], ev)

    def test_second_round_fetches_only_warrants_when_stocks_were_complete(self):
        ev, out = self._run({"BRANCH_ROUND_MODE": "import", "WPOOL_STATUS": "incomplete",
                             "STUB_WFETCH_SECS": "1"}, marker="1.0000")
        self.assertIn("RC=0", out, out)
        self.assertFalse([e for e in ev if e.startswith("stock-fetch")], "股票已完整,不再抓")
        self.assertFalse([e for e in ev if "--from-stage" in e and "warrants" not in e],
                         "不再匯入股票")
        w_import = self._first(ev, lambda e: "--from-stage" in e and "warrants" in e)
        scores = self._first(ev, lambda e: e.startswith("radar compute-scores"))
        deploys = self._all(ev, lambda e: e == "deploy")
        self.assertLess(w_import, scores, "只刷新評分的那一輪只上線一次,權證要在它之前寫入")
        self.assertEqual(len(deploys), 1)
        self.assertNotIn("radar compute-branch-stats", ev)
        self.assertIn("1.0000", self.marker_text, "不重寫標記")

    def test_second_round_refetches_only_stocks_when_warrants_were_ok(self):
        ev, out = self._run({"BRANCH_ROUND_MODE": "import", "WPOOL_STATUS": "ok",
                             "COV_RATIO": "1.0000"}, marker="0.9900")
        self.assertIn("RC=0", out, out)
        self.assertTrue([e for e in ev if e.startswith("stock-fetch")])
        self.assertNotIn("warrant-fetch-start", ev)
        self.assertEqual(len(self._all(ev, lambda e: e == "deploy")), 1)

    def test_second_round_without_marker_takes_over_both_phases(self):
        ev, out = self._run({"BRANCH_ROUND_MODE": "import", "STUB_WFETCH_SECS": "0"})
        self.assertIn("RC=0", out, out)
        self.assertTrue([e for e in ev if e.startswith("stock-fetch")])
        self.assertIn("warrant-fetch-start", ev)
        self.assertEqual(len(self._all(ev, lambda e: e == "deploy")), 2)
        self.assertIsNotNone(self.marker_text)

    # ── 三大法人晚到(2026-10-24):評分前補匯一次;22:30 法人晚到就重新上線 ──────────
    @staticmethod
    def _is_insti_retry(e: str) -> bool:
        return e.startswith("radar import-daily") and "--datasets insti --require twse:insti,tpex:insti" in e

    def test_insti_already_present_means_no_extra_import(self):
        ev, out = self._run({"STUB_WFETCH_SECS": "0"})
        self.assertIn("RC=0", out, out)
        self.assertIn("insti-check", ev, "先做唯讀檢查")
        self.assertFalse([e for e in ev if self._is_insti_retry(e)], ev)
        self.assertFalse(self.insti_marker)
        self.assertEqual(len(self._all(ev, lambda e: e == "deploy")), 2)

    def test_missing_insti_is_imported_once_after_the_crawl_and_before_scores(self):
        ev, out = self._run({"STUB_WFETCH_SECS": "0", "INSTI_SOURCES": "1"})
        self.assertIn("RC=0", out, out)
        retries = self._all(ev, self._is_insti_retry)
        self.assertEqual(len(retries), 1, ev)
        self.assertIn(f'--date {self._today_compact()}', ev[retries[0]], "帶 ROUND_DATE")
        stock_import = self._first(ev, lambda e: e.startswith("radar import-branch-trades --from-stage")
                                   and "warrants" not in e)
        scores = self._first(ev, lambda e: e.startswith("radar compute-scores"))
        deploys = self._all(ev, lambda e: e == "deploy")
        self.assertLess(stock_import, retries[0], "抓完、寫入分點之後")
        self.assertLess(retries[0], scores, "評分之前,第一段上線就帶著它")
        self.assertLess(retries[0], deploys[0])
        self.assertEqual(len(deploys), 2)
        self.assertIn("step import-insti-retry done rc=0", out)
        self.assertFalse(self.insti_marker, "補到了 → 不留標記")
        self.assertFalse([e for e in ev if e.startswith("NOTIFY") and "三大法人" in e], ev)

    def test_insti_still_pending_logs_only_and_leaves_the_marker(self):
        ev, out = self._run({"STUB_WFETCH_SECS": "0", "INSTI_SOURCES": "1", "STUB_INSTI_RC": "75"})
        self.assertIn("RC=0", out, out)
        self.assertEqual(len(self._all(ev, self._is_insti_retry)), 1)
        self.assertIn("補匯後仍未公布齊全(exit 75)", out)
        self.assertFalse([e for e in ev if e.startswith("NOTIFY") and "三大法人" in e], "75 只寫 log")
        self.assertTrue(self.insti_marker, "評分時法人仍缺 → 留標記給 22:30")
        self.assertEqual(len(self._all(ev, lambda e: e == "deploy")), 2)

    def test_insti_import_error_warns_and_the_round_continues(self):
        ev, out = self._run({"STUB_WFETCH_SECS": "0", "INSTI_SOURCES": "1", "STUB_INSTI_RC": "1"})
        self.assertIn("RC=0", out, out)
        warn = [e for e in ev if e.startswith("NOTIFY") and "三大法人補匯失敗（碼 1）" in e]
        self.assertEqual(len(warn), 1, ev)
        self.assertIn("pri=default kind=注意", warn[0])
        self.assertIn("22:30", warn[0])
        self.assertFalse([e for e in ev if "pri=high" in e], ev)
        self.assertIn("radar compute-scores --date", " ".join(ev))
        self.assertEqual(len(self._all(ev, lambda e: e == "deploy")), 2)
        self.assertIsNotNone(self.marker_text, "照常寫完成標記")
        self.assertTrue(self.insti_marker)

    def test_second_round_republishes_when_insti_arrived_after_the_first_publish(self):
        ev, out = self._run({"BRANCH_ROUND_MODE": "import", "WPOOL_STATUS": "ok",
                             "INSTI_SOURCES": "2"}, marker="1.0000", insti_missing=True)
        self.assertIn("RC=0", out, out)
        self.assertNotIn("publish skipped", out)
        self.assertFalse([e for e in ev if "fetch" in e], "不重爬")
        self.assertFalse([e for e in ev if self._is_insti_retry(e)], "開頭那次已拿到,不再補匯")
        self.assertNotIn("radar compute-branch-stats", ev)
        self.assertEqual(len(self._all(ev, lambda e: e.startswith("radar compute-scores"))), 1)
        self.assertEqual(len(self._all(ev, lambda e: e == "deploy")), 1)
        ok = [e for e in ev if e.startswith("NOTIFY") and "kind=成功" in e]
        self.assertEqual(len(ok), 1, ev)
        self.assertIn("晚到的三大法人", ok[0])
        self.assertFalse(self.insti_marker, "到齊並重算之後刪掉標記")
        self.assertIn("1.0000", self.marker_text, "不重寫完成標記")

    def test_second_round_still_skips_when_insti_is_still_missing(self):
        ev, out = self._run({"BRANCH_ROUND_MODE": "import", "WPOOL_STATUS": "ok",
                             "INSTI_SOURCES": "1"}, marker="1.0000", insti_missing=True)
        self.assertIn("RC=0", out, out)
        self.assertIn("publish skipped: first round complete", out)
        self.assertNotIn("deploy", ev)
        self.assertTrue(self.insti_marker)

    def test_second_round_without_insti_marker_skips_as_before(self):
        ev, out = self._run({"BRANCH_ROUND_MODE": "import", "WPOOL_STATUS": "ok"}, marker="1.0000")
        self.assertIn("publish skipped: first round complete", out)
        self.assertNotIn("insti-check", ev, "沒有標記就不必查")

    @staticmethod
    def _today_compact() -> str:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y%m%d")


if __name__ == "__main__":
    unittest.main()
