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
from radar.compute.branch_point_in_time_report import _price_observation
from radar.compute.branch_stock_pctile_counts import (
    DAYTRADE_MIN_OBS,
    DEFINITIONS_VERSION,
    compute_branch_stock_pctile_counts,
    episode_lots,
    rolling_close_ranges,
)
from radar.export.json_export import (
    BRANCH_PCTILE_LOOKUP_FIELDS,
    BRANCH_PCTILE_MAX_BRANCHES,
    BRANCH_PCTILE_MIN_KNOWN_PER_SIDE,
    _pctile_shrink_k,
    _rank_branch_pctile_rows,
    _rank_branch_pctile_rows_by_lots,
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

    def test_lots_follow_the_same_episode_classification_as_counts(self):
        compute_branch_stock_pctile_counts(as_of=self.as_of, window_days=30)
        by_pair = {(row["stock_id"], row["branch_name"]): row for row in self._rows()}
        low = by_pair[("P", "LOWBUY")]
        # 三個買進 episode 各 10 張;兩個落在低檔。
        self.assertEqual(low["buy_lots_known"], 30)
        self.assertEqual(low["low_buy_lots"], 20)
        self.assertEqual(low["sell_lots_known"], 0)
        self.assertEqual(low["high_sell_lots"], 0)
        seller = by_pair[("P", "SELLER")]
        # 賣出張數以絕對值累加(net_lots 是 -5)。
        self.assertEqual(seller["sell_lots_known"], 10)
        self.assertEqual(seller["high_sell_lots"], 10)
        # 張數的 pooled 尺 = 該股各分點的列加總。
        for row in (low, seller):
            self.assertEqual(row["stock_buy_lots_known"], 30)
            self.assertEqual(row["stock_low_buy_lots"], 20)
            self.assertEqual(row["stock_sell_lots_known"], 10)
            self.assertEqual(row["stock_high_sell_lots"], 10)

    def test_unknown_percentiles_are_counted_separately_never_as_failures(self):
        compute_branch_stock_pctile_counts(as_of=self.as_of, window_days=30)
        row = self._rows(stock_id="Q")[0]
        self.assertEqual(row["buy_pctile_unknown"], 1)
        self.assertEqual(row["buy_pctile_known"], 0)
        self.assertEqual(row["low_buy_count"], 0)
        # 分母是 known,unknown 不在分母裡,所以它既不是分子也不是分母。
        self.assertEqual(row["stock_buy_pctile_known"], 0)
        # 張數同理:不可知 episode 的 7 張不進任何 known。
        self.assertEqual(row["buy_lots_known"], 0)
        self.assertEqual(row["low_buy_lots"], 0)
        self.assertEqual(row["stock_buy_lots_known"], 0)

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


class BranchStockPctileDaytradeCountsTests(unittest.TestCase):
    """次日回吐的計數:窗口必須和分位計數同一個,而且低於門檻只是「未判定」。

    這幾個數字刻意不從 ``branch_stock_stats`` join 過來——那張表算的是全期,
    併排在同一個面板上會是兩個期間的數字。這裡測的正是「窗口有生效」。
    """

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.old_url, self.old_dir = config.DB_URL, config.DATA_DIR
        config.DB_URL = "sqlite:///" + (self.tmp_path / "dt.db").as_posix()
        config.DATA_DIR = self.tmp_path
        db._engine = None
        db.init_db()
        self.days = _market_days(date(2026, 1, 5), 40)
        self.as_of = self.days[39]
        day = self.days.__getitem__

        def buy(branch_id, index):
            return {"stock_id": "D", "date": day(index), "branch_id": branch_id,
                    "net_lots": 10, "sell_lots": 0, "pct": 1.0, "source": "fixture"}

        def next_day_sell(branch_id, index, sell_lots):
            # 次日的一列:賣出張數是要看的東西,但這一列本身不是事件
            # (|pct| < QUAL_PCT),所以不會被算成賣方 episode。
            return {"stock_id": "D", "date": day(index), "branch_id": branch_id,
                    "net_lots": -sell_lots, "sell_lots": sell_lots, "pct": -0.5,
                    "source": "fixture"}

        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": "D", "name": "Daytrade", "market": "twse", "type": "stock"},
            ])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": "D", "date": d, "open": 100, "close": 100, "adj_factor": 1.0}
                for d in self.days
            ])
            conn.execute(schema.tracked_branches.insert(), [
                {"branch_name": "FLIPPER", "source": "manual", "added_at": self.days[0]},
                {"branch_name": "NOFLIP", "source": "manual", "added_at": self.days[0]},
            ])
            conn.execute(schema.branch_dim.insert(), [
                {"id": 1, "branch_key": "flipper", "branch_name": "FLIPPER"},
                {"id": 2, "branch_key": "noflip", "branch_name": "NOFLIP"},
            ])
            conn.execute(schema.branch_trades_raw.insert(), [
                # FLIPPER 的合格買超日刻意跨在 20 日窗口的兩邊:
                # 窗口外(第 5/7/9 天)三次,三次都在次日回吐;
                # 窗口內(第 25/27/29/31 天)四次,只有第 25 天在次日回吐。
                buy(1, 5), next_day_sell(1, 6, 8),
                buy(1, 7), next_day_sell(1, 8, 8),
                buy(1, 9), next_day_sell(1, 10, 8),
                buy(1, 25), next_day_sell(1, 26, 8),
                buy(1, 27),                              # 次日完全沒有紀錄 = 0 張
                buy(1, 29), next_day_sell(1, 30, 3),     # 3 < 0.7 × 10,不算回吐
                buy(1, 31),
                # NOFLIP:窗口內剛好 8 次合格買超,一次都沒有在次日回吐。
                # 這是「判定得出來的 0 次」,與 FLIPPER 的「4 次不足以判定」不同。
                *[buy(2, index) for index in (20, 22, 24, 26, 28, 30, 32, 34)],
            ])

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self.old_url, self.old_dir
        self.tmp.cleanup()

    def _by_branch(self, window_days):
        compute_branch_stock_pctile_counts(as_of=self.as_of, window_days=window_days)
        with db.get_engine().connect() as conn:
            return {
                row["branch_name"]: dict(row)
                for row in conn.execute(text(
                    "SELECT * FROM branch_stock_pctile_counts"
                )).mappings()
            }

    def test_daytrade_counts_use_the_same_window_as_the_percentile_counts(self):
        windowed = self._by_branch(20)["FLIPPER"]
        self.assertEqual(windowed["window_market_days"], 20)
        self.assertEqual(windowed["window_from"], self.days[20])
        # 窗口內四次合格買超,其中一次次日回吐。
        self.assertEqual(windowed["daytrade_obs"], 4)
        self.assertEqual(windowed["daytrade_paybacks"], 1)
        # 分位計數同樣只數窗口內的 episode(這裡價格全平,分位一律不可知),
        # 兩組數字對得起來:同一個窗口、同一批合格買超日。
        self.assertEqual(
            windowed["buy_pctile_known"] + windowed["buy_pctile_unknown"], 4)

        # 換一個窗口,答案必須跟著變 —— 否則就代表這幾個數字不是窗口內算的
        # (例如從 branch_stock_stats 的全期數字 join 進來)。
        wider = self._by_branch(40)["FLIPPER"]
        self.assertEqual(wider["window_market_days"], 40)
        self.assertEqual(wider["daytrade_obs"], 7)
        self.assertEqual(wider["daytrade_paybacks"], 4)
        self.assertEqual(wider["buy_pctile_known"] + wider["buy_pctile_unknown"], 7)

    def test_below_minimum_observations_are_stored_raw_not_flattened(self):
        rows = self._by_branch(20)
        thin, determined = rows["FLIPPER"], rows["NOFLIP"]
        # 未達門檻的那一對照樣存原始計數,讀取端才有辦法說「未判定」。
        self.assertLess(thin["daytrade_obs"], DAYTRADE_MIN_OBS)
        self.assertEqual(thin["daytrade_obs"], 4)
        self.assertEqual(thin["daytrade_paybacks"], 1)
        # 「判定得出來的 0 次」與「不足以判定」是兩個不同的事實,而且分得出來:
        # 兩者的分子都可能是 0,唯一的區別就在分母。
        self.assertGreaterEqual(determined["daytrade_obs"], DAYTRADE_MIN_OBS)
        self.assertEqual(determined["daytrade_obs"], 8)
        self.assertEqual(determined["daytrade_paybacks"], 0)
        self.assertNotEqual(thin["daytrade_obs"], determined["daytrade_obs"])

    def test_stock_pooled_daytrade_counts_are_the_row_sums_of_that_stock(self):
        rows = self._by_branch(20)
        expected_obs = sum(row["daytrade_obs"] for row in rows.values())
        expected_paybacks = sum(row["daytrade_paybacks"] for row in rows.values())
        self.assertEqual(expected_obs, 12)
        self.assertEqual(expected_paybacks, 1)
        for name, row in rows.items():
            with self.subTest(branch=name):
                self.assertEqual(row["stock_daytrade_obs"], expected_obs)
                self.assertEqual(row["stock_daytrade_paybacks"], expected_paybacks)
                self.assertLessEqual(row["daytrade_obs"], row["stock_daytrade_obs"])
                self.assertLessEqual(row["daytrade_paybacks"], row["daytrade_obs"])


