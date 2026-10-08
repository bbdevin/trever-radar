# -*- coding: utf-8 -*-
"""分點平行爬(docs/47 §8)的原始資料一致性:三條路寫進資料庫的列**位元級相同**。

    workers=1               改動前的循序爬(鏡像輪替、全域節流)
    workers=5               每站一個 worker、各自節流、單一寫者照順序寫
    workers=5 + 暫存檔      只抓不寫(--stage-to)→ 只寫不抓(--from-stage)

比的不只是 branch_trades_raw:``branch_dim`` 的 id 由插入順序決定,新分點在三條路
必須拿到同一個 id,否則 raw 列的 branch_id 會不同——這就是 worker 不准自己寫、
主執行緒必須照目標順序 commit 的理由。用真的 fubon 解析器(只 mock HTTP 層),
樣本裡刻意放:多檔共用的新分點、只在一檔出現的新分點、既有分點、空頁(NoDataError)、
第一次失敗第二次成功的標的(重試輪)。
"""
import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import radar.config as config
import radar.db as db
from radar import schema
from radar.importer import import_branch_trades
from radar.providers import fubon

DATE = "2026-10-07"
DATE_COMPACT = "20261007"
STOCKS = [f"{2000 + i}" for i in range(40)]
EMPTY = {"2003", "2017", "2031"}          # 當天沒有分點(佔位頁)
TRANSIENT = "2010"                        # 第一次失敗,重試成功


def _row_html(key: str, bhid: str, name: str, buy: int, sell: int, pct: float) -> str:
    net = buy - sell
    return (f'<TR><TD><a href="zco0.djhtm?a=2330&b={key}&BHID={bhid}">{name}</a></TD>'
            f'<TD>{buy:,}</TD><TD>{sell:,}</TD><TD>{net:,}</TD><TD>{pct:.2f}%</TD></TR>')


def _page_for(sid: str) -> str:
    """每檔一份決定性的頁面:分點集合與數字只由代號決定,跟哪一站、第幾次無關。"""
    n = int(sid)
    rows = [
        _row_html("9800", "9800", "既有分點", 100 + n % 7, 20, 1.5),       # 預先存在
        _row_html(f"N{n % 5}", "9A00", f"共用新點{n % 5}", 50 + n % 3, 10 + n % 4, 0.9),
        _row_html(f"S{sid}", "9B00", f"獨有新點{sid}", 30, 5 + n % 9, 0.4),
    ]
    return "<html><table>" + "".join(rows) + "</table></html>"


class _Runner:
    """一條路一個全新的資料庫;回傳可比對的快照。"""

    def __init__(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def __enter__(self):
        self._old = config.DB_URL, config.DATA_DIR
        config.DATA_DIR = self.dir
        config.DB_URL = "sqlite:///" + (self.dir / "t.db").as_posix()
        db._engine = None
        db.init_db()
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": sid, "name": f"s{sid}", "market": "twse",
                 "type": "stock", "is_active": 1} for sid in STOCKS])
            conn.execute(schema.branch_dim.insert(),
                         {"id": 1, "branch_key": "9800", "branch_name": "既有分點"})
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": sid, "date": DATE, "close": 100, "volume": 1,
                 # 成交金額刻意與代號順序相反:抓的順序(金額大的先)≠ 代號順序。
                 "turnover": 10_000 - int(sid)} for sid in STOCKS])
        return self

    def __exit__(self, *exc):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old
        self._tmp.cleanup()

    def snapshot(self) -> dict:
        with db.get_engine().connect() as conn:
            raw = conn.exec_driver_sql(
                "SELECT * FROM branch_trades_raw ORDER BY stock_id, branch_id").fetchall()
            dim = conn.exec_driver_sql("SELECT * FROM branch_dim ORDER BY id").fetchall()
            logs = conn.exec_driver_sql(
                "SELECT dataset, date, rows, status, COALESCE(error,'') FROM import_logs "
                "WHERE dataset IN ('branch','branch_coverage') ORDER BY id").fetchall()
        return {"raw": [tuple(r) for r in raw], "dim": [tuple(r) for r in dim],
                "logs": [tuple(r) for r in logs]}


