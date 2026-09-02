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
        market = json.loads((out / "branches" / "warrant_branches.json").read_text(encoding="utf-8"))
        index = json.loads((detail_dir / "index.json").read_text(encoding="utf-8"))
        detail = json.loads((detail_dir / "2330.json").read_text(encoding="utf-8"))

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

        self.assertEqual(index["data_date"], self.DATES[-1])
        self.assertEqual(detail["data_date"], self.DATES[-1])
        self.assertEqual(
            [row["branch_name"] for row in detail["timeframes"]["1d"]],
            ["七百萬賣超分點", "六百萬分點", "兩百萬分點"],
        )

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
        self.assertEqual(market, {"1d": [], "2d": [], "5d": [], "30d": [], "120d": []})


if __name__ == "__main__":
    unittest.main()
