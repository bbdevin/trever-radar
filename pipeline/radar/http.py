import random
import threading
import time

import requests

from . import config, tls

_session = requests.Session()
_session.headers["User-Agent"] = config.USER_AGENT
# Trust configuration lives in `tls`: certificate verification stays on for
# every request, and the one host that serves an incomplete certificate chain
# (www.tpex.org.tw) gets the missing intermediate supplied from a vendored
# file, scoped to that host alone.  See radar/tls.py for why that is not a
# downgrade — the trust anchor is unchanged.
tls.configure_session(_session)
_last_request_at = 0.0

# 每個 throttle_key(= 鏡像站 host)各自的節流:分點平行爬(每站一個 worker)用。
# 全域的 `_last_request_at` 是單執行緒時代的設計,多執行緒同時讀寫會兩個 worker 算出
# 同一個空檔一起發出。這裡在鎖內「預約」下一個時槽(把 last 推到 now+wait 再放鎖、
# 再睡),同一站的兩個呼叫者絕不會擠進同一個間隔。帶 key 的呼叫**不碰**全域節流:
# 站與站之間本來就互相獨立(禮貌是對單一站講的)。
_keyed_last: dict[str, float] = {}
_keyed_lock = threading.Lock()


def _reserve_keyed_slot(key: str, interval: float) -> float:
    """回傳這次請求要先睡多久(鎖內預約時槽)。"""
    with _keyed_lock:
        now = time.monotonic()
        earliest = _keyed_last.get(key, 0.0) + interval
        start = earliest if earliest > now else now
        _keyed_last[key] = start
        return start - now


class RadarHTTPError(RuntimeError):
    """An exhausted HTTP request with machine-readable transport details."""

    def __init__(self, status_code: int | None, url: str, attempts: int,
                 original_error: Exception):
        self.status_code = status_code
        self.url = url
        self.attempts = attempts
        self.original_error = original_error
        status = f"HTTP {status_code}" if status_code is not None else type(original_error).__name__
        super().__init__(f"GET {url} failed after {attempts} attempts ({status}): {original_error}")


def _status_code(error: Exception) -> int | None:
    response = getattr(error, "response", None)
    code = getattr(response, "status_code", None)
    return code if isinstance(code, int) else None


def _get(url: str, params: dict | None = None, throttle: float | None = None,
         *, retries: int | None = None, status_retries: dict[int, int] | None = None,
         backoff_base: float | None = None, exponential_backoff: bool = False,
         jitter_max: float = 0.0, throttle_key: str | None = None):
    """GET with bounded retries.

    ``status_retries`` permits one endpoint to raise a specific HTTP status's
    total attempts without changing the ordinary retry budget.  Exponential
    backoff and bounded jitter are opt-in so existing callers retain their
    previous linear, jitter-free timing contract.

    Transient body-read failures are retried like any other fetch failure:
    ``_session.get`` is not streamed, so requests reads the whole body inside
    the call and a truncated response surfaces right here as
    ``ChunkedEncodingError`` (urllib3 ``ProtocolError``), ``ConnectionError``
    or ``ReadTimeout``.  They get the ordinary attempt budget and backoff;
    after the last attempt the original error is re-raised wrapped in
    ``RadarHTTPError`` (never swallowed).
    """
    global _last_request_at
    interval = config.THROTTLE_SECONDS if throttle is None else throttle
    default_attempts = config.HTTP_RETRIES if retries is None else retries
    base = config.HTTP_BACKOFF if backoff_base is None else backoff_base
    status_retries = status_retries or {}
    # An endpoint-specific extension is deliberately all-special only.  A
    # transient 520 may receive its larger budget, but a 502/timeout anywhere
    # in the sequence falls back to the ordinary bounded retry contract.
    special_only = True
    attempt = 0
    while True:
        attempt += 1
        if throttle_key is not None:
            wait = _reserve_keyed_slot(throttle_key, interval)
        else:
            wait = interval - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        try:
            if throttle_key is None:
                _last_request_at = time.monotonic()
            r = _session.get(url, params=params, timeout=config.HTTP_TIMEOUT)
            r.raise_for_status()
            return r
        except Exception as e:  # noqa: BLE001 - retry any fetch failure
            status_code = _status_code(e)
            if status_code not in status_retries:
                special_only = False
            special_retry = special_only and status_code in status_retries
            max_attempts = status_retries[status_code] if special_retry else default_attempts
            if attempt >= max_attempts:
                raise RadarHTTPError(status_code, url, attempt, e) from e
            if special_retry:
                delay = base * (2 ** (attempt - 1) if exponential_backoff else attempt)
            else:
                # Preserve the established non-special linear, no-jitter
                # timing even when this endpoint also has a 520 override.
                delay = config.HTTP_BACKOFF * attempt if status_retries else (
                    base * (2 ** (attempt - 1) if exponential_backoff else attempt)
                )
            if special_retry and jitter_max > 0:
                delay += random.uniform(0, jitter_max)
            time.sleep(delay)


def get_json(url: str, params: dict | None = None, *,
             retries: int | None = None, status_retries: dict[int, int] | None = None,
             backoff_base: float | None = None, exponential_backoff: bool = False,
             jitter_max: float = 0.0):
    """GET with throttle + retry, parsed as JSON."""
    return _get(
        url, params, retries=retries, status_retries=status_retries,
        backoff_base=backoff_base, exponential_backoff=exponential_backoff,
        jitter_max=jitter_max,
    ).json()


def get_text(url: str, params: dict | None = None, encoding: str = "big5",
             throttle: float | None = None, throttle_key: str | None = None) -> str:
    """GET with throttle + retry, decoded text (MoneyDJ 系頁面為 Big5)。

    throttle 可覆寫全域間隔:搭配鏡像站輪替時,整體節奏快、單站節奏仍禮貌。
    throttle_key 給定時改用**該 key 自己的**間隔(平行爬每站一個 worker),不碰全域節流。
    """
    r = _get(url, params, throttle=throttle, throttle_key=throttle_key)
    r.encoding = encoding
    return r.text