def _http_stub(calls: list, partial: dict[str, set] | None = None, latency: float = 0.0):
    """只 mock HTTP:解析仍走 fubon._ROW。TRANSIENT 那一檔第一次拋錯。
    ``partial`` = {站: 它**已經公布**的代號集合}:那一站對其他代號回空頁(假「空」)。
    ``latency`` 讓五條 worker 都分得到工作(零延遲時第一條執行緒會把佇列抓光)。"""
    import threading
    import time

    seen: dict[str, int] = {}
    lock = threading.Lock()

    def get_text(url, params=None, encoding="big5", throttle=None, throttle_key=None):
        sid = params["a"]
        host = url.split("/z/")[0]
        with lock:
            calls.append((sid, host, throttle, throttle_key))
            seen[sid] = seen.get(sid, 0) + 1
            n = seen[sid]
        if latency:
            time.sleep(latency)
        if sid == TRANSIENT and n == 1:
            raise RuntimeError("transient reset")
        if sid in EMPTY:
            return "<html>no rows today</html>"
        if partial and host in partial and sid not in partial[host]:
            return "<html>not published here yet</html>"
        return _page_for(sid)
    return get_text


def _run(workers: int, staged: bool, calls: list) -> dict:
    with _Runner() as r, mock.patch.object(fubon, "get_text", side_effect=_http_stub(calls)):
        kw = dict(top=0, warrants=0, sleep_s=0, workers=workers)
        if staged:
            stage = r.dir / "stage.json"
            staged_info = import_branch_trades(DATE_COMPACT, stage_to=stage, **kw)
            assert staged_info["staged"] and stage.exists()
            # 抓的那一步一列都不寫、一筆 log 都不記。
            assert r.snapshot() == {"raw": [], "dim": [(1, "9800", None, "既有分點")], "logs": []} \
                or r.snapshot()["raw"] == [], "stage_to 不得寫資料庫"
            info = import_branch_trades(from_stage=stage, **kw)
        else:
            info = import_branch_trades(DATE_COMPACT, **kw)
        snap = r.snapshot()
        snap["info"] = {k: info[k] for k in ("done", "empty", "failed", "rows", "status",
                                               "coverage", "expected", "ratio")}
        return snap


