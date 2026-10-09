"""compute-adjustments --ex-dates-since(還原因子日增量)。

三件事:
1. 選股器:證交所 TWT49U + 櫃買 exDailyQ(真實回應裁切的 fixture)→ 代號,
   去重、只留窗內、只留本庫有價格列的 stock/etf。全程不打網路。
2. --dry-run / --print-ids 不寫任何東西(DB 檔逐位元相同、不呼叫 FinMind)。
3. 種子庫:上次跑因子之後才發生的新除息 → 跑完後因子在除息日階梯、原始 OHLC
   逐位元不變、該檔指標全歷史重算且跨除息日連續(MA 沒有股利大小的跳動)。

FinMind 全市場(不帶 data_id)免費 token 不開放(2026-10-09 實測 status 400
「Your level is free」),所以選股走官方兩張公開表,FinMind 仍逐檔算因子。
"""
import datetime as real_datetime
import hashlib
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sqlalchemy import text

import radar.config as config
import radar.db as db
from radar import adjustments, cli, schema
from radar.providers import tpex, twse

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TWSE_FIXTURE = json.loads((FIXTURES / "twse_twt49u_20260904_20261009.json").read_text(encoding="utf-8"))
TPEX_FIXTURE = json.loads((FIXTURES / "tpex_exdailyq_20260904_20261009.json").read_text(encoding="utf-8"))
TODAY = real_datetime.date(2026, 10, 9)


class _FixedDatetime(real_datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 9, 13, 15, tzinfo=tz or ZoneInfo(config.TZ))


def _fake_get_json(url, params=None, **_kw):
    if "TWT49U" in url:
        return TWSE_FIXTURE
    if "exDailyQ" in url:
        return TPEX_FIXTURE
    raise AssertionError(f"unexpected request {url}")


class ProviderParseTests(unittest.TestCase):
    def test_twse_rows_become_iso_dates_and_codes(self):
        with patch("radar.providers.twse.get_json", _fake_get_json):
            rows = twse.fetch_ex_rights("20260904", "20261009")
        self.assertEqual(rows[0], {"date": "2026-09-07", "code": "00400A"})
        self.assertIn({"date": "2026-09-08", "code": "2379"}, rows)
        self.assertEqual(rows[-1], {"date": "2026-10-08", "code": "00400A"})
        self.assertEqual(len(rows), len(TWSE_FIXTURE["data"]))

    def test_tpex_rows_become_iso_dates_and_codes(self):
        with patch("radar.providers.tpex.get_json", _fake_get_json):
            rows = tpex.fetch_ex_rights("20260904", "20261009")
        self.assertEqual(rows[0], {"date": "2026-09-07", "code": "1268"})
        self.assertIn({"date": "2026-10-07", "code": "6129"}, rows)

    def test_tpex_sends_roc_dates(self):
        seen = {}

        def capture(url, params=None, **_kw):
            seen.update(params)
            return TPEX_FIXTURE

        with patch("radar.providers.tpex.get_json", capture):
            tpex.fetch_ex_rights("20260904", "20261009")
        self.assertEqual((seen["startDate"], seen["endDate"]), ("115/09/04", "115/10/09"))

    def test_empty_windows_are_empty_not_errors(self):
        twse_empty = {"stat": "很抱歉，沒有符合條件的資料!"}
        tpex_empty = {"stat": "ok", "tables": [{"fields": TPEX_FIXTURE["tables"][0]["fields"], "data": []}]}
        with patch("radar.providers.twse.get_json", lambda *a, **k: twse_empty):
            self.assertEqual(twse.fetch_ex_rights("20260215", "20260216"), [])
        with patch("radar.providers.tpex.get_json", lambda *a, **k: tpex_empty):
            self.assertEqual(tpex.fetch_ex_rights("20260215", "20260216"), [])

    def test_unknown_twse_stat_is_an_error(self):
        with patch("radar.providers.twse.get_json", lambda *a, **k: {"stat": "系統忙線中"}):
            with self.assertRaises(RuntimeError):
                twse.fetch_ex_rights("20260904", "20261009")


class SelectorTests(unittest.TestCase):
    def test_candidates_are_deduped_sorted_and_windowed(self):
        with patch("radar.providers.twse.get_json", _fake_get_json), \
                patch("radar.providers.tpex.get_json", _fake_get_json):
            all_ids = adjustments.ex_date_candidates("2026-09-04", "2026-10-09")
            late = adjustments.ex_date_candidates("2026-10-01", "2026-10-07")
        self.assertEqual(all_ids, sorted(set(all_ids)))
        self.assertEqual(all_ids.count("00400A"), 1)          # 09-07 與 10-08 兩次
        self.assertEqual(len(all_ids), 15)                    # 16 列,00400A 重複一次
        self.assertEqual(late, ["2947", "6129", "6947"])      # 10-08 的 00400A 在窗外

    def test_resolve_since_accepts_days_or_a_date(self):
        self.assertEqual(adjustments.resolve_since("10", TODAY), "2026-09-29")
        self.assertEqual(adjustments.resolve_since("40", TODAY), "2026-08-30")
        self.assertEqual(adjustments.resolve_since("2026-09-04", TODAY), "2026-09-04")
        with self.assertRaises(SystemExit):
            adjustments.resolve_since("last week", TODAY)


