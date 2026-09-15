"""分點匯入的日期合格判準:status 欄要能分辨「完美」和「全滅」。

改動前 `import_branch_trades` 的 status 兩個方向都錯:

- 太嚴:1,988 檔裡有 1 檔失敗就把整天標成 `error`(實測
  `date=2026-09-14 rows=57265 status=error error="1 stocks failed"`,其實有
  1,987 檔正確匯入)。
- 太鬆,而這個危險得多:來源整個死掉**不會**產生 `error`。鏡像站送出佔位頁,
  解析成 0 列 → `NoDataError` → 記成 empty 然後 continue;`failed == 0`,於是
  整輪記成 `status='ok', rows=0`,晚上那輪照樣在一個沒有分點資料的日期上算
  籌碼並上線。

現在合格與否由「這個日期有多少比例的股票宇宙拿到分點資料」決定,並和最近交易日
的同一統計量比對(重用 `_market_reference` 那套 `_quantile` /
`_REFERENCE_QUANTILE` / `_MIN_MARKET_SAMPLES` / `min_market_fraction`)。
"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import radar.cli as cli
import radar.config as config
import radar.db as db
from radar import schema
from radar.importer import import_branch_trades
from radar.providers import NoDataError

# 被評估的交易日,以及它前面 10 個交易日(基準窗)。
DATE = "2026-09-14"
DATE_COMPACT = "20260914"
BASELINE_DATES = [f"2026-09-{d:02d}" for d in range(1, 11)]  # 09-01..09-10
STOCKS = [f"10{i:02d}" for i in range(12)]  # 1000..1011,全部 type='stock'
COVERED = STOCKS[:10]  # 基準日每天都有這 10 檔的分點資料


def _branch_rows(stock_id, date):
    return [{
        "stock_id": stock_id, "date": date,
        "branch_key": "b1", "branch_name": "分點1", "broker_id": "999",
        "buy_lots": 5, "sell_lots": 1, "net_lots": 4, "pct": 1.0,
    }]


class _BranchCoverageBase(unittest.TestCase):
    baseline_dates = BASELINE_DATES

    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._old_url, self._old_dir = config.DB_URL, config.DATA_DIR
        config.DATA_DIR = tmp
        config.DB_URL = "sqlite:///" + (tmp / "t.db").as_posix()
        db._engine = None
        db.init_db()
        self._seed()

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old_url, self._old_dir
        self._tmp.cleanup()

    def _seed(self):
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": sid, "name": f"s{sid}", "market": "twse",
                 "type": "stock", "is_active": 1} for sid in STOCKS
            ])
            conn.execute(schema.branch_dim.insert(),
                         {"id": 1, "branch_key": "b1", "branch_name": "分點1"})
            # 交易日曆來自 daily_prices(而不是「有分點列的日期」)。
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": sid, "date": d, "close": 100, "volume": 1, "turnover": 1}
                for d in self.baseline_dates + [DATE] for sid in STOCKS
            ])
            if self.baseline_dates:
                conn.execute(schema.branch_trades_raw.insert(), [
                    {"stock_id": sid, "date": d, "branch_id": 1,
                     "buy_lots": 5, "sell_lots": 1, "net_lots": 4, "pct": 1.0}
                    for d in self.baseline_dates for sid in COVERED
                ])

    def _log_rows(self, dataset):
        with db.get_engine().connect() as conn:
            return conn.exec_driver_sql(
                "SELECT date, rows, status, COALESCE(error,'') FROM import_logs "
                f"WHERE dataset='{dataset}' ORDER BY id"
            ).fetchall()

    def _run(self, fetch, ids=None):
        with patch("radar.providers.fubon.fetch_branch_trades", side_effect=fetch):
            return import_branch_trades(DATE_COMPACT, ids=ids or COVERED,
                                        warrants=0, sleep_s=0)

    def _run_cli(self, fetch, ids=None):
        with patch("radar.providers.fubon.fetch_branch_trades", side_effect=fetch):
            try:
                cli.main(["import-branch-trades", "--date", DATE_COMPACT,
                          "--ids", ",".join(ids or COVERED),
                          "--warrants", "0", "--sleep", "0"])
            except SystemExit as exc:
                return exc.code
        return 0


class BranchDateFitnessTests(_BranchCoverageBase):
    def test_full_day_is_ok(self):
        info = self._run(lambda sid, date, throttle=None: _branch_rows(sid, DATE))
        self.assertEqual((info["done"], info["failed"], info["status"]), (10, 0, "ok"))
        self.assertEqual(info["coverage"], 10)
        self.assertEqual(info["reference"], 10)
        self.assertEqual(info["baseline_samples"], 10)
        self.assertTrue(info["fit"])
        self.assertFalse(info["dead_feed"])
        self.assertEqual(self._log_rows("branch")[-1][2], "ok")
        self.assertEqual(self._run_cli(
            lambda sid, date, throttle=None: _branch_rows(sid, DATE)), 0)

    def test_one_stock_failing_does_not_condemn_the_day(self):
        """1/1988 檔失敗 = `incomplete`,不是 `error`——這一天仍然可以上線。"""
        def fetch(sid, date, throttle=None):
            if sid == COVERED[0]:
                raise RuntimeError("HTTP 500")
            return _branch_rows(sid, DATE)

        info = self._run(fetch)
        self.assertEqual((info["done"], info["failed"]), (9, 1))
        self.assertTrue(info["fit"], "9/10 檔仍在帶內")
        self.assertEqual(info["status"], "incomplete")
        row = self._log_rows("branch")[-1]
        self.assertEqual((row[2], row[3]), ("incomplete", "1 stocks failed"))
        self.assertEqual(self._run_cli(fetch), cli.BRANCH_IMPORT_INCOMPLETE_EXIT)

    def test_dead_feed_parsing_to_zero_rows_is_error_not_ok(self):
        """佔位頁 → NoDataError → 舊版記 `ok, rows=0`。覆蓋率掉到 0,現在是 error。"""
        def fetch(sid, date, throttle=None):
            raise NoDataError("placeholder page")

        info = self._run(fetch)
        self.assertEqual((info["done"], info["empty"], info["failed"]), (0, 10, 0))
        self.assertEqual(info["coverage"], 0)
        self.assertFalse(info["fit"])
        self.assertEqual(info["status"], "error")
        row = self._log_rows("branch")[-1]
        self.assertEqual(row[2], "error")
        self.assertIn("coverage 0", row[3])
        self.assertIn("reference 10", row[3])
        # 日期不合格時離開碼是 1,76 不得蓋過真失敗。
        self.assertEqual(self._run_cli(fetch), 1)

    def test_partial_collapse_below_the_band_is_error(self):
        """帶外不只是「掉到 0」:10 → 4 檔(< 50% of 10)也不可以上線。"""
        def fetch(sid, date, throttle=None):
            if sid in COVERED[4:]:
                raise NoDataError("placeholder page")
            return _branch_rows(sid, DATE)

        info = self._run(fetch)
        self.assertEqual(info["coverage"], 4)
        self.assertFalse(info["fit"])
        self.assertEqual(info["status"], "error")
        self.assertIn("below 50%", self._log_rows("branch")[-1][3])

    def test_dead_round_on_an_already_fit_date_alarms_without_withholding(self):
        """兩個訊號互相獨立:這一輪什麼都沒抓到,但 17:40 那輪已經把日期填滿。

        publish 閘門看的是**累積**的日期覆蓋率(同一天 17:40/22:00 upsert 同一組
        key),死來源警報看的是**單輪**的 done == 0。所以這裡 status 仍是 ok、
        離開碼是 76,而不是 1。
        """
        with db.get_engine().begin() as conn:  # 17:40 那輪的成果
            conn.execute(schema.branch_trades_raw.insert(), [
                {"stock_id": sid, "date": DATE, "branch_id": 1,
                 "buy_lots": 5, "sell_lots": 1, "net_lots": 4, "pct": 1.0}
                for sid in COVERED
            ])

        def fetch(sid, date, throttle=None):
            raise NoDataError("placeholder page")

        info = self._run(fetch)
        self.assertEqual(info["done"], 0)
        self.assertTrue(info["dead_feed"])
        self.assertTrue(info["fit"], "日期本身仍然合格")
        self.assertEqual(info["status"], "ok")
        self.assertEqual(self._log_rows("branch")[-1][2], "ok")
        self.assertEqual(self._run_cli(fetch), cli.BRANCH_FEED_DEAD_EXIT)
        self.assertNotEqual(cli.BRANCH_FEED_DEAD_EXIT, cli.BRANCH_IMPORT_INCOMPLETE_EXIT)

    def test_retry_pass_converts_a_transient_miss_into_done(self):
        """恰好一次的重試:第一次失敗、第二次成功的標的算 done,列數也要算進去。"""
        seen = {}

        def fetch(sid, date, throttle=None):
            seen[sid] = seen.get(sid, 0) + 1
            if sid == COVERED[0] and seen[sid] == 1:
                raise RuntimeError("transient reset")
            return _branch_rows(sid, DATE)

        info = self._run(fetch)
        self.assertEqual(seen[COVERED[0]], 2, "失敗的標的要被重試,而且只重試一次")
        self.assertEqual(seen[COVERED[1]], 1, "成功的標的不重抓")
        self.assertEqual((info["done"], info["failed"], info["status"]), (10, 0, "ok"))
        self.assertEqual(info["rows"], 10, "重試成功的列數要算進 written")

    def test_retry_is_exactly_one_pass(self):
        def fetch(sid, date, throttle=None):
            if sid == COVERED[0]:
                raise RuntimeError("HTTP 500")
            return _branch_rows(sid, DATE)

        with patch("radar.providers.fubon.fetch_branch_trades",
                   side_effect=fetch) as spy:
            import_branch_trades(DATE_COMPACT, ids=COVERED, warrants=0, sleep_s=0)
        attempts = [c.args[0] for c in spy.call_args_list]
        self.assertEqual(attempts.count(COVERED[0]), 2, "只重試一次,不是重試框架")

    def test_warrant_rows_do_not_move_the_statistic(self):
        """`JOIN stocks ... type='stock'` 是承重的:權證分點列共用同一張表。

        一個被權證回補掃過的日期會多帶上萬個 distinct stock_id;少了這個 JOIN,
        統計量會隨「另一支不相干的爬蟲跑到哪一天」跳一個數量級。
        """
        def fetch(sid, date, throttle=None):
            if sid in COVERED[4:]:
                raise NoDataError("placeholder page")
            return _branch_rows(sid, DATE)

        baseline_info = self._run(fetch)
        self.assertEqual(baseline_info["coverage"], 4)

        with db.get_engine().begin() as conn:
            # 兩種都要擋掉:stocks 裡標成 warrant 的,和根本不在 stocks 裡的。
            conn.execute(schema.stocks.insert(), [
                {"id": f"9{i:03d}", "name": "warrant", "market": "twse",
                 "type": "warrant", "is_active": 1} for i in range(50)
            ])
            conn.execute(schema.branch_trades_raw.insert(), [
                {"stock_id": f"9{i:03d}", "date": DATE, "branch_id": 1,
                 "buy_lots": 1, "sell_lots": 1, "net_lots": 0, "pct": 0.1}
                for i in range(50)
            ] + [
                {"stock_id": f"W{i:04d}", "date": DATE, "branch_id": 1,
                 "buy_lots": 1, "sell_lots": 1, "net_lots": 0, "pct": 0.1}
                for i in range(50)
            ])

        after_info = self._run(fetch)
        self.assertEqual(after_info["coverage"], 4,
                         "100 列權證分點資料不可以讓這一天看起來健康")
        self.assertFalse(after_info["fit"])
        self.assertEqual(after_info["status"], "error")

    def test_predicate_inputs_are_logged_every_run(self):
        """判準看到的數字每晚留痕,否則帶狀判斷可能悄悄啟用而從沒被驗證過。"""
        self._run(lambda sid, date, throttle=None: _branch_rows(sid, DATE))
        rows = self._log_rows("branch_coverage")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][:3], (DATE, 10, "ok"))

    def test_branch_coverage_dataset_collides_with_nothing(self):
        """新 dataset 名稱不可以落進既有的 dataset 過濾條件裡。"""
        from radar.export import json_export

        source = Path(json_export.__file__).read_text(encoding="utf-8")
        self.assertIn("dataset IN ('quotes','insti','margin')", source)
        self.assertNotIn("branch_coverage", source)


class BranchColdStartTests(_BranchCoverageBase):
    """基準樣本不足時退回只做地板檢查——而不是靜默跳過檢查。"""

    baseline_dates = BASELINE_DATES[:3]  # < _MIN_MARKET_SAMPLES

    def test_thin_history_still_floors_at_nonzero_coverage(self):
        info = self._run(lambda sid, date, throttle=None: _branch_rows(sid, DATE))
        self.assertEqual(info["baseline_samples"], 3)
        self.assertIsNone(info["reference"], "樣本不足時不建立基準")
        self.assertTrue(info["fit"])
        self.assertEqual(info["status"], "ok")

    def test_thin_history_does_not_excuse_a_dead_feed(self):
        def fetch(sid, date, throttle=None):
            raise NoDataError("placeholder page")

        info = self._run(fetch)
        self.assertEqual(info["coverage"], 0)
        self.assertFalse(info["fit"], "樣本不足不等於不檢查")
        self.assertEqual(info["status"], "error")
        self.assertIn("floor test", self._log_rows("branch")[-1][3])


if __name__ == "__main__":
    unittest.main()
