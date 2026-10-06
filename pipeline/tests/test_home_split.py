# -*- coding: utf-8 -*-
"""docs/44 P2 首頁拆檔:home/head.json + home/stocks.json 是 radar.json 的投影。

純函式:只丟不加、鍵序不變、warrant 只留三鍵、接回 == 投影、generated_at 對不上擲例外。
種子 DB 匯出:radar.json 逐位元不受影響、home 兩檔寫出且接回 == 投影、緊湊序列化、
stocks 先寫 head 後寫。鍵名清單與前端 web/lib/homeLoad.ts 一致。
"""
import json
import os
import re
import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import radar.config as config
import radar.db as db
from radar import schema
from radar.export import home_split
from radar.export.home_split import (
    HOME_DROPPED_STOCK,
    HOME_DROPPED_TOP,
    HOME_WARRANT_KEYS,
    home_projection,
    home_stock,
    merge_home,
    split_home,
    write_home,
)
from radar.export.json_export import export_json

REPO = Path(__file__).resolve().parents[2]


def _stock(sid: str = "2330", **extra) -> dict:
    s = {
        "id": sid, "name": "台積電", "market": "twse", "industry": "半導體",
        "description": "晶圓代工", "close": 1000.0, "chg_pct": 1.5, "chg5_pct": 3.2,
        "turnover": 5e10, "volume_lots": 30000, "volume_ratio": 1.2, "transactions": 50000,
        "foreign_net_lots": 1200, "trust_net_lots": -30, "margin_chg_lots": 15,
        "warrant": {
            "call_turnover": 1e8, "call_volume": 1000, "call_count": 120,
            "put_turnover": 2e7, "put_volume": 300, "put_count": 40,
            "call_avg20": 8e7, "call_turnover_ratio": 1.25, "put_call_ratio": 0.2,
        },
        "technical": {"score": 60, "ma20": 990.0, "ma60": 950.0, "rsi14": 61.0,
                      "volume_ratio": 1.2, "reasons": [{"code": "T1", "text": "站上月線"}],
                      "risks": []},
        "scores": {"final": 70, "branch": 20, "warrant": 10, "tech": 20, "inst": 10,
                   "theme": 10, "risk_penalty": 0, "watch_price": 1010.0, "stop_price": 960.0},
        "state": "armed", "sources": ["branch"],
        "reasons": ["分點集中"], "raw_reasons": [{"code": "S12_BRANCH_ACCUMULATION", "text": "分點集中", "points": 20}],
        "strategy_signals": [], "risks": [], "spark": [1.0, 2.0], "spark_day": [1.0, 1.1], "spark_open": 1.0,
        "themes": ["AI"], "pocket_tags": [{"code": "H1_HOT_THEME", "text": "題材"}],
        "pocket_score": 2, "pocket_families": ["theme"],
    }
    s.update(extra)
    return s


def _radar(**extra) -> dict:
    r = {
        "data_date": "2026-10-06", "generated_at": "2026-10-06T17:40:00+08:00",
        "freshness": {"quotes": {"date": "2026-10-06", "stale": False}},
        "note": "n", "pocket_note": "p", "summary_text": ["s"],
        "summary": [{"market": "twse", "turnover": 1.0, "up": 1, "down": 0}],
        "sectors": [{"name": "半導體", "turnover": 1.0, "share": 1.0, "vs20": 1.1, "avg_chg": 1.0, "up": 1, "down": 0, "top": []}],
        "themes": [], "concentration": [{"id": "2330", "vs20": 2.0}],
        "lists": {"score": ["2330"], "hot": ["2330"], "armed": ["2330"]},
        "score_list_meta": {"withheld": False},
        "strategies": {"S12_BRANCH_ACCUMULATION": ["2330"]},
        "strategy_meta": {}, "stocks": [_stock(), _stock("2317", warrant=None, scores=None, state=None)],
        "futures_volume_anomalies": [],
    }
    r.update(extra)
    return r


