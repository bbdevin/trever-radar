"""`import-index`:大盤指數日收匯入(docs/49 §11、§12)。

獨立於 ``importer.import_daily``(那條鏈的 datasets 與 ``--require`` 字面是 quotes/insti/margin,
不混進去);共用它的 ``_run``:一市一筆交易、寫 ``import_logs``(source=twse|tpex|taifex,
dataset=index)、任何例外都不往外丟。回傳每市的結果 dict,離開碼由 cli 決定。

三個序列:``twse`` 加權指數、``tpex`` 櫃買指數、``tx`` 台指期近月(一般時段)。
"""
from __future__ import annotations

import time
from datetime import date as date_cls, timedelta

from . import config, schema
from .db import init_db, upsert
from .importer import _run
from .providers import NoDataError
from .providers import market_index as src

MARKETS = ("twse", "tpex", "tx")
NAMES = {"twse": "加權指數", "tpex": "櫃買指數", "tx": src.TX_NAME}
# 首頁 head.json 每個序列帶幾個收盤給迷你走勢圖;完整歷史在 market/indices_hist.json
SPARK_N = 40
HIST_N = 260
HIST_FILE = "indices_hist.json"
# TAIFEX futDataDown 一次請求約可吃一個月;回補時按這個天數切塊,塊與塊之間睡 THROTTLE_SECONDS
TX_CHUNK_DAYS = 28


def _upsert_row(conn, row: src.IndexRow) -> int:
    return upsert(conn, schema.market_indices, [{
        "market": row.market, "date": row.date, "close": row.close,
        "change": row.change, "chg_pct": row.chg_pct,
        "contract_month": row.contract_month, "settlement": row.settlement,
    }])


def import_market_index(date: str) -> list[dict]:
    """date: YYYYMMDD。三個來源各自 ``_run``;還沒公布 → status ``empty``(與 import-daily 同義)。"""
    init_db()
    return [
        {"date": date, **_run("twse", "index", date, lambda c: _upsert_row(c, src.fetch_twse_index(date)))},
        {"date": date, **_run("tpex", "index", date, lambda c: _upsert_row(c, src.fetch_tpex_index(date)))},
        {"date": date, **_run("taifex", "index", date, lambda c: _upsert_row(c, src.fetch_tx_index(date)))},
    ]


def _iso(d8: str) -> str:
    return f"{d8[:4]}-{d8[4:6]}-{d8[6:8]}"


def backfill_market_index(start: str, days: int) -> list[dict]:
    """從 ``start``(YYYYMMDD)往回 ``days`` 個日曆日,每天三個來源各一筆 ``_run``。

    對來源禮貌:TWSE 每天一請求(get_json 自帶 THROTTLE_SECONDS 間隔);TPEx 整月一請求、
    同月各天共用;TAIFEX futDataDown 每 ``TX_CHUNK_DAYS`` 天一請求、塊間睡 THROTTLE_SECONDS。
    休市日三個來源都是 empty,正常。
    """
    from .providers.taifex import fetch_history

    init_db()
    d0 = date_cls.fromisoformat(_iso(start))
    day_list = [(d0 - timedelta(days=k)).strftime("%Y%m%d") for k in range(max(1, days))]

    tpex_months: dict[str, dict] = {}

    def tpex_for(day: str) -> src.IndexRow:
        key = day[:6]
        if key not in tpex_months:
            tpex_months[key] = src.fetch_tpex_month(day)
        return src.parse_tpex_index(tpex_months[key], day)

    tx_rows: dict[str, src.IndexRow | None] = {}
    tx_chunks_done: set[str] = set()

    def tx_for(day: str) -> src.IndexRow:
        if day not in tx_rows:
            # 以 day 為終點往回抓一塊,塊內每一天都填進快取(沒有列的填 None)
            end = date_cls.fromisoformat(_iso(day))
            begin = max(end - timedelta(days=TX_CHUNK_DAYS - 1), d0 - timedelta(days=days - 1))
            key = f"{begin}..{end}"
            if key not in tx_chunks_done:
                if tx_chunks_done:
                    time.sleep(config.THROTTLE_SECONDS)
                tx_chunks_done.add(key)
                try:
                    rows = fetch_history(begin.isoformat(), end.isoformat())
                except NoDataError:
                    rows = []
                cur = begin
                while cur <= end:
                    d8 = cur.strftime("%Y%m%d")
                    tx_rows[d8] = src.pick_tx_near_month(rows, d8)
                    cur += timedelta(days=1)
        row = tx_rows.get(day)
        if row is None:
            raise NoDataError(f"taifex futDataDown {_iso(day)}: no TX regular-session row")
        return row

    out = []
    for day in day_list:
        for source, fn in (
            ("twse", lambda c, d=day: _upsert_row(c, src.fetch_twse_index(d))),
            ("tpex", lambda c, d=day: _upsert_row(c, tpex_for(d))),
            ("taifex", lambda c, d=day: _upsert_row(c, tx_for(d))),
        ):
            out.append({"date": day, **_run(source, "index", day, fn)})
    return out


