# -*- coding: utf-8 -*-
"""`import-futures-day` / 21:20 修訂偵測 / last_seen 不倒退。

docs/38 §7.18:futDataDown 當天就有當天(t)的完整一般時段,OpenAPI 日報要到 t+1
才有。這裡鎖住的是當日匯入的四條安全性質(不是今天 → 75 不寫、閘門沒過 → 75 不寫、
只寫 d 的列、probe 完全不碰資料庫),以及兩個寫入者並存之後才會出現的兩個問題
(21:20 那份把 last_seen 往回拉、官方日報與先寫入那份不一致)。

不連網:TAIFEX 的兩個 fetch 一律 mock 掉。
"""
import contextlib
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from sqlalchemy import create_engine, text as sql_text

import radar.config as config
import radar.db as db
from radar import cli, importer, schema
from radar.providers import NoDataError
from radar.providers.taifex import (
    SESSION_AFTER_HOURS,
    SESSION_REGULAR,
    FuturesContractRow,
    FuturesDailyRow,
)

TODAY = "2026-10-02"
PREV = "2026-10-01"
CODES = ["AAF", "ABF", "ACF", "ADF", "AEF", "AFF"]


def _contract(code, stock_id="9999"):
    return FuturesContractRow(
        contract_code=code, product_code=code[:-1], stock_id=stock_id, stock_name="x",
        is_stock_future=True, is_stock_option=False, is_weekly_option=False,
        market="twse", contract_multiplier=2000,
    )


def _row(code, d, session=SESSION_REGULAR, month="202610", volume=10, oi=100,
         settlement=50.0):
    return FuturesDailyRow(
        contract_code=code, date=d, contract_month=month, session=session,
        open=1.0, high=1.0, low=1.0, last=1.0, change=0.0,
        volume=volume, settlement_price=settlement, open_interest=oi,
    )


def _feed(d, codes=CODES, after_hours=True):
    """futDataDown 對 d 的回應:每檔一般 + 價差 (+ 盤後),外加一列指數期貨。"""
    rows = []
    for c in codes:
        rows.append(_row(c, d))
        rows.append(_row(c, d, month="202610/202611", volume=1))
        if after_hours:
            rows.append(_row(c, d, session=SESSION_AFTER_HOURS, settlement=None, oi=None))
    rows.append(_row("TXF", d))
    return rows


