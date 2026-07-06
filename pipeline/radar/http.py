import time

import requests

from . import config

_session = requests.Session()
_session.headers["User-Agent"] = config.USER_AGENT
_last_request_at = 0.0


def get_json(url: str, params: dict | None = None):
    """GET with throttle + retry. Returns parsed JSON or raises RuntimeError."""
    global _last_request_at
    last_err: Exception | None = None
    for attempt in range(1, config.HTTP_RETRIES + 1):
        wait = config.THROTTLE_SECONDS - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        try:
            _last_request_at = time.monotonic()
            r = _session.get(url, params=params, timeout=config.HTTP_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001 - retry any fetch/parse failure
            last_err = e
            time.sleep(config.HTTP_BACKOFF * attempt)
    raise RuntimeError(f"GET {url} failed after {config.HTTP_RETRIES} attempts: {last_err}")