class LotsAndLongCampComputeTests(unittest.TestCase):
    """張數跟著 episode 走;長線派只換區間(120 日),不換 episode。

    個股 L 的價格(150 個市場交易日,其餘收盤 100):
      * 第 10 天 300:只在 120 日區間裡看得到。
      * 第 45 天 130、第 50 天 100:第 50 天的 20 日分位 = 0(低檔)。
      * 第 125 天 150:20 日區間是 (100,150) → 1.0;120 日區間含第 10 天的 300,
        是 (100,300) → 0.25(低檔)。同一個 episode,兩派分類不同。
    """

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.old_url, self.old_dir = config.DB_URL, config.DATA_DIR
        config.DB_URL = "sqlite:///" + (self.tmp_path / "long.db").as_posix()
        config.DATA_DIR = self.tmp_path
        db._engine = None
        db.init_db()
        self.days = _market_days(date(2025, 1, 6), 150)
        self.as_of = self.days[-1]
        closes = {10: 300, 45: 130, 125: 150}
        day = self.days.__getitem__

        def trade(index, net, pct):
            return {"stock_id": "L", "date": day(index), "branch_id": 1,
                    "net_lots": net, "sell_lots": 0, "pct": pct, "source": "fixture"}

        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": "L", "name": "Long", "market": "twse", "type": "stock"},
            ])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": "L", "date": d, "open": 100, "close": closes.get(i, 100),
                 "adj_factor": 1.0}
                for i, d in enumerate(self.days)
            ])
            conn.execute(schema.tracked_branches.insert(), [
                {"branch_name": "HOLDER", "source": "manual", "added_at": self.days[0]},
            ])
            conn.execute(schema.branch_dim.insert(), [
                {"id": 1, "branch_key": "holder", "branch_name": "HOLDER"},
            ])
            conn.execute(schema.branch_trades_raw.insert(), [
                # 第 50 天一個 40 張的 episode:短線派可知(低檔),長線派前面不足
                # 119 個交易日 → 不可知,不會改用較短的區間。
                trade(50, 40, 1.0),
                # 第 125、126 天連續兩個合格日 = 一個 episode,300 + 500 = 800 張。
                trade(125, 300, 1.0), trade(126, 500, 2.0),
                # 第 127 天同向但 pct 不合格:不在 episode 裡,50 張不算。
                trade(127, 50, 0.5),
            ])

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self.old_url, self.old_dir
        self.tmp.cleanup()

    def _row(self):
        compute_branch_stock_pctile_counts(as_of=self.as_of, window_days=150)
        with db.get_engine().connect() as conn:
            return dict(conn.execute(text(
                "SELECT * FROM branch_stock_pctile_counts WHERE branch_name = 'HOLDER'"
            )).mappings().one())

    def test_a_multi_day_episode_counts_once_with_all_its_qualifying_lots(self):
        row = self._row()
        # 短線派:兩個 episode 都可知;第 50 天低檔(40 張),第 125 天 1.0(800 張)。
        self.assertEqual(row["buy_pctile_known"], 2)
        self.assertEqual(row["low_buy_count"], 1)
        self.assertEqual(row["buy_lots_known"], 840)
        self.assertEqual(row["low_buy_lots"], 40)

    def test_the_long_camp_uses_a_120_day_range_on_the_same_episodes(self):
        row = self._row()
        # 第 125 天:短線派不是低檔,長線派是(0.25)。
        self.assertEqual(row["buy_pctile_known_120d"], 1)
        self.assertEqual(row["low_buy_count_120d"], 1)
        self.assertEqual(row["buy_lots_known_120d"], 800)
        self.assertEqual(row["low_buy_lots_120d"], 800)
        # 第 50 天:前面只有 50 個交易日,不足 120 → 不可知,不是失敗。
        self.assertEqual(row["buy_pctile_unknown_120d"], 1)
        # 兩派的 episode 總數相同:只換區間,不換 episode。
        self.assertEqual(
            row["buy_pctile_known"] + row["buy_pctile_unknown"],
            row["buy_pctile_known_120d"] + row["buy_pctile_unknown_120d"],
        )
        # 該股 pooled 的長線派尺。
        self.assertEqual(row["stock_buy_pctile_known_120d"], 1)
        self.assertEqual(row["stock_low_buy_count_120d"], 1)
        self.assertEqual(row["stock_buy_lots_known_120d"], 800)
        self.assertEqual(row["stock_low_buy_lots_120d"], 800)
        self.assertEqual(row["stock_sell_lots_known_120d"], 0)

    def test_episode_lots_sums_absolute_net_lots_of_the_episode_days_only(self):
        datemap = {"a": {"net": -300}, "b": {"net": -500}, "c": {"net": -50}}
        self.assertEqual(episode_lots(["a", "b"], datemap), 800)