# ── 種子庫 ────────────────────────────────────────────────────────────────

OLD_EX = "2026-07-15"     # 上次 compute-adjustments(09-04)之前就有,因子已在庫
NEW_EX = "2026-09-08"     # 09-04 之後的新除息:因子還沒反映 → 本次要補
OLD_RATIO = 0.98
RAW_BEFORE_OLD = 100 / OLD_RATIO   # 未還原價:07-15 前 102.04…,之後 100,09-08 起 95
EVENTS = [
    {"date": OLD_EX, "before_price": RAW_BEFORE_OLD, "after_price": 100.0},
    {"date": NEW_EX, "before_price": 100.0, "after_price": 95.0},
]


def _weekdays(start: str, end: str) -> list[str]:
    d = real_datetime.date.fromisoformat(start)
    stop = real_datetime.date.fromisoformat(end)
    out = []
    while d <= stop:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += real_datetime.timedelta(days=1)
    return out


DATES = _weekdays("2026-04-01", "2026-10-08")


def _raw_close(d: str) -> float:
    if d < OLD_EX:
        return RAW_BEFORE_OLD
    if d < NEW_EX:
        return 100.0
    return 95.0


class _SeededDb(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.db_path = tmp / "t.db"
        self._old_url, self._old_dir = config.DB_URL, config.DATA_DIR
        config.DATA_DIR = tmp
        config.DB_URL = "sqlite:///" + self.db_path.as_posix()
        db._engine = None
        db.init_db()
        eng = db.get_engine()
        with eng.begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": "2379", "name": "瑞昱", "market": "twse", "type": "stock", "is_active": 1},
                {"id": "1268", "name": "漢來美食", "market": "tpex", "type": "stock", "is_active": 1},
                {"id": "00400A", "name": "ETF", "market": "twse", "type": "etf", "is_active": 1},
                {"id": "2442", "name": "無價格", "market": "twse", "type": "stock", "is_active": 1},
                {"id": "9999", "name": "不在窗內", "market": "twse", "type": "stock", "is_active": 1},
            ])
            rows = []
            for sid in ("2379", "1268", "00400A", "9999"):
                for d in DATES:
                    c = _raw_close(d) if sid == "2379" else 50.0
                    rows.append({
                        "stock_id": sid, "date": d, "open": c, "high": c + 0.5, "low": c - 0.5,
                        "close": c, "volume": 1000, "turnover": int(c * 1000), "transactions": 10,
                        # 上次跑因子時只知道 07-15 那次
                        "adj_factor": OLD_RATIO if (sid == "2379" and d < OLD_EX) else 1.0,
                    })
            conn.execute(schema.daily_prices.insert(), rows)
        eng.dispose()
        db._engine = None

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old_url, self._old_dir
        self._tmp.cleanup()

    def run_cli(self, *argv):
        buf = io.StringIO()
        with patch("radar.providers.twse.get_json", _fake_get_json), \
                patch("radar.providers.tpex.get_json", _fake_get_json), \
                patch("radar.cli.datetime", _FixedDatetime), \
                redirect_stdout(buf):
            cli.main(list(argv))
        return buf.getvalue()

    def factors(self, sid):
        with db.get_engine().connect() as conn:
            return dict(conn.execute(text(
                "SELECT date, adj_factor FROM daily_prices WHERE stock_id = :s ORDER BY date"),
                {"s": sid}).fetchall())

    def raw_rows(self):
        with db.get_engine().connect() as conn:
            return conn.execute(text(
                "SELECT stock_id, date, quote(open), quote(high), quote(low), quote(close), "
                "quote(volume), quote(turnover), quote(transactions) "
                "FROM daily_prices ORDER BY stock_id, date")).fetchall()


class DryRunTests(_SeededDb):
    def test_selector_intersects_with_the_db_universe(self):
        out = self.run_cli("compute-adjustments", "--ex-dates-since", "2026-09-04", "--print-ids")
        # 01010T/1466/... 不在庫;2442 沒有價格列;9999 不在窗內
        self.assertEqual(out.strip(), "00400A,1268,2379")

    def test_bare_flag_means_ten_days(self):
        out = self.run_cli("compute-adjustments", "--ex-dates-since", "--print-ids")
        self.assertEqual(out.strip(), "00400A")   # 只有 10-08 那筆在 09-29..10-09

    def test_dry_run_and_print_ids_write_nothing(self):
        before = hashlib.sha256(self.db_path.read_bytes()).hexdigest()
        calls = []
        with patch("radar.providers.finmind.fetch_dividend_results",
                   lambda *a, **k: calls.append(a) or EVENTS):
            out = self.run_cli("compute-adjustments", "--ex-dates-since", "2026-09-04", "--dry-run")
            self.run_cli("compute-adjustments", "--ex-dates-since", "40", "--print-ids")
            self.run_cli("compute-adjustments", "--ids", "2379", "--dry-run")
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        self.assertEqual(calls, [])
        self.assertIn("ids=00400A,1268,2379", out)
        self.assertIn("dry-run: 3 stocks would be adjusted; nothing written", out)
        self.assertEqual(hashlib.sha256(self.db_path.read_bytes()).hexdigest(), before)
        self.assertFalse(Path(str(self.db_path) + "-wal").exists()
                         and Path(str(self.db_path) + "-wal").stat().st_size > 0)

    def test_ex_dates_since_refuses_explicit_targets(self):
        with self.assertRaises(SystemExit):
            self.run_cli("compute-adjustments", "--ex-dates-since", "10", "--ids", "2330")


