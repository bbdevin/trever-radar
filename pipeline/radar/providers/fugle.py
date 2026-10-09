"""Fugle MarketData REST — 當日 1 分 K(WP-H3 spark_day)與歷史分 K(docs/50 分K)。

金鑰:環境變數 `FUGLE_API_KEY`(與盤中 worker 同一把,不另開 token 名)。
限速:約 60 req/min;本模組所有請求共用同一個節流(間隔 1.05s),429 依 Retry-After 退避。
當日分時(intraday/candles)只有當日可查;更早的分 K 走 historical/candles(免費方案:
timeframe 1/3/5/10/15/30/60、2023-05-23 起、單次區間 < 1 年、量為張)。
"""
from __future__ import annotations

import os
import time

import requests

from .. import config

CANDLES_URL = "https://api.fugle.tw/marketdata/v1.0/stock/intraday/candles/{symbol}"
HISTORICAL_CANDLES_URL = "https://api.fugle.tw/marketdata/v1.0/stock/historical/candles/{symbol}"
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


def candle_rows(payload: dict) -> list[dict]:
    """Fugle candles JSON 的 data 列,只留 OHLC 齊全的 {date, open, high, low, close, volume}。

    intraday 與 historical 兩個端點的列格式相同(date 為帶 +08:00 的 ISO 時間)。
    """
    out: list[dict] = []
    for row in payload.get("data") or []:
        try:
            o, h, l, c = (float(row[k]) for k in ("open", "high", "low", "close"))
        except (KeyError, TypeError, ValueError):
            continue
        if not row.get("date"):
            continue
        try:
            v = float(row.get("volume") or 0)
        except (TypeError, ValueError):
            v = 0.0
        out.append({"date": str(row["date"]), "open": o, "high": h, "low": l,
                    "close": c, "volume": v})
    return out


def parse_intraday_candles(payload: dict) -> dict | None:
    """從 Fugle candles JSON 抽出 {date, open, closes, rows}。資料不足回 None。

    closes 已降採樣(spark_day 用);rows 是完整的 1 分 K 列(``candle_rows``),
    給分K(docs/50)聚成 5 分 K——同一次請求,不多打。
    """
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
        "rows": candle_rows(payload),
    }


def _throttle():
    global _last_request_at
    wait = MIN_INTERVAL - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


def _get_json(url: str, params: dict, api_key: str, session: requests.Session,
              label: str) -> dict | None:
    """節流 + 429 退避 + 有限重試。4xx/5xx 或重試用盡回 None,不丟例外中斷整批。"""
    headers = {"X-API-KEY": api_key, "User-Agent": config.USER_AGENT}
    last_err: Exception | None = None
    for attempt in range(1, config.HTTP_RETRIES + 1):
        _throttle()
        try:
            r = session.get(url, params=params, headers=headers, timeout=config.HTTP_TIMEOUT)
            if r.status_code == 429:
                retry_after = float(r.headers.get("Retry-After") or 60)
                time.sleep(min(max(retry_after, 5), 90))
                continue
            if r.status_code >= 400:
                return None
            return r.json()
        except Exception as e:  # noqa: BLE001 — 單檔失敗不擋整批
            last_err = e
            time.sleep(config.HTTP_BACKOFF * attempt)
    if last_err:
        print(f"fugle {label}: {last_err}")
    return None


def fetch_intraday_candles(symbol: str, api_key: str,
                           session: requests.Session | None = None) -> dict | None:
    """抓一檔當日 1 分 K。429 會多等再試;失敗回 None,不丟例外中斷整批。"""
    payload = _get_json(CANDLES_URL.format(symbol=symbol), {"timeframe": "1"}, api_key,
                        session or requests.Session(), symbol)
    return parse_intraday_candles(payload) if payload else None


def fetch_historical_candles(symbol: str, api_key: str, *, timeframe: str = "5",
                             date_from: str, date_to: str,
                             session: requests.Session | None = None) -> list[dict] | None:
    """抓一檔 [date_from, date_to] 的歷史分 K 列(``candle_rows``)。失敗回 None;沒資料回 []。

    免費方案限制:區間須 < 1 年、分 K 自 2023-05-23 起;呼叫端(intraday_bars)只要 60 個交易日。
    """
    payload = _get_json(
        HISTORICAL_CANDLES_URL.format(symbol=symbol),
        {"timeframe": timeframe, "from": date_from, "to": date_to,
         "fields": "open,high,low,close,volume", "sort": "asc"},
        api_key, session or requests.Session(), f"{symbol} historical",
    )
    if payload is None:
        return None
    return candle_rows(payload)


def fetch_intraday_sparks(ids: list[str], api_key: str | None = None) -> dict[str, dict]:
    """批次抓榜單股票的當日分時。回傳 {stock_id: {date, open, closes, rows}}。"""
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
