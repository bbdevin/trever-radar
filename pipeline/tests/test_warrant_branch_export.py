"""Contract tests for the separate stock-detail warrant branch payload."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import radar.config as config
import radar.db as db
from radar import schema
from radar.export.json_export import export_json
from radar.importer import upsert_branch_trades


class WarrantBranchDetailExportTests(unittest.TestCase):
    """100–499 萬 is stock-detail-only; /branch remains at 500 萬."""

    DATES = ("2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07")

    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._old_url, self._old_dir = config.DB_URL, config.DATA_DIR
        config.DATA_DIR = tmp
        config.DB_URL = "sqlite:///" + (tmp / "t.db").as_posix()
        db._engine = None
        db.init_db()
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": "2330", "name": "台積電", "market": "twse", "type": "stock", "is_active": 1},
                {"id": "2317", "name": "鴻海", "market": "twse", "type": "stock", "is_active": 1},
            ])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": stock_id, "date": day, "close": 1000.0, "volume": 1000, "turnover": 1}
                for stock_id in ("2330", "2317") for day in self.DATES
            ])
            conn.execute(schema.warrants.insert(), [
                {"id": warrant_id, "name": name, "market": "twse", "kind": kind, "stock_id": stock_id}
                for warrant_id, name, stock_id, kind in (
                    ("123456", "兩百萬購", "2330", "call"),
                    ("123457", "六百萬購", "2330", "call"),
                    ("123458", "五十萬購", "2317", "call"),
                    ("123459", "七百萬售", "2330", "put"),
                )
            ])
            conn.execute(schema.warrant_daily.insert(), [
                {"warrant_id": warrant_id, "date": self.DATES[-1], "close": 10.0, "volume": 1, "turnover": 1}
                for warrant_id in ("123456", "123457", "123458", "123459")
            ])
            # Amount = net_lots × 1,000 × close: +200/+600/+50/-700 萬。
            upsert_branch_trades(conn, [
                {"stock_id": "123456", "date": self.DATES[-1], "branch_key": "two", "branch_name": "兩百萬分點", "buy_lots": 200, "sell_lots": 0, "net_lots": 200, "pct": 0},
                {"stock_id": "123457", "date": self.DATES[-1], "branch_key": "six", "branch_name": "六百萬分點", "buy_lots": 600, "sell_lots": 0, "net_lots": 600, "pct": 0},
                {"stock_id": "123458", "date": self.DATES[-1], "branch_key": "half", "branch_name": "五十萬分點", "buy_lots": 50, "sell_lots": 0, "net_lots": 50, "pct": 0},
                {"stock_id": "123459", "date": self.DATES[-1], "branch_key": "seven_sell", "branch_name": "七百萬賣超分點", "buy_lots": 0, "sell_lots": 700, "net_lots": -700, "pct": 0},
            ])

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old_url, self._old_dir
        self._tmp.cleanup()

    def test_detail_threshold_does_not_widen_market_payload(self):
        out = Path(self._tmp.name) / "out"
        detail_dir = out / "branches" / "warrant-stock-details"
        detail_dir.mkdir(parents=True)
        (detail_dir / "stale.json").write_text("old shard", encoding="utf-8")
        export_json(out)
        payload = json.loads((out / "branches" / "warrant_branches.json").read_text(encoding="utf-8"))
        index = json.loads((detail_dir / "index.json").read_text(encoding="utf-8"))
        detail = json.loads((detail_dir / "2330.json").read_text(encoding="utf-8"))

        # 全市場檔為 v1 wrapper,並自報同一個分點資料日。
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["threshold"], 5_000_000)
        self.assertEqual(payload["data_date"], self.DATES[-1])
        market = payload["timeframes"]

        self.assertEqual(index, {
            "version": 1, "threshold": 1_000_000, "data_date": self.DATES[-1], "stocks": ["2330"],
        })
        self.assertFalse((detail_dir / "2317.json").exists())
        self.assertFalse((detail_dir / "stale.json").exists())

        # One-day values carry into each available aggregation window. Every
        # Shard timeframe uses absolute-value thresholds and ordering: -700萬,
        # +600萬 and +200萬 appear in absolute descending order; <1M drops.
        for timeframe in ("1d", "2d", "5d", "30d", "120d"):
            self.assertEqual(
                [row["branch_name"] for row in detail["timeframes"][timeframe]],
                ["七百萬賣超分點", "六百萬分點", "兩百萬分點"],
            )
            self.assertEqual(
                [row["branch_name"] for row in market[timeframe]],
                ["七百萬賣超分點", "六百萬分點"],
            )
            self.assertEqual([row["net_amount"] for row in market[timeframe]], [-7_000_000, 6_000_000])
            self.assertEqual(
                [row["net_amount"] for row in detail["timeframes"][timeframe]],
                [-7_000_000, 6_000_000, 2_000_000],
            )
            self.assertNotIn("五十萬分點", [row["branch_name"] for row in detail["timeframes"][timeframe]])

    def test_data_date_and_windows_follow_branch_trades_not_price_date(self):
        """分點比報價晚一輪時,資料日必須是實際分點日,1d 桶不可被清空。"""
        lead = "2026-08-10"  # 只有報價、沒有分點的較新交易日
        with db.get_engine().begin() as conn:
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": stock_id, "date": lead, "close": 1000.0, "volume": 1000, "turnover": 1}
                for stock_id in ("2330", "2317")
            ])
        out = Path(self._tmp.name) / "out"
        out.mkdir(parents=True, exist_ok=True)
        export_json(out)
        detail_dir = out / "branches" / "warrant-stock-details"
        index = json.loads((detail_dir / "index.json").read_text(encoding="utf-8"))
        detail = json.loads((detail_dir / "2330.json").read_text(encoding="utf-8"))

        market = json.loads((out / "branches" / "warrant_branches.json").read_text(encoding="utf-8"))
        self.assertEqual(index["data_date"], self.DATES[-1])
        self.assertEqual(detail["data_date"], self.DATES[-1])
        self.assertEqual(market["data_date"], self.DATES[-1])
        self.assertEqual(
            [row["branch_name"] for row in detail["timeframes"]["1d"]],
            ["七百萬賣超分點", "六百萬分點", "兩百萬分點"],
        )

    def _export_detail(self):
        out = Path(self._tmp.name) / "out"
        out.mkdir(parents=True, exist_ok=True)
        export_json(out)
        return json.loads((out / "branches" / "warrant-stock-details" / "2330.json")
                          .read_text(encoding="utf-8"))

    def test_daily_series_sums_to_the_window_total_and_leaves_gaps(self):
        """逐日序列(2026-10-02):對齊 K 線畫券商每天的權證買賣超金額。

        08-04 再買 100 張(收盤 10 元 → +100 萬);08-05、08-06 沒有列——那兩天
        該券商不在前 15 大,**不是 0**,序列裡就不該有那兩天。
        """
        with db.get_engine().begin() as conn:
            conn.execute(schema.warrant_daily.insert(), [
                {"warrant_id": "123456", "date": self.DATES[1], "close": 10.0,
                 "volume": 1, "turnover": 1}])
            upsert_branch_trades(conn, [
                {"stock_id": "123456", "date": self.DATES[1], "branch_key": "two",
                 "branch_name": "兩百萬分點", "buy_lots": 100, "sell_lots": 0,
                 "net_lots": 100, "pct": 0}])
        detail = self._export_detail()
        # [日期, 認購金額, 認售金額]:方向相反的兩種權證分開放(買認售是看空)。
        series = detail["daily"]["兩百萬分點"]
        self.assertEqual(series, [[self.DATES[1], 1_000_000, 0], [self.DATES[-1], 2_000_000, 0]])
        total_120d = next(r["net_amount"] for r in detail["timeframes"]["120d"]
                          if r["branch_name"] == "兩百萬分點")
        self.assertEqual(sum(c + p for _, c, p in series), total_120d)
        self.assertEqual(detail["daily"]["七百萬賣超分點"], [[self.DATES[-1], 0, -7_000_000]])
        self.assertEqual(detail["daily_from"], self.DATES[0])

    def test_every_listed_branch_has_a_series_so_search_can_chart_it(self):
        """「搜尋券商」要能畫任何一家:分片裡每一家(≥ 100 萬)都有序列。

        實測 6488 共 61 家、逐日資料 60 KB,遠小於既有區間明細(674 KB)。
        沒進分片的(< 100 萬)就沒有序列——它也不會出現在任何清單裡。
        """
        with db.get_engine().begin() as conn:
            upsert_branch_trades(conn, [
                {"stock_id": "123456", "date": self.DATES[-1], "branch_key": f"x{i}",
                 "branch_name": f"小買家{i:02d}", "buy_lots": 150 + i, "sell_lots": 0,
                 "net_lots": 150 + i, "pct": 0}
                for i in range(12)])
        detail = self._export_detail()
        listed = {r["branch_name"] for rows in detail["timeframes"].values() for r in rows}
        self.assertEqual(set(detail["daily"]), listed)
        self.assertEqual(len(listed), 15)              # 3 家既有 + 12 家小買家
        self.assertNotIn("五十萬分點", detail["daily"])

    def test_branch_codes_are_decoded_for_the_code_column(self):
        """參考圖的「代號」欄。含英文字母的代號存成 UTF-16BE 十六進位。"""
        from radar.export.json_export import _branch_code
        self.assertEqual(_branch_code("7001"), "7001")
        self.assertEqual(_branch_code("0039004100390058"), "9A9X")
        self.assertEqual(_branch_code("0039004200320030"), "9B20")
        self.assertEqual(_branch_code("0039004100390067"), "9A9G")   # 來源是小寫 g
        self.assertIsNone(_branch_code(None))
        self.assertIsNone(_branch_code(""))
        detail = self._export_detail()
        self.assertEqual(detail["branch_codes"]["兩百萬分點"], "two")

    def test_breakdown_is_split_into_one_extra_file_per_stock(self):
        """排行留在分片、逐檔明細搬到 {id}.breakdown.json(第一屏只需要排行)。"""
        out = Path(self._tmp.name) / "out"
        out.mkdir(parents=True, exist_ok=True)
        export_json(out)
        detail_dir = out / "branches" / "warrant-stock-details"
        detail = json.loads((detail_dir / "2330.json").read_text(encoding="utf-8"))
        split = json.loads((detail_dir / "2330.breakdown.json").read_text(encoding="utf-8"))

        self.assertIs(detail["breakdown_split"], True)
        for rows in detail["timeframes"].values():
            for row in rows:
                self.assertNotIn("breakdown", row)
        self.assertEqual(split["version"], 1)
        self.assertEqual(split["data_date"], detail["data_date"])
        self.assertEqual(split["stock_id"], "2330")
        self.assertEqual(set(split["timeframes"]), set(detail["timeframes"]))
        for tf, rows in detail["timeframes"].items():
            self.assertEqual(set(split["timeframes"][tf]), {r["branch_name"] for r in rows})
        self.assertEqual(split["timeframes"]["5d"]["六百萬分點"], [{
            "warrant_id": "123457", "warrant_name": "六百萬購", "kind": "call",
            "net_lots": 600, "net_amount": 6_000_000,
        }])
        # 每檔只多一個明細檔;沒進 index 的股票兩個檔都沒有。
        self.assertEqual(sorted(p.name for p in detail_dir.glob("*.json")),
                         ["2330.breakdown.json", "2330.json", "index.json"])
        # /branch 的全市場檔不拆,明細仍內嵌。
        market = json.loads((out / "branches" / "warrant_branches.json").read_text(encoding="utf-8"))
        self.assertIn("breakdown", market["timeframes"]["5d"][0])

    def test_issuer_and_branch_group_parsing(self):
        from radar.export.json_export import _branch_broker_group, _warrant_issuer_group
        self.assertEqual(_warrant_issuer_group("環球晶凱基5C購02"), "凱基")
        self.assertEqual(_warrant_issuer_group("環球晶群益59售01"), "群益金鼎")
        self.assertEqual(_warrant_issuer_group("台積電永豐5A牛03"), "永豐金")
        self.assertEqual(_warrant_issuer_group("聯發科中信61購05"), "中國信託")
        self.assertIsNone(_warrant_issuer_group("兩百萬購"))
        self.assertIsNone(_warrant_issuer_group(None))
        self.assertEqual(_branch_broker_group("元大證券"), ("元大", True))
        self.assertEqual(_branch_broker_group("元大-南京"), ("元大", False))
        self.assertEqual(_branch_broker_group("凱基"), ("凱基", True))
        self.assertEqual(_branch_broker_group("群益金鼎-東大"), ("群益金鼎", False))
        self.assertEqual(_branch_broker_group("永豐金證券"), ("永豐金", True))
        self.assertEqual(_branch_broker_group("(牛牛牛)亞-鑫豐"), ("亞", False))

    def test_self_issued_share_is_marked_per_branch_and_warrant(self):
        """發行券商總公司在自家權證上的金額標 self(hq=True);別家券商不標。"""
        day = self.DATES[-1]
        with db.get_engine().begin() as conn:
            conn.execute(schema.warrants.insert(), [
                {"id": "700001", "name": "台積電凱基5C購02", "market": "twse", "kind": "call", "stock_id": "2330"},
                {"id": "700002", "name": "台積電元大58購01", "market": "twse", "kind": "call", "stock_id": "2330"},
            ])
            conn.execute(schema.warrant_daily.insert(), [
                {"warrant_id": w, "date": day, "close": 10.0, "volume": 1, "turnover": 1}
                for w in ("700001", "700002")])
            # 凱基總公司:賣自家 -900 萬、買元大 +100 萬 → 自家淨 -900 萬、占 90%。
            upsert_branch_trades(conn, [
                {"stock_id": "700001", "date": day, "branch_key": "9200", "branch_name": "凱基",
                 "buy_lots": 0, "sell_lots": 900, "net_lots": -900, "pct": 0},
                {"stock_id": "700002", "date": day, "branch_key": "9200", "branch_name": "凱基",
                 "buy_lots": 100, "sell_lots": 0, "net_lots": 100, "pct": 0},
                {"stock_id": "700001", "date": day, "branch_key": "9268", "branch_name": "凱基-台北",
                 "buy_lots": 150, "sell_lots": 0, "net_lots": 150, "pct": 0},
            ])
        out = Path(self._tmp.name) / "out"
        out.mkdir(parents=True, exist_ok=True)
        export_json(out)
        detail_dir = out / "branches" / "warrant-stock-details"
        detail = json.loads((detail_dir / "2330.json").read_text(encoding="utf-8"))
        split = json.loads((detail_dir / "2330.breakdown.json").read_text(encoding="utf-8"))
        rows = {r["branch_name"]: r for r in detail["timeframes"]["5d"]}

        self.assertEqual(rows["凱基"]["net_amount"], -8_000_000)
        self.assertEqual(rows["凱基"]["self"], {"net": -9_000_000, "pct": 90, "hq": True})
        self.assertEqual(rows["凱基-台北"]["self"], {"net": 1_500_000, "pct": 100, "hq": False})
        self.assertNotIn("self", rows["六百萬分點"])
        flags = {b["warrant_id"]: b.get("self", False) for b in split["timeframes"]["5d"]["凱基"]}
        self.assertEqual(flags, {"700001": True, "700002": False})

    def test_empty_warrant_branch_pool_reports_null_data_date(self):
        """池內沒有權證分點時報 null,不可拿報價日充當資料日。"""
        with db.get_engine().begin() as conn:
            conn.execute(schema.branch_trades_raw.delete())
        out = Path(self._tmp.name) / "out"
        out.mkdir(parents=True, exist_ok=True)
        export_json(out)
        detail_dir = out / "branches" / "warrant-stock-details"
        index = json.loads((detail_dir / "index.json").read_text(encoding="utf-8"))

        self.assertIsNone(index["data_date"])
        self.assertEqual(index["stocks"], [])
        market = json.loads((out / "branches" / "warrant_branches.json").read_text(encoding="utf-8"))
        self.assertEqual(market, {
            "version": 1,
            "threshold": 5_000_000,
            "data_date": None,
            "timeframes": {"1d": [], "2d": [], "5d": [], "30d": [], "120d": []},
        })


if __name__ == "__main__":
    unittest.main()
