"""radar.http._get retries transient body-read errors with the ordinary budget.

2026-10-05 16:00: import-warrant-master logged a ChunkedEncodingError
("Response ended prematurely") raised from inside ``_session.get``.  These
tests pin that such errors are retried with the standard backoff/throttle and
that, once the budget is spent, the error is raised (wrapped), not swallowed.
"""
from unittest.mock import patch

import pytest
import requests
import urllib3

import radar.config as config
import radar.http as radar_http
from radar.http import RadarHTTPError


class _Ok:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return [{"Code": "700001"}]


TRANSIENT = [
    requests.exceptions.ChunkedEncodingError(
        urllib3.exceptions.ProtocolError("Response ended prematurely")),
    requests.exceptions.ConnectionError("reset"),
    urllib3.exceptions.ProtocolError("Response ended prematurely"),
    requests.exceptions.ReadTimeout("read timed out"),
]


@pytest.fixture(autouse=True)
def _reset_throttle_clock():
    old = radar_http._last_request_at
    radar_http._last_request_at = 0.0
    yield
    radar_http._last_request_at = old


def test_chunked_encoding_error_once_then_success():
    err = requests.exceptions.ChunkedEncodingError(
        urllib3.exceptions.ProtocolError("Response ended prematurely"))
    with patch.object(radar_http._session, "get", side_effect=[err, _Ok()]) as get, \
         patch("radar.http.time.sleep") as sleep:
        rows = radar_http.get_json("https://www.tpex.org.tw/openapi/v1/tpex_warrant_issue")
    assert rows == [{"Code": "700001"}]
    assert get.call_count == 2
    # Ordinary linear backoff before the retry, and the global throttle still
    # applies to the retried request (sleep is mocked, so the throttle wait is
    # nearly the full interval).
    delays = [c.args[0] for c in sleep.call_args_list]
    assert delays[0] == config.HTTP_BACKOFF * 1
    assert len(delays) == 2 and 0 < delays[1] <= config.THROTTLE_SECONDS


@pytest.mark.parametrize("error", TRANSIENT, ids=lambda e: type(e).__name__)
def test_transient_error_once_then_success(error):
    with patch.object(radar_http._session, "get", side_effect=[error, _Ok()]) as get, \
         patch("radar.http.time.sleep"):
        response = radar_http._get("https://example.test/body", throttle=0)
    assert response.status_code == 200
    assert get.call_count == 2


@pytest.mark.parametrize("error", TRANSIENT, ids=lambda e: type(e).__name__)
def test_transient_error_every_time_gives_up_after_retry_limit(error):
    with patch.object(radar_http._session, "get", side_effect=error) as get, \
         patch("radar.http.time.sleep") as sleep:
        with pytest.raises(RadarHTTPError) as caught:
            radar_http._get("https://example.test/body", throttle=0)
    assert get.call_count == config.HTTP_RETRIES
    assert caught.value.attempts == config.HTTP_RETRIES
    assert caught.value.status_code is None
    assert caught.value.original_error is error
    assert caught.value.__cause__ is error
    # Linear backoff between attempts, no sleep after the final one.
    assert [c.args[0] for c in sleep.call_args_list] == [
        config.HTTP_BACKOFF * n for n in range(1, config.HTTP_RETRIES)
    ]