class BranchCrawlParity(unittest.TestCase):
    def test_sequential_parallel_and_staged_write_identical_rows(self):
        seq_calls, par_calls, stg_calls = [], [], []
        seq = _run(1, False, seq_calls)
        par = _run(5, False, par_calls)
        stg = _run(5, True, stg_calls)

        self.assertEqual(seq["info"]["status"], "ok")
        self.assertEqual(seq["info"]["done"], 37)
        self.assertEqual(seq["info"]["empty"], 3)
        self.assertEqual(seq["info"]["failed"], 0, "重試輪把瞬時失敗救回來")
        self.assertGreater(len(seq["raw"]), 100)
        # 新分點真的被配了新 id(1 是預先存在的),而且有多檔共用的。
        self.assertGreater(len(seq["dim"]), 1 + 5)

        self.assertEqual(par["raw"], seq["raw"], "平行爬的 raw 列必須與循序爬位元級相同")
        self.assertEqual(par["dim"], seq["dim"], "branch_dim 的 id 配法必須相同(照順序寫)")
        self.assertEqual(par["logs"], seq["logs"])
        self.assertEqual(par["info"], seq["info"])

        self.assertEqual(stg["raw"], seq["raw"], "暫存檔那條路也要位元級相同")
        self.assertEqual(stg["dim"], seq["dim"])
        self.assertEqual(stg["logs"], seq["logs"])
        self.assertEqual(stg["info"], seq["info"])

    def test_parallel_crawl_pins_each_request_to_one_mirror_with_its_own_interval(self):
        calls = []
        _run(5, False, calls)
        hosts = {c[1] for c in calls}
        self.assertEqual(hosts, set(fubon.MIRROR_HOSTS), "五站都要用到")
        for sid, host, throttle, key in calls:
            with self.subTest(sid=sid, host=host):
                self.assertEqual(key, host, "節流 key = 那一站,不碰全域節流")
                self.assertEqual(throttle, 0 * len(fubon.MIRROR_HOSTS))
        # 每檔的請求數:1 次,TRANSIENT 2 次(重試),每個 empty 多 1 次(另一站確認,docs/47
        # §8.8),加上開跑前每站 12 檔的公布檢查。
        from radar.importer import BRANCH_MIRROR_CHECK_SAMPLE, _evenly_spaced
        per_sid = {}
        for sid, *_ in calls:
            per_sid[sid] = per_sid.get(sid, 0) + 1
        picks = set(_evenly_spaced(sorted(STOCKS), BRANCH_MIRROR_CHECK_SAMPLE))
        n_hosts = len(fubon.MIRROR_HOSTS)
        check = BRANCH_MIRROR_CHECK_SAMPLE * n_hosts
        # 開跑前檢查若剛好抽到 TRANSIENT,它的那一次瞬時失敗就被檢查吸收,主爬不再重試。
        retry = 0 if TRANSIENT in picks else 1
        self.assertEqual(sum(per_sid.values()), len(STOCKS) + retry + len(EMPTY) + check)
        for sid in EMPTY:
            own = per_sid[sid] - (n_hosts if sid in picks else 0)
            self.assertEqual(own, 2, f"{sid} 空的要被第二站問一次")

    def test_sequential_path_is_byte_for_byte_the_old_shape(self):
        """workers=1 不得碰新機制:輪替站、全域節流(throttle_key=None)、每檔一請求。"""
        calls = []
        _run(1, False, calls)
        self.assertEqual({c[3] for c in calls}, {None})
        self.assertEqual({c[2] for c in calls}, {0})
        self.assertEqual(len(calls), len(STOCKS) + 1)
        self.assertEqual(len({c[1] for c in calls}), len(fubon.MIRROR_HOSTS), "鏡像輪替")

    def test_stage_file_carries_everything_the_commit_needs(self):
        calls = []
        with _Runner() as r, mock.patch.object(fubon, "get_text", side_effect=_http_stub(calls)):
            stage = r.dir / "stage.json"
            import_branch_trades(DATE_COMPACT, top=0, warrants=0, sleep_s=0, workers=5,
                                 stage_to=stage)
            payload = json.loads(stage.read_text(encoding="utf-8"))
        self.assertEqual(payload["date"], DATE)
        self.assertEqual(payload["expected"], len(STOCKS))
        self.assertEqual([r["sid"] for r in payload["results"]], payload["targets"],
                         "結果照目標順序")
        self.assertEqual(payload["counts"], {"done": 37, "empty": 3, "failed": 0})
        self.assertIn("mirrors", payload["report"])
        self.assertIn("mirror_check", payload["report"])
        # 成交金額大的先(代號小的金額大):目標順序是倒著的代號。
        self.assertEqual(payload["targets"], sorted(STOCKS))
        self.assertTrue(payload["complete"])

    def test_resume_refetches_only_what_the_previous_stage_did_not_get(self):
        """HIGH 1(c):同一天已有暫存檔 → done 的不重抓;pending/failed/empty 重抓;
        最後寫進資料庫的列與一口氣抓完的循序爬位元級相同。"""
        seq = _run(1, False, [])
        calls = []
        with _Runner() as r, mock.patch.object(fubon, "get_text", side_effect=_http_stub(calls)):
            stage = r.dir / "stage.json"
            targets = sorted(STOCKS)
            prior = []
            for sid in targets:
                if sid in targets[:10] and sid not in EMPTY and sid != TRANSIENT:
                    prior.append({"sid": sid, "outcome": "done", "rows": _rows_via_parser(sid)})
                elif sid in targets[10:14]:
                    prior.append({"sid": sid, "outcome": "failed", "rows": None})
                else:
                    prior.append({"sid": sid, "outcome": "pending", "rows": None})
            from radar.importer import write_branch_stage
            write_branch_stage(stage, {"date": DATE, "complete": False, "targets": targets,
                                       "expected": len(STOCKS), "results": prior})
            info = import_branch_trades(DATE_COMPACT, top=0, warrants=0, sleep_s=0, workers=5,
                                        stage_to=stage)
            self.assertEqual(info["resumed"], len([p for p in prior if p["outcome"] == "done"]))
            fetched = {c[0] for c in calls}
            for p in prior:
                with self.subTest(sid=p["sid"]):
                    self.assertEqual(p["sid"] in fetched, p["outcome"] != "done")
            final = import_branch_trades(from_stage=stage, top=0, warrants=0, sleep_s=0)
            snap = r.snapshot()
        self.assertEqual(final["status"], "ok")
        self.assertEqual(snap["raw"], seq["raw"])
        self.assertEqual(snap["dim"], seq["dim"])

    def test_stage_checkpoints_during_the_crawl_and_sigterm_keeps_partial_progress(self):
        """HIGH 1(c)/HIGH 2:每 N 檔寫一次暫存檔;SIGTERM handler 被叫到 → 不再領工作、
        暫存檔 complete=false 保留已抓到的、以 143 離開。模擬送訊號:直接呼叫裝好的 handler。"""
        import signal

        from radar import importer

        writes = []
        real_write = importer.write_branch_stage

        def spy_write(path, payload):
            writes.append(dict(payload))
            real_write(path, payload)

        calls = []
        fired = {"done": False}
        real_fetch = importer._fetch_branch_targets

        def fetch_then_fire(*a, **kw):
            # 抓到第一個 checkpoint 之後「收到」SIGTERM:handler 必須已裝在 SIGTERM 上。
            handler = signal.getsignal(signal.SIGTERM)
            self.assertTrue(callable(handler) and handler not in (signal.SIG_DFL, signal.SIG_IGN))
            orig_checkpoint = kw["checkpoint"]

            def checkpoint(results):
                orig_checkpoint(results)
                if not fired["done"]:
                    fired["done"] = True
                    handler(signal.SIGTERM, None)
            kw["checkpoint"] = checkpoint
            return real_fetch(*a, **kw)

        with _Runner() as r, mock.patch.object(fubon, "get_text", side_effect=_http_stub(calls)), \
             mock.patch.object(importer, "write_branch_stage", side_effect=spy_write), \
             mock.patch.object(importer, "_fetch_branch_targets", side_effect=fetch_then_fire), \
             mock.patch.object(importer, "BRANCH_STAGE_CHECKPOINT_EVERY", 8):
            stage = r.dir / "stage.json"
            with self.assertRaises(SystemExit) as cm:
                import_branch_trades(DATE_COMPACT, top=0, warrants=0, sleep_s=0, workers=5,
                                     stage_to=stage)
            self.assertEqual(cm.exception.code, 143)
            self.assertEqual(signal.getsignal(signal.SIGTERM), signal.SIG_DFL, "handler 還原")
            payload = json.loads(stage.read_text(encoding="utf-8"))
            self.assertFalse(payload["complete"])
            n_done = sum(1 for x in payload["results"] if x["outcome"] == "done")
            n_empty = sum(1 for x in payload["results"] if x["outcome"] == "empty")
            n_pending = sum(1 for x in payload["results"] if x["outcome"] == "pending")
            self.assertGreaterEqual(n_done + n_empty, 8, "第一個 checkpoint 之前抓到的都在")
            self.assertGreater(n_pending, 0, "沒抓完的標成 pending")
            self.assertEqual(r.snapshot()["raw"], [], "一列都沒進資料庫")
            self.assertGreaterEqual(len(writes), 2, "途中至少一次 checkpoint + 收尾一次")
            self.assertFalse(writes[0]["complete"])
            # 第二次 --stage-to:只補沒抓到的,然後完整。
            calls.clear()
            with mock.patch.object(importer, "_fetch_branch_targets", side_effect=real_fetch):
                info = import_branch_trades(DATE_COMPACT, top=0, warrants=0, sleep_s=0, workers=5,
                                            stage_to=stage)
            self.assertEqual(info["resumed"], n_done)
            self.assertTrue(json.loads(stage.read_text(encoding="utf-8"))["complete"])
            self.assertEqual(info["done"], 37)


