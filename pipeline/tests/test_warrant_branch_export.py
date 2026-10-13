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

        # /branch 全市場檔:self 只是新增的可選鍵,既有鍵與內嵌明細不變。
        market = json.loads((out / "branches" / "warrant_branches.json").read_text(encoding="utf-8"))
        kgi = next(r for r in market["timeframes"]["5d"] if r["branch_name"] == "凱基")
        self.assertEqual(set(kgi), {"branch_name", "underlying_id", "underlying_name",
                                    "net_amount", "breakdown", "self"})
        self.assertEqual(kgi["self"], rows["凱基"]["self"])
        self.assertEqual(len(kgi["breakdown"]), 2)
        plain = next(r for r in market["timeframes"]["5d"] if r["branch_name"] == "六百萬分點")
        self.assertEqual(set(plain), {"branch_name", "underlying_id", "underlying_name",
                                      "net_amount", "breakdown"})

    def test_self_issued_pct_is_floored_so_the_50_percent_rule_is_exact(self):
        from radar.export.json_export import _self_issued_summary

        def pct(own, other):
            breakdown = [
                {"warrant_name": "台積電凱基5C購02", "net_amount": own},
                {"warrant_name": "台積電元大58購01", "net_amount": other},
            ]
            return _self_issued_summary("凱基", breakdown)["pct"]

        self.assertEqual(pct(495, 505), 49)        # 49.5% 不可四捨五入成 50
        self.assertEqual(pct(4996, 5004), 49)      # 49.96%
        self.assertEqual(pct(500, 500), 50)        # 恰 50%
        self.assertEqual(pct(-500, 500), 50)       # 占比依絕對值
        self.assertIsNone(_self_issued_summary("元大-南京", [
            {"warrant_name": "台積電凱基5C購02", "net_amount": 100}]))

    def test_positions_estimate_in_shard_and_market_screening_file(self):
        """docs/51 wpos-avgcost-v1:分片 positions 鍵與全市場 warrant_positions.json。

        套牢分點 08-03 以 20 元買 600 張(成本 1,200 萬,現股 1000)→ 08-07 權證收 12
        → 估值 720 萬、帳面 −480 萬(−40%)。凱基總公司買自家權證 1,000 萬 → 分片有、
        篩選清單排除。
        """
        with db.get_engine().begin() as conn:
            conn.execute(schema.warrants.insert(), [
                {"id": "123460", "name": "台積電元大5A購01", "market": "twse", "kind": "call",
                 "stock_id": "2330", "maturity_date": "2027-01-29"},
                {"id": "700001", "name": "台積電凱基5C購02", "market": "twse", "kind": "call",
                 "stock_id": "2330", "maturity_date": "2027-01-29"},
            ])
            conn.execute(schema.warrant_daily.insert(), [
                {"warrant_id": "123460", "date": self.DATES[0], "close": 20.0, "volume": 1, "turnover": 1},
                {"warrant_id": "123460", "date": self.DATES[1], "close": 8.0, "volume": 1, "turnover": 1},
                {"warrant_id": "123460", "date": self.DATES[-1], "close": 12.0, "volume": 1, "turnover": 1},
                {"warrant_id": "700001", "date": self.DATES[-1], "close": 10.0, "volume": 1, "turnover": 1},
            ])
            upsert_branch_trades(conn, [
                {"stock_id": "123460", "date": self.DATES[0], "branch_key": "uw", "branch_name": "套牢分點",
                 "buy_lots": 600, "sell_lots": 0, "net_lots": 600, "pct": 0},
                # 帳面為正:08-04 以 8 元買 1,000 張(800 萬)→ 最後 12 元 → +400 萬(+50%)。
                {"stock_id": "123460", "date": self.DATES[1], "branch_key": "up", "branch_name": "帳面為正分點",
                 "buy_lots": 1000, "sell_lots": 0, "net_lots": 1000, "pct": 0},
                {"stock_id": "700001", "date": self.DATES[-1], "branch_key": "9200", "branch_name": "凱基",
                 "buy_lots": 1000, "sell_lots": 0, "net_lots": 1000, "pct": 0},
            ])
        out = Path(self._tmp.name) / "out"
        out.mkdir(parents=True, exist_ok=True)
        export_json(out)
        detail = json.loads((out / "branches" / "warrant-stock-details" / "2330.json").read_text(encoding="utf-8"))
        pos = detail["positions"]
        self.assertEqual(pos["version"], "wpos-avgcost-v1")
        self.assertEqual((pos["as_of"], pos["window_from"]), (self.DATES[-1], self.DATES[0]))
        self.assertEqual((pos["under_last"], pos["under_last_date"]), (1000.0, self.DATES[-1]))
        uw = pos["branches"]["套牢分點"]["call"]
        self.assertEqual((uw["lots"], uw["cost"], uw["value"], uw["unrealized"], uw["unrealized_pct"]),
                         (600, 12_000_000, 7_200_000, -4_800_000, -40.0))
        self.assertEqual(uw["avg_under"], 1000.0)
        self.assertEqual((uw["n_warrants"], uw["n_held"], uw["self_cost"]), (1, 1, 0))
        self.assertEqual(uw["last_buy_date"], self.DATES[0])
        self.assertNotIn("warrants", uw)
        self.assertNotIn("put", pos["branches"]["套牢分點"])
        # 既有分點:同日買 200 張 @10、最後價 10 → 帳面 0。
        two = pos["branches"]["兩百萬分點"]["call"]
        self.assertEqual((two["cost"], two["unrealized"]), (2_000_000, 0))
        # 賣超分點:沒有持股,只有找不到對應的賣出。
        seven = pos["branches"]["七百萬賣超分點"]["put"]
        self.assertEqual((seven["lots"], seven["sell_lots_unattributed"]), (0, 700))
        self.assertNotIn("unrealized", seven)
        # 凱基總公司自家權證:分片照算、self_cost 標出來。
        kgi = pos["branches"]["凱基"]["call"]
        self.assertEqual((kgi["cost"], kgi["self_cost"]), (10_000_000, 10_000_000))
        # 逐日序列契約不變。
        self.assertEqual(detail["daily"]["套牢分點"], [[self.DATES[0], 12_000_000, 0]])

        screen = json.loads((out / "branches" / "warrant_positions.json").read_text(encoding="utf-8"))
        self.assertEqual(screen["version"], 3)
        self.assertEqual(screen["definitions_version"], "wpos-avgcost-v1")
        self.assertEqual(screen["data_date"], self.DATES[-1])
        self.assertEqual((screen["min_cost"], screen["max_rows_per_side"]), (5_000_000, 400))
        self.assertNotIn("max_rows_per_kind", screen)
        call = screen["kinds"]["call"]
        self.assertEqual(set(call), {"excluded_self", "down", "up"})
        self.assertEqual(call["excluded_self"], 1)
        # 六百萬分點(600 張 @10 = 600 萬,帳面 0)也過 500 萬門檻,0% 歸帳面為負那邊;最差的在前。
        self.assertEqual(call["down"]["total"], 2)
        self.assertEqual([r["branch_name"] for r in call["down"]["rows"]], ["套牢分點", "六百萬分點"])
        self.assertEqual(call["up"]["total"], 1)
        up = call["up"]["rows"][0]
        self.assertEqual((up["branch_name"], up["cost"], up["unrealized"], up["unrealized_pct"]),
                         ("帳面為正分點", 8_000_000, 4_000_000, 50.0))
        self.assertEqual(up["buy_days"], [[self.DATES[1], 1000, 8_000_000, 1000.0]])
        self.assertEqual(screen["kinds"]["put"], {"excluded_self": 0, "down": {"rows": [], "total": 0},
                                                  "up": {"rows": [], "total": 0}})
        row = call["down"]["rows"][0]
        self.assertEqual((row["branch_name"], row["underlying_id"], row["underlying_name"], row["kind"]),
                         ("套牢分點", "2330", "台積電", "call"))
        self.assertEqual((row["cost"], row["unrealized"], row["unrealized_pct"]), (12_000_000, -4_800_000, -40.0))
        self.assertEqual((row["avg_under"], row["under_last"], row["under_last_date"]), (1000.0, 1000.0, self.DATES[-1]))
        self.assertEqual(row["self_pct"], 0)
        self.assertEqual(row["buy_days"], [[self.DATES[0], 600, 12_000_000, 1000.0]])
        self.assertEqual(uw["buy_days"], row["buy_days"])
        self.assertEqual(row["cost_valued"], 12_000_000)

    def test_positions_mark_expired_and_price_missing_legs(self):
        """到期權證仍持有但不估值;交易日沒收盤的腿整腿不估。"""
        with db.get_engine().begin() as conn:
            conn.execute(schema.warrants.insert(), [
                {"id": "123461", "name": "到期購", "market": "twse", "kind": "call",
                 "stock_id": "2330", "maturity_date": self.DATES[2]},
                {"id": "123462", "name": "無價購", "market": "twse", "kind": "call", "stock_id": "2330",
                 "maturity_date": None},
            ])
            conn.execute(schema.warrant_daily.insert(), [
                {"warrant_id": "123461", "date": self.DATES[0], "close": 5.0, "volume": 1, "turnover": 1},
            ])
            upsert_branch_trades(conn, [
                {"stock_id": "123461", "date": self.DATES[0], "branch_key": "ex", "branch_name": "到期分點",
                 "buy_lots": 400, "sell_lots": 0, "net_lots": 400, "pct": 0},
                {"stock_id": "123462", "date": self.DATES[0], "branch_key": "np", "branch_name": "無價分點",
                 "buy_lots": 2000, "sell_lots": 0, "net_lots": 2000, "pct": 0},
            ])
        detail = self._export_detail()
        ex = detail["positions"]["branches"]["到期分點"]["call"]
        self.assertEqual((ex["lots"], ex["cost"], ex["n_expired"]), (400, 2_000_000, 1))
        self.assertNotIn("unrealized", ex)
        # 無價分點:金額以 1.0 計入排行(既有契約),但持有估算整腿 cost_unknown,連張數都不進。
        np_ = detail["positions"]["branches"]["無價分點"]["call"]
        self.assertEqual((np_["lots"], np_["cost"], np_["n_cost_unknown"], np_["buy_lots"]), (0, 0, 1, 0))

    # main(8bc317f)的逐日序列查詢,逐字複製當對照;輸出必須與它逐位元相同,diff 才有意義。
    _MAIN_DAILY_SQL = """
        SELECT b.branch_name, w.stock_id AS underlying_id, b.date,
               SUM(CASE WHEN w.kind = 'call'
                        THEN b.net_lots * CAST(ROUND(COALESCE(wd.close, 1.0) * 1000) AS INTEGER) ELSE 0 END) AS call_amt,
               SUM(CASE WHEN w.kind = 'put'
                        THEN b.net_lots * CAST(ROUND(COALESCE(wd.close, 1.0) * 1000) AS INTEGER) ELSE 0 END) AS put_amt
        FROM branch_trades b
        JOIN warrants w ON w.id = b.stock_id
        JOIN stocks s ON s.id = w.stock_id
        LEFT JOIN warrant_daily wd ON wd.warrant_id = b.stock_id AND wd.date = b.date
        WHERE LENGTH(b.stock_id) = 6 AND b.date >= :d120 AND b.date <= :d1
          AND s.type = 'stock'
          AND s.name NOT LIKE '%指%'
        GROUP BY b.branch_name, w.stock_id, b.date
        ORDER BY b.date
    """

    def test_bull_bear_rows_keep_main_daily_semantics_byte_for_byte(self):
        """牛熊證:逐日序列照 main 算成 0(不進認購也不進認售欄),持有估算與篩選清單不含它們。"""
        from sqlalchemy import text
        day0, day1 = self.DATES[0], self.DATES[-1]
        with db.get_engine().begin() as conn:
            conn.execute(schema.warrants.insert(), [
                {"id": "031001", "name": "台積電元大5B牛01", "market": "twse", "kind": "bull", "stock_id": "2330", "maturity_date": None},
                {"id": "031002", "name": "台積電元大5B熊01", "market": "twse", "kind": "bear", "stock_id": "2330", "maturity_date": None},
                {"id": "031003", "name": "台積電凱基5C購09", "market": "twse", "kind": "call", "stock_id": "2330", "maturity_date": None},
            ])
            conn.execute(schema.warrant_daily.insert(), [
                {"warrant_id": w, "date": d, "close": 8.0, "volume": 1, "turnover": 1}
                for w in ("031001", "031002", "031003") for d in (day0, day1)
            ])
            upsert_branch_trades(conn, [
                # 牛熊分點:只有牛熊 → 進分片(金額 ≥ 100 萬)但逐日序列 [d, 0, 0],無持有估算。
                {"stock_id": "031001", "date": day0, "branch_key": "bb", "branch_name": "牛熊分點", "buy_lots": 900, "sell_lots": 0, "net_lots": 900, "pct": 0},
                {"stock_id": "031002", "date": day1, "branch_key": "bb", "branch_name": "牛熊分點", "buy_lots": 0, "sell_lots": 400, "net_lots": -400, "pct": 0},
                # 混合分點:牛證 + 認購同日;認購才進持有估算。
                {"stock_id": "031001", "date": day1, "branch_key": "mx", "branch_name": "混合分點", "buy_lots": 500, "sell_lots": 0, "net_lots": 500, "pct": 0},
                {"stock_id": "031003", "date": day1, "branch_key": "mx", "branch_name": "混合分點", "buy_lots": 300, "sell_lots": 0, "net_lots": 300, "pct": 0},
            ])
        detail = self._export_detail()
        self.assertEqual(detail["daily"]["牛熊分點"], [[day0, 0, 0], [day1, 0, 0]])
        self.assertEqual(detail["daily"]["混合分點"], [[day1, 2_400_000, 0]])
        self.assertNotIn("牛熊分點", detail["positions"]["branches"])
        mixed = detail["positions"]["branches"]["混合分點"]
        self.assertEqual(set(mixed), {"call"})
        self.assertEqual((mixed["call"]["lots"], mixed["call"]["cost"]), (300, 2_400_000))
        # 逐位元:整個 daily 物件(含券商鍵順序、每列順序)與 main 的查詢結果相同。
        with db.get_engine().connect() as conn:
            dates = [r[0] for r in conn.execute(text("SELECT DISTINCT date FROM daily_prices ORDER BY date DESC LIMIT 120"))]
            charted = {r for rows in detail["timeframes"].values() for r in (x["branch_name"] for x in rows)}
            expect: dict[str, list] = {}
            for r in conn.execute(text(self._MAIN_DAILY_SQL), {"d120": dates[-1], "d1": detail["data_date"]}):
                if r.underlying_id == "2330" and r.branch_name in charted:
                    expect.setdefault(r.branch_name, []).append([r.date, int(r.call_amt), int(r.put_amt)])
        self.assertEqual(json.dumps(detail["daily"], ensure_ascii=False), json.dumps(expect, ensure_ascii=False))
        # 篩選清單不含牛熊。
        out = Path(self._tmp.name) / "out"
        screen = json.loads((out / "branches" / "warrant_positions.json").read_text(encoding="utf-8"))
        self.assertEqual(set(screen["kinds"]), {"call", "put"})
        self.assertNotIn("牛熊分點", [r["branch_name"] for side in ("down", "up")
                                     for r in screen["kinds"]["call"][side]["rows"]])

    def test_issuer_alias_table(self):
        """外資發行商與分點名稱變體(verifier 2026-10-12):麥證/法興/匯豐、國泰綜合、台北富邦、國別前綴。"""
        from radar.export.json_export import _branch_broker_group, _is_self_issued, _warrant_issuer_group
        self.assertEqual(_warrant_issuer_group("台積電麥證5A購01"), "麥格理")
        self.assertEqual(_warrant_issuer_group("台積電法興5B售02"), "法國興業")
        self.assertEqual(_warrant_issuer_group("台積電匯豐5C購03"), "匯豐")
        self.assertEqual(_branch_broker_group("港商麥格理"), ("麥格理", True))
        self.assertEqual(_branch_broker_group("麥格理"), ("麥格理", True))
        self.assertEqual(_branch_broker_group("法商法國興業"), ("法國興業", True))
        self.assertEqual(_branch_broker_group("港商匯豐"), ("匯豐", True))
        self.assertEqual(_branch_broker_group("國泰綜合-敦南"), ("國泰", False))
        self.assertEqual(_branch_broker_group("國泰-敦南"), ("國泰", False))
        self.assertEqual(_branch_broker_group("台北富邦-建國"), ("富邦", False))
        self.assertEqual(_branch_broker_group("富邦-建國"), ("富邦", False))
        self.assertTrue(_is_self_issued("港商麥格理", "台積電麥證5A購01"))
        self.assertTrue(_is_self_issued("法商法國興業", "台積電法興5B售02"))
        self.assertTrue(_is_self_issued("港商匯豐", "台積電匯豐5C購03"))
        self.assertTrue(_is_self_issued("國泰綜合-敦南", "台積電國泰5D購04"))
        self.assertTrue(_is_self_issued("台北富邦-建國", "台積電富邦5E售05"))
        self.assertTrue(_is_self_issued("群益金鼎-板橋", "台積電群益59購03"))
        self.assertFalse(_is_self_issued("港商麥格理", "台積電凱基5C購02"))
        self.assertFalse(_is_self_issued("凱基-台北", "兩百萬購"))     # 解不出發行商 → 不猜

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
        screen = json.loads((out / "branches" / "warrant_positions.json").read_text(encoding="utf-8"))
        self.assertEqual(screen, {
            "version": 3, "definitions_version": "wpos-avgcost-v1", "data_date": None, "window_from": None,
            "min_cost": 5_000_000, "max_rows_per_side": 400,
            "kinds": {k: {"excluded_self": 0, "down": {"rows": [], "total": 0}, "up": {"rows": [], "total": 0}}
                      for k in ("call", "put")},
        })


if __name__ == "__main__":
    unittest.main()
