"""分K(docs/50):榜單聯集近 60 個交易日的 5 分 K → ``stocks/intraday/{id}.json``。

資料來源(與 spark_day 同一個 Fugle 免費方案前提,金鑰 ``FUGLE_API_KEY``):

* 當日:spark_day 同一輪已抓的 1 分 K(``spark_day.minute_rows``)聚成 5 分 K,**不多打請求**。
* 缺的日子(新進聯集、前幾天沒抓到):``historical/candles`` timeframe=5,每檔一次請求涵蓋
  最早到最晚的缺日;每輪最多 ``ROUND_CAP`` 次,共用 fugle 模組的節流(~57 次/分)與 429 退避。

本地快取 ``DATA_DIR/intraday5/{id}.json`` = ``{"id", "days": {日期: bars}}``,``[]`` = 問過、
那天真的沒有(停牌/未上市),不再重問;最新一個交易日例外,沒拿到就下輪再問。

5 分 K 桶以**開始時間**標記:09:00、09:05 … 13:25,共 54 根;13:30 收盤集合競價那一筆
併進 13:25 那根。歷史端點的時間標記語意見 ``FUGLE_HIST_LABEL``(第一次正式跑要核對,docs/50 §4)。

輸出 ``{id, tf:"5", from, to, adjusted:false, bars:[[epoch_s,o,h,l,c,v],…]}``(原始價、量為張),
緊湊序列化、tmp+rename、內容沒變不重寫。離開聯集的股票滿 ``DELETE_GRACE_DAYS`` 個交易日
才刪檔(榜單每天進出,不讓檔案跟著閃)。

這一步在 export 裡**隔離**:``export_intraday_safe`` 任何例外只記 warning,不中斷整輪 export。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

from .. import config
from .stock_parts import dumps_compact, write_atomic

_log = logging.getLogger(__name__)

TF = "5"
KEEP_DAYS = 60
ROUND_CAP = 120
DELETE_GRACE_DAYS = 10
CACHE_DIR_NAME = "intraday5"
STATE_NAME = "_state.json"
OUT_SUBDIR = "intraday"

SESSION_OPEN_MIN = 9 * 60       # 09:00
BUCKET_MIN = 5
LAST_BUCKET = 53                # 13:25 那根(09:00 起第 54 根)
CLOSE_OFFSET_MIN = 270          # 13:30 收盤集合競價 → 併進 LAST_BUCKET

# historical/candles 分 K 的時間標記:"open" = 該根的開始時間(09:00 是第一根),
# "close" = 結束時間(09:05 是第一根)。程式按 "open" 處理;第一次正式跑看 log 的
# ``intraday label check`` 一行,若第一根是 09:05 改成 "close"(docs/50 §4)。
FUGLE_HIST_LABEL = "open"

_TPE = ZoneInfo(config.TZ)

Bar = list  # [epoch_s, o, h, l, c, v]


def cache_dir() -> Path:
    return Path(config.DATA_DIR) / CACHE_DIR_NAME


def taipei_today() -> str:
    return datetime.now(_TPE).strftime("%Y-%m-%d")


def _num(x: float) -> float | int:
    """整數價寫成 int(省位元組),其餘四捨五入到 2 位。"""
    r = round(float(x), 2)
    return int(r) if r == int(r) else r


def _parse_ts(s: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_TPE)
    return dt.astimezone(_TPE)


def aggregate_5m(rows: Iterable[dict], *, label_shift_min: int = 0) -> dict[str, list[Bar]]:
    """1 分(或 5 分)K 列 → {日期: 5 分 K}。桶以開始時間標記,13:30 那筆併進 13:25。

    ``label_shift_min``:列的時間先平移幾分鐘再分桶(歷史端點若以結束時間標記傳 -5)。
    缺分鐘不補:某個 5 分鐘裡一筆都沒有就沒有那根。09:00 前、13:30 後的列丟掉。
    """
    parsed = []
    for r in rows:
        dt = _parse_ts(r.get("date", ""))
        if dt is None:
            continue
        if label_shift_min:
            dt = dt + timedelta(minutes=label_shift_min)
        parsed.append((dt, r))
    parsed.sort(key=lambda x: x[0])

    days: dict[str, dict[int, list]] = {}
    for dt, r in parsed:
        m = dt.hour * 60 + dt.minute - SESSION_OPEN_MIN
        if m < 0 or m > CLOSE_OFFSET_MIN:
            continue
        b = min(m // BUCKET_MIN, LAST_BUCKET)
        day = dt.strftime("%Y-%m-%d")
        cur = days.setdefault(day, {}).get(b)
        if cur is None:
            days[day][b] = [r["open"], r["high"], r["low"], r["close"], r.get("volume") or 0]
        else:
            cur[1] = max(cur[1], r["high"])
            cur[2] = min(cur[2], r["low"])
            cur[3] = r["close"]
            cur[4] += r.get("volume") or 0

    out: dict[str, list[Bar]] = {}
    for day, buckets in days.items():
        y, mo, d = (int(x) for x in day.split("-"))
        open_dt = datetime(y, mo, d, 9, 0, tzinfo=_TPE)
        out[day] = [
            [int((open_dt + timedelta(minutes=b * BUCKET_MIN)).timestamp()),
             _num(v[0]), _num(v[1]), _num(v[2]), _num(v[3]), int(round(v[4]))]
            for b, v in sorted(buckets.items())
        ]
    return out


# ── 快取 ──

def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load_cache(sid: str, cdir: Path) -> dict[str, list[Bar]]:
    data = _read_json(cdir / f"{sid}.json")
    days = data.get("days") if isinstance(data, dict) else None
    return dict(days) if isinstance(days, dict) else {}


def save_cache(sid: str, days: dict[str, list[Bar]], cdir: Path) -> None:
    cdir.mkdir(parents=True, exist_ok=True)
    write_atomic(cdir / f"{sid}.json",
                 dumps_compact({"id": sid, "days": dict(sorted(days.items()))}))


def build_payload(sid: str, days: dict[str, list[Bar]]) -> dict | None:
    """前端檔案內容;一根都沒有回 None(不寫檔,前端 404 → 改看日K)。"""
    filled = sorted(d for d, bars in days.items() if bars)
    if not filled:
        return None
    return {
        "id": sid, "tf": TF, "from": filled[0], "to": filled[-1], "adjusted": False,
        "bars": [bar for d in filled for bar in days[d]],
    }


def recent_trading_days(price_date: str, n: int = KEEP_DAYS) -> list[str]:
    """資料庫裡 price_date(含)以前最近 n 個交易日,舊到新。"""
    from sqlalchemy import text

    from ..db import get_engine

    with get_engine().connect() as conn:
        rows = conn.execute(text(
            "SELECT DISTINCT date FROM daily_prices WHERE date <= :d "
            "ORDER BY date DESC LIMIT :n"), {"d": price_date, "n": n}).fetchall()
    return sorted(r[0] for r in rows)


def _default_fetch_hist(api_key: str):
    import requests

    from ..providers.fugle import fetch_historical_candles

    sess = requests.Session()

    def fetch(sid: str, date_from: str, date_to: str) -> list[dict] | None:
        return fetch_historical_candles(sid, api_key, timeframe=TF, date_from=date_from,
                                        date_to=date_to, session=sess)
    return fetch


def update_intraday(
    out: Path,
    union_ids: Iterable[str],
    price_date: str,
    *,
    trading_days: list[str] | None = None,
    allow_fetch: bool = True,
    cap: int | None = ROUND_CAP,
    minute_rows_by_id: dict[str, list[dict]] | None = None,
    fetch_hist: Callable[[str, str, str], list[dict] | None] | None = None,
    cdir: Path | None = None,
    label: str = FUGLE_HIST_LABEL,
) -> dict:
    """更新快取並寫 ``out/stocks/intraday/{id}.json``。回傳統計(也印一行 log)。

    ``cap=None`` 不設上限(``export-intraday --backfill``)。``fetch_hist`` 缺省時用 Fugle
    (沒有 ``FUGLE_API_KEY`` 就不抓)。``minute_rows_by_id`` 缺省時讀 spark_day 這一輪抓到的 1 分 K。
    """
    union = list(dict.fromkeys(union_ids))
    cdir = cdir or cache_dir()
    tdays = sorted(trading_days if trading_days is not None else recent_trading_days(price_date))
    tdays = [d for d in tdays if d <= price_date][-KEEP_DAYS:]
    stats = {"union": len(union), "requests": 0, "fetched_days": 0, "today": 0,
             "written": 0, "files": 0, "deleted": 0}
    if not tdays:
        return stats
    window = set(tdays)
    latest = tdays[-1]
    out_dir = Path(out) / "stocks" / OUT_SUBDIR

    if minute_rows_by_id is None:
        from .spark_day import minute_rows
        minute_rows_by_id = minute_rows(price_date)
    if not allow_fetch:
        fetch_hist = None
    elif fetch_hist is None:
        key = os.environ.get("FUGLE_API_KEY")
        fetch_hist = _default_fetch_hist(key) if key else None
    shift = -BUCKET_MIN if label == "close" else 0
    label_logged = False

    for sid in union:
        days = load_cache(sid, cdir)
        before = dumps_compact(dict(sorted(days.items())))
        days = {d: bars for d, bars in days.items() if d in window}

        rows = minute_rows_by_id.get(sid)
        if rows:
            agg = aggregate_5m(rows).get(price_date)
            if agg and price_date in window:
                days[price_date] = agg
                stats["today"] += 1

        missing = [d for d in tdays if d not in days]
        if missing and fetch_hist is not None and (cap is None or stats["requests"] < cap):
            stats["requests"] += 1
            got = fetch_hist(sid, missing[0], missing[-1])
            if got is not None:
                agg = aggregate_5m(got, label_shift_min=shift)
                if got and not label_logged:
                    # 第一次正式跑核對標記語意用(docs/50 §4):挑一個完整的日子看第一根/最後一根。
                    raw_day = max((r["date"][:10] for r in got), default="")
                    times = sorted(r["date"][11:16] for r in got if r["date"][:10] == raw_day)
                    print(f"intraday label check {sid} {raw_day}: first={times[0]} "
                          f"last={times[-1]} rows={len(times)} label={label}", flush=True)
                    label_logged = True
                for d in missing:
                    if agg.get(d):
                        days[d] = agg[d]
                        stats["fetched_days"] += 1
                    elif d < latest:
                        days[d] = []   # 問過、真的沒有;最新一天不記,下輪再問

        if dumps_compact(dict(sorted(days.items()))) != before:
            save_cache(sid, days, cdir)

        payload = build_payload(sid, days)
        if payload is None:
            continue
        stats["files"] += 1
        text = dumps_compact(payload)
        target = out_dir / f"{sid}.json"
        try:
            same = target.read_text(encoding="utf-8") == text
        except OSError:
            same = False
        if not same:
            out_dir.mkdir(parents=True, exist_ok=True)
            write_atomic(target, text)
            stats["written"] += 1

    stats["deleted"] = _expire_left(set(union), price_date, tdays, out_dir, cdir)
    print("intraday: " + " ".join(f"{k}={v}" for k, v in stats.items())
          + f" cap={cap} fetch={'on' if fetch_hist else 'off'}", flush=True)
    return stats


def _expire_left(union: set[str], price_date: str, tdays: list[str],
                 out_dir: Path, cdir: Path) -> int:
    """離開聯集滿 DELETE_GRACE_DAYS 個交易日才刪(輸出檔與快取)。回傳刪掉的檔數。"""
    ids = set()
    for d in (out_dir, cdir):
        if d.is_dir():
            ids |= {p.stem for p in d.glob("*.json") if not p.name.startswith("_")}
    state_path = cdir / STATE_NAME
    state = _read_json(state_path) or {}
    absent: dict[str, str] = dict(state.get("absent_since") or {})
    before = dict(absent)
    for sid in list(absent):
        if sid in union or sid not in ids:
            absent.pop(sid)

    deleted = 0
    for sid in sorted(ids - union):
        since = absent.setdefault(sid, price_date)
        # since 那天(含)起到 price_date,這檔已缺席幾個交易日;since 比視窗還舊 = 早就超過。
        n_absent = (sum(1 for d in tdays if since <= d <= price_date)
                    if since >= tdays[0] else len(tdays) + 1)
        if n_absent > DELETE_GRACE_DAYS:
            for p in (out_dir / f"{sid}.json", cdir / f"{sid}.json"):
                if p.exists():
                    p.unlink()
                    deleted += 1
            absent.pop(sid)
    if absent != before:
        cdir.mkdir(parents=True, exist_ok=True)
        write_atomic(state_path, dumps_compact({"absent_since": dict(sorted(absent.items()))}))
    return deleted


def export_intraday_safe(out: Path, union_ids: Iterable[str], price_date: str, *,
                         today: str | None = None, **kw) -> dict | None:
    """json_export 用的入口:與 spark_day 同一個「今天 = 價格日」閘門才打 Fugle;
    其餘照常(用快取重寫/到期刪檔)。任何例外只記 warning,不讓整輪 export 失敗。"""
    try:
        today = today if today is not None else taipei_today()
        kw.setdefault("allow_fetch", today == price_date)
        return update_intraday(out, union_ids, price_date, **kw)
    except Exception:  # noqa: BLE001 — 分K 是附加檔,壞了不能拖垮 export
        _log.warning("intraday bars export failed; previous files kept", exc_info=True)
        return None


def union_from_export(out: Path) -> tuple[list[str], str]:
    """CLI 用:從剛匯出的 radar.json 讀聯集代號與資料日(radar.stocks 就是聯集)。"""
    radar = json.loads((Path(out) / "radar.json").read_text(encoding="utf-8"))
    return [s["id"] for s in radar.get("stocks") or []], radar["data_date"]