class FalseEmptiesFromAPartialMirror(unittest.TestCase):
    """2026-10-08 的事故:只公布了一半的鏡像站(cathay 待命加入)回了 98 個假「空」,被當成
    「當天沒有分點」上線。空不信單一站:每個 empty 到另一站再抓一次。"""

    def test_false_empties_are_recovered_from_another_mirror_and_rows_match_sequential(self):
        seq = _run(1, False, [])
        lagging = fubon.MIRROR_HOSTS[4]
        published = set(sorted(STOCKS)[:12])           # 它只公布了 12 檔
        calls = []
        import contextlib
        import io
        out = io.StringIO()
        with _Runner() as r, mock.patch.object(fubon, "get_text",
                                               side_effect=_http_stub(calls, {lagging: published},
                                                                      latency=0.003)), \
             contextlib.redirect_stdout(out):
            # 開跑前的 12 檔檢查本來會把它擋在待命;這裡 patch 檢查讓五站都「就緒」,逼它
            # 參與——模擬 10-08 cathay 通過了(太弱的)檢查卻只公布一半的情況。
            with mock.patch("radar.importer.probe_mirrors",
                            side_effect=lambda picks, date, hosts, per_host: {h: len(picks) for h in hosts}):
                info = import_branch_trades(DATE_COMPACT, top=0, warrants=0, sleep_s=0, workers=5)
            snap = r.snapshot()
        false_empties = [c for c in calls if c[1] == lagging and c[0] not in published and c[0] not in EMPTY]
        self.assertGreater(len(false_empties), 0, "那一站真的回了假空(測試前提)")
        self.assertEqual(info["empty"], len(EMPTY), "只剩真的空;假空全部被另一站救回")
        self.assertEqual(info["done"], 37)
        self.assertEqual(info["status"], "ok")
        self.assertEqual(snap["raw"], seq["raw"], "救回的列與循序爬位元級相同")
        self.assertEqual(snap["dim"], seq["dim"])
        log = out.getvalue()
        self.assertRegex(log, r"confirming \d+ empty result\(s\) from " + re.escape(lagging))
        self.assertRegex(log, r"empties checked=\d+ recovered=\d+ confirmed=3 failed=0")
        # 每個 empty 都被第二站問過(真空的也要確認),確認用的站不是回空的那一站。
        for sid in EMPTY:
            hosts_asked = [c[1] for c in calls if c[0] == sid]
            self.assertGreaterEqual(len(hosts_asked), 2, sid)
            self.assertGreaterEqual(len(set(hosts_asked)), 2, f"{sid} 要由不同的站確認")

    def test_empty_then_failure_is_failed_not_empty(self):
        """兩站說法對不上(一站空、一站失敗)→ failed,交給覆蓋率閘門與次日重抓。"""
        from radar.importer import _confirm_empties
        from radar.mirror_crawl import HostStats

        results = [{"sid": "A", "outcome": "empty", "rows": None, "host": "h1"},
                   {"sid": "B", "outcome": "empty", "rows": None, "host": "h1"},
                   {"sid": "C", "outcome": "done", "rows": [{"x": 1}], "host": "h2"}]
        stats = {"h1": HostStats(done=5), "h2": HostStats(done=5)}

        def fetch(sid, host, interval):
            self.assertEqual(host, "h2", "確認要到另一站")
            if sid == "A":
                raise RuntimeError("HTTP 500")
            from radar.providers import NoDataError
            raise NoDataError("still empty")

        tally = _confirm_empties(results, ["A", "B", "C"], stats, fetch, 0, None, None)
        self.assertEqual(tally, {"checked": 2, "recovered": 0, "confirmed": 1, "failed": 1})
        self.assertEqual(results[0]["outcome"], "failed")
        self.assertEqual(results[1]["outcome"], "empty")
        self.assertEqual(results[1]["confirmed_by"], ["h1", "h2"])
        self.assertEqual(results[2]["outcome"], "done")

    def test_single_live_host_confirms_on_itself_rather_than_not_at_all(self):
        from radar.importer import _confirm_empties
        from radar.mirror_crawl import HostStats

        results = [{"sid": "A", "outcome": "empty", "rows": None, "host": "h1"}]
        stats = {"h1": HostStats(done=5), "h2": HostStats(dead=True)}
        asked = []
        tally = _confirm_empties(results, ["A"], stats, lambda s, h, i: asked.append(h) or [{"x": 1}],
                                 0, None, None)
        self.assertEqual(asked, ["h1"])
        self.assertEqual(tally["recovered"], 1)
        self.assertEqual(results[0]["outcome"], "done")


