"""個股期貨 export 契約(per-stock `futures` 區塊)。

只驗「是不是標的」這個事實,外加當日的量/未平倉。刻意**沒有**任何比率、均值、
名次——量能異常排行是後面的切片,需要 60 個交易日歷史與事先登記的否決條件。
最後一個測試就是守住這件事的閘門。

用即拋 SQLite,風格同 test_backfill_gaps.py / test_margin_export.py,不連網路。
"""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import radar.config as config
import radar.db as db
from radar import schema
from radar.export.json_export import export_json

D = "2026-09-15"      # 價格日 = export 日
P = "2026-09-14"
LIST_AS_OF = "2026-09-11"   # 清單刷新日,刻意早於價格日

RATIO_ISH = ("ratio", "avg", "mean", "rank", "score", "z")


def _contract(code, stock_id, *, last_seen=LIST_AS_OF, future=1, option=0, weekly=0):
    return {
        "contract_code": code, "stock_id": stock_id, "stock_name": "x",
        "is_stock_future": future, "is_stock_option": option,
        "is_weekly_option": weekly, "market": "twse",
        "first_seen": "2026-01-02", "last_seen": last_seen,
    }


def _daily(code, month, session, volume, oi, date=D):
    return {"contract_code": code, "date": date, "contract_month": month,
            "session": session, "volume": volume, "open_interest": oi}


class FuturesExportTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._old_url, self._old_dir = config.DB_URL, config.DATA_DIR
        config.DATA_DIR = tmp
        config.DB_URL = "sqlite:///" + (tmp / "t.db").as_posix()
        db._engine = None
        db.init_db()
        self._seed_prices()
        self.out = tmp / "out"

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old_url, self._old_dir
        self._tmp.cleanup()

    def _seed_prices(self):
        eng = db.get_engine()
        with eng.begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": "2303", "name": "聯電", "market": "twse", "type": "stock", "is_active": 1},
                {"id": "1565", "name": "精華", "market": "tpex", "type": "stock", "is_active": 1},
                {"id": "9999", "name": "非標的", "market": "twse", "type": "stock", "is_active": 1},
            ])
            rows = []
            for sid in ("2303", "1565", "9999"):
                for date, close in ((P, 50.0), (D, 51.0)):
                    rows.append({"stock_id": sid, "date": date, "close": close,
                                 "volume": 1000, "turnover": 51_000_000})
            conn.execute(schema.daily_prices.insert(), rows)

    def _seed_futures(self, contracts, daily=()):
        eng = db.get_engine()
        with eng.begin() as conn:
            if contracts:
                conn.execute(schema.futures_contracts.insert(), list(contracts))
            if daily:
                conn.execute(schema.futures_daily.insert(), list(daily))

    def _stock(self, sid):
        export_json(self.out)
        return json.loads((self.out / "stocks" / f"{sid}.json").read_text(encoding="utf-8"))

    # ── 事實本身 ────────────────────────────────────────────────
    def test_single_contract(self):
        self._seed_futures([_contract("CCF", "2303", option=1)])
        futures = self._stock("2303")["futures"]
        self.assertEqual(futures["version"], 1)
        self.assertEqual(futures["contracts"], [
            {"code": "CCF", "is_futures": True, "is_option": True, "is_weekly_option": False},
        ])

    def test_two_contracts_for_one_stock(self):
        """1565 同時是 2,000 股的 MYF 與 100 股的 OMF——所以鍵是契約代碼。"""
        self._seed_futures([_contract("MYF", "1565"), _contract("OMF", "1565")])
        codes = [c["code"] for c in self._stock("1565")["futures"]["contracts"]]
        self.assertEqual(codes, ["MYF", "OMF"])

    def test_not_an_underlying_is_an_empty_list_not_a_missing_key(self):
        """空陣列是一個正面主張:完整官方清單截至該日不含這檔。"""
        self._seed_futures([_contract("CCF", "2303")])
        futures = self._stock("9999")["futures"]
        self.assertEqual(futures["contracts"], [])
        self.assertEqual(futures["list_as_of"], LIST_AS_OF)

    def test_key_absent_entirely_before_the_first_import(self):
        """沒有鍵 = 「我們不知道」,不可以與 contracts: [] 塌成同一件事。"""
        stock = self._stock("2303")
        self.assertNotIn("futures", stock)

    def test_list_as_of_is_the_mapping_date_not_the_price_date(self):
        self._seed_futures([_contract("CCF", "2303", last_seen=LIST_AS_OF)])
        stock = self._stock("2303")
        self.assertEqual(stock["futures"]["list_as_of"], LIST_AS_OF)
        self.assertNotEqual(stock["futures"]["list_as_of"], D)

    # ── 當日數字 ────────────────────────────────────────────────
    def test_daily_omitted_when_no_row_for_the_export_date(self):
        self._seed_futures(
            [_contract("CCF", "2303")],
            [_daily("CCF", "202609", "一般", 500, 900, date=P)],
        )
        contract = self._stock("2303")["futures"]["contracts"][0]
        self.assertNotIn("daily", contract)

    def test_daily_sums_months_and_splits_sessions(self):
        self._seed_futures(
            [_contract("CCF", "2303")],
            [
                _daily("CCF", "202609", "一般", 500, 900),
                _daily("CCF", "202610", "一般", 100, 100),
                # 盤後沒有未平倉(來源給 '-')——存量不可以兩個時段相加。
                _daily("CCF", "202609", "盤後", 40, None),
            ],
        )
        daily = self._stock("2303")["futures"]["contracts"][0]["daily"]
        self.assertEqual(daily["date"], D)
        self.assertEqual(daily["volume"], 640)
        self.assertEqual(daily["open_interest"], 1000)
        self.assertEqual(daily["session_volume"], {"一般": 600, "盤後": 40})

    def test_session_volume_only_lists_sessions_that_actually_have_rows(self):
        """21:20 那一輪常只有一般時段;寫 盤後: 0 會把「未公布」謊報成「沒成交」。"""
        self._seed_futures(
            [_contract("CCF", "2303")],
            [_daily("CCF", "202609", "一般", 500, 900)],
        )
        daily = self._stock("2303")["futures"]["contracts"][0]["daily"]
        self.assertEqual(daily["session_volume"], {"一般": 500})

    def test_calendar_spread_rows_are_excluded_from_the_volume_sum(self):
        """'202609/202610' 是轉倉對敲,不是部位;拿掉過濾這個測試必須紅。"""
        self._seed_futures(
            [_contract("CCF", "2303")],
            [
                _daily("CCF", "202609", "一般", 500, 900),
                _daily("CCF", "202609/202610", "一般", 2541, None),
            ],
        )
        daily = self._stock("2303")["futures"]["contracts"][0]["daily"]
        self.assertEqual(daily["volume"], 500)
        self.assertEqual(daily["session_volume"], {"一般": 500})

    # ── freshness ──────────────────────────────────────────────
    def test_freshness_reports_futures_lag(self):
        self._seed_futures(
            [_contract("CCF", "2303")],
            [_daily("CCF", "202609", "一般", 500, 900, date=P)],
        )
        export_json(self.out)
        payload = json.loads((self.out / "radar.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["freshness"]["futures"], {"date": P, "stale": True})

    # ── 閘門 ────────────────────────────────────────────────────
    def test_payload_cannot_silently_gain_a_rate(self):
        """後面那個切片要加比率/名次,得自己動手並過 review,不能順手混進來。"""
        self._seed_futures(
            [_contract("CCF", "2303"), _contract("MYF", "1565")],
            [
                _daily("CCF", "202609", "一般", 500, 900),
                _daily("CCF", "202609", "盤後", 40, None),
                _daily("CCF", "202609/202610", "一般", 2541, None),
            ],
        )
        export_json(self.out)
        offenders = []

        def walk(node, path):
            if isinstance(node, dict):
                for key, value in node.items():
                    lowered = key.lower()
                    if any(bad in lowered for bad in RATIO_ISH):
                        offenders.append(f"{path}.{key}")
                    walk(value, f"{path}.{key}")
            elif isinstance(node, list):
                for i, value in enumerate(node):
                    walk(value, f"{path}[{i}]")

        for sid in ("2303", "1565", "9999"):
            stock = json.loads((self.out / "stocks" / f"{sid}.json").read_text(encoding="utf-8"))
            walk(stock["futures"], f"{sid}.futures")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