class RollingCloseRangeTests(unittest.TestCase):
    """長線派用的滾動區間,與 20 日那一套的逐日重掃必須給出同一個分位。"""

    def test_matches_the_per_event_percentile_for_the_20_day_window(self):
        days = _market_days(date(2026, 1, 5), 80)
        market_index = {d: i for i, d in enumerate(days)}
        closes = [100 + ((i * 37) % 23) for i in range(80)]
        closes[30] = None   # 缺價:前後 20 天內的事件都不可知
        closes[60] = closes[59]
        row_by_date = {d: {"open": 1, "close": c} for d, c in zip(days, closes)}
        ranges = rolling_close_ranges(closes, 20)
        for index, day in enumerate(days):
            with self.subTest(index=index):
                expected = _price_observation(
                    event_date=day, market_index=market_index,
                    market_days=days, row_by_date=row_by_date,
                )
                bounds, close = ranges[index], closes[index]
                if bounds is None or close is None or bounds[0] == bounds[1]:
                    got = None
                else:
                    got = round((close - bounds[0]) / (bounds[1] - bounds[0]), 6)
                want = (expected["price_percentile_20d"]
                        if expected["price_percentile_status"] == "known" else None)
                self.assertEqual(got, want)

    def test_insufficient_history_and_gaps_are_unknown(self):
        ranges = rolling_close_ranges([1.0, 2.0, None, 4.0, 5.0, 6.0], 3)
        self.assertEqual(ranges, [None, None, None, None, None, (4.0, 6.0)])


