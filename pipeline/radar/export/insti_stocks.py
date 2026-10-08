"""法人買賣超個股排行(docs/49 §9「個股」模式):外資/投信/自營/合計 × 買超/賣超前 30 檔。

寫 ``rankings/insti_stocks_1d.json``,切到「法人族群 → 個股」才抓;與 ``insti_flow_1d.json``
分開,不吃族群檔的 250 KB 預算。``radar.json`` / ``home/*.json`` / ``insti_flow_1d.json`` 不受影響。

口徑與族群檔相同(``insti_group_flow.load_rows``、``trunc_lots``):
- 母體 = ``stocks.type = 'stock' AND is_active = 1``,ETF 不算;上市＋上櫃。
- 買超 = 截斷後張數 > 0、賣超 = < 0(零股不算任一邊);排名看金額(估)= 淨股數 × 當日收盤
  (停牌取 ≤ 當日最近收盤;仍無 → 金額 0、``amt_missing``,排在同邊最後)。
- 同分:買超 金額降冪 → 張數降冪 → 代號升冪;賣超 金額升冪 → 張數升冪 → 代號升冪。
- ``streak``:同一身分截至法人日連續同方向(截斷後張數同號)的法人日數,只看最近
  ``STREAK_LOOKBACK`` 個法人日;某日缺列即中斷。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy import bindparam, text

from .insti_group_flow import IDENTITIES, _stock_values, load_rows, trunc_lots

FILE_1D = "insti_stocks_1d.json"
TOP_N = 30
STREAK_LOOKBACK = 20


def _sign(n: int) -> int:
    return (n > 0) - (n < 0)


def _row(s: dict, ident: str) -> dict:
    r = {
        "id": s["id"], "name": s["name"], "market": s["market"],
        "ind": (s["industry"] or "").strip(),
        "net_lots": s["lots"][ident], "amt_est": round(s["amt"][ident]),
        "chg_pct": s["chg_pct"],
    }
    if s["amt_missing"]:
        r["amt_missing"] = True
    return r


def rank(rows: list[dict], *, top_n: int = TOP_N) -> dict:
    """純函式:``load_rows`` 的列 → {身分: {buy, sell, buy_n, sell_n}}(尚無 streak)。"""
    stocks = [_stock_values(r) for r in sorted(rows, key=lambda r: r["id"])]
    out = {}
    for ident in IDENTITIES:
        buys = [s for s in stocks if s["lots"][ident] > 0]
        sells = [s for s in stocks if s["lots"][ident] < 0]
        # 缺收盤的金額是 0:買超排在正金額之後、賣超排在負金額之後(兩邊都在最後)
        buys.sort(key=lambda s: (s["amt_missing"], -s["amt"][ident], -s["lots"][ident], s["id"]))
        sells.sort(key=lambda s: (s["amt_missing"], s["amt"][ident], s["lots"][ident], s["id"]))
        out[ident] = {
            "buy_n": len(buys),
            "sell_n": len(sells),
            "buy": [_row(s, ident) for s in buys[:top_n]],
            "sell": [_row(s, ident) for s in sells[:top_n]],
        }
    return out


def streak_dates(conn, i_date: str, lookback: int = STREAK_LOOKBACK) -> list[str]:
    """``i_date``(含)往前最近 ``lookback`` 個法人日,新到舊。"""
    return [r[0] for r in conn.execute(text(
        "SELECT DISTINCT date FROM daily_institutional WHERE date <= :i ORDER BY date DESC LIMIT :n"
    ), {"i": i_date, "n": lookback})]


def load_history(conn, ids: list[str], dates: list[str]) -> dict[tuple[str, str], dict]:
    """(stock_id, date) → 四個淨額(股),只取排行上出現的檔。"""
    if not ids or not dates:
        return {}
    stmt = text(
        "SELECT stock_id, date, foreign_net, trust_net, dealer_net, total_net "
        "FROM daily_institutional WHERE stock_id IN :ids AND date IN :dates"
    ).bindparams(bindparam("ids", expanding=True), bindparam("dates", expanding=True))
    out = {}
    for sid, d, f, t, dl, tot in conn.execute(stmt, {"ids": sorted(ids), "dates": dates}):
        out[(sid, d)] = {"foreign": f, "trust": t, "dealer": dl, "total": tot}
    return out


def streak(history: dict[tuple[str, str], dict], sid: str, ident: str, dates: list[str]) -> int:
    """``dates`` 新到舊;第一天的方向往回數,方向改變、零張或缺列即停。"""
    n, want = 0, None
    for d in dates:
        net = history.get((sid, d))
        sign = _sign(trunc_lots((net or {}).get(ident) or 0)) if net else 0
        if sign == 0 or (want is not None and sign != want):
            break
        want = sign
        n += 1
    return n


def add_streaks(ranked: dict, history: dict, dates: list[str]) -> dict:
    for ident, sides in ranked.items():
        for side in ("buy", "sell"):
            for r in sides[side]:
                r["streak"] = streak(history, r["id"], ident, dates)
    return ranked


def build(rows: list[dict], history: dict, dates: list[str], *,
          as_of: str, data_date: str, generated_at: str, top_n: int = TOP_N) -> dict:
    """純函式:payload。``history``/``dates`` 給 streak 用(``dates`` 空 → streak 全 0)。"""
    ranked = add_streaks(rank(rows, top_n=top_n), history, dates)
    twse = sum(1 for r in rows if r["market"] == "twse")
    tpex = sum(1 for r in rows if r["market"] == "tpex")
    return {
        "version": 1,
        "window": 1,
        "as_of": as_of,
        "data_date": data_date,
        "generated_at": generated_at,
        "stale": as_of != data_date,
        "coverage": {"twse": twse, "tpex": tpex, "partial": twse == 0 or tpex == 0},
        "amt_missing_n": sum(1 for r in rows if r["close"] is None),
        "streak_days": len(dates),
        "top_n": top_n,
        "ranks": ranked,
    }


def serialize(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def write_insti_stocks(out: Path, conn, *, data_date: str, i_date: str | None,
                       generated_at: str) -> Path | None:
    """寫 ``rankings/insti_stocks_1d.json``(tmp + rename);``i_date`` 為 None 時不寫。"""
    if not i_date:
        return None
    rows = load_rows(conn, i_date)
    ranked_ids = {r["id"] for sides in rank(rows).values() for side in ("buy", "sell") for r in sides[side]}
    dates = streak_dates(conn, i_date)
    history = load_history(conn, sorted(ranked_ids), dates)
    body = serialize(build(rows, history, dates, as_of=i_date, data_date=data_date,
                           generated_at=generated_at))
    rank_dir = Path(out) / "rankings"
    rank_dir.mkdir(parents=True, exist_ok=True)
    path = rank_dir / FILE_1D
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, path)
    return path
