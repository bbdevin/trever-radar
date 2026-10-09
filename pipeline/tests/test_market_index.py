"""大盤指數(docs/49 §11、§12):來源解析對 fixture 逐值相同、台指期近月、匯入/回補/離開碼、
export 的 indices(含 spark)/insti_market/market/indices_hist.json。

不連網:三個 fetch 一律 mock;fixture 是抓回來的原始回應(TWSE MI_INDEX type=IND 2026-10-08、
TPEx tradingIndex 2026-10 整月、TAIFEX futDataDown 2026-09-10/11 兩天,與 import-futures 共用)。
"""
import contextlib
import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import radar.config as config
import radar.db as db
from radar import cli, schema
from radar.export.json_export import export_json
from radar.market_index import (
    HIST_N, SPARK_N, backfill_market_index, import_market_index, indices_hist, latest_indices,
)
from radar.providers import NoDataError
from radar.providers import market_index as src
from radar.providers.taifex import SESSION_AFTER_HOURS, SESSION_REGULAR, FuturesDailyRow, parse_history_csv

FX = Path(__file__).parent / "fixtures"
TWSE_FX = json.loads((FX / "twse_mi_index_ind_20261008.json").read_text(encoding="utf-8"))
TPEX_FX = json.loads((FX / "tpex_trading_index_20261008.json").read_text(encoding="utf-8"))
TAIFEX_FX = parse_history_csv((FX / "taifex_fut_history.csv").read_bytes())


def _fut(code, d, month, session=SESSION_REGULAR, last=100.0, change=1.0, settle=100.5, volume=10):
    return FuturesDailyRow(contract_code=code, date=d, contract_month=month, session=session,
                           open=1.0, high=1.0, low=1.0, last=last, change=change, volume=volume,
                           settlement_price=settle, open_interest=1)


