"""自選「特定分點」晚間手機推播(docs/52 §9)。

只讀已匯出的 ``branches/watch/index.json`` 與選的分點所在分片,**不開資料庫**。
規則與前端 ``web/lib/watchedBranches.ts`` 同一套(buildRows／participants／sortRows 的
「同步家數」):分點今天現股淨買超,或(權證那天就是今天、``counted``)認購淨買 ≥ 100 萬 → 買方;
現股淨賣超、認購淨賣、認售淨買 → 賣方;認售淨賣不計。

推播只在 VPS 有 ``WATCH_PUSH_NTFY_TOPIC`` 時才送(``vps/scripts/lib.sh`` 的 ``watch_push``);
這裡只決定「要不要送、送什麼」,並把送成功之後要寫的狀態交給呼叫端:

* stdout 第一行 ``STATE {json}``、``TITLE …``、``CLICK …``,其後是內文;不送時只有一行 ``SKIP 原因``。
* 去重(:func:`decide`):同一個資料日最多三則——當晚第一則(``first``)、權證算進今天之後
  名單有變的一則(``warrants``)、之後名單又有變的一則(``late``,例如 22:30 那輪補齊覆蓋)。
  「名單有變」只看 :func:`moves`(主分點參與、或至少兩家同步的 (邊, 股, 參與分點));
  張數、金額變了但名單相同不算,不再送。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

DEFAULT_BRANCHES = ("富邦-新店", "永豐金-內湖", "元大-松江")   # 第一個是主分點
MAX_BRANCHES = 6                       # 與前端 MAX_BRANCHES 同值
SITE_URL = "https://radar.techtrever.com/watchlist?tab=branches"
BIG_HOLD_LOTS = 1000                   # 與前端 isBigHold 同一條規則
HOLD_FLOOR_LOTS = 20
TOP_BUY_LINES = 3
TOP_SELL_LINES = 1
UPDATE_LINES = 3                       # 更新那則:最多列幾檔變動(其餘一行「另有 N 檔」)
LINE_MAX_CHARS = 60
STATE_VERSION = 1


def parse_branches(raw: str | None) -> list[str]:
    """``WATCH_PUSH_BRANCHES``:逗號分隔(半形或全形),第一個是主分點;空或壞值 → 預設三家。
    去頭尾空白、去重、每個名稱 ≤ 64 字、最多 6 個(與前端 normalizeSet 同)。"""
    out: list[str] = []
    for part in re.split(r"[,，]", raw or ""):
        t = part.strip()
        if not t or len(t) > 64 or t in out or any(ord(ch) < 32 for ch in t):
            continue
        out.append(t)
        if len(out) >= MAX_BRANCHES:
            break
    return out or list(DEFAULT_BRANCHES)


def short_name(branch: str) -> str:
    """「富邦-新店」→「富邦新店」(推播一行要短)。"""
    return branch.replace("-", "")


def fmt_md(d: str | None) -> str:
    m = re.match(r"^\d{4}-(\d{2})-(\d{2})$", d or "")
    return f"{m.group(1)}/{m.group(2)}" if m else (d or "—")


def fmt_lots(n: int) -> str:
    return f"{'+' if n > 0 else '−' if n < 0 else ''}{abs(n):,}"


def fmt_wan(n: float) -> str:
    """元 → 「+320萬」「−1.2億」(與前端 fmtWan 同)。"""
    a = abs(n)
    body = f"{a / 1e8:.1f}億" if a >= 1e8 else f"{round(a / 1e4):,}萬"
    return f"{'+' if n > 0 else '−' if n < 0 else ''}{body}"


def is_big_hold(hold: int, avg_vol: int | None) -> bool:
    if hold <= 0:
        return False
    return hold >= BIG_HOLD_LOTS or (bool(avg_vol) and avg_vol > 0
                                     and hold >= HOLD_FLOOR_LOTS and hold >= avg_vol)


def load_watch(data: Path, branches: list[str]) -> tuple[dict, list[dict]] | None:
    """(index, 選的分點所在分片);沒有 index → None。"""
    idx_path = data / "branches" / "watch" / "index.json"
    if not idx_path.exists():
        return None
    index = json.loads(idx_path.read_text(encoding="utf-8"))
    by_name = {b[0]: b[1] for b in index.get("branches") or []}
    shards = []
    for s in sorted({by_name[b] for b in branches if b in by_name}):
        p = data / "branches" / "watch" / f"s{s:02d}.json"
        if p.exists():
            shards.append(json.loads(p.read_text(encoding="utf-8")))
    return index, shards


def build_rows(branches: list[str], shards: list[dict], warrant_counted: bool) -> list[dict]:
    """前端 buildRows 的 Python 版,只留推播用得到的欄位。"""
    meta: dict = {}
    for sh in shards:
        meta.update(sh.get("stocks") or {})
    rows: dict[str, dict] = {}

    def row_for(sid: str) -> dict:
        r = rows.get(sid)
        if r is None:
            m = meta.get(sid) or [sid, None, None, None]
            r = rows[sid] = {"sid": sid, "name": m[0] or sid, "close": m[1], "avg_vol": m[3],
                             "cells": {}, "warrants": {}}
        return r

    for b in branches:
        brows = next((sh["branches"][b] for sh in shards if b in (sh.get("branches") or {})), [])
        for rr in brows:
            row_for(rr[0])["cells"][b] = {"net": rr[3], "hold": rr[4] or 0}
        wrows = next((sh["warrants"][b] for sh in shards if b in (sh.get("warrants") or {})), [])
        for wr in wrows:
            row_for(wr[0])["warrants"][b] = {"call": wr[1], "put": wr[2]}
    for r in rows.values():
        r["buy"], r["sell"] = [], []
        r["w_buy"], r["w_sell"] = {}, {}   # 分點 → 這一邊算進來的權證 [(種類, 金額)]
        for b in branches:
            net = (r["cells"].get(b) or {}).get("net")
            w = r["warrants"].get(b)
            if w and warrant_counted:
                call, put = w["call"], w["put"]
                if call is not None and call > 0:
                    r["w_buy"][b] = [("認購", call)]
                sell_parts = []
                if call is not None and call < 0:
                    sell_parts.append(("認購", call))
                if put is not None and put > 0:
                    sell_parts.append(("認售", put))
                if sell_parts:
                    r["w_sell"][b] = sell_parts
            if (net is not None and net > 0) or b in r["w_buy"]:
                r["buy"].append(b)
            if (net is not None and net < 0) or b in r["w_sell"]:
                r["sell"].append(b)
    return list(rows.values())


def side_amount(row: dict, side: str) -> float:
    """排序用:現股金額(估)＋算進這一邊的權證金額;都沒有 → -1(與前端 sortRows 的 amt 同)。"""
    lots = 0
    for c in row["cells"].values():
        n = c["net"]
        if n is None:
            continue
        if side == "buy" and n > 0:
            lots += n
        if side == "sell" and n < 0:
            lots -= n
    a = None if row["close"] is None else lots * row["close"] * 1000
    w = sum(abs(v) for parts in row[f"w_{side}"].values() for _k, v in parts)
    return -1 if a is None and not w else (a or 0) + w


def ordered(rows: list[dict], side: str, anchor: str) -> list[dict]:
    """這一邊有人參與的股票:主分點參與的在前,再依同步家數、金額(估)、代號。"""
    cand = [r for r in rows if r[side]]
    return sorted(cand, key=lambda r: (anchor not in r[side], -len(r[side]),
                                       -side_amount(r, side), r["sid"]))


def moves(rows: list[dict], anchor: str) -> list[list]:
    """「名單」:主分點參與、或至少兩家同步的 [邊, 代號, [參與分點…]],排序後可比對。"""
    out = []
    for side in ("buy", "sell"):
        for r in rows:
            parts = r[side]
            if anchor in parts or len(parts) >= 2:
                out.append([side, r["sid"], list(parts)])
    return sorted(out)


def fingerprint(mv: list[list]) -> str:
    return hashlib.sha1(json.dumps(mv, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def stock_line(row: dict, side: str, branches: list[str]) -> str:
    """「買超 雙鴻 3/3 富邦新店+820 永豐金內湖 權證認購+320萬 元大松江+120 估計持有量大」。"""
    bits = [f"{'買超' if side == 'buy' else '賣超'} {row['name']} {len(row[side])}/{len(branches)}"]
    big = False
    for b in row[side]:
        c = row["cells"].get(b) or {}
        net = c.get("net")
        piece = short_name(b)
        if net is not None and ((side == "buy" and net > 0) or (side == "sell" and net < 0)):
            piece += fmt_lots(net)
        for kind, amt in row[f"w_{side}"].get(b, ()):
            piece += f" 權證{kind}{fmt_wan(amt)}"
        bits.append(piece)
        big = big or is_big_hold(c.get("hold") or 0, row["avg_vol"])
    if big:
        bits.append("估計持有量大")
    line = " ".join(bits)
    return line if len(line) <= LINE_MAX_CHARS else line[:LINE_MAX_CHARS - 1] + "…"


def counts_line(rows: list[dict], branches: list[str]) -> str:
    anchor = branches[0]
    a_buy = sum(1 for r in rows if anchor in r["buy"])
    a_sell = sum(1 for r in rows if anchor in r["sell"])
    parts = [f"主分點買超 {a_buy} 檔"]
    if len(branches) >= 2:
        all_buy = sum(1 for r in rows if all(b in r["buy"] for b in branches))
        parts.append(f"全部同買 {all_buy} 檔")
    parts.append(f"主分點賣超 {a_sell} 檔")
    return " · ".join(parts)


def note_line(index: dict) -> str:
    """誠實說明:單位與估算、權證是否算進今天、現股分點覆蓋。"""
    w = index.get("warrant")
    parts = ["單位:張"]
    if not w:
        parts.append("不含權證")
    elif w.get("counted"):
        parts.append("含權證(金額為估算)")
    elif w.get("day") == index.get("as_of") and w.get("complete") is False:
        parts.append("權證分點未完整,權證同買稍後更新")
    else:
        parts.append(f"權證分點只到 {fmt_md(w.get('day'))},權證同買稍後更新")
    c = index.get("coverage")
    if c and c.get("complete") is False and (c.get("expected") or 0) > 0 \
            and (c.get("covered") or 0) < c["expected"]:
        parts.append(f"分點已匯入 {c['covered']:,}/{c['expected']:,} 檔")
    return " · ".join(parts)


def message_lines(rows: list[dict], branches: list[str], only: set | None = None) -> list[str]:
    """股票行:買超前 TOP_BUY_LINES 檔、賣超前 TOP_SELL_LINES 檔。only = 只列這些 (邊, 代號)(更新那則)。"""
    anchor = branches[0]
    if only is not None:
        picked = []
        for side in ("buy", "sell"):
            picked += [(side, r) for r in ordered(rows, side, anchor) if (side, r["sid"]) in only]
        lines = [stock_line(r, side, branches) for side, r in picked[:UPDATE_LINES]]
        if len(picked) > UPDATE_LINES:
            lines.append(f"另有 {len(picked) - UPDATE_LINES} 檔名單變動,詳見頁面")
        return lines
    lines = [stock_line(r, "buy", branches) for r in ordered(rows, "buy", anchor)[:TOP_BUY_LINES]]
    lines += [stock_line(r, "sell", branches) for r in ordered(rows, "sell", anchor)[:TOP_SELL_LINES]]
    if not lines:
        lines.append("選的分點今天都沒有進入任何股票的前 15 大買超或賣超")
    return lines


def decide(index: dict, rows: list[dict], branches: list[str], state: dict | None,
           force: bool = False) -> dict:
    """要不要送、送哪一則。回 {"send": bool, "reason", "kind", "title", "body", "state"}。"""
    as_of = index.get("as_of")
    anchor = branches[0]
    mv = moves(rows, anchor)
    fp = fingerprint(mv)
    counted = bool((index.get("warrant") or {}).get("counted"))
    same_day = (not force and state is not None and state.get("version") == STATE_VERSION
                and state.get("data_date") == as_of and state.get("branches") == branches)
    sent = dict(state.get("sent") or {}) if same_day else {}
    if same_day and state.get("fp") == fp:
        return {"send": False, "reason": f"{as_of} 名單與上一則相同,不再送"}
    if not sent:
        kind = "first"
    elif counted and "warrants" not in sent:
        kind = "warrants"
    elif "late" not in sent:
        kind = "late"
    else:
        return {"send": False, "reason": f"{as_of} 今天已送 {len(sent)} 則(上限),不再送"}
    title = f"特定分點 {fmt_md(as_of)} · 主 {short_name(anchor)}"
    if kind == "first":
        lines = message_lines(rows, branches)
    else:
        title += " · 更新"
        prev = {(m[0], m[1]): m[2] for m in (state or {}).get("moves") or []}
        changed = {(m[0], m[1]) for m in mv if prev.get((m[0], m[1])) != m[2]}
        lines = message_lines(rows, branches, only=changed)
        head = "權證算進今天之後名單有變動:" if kind == "warrants" else "名單有變動:"
        lines = [head] + (lines or ["(有股票移出名單,詳見頁面)"])
    body = "\n".join([counts_line(rows, branches), *lines, note_line(index)])
    sent[kind] = fp
    new_state = {"version": STATE_VERSION, "data_date": as_of, "branches": branches,
                 "fp": fp, "sent": sent, "moves": mv}
    return {"send": True, "kind": kind, "title": title, "body": body, "state": new_state}


def run(data: Path, branches: list[str], state: dict | None, expect_date: str | None = None,
        force: bool = False) -> dict:
    loaded = load_watch(data, branches)
    if loaded is None:
        return {"send": False, "reason": "沒有 branches/watch/index.json"}
    index, shards = loaded
    as_of = index.get("as_of")
    if not as_of:
        return {"send": False, "reason": "index 沒有資料日"}
    if expect_date and not force and as_of != expect_date:
        return {"send": False, "reason": f"資料日 {as_of} 不是本輪的 {expect_date},不送"}
    counted = bool((index.get("warrant") or {}).get("counted"))
    rows = build_rows(branches, shards, counted)
    return decide(index, rows, branches, state, force=force)
