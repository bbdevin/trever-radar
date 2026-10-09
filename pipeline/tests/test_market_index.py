"""大盤指數(docs/49 §11):來源解析對 fixture 逐值相同、匯入/離開碼、export 的 indices/insti_market。

不連網:兩個 fetch 一律 mock;fixture 是 2026-10-09 抓回來的原始回應(TWSE MI_INDEX type=IND
2026-10-08、TPEx tradingIndex 2026-10 整月)。
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
from radar.market_index import import_market_index, latest_indices
from radar.providers import NoDataError
from radar.providers import market_index as src

FX = Path(__file__).parent / "fixtures"
TWSE_FX = json.loads((FX / "twse_mi_index_ind_20261008.json").read_text(encoding="utf-8"))
TPEX_FX = json.loads((FX / "tpex_trading_index_20261008.json").read_text(encoding="utf-8"))


class ParseFixtures(unittest.TestCase):
    def test_twse_taiex_row_matches_source_exactly(self):
        r = src.parse_twse_index(TWSE_FX, "20261008")
        self.assertEqual((r.market, r.date), ("twse", "2026-10-08"))
        # 來源:發行量加權股價指數 49,313.44、漲跌(+/-)=-、492.93、-0.99
        self.assertEqual(r.close, 49313.44)
        self.assertEqual(r.change, -492.93)
        self.assertEqual(r.chg_pct, -0.99)

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
            return conn.execute(text(
                "SELECT market, date, close, change, chg_pct FROM market_indices ORDER BY market, date"
            )).fetchall()

    def _patch(self, twse=None, tpex=None):
        twse = twse if twse is not None else (lambda d: src.parse_twse_index(TWSE_FX, d))
        tpex = tpex if tpex is not None else (lambda d: src.parse_tpex_index(TPEX_FX, d))
        return (mock.patch.object(src, "fetch_twse_index", side_effect=twse),
                mock.patch.object(src, "fetch_tpex_index", side_effect=tpex))

    def _cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                cli.main(["import-index", *argv])
            except SystemExit as e:
                code = e.code or 0
        return code, out.getvalue()


class ImportIndex(_TempDb):
    def test_writes_both_markets_and_logs_dataset_index(self):
        a, b = self._patch()
        with a, b:
            res = import_market_index("20261008")
        self.assertEqual([(r["source"], r["status"], r["rows"]) for r in res],
                         [("twse", "ok", 1), ("tpex", "ok", 1)])
        self.assertEqual([tuple(r) for r in self._rows()], [
            ("tpex", "2026-10-08", 426.71, -3.75, None),
            ("twse", "2026-10-08", 49313.44, -492.93, -0.99),
        ])
        from sqlalchemy import text
        with db.get_engine().connect() as conn:
            logs = conn.execute(text(
                "SELECT source, dataset, date, status FROM import_logs ORDER BY source")).fetchall()
        self.assertEqual([tuple(r) for r in logs],
                         [("tpex", "index", "2026-10-08", "ok"), ("twse", "index", "2026-10-08", "ok")])
        # 再跑一次:upsert,不重複
        with a, b:
            import_market_index("20261008")
        self.assertEqual(len(self._rows()), 2)

    def test_cli_exit_codes(self):
        a, b = self._patch()
        with a, b:
            self.assertEqual(self._cli("--date", "20261008")[0], 0)
        # 上櫃還沒公布 → 75,上市那一列照樣留著
        a, b = self._patch(tpex=lambda d: (_ for _ in ()).throw(NoDataError("not yet")))
        with a, b:
            code, out = self._cli("--date", "20261009")
        self.assertEqual(code, 75)
        self.assertIn("tpex: empty", out)
        self.assertEqual([r[1] for r in self._rows() if r[0] == "twse"], ["2026-10-08", "2026-10-09"])
        # 任一市錯誤 → 1
        a, b = self._patch(twse=lambda d: (_ for _ in ()).throw(RuntimeError("layout")))
        with a, b:
            self.assertEqual(self._cli("--date", "20261008")[0], 1)
        # 回補:休市日的 empty 不算失敗
        a, b = self._patch(tpex=lambda d: (_ for _ in ()).throw(NoDataError("holiday")))
        with a, b:
            code, out = self._cli("--date", "20261008", "--days", "2")
        self.assertEqual(code, 0)
        self.assertIn("index 20261007 twse", out)


D = "2026-10-08"
P = "2026-10-07"


class ExportMarketBrief(_TempDb):
    def _seed(self, with_index=True, with_insti=True):
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
                conn.execute(schema.market_indices.insert(), [
                    {"market": "twse", "date": P, "close": 49806.37, "change": -16.18, "chg_pct": -0.03},
                    {"market": "twse", "date": D, "close": 49313.44, "change": -492.93, "chg_pct": -0.99},
                    {"market": "tpex", "date": D, "close": 426.71, "change": -3.75, "chg_pct": None},
                ])

    def _radar(self):
        return json.loads((self.tmp / "out" / "radar.json").read_text(encoding="utf-8"))

    def test_indices_latest_per_market_and_tpex_pct_derived(self):
        self._seed()
        export_json(self.tmp / "out")
        r = self._radar()
        self.assertEqual(r["indices"], [
            {"market": "twse", "name": "加權指數", "date": D, "close": 49313.44, "change": -492.93, "chg_pct": -0.99},
            {"market": "tpex", "name": "櫃買指數", "date": D, "close": 426.71, "change": -3.75,
             "chg_pct": round(-3.75 / (426.71 + 3.75) * 100, 2)},
        ])
        head = json.loads((self.tmp / "out" / "home" / "head.json").read_text(encoding="utf-8"))
        self.assertEqual(head["indices"], r["indices"])
        self.assertEqual(head["insti_market"], r["insti_market"])

    def test_insti_market_equals_insti_flow_market_totals(self):
        self._seed()
        export_json(self.tmp / "out")
        r = self._radar()
        flow = json.loads((self.tmp / "out" / "rankings" / "insti_flow_1d.json").read_text(encoding="utf-8"))
        self.assertEqual(r["insti_market"], {"date": D, **flow["market"]})
        # ETF 不算;−1,000,500 股向零截斷 = −1,000 張;投信 −500 股 = 0 張(三檔)
        self.assertEqual(r["insti_market"]["foreign"]["net_lots"], 5000 - 1000 + 2000)
        self.assertEqual(r["insti_market"]["trust"]["net_lots"], 0)
        self.assertEqual(r["insti_market"]["foreign"]["amt_est"], round((5_000_000 - 1_000_500 + 2_000_000) * 110.0))

    def test_keys_absent_when_no_rows(self):
        self._seed(with_index=False, with_insti=False)
        export_json(self.tmp / "out")
        r = self._radar()
        self.assertNotIn("indices", r)
        self.assertNotIn("insti_market", r)

    def test_latest_indices_only_up_to_d(self):
        self._seed()
        with db.get_engine().connect() as conn:
            rows = latest_indices(conn, P)
        self.assertEqual([(x["market"], x["date"], x["close"]) for x in rows], [("twse", P, 49806.37)])


if __name__ == "__main__":
    unittest.main()
