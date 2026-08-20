"""把 Fugle 當日分時掛上榜單聯集,並以 data/spark_day.json 當日快取。

14:10 第一次 export 會抓 ~150–200 檔(約 3–4 分鐘);同日後續 export 走快取。
台北日 != 價格日(假日/隔日)且快取對得上價格日時沿用快取;對不上就跳過,前端退回 30 日線。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .. import config
from ..providers.fugle import fetch_intraday_sparks

CACHE_NAME = "spark_day.json"


def cache_path() -> Path:
    return Path(config.DATA_DIR) / CACHE_NAME


def taipei_today() -> str:
    return datetime.now(ZoneInfo(config.TZ)).strftime("%Y-%m-%d")


def load_cache(path: Path | None = None) -> dict:
    p = path or cache_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict) or not isinstance(data.get("stocks"), dict):
        return {}
    return data


def save_cache(date: str, stocks: dict[str, dict], path: Path | None = None) -> None:
    p = path or cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"date": date, "stocks": stocks}
    p.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                 encoding="utf-8")


def _row_ok(row: dict | None) -> bool:
    if not row:
        return False
    closes = row.get("closes")
    return isinstance(closes, list) and len(closes) >= 2 and row.get("open") is not None


def attach_spark_day(
    union: dict[str, dict],
    price_date: str,
    *,
    today: str | None = None,
    cache: dict | None = None,
    fetch_fn=None,
    persist: bool = True,
) -> int:
    """在 union 各股掛 spark_day / spark_open。回傳成功掛上的檔數。"""
    if not union:
        return 0
    today = today if today is not None else taipei_today()
    cached = cache if cache is not None else load_cache()
    stocks: dict[str, dict] = {}
    if cached.get("date") == price_date:
        stocks = dict(cached.get("stocks") or {})

    missing = [sid for sid in union if not _row_ok(stocks.get(sid))]
    fetched = 0
    if missing and today == price_date and os.environ.get("FUGLE_API_KEY"):
        fn = fetch_fn or fetch_intraday_sparks
        raw = fn(missing) or {}
        for sid, row in raw.items():
            if row.get("date") != price_date or not _row_ok(row):
                continue
            stocks[sid] = {"open": row["open"], "closes": row["closes"]}
            fetched += 1
        if persist and stocks:
            save_cache(price_date, stocks)
        print(f"spark_day: fetched {fetched}/{len(missing)} missing, cache={len(stocks)}")
    elif cached.get("date") == price_date:
        print(f"spark_day: cache hit date={price_date} n={len(stocks)}")
    else:
        print(f"spark_day: skip (today={today} price={price_date} missing={len(missing)})")

    n = 0
    for sid, s in union.items():
        row = stocks.get(sid)
        if not _row_ok(row):
            continue
        s["spark_day"] = row["closes"]
        s["spark_open"] = row["open"]
        n += 1
    return n
