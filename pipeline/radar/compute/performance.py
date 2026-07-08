"""Forward-return backfill for frozen daily_scores rows.

docs/04 §12 defines the honest V2 record: signals are generated after close,
entry is the next trading day's open, and forward returns are filled later.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text

from .. import config, schema
from ..db import get_engine, init_db

HORIZONS = (1, 3, 5, 10, 20)


def _norm_date(date: str | None) -> str | None:
    if not date:
        return None
    return f"{date[:4]}-{date[4:6]}-{date[6:8]}" if len(date) == 8 else date


def forward_returns(candles: list[dict], signal_date: str) -> dict | None:
    """Compute forward returns from the first candle after signal_date.

    candles must be sorted ascending and carry adjusted open/close prices. fwd_1d
    means the entry day's close vs the entry open; fwd_3d means the third trading
    day's close vs the same entry open.
    """
    entry_idx = next(
        (i for i, c in enumerate(candles)
         if c["date"] > signal_date and c.get("open") and c["open"] > 0),
        None,
    )
    if entry_idx is None:
        return None

    entry = candles[entry_idx]
    entry_price = entry["open"]
    out = {
        "entry_date": entry["date"],
        "entry_price": round(entry_price, 4),
    }
    for horizon in HORIZONS:
        target_idx = entry_idx + horizon - 1
        close = candles[target_idx]["close"] if target_idx < len(candles) else None
        out[f"fwd_{horizon}d"] = (
            round((close / entry_price - 1) * 100, 2)
            if close is not None and entry_price > 0
            else None
        )
    return out


def compute_performance(date: str | None = None, all_scores: bool = False) -> dict:
    """Backfill daily_scores entry/fwd return columns.

    Default mode updates rows that are still missing their 20-day forward return.
    Use date to force a single signal date, or all_scores to refresh every row.
    """
    init_db()
    engine = get_engine()
    d = _norm_date(date)
    now = datetime.now(ZoneInfo(config.TZ)).isoformat(timespec="seconds")

    with engine.connect() as conn:
        latest_price_date = conn.execute(text(
            "SELECT MAX(date) FROM daily_prices WHERE close IS NOT NULL"
        )).scalar()
        if not latest_price_date:
            raise RuntimeError("no price data")

        if d:
            candidates = conn.execute(text(
                "SELECT stock_id, date FROM daily_scores "
                "WHERE date = :d ORDER BY stock_id"
            ), {"d": d}).fetchall()
        elif all_scores:
            candidates = conn.execute(text(
                "SELECT stock_id, date FROM daily_scores ORDER BY date, stock_id"
            )).fetchall()
        else:
            candidates = conn.execute(text(
                "SELECT stock_id, date FROM daily_scores "
                "WHERE date < :latest AND (entry_price IS NULL OR fwd_20d IS NULL) "
                "ORDER BY date, stock_id"
            ), {"latest": latest_price_date}).fetchall()

        by_stock: dict[str, list[str]] = {}
        for sid, score_date in candidates:
            by_stock.setdefault(sid, []).append(score_date)

        updates = []
        for sid, score_dates in by_stock.items():
            min_date = min(score_dates)
            rows = conn.execute(text(
                "SELECT date, open * COALESCE(adj_factor, 1.0), "
                "       close * COALESCE(adj_factor, 1.0) "
                "FROM daily_prices "
                "WHERE stock_id = :sid AND date > :min_date "
                "  AND open IS NOT NULL AND close IS NOT NULL "
                "ORDER BY date"
            ), {"sid": sid, "min_date": min_date}).fetchall()
            candles = [{"date": r[0], "open": r[1], "close": r[2]} for r in rows]
            for score_date in score_dates:
                perf = forward_returns(candles, score_date)
                if perf is None:
                    continue
                updates.append({
                    "stock_id": sid,
                    "date": score_date,
                    "updated_at": now,
                    **perf,
                })

    with engine.begin() as conn:
        for u in updates:
            conn.execute(text("""
                UPDATE daily_scores
                SET entry_date = :entry_date,
                    entry_price = :entry_price,
                    fwd_1d = :fwd_1d,
                    fwd_3d = :fwd_3d,
                    fwd_5d = :fwd_5d,
                    fwd_10d = :fwd_10d,
                    fwd_20d = :fwd_20d,
                    fwd_updated_at = :updated_at
                WHERE stock_id = :stock_id AND date = :date
            """), u)
        conn.execute(schema.import_logs.insert().values(
            run_at=now,
            source="compute",
            dataset="performance",
            date=d or latest_price_date,
            rows=len(updates),
            status="ok",
        ))

    complete = sum(1 for u in updates if u["fwd_20d"] is not None)
    return {
        "date": d or latest_price_date,
        "candidates": len(candidates),
        "updated": len(updates),
        "complete_20d": complete,
    }
