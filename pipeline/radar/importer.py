"""Daily import orchestration: fetch → DTO → upsert, with import_logs bookkeeping."""
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config, schema
from .classify import classify, warrant_kind
from .db import get_engine, init_db, upsert
from .providers import NoDataError, tpex, twse


def iso(date: str) -> str:
    return f"{date[:4]}-{date[4:6]}-{date[6:8]}"


def _log(conn, source, dataset, date, rows, status, error=None, duration_ms=None):
    conn.execute(schema.import_logs.insert().values(
        run_at=datetime.now(ZoneInfo(config.TZ)).isoformat(timespec="seconds"),
        source=source, dataset=dataset, date=iso(date),
        rows=rows, status=status, error=error, duration_ms=duration_ms,
    ))


def _run(source: str, dataset: str, date: str, fn) -> dict:
    """Run one import step in its own transaction; log outcome; never raise."""
    engine = get_engine()
    t0 = time.monotonic()
    try:
        with engine.begin() as conn:
            rows = fn(conn)
            _log(conn, source, dataset, date, rows, "ok",
                 duration_ms=int((time.monotonic() - t0) * 1000))
            return {"source": source, "dataset": dataset, "rows": rows, "status": "ok"}
    except NoDataError as e:
        with engine.begin() as conn:
            _log(conn, source, dataset, date, 0, "empty", error=str(e)[:500])
        return {"source": source, "dataset": dataset, "rows": 0, "status": "empty"}
    except Exception as e:  # noqa: BLE001 - one failed dataset must not kill the run
        with engine.begin() as conn:
            _log(conn, source, dataset, date, 0, "error", error=str(e)[:500])
        return {"source": source, "dataset": dataset, "rows": 0, "status": "error", "error": str(e)}


def _import_quotes(conn, quotes, date: str) -> int:
    d = iso(date)
    stock_rows, price_rows, warrant_rows, wd_rows = [], [], [], []
    for q in quotes:
        kind = classify(q.code)
        if kind == "warrant":
            warrant_rows.append({"id": q.code, "name": q.name, "market": q.market,
                                 "kind": warrant_kind(q.code)})
            wd_rows.append({"warrant_id": q.code, "date": d, "close": q.close,
                            "volume": q.volume, "turnover": q.turnover,
                            "transactions": q.transactions})
        else:
            stock_rows.append({"id": q.code, "name": q.name, "market": q.market,
                               "type": kind, "is_active": 1})
            price_rows.append({"stock_id": q.code, "date": d, "open": q.open, "high": q.high,
                               "low": q.low, "close": q.close, "volume": q.volume,
                               "turnover": q.turnover, "transactions": q.transactions})
    # warrants master: keep existing stock_id/strike/… → insert-only via do_nothing-style upsert
    upsert_warrant_master(conn, warrant_rows)
    upsert(conn, schema.stocks, stock_rows)
    n = upsert(conn, schema.daily_prices, price_rows)
    n += upsert(conn, schema.warrant_daily, wd_rows)
    return n


def upsert_warrant_master(conn, rows):
    """Insert new warrants; update only name (master fields come from a separate import)."""
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    if not rows:
        return
    for i in range(0, len(rows), 800):
        stmt = sqlite_insert(schema.warrants).values(rows[i : i + 800])
        stmt = stmt.on_conflict_do_update(index_elements=["id"], set_={"name": stmt.excluded.name})
        conn.execute(stmt)


def _import_insti(conn, rows, date: str) -> int:
    d = iso(date)
    out = [{"stock_id": r.code, "date": d, "foreign_net": r.foreign_net,
            "trust_net": r.trust_net, "dealer_net": r.dealer_net, "total_net": r.total_net}
           for r in rows if classify(r.code) in ("stock", "etf")]
    return upsert(conn, schema.daily_institutional, out)


def _import_margin(conn, rows, date: str) -> int:
    d = iso(date)
    out = [{"stock_id": r.code, "date": d, "margin_balance": r.margin_balance,
            "margin_prev": r.margin_prev, "margin_limit": r.margin_limit,
            "short_balance": r.short_balance, "short_prev": r.short_prev}
           for r in rows if classify(r.code) in ("stock", "etf")]
    return upsert(conn, schema.daily_margins, out)


def import_daily(date: str, datasets: list[str] | None = None) -> list[dict]:
    """date: YYYYMMDD. datasets subset of {quotes, insti, margin}; None = all."""
    wanted = set(datasets or ["quotes", "insti", "margin"])
    init_db()
    results = []
    if "quotes" in wanted:
        results.append(_run("twse", "quotes", date,
                            lambda c: _import_quotes(c, twse.fetch_daily_quotes(date), date)))
        results.append(_run("tpex", "quotes", date,
                            lambda c: _import_quotes(c, tpex.fetch_daily_quotes(date), date)))
    if "insti" in wanted:
        results.append(_run("twse", "insti", date,
                            lambda c: _import_insti(c, twse.fetch_institutional(date), date)))
        results.append(_run("tpex", "insti", date,
                            lambda c: _import_insti(c, tpex.fetch_institutional(date), date)))
    if "margin" in wanted:
        results.append(_run("twse", "margin", date,
                            lambda c: _import_margin(c, twse.fetch_margin(date), date)))
        results.append(_run("tpex", "margin", date,
                            lambda c: _import_margin(c, tpex.fetch_margin(date), date)))
    return results