class ProjectionTests(unittest.TestCase):
    def test_home_stock_drops_only_listed_keys_and_keeps_order(self):
        s = _stock()
        h = home_stock(s)
        for k in HOME_DROPPED_STOCK:
            self.assertIn(k, s)
            self.assertNotIn(k, h)
        kept = [k for k in s if k not in HOME_DROPPED_STOCK]
        self.assertEqual(list(h), kept)
        for k in kept:
            if k != "warrant":
                self.assertIs(h[k], s[k], k)  # 同一個物件:值連 round 都沒動
        self.assertEqual(h["warrant"], {k: s["warrant"][k] for k in HOME_WARRANT_KEYS})
        self.assertEqual(list(h["warrant"]), list(HOME_WARRANT_KEYS))
        # 原 stock 沒被改到
        self.assertIn("technical", s)
        self.assertIn("put_turnover", s["warrant"])

    def test_warrant_none_and_missing_optional_keys(self):
        s = _stock(warrant=None)
        del s["spark_day"]
        del s["pocket_tags"]
        h = home_stock(s)
        self.assertIsNone(h["warrant"])
        self.assertNotIn("spark_day", h)
        self.assertNotIn("pocket_tags", h)
        # 權證缺鍵時不發明鍵
        s2 = _stock(warrant={"call_turnover": 1.0, "call_count": 2})
        self.assertEqual(home_stock(s2)["warrant"], {"call_turnover": 1.0, "call_count": 2})

    def test_split_then_merge_equals_projection(self):
        r = _radar()
        head, stocks_file = split_home(r)
        self.assertEqual(head["version"], 1)
        self.assertEqual(stocks_file["version"], 1)
        self.assertEqual(stocks_file["generated_at"], r["generated_at"])
        self.assertEqual(stocks_file["data_date"], r["data_date"])
        for k in HOME_DROPPED_TOP:
            self.assertIn(k, r)
            self.assertNotIn(k, head)
        self.assertNotIn("stocks", head)
        # head 其餘鍵:同一個物件、同鍵序
        self.assertEqual(list(head)[1:], [k for k in r if k != "stocks" and k not in HOME_DROPPED_TOP])
        for k in list(head)[1:]:
            self.assertIs(head[k], r[k])
        merged = merge_home(head, stocks_file)
        proj = home_projection(r)
        self.assertEqual(merged, proj)
        # 鍵集合相同;順序只差 stocks 被放到最後(radar.json 裡 futures_* 是在 stocks 之後補上的)
        self.assertEqual(set(merged), set(proj))
        self.assertEqual(list(merged)[:-1], [k for k in proj if k != "stocks"])
        self.assertEqual([s["id"] for s in merged["stocks"]], [s["id"] for s in r["stocks"]])
        # 投影只少不多:每一個留下來的值都與 radar 相同
        for k, v in proj.items():
            if k != "stocks":
                self.assertEqual(v, r[k])
        for ps, rs in zip(proj["stocks"], r["stocks"]):
            for k, v in ps.items():
                if k == "warrant" and isinstance(v, dict):
                    self.assertEqual(v, {wk: rs["warrant"][wk] for wk in HOME_WARRANT_KEYS if wk in rs["warrant"]})
                else:
                    self.assertEqual(v, rs[k])
        # radar 本身沒被改到
        self.assertIn("concentration", r)
        self.assertIn("technical", r["stocks"][0])

    def test_merge_refuses_different_rounds(self):
        head, stocks_file = split_home(_radar())
        stocks_file["generated_at"] = "2026-10-06T22:00:00+08:00"
        with self.assertRaises(ValueError):
            merge_home(head, stocks_file)

    def test_write_home_is_compact_and_versioned(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            sizes = write_home(out, _radar())
            head_text = (out / "home" / "head.json").read_text(encoding="utf-8")
            stocks_text = (out / "home" / "stocks.json").read_text(encoding="utf-8")
            self.assertTrue(head_text.startswith('{"version":1,'))
            self.assertTrue(stocks_text.startswith('{"version":1,'))
            self.assertNotIn(": ", head_text)
            self.assertEqual(sizes, {"head": len(head_text.encode("utf-8")),
                                     "stocks": len(stocks_text.encode("utf-8"))})
            self.assertEqual(sorted(p.name for p in (out / "home").iterdir()), ["head.json", "stocks.json"])

    def test_write_order_stocks_before_head(self):
        """stocks 先落地、head 最後(兩個都是 tmp+rename)。"""
        order: list[str] = []
        real = home_split.write_atomic

        def spy(path, text):
            order.append(path.name)
            real(path, text)

        home_split.write_atomic = spy
        try:
            with TemporaryDirectory() as tmp:
                write_home(Path(tmp), _radar())
        finally:
            home_split.write_atomic = real
        self.assertEqual(order, ["stocks.json", "head.json"])

    def test_frontend_mirror_of_key_lists(self):
        """web/lib/homeLoad.ts 的清單必須與這裡一致(前端靠它知道哪些欄位不會在 home 檔裡)。"""
        ts = (REPO / "web" / "lib" / "homeLoad.ts").read_text(encoding="utf-8")

        def ts_list(name: str) -> list[str]:
            m = re.search(rf"export const {name}\s*=\s*\[([^\]]*)\]", ts)
            self.assertIsNotNone(m, name)
            return re.findall(r'"([^"]+)"', m.group(1))

        self.assertEqual(ts_list("HOME_DROPPED_STOCK"), list(HOME_DROPPED_STOCK))
        self.assertEqual(ts_list("HOME_DROPPED_TOP"), list(HOME_DROPPED_TOP))
        self.assertEqual(ts_list("HOME_WARRANT_KEYS"), list(HOME_WARRANT_KEYS))
        self.assertIn('"/data/home/head.json"', ts)
        self.assertIn('"/data/home/stocks.json"', ts)


def _dates(n: int, end: str) -> list[str]:
    last = date.fromisoformat(end)
    return [(last - timedelta(days=n - 1 - i)).isoformat() for i in range(n)]


class ExportHomeTests(unittest.TestCase):
    """種子 DB(同 test_stock_parts):2330 進熱門榜 → radar.stocks 有一檔。"""

    D = "2026-07-09"

    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._old = (config.DB_URL, config.DATA_DIR)
        config.DATA_DIR = tmp
        config.DB_URL = "sqlite:///" + (tmp / "t.db").as_posix()
        db._engine = None
        db.init_db()
        days = _dates(60, self.D)
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": "2330", "name": "台積電", "market": "twse", "type": "stock", "industry": "半導體", "is_active": 1},
                {"id": "2317", "name": "鴻海", "market": "twse", "type": "stock", "industry": "電子", "is_active": 1},
            ])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": "2330", "date": day, "open": 100.0 + i % 7, "high": 101.0 + i % 7,
                 "low": 99.0 + i % 7, "close": 100.0 + i % 7, "volume": 5_000_000, "turnover": 200_000_000}
                for i, day in enumerate(days)
            ])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": "2317", "date": day, "open": 50.0, "high": 51.0, "low": 49.0,
                 "close": 50.0, "volume": 1_000_000, "turnover": None}
                for day in days
            ])

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old
        self._tmp.cleanup()

    def test_export_writes_home_files_that_merge_to_projection(self):
        out = Path(self._tmp.name) / "out"
        info = export_json(out)
        radar_text = (out / "radar.json").read_text(encoding="utf-8")
        radar = json.loads(radar_text)
        # radar.json 本尊:與改動前同一條序列化(有空白、ensure_ascii=False)、仍帶被投影丟掉的鍵
        self.assertEqual(radar_text, json.dumps(radar, ensure_ascii=False))
        self.assertIn("concentration", radar)
        self.assertIn("2330", [s["id"] for s in radar["stocks"]])
        self.assertIn("technical", radar["stocks"][0])
        self.assertIn("volume_lots", radar["stocks"][0])

        head = json.loads((out / "home" / "head.json").read_text(encoding="utf-8"))
        stocks_file = json.loads((out / "home" / "stocks.json").read_text(encoding="utf-8"))
        self.assertEqual(head["generated_at"], radar["generated_at"])
        self.assertEqual(stocks_file["generated_at"], radar["generated_at"])
        self.assertEqual(merge_home(head, stocks_file), home_projection(radar))
        for s in stocks_file["stocks"]:
            for k in HOME_DROPPED_STOCK:
                self.assertNotIn(k, s)
        self.assertEqual(info["home_bytes"]["head"],
                         len((out / "home" / "head.json").read_bytes()))
        # 沒有殘留的 tmp 檔
        self.assertFalse([p for p in (out / "home").iterdir() if ".tmp-" in p.name])
        self.assertEqual(os.listdir(out / "home").__len__(), 2)


if __name__ == "__main__":
    unittest.main()