class BranchPctileMigrationTests(unittest.TestCase):
    """既有正式檔案的表沒有新欄位:init_db 要補上,而且重跑不出錯。"""

    def test_additive_columns_are_added_idempotently_and_old_rows_stay_null(self):
        with TemporaryDirectory() as tmp:
            old_url, old_dir = config.DB_URL, config.DATA_DIR
            config.DB_URL = "sqlite:///" + (Path(tmp) / "old.db").as_posix()
            config.DATA_DIR = Path(tmp)
            db._engine = None
            try:
                with db.get_engine().begin() as conn:
                    conn.exec_driver_sql("""
                        CREATE TABLE branch_stock_pctile_counts (
                            branch_name TEXT, stock_id TEXT, as_of TEXT,
                            window_market_days INTEGER, window_from TEXT,
                            definitions_version TEXT, computed_at TEXT,
                            buy_pctile_known INTEGER, buy_pctile_unknown INTEGER,
                            low_buy_count INTEGER, sell_pctile_known INTEGER,
                            sell_pctile_unknown INTEGER, high_sell_count INTEGER,
                            stock_buy_pctile_known INTEGER, stock_low_buy_count INTEGER,
                            stock_sell_pctile_known INTEGER, stock_high_sell_count INTEGER,
                            PRIMARY KEY (branch_name, stock_id))
                    """)
                    conn.exec_driver_sql(
                        "INSERT INTO branch_stock_pctile_counts (branch_name, stock_id, "
                        "buy_pctile_known) VALUES ('甲', '1111', 9)")
                db.init_db()
                db.init_db()
                with db.get_engine().connect() as conn:
                    columns = {r[1] for r in conn.exec_driver_sql(
                        "PRAGMA table_info(branch_stock_pctile_counts)").fetchall()}
                    old = dict(conn.exec_driver_sql(
                        "SELECT * FROM branch_stock_pctile_counts").mappings().one())
                for name in (*schema.BRANCH_STOCK_PCTILE_ADDED_COLUMNS,
                             "daytrade_obs", "stock_daytrade_paybacks"):
                    with self.subTest(column=name):
                        self.assertIn(name, columns)
                        self.assertIsNone(old[name])
                self.assertEqual(old["buy_pctile_known"], 9)
            finally:
                if db._engine is not None:
                    db._engine.dispose()
                db._engine = None
                config.DB_URL, config.DATA_DIR = old_url, old_dir


