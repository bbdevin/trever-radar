# -*- coding: utf-8 -*-
"""自選「特定分點」晚間推播(docs/52 §9):訊息、去重、CLI 協定,以及 lib.sh 的 watch_push
(假的 docker / curl 實跑)與 daily-branches.sh 的接線。"""
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
from radar.export.branch_watch import shard_of
from radar.export.watch_push import (
    DEFAULT_BRANCHES,
    LINE_MAX_CHARS,
    SITE_URL,
    build_rows,
    decide,
    load_watch,
    parse_branches,
    run,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "vps" / "scripts"
LIB = SCRIPTS_DIR / "lib.sh"
MODULE = REPO_ROOT / "pipeline" / "radar" / "export" / "watch_push.py"

BANNED = ("勝率", "獲利", "報酬", "關鍵分點", "大漲", "噴", "極品", "機率", "目標價", "買進", "賣出",
          "看多", "看空", "將會", "有效支撐", "壓力沉重", "做多", "做空", "建議", "喊單", "套牢")

FUBON, SINOPAC, YUANTA = DEFAULT_BRANCHES
AS_OF = "2026-10-20"
WARRANT_TODAY = {"data_date": AS_OF, "day": AS_OF, "counted": True, "complete": True,
                 "min_amount": 1000000, "pool_turnover_min": 1000000}
WARRANT_STALE = {"data_date": "2026-10-17", "day": "2026-10-17", "counted": False, "complete": True,
                 "min_amount": 1000000, "pool_turnover_min": 1000000}


def _row(sid, net, hold=0):
    """分片列 [代號, 買, 賣, 淨, 估計仍持有, 進場日, 出現天數, 淨張合計, 最後出現日, 均價]。"""
    if net is None:
        return [sid, None, None, None, hold, "2026-09-01", 3, hold, "2026-10-15", None]
    return [sid, max(net, 0), max(-net, 0), net, hold, "2026-09-01", 3, hold, AS_OF, None]


STOCKS = {
    "3324": ["雙鴻", 820.0, 2.1, 3000, 1, 1],
    "3017": ["奇鋐", 1015.0, 1.0, 8000, 1, 1],
    "3653": ["健策", 1900.0, -0.5, 900, 1, 1],
    "2454": ["聯發科", 1300.0, -1.2, 9000, 1, 1],
    "2330": ["台積電", 1450.0, 0.3, 30000, 1, 1],
    "6669": ["緯穎", 3000.0, 0.0, 1500, 1, 1],
}


def realistic_day(warrant=WARRANT_TODAY, coverage=None):
    """富邦-新店 為主;雙鴻 三家同買(永豐金-內湖 只有認購權證)、奇鋐 2/3、健策 2/3、緯穎 只有主分點、
    台積電 只有元大-松江;聯發科 富邦＋永豐金同賣。"""
    branches = {
        FUBON: [_row("3324", 820), _row("3017", 450, hold=9000), _row("3653", 60),
                _row("6669", 30), _row("2454", -300)],
        SINOPAC: [_row("2454", -80), _row("3653", 15)],
        YUANTA: [_row("3324", 120), _row("3017", 60), _row("2330", 200)],
    }
    warrants = {SINOPAC: [["3324", 3_200_000, None, None, None, None, None]]}
    index = {"version": 1, "as_of": AS_OF, "window_days": 60, "window_from": "2026-07-23",
             "shards": 64, "hold_min": 100, "hold_floor": 20, "hold_top": 60,
             "coverage": coverage or {"covered": 1957, "expected": 1957, "complete": True},
             "warrant": warrant,
             "branches": [[b, shard_of(b), 1, 1, 0, 0] for b in sorted(branches)]}
    return index, branches, warrants


def write_export(root: Path, index, branches, warrants):
    d = root / "branches" / "watch"
    d.mkdir(parents=True, exist_ok=True)
    shards: dict[int, dict] = {}
    for b, rows in branches.items():
        s = shard_of(b)
        sh = shards.setdefault(s, {"version": 1, "as_of": index["as_of"], "shard": s,
                                   "branches": {}, "warrants": {}, "stocks": {}})
        sh["branches"][b] = rows
        for r in rows:
            sh["stocks"][r[0]] = STOCKS[r[0]]
    for b, rows in warrants.items():
        s = shard_of(b)
        sh = shards.setdefault(s, {"version": 1, "as_of": index["as_of"], "shard": s,
                                   "branches": {}, "warrants": {}, "stocks": {}})
        sh["warrants"][b] = rows
        for r in rows:
            sh["stocks"][r[0]] = STOCKS[r[0]]
    for s, sh in shards.items():
        (d / f"s{s:02d}.json").write_text(json.dumps(sh, ensure_ascii=False), encoding="utf-8")
    (d / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")


class _Tmp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def export(self, **kw):
        write_export(self.root, *realistic_day(**kw))

    def push(self, state=None, **kw):
        return run(self.root, list(DEFAULT_BRANCHES), state, **kw)


class MessageTests(_Tmp):
    def test_realistic_day_verbatim(self):
        self.export()
        res = self.push(expect_date=AS_OF)
        self.assertTrue(res["send"])
        self.assertEqual(res["kind"], "first")
        self.assertEqual(res["title"], "特定分點 10/20 · 主 富邦新店")
        self.assertEqual(res["body"], "\n".join([
            "主分點買超 4 檔 · 全部同買 1 檔 · 主分點賣超 1 檔",
            "買超 雙鴻 3/3 富邦新店+820 永豐金內湖 權證認購+320萬 元大松江+120",
            "買超 奇鋐 2/3 富邦新店+450 元大松江+60 估計持有量大",
            "買超 健策 2/3 富邦新店+60 永豐金內湖+15",
            "賣超 聯發科 2/3 富邦新店−300 永豐金內湖−80",
            "單位:張 · 含權證(金額為估算)",
        ]))

    def test_at_most_six_body_lines(self):
        self.export()
        self.assertLessEqual(len(self.push()["body"].splitlines()), 6)

    def test_ordering_anchor_first_then_count_then_amount(self):
        self.export()
        index, shards = load_watch(self.root, list(DEFAULT_BRANCHES))
        rows = build_rows(list(DEFAULT_BRANCHES), shards, True)
        from radar.export.watch_push import ordered
        buy = [r["sid"] for r in ordered(rows, "buy", FUBON)]
        # 雙鴻 3 家;奇鋐、健策 2 家(奇鋐金額大);緯穎 只有主分點;台積電 主分點沒參與 → 最後
        self.assertEqual(buy, ["3324", "3017", "3653", "6669", "2330"])

    def test_warrant_not_counted_says_it_comes_later(self):
        self.export(warrant=WARRANT_STALE)
        res = self.push()
        self.assertIn("全部同買 0 檔", res["body"])          # 永豐金只有(舊的)權證 → 不算
        self.assertIn("買超 雙鴻 2/3 富邦新店+820 元大松江+120", res["body"])
        self.assertNotIn("權證認購", res["body"])
        self.assertTrue(res["body"].endswith("權證分點只到 10/17,權證同買稍後更新"))

    def test_warrant_incomplete_today(self):
        w = dict(WARRANT_TODAY, counted=False, complete=False)
        self.export(warrant=w)
        self.assertIn("權證分點未完整,權證同買稍後更新", self.push()["body"])

    def test_no_warrant_data(self):
        self.export(warrant=None)
        self.assertIn("不含權證", self.push()["body"])

    def test_coverage_incomplete_is_said(self):
        self.export(coverage={"covered": 1688, "expected": 1957, "complete": False})
        self.assertIn("分點已匯入 1,688/1,957 檔", self.push()["body"])

    def test_coverage_complete_says_nothing(self):
        self.export()
        self.assertNotIn("分點已匯入", self.push()["body"])

    def test_long_lines_are_truncated(self):
        index, branches, warrants = realistic_day()
        many = [f"券商{i}-分公司{i}" for i in range(6)]
        index["branches"] = [[b, shard_of(b), 1, 0, 0, 0] for b in many]
        STOCKS["9999"] = ["很長很長的股票名稱", 10.0, 0.0, 100, 1, 1]
        self.addCleanup(STOCKS.pop, "9999")
        write_export(self.root, index, {b: [_row("9999", 1234)] for b in many}, {})
        res = run(self.root, many, None)
        line = res["body"].splitlines()[1]
        self.assertEqual(len(line), LINE_MAX_CHARS)
        self.assertTrue(line.endswith("…"))
        self.assertTrue(line.startswith("買超 很長很長的股票名稱 6/6"))

    def test_nothing_moved(self):
        index, _b, _w = realistic_day()
        write_export(self.root, index, {FUBON: [_row("2330", None, hold=500)]}, {})
        body = self.push()["body"]
        self.assertIn("主分點買超 0 檔 · 全部同買 0 檔 · 主分點賣超 0 檔", body)
        self.assertIn("選的分點今天都沒有進入任何股票的前 15 大買超或賣超", body)

    def test_unknown_branch_is_harmless(self):
        self.export()
        res = run(self.root, ["不存在-分點", FUBON], None)
        self.assertIn("主分點買超 0 檔", res["body"])

    def test_no_banned_words_in_any_variant(self):
        for kw in ({}, {"warrant": WARRANT_STALE}, {"warrant": None},
                   {"coverage": {"covered": 1, "expected": 2, "complete": False}}):
            with self.subTest(**{k: str(v)[:20] for k, v in kw.items()}):
                self.export(**kw)
                res = self.push()
                text = res["title"] + res["body"]
                for bad in BANNED:
                    self.assertNotIn(bad, text)

    def test_module_literals_carry_no_banned_word(self):
        import ast
        literals = [n.value for n in ast.walk(ast.parse(MODULE.read_text(encoding="utf-8")))
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        for lit in literals:
            for bad in BANNED:
                self.assertNotIn(bad, lit)

    def test_click_url(self):
        self.assertEqual(SITE_URL, "https://radar.techtrever.com/watchlist?tab=branches")


class GuardTests(_Tmp):
    def test_other_day_is_not_sent(self):
        self.export()
        res = self.push(expect_date="2026-10-21")
        self.assertFalse(res["send"])
        self.assertIn("不是本輪的", res["reason"])

    def test_force_ignores_the_date(self):
        self.export()
        self.assertTrue(self.push(expect_date="2026-10-21", force=True)["send"])

    def test_no_export(self):
        self.assertFalse(self.push()["send"])

    def test_parse_branches(self):
        self.assertEqual(parse_branches(None), list(DEFAULT_BRANCHES))
        self.assertEqual(parse_branches(""), list(DEFAULT_BRANCHES))
        self.assertEqual(parse_branches(" 元大-松江 ，富邦-新店,元大-松江,, "), ["元大-松江", "富邦-新店"])
        self.assertEqual(len(parse_branches(",".join(f"x{i}" for i in range(9)))), 6)
        self.assertEqual(parse_branches("a" * 65 + ",b"), ["b"])


class DedupeTests(_Tmp):
    """同一資料日:第一則 → 權證算進今天後名單有變才送更新 → 之後再變送最後一則 → 上限。"""

    def test_same_data_same_list_is_sent_once(self):
        self.export()
        first = self.push()
        self.assertTrue(first["send"])
        again = self.push(state=first["state"])
        self.assertFalse(again["send"])
        self.assertIn("名單與上一則相同", again["reason"])

    def test_amount_changes_only_are_not_material(self):
        self.export()
        st = self.push()["state"]
        index, branches, warrants = realistic_day()
        branches[FUBON][0] = _row("3324", 999)               # 張數變了,名單沒變
        write_export(self.root, index, branches, warrants)
        self.assertFalse(self.push(state=st)["send"])

    def test_stocks_then_warrants_then_late_then_cap(self):
        self.export(warrant=WARRANT_STALE)
        first = self.push()
        self.assertEqual(first["kind"], "first")
        # 第二段:權證算進今天 → 雙鴻 變 3/3(名單有變)→ 更新
        self.export()
        upd = self.push(state=first["state"])
        self.assertTrue(upd["send"])
        self.assertEqual(upd["kind"], "warrants")
        self.assertEqual(upd["title"], "特定分點 10/20 · 主 富邦新店 · 更新")
        lines = upd["body"].splitlines()
        self.assertEqual(lines[1], "權證算進今天之後名單有變動:")
        self.assertEqual(lines[2], "買超 雙鴻 3/3 富邦新店+820 永豐金內湖 權證認購+320萬 元大松江+120")
        self.assertEqual(len(lines), 4, "只列變動的股票")
        # 同一份資料再上線一次(22:30 沒變)→ 不送
        self.assertFalse(self.push(state=upd["state"])["send"])
        # 22:30 補齊覆蓋:永豐金也買了緯穎 → late
        index, branches, warrants = realistic_day()
        branches[SINOPAC].append(_row("6669", 40))
        write_export(self.root, index, branches, warrants)
        late = self.push(state=upd["state"])
        self.assertEqual(late["kind"], "late")
        self.assertIn("名單有變動:", late["body"])
        self.assertIn("買超 緯穎 2/3 富邦新店+30 永豐金內湖+40", late["body"])
        # 再變 → 已送三則,不再送
        branches[YUANTA].append(_row("6669", 10))
        write_export(self.root, index, branches, warrants)
        capped = self.push(state=late["state"])
        self.assertFalse(capped["send"])
        self.assertIn("上限", capped["reason"])

    def test_update_lists_at_most_three_changes(self):
        index, _b, _w = realistic_day(warrant=WARRANT_STALE)
        write_export(self.root, index, {FUBON: [_row("2330", None, hold=500)]}, {})
        st = self.push()["state"]                              # 第一則:今天都沒動
        self.export()                                          # 之後 5 檔進名單(台積電只有一家、不算)
        lines = self.push(state=st)["body"].splitlines()
        self.assertEqual(len(lines), 7)
        self.assertEqual(lines[1], "權證算進今天之後名單有變動:")
        self.assertEqual(lines[5], "另有 2 檔名單變動,詳見頁面")

    def test_first_already_with_warrants_later_change_is_not_blamed_on_warrants(self):
        """第一段沒上線(覆蓋率 < 0.98):第一則已含權證;之後的變動是 late、標頭不提權證。"""
        self.export()
        first = self.push()
        self.assertTrue(first["state"]["counted"])
        index, branches, warrants = realistic_day()
        branches[SINOPAC].append(_row("6669", 40))
        write_export(self.root, index, branches, warrants)
        upd = self.push(state=first["state"])
        self.assertEqual(upd["kind"], "late")
        self.assertEqual(upd["body"].splitlines()[1], "名單有變動:")
        self.assertNotIn("權證算進今天", upd["body"])

    def test_malformed_state_counts_as_none(self):
        self.export()
        good = self.push()["state"]
        bad_states = [
            [], 0, "x", 1.5, True, {},
            {**good, "sent": ["first"]}, {**good, "sent": "first"},
            {**good, "sent": {"other": "x"}}, {**good, "sent": {"first": 1}},
            {**good, "moves": "x"}, {**good, "moves": [["buy", "3324"]]},
            {**good, "moves": [["buy", 3324, []]]}, {**good, "moves": [["up", "3324", []]]},
            {**good, "moves": [["buy", "3324", "富邦-新店"]]}, {**good, "moves": [None]},
            {**good, "branches": "富邦-新店"}, {**good, "branches": [1]},
            {**good, "fp": None}, {**good, "data_date": 20261020}, {**good, "version": 2},
            {**good, "counted": "yes"},
        ]
        for st in bad_states:
            with self.subTest(state=str(st)[:60]):
                res = self.push(state=st)
                self.assertTrue(res["send"])
                self.assertEqual(res["kind"], "first")

    def test_malformed_state_through_the_cli(self):
        for raw in ("[]", "0", '"x"', '{"version":1,"sent":[]}'):
            with self.subTest(raw=raw):
                self.export()
                buf = io.StringIO()
                import sys
                old = sys.stdin
                sys.stdin = io.StringIO(raw)
                try:
                    with redirect_stdout(buf):
                        main(["watch-push", "--data", str(self.root), "--state", "-"])
                finally:
                    sys.stdin = old
                self.assertTrue(buf.getvalue().startswith("STATE "))

    def test_warrants_counted_without_change_is_skipped(self):
        index, branches, _w = realistic_day(warrant=WARRANT_STALE)
        write_export(self.root, index, branches, {})
        st = self.push()["state"]
        index, branches, _w = realistic_day()
        write_export(self.root, index, branches, {})          # 權證算進今天,但沒有權證同買
        self.assertFalse(self.push(state=st)["send"])

    def test_new_day_starts_over(self):
        self.export()
        st = self.push()["state"]
        st["data_date"] = "2026-10-19"
        self.assertEqual(self.push(state=st)["kind"], "first")

    def test_changed_branch_set_starts_over(self):
        self.export()
        st = self.push()["state"]
        res = run(self.root, [FUBON, YUANTA], st)
        self.assertEqual(res["kind"], "first")

    def test_force_ignores_the_state(self):
        self.export()
        st = self.push()["state"]
        self.assertTrue(self.push(state=st, force=True)["send"])


class CliTests(_Tmp):
    def cli(self, *args, stdin=""):
        import sys
        buf = io.StringIO()
        old = sys.stdin
        sys.stdin = io.StringIO(stdin)
        try:
            with redirect_stdout(buf):
                main(["watch-push", "--data", str(self.root), *args])
        finally:
            sys.stdin = old
        return buf.getvalue()

    def test_protocol(self):
        self.export()
        out = self.cli("--state", "-", "--expect-date", AS_OF).splitlines()
        self.assertTrue(out[0].startswith("STATE {"))
        state = json.loads(out[0][len("STATE "):])
        self.assertEqual(state["data_date"], AS_OF)
        self.assertEqual(out[1], "TITLE 特定分點 10/20 · 主 富邦新店")
        self.assertEqual(out[2], f"CLICK {SITE_URL}")
        self.assertTrue(out[3].startswith("主分點買超 4 檔"))
        # 把狀態餵回去 → SKIP
        again = self.cli("--state", "-", stdin=out[0][len("STATE "):])
        self.assertTrue(again.startswith("SKIP "))

    def test_broken_state_counts_as_none(self):
        self.export()
        self.assertTrue(self.cli("--state", "-", stdin="{not json").startswith("STATE "))

    def test_branches_flag_and_dry_run(self):
        self.export()
        out = self.cli("--dry-run", "--branches", "元大-松江,富邦-新店")
        self.assertIn("分點組合(第一個為主): 元大-松江、富邦-新店", out)
        self.assertIn("特定分點 10/20 · 主 元大松江", out)
        self.assertNotIn("STATE", out)

    def test_dry_run_says_why_not(self):
        self.export()
        out = self.cli("--dry-run", "--expect-date", "2026-10-21")
        self.assertIn("不送: 資料日 2026-10-20 不是本輪的 2026-10-21", out)


# ── lib.sh 的 watch_push(假的 docker / curl)與接線 ─────────────────────────────

BASH = shutil.which("bash")


def _bash_works() -> bool:
    if not BASH:
        return False
    try:
        return subprocess.run([BASH, "-c", "echo ok"], capture_output=True, text=True,
                              timeout=20).stdout.strip() == "ok"
    except Exception:  # noqa: BLE001 - WSL 啟動器在沒有發行版時會失敗
        return False


def _for_bash(path: Path) -> str:
    if os.name == "nt":
        drive, rest = os.path.splitdrive(str(path))
        return "/mnt/" + drive[0].lower() + rest.replace("\\", "/")
    return str(path)


SAMPLE_OUT = ("STATE {\"version\":1,\"data_date\":\"2026-10-20\"}\n"
              "TITLE 特定分點 10/20 · 主 富邦新店\n"
              f"CLICK {SITE_URL}\n"
              "主分點買超 4 檔\n單位:張")


@unittest.skipUnless(_bash_works(), "需要可用的 bash")
class HelperBehaviourTests(unittest.TestCase):
    def _run(self, docker_stdout=SAMPLE_OUT, docker_rc=0, curl_rc=0, topic="secret-topic",
             args='"2026-10-20"', runs=1):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name)
        self.home = home
        (home / "docker.out").write_text(docker_stdout, encoding="utf-8", newline="\n")
        h = _for_bash(home)
        script = f"""
source '{_for_bash(LIB)}' >/dev/null 2>&1
export NTFY=ops WATCH_PUSH_NTFY_TOPIC='{topic}' WATCH_PUSH_STATE_FILE='{h}/state.json'
export WATCH_PUSH_BRANCHES='元大-松江,富邦-新店'
docker() {{ printf 'DOCKER %s\\n' "$*" >> '{h}/docker.log'; cat > '{h}/stdin.seen'; cat '{h}/docker.out'; return {docker_rc}; }}
timeout() {{ shift 3; "$@"; }}
curl() {{ printf 'CURL %s\\n' "$*" >> '{h}/curl.log'; case "$*" in *ntfy.sh/ops*) return 0;; esac; return {curl_rc}; }}
for i in $(seq 1 {runs}); do watch_push {args}; done
echo ROUND_CONTINUES
"""
        (home / "run.sh").write_text(script, encoding="utf-8", newline="\n")
        res = subprocess.run([BASH, f"{h}/run.sh"], capture_output=True, timeout=60)
        out = res.stdout.decode("utf-8", "replace")
        self.assertIn("ROUND_CONTINUES", out, res.stderr.decode("utf-8", "replace"))
        self.out = out
        log = home / "curl.log"
        return log.read_text(encoding="utf-8") if log.exists() else ""

    def _state(self):
        p = self.home / "state.json"
        return p.read_text(encoding="utf-8") if p.exists() else None

    def test_off_without_topic(self):
        self.assertEqual(self._run(topic=""), "")
        self.assertFalse((self.home / "docker.log").exists())

    def test_sends_to_the_watch_topic_and_writes_state(self):
        sent = self._run()
        self.assertEqual(sent.count("CURL"), 1)
        self.assertIn("ntfy.sh/secret-topic", sent)
        self.assertIn("Title: 特定分點 10/20 · 主 富邦新店", sent)
        self.assertIn(f"Click: {SITE_URL}", sent)
        self.assertIn("主分點買超 4 檔", sent)
        self.assertNotIn("STATE", sent)
        self.assertEqual(self._state().strip(), '{"version":1,"data_date":"2026-10-20"}')
        docker = (self.home / "docker.log").read_text(encoding="utf-8")
        self.assertIn("--expect-date 2026-10-20", docker)
        self.assertIn("--branches 元大-松江,富邦-新店", docker)
        self.assertIn("/app/web/public/data:ro", docker)
        self.assertIn("run --rm -i --init", docker, "timeout 的 TERM 要真的停得掉容器裡的 python")
        self.assertNotIn("/app/data", docker, "不掛資料庫目錄")

    def test_state_is_fed_back_on_stdin(self):
        self._run(runs=2)
        self.assertEqual((self.home / "stdin.seen").read_text(encoding="utf-8").strip(),
                         '{"version":1,"data_date":"2026-10-20"}')

    def test_failed_send_leaves_no_state_and_warns(self):
        sent = self._run(curl_rc=22)
        self.assertIsNone(self._state())
        self.assertIn("ntfy.sh/ops", sent)
        self.assertIn("特定分點推播送出失敗", sent)

    def test_skip_sends_nothing(self):
        self.assertEqual(self._run(docker_stdout="SKIP 名單與上一則相同"), "")
        self.assertIn("watch-push: SKIP", self.out)
        self.assertIsNone(self._state())

    def test_generation_failure_warns_and_continues(self):
        sent = self._run(docker_stdout="", docker_rc=1)
        self.assertIn("ntfy.sh/ops", sent)
        self.assertIn("特定分點推播產生失敗", sent)
        self.assertNotIn("secret-topic", sent)

    def test_force_sends_but_writes_no_state(self):
        sent = self._run(args="--force")
        self.assertIn("ntfy.sh/secret-topic", sent)
        self.assertIsNone(self._state())
        self.assertIn("--force", (self.home / "docker.log").read_text(encoding="utf-8"))


FULL_LINE_COMMENT = re.compile(r"^\s*#")


class WiringTests(unittest.TestCase):
    def test_called_inside_publish_site_after_deploy(self):
        src = (SCRIPTS_DIR / "daily-branches.sh").read_text(encoding="utf-8")
        m = re.search(r"^publish_site\(\)\s*\{(.*?)\n\}", src, re.S | re.M)
        self.assertIsNotNone(m)
        lines = [ln.strip() for ln in m.group(1).splitlines() if not FULL_LINE_COMMENT.match(ln)]
        self.assertIn('watch_push "$ROUND_DATE"', lines)
        self.assertGreater(lines.index('watch_push "$ROUND_DATE"'),
                           lines.index('run_step_or_fail "deploy" deploy_data'))

    def test_only_daily_branches_calls_it(self):
        callers = {p.name for p in SCRIPTS_DIR.glob("*.sh") if p.name != "lib.sh"
                   and re.search(r"(?m)^\s*watch_push\b", p.read_text(encoding="utf-8"))}
        self.assertEqual(callers, {"daily-branches.sh"})

    def test_helper_never_fails_the_round(self):
        lib = LIB.read_text(encoding="utf-8")
        m = re.search(r"^watch_push\(\)\s*\{(.*?)\n\}", lib, re.S | re.M)
        body = m.group(1)
        self.assertEqual(body.strip().splitlines()[-1].strip(), "return 0")
        self.assertNotRegex(body, r"(?m)^\s*exit\b")
        self.assertIn("|| rc=$?", body)
        self.assertRegex(body, r"timeout\s+.*?\s60s\s")
        self.assertIn('[ -n "${WATCH_PUSH_NTFY_TOPIC:-}" ] || return 0', body)
        self.assertNotIn("${NTFY}", body, "不送到維運主題")
        self.assertIn("docker run --rm -i --init", body)

    def test_state_file_is_gitignored(self):
        gi = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("data/watch-push-state.json", gi)
        self.assertIn("data/watch-push-state.json.tmp", gi)


if __name__ == "__main__":
    unittest.main()
