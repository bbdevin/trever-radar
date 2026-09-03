"""docs/37 E2 pair 粒度:分點 × 個股 的買/賣價格分位計數與其匯出契約。

這裡驗的是「數字加不加得起來」與「有沒有被當成判定」,不是「誰是關鍵分點」——
量測顯示這個性質隔年重新標記率只有 1.6–5.4%,所以程式裡不該有旗標可測。
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
from radar.cli import main
from radar.compute.branch_stock_pctile_counts import (
    DEFINITIONS_VERSION,
    compute_branch_stock_pctile_counts,
)
from radar.export.json_export import (
    BRANCH_PCTILE_MAX_BRANCHES,
    BRANCH_PCTILE_MIN_KNOWN_PER_SIDE,
    _rank_branch_pctile_rows,
    export_json,
)


def _market_days(start: date, count: int) -> list[str]:
    days: list[str] = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current.isoformat())
        current += timedelta(days=1)
    return days


# 個股 P 的價格被排成:第 18 天一根 200 的高點,其餘平盤 100。於是第 19～27 天
# 的 20 日窗口極值都是 (100, 200),事件日分位剛好是 (close - 100) / 100。
_P_CLOSE = {18: 200, 19: 130, 21: 190, 23: 180, 25: 110}


def _pair_row(branch_name: str, **counts) -> dict:
    """匯出排序用的一列;window 欄位在排序時用不到,故留給呼叫端補。"""
    row = {
        "branch_name": branch_name,
        "buy_pctile_known": 0, "buy_pctile_unknown": 0, "low_buy_count": 0,
        "sell_pctile_known": 0, "sell_pctile_unknown": 0, "high_sell_count": 0,
        "stock_buy_pctile_known": 0, "stock_low_buy_count": 0,
        "stock_sell_pctile_known": 0, "stock_high_sell_count": 0,
    }
    row.update(counts)
    return row


class BranchStockPctileCountsComputeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.old_url, self.old_dir = config.DB_URL, config.DATA_DIR
        config.DB_URL = "sqlite:///" + (self.tmp_path / "pair.db").as_posix()
        config.DATA_DIR = self.tmp_path
        db._engine = None
        db.init_db()
        self.days = _market_days(date(2026, 1, 2), 28)
        self.as_of = self.days[27]
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": "P", "name": "Pool", "market": "twse", "type": "stock"},
                {"id": "Q", "name": "Quiet", "market": "twse", "type": "stock"},
            ])
            prices = []
            for index, day in enumerate(self.days):
                prices.append({
                    "stock_id": "P", "date": day, "open": 100,
                    "close": _P_CLOSE.get(index, 100), "adj_factor": 1.0,
                })
                # Q 在第 20 天沒有收盤價,所以那天的分位必須是 unknown。
                prices.append({
                    "stock_id": "Q", "date": day, "open": 100,
                    "close": None if index == 20 else 100, "adj_factor": 1.0,
                })
            conn.execute(schema.daily_prices.insert(), prices)
            conn.execute(schema.tracked_branches.insert(), [
                {"branch_name": "LOWBUY", "source": "manual", "added_at": self.days[0]},
                {"branch_name": "SELLER", "source": "manual", "added_at": self.days[0]},
            ])
            conn.execute(schema.branch_dim.insert(), [
                {"id": 1, "branch_key": "lowbuy", "branch_name": "LOWBUY"},
                {"id": 2, "branch_key": "seller", "branch_name": "SELLER"},
                {"id": 3, "branch_key": "untracked", "branch_name": "UNTRACKED"},
            ])
            conn.execute(schema.branch_trades_raw.insert(), [
                # LOWBUY 在 P:三次不相鄰的買進 episode。第 19 天分位 0.30(低買)、
                # 第 21 天 0.90、第 25 天 0.10(低買)。
                {"stock_id": "P", "date": self.days[19], "branch_id": 1, "net_lots": 10, "pct": 1.0, "source": "fixture"},
                {"stock_id": "P", "date": self.days[21], "branch_id": 1, "net_lots": 10, "pct": 1.0, "source": "fixture"},
                {"stock_id": "P", "date": self.days[25], "branch_id": 1, "net_lots": 10, "pct": 1.0, "source": "fixture"},
                # SELLER 在 P:兩次賣出 episode。第 21 天 0.90(高賣)、第 23 天 0.80(高賣)。
                {"stock_id": "P", "date": self.days[21], "branch_id": 2, "net_lots": -5, "pct": -1.5, "source": "fixture"},
                {"stock_id": "P", "date": self.days[23], "branch_id": 2, "net_lots": -5, "pct": -1.5, "source": "fixture"},
                # SELLER 在 Q:事件日沒有收盤價 → 分位 unknown,不是失敗。
                {"stock_id": "Q", "date": self.days[20], "branch_id": 2, "net_lots": 7, "pct": 1.0, "source": "fixture"},
                # pct 缺漏:是觀察到的一列,但不是事件。
                {"stock_id": "Q", "date": self.days[22], "branch_id": 2, "net_lots": 7, "pct": None, "source": "fixture"},
                # 不在 universe:永遠不該有列。
                {"stock_id": "P", "date": self.days[19], "branch_id": 3, "net_lots": 10, "pct": 1.0, "source": "fixture"},
            ])

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self.old_url, self.old_dir
        self.tmp.cleanup()

    def _rows(self, **where):
        clause = "".join(f" AND {key} = :{key}" for key in where)
        with db.get_engine().connect() as conn:
            return [dict(row) for row in conn.execute(text(
                f"SELECT * FROM branch_stock_pctile_counts WHERE 1=1{clause} "
                "ORDER BY stock_id, branch_name"
            ), where).mappings()]

    def test_counts_are_per_pair_and_the_universe_is_respected(self):
        info = compute_branch_stock_pctile_counts(as_of=self.as_of, window_days=30)
        rows = self._rows()
        self.assertEqual(
            [(row["stock_id"], row["branch_name"]) for row in rows],
            [("P", "LOWBUY"), ("P", "SELLER"), ("Q", "SELLER")],
        )
        self.assertEqual(info["pairs_written"], 3)
        self.assertEqual(info["stocks_written"], 2)
        self.assertEqual({row["definitions_version"] for row in rows}, {DEFINITIONS_VERSION})
        self.assertTrue(all(row["computed_at"] for row in rows))
        by_pair = {(row["stock_id"], row["branch_name"]): row for row in rows}

        low = by_pair[("P", "LOWBUY")]
        self.assertEqual(low["buy_pctile_known"], 3)
        self.assertEqual(low["low_buy_count"], 2)
        # 買方與賣方各自獨立:買方的列不會因為沒有賣出而被記成任何失敗。
        self.assertEqual(low["sell_pctile_known"], 0)
        self.assertEqual(low["high_sell_count"], 0)

        seller = by_pair[("P", "SELLER")]
        self.assertEqual(seller["sell_pctile_known"], 2)
        self.assertEqual(seller["high_sell_count"], 2)
        self.assertEqual(seller["buy_pctile_known"], 0)

    def test_unknown_percentiles_are_counted_separately_never_as_failures(self):
        compute_branch_stock_pctile_counts(as_of=self.as_of, window_days=30)
        row = self._rows(stock_id="Q")[0]
        self.assertEqual(row["buy_pctile_unknown"], 1)
        self.assertEqual(row["buy_pctile_known"], 0)
        self.assertEqual(row["low_buy_count"], 0)
        # 分母是 known,unknown 不在分母裡,所以它既不是分子也不是分母。
        self.assertEqual(row["stock_buy_pctile_known"], 0)

    def test_stock_pooled_counts_are_the_row_sums_of_that_stock(self):
        compute_branch_stock_pctile_counts(as_of=self.as_of, window_days=30)
        p_rows = self._rows(stock_id="P")
        expected = {
            "stock_buy_pctile_known": sum(row["buy_pctile_known"] for row in p_rows),
            "stock_low_buy_count": sum(row["low_buy_count"] for row in p_rows),
            "stock_sell_pctile_known": sum(row["sell_pctile_known"] for row in p_rows),
            "stock_high_sell_count": sum(row["high_sell_count"] for row in p_rows),
        }
        self.assertEqual(expected["stock_buy_pctile_known"], 3)
        self.assertEqual(expected["stock_sell_pctile_known"], 2)
        for row in p_rows:
            with self.subTest(branch=row["branch_name"]):
                for key, value in expected.items():
                    self.assertEqual(row[key], value)

    def test_every_row_is_internally_self_describing(self):
        compute_branch_stock_pctile_counts(as_of=self.as_of, window_days=30)
        rows = self._rows()
        self.assertTrue(rows)
        for row in rows:
            with self.subTest(stock=row["stock_id"], branch=row["branch_name"]):
                self.assertLessEqual(row["low_buy_count"], row["buy_pctile_known"])
                self.assertLessEqual(row["high_sell_count"], row["sell_pctile_known"])
                self.assertLessEqual(row["buy_pctile_known"], row["stock_buy_pctile_known"])
                self.assertLessEqual(row["low_buy_count"], row["stock_low_buy_count"])
                self.assertLessEqual(row["sell_pctile_known"], row["stock_sell_pctile_known"])
                self.assertLessEqual(row["high_sell_count"], row["stock_high_sell_count"])
                self.assertGreater(
                    row["buy_pctile_known"] + row["buy_pctile_unknown"]
                    + row["sell_pctile_known"] + row["sell_pctile_unknown"], 0,
                )

    def test_table_holds_only_the_latest_snapshot(self):
        compute_branch_stock_pctile_counts(as_of=self.as_of, window_days=30)
        self.assertEqual(len(self._rows()), 3)
        with db.get_engine().begin() as conn:
            conn.execute(schema.branch_trades_raw.delete().where(
                schema.branch_trades_raw.c.stock_id == "Q"
            ))
        info = compute_branch_stock_pctile_counts(as_of=self.as_of, window_days=30)
        rows = self._rows()
        # 舊的 Q 列必須被整份取代掉,不能留成孤兒。
        self.assertEqual([row["stock_id"] for row in rows], ["P", "P"])
        self.assertEqual(info["pairs_written"], 2)

    def test_no_flag_score_or_rank_column_exists(self):
        """量測顯示這個性質不持久,所以 schema 裡不該有任何判定欄位。"""
        with db.get_engine().connect() as conn:
            columns = {
                row[1] for row in
                conn.exec_driver_sql("PRAGMA table_info(branch_stock_pctile_counts)").fetchall()
            }
        self.assertTrue(columns)
        for banned in ("rate", "score", "rank", "flag", "is_key", "key_branch",
                       "win_rate", "ret", "profit", "pnl"):
            with self.subTest(banned=banned):
                self.assertFalse(
                    [name for name in columns if banned in name],
                    f"欄位名稱不得出現 {banned!r}:這張表只存計數與分母",
                )

    def test_truncated_window_records_the_real_first_market_day(self):
        info = compute_branch_stock_pctile_counts(as_of=self.as_of, window_days=490)
        self.assertTrue(info["window_truncated"])
        self.assertEqual(info["window_market_days"], 28)
        self.assertEqual(info["window_from"], self.days[0])
        self.assertEqual(self._rows()[0]["window_from"], self.days[0])

    def test_invalid_as_of_and_window_are_rejected_without_touching_the_table(self):
        compute_branch_stock_pctile_counts(as_of=self.as_of, window_days=30)
        saturday = (date.fromisoformat(self.days[-1]) + timedelta(days=1)).isoformat()
        with self.assertRaisesRegex(ValueError, "market trading day"):
            compute_branch_stock_pctile_counts(as_of=saturday)
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            compute_branch_stock_pctile_counts(as_of="2026/01/02")
        with self.assertRaisesRegex(ValueError, "window-days"):
            compute_branch_stock_pctile_counts(as_of=self.as_of, window_days=0)
        # 失敗時整份 rollback:上一份完整快照必須原封不動。
        self.assertEqual(len(self._rows()), 3)

    def test_cli_defaults_to_the_latest_trading_day_and_is_repeatable(self):
        main(["branch-stock-pctile-counts", "--window-days", "30"])
        main(["branch-stock-pctile-counts", "--window-days", "30"])
        rows = self._rows()
        self.assertEqual(len(rows), 3)
        self.assertEqual({row["as_of"] for row in rows}, {self.as_of})


class BranchPctileRankingTests(unittest.TestCase):
    """排序用的是「超出該檔股票自身基準」的差額,不是原始比率。"""

    def test_margin_winner_beats_the_raw_rate_winner(self):
        # 該檔股票自身基準:買 50%(100/200)、賣 20%(40/200)。兩側差 30 個
        # 百分點——這正是全市場的實況(低買 53.35% / 高賣 35.35%)。
        base = {
            "stock_buy_pctile_known": 200, "stock_low_buy_count": 100,
            "stock_sell_pctile_known": 200, "stock_high_sell_count": 40,
        }
        # RAWWINNER:買 14/20 = 70%、賣 1/5 = 20%。把兩側合起來看是 15/25 = 60%。
        raw_winner = _pair_row(
            "RAWWINNER", buy_pctile_known=20, low_buy_count=14,
            sell_pctile_known=5, high_sell_count=1, **base,
        )
        # MARGINWINNER:買 2/5 = 40%、賣 12/20 = 60%。合起來只有 14/25 = 56%,
        # 比 RAWWINNER 低;但買側只輸基準 10pp、賣側贏基準 40pp。
        margin_winner = _pair_row(
            "MARGINWINNER", buy_pctile_known=5, low_buy_count=2,
            sell_pctile_known=20, high_sell_count=12, **base,
        )
        rows = [raw_winner, margin_winner]

        def pooled_rate(row):
            return (
                (row["low_buy_count"] + row["high_sell_count"])
                / (row["buy_pctile_known"] + row["sell_pctile_known"])
            )

        # 前提成立:把兩側合併成一個比率,會挑到 RAWWINNER。
        self.assertGreater(pooled_rate(raw_winner), pooled_rate(margin_winner))
        # 但扣掉各自那一側的基準之後,順序反過來——這就是那把尺的用途。
        ranked = _rank_branch_pctile_rows(rows, limit=10, min_known=5)
        self.assertEqual(
            [row["branch_name"] for row in ranked], ["MARGINWINNER", "RAWWINNER"],
        )

    def test_thin_pairs_are_excluded_by_the_floor_on_each_side(self):
        rows = [
            _pair_row("BOTH_OK", buy_pctile_known=5, low_buy_count=5,
                      sell_pctile_known=5, high_sell_count=5),
            _pair_row("THIN_SELL", buy_pctile_known=99, low_buy_count=99,
                      sell_pctile_known=4, high_sell_count=4),
            _pair_row("THIN_BUY", buy_pctile_known=4, low_buy_count=4,
                      sell_pctile_known=99, high_sell_count=99),
        ]
        ranked = _rank_branch_pctile_rows(
            rows, limit=10, min_known=BRANCH_PCTILE_MIN_KNOWN_PER_SIDE,
        )
        self.assertEqual([row["branch_name"] for row in ranked], ["BOTH_OK"])

    def test_the_cap_holds_and_ties_break_deterministically(self):
        rows = [
            _pair_row(f"B{index:02d}", buy_pctile_known=10, low_buy_count=10,
                      sell_pctile_known=10, high_sell_count=10)
            for index in range(25)
        ]
        ranked = _rank_branch_pctile_rows(
            rows, limit=BRANCH_PCTILE_MAX_BRANCHES, min_known=5,
        )
        self.assertEqual(len(ranked), BRANCH_PCTILE_MAX_BRANCHES)
        self.assertEqual(
            [row["branch_name"] for row in ranked],
            [f"B{index:02d}" for index in range(BRANCH_PCTILE_MAX_BRANCHES)],
        )

    def test_a_missing_stock_baseline_does_not_crash_the_sort(self):
        rows = [_pair_row("NOBASE", buy_pctile_known=5, low_buy_count=5,
                          sell_pctile_known=5, high_sell_count=5)]
        self.assertEqual(
            [row["branch_name"] for row in _rank_branch_pctile_rows(rows, 10, 5)],
            ["NOBASE"],
        )


class BranchPctileExportTests(unittest.TestCase):
    """個股 JSON 的形狀:鍵永遠在,沒有合格分點時是誠實的空清單。"""

    DATES = ("2026-08-03", "2026-08-04", "2026-08-05")

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.old_url, self.old_dir = config.DB_URL, config.DATA_DIR
        config.DB_URL = "sqlite:///" + (self.tmp_path / "e.db").as_posix()
        config.DATA_DIR = self.tmp_path
        db._engine = None
        db.init_db()
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": "1111", "name": "有證據", "market": "twse", "type": "stock", "is_active": 1},
                {"id": "2222", "name": "沒證據", "market": "twse", "type": "stock", "is_active": 1},
            ])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": sid, "date": day, "open": 100.0, "close": 100.0,
                 "volume": 1000, "turnover": 1, "adj_factor": 1.0}
                for sid in ("1111", "2222") for day in self.DATES
            ])

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self.old_url, self.old_dir
        self.tmp.cleanup()

    def _seed(self, rows):
        window = {
            "as_of": self.DATES[-1], "window_market_days": 490,
            "window_from": "2024-08-01", "definitions_version": DEFINITIONS_VERSION,
            "computed_at": "2026-08-05T23:10:00+08:00",
        }
        with db.get_engine().begin() as conn:
            conn.execute(schema.branch_stock_pctile_counts.insert(),
                         [{**window, **row} for row in rows])

    def _export(self, sid):
        out = self.tmp_path / "out"
        out.mkdir(parents=True, exist_ok=True)
        export_json(out)
        return json.loads((out / "stocks" / f"{sid}.json").read_text(encoding="utf-8"))

    def test_payload_carries_counts_denominators_and_the_stock_baseline(self):
        self._seed([
            {"stock_id": "1111", "branch_name": "甲", "buy_pctile_known": 33,
             "buy_pctile_unknown": 2, "low_buy_count": 28, "sell_pctile_known": 20,
             "sell_pctile_unknown": 1, "high_sell_count": 14,
             "stock_buy_pctile_known": 1000, "stock_low_buy_count": 572,
             "stock_sell_pctile_known": 900, "stock_high_sell_count": 287},
            # 兩側都不足 5 筆:必須被門檻擋掉。
            {"stock_id": "1111", "branch_name": "乙", "buy_pctile_known": 4,
             "buy_pctile_unknown": 0, "low_buy_count": 4, "sell_pctile_known": 4,
             "sell_pctile_unknown": 0, "high_sell_count": 4,
             "stock_buy_pctile_known": 1000, "stock_low_buy_count": 572,
             "stock_sell_pctile_known": 900, "stock_high_sell_count": 287},
        ])
        payload = self._export("1111")["branch_pctile_counts"]
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["as_of"], self.DATES[-1])
        self.assertEqual(payload["window_market_days"], 490)
        self.assertEqual(payload["window_from"], "2024-08-01")
        self.assertEqual(payload["computed_at"], "2026-08-05T23:10:00+08:00")
        self.assertEqual(payload["definitions_version"], DEFINITIONS_VERSION)
        self.assertEqual(payload["min_known_episodes_per_side"], 5)
        self.assertEqual(payload["max_branches"], 10)
        # 那把尺跟著 payload 一起走,前端不必自己推測基準。
        self.assertEqual(payload["stock_buy_pctile_known"], 1000)
        self.assertEqual(payload["stock_low_buy_count"], 572)
        self.assertEqual(payload["stock_sell_pctile_known"], 900)
        self.assertEqual(payload["stock_high_sell_count"], 287)
        self.assertEqual(payload["branches"], [{
            "branch_name": "甲", "buy_pctile_known": 33, "buy_pctile_unknown": 2,
            "low_buy_count": 28, "sell_pctile_known": 20, "sell_pctile_unknown": 1,
            "high_sell_count": 14,
        }])
        # 沒有任何判定欄位:沒有比率、沒有旗標、沒有名次。
        for banned in ("rate", "score", "rank", "flag", "is_key", "win", "profit"):
            with self.subTest(banned=banned):
                self.assertFalse([k for k in payload["branches"][0] if banned in k])

    def test_a_stock_with_no_qualifying_branch_emits_an_empty_list_not_a_missing_key(self):
        self._seed([
            {"stock_id": "1111", "branch_name": "甲", "buy_pctile_known": 9,
             "buy_pctile_unknown": 0, "low_buy_count": 9, "sell_pctile_known": 9,
             "sell_pctile_unknown": 0, "high_sell_count": 9,
             "stock_buy_pctile_known": 9, "stock_low_buy_count": 9,
             "stock_sell_pctile_known": 9, "stock_high_sell_count": 9},
        ])
        payload = self._export("2222")["branch_pctile_counts"]
        self.assertEqual(payload["branches"], [])
        # 這檔股票在快照裡完全沒有列,所以它自己的基準是「不知道」,不是 0。
        self.assertIsNone(payload["stock_buy_pctile_known"])
        self.assertIsNone(payload["stock_sell_pctile_known"])
        # window 中繼資料仍然來自快照,頁面才說得出自己涵蓋哪一段期間。
        self.assertEqual(payload["as_of"], self.DATES[-1])

    def test_export_survives_a_database_that_never_ran_the_computation(self):
        with db.get_engine().begin() as conn:
            conn.exec_driver_sql("DROP TABLE branch_stock_pctile_counts")
        out = self.tmp_path / "out"
        out.mkdir(parents=True, exist_ok=True)
        # export_json 會 init_db 重建空表;內容仍是誠實的空。
        export_json(out)
        payload = json.loads(
            (out / "stocks" / "1111.json").read_text(encoding="utf-8")
        )["branch_pctile_counts"]
        self.assertEqual(payload["branches"], [])
        self.assertIsNone(payload["as_of"])


if __name__ == "__main__":
    unittest.main()
