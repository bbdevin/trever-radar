"""Backward-adjustment factors for daily prices."""
from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text

from . import config, schema
from .db import get_engine, init_db
from .importer import _log
from .providers import finmind


def factors_for_dates(dates: list[str], events: list[dict]) -> dict[str, float]:
    """Return cumulative backward adjustment factors keyed by price date.

    Each event applies only to dates before the ex-right/ex-dividend date.
    Example: if 2026-06-12 has before=100 and after=95, then 2026-06-11
    gets multiplied by 0.95, while 2026-06-12 itself remains at 1.0.
    """
    clean_events = []
    for e in events:
        before = e.get("before_price")
        after = e.get("after_price")
        if not e.get("date") or not before or not after or before <= 0 or after <= 0:
            continue
        ratio = after / before
        if ratio <= 0:
            continue
        clean_events.append((e["date"], ratio))
    clean_events.sort(reverse=True)

    out: dict[str, float] = {}
    factor = 1.0
    i = 0
    for d in sorted(dates, reverse=True):
        while i < len(clean_events) and d < clean_events[i][0]:
            factor *= clean_events[i][1]
            i += 1
        out[d] = round(factor, 8)
    return out


def _targets(conn, ids: list[str] | None, top: int | None, all_stocks: bool) -> list[str]:
    if ids:
        return ids
    if top:
        rows = conn.execute(text("""
            SELECT stock_id
            FROM daily_prices
            WHERE date = (SELECT MAX(date) FROM daily_prices)
              AND turnover IS NOT NULL
            ORDER BY turnover DESC
            LIMIT :n
        """), {"n": top}).fetchall()
        return [r[0] for r in rows]
    if all_stocks:
        rows = conn.execute(text("""
            SELECT DISTINCT s.id
            FROM stocks s
            JOIN daily_prices p ON p.stock_id = s.id
            WHERE s.type IN ('stock', 'etf')
            ORDER BY s.id
        """)).fetchall()
        return [r[0] for r in rows]
    raise SystemExit("compute-adjustments needs --ids, --top or --all")


def compute_adjustments(ids: list[str] | None = None, top: int | None = None,
                        all_stocks: bool = False, start_date: str = "1990-01-01",
                        sleep_s: float = 1.0) -> dict:
    """Fetch dividend results and update daily_prices.adj_factor.

    This is idempotent: every run recomputes and overwrites factors for the
    selected stocks from the current dividend result rows.
    """
    init_db()
    engine = get_engine()
    today = datetime.now(ZoneInfo(config.TZ)).strftime("%Y%m%d")
    with engine.connect() as conn:
        targets = _targets(conn, ids, top, all_stocks)

    done = failed = events_seen = rows_updated = 0
    for sid in targets:
        try:
            events = finmind.fetch_dividend_results(sid, start_date)
        except finmind.RateLimitedError as e:
            print(f"quota hit at {sid}: {e} — stopping; re-run later to continue", flush=True)
            break
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"adjust {sid} FAILED: {str(e)[:120]}", flush=True)
            continue

        with engine.begin() as conn:
            dates = [r[0] for r in conn.execute(text(
                "SELECT date FROM daily_prices WHERE stock_id = :sid ORDER BY date"
            ), {"sid": sid}).fetchall()]
            if not dates:
                continue
            factors = factors_for_dates(dates, events)
            for d, factor in factors.items():
                r = conn.execute(text("""
                    UPDATE daily_prices
                    SET adj_factor = :factor
                    WHERE stock_id = :sid AND date = :d
                """), {"sid": sid, "d": d, "factor": factor})
                rows_updated += r.rowcount
            _log(conn, "finmind", "adj_factor", today, len(events), "ok")

        done += 1
        events_seen += len(events)
        print(f"adjust {sid} ok: {len(events)} events, {len(factors)} price rows", flush=True)
        if sleep_s > 0:
            time.sleep(sleep_s)

    return {"done": done, "failed": failed, "events": events_seen, "rows": rows_updated}
