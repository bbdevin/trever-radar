# -*- coding: utf-8 -*-
"""個股 chips 檔的分點日史 ``branch_days``(v2,2026-10-10;docs/44 §3.4)。

為什麼換格式:舊 ``branch_history`` 每天只留 |淨額| 前 12 列(買賣兩側合計),一邊倒的日子
另一側整個不見(2464 盟立 10/08 匯出 12 列全是賣超,買超名單空白);鉅祥只剩 6+6。來源
(每日買超前 15 + 賣超前 15,最多 30 列)在 ``branch_trades_raw`` 本來就齊,只是匯出時裁掉。

v2 把每一列都留下來(**與 raw 逐列相等**,不裁、不合併同名),但換成緊湊格式:
  {"version": 2, "per_side": 15, "names": [分點名…],
   "days": [[日期, [[名字索引, 買張, 賣張(, 淨張)], …]], …]}
  * days 新→舊,最多 ``MAX_DAYS`` 個交易日;每天的列順序 = 查詢順序(branch_id 遞減),不重排。
  * 淨張 = 買 − 賣 時省略第 4 欄;raw 的 net_lots 與買賣差不同時才寫出來(讀端一律 ``row[3]``
    優先),所以解碼後的 net 永遠等於 raw。
  * NULL 張數與舊格式相同視為 0。
名字查表讓 30 列/日比舊格式 12 列/日還小(本機量測見 docs/44 §3.4)。

``decode`` 還原成舊 ``branch_history`` 的形狀 ``[{t, branches: [{n, b, s, net}]}]``,前端
``web/lib/stockParts.ts`` 的 ``decodeBranchDays`` 是同一條規則的 TS 版;pytest 以 raw 列逐筆對照。
"""
from __future__ import annotations

from typing import Iterable

BRANCH_DAYS_VERSION = 2
PER_SIDE = 15
MAX_DAYS = 480


def encode_branch_days(rows: Iterable[tuple]) -> dict:
    """``rows`` = (date, branch_name, buy_lots, sell_lots, net_lots),已依 date DESC、branch_id DESC
    排好(json_export 的查詢順序)。同一天的列照原順序放;日期只留最新 ``MAX_DAYS`` 天。"""
    names: list[str] = []
    index: dict[str, int] = {}
    days: list[list] = []
    current: str | None = None
    current_rows: list[list[int]] | None = None
    for date, name, buy, sell, net in rows:
        if date != current:
            if len(days) >= MAX_DAYS:
                break
            current = date
            current_rows = []
            days.append([date, current_rows])
        idx = index.get(name)
        if idx is None:
            idx = index[name] = len(names)
            names.append(name)
        b = buy or 0
        s = sell or 0
        n = net or 0
        row = [idx, b, s] if n == b - s else [idx, b, s, n]
        current_rows.append(row)  # type: ignore[union-attr]
    return {"version": BRANCH_DAYS_VERSION, "per_side": PER_SIDE, "names": names, "days": days}


def decode_branch_days(payload: dict | None) -> list[dict]:
    """v2 → 舊 ``branch_history`` 形狀(新→舊)。None / 空 → []。"""
    if not payload:
        return []
    names = payload.get("names") or []
    out = []
    for date, rows in payload.get("days") or []:
        out.append({
            "t": date,
            "branches": [
                {"n": names[r[0]], "b": r[1], "s": r[2], "net": r[3] if len(r) > 3 else r[1] - r[2]}
                for r in rows
            ],
        })
    return out


def branch_history_of(payload: dict) -> list[dict]:
    """個股 payload(新或舊)的分點日史:有 ``branch_days`` 就解碼,否則用舊 ``branch_history``。"""
    if payload.get("branch_days") is not None:
        return decode_branch_days(payload["branch_days"])
    return payload.get("branch_history") or []
