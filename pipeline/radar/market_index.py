"""`import-index`:大盤指數日收匯入(docs/49 §11)。

獨立於 ``importer.import_daily``(那條鏈的 datasets 與 ``--require`` 字面是 quotes/insti/margin,
不混進去);共用它的 ``_run``:一市一筆交易、寫 ``import_logs``(source=twse|tpex,
dataset=index)、任何例外都不往外丟。回傳每市的結果 dict,離開碼由 cli 決定。
"""
from __future__ import annotations

from . import schema
from .db import init_db, upsert
from .importer import _run
from .providers import market_index as src


def _upsert_row(conn, row: src.IndexRow) -> int:
    return upsert(conn, schema.market_indices, [{
        "market": row.market, "date": row.date, "close": row.close,
        "change": row.change, "chg_pct": row.chg_pct,
    }])


def import_market_index(date: str) -> list[dict]:
    """date: YYYYMMDD。兩市各自 ``_run``;還沒公布 → status ``empty``(與 import-daily 同義)。"""
    init_db()
    return [
        _run("twse", "index", date, lambda c: _upsert_row(c, src.fetch_twse_index(date))),
        _run("tpex", "index", date, lambda c: _upsert_row(c, src.fetch_tpex_index(date))),
    ]


def latest_indices(conn, d: str) -> list[dict]:
    """export 用:每市 ≤ ``d`` 的最新一列,固定順序 twse、tpex;沒有列的市不出。

    ``chg_pct`` 來源沒給(TPEx)時由 close/change 推:change ÷ 前收 × 100,四捨五入兩位。
    """
    from sqlalchemy import text

    out = []
    for market, name in (("twse", "加權指數"), ("tpex", "櫃買指數")):
        row = conn.execute(text("""
            SELECT date, close, change, chg_pct FROM market_indices
            WHERE market = :m AND date <= :d ORDER BY date DESC LIMIT 1
        """), {"m": market, "d": d}).fetchone()
        if row is None:
            continue
        date, close, change, pct = row
        if pct is None and change is not None and close - change:
            pct = round(change / (close - change) * 100, 2)
        out.append({"market": market, "name": name, "date": date, "close": close,
                    "change": change, "chg_pct": pct})
    return out