class IncrementalRunTests(_SeededDb):
    def fake_dividends(self, sid, start_date="1990-01-01"):
        return list(EVENTS) if sid == "2379" else []

    def test_new_dividend_steps_factors_keeps_raw_and_recomputes_indicators(self):
        raw_before = self.raw_rows()
        old_factors_1268 = self.factors("1268")

        with patch("radar.providers.finmind.fetch_dividend_results", self.fake_dividends):
            out = self.run_cli("compute-adjustments", "--ex-dates-since", "2026-09-04", "--sleep", "0")
        self.assertIn("ids=00400A,1268,2379", out)
        self.assertIn("adjustments: 3 stocks", out)
        changed_rows = sum(1 for d in DATES if d < NEW_EX)
        self.assertIn(f"changed: 1 stocks, {changed_rows} rows", out)
        self.assertIn("changed_ids=2379", out)

        # 因子:除息日(含)以後 1.0,前一天起乘上 0.95,07-15 以前再乘 0.98
        f = self.factors("2379")
        self.assertEqual(f[NEW_EX], 1.0)
        self.assertEqual(f["2026-10-08"], 1.0)
        self.assertEqual(f["2026-09-07"], 0.95)
        self.assertEqual(f[OLD_EX], 0.95)
        self.assertAlmostEqual(f["2026-07-14"], 0.98 * 0.95, places=8)
        self.assertEqual(self.factors("1268"), old_factors_1268)   # 無事件 → 不變

        # 原始 OHLC/量/金額逐位元不變
        self.assertEqual(self.raw_rows(), raw_before)

        # 指標:只對這檔全歷史重算
        out = self.run_cli("compute-indicators", "--ids", "2379")
        self.assertIn("indicators: 1 computed", out)
        with db.get_engine().connect() as conn:
            ind = conn.execute(text(
                "SELECT date, ma5, ma20 FROM indicators_daily WHERE stock_id = '2379' ORDER BY date"
            )).fetchall()
            others = conn.execute(text(
                "SELECT COUNT(*) FROM indicators_daily WHERE stock_id <> '2379'")).scalar()
        self.assertEqual(others, 0)
        self.assertEqual(len(ind), len(DATES))     # 全歷史(< 400 根全寫)
        ma20 = {d: v for d, _, v in ind if v is not None}
        self.assertIn("2026-09-07", ma20)
        self.assertIn(NEW_EX, ma20)
        # 還原後整段是平的 95:跨除息日沒有 5% 的跳動,MA20 一路 95
        for d, v in ma20.items():
            self.assertAlmostEqual(v, 95.0, places=3, msg=d)
        self.assertAlmostEqual(ma20[NEW_EX] - ma20["2026-09-07"], 0.0, places=6)

    def test_unadjusted_baseline_would_have_jumped(self):
        """對照組:不先補因子就算指標,MA5 在除息後一週內掉約 5 元——上一個測試擋的就是這個。"""
        self.run_cli("compute-indicators", "--ids", "2379")
        with db.get_engine().connect() as conn:
            ma5 = dict(conn.execute(text(
                "SELECT date, ma5 FROM indicators_daily WHERE stock_id = '2379'")).fetchall())
        self.assertGreater(ma5["2026-09-07"] - ma5["2026-09-14"], 4.9)

    def test_rerun_is_idempotent_and_reports_no_change(self):
        with patch("radar.providers.finmind.fetch_dividend_results", self.fake_dividends):
            self.run_cli("compute-adjustments", "--ex-dates-since", "2026-09-04", "--sleep", "0")
            out = self.run_cli("compute-adjustments", "--ex-dates-since", "2026-09-04", "--sleep", "0")
        self.assertIn("changed: 0 stocks, 0 rows", out)
        self.assertIn("changed_ids=\n", out)

    def test_empty_selection_does_nothing(self):
        with patch("radar.providers.finmind.fetch_dividend_results",
                   lambda *a, **k: self.fail("FinMind must not be called")):
            with patch("radar.providers.twse.get_json", lambda *a, **k: {"stat": "很抱歉，沒有符合條件的資料!"}):
                buf = io.StringIO()
                with patch("radar.providers.tpex.get_json",
                           lambda *a, **k: {"stat": "ok", "tables": [{"fields": ["除權息日期", "代號"], "data": []}]}), \
                        patch("radar.cli.datetime", _FixedDatetime), redirect_stdout(buf):
                    cli.main(["compute-adjustments", "--ex-dates-since", "10"])
        self.assertIn("changed: 0 stocks, 0 rows", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
