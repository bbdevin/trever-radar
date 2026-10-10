# -*- coding: utf-8 -*-
"""個股 chips 的分點日史 ``branch_days`` v2(docs/44 §3.4;2026-10-10)。

釘住的契約:
  * **與 raw 逐列相等**:每檔每日 ``branch_trades_raw`` 的每一列(買、賣、淨)都在,不裁、不合併同名、
    不重排(branch_id 遞減);30 列/日的日子輸出 30 列(舊格式只剩 |淨額| 前 12 列)。
  * 淨張與買賣差不同的列(來源 net_lots 自己給的)解碼後仍等於 raw。
  * 日數上限 480、新→舊;名字表只含出現過的分點;``branch_tags`` 的名字範圍涵蓋全部列。
  * chips 檔 version 2、沒有 ``branch_history`` 鍵;舊 ``--legacy-stocks`` 單一檔同樣寫 ``branch_days``。
  * 緊湊格式真的比舊格式小:同一批列,v2(全部 30 列)< v1(前 12 列、逐列物件)。
"""
import json
import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import text

import radar.config as config
import radar.db as db
from radar import schema
from radar.export.branch_days import (
    BRANCH_DAYS_VERSION,
    MAX_DAYS,
    PER_SIDE,
    branch_history_of,
    decode_branch_days,
    encode_branch_days,
)
from radar.export.json_export import export_json
from radar.export.stock_parts import dumps_compact, read_merged_stock
from radar.importer import upsert_branch_trades

BROKERS = ["凱基", "元大", "富邦", "永豐金", "群益金鼎", "統一", "國泰", "華南永昌", "兆豐", "玉山"]
SITES = ["台北", "新竹", "板橋", "台中", "高雄", "松山", "敦南", "士林", "竹北", "三重"]


def _name(i: int) -> str:
    return f"{BROKERS[i % len(BROKERS)]}-{SITES[(i * 7) % len(SITES)]}{i // 100}"


def _dates(n: int, end: str) -> list[str]:
    last = date.fromisoformat(end)
    return [(last - timedelta(days=n - 1 - i)).isoformat() for i in range(n)]


class CodecTests(unittest.TestCase):
    def test_round_trip_keeps_every_row_in_order_and_net(self):
        rows = [
            ("2026-10-08", "A", 10, 0, 10),
            ("2026-10-08", "B", 0, 7, -7),
            ("2026-10-08", "A", 3, 0, 3),          # 同名第二列(另一個 branch_key),不合併
            ("2026-10-08", "C", 5, 2, 4),          # 來源 net ≠ 買−賣 → 第 4 欄
            ("2026-10-08", "D", None, None, None),  # NULL → 0
            ("2026-10-07", "B", 1, 0, 1),
        ]
        enc = encode_branch_days(rows)
        self.assertEqual(enc["version"], BRANCH_DAYS_VERSION)
        self.assertEqual(enc["per_side"], PER_SIDE)
        self.assertEqual(enc["names"], ["A", "B", "C", "D"])
        self.assertEqual(enc["days"][0], ["2026-10-08", [[0, 10, 0], [1, 0, 7], [0, 3, 0], [2, 5, 2, 4], [3, 0, 0]]])
        self.assertEqual(decode_branch_days(enc), [
            {"t": "2026-10-08", "branches": [
                {"n": "A", "b": 10, "s": 0, "net": 10}, {"n": "B", "b": 0, "s": 7, "net": -7},
                {"n": "A", "b": 3, "s": 0, "net": 3}, {"n": "C", "b": 5, "s": 2, "net": 4},
                {"n": "D", "b": 0, "s": 0, "net": 0}]},
            {"t": "2026-10-07", "branches": [{"n": "B", "b": 1, "s": 0, "net": 1}]},
        ])
        self.assertEqual(decode_branch_days(None), [])
        self.assertEqual(encode_branch_days([]), {"version": 2, "per_side": 15, "names": [], "days": []})

    def test_caps_at_max_days_newest_first(self):
        days = _dates(MAX_DAYS + 5, "2026-10-08")
        rows = [(d, "X", 1, 0, 1) for d in reversed(days)]
        enc = encode_branch_days(rows)
        self.assertEqual(len(enc["days"]), MAX_DAYS)
        self.assertEqual(enc["days"][0][0], "2026-10-08")
        self.assertEqual(enc["days"][-1][0], days[5])

    def test_branch_history_of_reads_both_generations(self):
        old = {"branch_history": [{"t": "2026-10-08", "branches": []}]}
        self.assertEqual(branch_history_of(old), old["branch_history"])
        new = {"branch_days": encode_branch_days([("2026-10-08", "A", 1, 0, 1)])}
        self.assertEqual(branch_history_of(new)[0]["branches"][0]["n"], "A")
        self.assertEqual(branch_history_of({}), [])