def _lot_row(branch_name: str, **values) -> dict:
    """張數排序用的一列(攤平後、不帶後綴的鍵)。"""
    row = _pair_row(branch_name)
    row.update({
        "buy_lots_known": 0, "low_buy_lots": 0, "sell_lots_known": 0, "high_sell_lots": 0,
        "stock_buy_lots_known": 10000, "stock_low_buy_lots": 2250,
        "stock_sell_lots_known": 10000, "stock_high_sell_lots": 3000,
    })
    row.update(values)
    return row


def _filler_rows(count: int, lots: int) -> list[dict]:
    """決定 K 用的典型分點:買進次數不足,不會入選,只貢獻張數中位數。"""
    return [
        _lot_row(f"Z{index:03d}", buy_pctile_known=2, buy_lots_known=lots,
                 sell_pctile_known=2, sell_lots_known=lots)
        for index in range(count)
    ]


class BranchPctileLotsRankingTests(unittest.TestCase):
    """lots_shrunk_v1:張數加權、向該股基準收縮,只要求買側。"""

    def _rank(self, rows):
        return _rank_branch_pctile_rows_by_lots(rows, limit=30, min_known=5)

    def test_shrinkage_beats_a_tiny_sample_with_a_higher_raw_share(self):
        # 該股基準:買在低檔 22.5% 的張數。
        tiny = _lot_row("TINY", buy_pctile_known=8, low_buy_count=6,
                        buy_lots_known=40, low_buy_lots=35)
        heavy = _lot_row("HEAVY", buy_pctile_known=11, low_buy_count=7,
                         buy_lots_known=2350, low_buy_lots=1318)
        # 前提:原始張數比率 TINY 87.5% > HEAVY 56%。
        self.assertGreater(35 / 40, 1318 / 2350)
        ranked, shrink = self._rank([tiny, heavy, *_filler_rows(9, 300)])
        self.assertEqual([row["branch_name"] for row in ranked], ["HEAVY", "TINY"])
        self.assertEqual(shrink["shrink_k_buy_lots"], 300)

    def test_a_heavy_lot_low_buyer_outranks_a_6_of_8_count_branch(self):
        """群益金鼎-板橋的形狀:買 7/11 次、賣側 2/7 次,但張數集中在低檔。"""
        base = {"stock_buy_pctile_known": 2000, "stock_low_buy_count": 944,
                "stock_sell_pctile_known": 2000, "stock_high_sell_count": 696}
        small = _lot_row("SMALL68", buy_pctile_known=8, low_buy_count=6,
                         buy_lots_known=60, low_buy_lots=45,
                         sell_pctile_known=9, high_sell_count=5,
                         sell_lots_known=50, high_sell_lots=30, **base)
        holder = _lot_row("HOLDER", buy_pctile_known=11, low_buy_count=7,
                          buy_lots_known=2350, low_buy_lots=1318,
                          sell_pctile_known=7, high_sell_count=2,
                          sell_lots_known=400, high_sell_lots=80, **base)
        fillers = _filler_rows(9, 300)
        # v1 的次數排序:HOLDER 排在 SMALL68 後面(甚至因賣側不足不入選時也一樣)。
        counts = _rank_branch_pctile_rows([small, holder, *fillers], limit=30, min_known=5)
        self.assertEqual([row["branch_name"] for row in counts], ["SMALL68", "HOLDER"])
        ranked, _ = self._rank([small, holder, *fillers])
        self.assertEqual([row["branch_name"] for row in ranked][:2], ["HOLDER", "SMALL68"])

    def test_the_sell_side_is_not_required_and_thin_sells_are_ignored(self):
        # 兩者買側相同;A 賣側只有 2 次且張數全不在高檔——不足 5 次就不扣分。
        a = _lot_row("A", buy_pctile_known=6, low_buy_count=4,
                     buy_lots_known=600, low_buy_lots=400,
                     sell_pctile_known=2, sell_lots_known=900, high_sell_lots=0)
        b = _lot_row("B", buy_pctile_known=6, low_buy_count=4,
                     buy_lots_known=600, low_buy_lots=400)
        thin_buy = _lot_row("THINBUY", buy_pctile_known=4, low_buy_count=4,
                            buy_lots_known=5000, low_buy_lots=5000)
        ranked, _ = self._rank([b, a, thin_buy, *_filler_rows(5, 300)])
        # 同分以名稱排;買側不足 5 次的不入選,張數再多也一樣。
        self.assertEqual([row["branch_name"] for row in ranked], ["A", "B"])

    def test_a_known_sell_side_adds_its_shrunk_margin(self):
        seller = _lot_row("SELLS_HIGH", buy_pctile_known=6, buy_lots_known=600, low_buy_lots=150,
                          sell_pctile_known=6, sell_lots_known=600, high_sell_lots=500)
        plain = _lot_row("BUY_ONLY", buy_pctile_known=6, buy_lots_known=600, low_buy_lots=150)
        ranked, _ = self._rank([plain, seller, *_filler_rows(5, 300)])
        self.assertEqual([row["branch_name"] for row in ranked], ["SELLS_HIGH", "BUY_ONLY"])

    def test_k_is_the_median_of_positive_known_lots_per_side(self):
        rows = [_lot_row(name, buy_lots_known=lots, sell_lots_known=sell)
                for name, lots, sell in (("a", 0, 7), ("b", 10, 0), ("c", 20, 0), ("d", 30, 0),
                                          ("e", 40, 0))]
        self.assertEqual(_pctile_shrink_k(rows, "buy_lots_known"), 25)
        self.assertEqual(_pctile_shrink_k(rows, "sell_lots_known"), 7)
        self.assertEqual(_pctile_shrink_k([_lot_row("x")], "buy_lots_known"), 0)

    def test_the_cap_holds(self):
        rows = [_lot_row(f"B{index:02d}", buy_pctile_known=5, buy_lots_known=10, low_buy_lots=10)
                for index in range(BRANCH_PCTILE_MAX_BRANCHES + 5)]
        ranked, _ = self._rank(rows)
        self.assertEqual(len(ranked), BRANCH_PCTILE_MAX_BRANCHES)
        self.assertEqual(ranked[0]["branch_name"], "B00")


