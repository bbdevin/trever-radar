"""法人族群買賣超(docs/49 MVP):外資/投信/自營/合計 × 產業/題材,今日視窗。

只整理 ``daily_institutional`` 既有的逐檔淨額,不新增資料源、不進任何分數。
寫 ``rankings/insti_flow_1d.json``;``radar.json`` / ``home/*.json`` 不受影響。

口徑(docs/49 §2):
- 母體 = ``stocks.type = 'stock' AND is_active = 1``,ETF 不算。
- 張數 = 逐檔 ``淨股數 // 1000``(同首頁卡片 ``foreign_net_lots`` 的轉法),族群張數 =
  成分逐檔張數相加,所以「族群 = Σ 成員」「產業各組 + 其他 = 全市場」兩條恆等式都成立。
- 金額(估) = Σ 淨股數 × 當日收盤;停牌取 ≤ 當日最近一筆收盤;仍無 → 金額計 0、張數照算,
  記 ``amt_missing_n``。
- 產業:官方產業別;空白或字面「其他」、以及有法人列的成分 < 3 檔的產業,併入「其他」
  (``other``,不排名)。
- 題材:``company_themes_by_stock``(與 ``radar.themes`` 同一份 membership),排除
  ``data_date`` 晚於報價日者,同名題材以 (name, stock_id) 去重;成分 ≥ 3 檔、
  |金額(估)| ≥ 1,000 萬才輸出;每個身分買超、賣超各留前 20 組。題材成分重疊,不做合計。
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from sqlalchemy import text

IDENTITIES = ("foreign", "trust", "dealer", "total")
OTHER_GROUP = "其他"
MIN_GROUP_N = 3
THEME_TOP = 20
THEME_MIN_ABS_AMT = 10_000_000
BUY_TOP = 5
SELL_TOP = 3
FILE_1D = "insti_flow_1d.json"
MAX_RAW_BYTES = 250_000
BUDGET_STEPS = (
    {"buy_top": BUY_TOP, "sell_top": SELL_TOP, "theme_top": THEME_TOP},
    {"buy_top": 3, "sell_top": 2, "theme_top": THEME_TOP},
    {"buy_top": 3, "sell_top": 2, "theme_top": 10},
)


def load_rows(conn, i_date: str) -> list[dict]:
    """``i_date`` 當日母體內每檔一列:四個淨額(股)、估算用收盤、當日漲跌幅。"""
    rows = conn.execute(text("""
        SELECT i.stock_id, s.name, s.market, s.industry,
               i.foreign_net, i.trust_net, i.dealer_net, i.total_net,
               p.close AS close_today,
               (SELECT pf.close FROM daily_prices pf
                 WHERE pf.stock_id = i.stock_id AND pf.date <= :i AND pf.close IS NOT NULL
                 ORDER BY pf.date DESC LIMIT 1) AS close_fallback,
               (SELECT pp.close FROM daily_prices pp
                 WHERE pp.stock_id = i.stock_id AND pp.date < :i AND pp.close IS NOT NULL
                 ORDER BY pp.date DESC LIMIT 1) AS prev_close
        FROM daily_institutional i
        JOIN stocks s ON s.id = i.stock_id AND s.type = 'stock' AND s.is_active = 1
        LEFT JOIN daily_prices p ON p.stock_id = i.stock_id AND p.date = :i
        WHERE i.date = :i
        ORDER BY i.stock_id
    """), {"i": i_date}).fetchall()
    out = []
    for (sid, name, market, industry, f, t, dl, tot,
         close_today, close_fb, prev_close) in rows:
        close = close_today if close_today is not None else close_fb
        chg = None
        if close_today is not None and prev_close:
            chg = round((close_today / prev_close - 1) * 100, 2)
        out.append({
            "id": sid, "name": name, "market": market, "industry": industry,
            "net": {"foreign": f, "trust": t, "dealer": dl, "total": tot},
            "close": close, "chg_pct": chg,
        })
    return out


def _stock_values(row: dict) -> dict:
    lots, amt = {}, {}
    for ident in IDENTITIES:
        shares = row["net"].get(ident) or 0
        lots[ident] = shares // 1000
        amt[ident] = shares * row["close"] if row["close"] is not None else 0
    return {**row, "lots": lots, "amt": amt, "amt_missing": row["close"] is None}


def _group_key(g: dict):
    return (-g["amt_est"], -g["net_lots"], g["name"])


def _member(s: dict, ident: str) -> dict:
    return {
        "id": s["id"], "name": s["name"], "market": s["market"],
        "net_lots": s["lots"][ident], "amt_est": round(s["amt"][ident]),
        "chg_pct": s["chg_pct"],
    }


def _group(name: str, members: list[dict], ident: str, buy_top: int = BUY_TOP, sell_top: int = SELL_TOP) -> dict:
    lots = [s["lots"][ident] for s in members]
    buys = sorted((s for s in members if s["lots"][ident] > 0),
                  key=lambda s: (-s["lots"][ident], s["id"]))[:buy_top]
    sells = sorted((s for s in members if s["lots"][ident] < 0),
                   key=lambda s: (s["lots"][ident], s["id"]))[:sell_top]
    g = {
        "name": name,
        "n": len(members),
        "buy_n": sum(1 for v in lots if v > 0),
        "sell_n": sum(1 for v in lots if v < 0),
        "net_lots": sum(lots),
        "amt_est": round(sum(s["amt"][ident] for s in members)),
        "buy_top": [_member(s, ident) for s in buys],
        "sell_top": [_member(s, ident) for s in sells],
    }
    missing = sum(1 for s in members if s["amt_missing"])
    if missing:
        g["amt_missing_n"] = missing
    return g


def _is_future(data_date: str | None, quote_date: str) -> bool:
    if not data_date:
        return False
    try:
        return date.fromisoformat(data_date) > date.fromisoformat(quote_date)
    except ValueError:
        return True  # 同 json_export:讀不懂的日期不參與當日快照


def aggregate(
    rows: list[dict],
    memberships: dict[str, list[dict]],
    *,
    as_of: str,
    data_date: str,
    generated_at: str,
    buy_top: int = BUY_TOP,
    sell_top: int = SELL_TOP,
    theme_top: int = THEME_TOP,
) -> dict:
    """純函式:``load_rows`` 的列 + 題材 membership → 1 日視窗 payload。"""
    grp = lambda name, members, ident: _group(name, members, ident, buy_top, sell_top)  # noqa: E731
    stocks = [_stock_values(r) for r in sorted(rows, key=lambda r: r["id"])]

    # ── 產業:不足 3 檔與空白/「其他」併為其他 ──
    by_ind: dict[str, list[dict]] = {}
    for s in stocks:
        ind = (s["industry"] or "").strip()
        by_ind.setdefault(ind if ind and ind != OTHER_GROUP else OTHER_GROUP, []).append(s)
    ranked_ind: dict[str, list[dict]] = {}
    other: list[dict] = []
    for ind, members in by_ind.items():
        if ind == OTHER_GROUP or len(members) < MIN_GROUP_N:
            other.extend(members)
        else:
            ranked_ind[ind] = members
    other.sort(key=lambda s: s["id"])

    # ── 題材:未來 membership 不算;同名題材 (name, stock_id) 去重 ──
    by_theme: dict[str, list[dict]] = {}
    theme_seen: set[tuple[str, str]] = set()
    theme_stale_dates: dict[str, list[str]] = {}
    for s in stocks:
        for m in memberships.get(s["id"], []):
            name = m.get("name")
            if not name or _is_future(m.get("data_date"), data_date):
                continue
            if (name, s["id"]) in theme_seen:
                continue
            theme_seen.add((name, s["id"]))
            by_theme.setdefault(name, []).append(s)
            if m.get("status") == "stale" and m.get("data_date"):
                theme_stale_dates.setdefault(name, []).append(m["data_date"])

    industry_out, theme_out, other_out, market = {}, {}, {}, {}
    for ident in IDENTITIES:
        market[ident] = {
            "net_lots": sum(s["lots"][ident] for s in stocks),
            "amt_est": round(sum(s["amt"][ident] for s in stocks)),
        }
        industry_out[ident] = sorted(
            (grp(name, members, ident) for name, members in ranked_ind.items()),
            key=_group_key,
        )
        if other:
            other_out[ident] = grp(OTHER_GROUP, other, ident)
        themes = []
        for name, members in by_theme.items():
            if len(members) < MIN_GROUP_N:
                continue
            g = grp(name, members, ident)
            if abs(g["amt_est"]) < THEME_MIN_ABS_AMT:
                continue
            if name in theme_stale_dates:
                g["cls_date"] = min(theme_stale_dates[name])
            themes.append(g)
        buys = sorted((g for g in themes if g["amt_est"] > 0), key=_group_key)[:theme_top]
        sells = sorted((g for g in themes if g["amt_est"] < 0),
                       key=lambda g: (g["amt_est"], g["net_lots"], g["name"]))[:theme_top]
        theme_out[ident] = sorted(buys + sells, key=_group_key)

    twse = sum(1 for s in stocks if s["market"] == "twse")
    tpex = sum(1 for s in stocks if s["market"] == "tpex")
    groups = {"industry": industry_out, "theme": theme_out}
    if other_out:
        groups["other"] = other_out
    return {
        "version": 1,
        "window": 1,
        "days_actual": 1,
        "as_of": as_of,
        "data_date": data_date,
        "generated_at": generated_at,
        "stale": as_of != data_date,
        "coverage": {"twse": twse, "tpex": tpex, "partial": twse == 0 or tpex == 0},
        "amt_missing_n": sum(1 for s in stocks if s["amt_missing"]),
        "market": market,
        "groups": groups,
    }


def serialize(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def fit_budget(rows: list[dict], memberships: dict[str, list[dict]], **kw) -> str:
    """docs/49 §3.2 預算:單檔 ≤ 250 KB raw。超過先砍成員數(5+3 → 3+2),再砍題材組數(20 → 10)。

    畫面的「買超前 N」讀 ``buy_top`` 長度,所以降級不必改前端。
    """
    body = ""
    for caps in BUDGET_STEPS:
        body = serialize(aggregate(rows, memberships, **kw, **caps))
        if len(body.encode("utf-8")) <= MAX_RAW_BYTES:
            return body
    return body


def write_insti_flow(
    out: Path,
    conn,
    *,
    data_date: str,
    i_date: str | None,
    memberships: dict[str, list[dict]],
    generated_at: str,
) -> Path | None:
    """寫 ``rankings/insti_flow_1d.json``(tmp + rename);``i_date`` 為 None 時不寫。"""
    if not i_date:
        return None
    body = fit_budget(
        load_rows(conn, i_date), memberships,
        as_of=i_date, data_date=data_date, generated_at=generated_at,
    )
    rank_dir = Path(out) / "rankings"
    rank_dir.mkdir(parents=True, exist_ok=True)
    path = rank_dir / FILE_1D
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, path)
    return path
