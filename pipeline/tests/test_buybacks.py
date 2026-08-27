"""E1 MOPS buyback contracts: parsing, atomic imports, point-in-time export, KB1."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import radar.config as config
import radar.db as db
from radar import schema
from radar.export.json_export import export_json
from radar.importer import BUYBACK_MAX_DAYS, _validate_buyback_range, import_buybacks
from radar.pocket import buyback_status, buyback_window_trigger, pocket_score, tag_stock, PocketContext
from radar.providers import mops


def _cells(values):
    return "".join(f"<td>{value}</td>" for value in values)


def _row(stock_id="2330", name="台積電", *, flag="N", start="115/08/01", end="115/08/31"):
    # Official t35sc09 order: serial, id, name, board, purpose, ceiling,
    # planned, price min/max, period, flag, KB1 link, then execution facts.
    return [
        "1", stock_id, name, "115/07/20", "維護公司信用及股東權益", "1,000,000,000", "5,000,000",
        "800", "1,000", start, end, flag, "KB1", "1,200,000", "100,000", "24.0%", "1,050,000,000",
        "875.5", "0.20%", "尚未執行完畢",
    ]


def _html(*rows):
    header = "".join("<th>欄位</th>" for _ in range(20))
    body = "".join(f"<tr>{_cells(row)}</tr>" for row in rows)
    return f"<html><body>出表日：115/08/15<table class='hasBorder'><tr>{header}</tr>{body}</table></body></html>"


class ParseBuybackHtmlTests(unittest.TestCase):
    def test_repeated_tables_roc_numbers_nulls_and_report_date(self):
        fixture = (Path(__file__).parent / "fixtures" / "mops_t35sc09_complete.html").read_text(encoding="utf-8")
        source = fixture + fixture
        rows = mops.parse_buybacks_html(source, "twse")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row.stock_id, row.board_date, row.start_date, row.end_date), ("2330", "2026-07-20", "2026-08-01", "2026-08-31"))
        self.assertEqual((row.planned_shares, row.executed_shares, row.transferred_shares, row.execution_pct), (5_000_000, 1_200_000, 100_000, 24.0))
        self.assertEqual((row.executed_amount, row.avg_price, row.share_ratio_pct, row.incomplete_reason), (1_050_000_000, 875.5, 0.2, "尚未執行完畢"))
        self.assertEqual((row.report_date, row.source_updated_at), ("2026-08-15", "2026-08-15"))

    def test_repeated_header_and_missing_values(self):
        values = _row("6488", "環球晶")
        values[5] = values[7] = values[13] = values[15] = "\u00a0--\u00a0"
        rows = mops.parse_buybacks_html(_html(values), "tpex")
        self.assertIsNone(rows[0].total_amount_limit)
        self.assertIsNone(rows[0].price_min)
        self.assertIsNone(rows[0].executed_shares)
        self.assertIsNone(rows[0].execution_pct)

    def test_report_date_accepts_actual_and_legacy_label(self):
        actual = _html(_row())
        self.assertEqual(mops.parse_buybacks_html(actual, "twse")[0].report_date, "2026-08-15")
        legacy = actual.replace("出表日：", "出表日期：")
        self.assertEqual(mops.parse_buybacks_html(legacy, "twse")[0].report_date, "2026-08-15")

    def test_column_drift_and_no_table_fail_closed(self):
        with self.assertRaises(mops.MopsBuybackError):
            mops.parse_buybacks_html(_html(_row()[:-1]), "twse")
        with self.assertRaises(mops.MopsBuybackError):
            mops.parse_buybacks_html("<html><body>出表日期：115/08/15</body></html>", "twse")

    def test_multiple_tables_fail_closed_when_any_data_layout_drifts(self):
        with self.assertRaises(mops.MopsBuybackError):
            mops.parse_buybacks_html(_html(_row()) + _html(_row()[:-1]), "twse")

    def test_blank_stock_id_candidate_fails_whole_batch(self):
        malformed = _row("2330")
        malformed[1] = ""
        with self.assertRaises(mops.MopsBuybackError):
            mops.parse_buybacks_html(_html(_row("2330"), malformed), "twse")

    def test_script_content_is_not_a_table_row(self):
        with self.assertRaises(mops.MopsBuybackError):
            mops.parse_buybacks_html(f"<script>{_html(_row())}</script>", "twse")


class _Response:
    def __init__(self, status_code=200, body=None, text=""):
        self.status_code, self._body, self.text = status_code, body, text

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class _Session:
    def __init__(self, post_response=None, get_response=None, post_error=None):
        self.post_response, self.get_response, self.post_error = post_response, get_response, post_error
        self.payload = None

    def post(self, url, json, headers, timeout):
        self.payload = json
        self.post_headers = headers
        if self.post_error:
            raise self.post_error
        return self.post_response

    def get(self, url, headers, timeout):
        self.get_headers = headers
        return self.get_response


class RedirectContractTests(unittest.TestCase):
    def test_redirect_success_and_verified_payload(self):
        session = _Session(
            _Response(body={"code": 200, "result": {"url": "https://mopsov.twse.com.tw/mops/web/t35sc09"}}),
            _Response(text=_html(_row())),
        )
        rows = mops.fetch_buybacks("2026-08-01", "2026-08-15", "twse", session=session)
        self.assertEqual(rows[0].stock_id, "2330")
        self.assertEqual(session.payload["apiName"], "ajax_t35sc09")
        self.assertEqual(session.payload["parameters"], {
            "TYPEK": "sii", "d1": "1150801", "d2": "1150815", "RD": "1", "encodeURIComponent": "1",
            "step": "1", "firstin": "1", "off": "1",
        })
        self.assertEqual(session.post_headers, mops._REQUEST_HEADERS)
        self.assertEqual(session.get_headers, mops._REQUEST_HEADERS)
        self.assertTrue(session.post_headers["User-Agent"].startswith("Mozilla/5.0"))
        self.assertEqual(session.get_headers["Referer"], mops.SOURCE_URL)

    def test_redirect_406_missing_url_and_network_fail_closed(self):
        for session in (
            _Session(_Response(status_code=406)),
            _Session(_Response(body={"code": 200, "result": {}})),
            _Session(post_error=OSError("offline")),
        ):
            with self.subTest(session=session):
                with self.assertRaises(mops.MopsBuybackError):
                    mops.fetch_buybacks("2026-08-01", "2026-08-15", "twse", session=session)


class BuybackDbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.old_url, self.old_dir = config.DB_URL, config.DATA_DIR
        config.DATA_DIR = Path(self.tmp.name)
        config.DB_URL = "sqlite:///" + (config.DATA_DIR / "radar.db").as_posix()
        db._engine = None
        db.init_db()

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self.old_url, self.old_dir
        self.tmp.cleanup()

    def _db_row(self, *, plan_id="old", stock_id="2330", report_date="2026-08-15", source_updated_at="2026-08-15", flag="N", start="2026-08-01", end="2026-08-31"):
        return {
            "plan_id": plan_id, "stock_id": stock_id, "name": "測試公司", "market": "twse",
            "board_date": "2026-07-20", "purpose": "維護股東權益", "total_amount_limit": None,
            "planned_shares": 5_000_000, "price_min": 10.0, "price_max": 20.0,
            "start_date": start, "end_date": end, "completed_flag": flag,
            "executed_shares": 1_000_000, "transferred_shares": None, "execution_pct": 20.0,
            "executed_amount": None, "avg_price": None, "share_ratio_pct": None, "incomplete_reason": None,
            "report_date": report_date, "source_updated_at": source_updated_at, "source": "mops_t35sc09", "imported_at": "2026-08-15T12:00:00+08:00",
        }

    def test_range_is_bounded(self):
        self.assertEqual(_validate_buyback_range("2026-01-01", "2026-01-01"), ("2026-01-01", "2026-01-01"))
        self.assertEqual(BUYBACK_MAX_DAYS, 365)
        with self.assertRaises(ValueError):
            _validate_buyback_range("2026-08-02", "2026-08-01")
        with self.assertRaises(ValueError):
            _validate_buyback_range("2025-07-31", "2026-08-01")

    def test_tpex_failure_keeps_existing_rows(self):
        with db.get_engine().begin() as conn:
            conn.execute(schema.buybacks.insert(), [self._db_row()])
        original = mops.fetch_buybacks
        try:
            def fake_fetch(_start, _end, market):
                if market == "tpex":
                    raise mops.MopsBuybackError("bad OTC table")
                return [original_parse]

            original_parse = mops.parse_buybacks_html(_html(_row()), "twse")[0]
            mops.fetch_buybacks = fake_fetch
            with self.assertRaises(RuntimeError):
                import_buybacks("2026-08-01", "2026-08-15")
        finally:
            mops.fetch_buybacks = original
        with db.get_engine().connect() as conn:
            self.assertEqual(conn.execute(schema.buybacks.select()).fetchall()[0].plan_id, "old")
            log = conn.execute(schema.import_logs.select()).mappings().first()
            self.assertEqual((log["dataset"], log["status"], log["rows"]), ("buybacks", "error", 0))

    def test_point_in_time_export_blocks_future_report(self):
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [{"id": "2330", "name": "測試公司", "market": "twse", "type": "stock", "is_active": 1}])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": "2330", "date": "2026-08-14", "close": 100, "volume": 1000, "turnover": 100000},
                {"stock_id": "2330", "date": "2026-08-15", "close": 101, "volume": 1000, "turnover": 101000},
            ])
            conn.execute(schema.buybacks.insert(), [
                self._db_row(plan_id="known", report_date="2026-08-15", source_updated_at="2026-08-15"),
                self._db_row(plan_id="future", report_date="2026-08-16", source_updated_at="2026-08-16", stock_id="2330"),
            ])
        out = Path(self.tmp.name) / "out"
        export_json(out)
        payload = json.loads((out / "stocks" / "2330.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["buyback"]["plan_id"], "known")
        self.assertEqual(payload["buyback"]["status"], "in_progress")


class BuybackPocketTests(unittest.TestCase):
    def test_y_n_statuses_and_inclusive_boundaries(self):
        base = {"start_date": "2026-08-01", "end_date": "2026-08-31"}
        self.assertEqual(buyback_status({**base, "completed_flag": "Y"}, "2026-08-01"), "completed")
        self.assertEqual(buyback_status({**base, "completed_flag": "N"}, "2026-08-01"), "in_progress")
        self.assertEqual(buyback_status({**base, "completed_flag": "N"}, "2026-08-31"), "in_progress")
        self.assertEqual(buyback_status({**base, "completed_flag": "N"}, "2026-09-01"), "expired")
        self.assertEqual(buyback_status({"completed_flag": "N", "start_date": None, "end_date": "2026-08-31"}, "2026-08-15"), "unknown")

    def test_multiple_plans_kb1_does_not_touch_final(self):
        plans = [
            {"start_date": "2026-08-01", "end_date": "2026-08-31", "completed_flag": "N"},
            {"start_date": "2026-07-01", "end_date": "2026-07-31", "completed_flag": "N"},
        ]
        tag = buyback_window_trigger(plans, "2026-08-15")
        self.assertEqual(tag["code"], "KB1_BUYBACK_WINDOW")
        stock = {"id": "2330", "scores": {"final": 71}, "themes": []}
        ctx = PocketContext(buybacks={"2330": plans})
        tag_stock("2330", stock, ctx, ["2026-08-15"], ["2026-08-15"], [], set())
        self.assertEqual(stock["scores"]["final"], 71)
        self.assertEqual(stock["pocket_score"], pocket_score({"BUYBACK"}))

    def test_no_kb2_in_runtime_code(self):
        root = Path(__file__).resolve().parents[2]
        paths = list((root / "pipeline" / "radar").rglob("*.py")) + list((root / "web").rglob("*.ts*"))
        self.assertFalse(any("KB2_BUYBACK_BRANCH" in path.read_text(encoding="utf-8") for path in paths))


if __name__ == "__main__":
    unittest.main()