class _TempDb(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._old = config.DB_URL, config.DATA_DIR
        config.DATA_DIR = tmp
        config.DB_URL = "sqlite:///" + (tmp / "t.db").as_posix()
        db._engine = None
        db.init_db()

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old
        self._tmp.cleanup()

    def _q(self, sql, **params):
        with db.get_engine().connect() as conn:
            return conn.execute(sql_text(sql), params).fetchall()

    def _seed_prices(self, d):
        with db.get_engine().begin() as conn:
            conn.execute(schema.daily_prices.insert().values(
                stock_id="2330", date=d, close=1.0, adj_factor=1.0))

    def _seed_futures(self, d, codes=CODES):
        rows = [_row(c, d) for c in codes]
        with db.get_engine().begin() as conn:
            db.upsert(conn, schema.futures_daily, importer._futures_daily_payload(rows))

    def _futures_rows(self):
        return self._q("SELECT COUNT(*) FROM futures_daily")[0][0]

    def _patch_taifex(self, rows=None, contracts=None, history_exc=None):
        contracts = contracts if contracts is not None else [_contract(c) for c in CODES]
        hist = mock.patch("radar.providers.taifex.fetch_history",
                          side_effect=history_exc, return_value=rows)
        lst = mock.patch("radar.providers.taifex.fetch_stock_list", return_value=contracts)
        return hist, lst


class ImportFuturesDay(_TempDb):
    def _run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                cli.main(["import-futures-day", *argv])
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_not_today_exits_75_without_fetching_or_writing(self):
        self._seed_prices(PREV)          # 現貨還停在昨天
        hist, lst = self._patch_taifex(_feed(TODAY))
        with hist as h, lst, mock.patch.object(importer, "_taipei_today", return_value=TODAY):
            code, _, err = self._run_cli()
        self.assertEqual(code, 75)
        self.assertIn("spot not in yet", err)
        h.assert_not_called()
        self.assertEqual(self._futures_rows(), 0)
        self.assertEqual(self._q("SELECT COUNT(*) FROM futures_contracts")[0][0], 0)
        self.assertEqual(self._q("SELECT COUNT(*) FROM import_logs")[0][0], 0)

    def test_completeness_guard_exits_75_and_names_missing_codes_without_writing(self):
        self._seed_prices(TODAY)
        self._seed_futures(PREV)                     # 前一個期貨日:6 檔
        before = self._futures_rows()
        partial = _feed(TODAY, codes=CODES[:3])      # 今天只有 3 檔 < 6 − 2
        hist, lst = self._patch_taifex(partial)
        with hist, lst, mock.patch.object(importer, "_taipei_today", return_value=TODAY):
            code, _, err = self._run_cli()
        self.assertEqual(code, 75)
        self.assertIn("ADF AEF AFF", err)
        self.assertEqual(self._futures_rows(), before)
        self.assertEqual(self._q("SELECT COUNT(*) FROM futures_contracts")[0][0], 0)
        self.assertEqual(self._q("SELECT COUNT(*) FROM import_logs")[0][0], 0)

    def test_guard_tolerates_the_slack(self):
        self._seed_prices(TODAY)
        self._seed_futures(PREV)
        hist, lst = self._patch_taifex(_feed(TODAY, codes=CODES[:4]))   # 6 − 2 = 4:剛好過
        with hist, lst, mock.patch.object(importer, "_taipei_today", return_value=TODAY):
            code, _, _ = self._run_cli()
        self.assertEqual(code, 0)

    def test_spread_only_codes_do_not_count_toward_the_guard(self):
        self._seed_prices(TODAY)
        self._seed_futures(PREV)
        feed = [r for r in _feed(TODAY) if not (r.contract_code in CODES[2:]
                                                and r.session == SESSION_REGULAR
                                                and "/" not in r.contract_month)]
        hist, lst = self._patch_taifex(feed)        # 4 檔只剩價差/盤後
        with hist, lst, mock.patch.object(importer, "_taipei_today", return_value=TODAY):
            code, _, _ = self._run_cli()
        self.assertEqual(code, 75)
        self.assertEqual(self._q("SELECT COUNT(*) FROM futures_daily WHERE date=:d", d=TODAY)[0][0], 0)

    def test_not_published_yet_exits_75(self):
        self._seed_prices(TODAY)
        hist, lst = self._patch_taifex(history_exc=NoDataError("empty parse"))
        with hist, lst, mock.patch.object(importer, "_taipei_today", return_value=TODAY):
            code, _, _ = self._run_cli()
        self.assertEqual(code, 75)
        self.assertEqual(self._futures_rows(), 0)

    def test_join_matching_nothing_is_an_error_not_a_pending(self):
        self._seed_prices(TODAY)
        hist, lst = self._patch_taifex(_feed(TODAY), contracts=[_contract("ZZF")])
        with hist, lst, mock.patch.object(importer, "_taipei_today", return_value=TODAY):
            with self.assertRaises(RuntimeError):
                importer.import_futures_day()
        self.assertEqual(self._futures_rows(), 0)

    def test_happy_path_writes_both_sessions_for_d_only(self):
        self._seed_prices(TODAY)
        self._seed_futures(PREV)
        feed = _feed(TODAY) + [_row("AAF", "2026-09-30", volume=999)]   # 別天的列不寫
        hist, lst = self._patch_taifex(feed)
        with hist as h, lst, mock.patch.object(importer, "_taipei_today", return_value=TODAY):
            code, out, _ = self._run_cli()
        self.assertEqual(code, 0)
        h.assert_called_once_with(TODAY, TODAY)
        self.assertIn(f"futures-day {TODAY}", out)
        self.assertIn(f"{SESSION_AFTER_HOURS}=6", out)
        self.assertIn(f"{SESSION_REGULAR}=12", out)          # 6 一般 + 6 價差
        got = dict(self._q(
            "SELECT session, COUNT(*) FROM futures_daily WHERE date=:d GROUP BY session",
            d=TODAY))
        self.assertEqual(got, {SESSION_REGULAR: 12, SESSION_AFTER_HOURS: 6})
        self.assertEqual(self._q("SELECT COUNT(*) FROM futures_daily WHERE date='2026-09-30'")[0][0], 0)
        self.assertEqual(self._q("SELECT COUNT(*) FROM futures_daily WHERE contract_code='TXF'")[0][0], 0)
        logs = self._q("SELECT source, dataset, date, rows, status FROM import_logs")
        self.assertEqual([tuple(r) for r in logs], [("taifex", "futures-day", TODAY, 18, "ok")])
        self.assertEqual(
            {r[0] for r in self._q("SELECT last_seen FROM futures_contracts")}, {TODAY})

    def test_after_hours_is_not_required(self):
        self._seed_prices(TODAY)
        hist, lst = self._patch_taifex(_feed(TODAY, after_hours=False))
        with hist, lst, mock.patch.object(importer, "_taipei_today", return_value=TODAY):
            code, out, _ = self._run_cli()
        self.assertEqual(code, 0)
        self.assertNotIn(SESSION_AFTER_HOURS, out)

    def test_explicit_date_skips_the_today_check(self):
        self._seed_prices(PREV)
        hist, lst = self._patch_taifex(_feed(PREV))
        with hist, lst, mock.patch.object(importer, "_taipei_today", return_value=TODAY):
            code, _, _ = self._run_cli("--date", PREV)
        self.assertEqual(code, 0)
        self.assertGreater(self._q("SELECT COUNT(*) FROM futures_daily WHERE date=:d", d=PREV)[0][0], 0)


class LastSeenNeverRegresses(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        schema.metadata.create_all(self.engine)

    def _upsert(self, seen_on):
        with self.engine.begin() as conn:
            importer._upsert_futures_contracts(conn, [_contract("AAF")], seen_on)

    def _seen(self):
        with self.engine.connect() as conn:
            return tuple(conn.execute(sql_text(
                "SELECT first_seen, last_seen FROM futures_contracts")).fetchone())

    def test_older_run_after_same_day_import_keeps_the_newer_last_seen(self):
        self._upsert(TODAY)      # 16:10 import-futures-day 寫 t
        self._upsert(PREV)       # 21:20 import-futures(OpenAPI)仍是 t−1
        self.assertEqual(self._seen(), (TODAY, TODAY))

    def test_newer_run_still_advances_last_seen(self):
        self._upsert(PREV)
        self._upsert(TODAY)
        self.assertEqual(self._seen(), (PREV, TODAY))


class RevisionDetector(_TempDb):
    def _count(self, rows):
        with db.get_engine().connect() as conn:
            return importer._count_futures_revisions(conn, PREV, rows)

    def test_counts_only_changed_overlapping_rows(self):
        self._seed_futures(PREV, codes=["AAF", "ABF", "ACF", "ADF"])
        incoming = [
            _row("AAF", PREV),                    # 相同
            _row("ABF", PREV, volume=11),         # 量不同
            _row("ACF", PREV, oi=101),            # 未平倉不同
            _row("ADF", PREV, settlement=50.5),   # 結算價不同
            _row("AEF", PREV, volume=0),          # 新列:不算修訂
        ]
        self.assertEqual(self._count(incoming), {"compared": 4, "changed": 3})

    def test_none_and_zero_are_different_facts(self):
        with db.get_engine().begin() as conn:
            db.upsert(conn, schema.futures_daily, importer._futures_daily_payload([
                _row("AAF", PREV, volume=None),
                _row("ABF", PREV, volume=0),
                _row("ACF", PREV, settlement=None),
            ]))
        incoming = [
            _row("AAF", PREV, volume=0),          # None → 0:改了
            _row("ABF", PREV, volume=None),       # 0 → None:改了
            _row("ACF", PREV, settlement=None),   # None → None:沒改
        ]
        self.assertEqual(self._count(incoming), {"compared": 3, "changed": 2})

    def test_stored_spreads_missing_from_openapi_are_not_revisions(self):
        with db.get_engine().begin() as conn:
            db.upsert(conn, schema.futures_daily, importer._futures_daily_payload([
                _row("AAF", PREV), _row("AAF", PREV, month="202610/202611")]))
        self.assertEqual(self._count([_row("AAF", PREV)]), {"compared": 1, "changed": 0})

    def test_import_futures_prints_the_check_and_still_overwrites(self):
        self._seed_futures(PREV, codes=["AAF", "ABF"])
        report = [_row("AAF", PREV), _row("ABF", PREV, volume=77),
                  _row("ABF", PREV, session=SESSION_AFTER_HOURS)]
        out = io.StringIO()
        with mock.patch("radar.providers.taifex.fetch_daily_report", return_value=report), \
                mock.patch("radar.providers.taifex.fetch_stock_list",
                           return_value=[_contract("AAF"), _contract("ABF")]), \
                contextlib.redirect_stdout(out):
            cli.cmd_import_futures(None)
        self.assertIn(f"futures revision check: date={PREV} compared=2 changed=1", out.getvalue())
        vol = self._q("SELECT volume FROM futures_daily WHERE contract_code='ABF' "
                      "AND session=:s", s=SESSION_REGULAR)[0][0]
        self.assertEqual(vol, 77)   # 官方日報為準


if __name__ == "__main__":
    unittest.main()
