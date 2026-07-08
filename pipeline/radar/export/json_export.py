"""Export frontend JSON files from SQLite.

Until the scoring module exists, the radar page shows dynamic day-driven lists
(hot by turnover / surge by volume ratio / strong by change) plus a sector
money-flow panel built from industry sums vs their 20-day averages.
"""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import text

from .. import config
from ..db import get_engine, init_db

DEFAULT_OUT = config.ROOT / "web" / "public" / "data"

MIN_TURNOVER = 100_000_000          # 榜單門檻:成交金額 1 億
SURGE_MIN_RATIO = 1.5
MIN_WARRANT_TURNOVER = 20_000_000


def export_json(out_dir: Path | None = None) -> dict:
    out = Path(out_dir) if out_dir else DEFAULT_OUT
    out.mkdir(parents=True, exist_ok=True)
    init_db()
    engine = get_engine()
    with engine.connect() as conn:
        dates = [r[0] for r in conn.execute(text(
            "SELECT DISTINCT date FROM daily_prices ORDER BY date DESC LIMIT 22"))]
        if not dates:
            raise RuntimeError("no data in daily_prices; run import-daily first")
        d = dates[0]
        prev = dates[1] if len(dates) > 1 else None
        base20 = dates[1:21]                       # 前 20 個交易日(不含今日)

        rows = conn.execute(text("""
            SELECT p.stock_id, s.name, s.market, s.industry, p.close, p.turnover,
                   p.volume, p.transactions, pp.close AS prev_close,
                   i.foreign_net, i.trust_net, m.margin_balance, m.margin_prev,
                   a.avg_vol20,
                   w.call_turnover, w.call_volume, w.call_count,
                   w.put_turnover, w.put_volume, w.put_count,
                   wa.avg_call_turnover,
                   ti.tech_score, ti.ma20, ti.ma60, ti.rsi14, ti.volume_ratio AS tech_volume_ratio,
                   ti.reasons AS tech_reasons, ti.risks AS tech_risks,
                   ds.final AS score_final, ds.branch_score, ds.warrant_score, ds.inst_score, ds.theme_score,
                   ds.risk_penalty, ds.reasons AS score_reasons, ds.risks AS score_risks
            FROM daily_prices p
            JOIN stocks s ON s.id = p.stock_id AND s.type = 'stock'
            LEFT JOIN daily_prices pp ON pp.stock_id = p.stock_id AND pp.date = :prev
            LEFT JOIN daily_institutional i ON i.stock_id = p.stock_id AND i.date = :d
            LEFT JOIN daily_margins m ON m.stock_id = p.stock_id AND m.date = :d
            LEFT JOIN warrant_stock_daily w ON w.stock_id = p.stock_id AND w.date = :d
            LEFT JOIN indicators_daily ti ON ti.stock_id = p.stock_id AND ti.date = :d
            LEFT JOIN daily_scores ds ON ds.stock_id = p.stock_id AND ds.date = :d
            LEFT JOIN (
                SELECT stock_id, AVG(volume) AS avg_vol20 FROM daily_prices
                WHERE date >= :d20 AND date < :d GROUP BY stock_id
            ) a ON a.stock_id = p.stock_id
            LEFT JOIN (
                SELECT stock_id, AVG(call_turnover) AS avg_call_turnover
                FROM warrant_stock_daily
                WHERE date >= :d20 AND date < :d
                GROUP BY stock_id
            ) wa ON wa.stock_id = p.stock_id
            WHERE p.date = :d AND p.close IS NOT NULL
        """), {"d": d, "prev": prev, "d20": base20[-1] if base20 else d}).fetchall()

        all_stocks = []
        for r in rows:
            (sid, name, market, industry, close, turnover, volume, tx,
             prev_close, f_net, t_net, mb, mp, avg_vol20,
             call_turnover, call_volume, call_count,
             put_turnover, put_volume, put_count, avg_call_turnover,
             tech_score, tech_ma20, tech_ma60, tech_rsi14, tech_volume_ratio,
             tech_reasons, tech_risks,
              score_final, branch_score, warrant_score, inst_score, theme_score,
              risk_penalty, score_reasons, score_risks) = r
            chg_pct = round((close - prev_close) / prev_close * 100, 2) if prev_close else None
            vol_ratio = None
            if avg_vol20 and avg_vol20 > 0 and volume:
                vol_ratio = round(volume / avg_vol20, 2)
            warrant = None
            if call_turnover is not None or put_turnover is not None:
                call_turnover = call_turnover or 0
                put_turnover = put_turnover or 0
                ratio = None
                if avg_call_turnover and avg_call_turnover > 0:
                    ratio = round(call_turnover / avg_call_turnover, 2)
                warrant = {
                    "call_turnover": call_turnover,
                    "call_volume": call_volume or 0,
                    "call_count": call_count or 0,
                    "put_turnover": put_turnover,
                    "put_volume": put_volume or 0,
                    "put_count": put_count or 0,
                    "call_avg20": round(avg_call_turnover) if avg_call_turnover is not None else None,
                    "call_turnover_ratio": ratio,
                    "put_call_ratio": round(put_turnover / call_turnover, 2) if call_turnover > 0 else None,
                }
            technical = None
            if tech_score is not None:
                technical = {
                    "score": tech_score,
                    "ma20": tech_ma20,
                    "ma60": tech_ma60,
                    "rsi14": tech_rsi14,
                    "volume_ratio": tech_volume_ratio,
                    "reasons": json.loads(tech_reasons or "[]"),
                    "risks": json.loads(tech_risks or "[]"),
                }
            all_stocks.append({
                "id": sid, "name": name, "market": market, "industry": industry,
                "close": close, "chg_pct": chg_pct,
                "turnover": turnover, "volume_lots": (volume or 0) // 1000,
                "volume_ratio": vol_ratio, "transactions": tx,
                "foreign_net_lots": None if f_net is None else f_net // 1000,
                "trust_net_lots": None if t_net is None else t_net // 1000,
                "margin_chg_lots": None if (mb is None or mp is None) else mb - mp,
                "warrant": warrant,
                "technical": technical,
                "scores": None if score_final is None else {
                    "final": score_final,
                    "branch": branch_score,
                    "warrant": warrant_score,
                    "tech": tech_score,
                    "inst": inst_score,
                    "theme": theme_score,
                    "risk_penalty": risk_penalty,
                },
                "reasons": [x["text"] for x in json.loads(score_reasons or "[]")[:4]],
                "risks": [x["text"] for x in json.loads(score_risks or "[]")[:3]],
            })

        # ── 榜單(動態,依今日行情) ──
        score = sorted(
            [s for s in all_stocks if s["scores"] and s["scores"]["final"] >= 65],
            key=lambda s: (s["scores"]["final"], s["turnover"] or 0), reverse=True)
        hot = sorted(
            [s for s in all_stocks if (s["turnover"] or 0) >= 1_000_000_000],
            key=lambda s: s["turnover"] or 0, reverse=True)
        surge = sorted(
            [s for s in all_stocks
             if (s["turnover"] or 0) >= MIN_TURNOVER
             and (s["volume_ratio"] or 0) >= SURGE_MIN_RATIO],
            key=lambda s: s["volume_ratio"], reverse=True)
        strong = sorted(
            [s for s in all_stocks
             if (s["turnover"] or 0) >= MIN_TURNOVER and (s["chg_pct"] or 0) >= 5.0],
            key=lambda s: s["chg_pct"], reverse=True)
        warrant = sorted(
            [s for s in all_stocks
             if s["warrant"] and s["warrant"]["call_turnover"] >= MIN_WARRANT_TURNOVER
             and (s["warrant"]["call_turnover_ratio"] or 0) >= 1.5],
            key=lambda s: (
                s["warrant"]["call_turnover_ratio"] or 0,
                s["warrant"]["call_turnover"],
            ),
            reverse=True,
        )

        union: dict[str, dict] = {}
        for s in score + hot + surge + strong + warrant:
            union[s["id"]] = s
        for s in union.values():
            s["spark"] = [row[0] for row in conn.execute(text(
                "SELECT close FROM (SELECT close, date FROM daily_prices "
                "WHERE stock_id = :s AND close IS NOT NULL AND date <= :d "
                "ORDER BY date DESC LIMIT 30) ORDER BY date"), {"s": s["id"], "d": d})]

        # ── 族群資金流(官方產業別;題材標籤之後人工維護再加) ──
        sector_today: dict[str, dict] = {}
        for s in all_stocks:
            ind = s["industry"]
            if not ind:
                continue
            g = sector_today.setdefault(ind, {"turnover": 0, "up": 0, "down": 0,
                                              "chgs": [], "stocks": []})
            g["turnover"] += s["turnover"] or 0
            if s["chg_pct"] is not None:
                g["chgs"].append(s["chg_pct"])
                if s["chg_pct"] > 0:
                    g["up"] += 1
                elif s["chg_pct"] < 0:
                    g["down"] += 1
            g["stocks"].append(s)

        prior = {r[0]: r[1] for r in conn.execute(text("""
            SELECT s.industry, SUM(p.turnover) * 1.0 / COUNT(DISTINCT p.date)
            FROM daily_prices p
            JOIN stocks s ON s.id = p.stock_id AND s.type = 'stock'
            WHERE p.date >= :d20 AND p.date < :d AND s.industry IS NOT NULL
            GROUP BY s.industry
        """), {"d": d, "d20": base20[-1] if base20 else d})}

        total_today = sum(g["turnover"] for g in sector_today.values()) or 1

        def group_payload(name, g, prior_avg):
            top = sorted(g["stocks"], key=lambda s: s["turnover"] or 0, reverse=True)[:8]
            return {
                "name": name,
                "turnover": g["turnover"],
                "share": round(g["turnover"] / total_today * 100, 1),
                "vs20": round(g["turnover"] / prior_avg, 2) if prior_avg else None,
                "avg_chg": round(sum(g["chgs"]) / len(g["chgs"]), 2) if g["chgs"] else None,
                "up": g["up"], "down": g["down"],
                "top": [{"id": s["id"], "name": s["name"], "chg_pct": s["chg_pct"],
                         "turnover": s["turnover"]} for s in top],
            }

        sectors = [group_payload(ind, g, prior.get(ind)) for ind, g in sector_today.items()]
        sectors.sort(key=lambda x: x["turnover"], reverse=True)

        # ── 題材/概念股資金流(富邦概念股分類;成分重疊,share 僅供相對比較) ──
        by_id = {s["id"]: s for s in all_stocks}
        theme_groups: dict[str, dict] = {}
        for name, sid in conn.execute(text(
                "SELECT t.name, st.stock_id FROM stock_themes st "
                "JOIN themes t ON t.id = st.theme_id")):
            s = by_id.get(sid)
            if s is None:
                continue
            g = theme_groups.setdefault(name, {"turnover": 0, "up": 0, "down": 0,
                                               "chgs": [], "stocks": []})
            g["turnover"] += s["turnover"] or 0
            if s["chg_pct"] is not None:
                g["chgs"].append(s["chg_pct"])
                if s["chg_pct"] > 0:
                    g["up"] += 1
                elif s["chg_pct"] < 0:
                    g["down"] += 1
            g["stocks"].append(s)
        theme_prior = {r[0]: r[1] for r in conn.execute(text("""
            SELECT t.name, SUM(p.turnover) * 1.0 / COUNT(DISTINCT p.date)
            FROM daily_prices p
            JOIN stock_themes st ON st.stock_id = p.stock_id
            JOIN themes t ON t.id = st.theme_id
            WHERE p.date >= :d20 AND p.date < :d
            GROUP BY t.name
        """), {"d": d, "d20": base20[-1] if base20 else d})}
        themes = [group_payload(name, g, theme_prior.get(name))
                  for name, g in theme_groups.items()
                  if len(g["stocks"]) >= 3 and g["turnover"] >= 5e8]
        themes.sort(key=lambda x: x["turnover"], reverse=True)

        summary = conn.execute(text("""
            SELECT s.market,
                   SUM(p.turnover),
                   SUM(CASE WHEN pp.close IS NOT NULL AND p.close > pp.close THEN 1 ELSE 0 END),
                   SUM(CASE WHEN pp.close IS NOT NULL AND p.close < pp.close THEN 1 ELSE 0 END)
            FROM daily_prices p
            JOIN stocks s ON s.id = p.stock_id AND s.type = 'stock'
            LEFT JOIN daily_prices pp ON pp.stock_id = p.stock_id AND pp.date = :prev
            WHERE p.date = :d AND p.close IS NOT NULL
            GROUP BY s.market
        """), {"d": d, "prev": prev}).fetchall()

        logs = conn.execute(text("""
            SELECT source, dataset, date, rows, status, MAX(run_at)
            FROM import_logs WHERE dataset IN ('quotes','insti','margin')
            GROUP BY source, dataset, date ORDER BY date DESC, source, dataset LIMIT 12
        """)).fetchall()

    now = datetime.now(ZoneInfo(config.TZ)).isoformat(timespec="seconds")
    radar = {
        "data_date": d,
        "generated_at": now,
        "note": "綜合分=分點/權證/技術/法人/題材加權−風險扣分;≥65 為觀察門檻",
        "summary": [
            {"market": m, "turnover": t, "up": up, "down": down}
            for m, t, up, down in summary
        ],
        "sectors": sectors[:16],
        "themes": themes[:36],
        "lists": {
            "score": [s["id"] for s in score],
            "hot": [s["id"] for s in hot],
            "surge": [s["id"] for s in surge],
            "strong": [s["id"] for s in strong],
            "warrant": [s["id"] for s in warrant],
        },
        "stocks": list(union.values()),
    }
    meta = {
        "generated_at": now,
        "datasets": [
            {"source": s, "dataset": ds, "date": dt, "rows": rw, "status": st, "run_at": ra}
            for s, ds, dt, rw, st, ra in logs
        ],
    }
    (out / "radar.json").write_text(json.dumps(radar, ensure_ascii=False), encoding="utf-8")
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    # 全市場搜尋索引(id/名稱/市場/產業;compact 陣列省體積)
    with engine.connect() as conn:
        idx = [[r[0], r[1], r[2], r[3] or ""] for r in conn.execute(text(
            "SELECT id, name, market, industry FROM stocks "
            "WHERE type IN ('stock','etf') AND is_active = 1 ORDER BY id"))]
    (out / "stocks_index.json").write_text(
        json.dumps(idx, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # 個股 K 線 JSON:榜單聯集=全歷史;其餘評分池=近 600 根(控部署體積)
    stock_dir = out / "stocks"
    stock_dir.mkdir(exist_ok=True)
    by_id_all = {s["id"]: s for s in all_stocks}
    with engine.connect() as conn:
        pool_ids = [r[0] for r in conn.execute(text(
            "SELECT stock_id FROM daily_scores WHERE date = :d"), {"d": d})]
        # 權證分點(當日,權證代號=6碼)→ {權證id: 前8大進出}
        wb: dict[str, list] = {}
        for r in conn.execute(text(
            "SELECT stock_id, branch_name, buy_lots, sell_lots, net_lots "
            "FROM branch_trades WHERE date = :d AND LENGTH(stock_id) = 6"), {"d": d}):
            wb.setdefault(r[0], []).append(
                {"name": r[1], "buy": r[2], "sell": r[3], "net": r[4]})
        for rows_list in wb.values():
            rows_list.sort(key=lambda x: -abs(x["net"] or 0))
            del rows_list[8:]

        export_ids = list(dict.fromkeys(list(union.keys()) + pool_ids))
        for sid in export_ids:
            s = by_id_all.get(sid)
            if s is None:
                continue
            if sid in union:
                candles = conn.execute(text(
                    "SELECT p.date, p.open, p.high, p.low, p.close, p.volume, p.turnover, p.adj_factor "
                    "FROM daily_prices p WHERE p.stock_id = :s AND p.close IS NOT NULL "
                    "ORDER BY p.date"), {"s": sid}).fetchall()
            else:
                candles = list(reversed(conn.execute(text(
                    "SELECT p.date, p.open, p.high, p.low, p.close, p.volume, p.turnover, p.adj_factor "
                    "FROM daily_prices p WHERE p.stock_id = :s AND p.close IS NOT NULL "
                    "ORDER BY p.date DESC LIMIT 600"), {"s": sid}).fetchall()))
            warrant_history = conn.execute(text("""
                SELECT date, call_turnover, put_turnover, call_count, put_count
                FROM warrant_stock_daily
                WHERE stock_id = :s
                ORDER BY date DESC LIMIT 60
            """), {"s": sid}).fetchall()
            active_warrants = conn.execute(text("""
                SELECT w.id, w.name, w.kind, w.strike, w.exercise_ratio, w.maturity_date,
                       d.close, d.volume, d.turnover
                FROM warrant_daily d
                JOIN warrants w ON w.id = d.warrant_id
                WHERE w.stock_id = :s
                  AND d.date = :d
                  AND w.kind IN ('call', 'put')
                  AND d.turnover > 0
                ORDER BY d.turnover DESC
                LIMIT 12
            """), {"s": sid, "d": d}).fetchall()
            stock_branches = conn.execute(text("""
                SELECT branch_name, buy_lots, sell_lots, net_lots, pct
                FROM branch_trades
                WHERE stock_id = :s AND date = :d
                ORDER BY net_lots DESC
            """), {"s": sid, "d": d}).fetchall()
            
            branch_history_rows = conn.execute(text("""
                SELECT date, branch_name, buy_lots, sell_lots, net_lots
                FROM branch_trades
                WHERE stock_id = :s AND date >= date(:d, '-365 days')
                ORDER BY date DESC
            """), {"s": sid, "d": d}).fetchall()
            history_by_date: dict[str, list] = {}
            for r in branch_history_rows:
                history_by_date.setdefault(r[0], []).append({
                    "n": r[1], "b": r[2] or 0, "s": r[3] or 0, "net": r[4] or 0
                })
            branch_history = [
                {"t": dt, "branches": sorted(branches, key=lambda x: -abs(x["net"]))}
                for dt, branches in sorted(history_by_date.items(), reverse=True)[:240]
            ]
            payload = {
                "id": sid, "name": s["name"], "market": s["market"],
                "candles": [
                    {"t": c[0], "o": c[1], "h": c[2], "l": c[3], "c": c[4],
                     "v": (c[5] or 0) // 1000, "amt": c[6], "af": c[7] or 1.0}
                    for c in candles
                ],
                "technical": s["technical"],
                "scores": s["scores"],
                "reasons": s.get("reasons", []),
                "risks": s.get("risks", []),
                "branches": [
                    {"name": r[0], "buy": r[1] or 0, "sell": r[2] or 0,
                     "net": r[3] or 0, "pct": r[4]}
                    for r in stock_branches
                ],
                "branch_history": branch_history,
                "warrant": s["warrant"],
                "warrant_history": [
                    {"t": r[0], "call_turnover": r[1] or 0, "put_turnover": r[2] or 0,
                     "call_count": r[3] or 0, "put_count": r[4] or 0}
                    for r in reversed(warrant_history)
                ],
                "active_warrants": [
                    {"id": r[0], "name": r[1], "kind": r[2], "strike": r[3],
                     "exercise_ratio": r[4], "maturity_date": r[5], "close": r[6],
                     "volume_lots": (r[7] or 0) // 1000, "turnover": r[8] or 0,
                     "branches": wb.get(r[0], [])}
                    for r in active_warrants
                ],
            }
            (stock_dir / f"{sid}.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return {"out": str(out), "date": d, "stocks": len(export_ids)}
