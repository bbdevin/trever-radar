"""V1-Free 盤後綜合分數(docs/04;分點/題材缺席 → 權重自動重分配)。

權重:權證 0.30、技術 0.30、法人融資 0.25、題材 0.15(未實作)。
分項為 NULL(無資料)時,以可用分項權重重新歸一化;風險扣分最後套用。
純函式 score_*() 可單元測試;compute_scores() 負責取數與落地。
"""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text

from .. import config, schema
from ..db import get_engine, init_db, upsert

WEIGHTS = {"warrant": 0.30, "tech": 0.30, "inst": 0.25}   # theme 0.15 缺席
MIN_ADV20_TURNOVER = 30_000_000      # 前置過濾:20日均成交金額 3,000 萬
WARRANT_MIN_BASE = 1_000_000         # 權證基期門檻:20日均認購金額 < 100 萬 → 封頂 40


def _fmt_e8(n: float) -> str:
    return f"{n / 1e8:.2f}億" if n >= 1e8 else f"{n / 1e4:,.0f}萬"


def score_warrant(call_to, call_vol, put_to, avg_call_to, avg_call_vol,
                  ratio_prev1, ratio_prev2, chg_pct, chg5_pct):
    """回傳 (score|None, reasons, risks)。無權證成交基礎 → None(權重重分配)。"""
    reasons, risks = [], []
    if not avg_call_to or avg_call_to <= 0:
        return None, reasons, risks
    call_to = call_to or 0
    put_to = put_to or 0
    score = 0

    def add(points, code, txt, value=None):
        nonlocal score
        score += points
        reasons.append({"code": code, "points": points, "text": txt, "value": value})

    ratio = call_to / avg_call_to
    if ratio >= 3:
        add(30, "W1_TURNOVER_X3", f"認購權證成交{_fmt_e8(call_to)},為20日均值{ratio:.1f}倍", round(ratio, 2))
    elif ratio >= 2:
        add(20, "W1_TURNOVER_X2", f"認購權證成交{_fmt_e8(call_to)},為20日均值{ratio:.1f}倍", round(ratio, 2))
    elif ratio >= 1.5:
        add(10, "W1_TURNOVER_X1_5", f"認購權證成交為20日均值{ratio:.1f}倍", round(ratio, 2))

    if avg_call_vol and avg_call_vol > 0 and call_vol:
        vratio = call_vol / avg_call_vol
        if vratio >= 3:
            add(15, "W2_VOLUME_X3", f"認購權證成交量為20日均量{vratio:.1f}倍", round(vratio, 2))
        elif vratio >= 2:
            add(10, "W2_VOLUME_X2", f"認購權證成交量為20日均量{vratio:.1f}倍", round(vratio, 2))

    triggered = score > 0
    if triggered and chg_pct is not None and chg5_pct is not None \
            and chg_pct < 3 and chg5_pct < 8:
        add(20, "W3_STOCK_QUIET", f"權證先動而股價未大漲(今日{chg_pct:+.1f}%、5日{chg5_pct:+.1f}%)")

    if ratio >= 1.5 and ratio_prev1 is not None and ratio_prev1 >= 1.5:
        if ratio_prev2 is not None and ratio_prev2 >= 1.5:
            add(15, "W4_STREAK3", "權證金額放大連續3日")
        else:
            add(10, "W4_STREAK2", "權證金額放大連續2日")

    total = call_to + put_to
    if triggered and total > 5_000_000 and call_to / total >= 0.75:
        add(10, "W5_CALL_DOMINANT", f"認購佔權證成交{call_to / total:.0%}")

    if avg_call_to < WARRANT_MIN_BASE:
        score = min(score, 40)          # 低基期暴增常是單一散戶,封頂
    return min(score, 100), reasons, risks