class BranchPctileRankingTests(unittest.TestCase):
    """counts_v1(舊快照的退路):排序用「超出該檔股票自身基準」的差額,不是原始比率。"""

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
            for index in range(BRANCH_PCTILE_MAX_BRANCHES + 15)
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

    _STOCK_SHORT = {
        "stock_buy_pctile_known": 1000, "stock_low_buy_count": 572,
        "stock_sell_pctile_known": 900, "stock_high_sell_count": 287,
        "stock_buy_lots_known": 50000, "stock_low_buy_lots": 11250,
        "stock_sell_lots_known": 40000, "stock_high_sell_lots": 12000,
        "stock_daytrade_obs": 800, "stock_daytrade_paybacks": 96,
    }
    _STOCK_LONG = {
        "stock_buy_pctile_known_120d": 900, "stock_low_buy_count_120d": 400,
        "stock_sell_pctile_known_120d": 800, "stock_high_sell_count_120d": 300,
        "stock_buy_lots_known_120d": 45000, "stock_low_buy_lots_120d": 9000,
        "stock_sell_lots_known_120d": 38000, "stock_high_sell_lots_120d": 11000,
    }

    @classmethod
    def _full_row(cls, name, short, long, stock_id="1111", **extra):
        """完整 v2 快照的一列。short/long 依序是 (買已知, 低檔, 賣已知, 高檔,
        買已知張數, 低檔張數, 賣已知張數, 高檔張數)。"""
        keys = ("buy_pctile_known", "low_buy_count", "sell_pctile_known", "high_sell_count",
                "buy_lots_known", "low_buy_lots", "sell_lots_known", "high_sell_lots")
        row = {"stock_id": stock_id, "branch_name": name,
               "buy_pctile_unknown": 0, "sell_pctile_unknown": 0,
               "buy_pctile_unknown_120d": 1, "sell_pctile_unknown_120d": 0,
               "daytrade_obs": 9, "daytrade_paybacks": 1,
               **cls._STOCK_SHORT, **cls._STOCK_LONG}
        row.update(zip(keys, short))
        row.update({f"{key}_120d": value for key, value in zip(keys, long)})
        row.update(extra)
        return row

    def test_v2_payload_has_two_camps_lot_fields_and_a_lookup(self):
        self._seed([
            # 兩派都入選。
            self._full_row("甲", (33, 28, 20, 14, 3300, 2500, 2000, 1500),
                           (30, 20, 18, 10, 3000, 2000, 1800, 900)),
            # 兩派買側都不足 5 次:不入選,但進 lookup。
            self._full_row("乙", (4, 4, 4, 4, 40, 40, 40, 40), (3, 3, 0, 0, 30, 30, 0, 0)),
            # 短線派入選、長線派買側只有 3 次:進短線派清單,也進 lookup(長線派要查得到)。
            self._full_row("丙", (6, 3, 0, 0, 600, 300, 0, 0), (3, 1, 0, 0, 300, 100, 0, 0)),
            # 只有分位不可知的 episode:兩派都沒有任何已知紀錄,不進 lookup。
            self._full_row("丁", (0, 0, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0, 0, 0),
                           buy_pctile_unknown=2),
        ])
        payload = self._export("1111")["branch_pctile_counts"]
        self.assertEqual(payload["version"], 2)
        self.assertEqual(payload["ranking"], "lots_shrunk_v1")
        self.assertEqual(payload["windows"], {"short": 20, "long": 120})
        self.assertEqual(payload["low_buy_max_pctile"], 0.4)
        self.assertEqual(payload["high_sell_min_pctile"], 0.6)
        self.assertEqual(payload["min_known_episodes_per_side"], 5)
        self.assertEqual(payload["max_branches"], 30)
        self.assertEqual(payload["min_daytrade_obs"], DAYTRADE_MIN_OBS)
        self.assertEqual(payload["as_of"], self.DATES[-1])
        self.assertEqual(payload["window_market_days"], 490)
        self.assertEqual(payload["window_from"], "2024-08-01")
        self.assertEqual(payload["computed_at"], "2026-08-05T23:10:00+08:00")
        self.assertEqual(payload["definitions_version"], DEFINITIONS_VERSION)
        self.assertEqual(payload["stock_daytrade_obs"], 800)
        self.assertEqual(payload["stock_daytrade_paybacks"], 96)

        short, long = payload["short"], payload["long"]
        self.assertTrue(short["available"])
        self.assertTrue(long["available"])
        # 兩把尺(次數與張數)各派一份。
        self.assertEqual(short["stock_buy_lots_known"], 50000)
        self.assertEqual(short["stock_low_buy_lots"], 11250)
        self.assertEqual(short["stock_low_buy_count"], 572)
        self.assertEqual(long["stock_buy_pctile_known"], 900)
        self.assertEqual(long["stock_high_sell_lots"], 11000)
        # K = 該側已知張數 > 0 的分點之中位數:短線派買側 [40, 600, 3300] → 600。
        self.assertEqual(short["shrink_k_buy_lots"], 600)
        self.assertEqual(short["shrink_k_sell_lots"], (40 + 2000) / 2)
        self.assertEqual(long["shrink_k_buy_lots"], 300)

        self.assertEqual({b["branch_name"] for b in short["branches"]}, {"甲", "丙"})
        self.assertEqual([b["branch_name"] for b in long["branches"]], ["甲"])
        first = next(b for b in short["branches"] if b["branch_name"] == "甲")
        self.assertEqual(first, {
            "branch_name": "甲", "buy_pctile_known": 33, "buy_pctile_unknown": 0,
            "low_buy_count": 28, "sell_pctile_known": 20, "sell_pctile_unknown": 0,
            "high_sell_count": 14, "buy_lots_known": 3300, "low_buy_lots": 2500,
            "sell_lots_known": 2000, "high_sell_lots": 1500,
            "daytrade_obs": 9, "daytrade_paybacks": 1,
        })
        # 次日回吐只屬於短線派。
        self.assertNotIn("daytrade_obs", long["branches"][0])
        self.assertEqual(long["branches"][0]["low_buy_lots"], 2000)
        self.assertEqual(long["branches"][0]["buy_pctile_unknown"], 1)

        self.assertEqual(payload["lookup_fields"], list(BRANCH_PCTILE_LOOKUP_FIELDS))
        self.assertEqual(len(payload["lookup_fields"]), 17)
        self.assertEqual(payload["lookup_fields"][:2], ["branch_name", "short.buy_pctile_known"])
        self.assertEqual(payload["lookup_fields"][-1], "long.high_sell_lots")
        lookup = {entry[0]: dict(zip(payload["lookup_fields"], entry))
                  for entry in payload["lookup"]}
        # 甲兩派都在清單裡 → 不重複放;丁沒有任何已知紀錄 → 不放。
        self.assertEqual(sorted(lookup), sorted(["乙", "丙"]))
        self.assertEqual(lookup["乙"]["short.buy_pctile_known"], 4)
        self.assertEqual(lookup["乙"]["short.low_buy_lots"], 40)
        self.assertEqual(lookup["丙"]["long.buy_pctile_known"], 3)
        self.assertEqual(lookup["丙"]["long.low_buy_lots"], 100)
        # 沒有任何判定欄位:沒有比率、沒有旗標、沒有分數或名次。
        for camp in (short, long):
            for row in camp["branches"]:
                for banned in ("rate", "score", "rank", "flag", "is_key", "win", "profit", "margin"):
                    with self.subTest(banned=banned):
                        self.assertFalse([k for k in row if banned in k])

    def test_an_old_snapshot_without_lots_falls_back_to_the_count_ranking(self):
        legacy = {
            "buy_pctile_unknown": 0, "sell_pctile_unknown": 0,
            "stock_buy_pctile_known": 1000, "stock_low_buy_count": 572,
            "stock_sell_pctile_known": 900, "stock_high_sell_count": 287,
        }
        self._seed([
            {"stock_id": "1111", "branch_name": "甲", "buy_pctile_known": 33,
             "low_buy_count": 28, "sell_pctile_known": 20, "high_sell_count": 14, **legacy},
            # v1 規則仍要求兩側各 5 次:賣側 2 次 → 不入選,但查得到。
            {"stock_id": "1111", "branch_name": "乙", "buy_pctile_known": 30,
             "low_buy_count": 30, "sell_pctile_known": 2, "high_sell_count": 2, **legacy},
        ])
        payload = self._export("1111")["branch_pctile_counts"]
        self.assertEqual(payload["version"], 2)
        self.assertEqual(payload["ranking"], "counts_v1")
        self.assertEqual([b["branch_name"] for b in payload["short"]["branches"]], ["甲"])
        self.assertIsNone(payload["short"]["branches"][0]["buy_lots_known"])
        self.assertIsNone(payload["short"]["shrink_k_buy_lots"])
        self.assertIsNone(payload["short"]["stock_buy_lots_known"])
        # 長線派在舊快照裡沒有算:明講 unavailable,不是空的排行。
        self.assertFalse(payload["long"]["available"])
        self.assertEqual(payload["long"]["branches"], [])
        entry = dict(zip(payload["lookup_fields"], payload["lookup"][0]))
        self.assertEqual(entry["branch_name"], "乙")
        self.assertEqual(entry["short.buy_pctile_known"], 30)
        self.assertIsNone(entry["short.buy_lots_known"])
        self.assertIsNone(entry["long.buy_pctile_known"])

    def test_a_stock_with_no_rows_emits_empty_lists_not_missing_keys(self):
        self._seed([
            self._full_row("甲", (9, 9, 9, 9, 90, 90, 90, 90), (9, 9, 9, 9, 90, 90, 90, 90)),
        ])
        payload = self._export("2222")["branch_pctile_counts"]
        self.assertEqual(payload["ranking"], "lots_shrunk_v1")
        for camp in ("short", "long"):
            with self.subTest(camp=camp):
                self.assertTrue(payload[camp]["available"])
                self.assertEqual(payload[camp]["branches"], [])
                # 這檔股票在快照裡完全沒有列,所以它自己的基準是「不知道」,不是 0。
                self.assertIsNone(payload[camp]["stock_buy_pctile_known"])
                self.assertIsNone(payload[camp]["stock_buy_lots_known"])
        self.assertIsNone(payload["stock_daytrade_obs"])
        self.assertEqual(payload["lookup"], [])
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
        self.assertEqual(payload["short"]["branches"], [])
        self.assertEqual(payload["long"]["branches"], [])
        self.assertEqual(payload["lookup"], [])
        self.assertIsNone(payload["as_of"])


if __name__ == "__main__":
    unittest.main()
