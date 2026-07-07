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

HOT_N = 15
SURGE_N = 15
STRONG_N = 15
WARRANT_N = 15
MIN_TURNOVER = 1e8          # 榜單門檻:成交金額 1 億
SURGE_MIN_RATIO = 1.5
MIN_WARRANT_TURNOVER = 1_000_000


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
                   wa.avg_call_turnover
            FROM daily_prices p
            JOIN stocks s ON s.id = p.stock_id AND s.type = 'stock'
            LEFT JOIN daily_prices pp ON pp.stock_id = p.stock_id AND pp.date = :prev
            LEFT JOIN daily_institutional i ON i.stock_id = p.stock_id AND i.date = :d
            LEFT JOIN daily_margins m ON m.stock_id = p.stock_id AND m.date = :d
            LEFT JOIN warrant_stock_daily w ON w.stock_id = p.stock_id AND w.date = :d
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
             put_turnover, put_volume, put_count, avg_call_turnover) = r
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
            all_stocks.append({
                "id": sid, "name": name, "market": market, "industry": industry,
                "close": close, "chg_pct": chg_pct,
                "turnover": turnover, "volume_lots": (volume or 0) // 1000,
                "volume_ratio": vol_ratio, "transactions": tx,
                "foreign_net_lots": None if f_net is None else f_net // 1000,
                "trust_net_lots": None if t_net is None else t_net // 1000,
                "margin_chg_lots": None if (mb is None or mp is None) else mb - mp,
                "warrant": warrant,
                "scores": None, "reasons": [], "risks": [],
            })

        # ── 三榜(動態,依今日行情) ──
        hot = sorted(all_stocks, key=lambda s: s["turnover"] or 0, reverse=True)[:HOT_N]
        surge = sorted(
            [s for s in all_stocks
             if (s["turnover"] or 0) >= MIN_TURNOVER
             and (s["volume_ratio"] or 0) >= SURGE_MIN_RATIO],
            key=lambda s: s["volume_ratio"], reverse=True)[:SURGE_N]
        strong = sorted(
            [s for s in all_stocks
             if (s["turnover"] or 0) >= MIN_TURNOVER and (s["chg_pct"] or 0) > 0],
            key=lambda s: s["chg_pct"], reverse=True)[:STRONG_N]
        warrant = sorted(
            [s for s in all_stocks
             if s["warrant"] and s["warrant"]["call_turnover"] >= MIN_WARRANT_TURNOVER],
            key=lambda s: (
                s["warrant"]["call_turnover_ratio"] or 0,
                s["warrant"]["call_turnover"],
            ),
            reverse=True,
        )[:WARRANT_N]

        union: dict[str, dict] = {}
        for s in hot + surge + strong + warrant:
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
        sectors = []
        for ind, g in sector_today.items():
            top = sorted(g["stocks"], key=lambda s: s["turnover"] or 0, reverse=True)[:3]
            sectors.append({
                "name": ind,
                "turnover": g["turnover"],
                "share": round(g["turnover"] / total_today * 100, 1),
                "vs20": round(g["turnover"] / prior[ind], 2) if prior.get(ind) else None,
                "avg_chg": round(sum(g["chgs"]) / len(g["chgs"]), 2) if g["chgs"] else None,
                "up": g["up"], "down": g["down"],
                "top": [{"id": s["id"], "name": s["name"], "chg_pct": s["chg_pct"]} for s in top],
            })
        sectors.sort(key=lambda x: x["turnover"], reverse=True)

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
        "note": "評分模組建置中;三榜為當日行情動態排序",
        "summary": [
            {"market": m, "turnover": t, "up": up, "down": down}
            for m, t, up, down in summary
        ],
        "sectors": sectors[:12],
        "lists": {
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

    # 個股 K 線 JSON(榜單聯集)
    stock_dir = out / "stocks"
    stock_dir.mkdir(exist_ok=True)
    with engine.connect() as conn:
        for s in union.values():
            candles = conn.execute(text(
                "SELECT date, open, high, low, close, volume, turnover, adj_factor FROM daily_prices "
                "WHERE stock_id = :s AND close IS NOT NULL ORDER BY date"), {"s": s["id"]}).fetchall()
            warrant_history = conn.execute(text("""
                SELECT date, call_turnover, put_turnover, call_count, put_count
                FROM warrant_stock_daily
                WHERE stock_id = :s
                ORDER BY date DESC LIMIT 60
            """), {"s": s["id"]}).fetchall()
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
            """), {"s": s["id"], "d": d}).fetchall()
            payload = {
                "id": s["id"], "name": s["name"], "market": s["market"],
                "candles": [
                    {"t": c[0], "o": c[1], "h": c[2], "l": c[3], "c": c[4],
                     "v": (c[5] or 0) // 1000, "amt": c[6], "af": c[7] or 1.0}
                    for c in candles
                ],
                "warrant": s["warrant"],
                "warrant_history": [
                    {"t": r[0], "call_turnover": r[1] or 0, "put_turnover": r[2] or 0,
                     "call_count": r[3] or 0, "put_count": r[4] or 0}
                    for r in reversed(warrant_history)
                ],
                "active_warrants": [
                    {"id": r[0], "name": r[1], "kind": r[2], "strike": r[3],
                     "exercise_ratio": r[4], "maturity_date": r[5], "close": r[6],
                     "volume_lots": (r[7] or 0) // 1000, "turnover": r[8] or 0}
                    for r in active_warrants
                ],
            }
            (stock_dir / f"{s['id']}.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return {"out": str(out), "date": d, "stocks": len(union)}
