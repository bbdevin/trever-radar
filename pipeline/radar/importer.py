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


def backfill(days: int, datasets: list[str] | None = None) -> dict:
    """Import the last `days` trading days (skips weekends and already-imported dates).

    Runs oldest-last (walks backwards from today). Holidays cost one probe each and
    are logged as 'empty'. Safe to interrupt and re-run: already-present dates skip.
    """
    from datetime import date as date_cls, timedelta

    from sqlalchemy import text

    init_db()
    with get_engine().connect() as conn:
        have = {r[0] for r in conn.execute(text("SELECT DISTINCT date FROM daily_prices"))}
    cur = datetime.now(ZoneInfo(config.TZ)).date()
    done = imported = probes = 0
    # scan cap: trading days ≈ 5/7 of calendar days; generous margin for holidays
    for _ in range(days * 2 + 40):
        if done >= days:
            break
        ds = cur.strftime("%Y%m%d")
        if cur.weekday() >= 5:  # Sat/Sun: no request
            cur -= timedelta(days=1)
            continue
        if iso(ds) in have:
            done += 1
            cur -= timedelta(days=1)
            continue
        results = import_daily(ds, datasets or ["quotes"])
        probes += 1
        if any(r["dataset"] == "quotes" and r["status"] == "ok" for r in results):
            done += 1
            imported += 1
            print(f"backfill {iso(ds)} ok ({done}/{days})", flush=True)
        cur -= timedelta(days=1)
    return {"trading_days": done, "imported": imported, "probes": probes}


def deep_backfill(ids: list[str] | None = None, top: int | None = None,
                  all_stocks: bool = False, sleep_s: float = 7.0) -> dict:
    """Since-IPO history via FinMind, one request per stock.

    Selection: explicit ids > --top N by latest turnover > --all (type stock/etf).
    Anonymous quota is low; a free token (RADAR_FINMIND_TOKEN) allows ~600 req/hr.
    On quota exhaustion: stops cleanly; re-run later — already-full stocks are skipped
    via a cheap freshness check (earliest date < 2010 means history already present).
    """
    import time as time_mod

    from sqlalchemy import text

    from .providers import finmind

    init_db()
    engine = get_engine()
    with engine.connect() as conn:
        if ids:
            targets = [(i, None) for i in ids]
        else:
            q = ("SELECT s.id, MIN(p.date) FROM stocks s "
                 "JOIN daily_prices p ON p.stock_id = s.id "
                 "WHERE s.type IN ('stock','etf') GROUP BY s.id")
            rows = conn.execute(text(q)).fetchall()
            if top:
                latest = conn.execute(text(
                    "SELECT stock_id FROM daily_prices WHERE date = "
                    "(SELECT MAX(date) FROM daily_prices) AND turnover IS NOT NULL "
                    "ORDER BY turnover DESC LIMIT :n"), {"n": top}).fetchall()
                wanted = {r[0] for r in latest}
                targets = [(sid, mind) for sid, mind in rows if sid in wanted]
            elif all_stocks:
                targets = list(rows)
            else:
                raise SystemExit("deep-backfill needs --ids, --top or --all")

    done = skipped = failed = 0
    for sid, min_date in targets:
        if min_date and min_date < "2010-01-01":
            skipped += 1     # deep history already present
            continue
        try:
            price_rows = finmind.fetch_daily_history(sid)
        except finmind.RateLimitedError as e:
            print(f"quota hit at {sid}: {e} — stopping; re-run later to continue", flush=True)
            break
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"deep {sid} FAILED: {str(e)[:120]}", flush=True)
            continue
        with engine.begin() as conn:
            n = upsert(conn, schema.daily_prices, price_rows)
            _log(conn, "finmind", "history", price_rows[-1]["date"].replace("-", ""),
                 n, "ok")
        done += 1
        print(f"deep {sid} ok: {len(price_rows)} rows since {price_rows[0]['date']} "
              f"({done} done)", flush=True)
        time_mod.sleep(sleep_s)
    return {"done": done, "skipped": skipped, "failed": failed}


def import_stock_info() -> int:
    """Fill stocks.industry from FinMind TaiwanStockInfo (one request)."""
    from sqlalchemy import text

    from .providers import finmind

    init_db()
    mapping = finmind.fetch_stock_info()
    n = 0
    with get_engine().begin() as conn:
        for sid, ind in mapping.items():
            r = conn.execute(text(
                "UPDATE stocks SET industry = :ind WHERE id = :sid"), {"ind": ind, "sid": sid})
            n += r.rowcount
        _log(conn, "finmind", "stock_info",
             datetime.now(ZoneInfo(config.TZ)).strftime("%Y%m%d"), n, "ok")
    return n


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