class StageResumeRules(unittest.TestCase):
    """續抓只接「同一天、未完成、形狀正確」的暫存檔;其他一律當不存在、整份重爬。"""

    def _run_with_stage(self, stage_payload):
        calls = []
        with _Runner() as r, mock.patch.object(fubon, "get_text", side_effect=_http_stub(calls)):
            stage = r.dir / "stage.json"
            stage.write_text(json.dumps(stage_payload, ensure_ascii=False), encoding="utf-8")
            import io
            import contextlib
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                info = import_branch_trades(DATE_COMPACT, top=0, warrants=0, sleep_s=0,
                                            workers=5, stage_to=stage)
            return info, {c[0] for c in calls}, out.getvalue()

    def test_malformed_stage_is_ignored_with_a_warning_not_a_crash(self):
        """LOW(第二次驗證):結果缺 sid 以前會 KeyError,把兩輪都炸掉。"""
        bad = {"date": DATE, "complete": False, "targets": sorted(STOCKS),
               "expected": len(STOCKS),
               "results": [{"outcome": "done", "rows": []}, {"sid": "2001", "outcome": "weird"}]}
        info, fetched, out = self._run_with_stage(bad)
        self.assertEqual(info["resumed"], 0)
        self.assertEqual(fetched, set(STOCKS), "整份重爬")
        self.assertIn("malformed, ignored", out)

    def test_complete_stage_is_not_resumed_the_round_crawls_everything_again(self):
        """設計決定(docs/47 §8.2 第 3 點):已完成的暫存檔 = 那一輪抓完了。留下來的只會是
        不合格那一支,第二輪要做 main 上 22:30 的事——全部重爬,晚公布的才補得到。"""
        done = {"date": DATE, "complete": True, "targets": sorted(STOCKS),
                "expected": len(STOCKS),
                "results": [{"sid": sid, "outcome": "done", "rows": _rows_via_parser(sid)}
                            for sid in sorted(STOCKS)]}
        info, fetched, out = self._run_with_stage(done)
        self.assertEqual(info["resumed"], 0)
        self.assertEqual(fetched, set(STOCKS))
        self.assertIn("complete stage ignored", out)

    def test_other_days_stage_is_ignored(self):
        other = {"date": "2026-10-06", "complete": False, "targets": sorted(STOCKS),
                 "expected": len(STOCKS),
                 "results": [{"sid": sid, "outcome": "done", "rows": []} for sid in STOCKS]}
        info, fetched, _ = self._run_with_stage(other)
        self.assertEqual(info["resumed"], 0)
        self.assertEqual(fetched, set(STOCKS))


def _rows_via_parser(sid: str) -> list[dict]:
    """用真的解析器產生某檔的列(給「上一輪已抓到」的暫存檔用)。"""
    with mock.patch.object(fubon, "get_text", return_value=_page_for(sid)):
        return fubon.fetch_branch_trades(sid, DATE_COMPACT)


if __name__ == "__main__":
    unittest.main()