class ParseFixtures(unittest.TestCase):
    def test_twse_taiex_row_matches_source_exactly(self):
        r = src.parse_twse_index(TWSE_FX, "20261008")
        self.assertEqual((r.market, r.date), ("twse", "2026-10-08"))
        # 來源:發行量加權股價指數 49,313.44、漲跌(+/-)=-、492.93、-0.99
        self.assertEqual(r.close, 49313.44)
        self.assertEqual(r.change, -492.93)
        self.assertEqual(r.chg_pct, -0.99)
        self.assertIsNone(r.contract_month)

    def test_twse_sign_comes_from_the_direction_column(self):
        j = json.loads(json.dumps(TWSE_FX))
        for row in j["tables"][0]["data"]:
            if row[0] == src.TAIEX_NAME:
                row[2] = "<p style ='color:red'>+</p>"
                row[4] = "0.99"
        r = src.parse_twse_index(j, "20261008")
        self.assertEqual((r.change, r.chg_pct), (492.93, 0.99))

    def test_twse_not_ok_is_pending(self):
        with self.assertRaises(NoDataError):
            src.parse_twse_index({"stat": "很抱歉，沒有符合條件的資料!"}, "20261010")

    def test_twse_header_without_rows_is_pending_not_error(self):
        # 2026-10-09 盤中實抓:stat=OK、價格指數表有 fields、data=[],其餘 9 張表全空
        pending = json.loads((FX / "twse_mi_index_ind_pending_20261009.json").read_text(encoding="utf-8"))
        self.assertEqual(pending["stat"], "OK")
        self.assertEqual(pending["tables"][0]["data"], [])
        with self.assertRaises(NoDataError):
            src.parse_twse_index(pending, "20261009")

    def test_twse_layout_change_is_an_error_not_pending(self):
        j = {"stat": "OK", "tables": [{"fields": ["別的"], "data": [["x"]]}]}
        with self.assertRaises(RuntimeError):
            src.parse_twse_index(j, "20261008")

    def test_tpex_row_for_the_requested_day_matches_source_exactly(self):
        r = src.parse_tpex_index(TPEX_FX, "20261008")
        self.assertEqual((r.market, r.date), ("tpex", "2026-10-08"))
        self.assertEqual((r.close, r.change, r.chg_pct), (426.71, -3.75, None))
        r7 = src.parse_tpex_index(TPEX_FX, "20261007")
        self.assertEqual((r7.close, r7.change), (430.46, -0.4))

    def test_tpex_missing_day_is_pending(self):
        with self.assertRaises(NoDataError):
            src.parse_tpex_index(TPEX_FX, "20261009")
        with self.assertRaises(NoDataError):
            src.parse_tpex_index({"stat": "error"}, "20261008")

    def test_tx_near_month_matches_the_futdatadown_fixture_exactly(self):
        # fixture 2026/09/10 TX 202609 一般:收盤 46870、漲跌 -308、結算 46869(盤後列 46984 不取)
        r = src.pick_tx_near_month(TAIFEX_FX, "20260910")
        self.assertEqual((r.market, r.date, r.contract_month), ("tx", "2026-09-10", "202609"))
        self.assertEqual((r.close, r.change, r.settlement, r.chg_pct), (46870.0, -308.0, 46869.0, None))
        r11 = src.pick_tx_near_month(TAIFEX_FX, "20260911")
        self.assertEqual((r11.close, r11.change, r11.settlement), (46218.0, -651.0, 46187.0))
        # 來源的「漲跌%」是 -0.65%;export 由 change/(close-change) 推要對得上
        self.assertEqual(round(-308 / (46870 + 308) * 100, 2), -0.65)
        self.assertIsNone(src.pick_tx_near_month(TAIFEX_FX, "20260912"))

    def test_tx_near_month_rule(self):
        d = "2026-09-16"
        rows = [
            _fut("TX", d, "202609/202610", last=10.0),        # 價差組合不算
            _fut("TX", d, "202610", last=46500.0),
            _fut("TX", d, "202609", last=46400.0, change=-50.0, settle=46390.0),  # 最後交易日當天仍是近月
            _fut("TX", d, "202609", session=SESSION_AFTER_HOURS, last=46000.0),  # 盤後不算
            _fut("MTX", d, "202609", last=46401.0),            # 小台不算
            _fut("TX", "2026-09-17", "202609", last=1.0),       # 別天不算
        ]
        r = src.pick_tx_near_month(rows, "20260916")
        self.assertEqual((r.contract_month, r.close, r.change, r.settlement), ("202609", 46400.0, -50.0, 46390.0))
        # 次一交易日來源不再列 202609 → 近月自然換成 202610
        rows17 = [_fut("TX", "2026-09-17", "202610", last=46550.0)]
        self.assertEqual(src.pick_tx_near_month(rows17, "20260917").contract_month, "202610")
        # 近月列沒有收盤(無成交)→ 退到下一個有收盤的月份
        rows_nolast = [_fut("TX", d, "202609", last=None), _fut("TX", d, "202610", last=5.0)]
        self.assertEqual(src.pick_tx_near_month(rows_nolast, "20260916").contract_month, "202610")

    def test_tx_last_trading_day_settlement_zero_is_null(self):
        # 最後交易日來源把到期月結算價寫成 0(2026-05-20 … 09-16 皆然):不是價格,存 NULL
        rows = [_fut("TX", "2026-09-16", "202609", last=46400.0, change=-50.0, settle=0.0)]
        r = src.pick_tx_near_month(rows, "20260916")
        self.assertEqual((r.close, r.change), (46400.0, -50.0))
        self.assertIsNone(r.settlement)
        rows_none = [_fut("TX", "2026-09-16", "202609", last=46400.0, settle=None)]
        self.assertIsNone(src.pick_tx_near_month(rows_none, "20260916").settlement)


