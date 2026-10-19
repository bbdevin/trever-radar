"""把 Fugle 當日分時掛上榜單聯集,並以 data/spark_day.json 當日快取。

抓取(2026-10-19 起,docs/50 §3.1):每輪 export 之前,``radar fetch-intraday`` 在**不握 DB 鎖**
的情況下把缺的檔抓進快取(第一輪 ~150–200 檔,約 3–4 分鐘);export 本身預設只讀快取
(``allow_fetch=False``)。``RADAR_EXPORT_FETCH=1`` = 舊行為,export 自己抓。
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

# 本程序這一輪抓到的完整 1 分 K 列({stock_id: rows}),連同價格日。分K(docs/50,
# export/intraday_bars.py)在同一輪 export 緊接著讀它聚成當日 5 分 K,不另發請求。
# 不進快取檔(spark_day.json 只存降採樣的收盤),也不進任何 JSON。
_minute_rows: dict[str, list[dict]] = {}
_minute_rows_date: str | None = None


def minute_rows(price_date: str) -> dict[str, list[dict]]:
    """這一輪 attach_spark_day 抓到、屬於 price_date 的 1 分 K 列;沒有就是 {}。"""
    return dict(_minute_rows) if _minute_rows_date == price_date else {}


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
    """tmp+rename:fetch-intraday 寫這個檔時,另一輪的 export 可能正在讀(不握同一把鎖)。
    以前直接 write_text,讀到寫一半的檔 → JSONDecodeError → 整個聯集掉回 30 日線。"""
    from .stock_parts import write_atomic

    p = path or cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"date": date, "stocks": stocks}
    write_atomic(p, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


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
    allow_fetch: bool = True,
) -> int:
    """在 union 各股掛 spark_day / spark_open。回傳成功掛上的檔數。

    ``allow_fetch=False``:只讀快取、絕不打 Fugle(export 的預設,抓取由 fetch-intraday 先做)。
    """
    global _minute_rows, _minute_rows_date
    if not union:
        return 0
    today = today if today is not None else taipei_today()
    cached = cache if cache is not None else load_cache()
    stocks: dict[str, dict] = {}
    if cached.get("date") == price_date:
        stocks = dict(cached.get("stocks") or {})

    missing = [sid for sid in union if not _row_ok(stocks.get(sid))]
    fetched = 0
    if missing and allow_fetch and today == price_date and os.environ.get("FUGLE_API_KEY"):
        fn = fetch_fn or fetch_intraday_sparks
        raw = fn(missing) or {}
        _minute_rows, _minute_rows_date = {}, price_date
        for sid, row in raw.items():
            if row.get("date") != price_date or not _row_ok(row):
                continue
            stocks[sid] = {"open": row["open"], "closes": row["closes"]}
            if row.get("rows"):
                _minute_rows[sid] = row["rows"]
            fetched += 1
        if persist and stocks:
            save_cache(price_date, stocks)
        print(f"spark_day: fetched {fetched}/{len(missing)} missing, cache={len(stocks)}")
    elif cached.get("date") == price_date:
        print(f"spark_day: cache hit date={price_date} n={len(stocks)} missing={len(missing)}"
              + ("" if allow_fetch else " fetch=off"))
    else:
        print(f"spark_day: skip (today={today} price={price_date} missing={len(missing)}"
              + ("" if allow_fetch else " fetch=off") + ")")

    n = 0
    for sid, s in union.items():
        row = stocks.get(sid)
        if not _row_ok(row):
            continue
        s["spark_day"] = row["closes"]
        s["spark_open"] = row["open"]
        n += 1
    return n
