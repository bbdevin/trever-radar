import time

import requests

from . import config

_session = requests.Session()
_session.headers["User-Agent"] = config.USER_AGENT
_last_request_at = 0.0


def _get(url: str, params: dict | None = None, throttle: float | None = None):
    global _last_request_at
    last_err: Exception | None = None
    interval = config.THROTTLE_SECONDS if throttle is None else throttle
    for attempt in range(1, config.HTTP_RETRIES + 1):
        wait = interval - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        try:
            _last_request_at = time.monotonic()
            r = _session.get(url, params=params, timeout=config.HTTP_TIMEOUT)
            r.raise_for_status()
            return r
        except Exception as e:  # noqa: BLE001 - retry any fetch failure
            last_err = e
            time.sleep(config.HTTP_BACKOFF * attempt)
    raise RuntimeError(f"GET {url} failed after {config.HTTP_RETRIES} attempts: {last_err}")


def get_json(url: str, params: dict | None = None):
    """GET with throttle + retry, parsed as JSON."""
    return _get(url, params).json()


def get_text(url: str, params: dict | None = None, encoding: str = "big5",
             throttle: float | None = None) -> str:
    """GET with throttle + retry, decoded text (MoneyDJ 系頁面為 Big5)。

    throttle 可覆寫全域間隔:搭配鏡像站輪替時,整體節奏快、單站節奏仍禮貌。
    """
    r = _get(url, params, throttle=throttle)
    r.encoding = encoding
    return r.text
