import random
import time

import requests

from . import config

_session = requests.Session()
_session.headers["User-Agent"] = config.USER_AGENT
_last_request_at = 0.0


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
         jitter_max: float = 0.0):
    """GET with bounded retries.

    ``status_retries`` permits one endpoint to raise a specific HTTP status's
    total attempts without changing the ordinary retry budget.  Exponential
    backoff and bounded jitter are opt-in so existing callers retain their
    previous linear, jitter-free timing contract.
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
        wait = interval - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        try:
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
             throttle: float | None = None) -> str:
    """GET with throttle + retry, decoded text (MoneyDJ 系頁面為 Big5)。

    throttle 可覆寫全域間隔:搭配鏡像站輪替時,整體節奏快、單站節奏仍禮貌。
    """
    r = _get(url, params, throttle=throttle)
    r.encoding = encoding
    return r.text
