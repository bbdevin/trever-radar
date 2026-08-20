"""Fugle MarketData REST — 當日 1 分 K(WP-H3 spark_day)。

金鑰:環境變數 `FUGLE_API_KEY`(與盤中 worker 同一把,不另開 token 名)。
限速:約 60 req/min;本模組預設間隔 1.05s。
分時只有當日可查,隔日補不到——失敗或非當日就讓前端退回 30 日線。
"""
from __future__ import annotations

import os
import time

import requests

from .. import config

CANDLES_URL = "https://api.fugle.tw/marketdata/v1.0/stock/intraday/candles/{symbol}"
SPARK_DAY_POINTS = 60
MIN_INTERVAL = 1.05
_last_request_at = 0.0


def downsample_closes(closes: list[float], n: int = SPARK_DAY_POINTS) -> list[float]:
    """均勻抽 n 點,必含首尾。點數不足 n 則全留。"""
    if len(closes) <= n:
        return [round(float(c), 2) for c in closes]
    last = len(closes) - 1
    idxs: list[int] = []
    seen: set[int] = set()
    for i in range(n):
        idx = round(i * last / (n - 1))
        if idx not in seen:
            seen.add(idx)
            idxs.append(idx)
    if last not in seen:
        idxs.append(last)
    return [round(float(closes[i]), 2) for i in idxs]


def parse_intraday_candles(payload: dict) -> dict | None:
    """從 Fugle candles JSON 抽出 {date, open, closes}(已降採樣)。資料不足回 None。"""
    rows = payload.get("data") or []
    closes: list[float] = []
    for row in rows:
        c = row.get("close")
        if c is None:
            continue
        try:
            closes.append(float(c))
        except (TypeError, ValueError):
            continue
    if len(closes) < 2:
        return None
    try:
        open_px = float(rows[0]["open"])
    except (KeyError, TypeError, ValueError, IndexError):
        open_px = closes[0]
    date = payload.get("date")
    if not date:
        return None
    return {
        "date": str(date)[:10],
        "open": round(open_px, 2),
        "closes": downsample_closes(closes),
    }


def _throttle():
    global _last_request_at
    wait = MIN_INTERVAL - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


def fetch_intraday_candles(symbol: str, api_key: str,
                           session: requests.Session | None = None) -> dict | None:
    """抓一檔當日 1 分 K。429 會多等再試;失敗回 None,不丟例外中斷整批。"""
    sess = session or requests.Session()
    url = CANDLES_URL.format(symbol=symbol)
    headers = {"X-API-KEY": api_key, "User-Agent": config.USER_AGENT}
    last_err: Exception | None = None
    for attempt in range(1, config.HTTP_RETRIES + 1):
        _throttle()
        try:
            r = sess.get(url, params={"timeframe": "1"}, headers=headers,
                         timeout=config.HTTP_TIMEOUT)
            if r.status_code == 429:
                retry_after = float(r.headers.get("Retry-After") or 60)
                time.sleep(min(max(retry_after, 5), 90))
                continue
            if r.status_code >= 400:
                return None
            parsed = parse_intraday_candles(r.json())
            return parsed
        except Exception as e:  # noqa: BLE001 — 單檔失敗不擋整批
            last_err = e
            time.sleep(config.HTTP_BACKOFF * attempt)
    if last_err:
        print(f"fugle {symbol}: {last_err}")
    return None


def fetch_intraday_sparks(ids: list[str], api_key: str | None = None) -> dict[str, dict]:
    """批次抓榜單股票的當日分時。回傳 {stock_id: {date, open, closes}}。"""
    key = api_key if api_key is not None else os.environ.get("FUGLE_API_KEY")
    if not key:
        return {}
    out: dict[str, dict] = {}
    sess = requests.Session()
    total = len(ids)
    for i, sid in enumerate(ids, start=1):
        parsed = fetch_intraday_candles(sid, key, session=sess)
        if parsed:
            out[sid] = parsed
        if i == 1 or i % 20 == 0 or i == total:
            print(f"spark_day fetch {i}/{total} ok={len(out)}")
    return out
