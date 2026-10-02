"""`lookup` 的大小上限(json_export._branch_pctile_payload,2026-10-02)。

上限是為了 JSON 大小加的:全收時每檔平均約 470 個分點。驗證者抓到兩個破口,
這裡把它們釘住:
  1. 在某一派清單裡、另一派沒入選的分點,另一派的數字**只能**從 lookup 來;被上限
     擠掉時,畫面把「有紀錄」講成「沒有紀錄」。
  2. 舊快照(張數欄 NULL)時權重全為 1,上限退化成「依名稱取前 150」。
"""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from radar import config, db, schema
from radar.export import json_export as je

KEYS = ("buy_pctile_known", "low_buy_count", "sell_pctile_known", "high_sell_count",
        "buy_lots_known", "low_buy_lots", "sell_lots_known", "high_sell_lots")
STOCK = {"stock_buy_pctile_known": 1000, "stock_low_buy_count": 400,
         "stock_sell_pctile_known": 1000, "stock_high_sell_count": 350,
         "stock_buy_lots_known": 100000, "stock_low_buy_lots": 30000,
         "stock_sell_lots_known": 100000, "stock_high_sell_lots": 30000}


def _row(name, short, long):
    r = {"stock_id": "1111", "branch_name": name, "as_of": "2026-08-05",
         "window_market_days": 490, "window_from": "2024-08-01",
         "definitions_version": "x", "computed_at": "t",
         "buy_pctile_unknown": 0, "sell_pctile_unknown": 0,
         "buy_pctile_unknown_120d": 0, "sell_pctile_unknown_120d": 0,
         "daytrade_obs": 0, "daytrade_paybacks": 0,
         "stock_daytrade_obs": 0, "stock_daytrade_paybacks": 0}
    r.update(STOCK)
    r.update({k + "_120d": v for k, v in STOCK.items()})
    r.update(zip(KEYS, short))
    r.update({k + "_120d": v for k, v in zip(KEYS, long)})
    return r


class LookupCapTests(unittest.TestCase):
    def setUp(self):
        self._saved = (config.DB_URL, config.DATA_DIR, db._engine)
        self._tmp = TemporaryDirectory()
        config.DB_URL = "sqlite:///" + (Path(self._tmp.name) / "e.db").as_posix()
        config.DATA_DIR = Path(self._tmp.name)
        db._engine = None
        db.init_db()

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        config.DB_URL, config.DATA_DIR, db._engine = self._saved
        self._tmp.cleanup()

    def _payload(self, rows):
        with db.get_engine().begin() as conn:
            conn.execute(schema.branch_stock_pctile_counts.insert(), rows)
        with db.get_engine().connect() as conn:
            meta = je._branch_pctile_snapshot_meta(conn)
            return je._branch_pctile_payload(conn, "1111", meta, True)

    def test_cap_keeps_heaviest_and_drops_single_record_branches(self):
        rows = [_row(f"S{i:03d}", (2, 0, 10, 3, 1000 + i, 0, 5000 + i * 10, 1500),
                     (2, 0, 10, 3, 1000 + i, 0, 5000 + i * 10, 1500)) for i in range(200)]
        rows.append(_row("ONE", (1, 1, 1, 1, 99999, 99999, 99999, 99999),
                         (1, 1, 1, 1, 99999, 99999, 99999, 99999)))
        names = [e[0] for e in self._payload(rows)["lookup"]]
        self.assertEqual(len(names), je.BRANCH_PCTILE_LOOKUP_MAX)
        self.assertEqual(names, sorted(names))
        self.assertNotIn("ONE", names, "只有 1 次紀錄的分點不收,無論張數多大")
        self.assertIn("S199", names)
        self.assertNotIn("S000", names, "依可見張數取前 N,最輕的被擠掉")

    def test_a_branch_ranked_in_one_camp_is_never_capped_out(self):
        rows = [_row(f"S{i:03d}", (2, 0, 10, 3, 1000 + i, 0, 5000 + i * 10, 1500),
                     (2, 0, 10, 3, 1000 + i, 0, 5000 + i * 10, 1500)) for i in range(200)]
        rows.append(_row("RANKSHORT", (5, 5, 0, 0, 50, 50, 0, 0), (4, 2, 0, 0, 400, 200, 0, 0)))
        payload = self._payload(rows)
        self.assertIn("RANKSHORT", [b["branch_name"] for b in payload["short"]["branches"]])
        self.assertNotIn("RANKSHORT", [b["branch_name"] for b in payload["long"]["branches"]])
        entry = next((e for e in payload["lookup"] if e[0] == "RANKSHORT"), None)
        self.assertIsNotNone(entry, "長線派的數字只能從 lookup 來,不得被上限擠掉")
        long_buy_known = entry[1 + len(KEYS)]
        self.assertEqual(long_buy_known, 4)

    def test_legacy_snapshot_weights_by_episodes_not_by_name(self):
        rows = []
        for i in range(200):
            r = _row(f"L{i:03d}", (2, 0, 2 + i, 1, None, None, None, None), (None,) * 8)
            for k in list(r):
                if k.endswith("_120d") or "lots" in k:
                    r[k] = None
            rows.append(r)
        names = [e[0] for e in self._payload(rows)["lookup"]]
        self.assertIn("L199", names, "賣出紀錄最多的不得因名稱排後面被丟掉")
        self.assertNotIn("L000", names)


if __name__ == "__main__":
    unittest.main()
