"""Export frontend JSON files from SQLite.

Until the scoring module exists, radar.json lists top-30 stocks by turnover
(real prices/insti/margin data, scores=null) so the UI can render live data.
"""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import text

from .. import config
from ..db import get_engine

DEFAULT_OUT = config.ROOT / "web" / "public" / "data"


def _latest_dates(conn) -> list[str]:
    rows = conn.execute(text(
        "SELECT DISTINCT date FROM daily_prices ORDER BY date DESC LIMIT 2")).fetchall()
    return [r[0] for r in rows]


def export_json(out_dir: Path | None = None) -> dict:
    out = Path(out_dir) if out_dir else DEFAULT_OUT
    out.mkdir(parents=True, exist_ok=True)
    engine = get_engine()
    with engine.connect() as conn:
        dates = _latest_dates(conn)
        if not dates:
            raise RuntimeError("no data in daily_prices; run import-daily first")
        d = dates[0]
        prev = dates[1] if len(dates) > 1 else None

        items = conn.execute(text("""
            SELECT p.stock_id, s.name, s.market, p.close, p.turnover, p.volume,
                   p.transactions, pp.close AS prev_close,
                   i.foreign_net, i.trust_net,
                   m.margin_balance, m.margin_prev
            FROM daily_prices p
            JOIN stocks s ON s.id = p.stock_id AND s.type = 'stock'
            LEFT JOIN daily_prices pp ON pp.stock_id = p.stock_id AND pp.date = :prev
            LEFT JOIN daily_institutional i ON i.stock_id = p.stock_id AND i.date = :d
            LEFT JOIN daily_margins m ON m.stock_id = p.stock_id AND m.date = :d
            WHERE p.date = :d AND p.close IS NOT NULL
            ORDER BY p.turnover DESC LIMIT 30
        """), {"d": d, "prev": prev}).fetchall()

        stocks = []
        for r in items:
            (sid, name, market, close, turnover, volume, tx,
             prev_close, f_net, t_net, mb, mp) = r
            chg_pct = None
            if prev_close:
                chg_pct = round((close - prev_close) / prev_close * 100, 2)
            stocks.append({
                "id": sid, "name": name, "market": market,
                "close": close, "chg_pct": chg_pct,
                "turnover": turnover, "volume_lots": (volume or 0) // 1000,
                "transactions": tx,
                "foreign_net_lots": None if f_net is None else f_net // 1000,
                "trust_net_lots": None if t_net is None else t_net // 1000,
                "margin_chg_lots": None if (mb is None or mp is None) else mb - mp,
                "scores": None,          # scoring module not built yet
                "reasons": [], "risks": [],
            })

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
            FROM import_logs GROUP BY source, dataset, date
            ORDER BY date DESC, source, dataset LIMIT 12
        """)).fetchall()

    now = datetime.now(ZoneInfo(config.TZ)).isoformat(timespec="seconds")
    radar = {
        "data_date": d,
        "generated_at": now,
        "note": "評分模組建置中,暫以成交金額排序顯示",
        "summary": [
            {"market": m, "turnover": t, "up": up, "down": down}
            for m, t, up, down in summary
        ],
        "stocks": stocks,
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
    return {"out": str(out), "date": d, "stocks": len(stocks)}