class _TempDb(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._old = config.DB_URL, config.DATA_DIR
        config.DATA_DIR = self.tmp
        config.DB_URL = "sqlite:///" + (self.tmp / "t.db").as_posix()
        db._engine = None
        db.init_db()

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old
        self._tmp.cleanup()

    def _rows(self):
        from sqlalchemy import text
        with db.get_engine().connect() as conn:
            return [tuple(r) for r in conn.execute(text(
                "SELECT market, date, close, change, chg_pct, contract_month, settlement "
                "FROM market_indices ORDER BY market, date"
            )).fetchall()]

    def _patch(self, twse=None, tpex=None, tx=None):
        twse = twse if twse is not None else (lambda d: src.parse_twse_index(TWSE_FX, d))
        tpex = tpex if tpex is not None else (lambda d: src.parse_tpex_index(TPEX_FX, d))
        tx = tx if tx is not None else (lambda d: _fut_or_none(d))
        return (mock.patch.object(src, "fetch_twse_index", side_effect=twse),
                mock.patch.object(src, "fetch_tpex_index", side_effect=tpex),
                mock.patch.object(src, "fetch_tx_index", side_effect=tx))

    def _cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                cli.main(["import-index", *argv])
            except SystemExit as e:
                code = e.code or 0
        return code, out.getvalue()


def _fut_or_none(d8):
    r = src.pick_tx_near_month(TAIFEX_FX, d8)
    if r is None:
        raise NoDataError("no tx")
    return r


class ImportIndex(_TempDb):
    def test_writes_three_series_and_logs_dataset_index(self):
        a, b, c = self._patch(tx=lambda d: src.pick_tx_near_month(TAIFEX_FX, "20260910"))
        with a, b, c:
            res = import_market_index("20261008")
        self.assertEqual([(r["source"], r["status"], r["rows"]) for r in res],
                         [("twse", "ok", 1), ("tpex", "ok", 1), ("taifex", "ok", 1)])
        self.assertEqual(self._rows(), [
            ("tpex", "2026-10-08", 426.71, -3.75, None, None, None),
            ("twse", "2026-10-08", 49313.44, -492.93, -0.99, None, None),
            ("tx", "2026-09-10", 46870.0, -308.0, None, "202609", 46869.0),
        ])
        from sqlalchemy import text
        with db.get_engine().connect() as conn:
            logs = conn.execute(text(
                "SELECT source, dataset, status FROM import_logs ORDER BY source")).fetchall()
        self.assertEqual([tuple(r) for r in logs],
                         [("taifex", "index", "ok"), ("tpex", "index", "ok"), ("twse", "index", "ok")])
        with a, b, c:
            import_market_index("20261008")
        self.assertEqual(len(self._rows()), 3)

    def test_cli_exit_codes(self):
        a, b, c = self._patch(tx=lambda d: src.pick_tx_near_month(TAIFEX_FX, "20260910"))
        with a, b, c:
            self.assertEqual(self._cli("--date", "20261008")[0], 0)
        # 台指期還沒產製 → 75,其他兩市那一列照樣留著
        a, b, c = self._patch()
        with a, b, c:
            code, out = self._cli("--date", "20261008")
        self.assertEqual(code, 75)
        self.assertIn("taifex: empty", out)
        self.assertEqual([r[0] for r in self._rows()], ["tpex", "twse", "tx"])
        # 任一來源錯誤 → 1
        a, b, c = self._patch(twse=lambda d: (_ for _ in ()).throw(RuntimeError("layout")))
        with a, b, c:
            self.assertEqual(self._cli("--date", "20261008")[0], 1)
        # 上市盤中「表頭有、沒有列」是 pending:單日 75、不是 1
        pending = json.loads((FX / "twse_mi_index_ind_pending_20261009.json").read_text(encoding="utf-8"))
        a, b, c = self._patch(twse=lambda d: src.parse_twse_index(pending, d),
                              tx=lambda d: src.pick_tx_near_month(TAIFEX_FX, "20260910"))
        with a, b, c:
            code, out = self._cli("--date", "20261009")
        self.assertEqual(code, 75)
        self.assertIn("twse: empty", out)

    def test_backfill_shares_tpex_month_and_tx_chunks(self):
        calls = {"tpex": 0, "tx": []}

        def tpex_month(d):
            calls["tpex"] += 1
            return TPEX_FX

        def fetch_history(start, end):
            calls["tx"].append((start, end))
            return TAIFEX_FX

        with mock.patch.object(src, "fetch_twse_index", side_effect=lambda d: src.parse_twse_index(TWSE_FX, d)), \
                mock.patch.object(src, "fetch_tpex_month", side_effect=tpex_month), \
                mock.patch("radar.providers.taifex.fetch_history", side_effect=fetch_history), \
                mock.patch("radar.market_index.time.sleep"):
            res = backfill_market_index("20261008", 3)
        self.assertEqual(calls["tpex"], 1)                      # 同一個月只抓一次
        self.assertEqual(calls["tx"], [("2026-10-06", "2026-10-08")])  # 一塊涵蓋三天
        by = {(r["date"], r["source"]): r["status"] for r in res}
        self.assertEqual(by[("20261008", "tpex")], "ok")
        self.assertEqual(by[("20261007", "tpex")], "ok")
        self.assertEqual(by[("20261006", "tpex")], "ok")
        self.assertEqual(by[("20261008", "taifex")], "empty")   # fixture 只有 9/10、9/11
        # 回補:休市/沒列的 empty 不算失敗
        with mock.patch.object(src, "fetch_twse_index", side_effect=lambda d: src.parse_twse_index(TWSE_FX, d)), \
                mock.patch.object(src, "fetch_tpex_month", side_effect=tpex_month), \
                mock.patch("radar.providers.taifex.fetch_history", side_effect=fetch_history), \
                mock.patch("radar.market_index.time.sleep"):
            code, out = self._cli("--date", "20261008", "--days", "2")
        self.assertEqual(code, 0)
        self.assertIn("index 20261007 twse", out)

    def test_backfill_returns_0_when_only_today_is_pending(self):
        pending = json.loads((FX / "twse_mi_index_ind_pending_20261009.json").read_text(encoding="utf-8"))

        def twse(d):
            return src.parse_twse_index(pending if d == "20261009" else TWSE_FX, d)

        with mock.patch.object(src, "fetch_twse_index", side_effect=twse), \
                mock.patch.object(src, "fetch_tpex_month", return_value=TPEX_FX), \
                mock.patch("radar.providers.taifex.fetch_history", return_value=TAIFEX_FX), \
                mock.patch("radar.market_index.time.sleep"):
            code, out = self._cli("--date", "20261009", "--days", "3")
        self.assertEqual(code, 0)
        self.assertIn("index 20261009 twse: empty", out)
        self.assertIn("index 20261008 twse: ok", out)


D = "2026-10-08"
P = "2026-10-07"


class ExportMarketBrief(_TempDb):
    def _seed(self, with_index=True, with_insti=True, long=False):
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": "2330", "name": "台積電", "market": "twse", "type": "stock", "industry": "半導體業", "is_active": 1},
                {"id": "2454", "name": "聯發科", "market": "twse", "type": "stock", "industry": "半導體業", "is_active": 1},
                {"id": "6488", "name": "環球晶", "market": "tpex", "type": "stock", "industry": "半導體業", "is_active": 1},
                {"id": "0050", "name": "元大台灣50", "market": "twse", "type": "etf", "industry": None, "is_active": 1},
            ])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": s, "date": dt, "close": c, "volume": 1000, "turnover": 1e8}
                for s in ("2330", "2454", "6488", "0050") for dt, c in ((P, 100.0), (D, 110.0))
            ])
            if with_insti:
                conn.execute(schema.daily_institutional.insert(), [
                    {"stock_id": s, "date": D, "foreign_net": f, "trust_net": -500, "dealer_net": 0,
                     "total_net": f - 500}
                    for s, f in (("2330", 5_000_000), ("2454", -1_000_500), ("6488", 2_000_000),
                                 ("0050", 90_000_000))])
            if with_index:
                # executemany 以第一筆的鍵為準,所以每筆都明寫六個欄位
                def ix(market, date, close, change, chg_pct, cm=None, settle=None):
                    return {"market": market, "date": date, "close": close, "change": change,
                            "chg_pct": chg_pct, "contract_month": cm, "settlement": settle}
                rows = [
                    ix("twse", P, 49806.37, -16.18, -0.03),
                    ix("twse", D, 49313.44, -492.93, -0.99),
                    ix("tpex", D, 426.71, -3.75, None),
                    ix("tx", D, 49250.0, -500.0, None, "202610", 49240.0),
                ]
                if long:
                    from datetime import date as dc, timedelta
                    base = dc(2026, 10, 6)
                    rows += [ix("twse", (base - timedelta(days=k)).isoformat(), 40000.0 + k, 1.0, 0.0)
                             for k in range(300)]
                conn.execute(schema.market_indices.insert(), rows)

    def _radar(self):
        return json.loads((self.tmp / "out" / "radar.json").read_text(encoding="utf-8"))

    def test_indices_latest_per_market_with_spark_and_derived_pct(self):
        self._seed()
        export_json(self.tmp / "out")
        r = self._radar()
        self.assertEqual(r["indices"], [
            {"market": "twse", "name": "加權指數", "date": D, "close": 49313.44, "change": -492.93, "chg_pct": -0.99,
             "spark": [49806.37, 49313.44]},
            {"market": "tpex", "name": "櫃買指數", "date": D, "close": 426.71, "change": -3.75,
             "chg_pct": round(-3.75 / (426.71 + 3.75) * 100, 2), "spark": [426.71]},
            {"market": "tx", "name": "台指期", "date": D, "close": 49250.0, "change": -500.0,
             "chg_pct": round(-500 / (49250 + 500) * 100, 2), "spark": [49250.0],
             "contract_month": "202610", "settlement": 49240.0},
        ])
        head = json.loads((self.tmp / "out" / "home" / "head.json").read_text(encoding="utf-8"))
        self.assertEqual(head["indices"], r["indices"])
        self.assertEqual(head["insti_market"], r["insti_market"])

    def test_hist_file_and_spark_caps(self):
        self._seed(long=True)
        export_json(self.tmp / "out")
        r = self._radar()
        twse = next(i for i in r["indices"] if i["market"] == "twse")
        self.assertEqual(len(twse["spark"]), SPARK_N)
        self.assertEqual(twse["spark"][-2:], [49806.37, 49313.44])     # 舊→新
        hist = json.loads((self.tmp / "out" / "market" / "indices_hist.json").read_text(encoding="utf-8"))
        self.assertEqual(hist["as_of"], D)
        self.assertEqual(len(hist["series"]["twse"]["points"]), HIST_N)
        self.assertEqual(hist["series"]["twse"]["points"][-1], [D, 49313.44, -492.93, -0.99])
        self.assertEqual(hist["series"]["tpex"]["points"], [[D, 426.71, -3.75, round(-3.75 / 430.46 * 100, 2)]])
        self.assertEqual(hist["series"]["tx"]["contract_month"], "202610")
        # 台指期每列帶當天的近月月份(近月連續、不調整價差;游標停在哪天就顯示那天的月份)
        self.assertEqual(hist["series"]["tx"]["points"], [[D, 49250.0, -500.0, round(-500 / 49750 * 100, 2), "202610"]])
        raw = (self.tmp / "out" / "market" / "indices_hist.json").read_text(encoding="utf-8")
        self.assertNotIn(": ", raw)

    def test_insti_market_equals_insti_flow_market_totals(self):
        self._seed()
        export_json(self.tmp / "out")
        r = self._radar()
        flow = json.loads((self.tmp / "out" / "rankings" / "insti_flow_1d.json").read_text(encoding="utf-8"))
        self.assertEqual(r["insti_market"], {"date": D, **flow["market"]})
        self.assertEqual(r["insti_market"]["foreign"]["net_lots"], 5000 - 1000 + 2000)
        self.assertEqual(r["insti_market"]["trust"]["net_lots"], 0)
        self.assertEqual(r["insti_market"]["foreign"]["amt_est"], round((5_000_000 - 1_000_500 + 2_000_000) * 110.0))

    def test_keys_and_hist_absent_when_no_rows(self):
        self._seed(with_index=False, with_insti=False)
        out = self.tmp / "out"
        (out / "market").mkdir(parents=True)
        (out / "market" / "indices_hist.json").write_text("{}", encoding="utf-8")  # 舊檔
        export_json(out)
        r = self._radar()
        self.assertNotIn("indices", r)
        self.assertNotIn("insti_market", r)
        self.assertFalse((out / "market" / "indices_hist.json").exists())
        with db.get_engine().connect() as conn:
            self.assertIsNone(indices_hist(conn, D, "x"))

    def test_old_shape_table_is_migrated_and_export_isolated(self):
        """§11 形狀的 market_indices(沒有 contract_month/settlement)→ init_db 補欄;指數摘要壞掉只少鍵。"""
        from sqlalchemy import text
        with db.get_engine().begin() as conn:
            conn.exec_driver_sql("DROP TABLE market_indices")
            conn.exec_driver_sql(
                "CREATE TABLE market_indices (market TEXT, date TEXT, close REAL NOT NULL, change REAL, chg_pct REAL, "
                "PRIMARY KEY (market, date))")
            conn.exec_driver_sql(
                "INSERT INTO market_indices VALUES ('twse', '2026-10-08', 49313.44, -492.93, -0.99)")
        db.init_db()
        with db.get_engine().connect() as conn:
            cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(market_indices)").fetchall()}
            self.assertTrue({"contract_month", "settlement"} <= cols)
            self.assertEqual(latest_indices(conn, D)[0]["close"], 49313.44)
            conn.execute(text("SELECT 1"))
        self._seed(with_index=False)
        with mock.patch("radar.export.json_export.latest_indices", side_effect=RuntimeError("boom")), \
                self.assertLogs("radar.export.json_export", level="WARNING") as logs:
            export_json(self.tmp / "out")
        self.assertIn("market indices summary failed", "\n".join(logs.output))
        r = self._radar()
        self.assertNotIn("indices", r)
        self.assertIn("insti_market", r)
        self.assertTrue((self.tmp / "out" / "stocks_index.json").exists())

    def test_latest_indices_only_up_to_d(self):
        self._seed()
        with db.get_engine().connect() as conn:
            rows = latest_indices(conn, P)
        self.assertEqual([(x["market"], x["date"], x["close"]) for x in rows], [("twse", P, 49806.37)])


if __name__ == "__main__":
    unittest.main()
