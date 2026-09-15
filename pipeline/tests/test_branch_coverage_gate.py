"""分點匯入的日期合格判準:分母是**這一輪自己要的股票檔數**,不是歷史基準。

改動前 `import_branch_trades` 的 status 兩個方向都錯:

- 太嚴:1,988 檔裡有 1 檔失敗就把整天標成 `error`(實測
  `date=2026-09-14 rows=57265 status=error error="1 stocks failed"`,其實有
  1,987 檔正確匯入)。
- 太鬆,而這個危險得多:來源整個死掉**不會**產生 `error`。鏡像站送出佔位頁,
  解析成 0 列 → `NoDataError` → 記成 empty 然後 continue;`failed == 0`,於是
  整輪記成 `status='ok', rows=0`,晚上那輪照樣在一個沒有分點資料的日期上算
  籌碼並上線。

第一版用「最近 60 個交易日同一統計量的高分位數」當分母。那個工具是為
`_market_reference` 的上櫃/融資呼叫者設計的——它們真的不知道交易所今天會公布
幾列。分點匯入不一樣:它自己建目標清單,分母同一天就精確已知。這個檔案測的是
改用已知分母之後的判準:

    ratio      = min(1.0, coverage / expected)
    error      coverage == 0 或 ratio < 0.5           (扣留閘門,共用參數)
    incomplete ratio < 0.8 或 failed > 0              (警報,本呼叫路徑專用)
    ok         其餘
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

DATE = "2026-09-14"
DATE_COMPACT = "20260914"
# 12 檔普通股都在當日 daily_prices 裡,所以 `--top 0` 的分母恰好是 12。
STOCKS = [f"10{i:02d}" for i in range(12)]


def _branch_rows(stock_id, date):
    return [{
        "stock_id": stock_id, "date": date,
        "branch_key": "b1", "branch_name": "分點1", "broker_id": "999",
        "buy_lots": 5, "sell_lots": 1, "net_lots": 4, "pct": 1.0,
    }]


def _raw_rows(stock_ids, date):
    return [{"stock_id": sid, "date": date, "branch_id": 1,
             "buy_lots": 5, "sell_lots": 1, "net_lots": 4, "pct": 1.0}
            for sid in stock_ids]


class _BranchCoverageBase(unittest.TestCase):
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
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": sid, "date": DATE, "close": 100,
                 "volume": 1, "turnover": 1} for sid in STOCKS
            ])

    def _log_rows(self, dataset):
        with db.get_engine().connect() as conn:
            return conn.exec_driver_sql(
                "SELECT date, rows, status, COALESCE(error,'') FROM import_logs "
                f"WHERE dataset='{dataset}' ORDER BY id"
            ).fetchall()

    def _run(self, fetch, **kw):
        kw.setdefault("top", 0)
        kw.setdefault("warrants", 0)
        with patch("radar.providers.fubon.fetch_branch_trades", side_effect=fetch):
            return import_branch_trades(DATE_COMPACT, sleep_s=0, **kw)

    def _run_cli(self, fetch):
        with patch("radar.providers.fubon.fetch_branch_trades", side_effect=fetch):
            try:
                cli.main(["import-branch-trades", "--date", DATE_COMPACT,
                          "--top", "0", "--warrants", "0", "--sleep", "0"])
            except SystemExit as exc:
                return exc.code
        return 0


def _all_ok(sid, date, throttle=None):
    return _branch_rows(sid, DATE)


def _no_data(sid, date, throttle=None):
    raise NoDataError("placeholder page")


def _missing(ids):
    """對 `ids` 裡的標的回佔位頁(empty),其餘正常。"""
    def fetch(sid, date, throttle=None):
        if sid in ids:
            raise NoDataError("placeholder page")
        return _branch_rows(sid, DATE)
    return fetch


class BranchDateFitnessTests(_BranchCoverageBase):
    def test_full_coverage_is_ok(self):
        info = self._run(_all_ok)
        self.assertEqual((info["done"], info["failed"], info["status"]),
                         (12, 0, "ok"))
        self.assertEqual((info["coverage"], info["expected"]), (12, 12))
        self.assertEqual(info["ratio"], 1.0)
        self.assertTrue(info["fit"])
        self.assertFalse(info["dead_feed"])
        self.assertEqual(self._log_rows("branch")[-1][2], "ok")
        self.assertEqual(self._run_cli(_all_ok), 0)

    def test_one_stock_failing_is_incomplete_not_error(self):
        """1/1988 檔失敗 = `incomplete`——這一天仍然可以上線,而且比例仍健康。"""
        def fetch(sid, date, throttle=None):
            if sid == STOCKS[0]:
                raise RuntimeError("HTTP 500")
            return _branch_rows(sid, DATE)

        info = self._run(fetch)
        self.assertEqual((info["done"], info["failed"]), (11, 1))
        self.assertAlmostEqual(info["ratio"], 11 / 12)
        self.assertTrue(info["fit"])
        self.assertEqual(info["status"], "incomplete")
        row = self._log_rows("branch")[-1]
        # 只由 failed 造成的 incomplete,理由字串裡不可以出現覆蓋率警報。
        self.assertEqual((row[2], row[3]), ("incomplete", "1 stocks failed"))
        self.assertEqual(self._run_cli(fetch), cli.BRANCH_IMPORT_INCOMPLETE_EXIT)

    def test_ratio_alarm_fires_with_zero_failures(self):
        """兩個 incomplete 成因互相獨立:一檔都沒失敗,純粹覆蓋率不足也要警報。

        9/12 = 75%,在 0.5 的扣留閘門之上(照樣上線)、在 0.8 的警報線之下。
        """
        fetch = _missing(STOCKS[9:])
        info = self._run(fetch)
        self.assertEqual((info["done"], info["empty"], info["failed"]), (9, 3, 0))
        self.assertAlmostEqual(info["ratio"], 0.75)
        self.assertTrue(info["fit"], "75% 仍然可以上線")
        self.assertEqual(info["status"], "incomplete")
        row = self._log_rows("branch")[-1]
        self.assertIn("9/12", row[3])
        self.assertIn("alarm", row[3])
        self.assertNotIn("failed", row[3], "沒有任何標的失敗")
        # 離開碼合約不變:警報不影響 exit code,failed == 0 且有抓到東西 = 0。
        self.assertEqual(self._run_cli(fetch), 0)

    def test_both_incomplete_causes_are_reported_together(self):
        def fetch(sid, date, throttle=None):
            if sid in STOCKS[9:]:
                raise NoDataError("placeholder page")
            if sid == STOCKS[0]:
                raise RuntimeError("HTTP 500")
            return _branch_rows(sid, DATE)

        info = self._run(fetch)
        self.assertEqual((info["failed"], info["status"]), (1, "incomplete"))
        reason = self._log_rows("branch")[-1][3]
        self.assertIn("alarm", reason)
        self.assertIn("1 stocks failed", reason)

    def test_partial_collapse_below_the_publish_floor_is_error(self):
        """5/12 ≈ 42% < 50%:不只是「掉到 0」才扣留。"""
        fetch = _missing(STOCKS[5:])
        info = self._run(fetch)
        self.assertEqual((info["coverage"], info["expected"]), (5, 12))
        self.assertFalse(info["fit"])
        self.assertEqual(info["status"], "error")
        reason = self._log_rows("branch")[-1][3]
        self.assertIn("42%", reason)
        self.assertIn("publish floor", reason)
        self.assertEqual(self._run_cli(fetch), 1)

    def test_dead_feed_parsing_to_zero_rows_is_error_not_ok(self):
        """佔位頁 → NoDataError → 舊版記 `ok, rows=0`。覆蓋率 0,現在是 error。"""
        info = self._run(_no_data)
        self.assertEqual((info["done"], info["empty"], info["failed"]), (0, 12, 0))
        self.assertEqual(info["coverage"], 0)
        self.assertEqual(info["ratio"], 0.0)
        self.assertFalse(info["fit"])
        self.assertEqual(info["status"], "error")
        self.assertIn("coverage 0", self._log_rows("branch")[-1][3])
        # 日期不合格時離開碼是 1,76 不得蓋過真失敗。
        self.assertEqual(self._run_cli(_no_data), 1)

    def test_cumulative_coverage_beyond_this_runs_targets_clamps_to_one(self):
        """同一天 17:40 已覆蓋全宇宙,22:00 只補抓兩檔:比例不可以變成 600%。"""
        with db.get_engine().begin() as conn:
            conn.execute(schema.branch_trades_raw.insert(), _raw_rows(STOCKS, DATE))

        info = self._run(_all_ok, ids=STOCKS[:2])
        self.assertEqual((info["coverage"], info["expected"]), (12, 2))
        self.assertEqual(info["ratio"], 1.0, "min(1.0, ...) 夾住累積覆蓋")
        self.assertEqual(info["status"], "ok")

    def test_dead_round_on_an_already_fit_date_alarms_without_withholding(self):
        """兩個訊號互相獨立:這一輪什麼都沒抓到,但 17:40 那輪已經把日期填滿。

        publish 閘門看的是**累積**的日期覆蓋率(同一天 17:40/22:00 upsert 同一組
        key),死來源警報看的是**單輪**的 done == 0。所以這裡 status 仍是 ok、
        離開碼是 76,而不是 1。
        """
        with db.get_engine().begin() as conn:
            conn.execute(schema.branch_trades_raw.insert(), _raw_rows(STOCKS, DATE))

        info = self._run(_no_data)
        self.assertEqual(info["done"], 0)
        self.assertTrue(info["dead_feed"])
        self.assertTrue(info["fit"], "日期本身仍然合格")
        self.assertEqual(info["status"], "ok")
        self.assertEqual(self._log_rows("branch")[-1][2], "ok")
        self.assertEqual(self._run_cli(_no_data), cli.BRANCH_FEED_DEAD_EXIT)
        self.assertNotEqual(cli.BRANCH_FEED_DEAD_EXIT,
                            cli.BRANCH_IMPORT_INCOMPLETE_EXIT)

    def test_retry_pass_converts_a_transient_miss_into_done(self):
        """恰好一次的重試:第一次失敗、第二次成功的標的算 done,列數也要算進去。"""
        seen = {}

        def fetch(sid, date, throttle=None):
            seen[sid] = seen.get(sid, 0) + 1
            if sid == STOCKS[0] and seen[sid] == 1:
                raise RuntimeError("transient reset")
            return _branch_rows(sid, DATE)

        info = self._run(fetch)
        self.assertEqual(seen[STOCKS[0]], 2, "失敗的標的要被重試,而且只重試一次")
        self.assertEqual(seen[STOCKS[1]], 1, "成功的標的不重抓")
        self.assertEqual((info["done"], info["failed"], info["status"]),
                         (12, 0, "ok"))
        self.assertEqual(info["rows"], 12, "重試成功的列數要算進 written")

    def test_retry_is_exactly_one_pass(self):
        def fetch(sid, date, throttle=None):
            if sid == STOCKS[0]:
                raise RuntimeError("HTTP 500")
            return _branch_rows(sid, DATE)

        with patch("radar.providers.fubon.fetch_branch_trades",
                   side_effect=fetch) as spy:
            import_branch_trades(DATE_COMPACT, top=0, warrants=0, sleep_s=0)
        attempts = [c.args[0] for c in spy.call_args_list]
        self.assertEqual(attempts.count(STOCKS[0]), 2, "只重試一次,不是重試框架")

    def test_warrant_rows_do_not_move_the_numerator(self):
        """`JOIN stocks ... type='stock'` 是承重的:權證分點列共用同一張表。

        一個被權證回補掃過的日期會多帶上萬個 distinct stock_id;少了這個 JOIN,
        分子會隨「另一支不相干的爬蟲跑到哪一天」跳一個數量級。
        """
        fetch = _missing(STOCKS[5:])
        self.assertEqual(self._run(fetch)["coverage"], 5)

        with db.get_engine().begin() as conn:
            # 兩種都要擋掉:stocks 裡標成 warrant 的,和根本不在 stocks 裡的。
            conn.execute(schema.stocks.insert(), [
                {"id": f"9{i:03d}", "name": "warrant", "market": "twse",
                 "type": "warrant", "is_active": 1} for i in range(50)
            ])
            conn.execute(schema.branch_trades_raw.insert(),
                         _raw_rows([f"9{i:03d}" for i in range(50)], DATE)
                         + _raw_rows([f"W{i:04d}" for i in range(50)], DATE))

        after = self._run(fetch)
        self.assertEqual(after["coverage"], 5, "100 列權證分點不可以讓這天看起來健康")
        self.assertFalse(after["fit"])
        self.assertEqual(after["status"], "error")

    def test_warrant_targets_do_not_inflate_the_denominator(self):
        """分母必須在權證目標被接上去之前量,否則比例會被靜默灌水。

        權證不進分子(`_branch_coverage` JOIN 了 `type='stock'`),所以把它們算進
        分母,一個 100% 健康的日子會被算成 12/14 = 86%。
        """
        with db.get_engine().begin() as conn:
            conn.execute(schema.warrants.insert(), [
                {"id": "WA", "name": "wa", "market": "twse", "kind": "call",
                 "stock_id": STOCKS[0]},
                {"id": "WB", "name": "wb", "market": "twse", "kind": "put",
                 "stock_id": STOCKS[1]},
            ])
            conn.execute(schema.warrant_daily.insert(), [
                {"warrant_id": "WA", "date": DATE, "close": 1,
                 "volume": 1, "turnover": 900},
                {"warrant_id": "WB", "date": DATE, "close": 1,
                 "volume": 1, "turnover": 800},
            ])

        info = self._run(_all_ok, warrants=2)
        self.assertEqual(info["targets"], 14, "權證確實有被抓")
        self.assertEqual(info["expected"], 12, "但它們不進分母")
        self.assertEqual(info["ratio"], 1.0)
        self.assertEqual(info["status"], "ok")

        # threshold 模式走另一段 SQL,同樣不可以動到分母。
        info = self._run(_all_ok, warrants=0, warrant_turnover_min=100)
        self.assertEqual(info["targets"], 14)
        self.assertEqual(info["expected"], 12)
        self.assertEqual(info["status"], "ok")

    def test_predicate_inputs_are_logged_every_run(self):
        """分子分母同列留痕:同一天跑兩輪,分兩列的話讀日誌的人得自己配對。"""
        self._run(_missing(STOCKS[9:]))
        rows = self._log_rows("branch_coverage")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][:3], (DATE, 9, "ok"))
        self.assertIn("expected=12", rows[0][3])
        self.assertIn("ratio=0.75", rows[0][3])

    def test_branch_coverage_dataset_collides_with_nothing(self):
        """新 dataset 名稱不可以落進既有的 dataset 過濾條件裡。"""
        from radar.export import json_export

        source = Path(json_export.__file__).read_text(encoding="utf-8")
        self.assertIn("dataset IN ('quotes','insti','margin')", source)
        self.assertNotIn("branch_coverage", source)

    def test_history_is_no_longer_consulted(self):
        """判準只看同一天:前一天全滅、或根本沒有歷史,都不改變今天的結論。"""
        info = self._run(_all_ok)
        self.assertEqual(info["status"], "ok")
        self.assertNotIn("reference", info)
        self.assertNotIn("baseline_samples", info)


if __name__ == "__main__":
    unittest.main()