class ExportParityTests(unittest.TestCase):
    """種子 DB:2464 每天 15 買 + 15 賣(其中一天 15 列全是賣超,模擬 10/08 的盟立);2476 每天 6+6;
    另加同名兩個 branch_key 同日、來源 net ≠ 買−賣、共 482 個交易日(超過 480 上限)。"""

    D = "2026-10-08"

    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._old = (config.DB_URL, config.DATA_DIR)
        config.DATA_DIR = tmp
        config.DB_URL = "sqlite:///" + (tmp / "t.db").as_posix()
        db._engine = None
        db.init_db()
        self.days = _dates(482, self.D)
        trades = []
        for di, day in enumerate(self.days):
            if day == self.D:
                # 一邊倒的日子:15 列全是賣超(舊格式 12 列全賣 → 買超名單空白)
                for i in range(15):
                    trades.append(self._trade("2464", day, f"s{i}", _name(i), 0, 500 - i * 7))
            else:
                for i in range(15):
                    trades.append(self._trade("2464", day, f"b{i}", _name(i), 300 - i * 11 + di % 5, 0))
                    trades.append(self._trade("2464", day, f"s{i}", _name(20 + i), 0, 280 - i * 9 + di % 3))
            for i in range(6):
                trades.append(self._trade("2476", day, f"b{i}", _name(40 + i), 120 - i * 10, 0))
                trades.append(self._trade("2476", day, f"s{i}", _name(50 + i), 0, 110 - i * 9))
        # 同名兩個 branch_key 同一天(改名合併);來源 net 與買賣差不同
        trades.append(self._trade("2476", self.D, "dup1", "凱基-台北", 40, 0))
        trades.append(self._trade("2476", self.D, "dup2", "凱基-台北", 25, 0))
        trades.append({"stock_id": "2476", "date": self.D, "branch_key": "odd", "branch_name": "怪怪-分點",
                       "buy_lots": 10, "sell_lots": 4, "net_lots": 5, "pct": 0.1})
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": "2464", "name": "盟立", "market": "twse", "type": "stock", "is_active": 1},
                {"id": "2476", "name": "鉅祥", "market": "twse", "type": "stock", "is_active": 1},
            ])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": sid, "date": day, "open": 50.0, "high": 51.0, "low": 49.0, "close": 50.0,
                 "volume": 1_000_000, "turnover": 50_000_000}
                for sid in ("2464", "2476") for day in self.days
            ])
            upsert_branch_trades(conn, trades)

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old
        self._tmp.cleanup()

    @staticmethod
    def _trade(sid, day, key, name, buy, sell):
        return {"stock_id": sid, "date": day, "branch_key": key, "branch_name": name,
                "buy_lots": buy, "sell_lots": sell, "net_lots": buy - sell, "pct": 0}

    def _raw(self, conn, sid):
        rows = conn.execute(text("""
            SELECT r.date, d.branch_name, r.buy_lots, r.sell_lots, r.net_lots
            FROM branch_trades_raw r JOIN branch_dim d ON r.branch_id = d.id
            WHERE r.stock_id = :s ORDER BY r.date DESC, r.branch_id DESC
        """), {"s": sid}).fetchall()
        by_date: dict[str, list] = {}
        for r in rows:
            by_date.setdefault(r[0], []).append({"n": r[1], "b": r[2] or 0, "s": r[3] or 0, "net": r[4] or 0})
        return by_date

    def test_export_matches_raw_row_for_row(self):
        out = Path(self._tmp.name) / "out"
        export_json(out, legacy_stocks=True)
        with db.get_engine().connect() as conn:
            for sid in ("2464", "2476"):
                raw = self._raw(conn, sid)
                merged = read_merged_stock(out / "stocks", sid)
                chips = json.loads((out / "stocks" / "chips" / f"{sid}.json").read_text(encoding="utf-8"))
                self.assertEqual(chips["version"], 2)
                self.assertNotIn("branch_history", chips)
                self.assertEqual(chips["branch_days"], merged["branch_days"])
                hist = branch_history_of(merged)
                # 480 天上限、新→舊
                self.assertEqual(len(hist), 480)
                self.assertEqual(hist[0]["t"], self.D)
                self.assertEqual([h["t"] for h in hist], sorted(raw)[::-1][:480])
                for day in hist:
                    self.assertEqual(day["branches"], raw[day["t"]], f"{sid} {day['t']}")
                # 名字表只含出現過的分點;branch_tags 名字範圍涵蓋全部
                names = {b["n"] for d in hist for b in d["branches"]}
                self.assertEqual(set(merged["branch_days"]["names"]), names)
                # 舊單一檔(逃生口)寫的是同一份 branch_days
                legacy = json.loads((out / "stocks" / f"{sid}.json").read_text(encoding="utf-8"))
                self.assertEqual(legacy["branch_days"], merged["branch_days"])
                self.assertNotIn("branch_history", legacy)

            # 2464 10/08:15 列全賣超都在(舊格式 12 列全賣、買超空白;前一天 30 列)
            h2464 = branch_history_of(read_merged_stock(out / "stocks", "2464"))
            self.assertEqual(len(h2464[0]["branches"]), 15)
            self.assertTrue(all(b["net"] < 0 for b in h2464[0]["branches"]))
            self.assertEqual(len(h2464[1]["branches"]), 30)
            self.assertEqual(sum(1 for b in h2464[1]["branches"] if b["net"] > 0), 15)
            self.assertEqual(sum(1 for b in h2464[1]["branches"] if b["net"] < 0), 15)
            # 2476 10/08:6+6 + 同名兩列(不合併)+ 來源 net ≠ 買−賣 的列原值
            d0 = branch_history_of(read_merged_stock(out / "stocks", "2476"))[0]
            self.assertEqual(len(d0["branches"]), 15)
            self.assertEqual([b for b in d0["branches"] if b["n"] == "凱基-台北"],
                             [{"n": "凱基-台北", "b": 25, "s": 0, "net": 25}, {"n": "凱基-台北", "b": 40, "s": 0, "net": 40}])
            self.assertIn({"n": "怪怪-分點", "b": 10, "s": 4, "net": 5}, d0["branches"])
            # 當日 branches(完整當日列)與 branch_days 第一天是同一批列
            p2476 = read_merged_stock(out / "stocks", "2476")
            self.assertEqual(sorted((b["name"], b["buy"], b["sell"], b["net"]) for b in p2476["branches"]),
                             sorted((b["n"], b["b"], b["s"], b["net"]) for b in d0["branches"]))

    def test_compact_v2_is_smaller_than_legacy_v1_even_with_all_rows(self):
        """同一批列:v2(全部列)比 v1(|淨額| 前 12 列、逐列物件)小。數字進 docs/44 §3.4。"""
        with db.get_engine().connect() as conn:
            rows = conn.execute(text("""
                SELECT r.date, d.branch_name, r.buy_lots, r.sell_lots, r.net_lots
                FROM branch_trades_raw r JOIN branch_dim d ON r.branch_id = d.id
                WHERE r.stock_id = '2464' ORDER BY r.date DESC, r.branch_id DESC
            """)).fetchall()
        by_date: dict[str, list] = {}
        for r in rows:
            by_date.setdefault(r[0], []).append({"n": r[1], "b": r[2] or 0, "s": r[3] or 0, "net": r[4] or 0})
        v1 = [{"t": dt, "branches": sorted(bs, key=lambda x: -abs(x["net"]))[:12]}
              for dt, bs in sorted(by_date.items(), reverse=True)[:480]]
        v2 = encode_branch_days(rows)
        v1_bytes = len(dumps_compact(v1).encode("utf-8"))
        v2_bytes = len(dumps_compact(v2).encode("utf-8"))
        self.assertEqual(sum(len(d["branches"]) for d in v1), 12 * 479 + 12)   # 舊格式每天只剩 12 列
        self.assertEqual(sum(len(r) for _, r in v2["days"]), 30 * 479 + 15)      # v2 全部
        self.assertLess(v2_bytes, v1_bytes)


if __name__ == "__main__":
    unittest.main()
