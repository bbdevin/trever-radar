"""FinMind v4 API — deep history (since IPO), one request per stock.

Free tier: anonymous works with a low hourly quota; a free registered token
raises it (~600 req/hr). Set RADAR_FINMIND_TOKEN to use a token.
"""
import os

from ..http import get_json
from . import NoDataError

API = "https://api.finmindtrade.com/api/v4/data"


class RateLimitedError(Exception):
    pass


def fetch_stock_info() -> dict[str, str]:
    """TaiwanStockInfo — one request, whole market. Returns {stock_id: industry_category}."""
    params = {"dataset": "TaiwanStockInfo"}
    token = os.environ.get("RADAR_FINMIND_TOKEN")
    if token:
        params["token"] = token
    j = get_json(API, params)
    if j.get("status") != 200:
        raise RuntimeError(f"finmind TaiwanStockInfo: status={j.get('status')} msg={j.get('msg')}")
    out: dict[str, str] = {}
    for r in j.get("data") or []:
        sid = str(r.get("stock_id", "")).strip()
        ind = (r.get("industry_category") or "").strip()
        if sid and ind and sid not in out:   # first category wins when duplicated
            out[sid] = ind
    return out


def fetch_daily_history(stock_id: str, start_date: str = "1990-01-01") -> list[dict]:
    """Return rows shaped for the daily_prices table (each row carries its own date)."""
    params = {"dataset": "TaiwanStockPrice", "data_id": stock_id, "start_date": start_date}
    token = os.environ.get("RADAR_FINMIND_TOKEN")
    if token:
        params["token"] = token
    j = get_json(API, params)
    status = j.get("status")
    if status == 402 or "quota" in str(j.get("msg", "")).lower():
        raise RateLimitedError(f"finmind quota hit: {j.get('msg')}")
    if status != 200:
        raise RuntimeError(f"finmind {stock_id}: status={status} msg={j.get('msg')}")
    data = j.get("data") or []
    if not data:
        raise NoDataError(f"finmind {stock_id}: no rows")
    return [{
        "stock_id": stock_id,
        "date": r["date"],                       # already YYYY-MM-DD
        "open": r.get("open") or None,
        "high": r.get("max") or None,
        "low": r.get("min") or None,
        "close": r.get("close") or None,
        "volume": r.get("Trading_Volume"),
        "turnover": r.get("Trading_money"),
        "transactions": r.get("Trading_turnover"),
    } for r in data]