def _pct(close: float, change: float | None, pct: float | None) -> float | None:
    """來源沒給百分比時由 close/change 推:change ÷ 前收 × 100,四捨五入兩位。"""
    if pct is not None:
        return pct
    if change is None or not (close - change):
        return None
    return round(change / (close - change) * 100, 2)


def _series(conn, market: str, d: str, n: int) -> list[tuple]:
    """``market`` 在 ≤ d 的最近 n 列,**由舊到新**:(date, close, change, chg_pct, contract_month, settlement)。"""
    from sqlalchemy import text

    rows = conn.execute(text("""
        SELECT date, close, change, chg_pct, contract_month, settlement FROM market_indices
        WHERE market = :m AND date <= :d ORDER BY date DESC LIMIT :n
    """), {"m": market, "d": d, "n": n}).fetchall()
    return [tuple(r) for r in reversed(rows)]


def latest_indices(conn, d: str) -> list[dict]:
    """export 用:每個序列 ≤ ``d`` 的最新一列 + 最近 ``SPARK_N`` 個收盤(舊→新),固定順序
    twse、tpex、tx;沒有列的序列不出。``tx`` 多帶 contract_month / settlement。
    """
    out = []
    for market in MARKETS:
        rows = _series(conn, market, d, SPARK_N)
        if not rows:
            continue
        date, close, change, pct, cm, settle = rows[-1]
        item = {"market": market, "name": NAMES[market], "date": date, "close": close,
                "change": change, "chg_pct": _pct(close, change, pct),
                "spark": [r[1] for r in rows]}
        if market == "tx":
            item["contract_month"] = cm
            item["settlement"] = settle
        out.append(item)
    return out


def indices_hist(conn, d: str, generated_at: str) -> dict | None:
    """``market/indices_hist.json`` 的內容:每個序列 ≤ d 最近 ``HIST_N`` 列,
    ``points`` = [date, close, change, chg_pct](舊→新)。一個序列都沒有 → None(不寫檔)。"""
    series = {}
    for market in MARKETS:
        rows = _series(conn, market, d, HIST_N)
        if not rows:
            continue
        series[market] = {
            "name": NAMES[market],
            "points": [[r[0], r[1], r[2], _pct(r[1], r[2], r[3])] for r in rows],
        }
        if market == "tx":
            series[market]["contract_month"] = rows[-1][4]
    if not series:
        return None
    return {"version": 1, "as_of": d, "generated_at": generated_at, "series": series}


def write_indices_hist(out, conn, d: str, generated_at: str) -> bool:
    """寫 ``out/market/indices_hist.json``(緊湊、tmp+rename)。沒有資料 → 刪舊檔、回 False。"""
    from .export.stock_parts import dumps_compact, write_atomic

    target = out / "market" / HIST_FILE
    payload = indices_hist(conn, d, generated_at)
    if payload is None:
        target.unlink(missing_ok=True)
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(target, dumps_compact(payload))
    return True