def score_inst(f_today, f_streak3, t_today, t_streak3, total_net, volume,
               margin_use):
    """法人融資分。全部資料缺 → None。"""
    if f_today is None and t_today is None:
        return None, [], []
    reasons, risks = [], []
    score = 0

    def add(points, code, txt, value=None):
        nonlocal score
        score += points
        reasons.append({"code": code, "points": points, "text": txt, "value": value})

    # 顯著性門檻(04 §2 B7):買超需達成交量 1% 或絕對張數下限,否則不計
    t_sig = (t_today or 0) > 0 and volume and \
        ((t_today >= volume * 0.01) or t_today >= 500_000)
    f_sig = (f_today or 0) > 0 and volume and \
        ((f_today >= volume * 0.01) or f_today >= 1_000_000)
    if t_sig:
        add(15, "I_TRUST_BUY", f"投信買超{t_today // 1000:,}張", t_today // 1000)
        if t_streak3:
            add(15, "I_TRUST_STREAK", "投信連3日買超")
    if f_sig:
        add(10, "I_FOREIGN_BUY", f"外資買超{f_today // 1000:,}張", f_today // 1000)
        if f_streak3:
            add(15, "I_FOREIGN_STREAK", "外資連3日買超")
    if t_sig and f_sig:
        add(10, "I_BOTH_BUY", "外資投信同步買超")
    if total_net is not None and volume:
        share = total_net / volume
        if share >= 0.03:
            add(15, "I_NET_SHARE", f"三大法人買超佔成交量{share:.0%}", round(share, 3))
    if margin_use is not None and margin_use < 0.6:
        add(5, "I_MARGIN_OK", "融資使用率健康(<60%)", round(margin_use, 2))
    return min(score, 100), reasons, risks


def risk_deductions(chg5_pct, chg10_pct, open_, high, close, prev_close,
                    volume_ratio, tech_risks, f_streak5_sell, margin_use):
    penalty = 0
    risks = []

    def hit(points, code, txt, value=None):
        nonlocal penalty
        penalty -= points
        risks.append({"code": code, "points": -points, "text": txt, "value": value})

    if chg5_pct is not None and chg5_pct > 20:
        hit(15, "R_HOT5", f"5日累漲{chg5_pct:.0f}%,追價風險高", round(chg5_pct, 1))
    elif chg10_pct is not None and chg10_pct > 35:
        hit(15, "R_HOT10", f"10日累漲{chg10_pct:.0f}%,追價風險高", round(chg10_pct, 1))

    if None not in (open_, high, close) and volume_ratio is not None and volume_ratio >= 2.5:
        body = abs(close - open_)
        upper = high - max(open_, close)
        if body > 0 and upper >= 2 * body:
            hit(10, "R_SHOOTING", "爆量長上影,疑高檔換手或出貨")

    if None not in (open_, close, prev_close) and prev_close > 0:
        if open_ >= prev_close * 1.03 and close < open_:
            hit(8, "R_GAP_FADE", "開高走低(開盤+3%以上收黑)")

    if any(r.get("code") == "R_RSI_OVERHEAT" for r in tech_risks or []):
        hit(5, "R_RSI_OVERHEAT", "RSI14超過80,短線過熱")

    if f_streak5_sell:
        hit(8, "R_FOREIGN_SELL5", "外資連5日賣超")

    if margin_use is not None and margin_use >= 0.6:
        hit(8, "R_MARGIN_HOT", f"融資使用率{margin_use:.0%},融資過熱", round(margin_use, 2))

    return max(penalty, -40), risks


def combine(warrant, tech, inst) -> int | None:
    parts = [(s, WEIGHTS[k]) for k, s in
             (("warrant", warrant), ("tech", tech), ("inst", inst)) if s is not None]
    if not parts:
        return None
    wsum = sum(w for _, w in parts)
    return round(sum(s * w for s, w in parts) / wsum)


def compute_scores(date: str | None = None) -> dict:
    init_db()
    engine = get_engine()
    with engine.connect() as conn:
        dates = [r[0] for r in conn.execute(text(
            "SELECT DISTINCT date FROM daily_prices ORDER BY date DESC LIMIT 22"))]
        if not dates:
            raise RuntimeError("no price data")
        d = f"{date[:4]}-{date[4:6]}-{date[6:8]}" if date else dates[0]
        if d not in dates:
            raise RuntimeError(f"{d} not in recent price dates")
        di = dates.index(d)
        recent = dates[di:di + 11]                 # d 與其前 10 個交易日
        base20_start = dates[min(di + 20, len(dates) - 1)]

        # 價格(近 11 日)
        prices: dict[str, dict[str, tuple]] = {}
        for r in conn.execute(text(
            "SELECT stock_id, date, open, high, low, close, volume FROM daily_prices "
            "WHERE date >= :lo AND date <= :d AND close IS NOT NULL"),
                {"lo": recent[-1], "d": d}):
            prices.setdefault(r[0], {})[r[1]] = r

        adv = {r[0]: r[1] for r in conn.execute(text(
            "SELECT stock_id, AVG(turnover) FROM daily_prices "
            "WHERE date >= :lo AND date < :d GROUP BY stock_id"),
            {"lo": base20_start, "d": d})}

        stocks = {r[0] for r in conn.execute(text(
            "SELECT id FROM stocks WHERE type = 'stock'"))}

        # 權證:今日與前2日 + 20日均
        w_rows: dict[str, dict[str, tuple]] = {}
        for r in conn.execute(text(
            "SELECT stock_id, date, call_turnover, call_volume, put_turnover "
            "FROM warrant_stock_daily WHERE date >= :lo AND date <= :d"),
                {"lo": recent[min(2, len(recent) - 1)], "d": d}):
            w_rows.setdefault(r[0], {})[r[1]] = r
        w_avg = {r[0]: (r[1], r[2]) for r in conn.execute(text(
            "SELECT stock_id, AVG(call_turnover), AVG(call_volume) "
            "FROM warrant_stock_daily WHERE date >= :lo AND date < :d GROUP BY stock_id"),
            {"lo": base20_start, "d": d})}

        tech = {r[0]: r for r in conn.execute(text(
            "SELECT stock_id, tech_score, volume_ratio, risks, reasons "
            "FROM indicators_daily WHERE date = :d"), {"d": d})}

        insti: dict[str, dict[str, tuple]] = {}
        for r in conn.execute(text(
            "SELECT stock_id, date, foreign_net, trust_net, total_net "
            "FROM daily_institutional WHERE date >= :lo AND date <= :d"),
                {"lo": recent[min(4, len(recent) - 1)], "d": d}):
            insti.setdefault(r[0], {})[r[1]] = r

        margins = {r[0]: r for r in conn.execute(text(
            "SELECT stock_id, margin_balance, margin_limit FROM daily_margins "
            "WHERE date = :d"), {"d": d})}

    out_rows = []
    for sid in stocks:
        if (adv.get(sid) or 0) < MIN_ADV20_TURNOVER:
            continue
        p = prices.get(sid, {})
        today = p.get(d)
        if today is None:
            continue
        _, _, open_, high, _low, close, volume = today

        def close_ago(n):
            return p[recent[n]][5] if n < len(recent) and recent[n] in p else None

        prev_close = close_ago(1)
        c5, c10 = close_ago(5), close_ago(10)
        chg = (close / prev_close - 1) * 100 if prev_close else None
        chg5 = (close / c5 - 1) * 100 if c5 else None
        chg10 = (close / c10 - 1) * 100 if c10 else None

        # 權證
        wr = w_rows.get(sid, {})
        w_today = wr.get(d)
        avg_to, avg_vol = w_avg.get(sid, (None, None))

        def w_ratio(n):
            row = wr.get(recent[n]) if n < len(recent) else None
            if row is None or not avg_to:
                return None
            return (row[2] or 0) / avg_to
        w_score, w_reasons, w_risks = score_warrant(
            w_today[2] if w_today else 0, w_today[3] if w_today else 0,
            w_today[4] if w_today else 0, avg_to, avg_vol,
            w_ratio(1), w_ratio(2), chg, chg5)

        # 技術
        t = tech.get(sid)
        t_score = t[1] if t else None
        t_vr = t[2] if t else None
        t_risks = json.loads(t[3]) if t and t[3] else []
        t_reasons = json.loads(t[4]) if t and t[4] else []

        # 法人
        ins = insti.get(sid, {})

        def ins_at(n):
            return ins.get(recent[n]) if n < len(recent) else None
        i_today = ins_at(0)
        f_net = i_today[2] if i_today else None
        t_net = i_today[3] if i_today else None
        total_net = i_today[4] if i_today else None
        f_streak3 = all(ins_at(n) and (ins_at(n)[2] or 0) > 0 for n in range(3))
        t_streak3 = all(ins_at(n) and (ins_at(n)[3] or 0) > 0 for n in range(3))
        f_sell5 = all(ins_at(n) and (ins_at(n)[2] or 0) < 0 for n in range(5))
        m = margins.get(sid)
        margin_use = (m[1] / m[2]) if m and m[1] is not None and m[2] else None
        i_score, i_reasons, i_risks = score_inst(
            f_net, f_streak3, t_net, t_streak3, total_net, volume, margin_use)

        penalty, r_risks = risk_deductions(
            chg5, chg10, open_, high, close, prev_close, t_vr, t_risks,
            f_sell5, margin_use)

        base = combine(w_score, t_score, i_score)
        if base is None:
            continue
        final = max(0, min(100, base + penalty))

        top_tech = sorted(t_reasons, key=lambda r: -r.get("points", 0))[:3]
        reasons = w_reasons + top_tech + i_reasons
        risks = w_risks + t_risks + i_risks + r_risks
        out_rows.append({
            "stock_id": sid, "date": d,
            "warrant_score": w_score, "tech_score": t_score, "inst_score": i_score,
            "theme_score": None, "risk_penalty": penalty, "final": final,
            "reasons": json.dumps(reasons, ensure_ascii=False),
            "risks": json.dumps(risks, ensure_ascii=False),
        })

    with engine.begin() as conn:
        n = upsert(conn, schema.daily_scores, out_rows)
        conn.execute(schema.import_logs.insert().values(
            run_at=datetime.now(ZoneInfo(config.TZ)).isoformat(timespec="seconds"),
            source="compute", dataset="scores", date=d, rows=n, status="ok"))
    qualified = sum(1 for r in out_rows if r["final"] >= 65)
    return {"date": d, "scored": len(out_rows), "watchlist": qualified}
