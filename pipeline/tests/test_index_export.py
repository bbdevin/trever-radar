"""`export-index`(docs/49 §12.6.5):早上只重寫指數三份檔,與全量 export 逐位元相同。

情境:資料日 D(daily_prices 停在 D),早上匯入期交所標次一交易日 N 的盤後列(D 15:00 → D+1 05:00)。
窄 export 寫出的 radar.json / home/head.json / home/stocks.json / market/indices_hist.json 要與同一個
DB 狀態下的全量 export 逐位元相同(generated_at 固定);其他檔不動。
"""
import contextlib
import io
import json
import shutil
from datetime import datetime as real_datetime
from unittest import mock

import radar.db as db
from radar import cli, schema
from radar.export.index_export import export_index
from radar.export.json_export import export_json
from radar.market_index import latest_indices

import tests.test_market_index as tmi
from tests.test_market_index import D, P

N = "2026-10-09"   # D 的次一交易日:D 15:00 → 10/09 05:00 那一夜,期交所標 N
FILES = ("radar.json", "home/head.json", "home/stocks.json", "market/indices_hist.json")


class _FixedNow(real_datetime):
    @classmethod
    def now(cls, tz=None):
        return real_datetime(2026, 10, 13, 8, 5, 0, tzinfo=tz)


class _Base(tmi._TempDb):
    # 只借 seed,不繼承 ExportMarketBrief 的 test_*(否則那些測試在這裡再跑一次);
    # 以模組屬性取用,不把 TestCase 類別匯入本模組命名空間(pytest 會再收集一次)
    _seed = tmi.ExportMarketBrief._seed


class ExportIndex(_Base):
    def setUp(self):
        super().setUp()
        self._stack = contextlib.ExitStack()
        self._stack.enter_context(mock.patch("radar.export.json_export.datetime", _FixedNow))
        self._stack.enter_context(mock.patch("radar.export.index_export.datetime", _FixedNow))

    def tearDown(self):
        self._stack.close()
        super().tearDown()

    def _night_n(self, close=49100.0, change=-150.0):
        with db.get_engine().begin() as conn:
            conn.execute(schema.market_indices.insert(), [
                {"market": "tx_night", "date": N, "close": close, "change": change, "chg_pct": None,
                 "contract_month": "202610", "settlement": None}])

    def _bytes(self, out):
        return {f: (out / f).read_bytes() for f in FILES}

    def _full(self, name):
        out = self.tmp / name
        export_json(out)
        return out

    def test_morning_night_is_byte_identical_to_full_export(self):
        self._seed(night=True, tx_prev=True)
        out = self._full("out")
        before_meta = (out / "meta.json").read_bytes()
        before_index = (out / "stocks_index.json").read_bytes()
        self._night_n()
        info = export_index(out)
        self.assertEqual(info["date"], D)
        self.assertEqual(info["night"]["date"], N)
        full = self._full("full")
        self.assertEqual(self._bytes(out), self._bytes(full))
        # 其他檔沒動
        self.assertEqual((out / "meta.json").read_bytes(), before_meta)
        self.assertEqual((out / "stocks_index.json").read_bytes(), before_index)
        head = json.loads((out / "home" / "head.json").read_text(encoding="utf-8"))
        tx = next(i for i in head["indices"] if i["market"] == "tx")
        # 一般時段仍是 D;夜盤是 D 15:00 → D+1 05:00 那一夜(期交所標 N)
        self.assertEqual((tx["date"], tx["close"]), (D, 49250.0))
        self.assertEqual(tx["night"], {"date": N, "from": D, "to": "2026-10-09", "close": 49100.0,
                                       "change": -150.0, "chg_pct": round(-150 / 49250 * 100, 2),
                                       "contract_month": "202610"})
        self.assertEqual(head["data_date"], D)

    def test_no_db_change_rewrites_identical_bytes(self):
        self._seed(night=True, tx_prev=True)
        out = self._full("out")
        before = self._bytes(out)
        export_index(out)
        self.assertEqual(self._bytes(out), before)

    def test_indices_key_added_in_the_same_position_as_full_export(self):
        self._seed(with_index=False)
        out = self._full("out")
        self.assertNotIn("indices", json.loads((out / "radar.json").read_text(encoding="utf-8")))
        with db.get_engine().begin() as conn:
            conn.execute(schema.market_indices.insert(), [
                {"market": "tx", "date": D, "close": 49250.0, "change": -500.0, "chg_pct": None,
                 "contract_month": "202610", "settlement": 49240.0}])
        self._night_n()
        export_index(out)
        full = self._full("full")
        self.assertEqual(self._bytes(out), self._bytes(full))
        keys = list(json.loads((out / "radar.json").read_text(encoding="utf-8")))
        self.assertEqual(keys[keys.index("indices") + 1], "insti_market")

    def test_missing_radar_json_fails_without_writing(self):
        self._seed()
        out = self.tmp / "empty"
        out.mkdir()
        with self.assertRaises(FileNotFoundError):
            export_index(out)
        self.assertEqual(list(out.iterdir()), [])

    def test_cli_prints_a_greppable_line(self):
        self._seed(night=True, tx_prev=True)
        out = self._full("out")
        self._night_n()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli.main(["export-index", "--out", str(out)])
        self.assertEqual(buf.getvalue().strip(), f"export-index date={D} night={N} close=49100.0")
        shutil.rmtree(out / "home")
        with db.get_engine().begin() as conn:
            conn.exec_driver_sql("DELETE FROM market_indices WHERE market='tx_night'")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli.main(["export-index", "--out", str(out)])
        self.assertEqual(buf.getvalue().strip(), f"export-index date={D} night=none")
        self.assertTrue((out / "home" / "head.json").exists())


class NightAfterRule(_Base):
    """``latest_tx_night``:d 15:00 開盤那一夜已入庫就用它;只認 from == d,不往更後面拿。"""

    def test_only_the_night_that_opened_at_d(self):
        self._seed(night=True, tx_prev=True)
        with db.get_engine().begin() as conn:
            conn.execute(schema.market_indices.insert(), [
                {"market": "tx_night", "date": "2026-10-12", "close": 1.0, "change": 0.0, "chg_pct": None,
                 "contract_month": "202610", "settlement": None}])
        with db.get_engine().connect() as conn:
            # 10/12 那一夜的 from = 最後一個早於它的 tx 日 = D → 是 D 之後緊接的那一夜
            night = next(i for i in latest_indices(conn, D) if i["market"] == "tx")["night"]
            self.assertEqual((night["date"], night["from"], night["to"]), ("2026-10-12", D, "2026-10-09"))
            # 查 P:D 之後的那一夜 from = D ≠ P → 不拿;P 之後緊接的(標 D)才是
            night_p = next(i for i in latest_indices(conn, P) if i["market"] == "tx")["night"]
            self.assertEqual((night_p["date"], night_p["from"]), (D, P))
        # D 的一般時段列也還沒有(資料日落後):10/12 那一夜 from = P ≠ D → 退回 ≤ D 的那一夜
        with db.get_engine().begin() as conn:
            conn.exec_driver_sql("DELETE FROM market_indices WHERE market='tx' AND date=:d", {"d": D})
            conn.execute(schema.market_indices.insert(), [
                {"market": "tx", "date": "2026-10-06", "close": 49000.0, "change": 0.0, "chg_pct": None,
                 "contract_month": "202610", "settlement": 49000.0}])
        with db.get_engine().connect() as conn:
            tx = next(i for i in latest_indices(conn, D) if i["market"] == "tx")
            self.assertEqual(tx["night"]["date"], D)
