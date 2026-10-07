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


def _http_stub(calls: list):
    """只 mock HTTP:解析仍走 fubon._ROW。TRANSIENT 那一檔第一次拋錯。"""
    seen: dict[str, int] = {}

    def get_text(url, params=None, encoding="big5", throttle=None, throttle_key=None):
        sid = params["a"]
        host = url.split("/z/")[0]
        calls.append((sid, host, throttle, throttle_key))
        seen[sid] = seen.get(sid, 0) + 1
        if sid == TRANSIENT and seen[sid] == 1:
            raise RuntimeError("transient reset")
        if sid in EMPTY:
            return "<html>no rows today</html>"
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
        # 每檔的請求數與循序爬相同:1 次,TRANSIENT 2 次(重試),加上開跑前每站 6 檔的公布檢查。
        from radar.importer import BRANCH_MIRROR_CHECK_SAMPLE
        per_sid = {}
        for sid, *_ in calls:
            per_sid[sid] = per_sid.get(sid, 0) + 1
        check = BRANCH_MIRROR_CHECK_SAMPLE * len(fubon.MIRROR_HOSTS)
        self.assertEqual(sum(per_sid.values()), len(STOCKS) + 1 + check)

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


if __name__ == "__main__":
    unittest.main()
