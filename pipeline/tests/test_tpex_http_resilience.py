"""TPEx 520 retry, import metadata, CLI temp-failure, and shell contracts."""
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import unittest

import requests

import radar.cli as cli
import radar.config as config
import radar.db as db
import radar.http as radar_http
import radar.importer as importer
from radar.dto import Quote
from radar.http import RadarHTTPError
from radar.providers import NoDataError, tpex


class _Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class RadarHttpRetryTests(unittest.TestCase):
    def setUp(self):
        self.old_last = radar_http._last_request_at
        radar_http._last_request_at = 0.0

    def tearDown(self):
        radar_http._last_request_at = self.old_last

    def test_520_retries_exponentially_with_jitter_and_no_final_sleep(self):
        responses = [_Response(520), _Response(520), _Response(200, {"ok": True})]
        with patch.object(radar_http._session, "get", side_effect=responses) as get, \
             patch("radar.http.time.sleep") as sleep, \
             patch("radar.http.random.uniform", side_effect=[0.5, 1.5]) as jitter:
            response = radar_http._get(
                "https://example.test/tpex", status_retries={520: 5},
                backoff_base=5, exponential_backoff=True, jitter_max=2, throttle=0,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(get.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [5.5, 11.5])
        self.assertEqual(jitter.call_count, 2)

    def test_final_520_exposes_fields_and_does_not_sleep_after_last_attempt(self):
        response = _Response(520)
        with patch.object(radar_http._session, "get", return_value=response) as get, \
             patch("radar.http.time.sleep") as sleep, \
             patch("radar.http.random.uniform", return_value=0):
            with self.assertRaises(RadarHTTPError) as caught:
                radar_http._get(
                    "https://example.test/tpex", status_retries={520: 5},
                    backoff_base=5, exponential_backoff=True, jitter_max=2, throttle=0,
                )
        error = caught.exception
        self.assertEqual(error.status_code, 520)
        self.assertEqual(error.url, "https://example.test/tpex")
        self.assertEqual(error.attempts, 5)
        self.assertIsInstance(error.original_error, requests.HTTPError)
        self.assertEqual(get.call_count, 5)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [5, 10, 20, 40])

    def test_non_520_timeout_and_json_errors_do_not_gain_special_retry_or_http_wrapper(self):
        with patch.object(radar_http._session, "get", return_value=_Response(502)), \
             patch("radar.http.time.sleep"):
            with self.assertRaises(RadarHTTPError) as caught:
                radar_http._get("https://example.test/other", status_retries={520: 5})
        self.assertEqual(caught.exception.status_code, 502)
        self.assertEqual(caught.exception.attempts, config.HTTP_RETRIES)

        with patch.object(radar_http._session, "get", side_effect=requests.Timeout("slow")), \
             patch("radar.http.time.sleep"):
            with self.assertRaises(RadarHTTPError) as caught:
                radar_http._get("https://example.test/timeout", status_retries={520: 5})
        self.assertIsNone(caught.exception.status_code)
        self.assertEqual(caught.exception.attempts, config.HTTP_RETRIES)

        with patch.object(radar_http._session, "get", return_value=_Response(200, ValueError("bad json"))):
            with self.assertRaisesRegex(ValueError, "bad json"):
                radar_http.get_json("https://example.test/json")

    def test_502_then_520s_never_extends_the_ordinary_three_attempt_budget(self):
        responses = [_Response(502), _Response(520), _Response(520), _Response(520)]
        with patch.object(radar_http._session, "get", side_effect=responses) as get, \
             patch("radar.http.time.sleep") as sleep, \
             patch("radar.http.random.uniform") as jitter:
            with self.assertRaises(RadarHTTPError) as caught:
                radar_http._get(
                    "https://example.test/mixed", status_retries={520: 5},
                    backoff_base=5, exponential_backoff=True, jitter_max=2, throttle=0,
                )
        self.assertEqual(caught.exception.status_code, 520)
        self.assertEqual(caught.exception.attempts, config.HTTP_RETRIES)
        self.assertEqual(get.call_count, config.HTTP_RETRIES)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [5, 10])
        jitter.assert_not_called()

    def test_520_then_502_then_520_stops_at_three_and_only_first_520_gets_jitter(self):
        responses = [_Response(520), _Response(502), _Response(520), _Response(520)]
        with patch.object(radar_http._session, "get", side_effect=responses) as get, \
             patch("radar.http.time.sleep") as sleep, \
             patch("radar.http.random.uniform", return_value=0.5) as jitter:
            with self.assertRaises(RadarHTTPError) as caught:
                radar_http._get(
                    "https://example.test/mixed", status_retries={520: 5},
                    backoff_base=5, exponential_backoff=True, jitter_max=2, throttle=0,
                )
        self.assertEqual(caught.exception.status_code, 520)
        self.assertEqual(caught.exception.attempts, config.HTTP_RETRIES)
        self.assertEqual(get.call_count, config.HTTP_RETRIES)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [5.5, 10])
        self.assertEqual(jitter.call_count, 1)

    def test_tpex_daily_quotes_uses_520_override_and_keeps_empty_as_no_data(self):
        with patch("radar.providers.tpex.get_json", return_value={"stat": "ok", "tables": []}) as get:
            with self.assertRaises(NoDataError):
                tpex.fetch_daily_quotes("20260901")
        self.assertEqual(get.call_args.kwargs["status_retries"], {520: 5})
        self.assertEqual(get.call_args.kwargs["backoff_base"], 5.0)
        self.assertTrue(get.call_args.kwargs["exponential_backoff"])
        self.assertEqual(get.call_args.kwargs["jitter_max"], 2.0)


class ImportDailyHttpResultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.old_url, self.old_dir = config.DB_URL, config.DATA_DIR
        root = Path(self.tmp.name)
        config.DB_URL = "sqlite:///" + (root / "test.db").as_posix()
        config.DATA_DIR = root
        db._engine = None
        db.init_db()

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self.old_url, self.old_dir
        self.tmp.cleanup()

    @staticmethod
    def _quote():
        return Quote("2330", "TSMC", "twse", 1, 2, 1, 2, 100, 200, 10)

    @staticmethod
    def _http_error(status_code=520):
        raw = requests.HTTPError(f"HTTP {status_code}")
        return RadarHTTPError(status_code, "https://tpex.example/dailyQuotes", 5, raw)

    def test_twse_transaction_commits_when_tpex_http_520_is_logged_as_partial_error(self):
        with patch("radar.importer.twse.fetch_daily_quotes", return_value=[self._quote()]), \
             patch("radar.importer.tpex.fetch_daily_quotes", side_effect=self._http_error()):
            results = importer.import_daily("20260901", ["quotes"])
        self.assertEqual(results[0]["status"], "ok")
        self.assertEqual(results[1]["error_kind"], "http")
        self.assertEqual(results[1]["status_code"], 520)
        with db.get_engine().connect() as conn:
            self.assertEqual(conn.exec_driver_sql("SELECT COUNT(*) FROM daily_prices WHERE stock_id='2330'").scalar(), 1)
            log = conn.exec_driver_sql(
                "SELECT status, error FROM import_logs WHERE source='tpex' AND dataset='quotes'"
            ).fetchone()
        self.assertEqual(log[0], "error")
        self.assertIn("HTTP 520", log[1])

    def test_parser_or_database_errors_are_not_marked_http(self):
        result = importer._run("tpex", "quotes", "20260901", lambda _conn: (_ for _ in ()).throw(ValueError("schema changed")))
        self.assertEqual(result["status"], "error")
        self.assertNotIn("error_kind", result)
        self.assertNotIn("status_code", result)

    def test_statusless_radar_http_error_is_transport_not_http(self):
        error = RadarHTTPError(None, "https://tpex.example/dailyQuotes", 3, requests.Timeout("slow"))
        result = importer._run(
            "tpex", "quotes", "20260901",
            lambda _conn: (_ for _ in ()).throw(error),
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_kind"], "transport")
        self.assertNotIn("status_code", result)

    def test_cli_exit_matrix_only_allows_the_exact_tpex_520_partial_case(self):
        twse_ok = {"source": "twse", "dataset": "quotes", "rows": 1, "status": "ok"}
        tpex_520 = {"source": "tpex", "dataset": "quotes", "rows": 0, "status": "error",
                    "error_kind": "http", "status_code": 520, "error": "HTTP 520"}
        cases = [
            ("quotes", [twse_ok, tpex_520], 75),
            ("quotes", [twse_ok, {"source": "tpex", "dataset": "quotes", "rows": 0, "status": "empty"}], 0),
            ("quotes", [{**twse_ok, "status": "empty"}, tpex_520], 1),
            ("quotes", [{**twse_ok, "status": "error", "error": "twse failed"}, tpex_520], 1),
            ("quotes", [twse_ok, {**tpex_520, "status_code": 502}], 1),
            ("quotes", [twse_ok, tpex_520, {"source": "twse", "dataset": "insti",
                                               "rows": 1, "status": "ok"}], 1),
            ("quotes", [twse_ok, tpex_520, {"source": "tpex", "dataset": "quotes",
                                               "rows": 0, "status": "empty"}], 1),
            ("quotes", [twse_ok, tpex_520, {**twse_ok, "rows": 2}], 1),
            ("quotes", [twse_ok, {"source": "tpex", "dataset": "quotes", "rows": 0,
                                    "status": "error", "error": "timeout"}], 1),
            ("quotes", [twse_ok, {"source": "tpex", "dataset": "quotes", "rows": 0,
                                    "status": "error", "error": "schema changed"}], 1),
            ("quotes", [{**twse_ok, "status": "error", "error": "twse failed"}, tpex_520], 1),
            ("quotes,insti", [twse_ok, tpex_520], 1),
        ]
        for datasets, results, expected in cases:
            with self.subTest(datasets=datasets, expected=expected), \
                 patch("radar.importer.import_daily", return_value=results):
                with self.assertRaises(SystemExit) as caught:
                    cli.cmd_import_daily(SimpleNamespace(date="20260901", datasets=datasets))
            self.assertEqual(caught.exception.code, expected)

    def _run_daily_insti_harness(self, quotes_rc=0, insti_rc=0, master_rc=0):
        """Run a copied script with a sibling fake lib; never touch VPS helpers."""
        source = Path(__file__).parents[2] / "vps" / "scripts" / "daily-insti.sh"
        with TemporaryDirectory() as tmp:
            scripts = Path(tmp) / "scripts"
            scripts.mkdir()
            script = scripts / "daily-insti.sh"
            shutil.copy2(source, script)
            events = Path(tmp) / "events.log"
            (scripts / "lib.sh").write_text(
                """#!/usr/bin/env bash
record() { printf '%s\\n' \"$1\" >> \"$RADAR_TEST_EVENTS\"; }
set -euo pipefail
trap 'record "err:$?:$BASH_COMMAND"' ERR
acquire_db_lock() { record lock; }
sync_code() { record sync; }
notify() { record \"notify:$1:$2:$3\"; }
notify_warn() { record \"warn:$1\"; }
notify_ok() { record \"ok:$1\"; }
taipei_date() { echo 20260901; }
deploy_data() { record deploy; }
radar() {
  record \"radar:$*\"
  if [ \"$1\" = import-daily ] && [ \"$2\" = --datasets ] && [ \"$3\" = quotes ]; then
    return \"${QUOTES_RC:-0}\"
  fi
  if [ \"$1\" = import-daily ] && [ \"$2\" = --datasets ] && [ \"$3\" = insti ]; then
    return \"${INSTI_RC:-0}\"
  fi
  if [ \"$1\" = import-warrant-master ]; then
    return \"${MASTER_RC:-0}\"
  fi
  return 0
}
                """,
                encoding="utf-8",
                newline="\n",
            )
            run = subprocess.run(
                # The local bash is WSL-backed and does not forward arbitrary
                # Windows env additions, so set harness-only values in Bash.
                ["bash", "-c", (
                    "RADAR_TEST_EVENTS=../events.log "
                    f"QUOTES_RC={quotes_rc} INSTI_RC={insti_rc} "
                    f"MASTER_RC={master_rc} exec bash {script.name}"
                )],
                cwd=scripts, env=os.environ, text=True,
                capture_output=True, timeout=10, check=False,
            )
            if not events.exists():
                raise AssertionError(
                    f"harness did not record events (rc={run.returncode}, "
                    f"stdout={run.stdout!r}, stderr={run.stderr!r})"
                )
            return run.returncode, events.read_text(encoding="utf-8").splitlines()

    def test_daily_insti_75_runs_independent_steps_but_never_publishes(self):
        rc, events = self._run_daily_insti_harness(quotes_rc=75)
        self.assertEqual(rc, 75)
        quotes = events.index("radar:import-daily --datasets quotes")
        insti = events.index("radar:import-daily --datasets insti")
        master = events.index("radar:import-warrant-master")
        self.assertLess(quotes, insti)
        self.assertLess(insti, master)
        self.assertTrue(any("本輪不發布" in event for event in events))
        self.assertFalse(any(event.startswith("err:") for event in events))
        self.assertFalse(any("aggregate-warrants" in event or "compute-" in event or
                             "export-json" in event or event == "deploy" or event.startswith("ok:")
                             for event in events))

    def test_daily_insti_75_with_master_failure_never_claims_data_will_publish(self):
        rc, events = self._run_daily_insti_harness(quotes_rc=75, master_rc=1)
        self.assertEqual(rc, 75)
        warnings = [event for event in events if event.startswith("warn:")]
        self.assertTrue(any("權證主檔暫時抓不到" in event for event in warnings))
        self.assertFalse(any("日K仍會上線" in event for event in warnings))
        self.assertTrue(any("本輪不發布" in event for event in warnings))
        self.assertFalse(any(event.startswith("ok:") for event in events))

    def test_daily_insti_non_75_preserves_failure_and_stops_before_independent_steps(self):
        rc, events = self._run_daily_insti_harness(quotes_rc=1)
        self.assertEqual(rc, 1)
        self.assertIn("radar:import-daily --datasets quotes", events)
        self.assertFalse(any("--datasets insti" in event or "warrant-master" in event for event in events))
        self.assertTrue(any(event.startswith("notify:") and ":high:" in event for event in events))

    def test_daily_insti_insti_failure_trips_err_once_and_stops_before_master_or_publish(self):
        rc, events = self._run_daily_insti_harness(insti_rc=42)
        self.assertEqual(rc, 42)
        self.assertIn("radar:import-daily --datasets quotes", events)
        self.assertIn("radar:import-daily --datasets insti", events)
        self.assertFalse(any("warrant-master" in event or "aggregate-warrants" in event
                             or event == "deploy" or event.startswith("ok:") for event in events))
        self.assertEqual(sum(event.startswith("err:") for event in events), 1)

    def test_daily_insti_master_failure_is_handled_without_err_and_still_publishes(self):
        rc, events = self._run_daily_insti_harness(master_rc=1)
        self.assertEqual(rc, 0)
        self.assertTrue(any("權證主檔暫時抓不到" in event for event in events))
        self.assertFalse(any(event.startswith("err:") for event in events))
        self.assertTrue(any("aggregate-warrants" in event for event in events))
        self.assertIn("deploy", events)
        self.assertTrue(any(event.startswith("ok:") for event in events))

    def test_daily_insti_success_runs_publish_sequence(self):
        rc, events = self._run_daily_insti_harness()
        self.assertEqual(rc, 0)
        self.assertTrue(any("aggregate-warrants" in event for event in events))
        self.assertTrue(any("compute-indicators" in event for event in events))
        self.assertTrue(any("compute-scores" in event for event in events))
        self.assertTrue(any("export-json" in event for event in events))
        self.assertIn("deploy", events)
        self.assertTrue(any(event.startswith("ok:") for event in events))
