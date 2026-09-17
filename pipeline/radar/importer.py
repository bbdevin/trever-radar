"""Daily import orchestration: fetch → DTO → upsert, with import_logs bookkeeping."""
import hashlib
import json
import math
import os
import tempfile
import time
from datetime import date as date_cls, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config, schema
from .classify import classify, warrant_kind
from .db import get_engine, init_db, upsert
from .http import RadarHTTPError
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
    except RadarHTTPError as e:
        with engine.begin() as conn:
            _log(conn, source, dataset, date, 0, "error", error=str(e)[:500])
        result = {
            "source": source, "dataset": dataset, "rows": 0, "status": "error",
            "error": str(e),
        }
        if e.status_code is None:
            # Connection/timeout failures have no HTTP response; callers must
            # not mistake them for the narrowly recoverable TPEx 520 case.
            result["error_kind"] = "transport"
        else:
            result["error_kind"] = "http"
            result["status_code"] = e.status_code
        return result
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
    out = [{"stock_id": r.code, "date": d,
            "margin_balance": r.margin_balance, "margin_prev": r.margin_prev,
            "margin_limit": r.margin_limit,
            "margin_buy": r.margin_buy, "margin_sell": r.margin_sell,
            "margin_repay": r.margin_repay,
            "short_balance": r.short_balance, "short_prev": r.short_prev,
            "short_buy": r.short_buy, "short_sell": r.short_sell,
            "short_repay": r.short_repay}
           for r in rows if classify(r.code) in ("stock", "etf")]
    return upsert(conn, schema.daily_margins, out)


def backfill_margin(
    days: int = 240,
    sleep_s: float = 0.4,
    dry_run: bool = False,
    min_rows: int = 500,
    *,
    strict_markets: bool = True,
    min_market_fraction: float = 0.5,
) -> dict:
    """Backfill TWSE/TPEx margin for recent trading days with gaps or missing buy fields.

    Unlike ``backfill()``, checks ``daily_margins`` completeness per date instead of
    skipping when ``daily_prices`` already has the day.

    A date is re-imported if *any* of three independent checks trips:
    - ``cnt < min_rows`` — absolute floor. Still needed: on a small/fresh DB
      the market-relative reference below isn't trusted yet (see
      `_MIN_MARKET_SAMPLES`), so this is the only signal available there.
    - market-relative (``strict_markets=True``, default): reuses
      `_market_reference`/`_incomplete_markets` — the same per-market
      per-market reference check `backfill()` uses, just against
      ``daily_margins``. This catches a date where one market silently failed
      while the other logged ok and the *total* still clears `min_rows`.
      Measured production case (2026-09-02): 1,293 rows total (> the 500
      floor) but only because TWSE was near-full while TPEx lost ~980 stocks
      and TWSE lost 83 — a ``margin error rows=0`` at 21:21:20 that night
      shows a run that partially failed; the floor alone could never see it.
    - ``null_buy > cnt * 0.05`` — orthogonal data-quality check, unchanged.

    Pass ``strict_markets=False`` to disable the new check and rely on the
    floor + null_buy checks alone (the pre-fix behaviour).
    """
    import time as time_mod

    from sqlalchemy import text

    init_db()
    with get_engine().connect() as conn:
        trading_days = [
            r[0]
            for r in conn.execute(
                text(
                    "SELECT DISTINCT date FROM daily_prices "
                    "ORDER BY date DESC LIMIT :cap"
                ),
                {"cap": days + 60},
            ).fetchall()
        ]
        # Window for the reference must cover the same span we might repair;
        # trading_days is newest-first, so the oldest entry is the floor.
        window_start = trading_days[-1] if trading_days else "9999-99-99"
        market_counts, reference, samples = (
            _market_reference(conn, "daily_margins", window_start)
            if strict_markets else ({}, {}, {})
        )
    targets = list(reversed(trading_days[:days]))
    unverified = sorted(set(samples) - set(reference))
    if strict_markets:
        print("backfill-margin market reference:", flush=True)
        for line in describe_reference(reference, samples):
            print(line, flush=True)

    imported = skipped = errors = 0
    repaired: list[dict] = []
    for d_iso in targets:
        ds = d_iso.replace("-", "")
        with get_engine().connect() as conn:
            row = conn.execute(
                text(
                    "SELECT COUNT(*), "
                    "SUM(CASE WHEN margin_buy IS NULL THEN 1 ELSE 0 END) "
                    "FROM daily_margins WHERE date = :d"
                ),
                {"d": d_iso},
            ).fetchone()
        cnt = int(row[0] or 0)
        null_buy = int(row[1] or 0)
        missing_markets = (
            _incomplete_markets(d_iso, market_counts, reference, min_market_fraction)
            if strict_markets else []
        )
        need = cnt < min_rows or (cnt > 0 and null_buy > cnt * 0.05) or bool(missing_markets)
        if not need:
            skipped += 1
            continue
        if missing_markets:
            repaired.extend({"date": d_iso, "market": m} for m in missing_markets)
        if dry_run:
            print(
                f"backfill-margin dry-run {d_iso}: rows={cnt} null_buy={null_buy}"
                + (f" incomplete_markets={','.join(missing_markets)}" if missing_markets else ""),
                flush=True,
            )
            imported += 1
            continue
        results = import_daily(ds, ["margin"])
        margin_results = [r for r in results if r.get("dataset") == "margin"]
        ok = any(r["status"] == "ok" for r in margin_results)
        empty = margin_results and all(r["status"] == "empty" for r in margin_results)
        if ok:
            imported += 1
            print(f"backfill-margin {d_iso} ok ({imported} imported)", flush=True)
        elif empty:
            skipped += 1
        else:
            errors += 1
            print(f"backfill-margin {d_iso} error", flush=True)
        time_mod.sleep(sleep_s)

    return {
        "days_target": len(targets),
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "dry_run": dry_run,
        "repaired": repaired,
        "reference": dict(reference),
        "samples": dict(samples),
        "unverified_markets": unverified,
    }


# A market's reference row-count is trusted only once at least this many
# sampled trading days exist for it in the scanned window; below that, the
# market is exempt from the completeness check (see `backfill` docstring).
_MIN_MARKET_SAMPLES = 5

# Quantile of a market's per-date row counts taken as "what it normally
# delivers". High on purpose — see `_market_reference` for why the median is
# the wrong statistic for a shortfall detector.
_REFERENCE_QUANTILE = 0.9


def _market_reference(conn, table, window_start_iso: str) -> tuple[dict, dict]:
    """Per-(date, market) row counts and a per-market reference level, for `table`.

    `table` must be a trusted internal literal (``daily_prices`` or
    ``daily_margins``) — it is interpolated into SQL, never caller/user input.
    Shared by `backfill()` and `backfill_margin()`: both need the identical
    concept ("this date is under-represented for some market relative to what
    that market normally delivers"), just against a different table.

    Returns ``(counts, reference, samples)``. ``samples`` is the number of
    window dates carrying any rows per market, including markets with too few
    to earn a reference — callers need it to tell "checked and clean" apart
    from "could not check", which is the whole point of `describe_reference`.

    Reference = a high quantile (`_REFERENCE_QUANTILE`) of the row count
    across dates in the window that have *any* row for that market.
    Restricting to dates with data means a date with a total outage (0 rows)
    contributes no sample, so a run of total outages can never drag its own
    market's reference down to mask itself. That restriction has a cost: it
    also starves the sample count, and below `_MIN_MARKET_SAMPLES` the market
    is exempted rather than flagged — see `describe_reference` for why that
    has to be said out loud instead of passing silently.

    **Why the upper end of the distribution and not the median.** This is a
    shortfall detector, and the count is bounded above by the size of the
    market's universe — ``daily_prices``/``daily_margins`` are keyed on
    ``(stock_id, date)``, so no date can report more rows than there are
    stocks. There is no "too many rows" failure to be robust against, which
    is the only thing the median would buy. What the median costs is severe:
    it assumes bad days are a minority of the window, and the outage this
    function exists to catch was **25 consecutive trading days**. Worked
    through against the real 2026 data, TPEx at ~985 normal and ~475 during
    the outage: with a 60-day window the split is 35 good / 25 bad and the
    median lands on 985, so the outage is caught; with a 40-day window it is
    16 good / 25 bad, the median lands on **475**, and every bad date is
    silently declared healthy. Whether the bug is detected would depend on
    the caller's ``days`` argument. A high quantile returns 985 in both.

    The quantile is 0.9 rather than the plain max so that one anomalous day
    (a market holiday that still logs a partial session, a one-off duplicate
    universe) cannot single-handedly raise the bar for every other date. With
    the ``_MIN_MARKET_SAMPLES`` floor of 5 samples, 0.9 sits at or next to the
    largest sample, which is the intended reading of "what this market
    normally delivers".
    """
    from sqlalchemy import text

    assert table in ("daily_prices", "daily_margins"), table
    rows = conn.execute(text(
        f"SELECT COALESCE(s.market, '__null__') AS market, t.date, COUNT(*) AS n "
        f"FROM {table} t JOIN stocks s ON s.id = t.stock_id "
        f"WHERE t.date >= :start "
        f"GROUP BY market, t.date"
    ), {"start": window_start_iso}).fetchall()
    counts: dict[str, dict[str, int]] = {}
    series: dict[str, list[int]] = {}
    for market, d, n in rows:
        counts.setdefault(d, {})[market] = n
        series.setdefault(market, []).append(n)
    reference = {
        market: _quantile(vals, _REFERENCE_QUANTILE)
        for market, vals in series.items()
        if len(vals) >= _MIN_MARKET_SAMPLES
    }
    samples = {market: len(vals) for market, vals in series.items()}
    return counts, reference, samples


def describe_reference(reference: dict, samples: dict) -> list[str]:
    """Human-readable lines about what the check could and could not verify.

    Both limits of this detector are silent by construction, and silence here
    reads exactly like health:

    - A market with fewer than `_MIN_MARKET_SAMPLES` dates carrying any rows is
      exempt from the check. That floor exists so a fresh DB does not produce
      nonsense, but it points the wrong way under stress: the longer and more
      total an outage, the fewer dates carry rows, so a market can starve its
      own sample count below the floor and buy itself silence. Verified: a
      market present on only 4 of 29 window dates and then absent entirely on
      the target date is not flagged at all.
    - The reference is a high quantile of the window, so an outage covering
      more than about 90% of the scanned `days` becomes its own definition of
      normal. Verified: flagged through 35/39 degraded dates, silent from
      36/39 on.

    Neither can be fixed by choosing a better statistic — both are what it
    means to infer "normal" from the same data that may be broken. What can be
    fixed is the silence. Printing the reference and its sample count lets an
    operator who knows the domain catch both instantly: "tpex reference=475
    from 39 dates" is obviously wrong to anyone who knows TPEx delivers ~985,
    and "tpex UNVERIFIED (4 dates)" says the check abstained rather than
    passed. Callers surface these lines; they are not decorative.
    """
    lines = []
    for market in sorted(samples):
        n = samples[market]
        if market in reference:
            lines.append(f"  {market}: reference={reference[market]} from {n} dates")
        else:
            lines.append(
                f"  {market}: UNVERIFIED — only {n} date(s) with any rows in the "
                f"window, below the {_MIN_MARKET_SAMPLES} needed to establish a "
                f"reference; this market was NOT checked for gaps"
            )
    return lines


def _quantile(values: list[int], q: float) -> int:
    """`q`-quantile by nearest-rank, so the result is always an observed count.

    Nearest-rank (rather than an interpolating quantile) keeps the reference
    equal to a row count some date actually reported, which makes a flagged
    date explainable: "this market delivered N here against M on <that date>".
    """
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))
    return int(ordered[idx])


def _incomplete_markets(d_iso: str, counts: dict, reference: dict, fraction: float) -> list[str]:
    """Markets whose row count on `d_iso` falls below `fraction` of their reference.

    Markets with no trusted reference (see `_MIN_MARKET_SAMPLES`) are silently
    skipped — there isn't enough information to call them incomplete, and a
    thin/fresh DB must not produce false positives.
    """
    day_counts = counts.get(d_iso, {})
    return sorted(
        market for market, ref in reference.items()
        if ref > 0 and day_counts.get(market, 0) < fraction * ref
    )


def backfill(days: int, datasets: list[str] | None = None, *,
             strict_markets: bool = True, min_market_fraction: float = 0.5) -> dict:
    """Import the last `days` trading days (skips weekends and already-imported dates).

    Runs oldest-last (walks backwards from today). Holidays cost one probe each and
    are logged as 'empty'. Safe to interrupt and re-run: already-present dates skip.

    Completeness (``strict_markets=True``, the default — this is the fix for the
    "half-empty date" bug): a date counts as done only when *every market with
    enough history in the window* is adequately represented, not merely when
    the date has one row. TWSE and TPEx quotes are two independent sources
    fetched in the same ``import_daily`` call; when one silently fails while
    the other succeeds, the old "date exists in daily_prices" check could
    never detect or repair the resulting half-empty date (measured in
    production: 2026-07-16..08-19, TWSE ok/TPEx empty every day, ~510 TPEx
    stocks missing per day; 2026-08-11..08-13, no quotes import ran at all,
    ~800 TWSE stocks missing per day — ~15,150 missing rows total, and
    permanently unrepairable by the old check since `deep_backfill` never
    revisits a stock once it has pre-2010 history).

    Rules, applied per date:
    - Market comes from ``stocks.market`` (observed values: twse, tpex),
      discovered from the data rather than hardcoded, so a new market is
      picked up automatically without a code change. Rows whose stock has a
      NULL market are grouped into a synthetic ``__null__`` market bucket
      instead of being dropped from the accounting — a NULL-market
      population can still be flagged if it goes missing.
    - A market's reference row-count (see ``_market_reference``) is the
      0.9-quantile of its count across window dates that have any data for
      it — deliberately the upper end, because a run of bad days longer than
      half the window would let a median define itself as normal — and is
      trusted only with >= 5 such dates; thinner markets (e.g. a fresh DB
      with a handful of dates) are exempt from the check for that market, so
      a small DB never produces nonsense results.
    - A date is incomplete if any checked market's count on it is below
      ``min_market_fraction`` (default 0.5) of that market's reference.

    Pass ``strict_markets=False`` for the old, pre-fix "date has any row is
    enough" check.
    """
    from datetime import date as date_cls, timedelta

    from sqlalchemy import text

    init_db()
    today = datetime.now(ZoneInfo(config.TZ)).date()
    # scan cap: trading days ≈ 5/7 of calendar days; generous margin for holidays
    scan_calendar_days = days * 2 + 40
    window_start = (today - timedelta(days=scan_calendar_days)).isoformat()

    with get_engine().connect() as conn:
        have = {r[0] for r in conn.execute(text("SELECT DISTINCT date FROM daily_prices"))}
        market_counts, reference, samples = (
            _market_reference(conn, "daily_prices", window_start)
            if strict_markets else ({}, {}, {})
        )

    unverified = sorted(set(samples) - set(reference))
    if strict_markets:
        print("backfill market reference:", flush=True)
        for line in describe_reference(reference, samples):
            print(line, flush=True)

    cur = today
    done = imported = probes = 0
    attempted: list[dict] = []
    for _ in range(scan_calendar_days):
        if done >= days:
            break
        ds = cur.strftime("%Y%m%d")
        if cur.weekday() >= 5:  # Sat/Sun: no request
            cur -= timedelta(days=1)
            continue
        d_iso = iso(ds)
        if d_iso in have:
            missing = (
                _incomplete_markets(d_iso, market_counts, reference, min_market_fraction)
                if strict_markets else []
            )
            if not missing:
                done += 1
                cur -= timedelta(days=1)
                continue
            print(f"backfill {d_iso} incomplete: {','.join(missing)} below "
                  f"{min_market_fraction:.0%} of reference; re-importing", flush=True)
            attempted.extend({"date": d_iso, "market": m} for m in missing)
        results = import_daily(ds, datasets or ["quotes"])
        probes += 1
        if any(r["dataset"] == "quotes" and r["status"] == "ok" for r in results):
            done += 1
            imported += 1
            print(f"backfill {d_iso} ok ({done}/{days})", flush=True)
        cur -= timedelta(days=1)

    # 重新量測,而不是相信「跑完了」。
    #
    # 這條存在的理由:`_run` 的 docstring 明講 "never raise",每一次抓取失敗都被
    # 轉成 import_logs 裡的 empty/error 紀錄然後正常返回;`backfill()` 對任何日期
    # 都不會拋出;而 `cmd_backfill` 沒有 sys.exit。所以在本次改動之前,**25 個
    # 日期全部抓取失敗時,這支指令會印出「N market-gaps repaired」然後 exit 0**,
    # 而那個 N 是在呼叫 import_daily **之前**就累加的——它數的是嘗試,不是成果。
    # 任何把後續步驟鏈在這個離開碼上的流程,都鏈在一個不存在的閘門上。
    #
    # 對照用的參考值刻意沿用跑之前那一份:修復會把列數推上去,若在這裡重算
    # 參考值,門檻會跟著上移,變成拿修好之後的標準去評判修好之後的結果。
    still_incomplete: list[dict] = []
    if strict_markets and attempted:
        attempted_dates = sorted({a["date"] for a in attempted})
        with get_engine().connect() as conn:
            after_counts, _, _ = _market_reference(conn, "daily_prices", window_start)
        for d_iso in attempted_dates:
            for m in _incomplete_markets(d_iso, after_counts, reference, min_market_fraction):
                still_incomplete.append({
                    "date": d_iso,
                    "market": m,
                    "rows": after_counts.get(d_iso, {}).get(m, 0),
                    "reference": reference.get(m),
                })
        for row in still_incomplete:
            print(f"backfill {row['date']} STILL INCOMPLETE: {row['market']} has "
                  f"{row['rows']} rows against a reference of {row['reference']}",
                  flush=True)

    return {
        "trading_days": done,
        "imported": imported,
        "probes": probes,
        # `repaired` 保留原鍵名給既有讀者,但語意是「嘗試修復的 (日期, 市場)」。
        # 真正回答「修好了沒有」的是 still_incomplete。
        "repaired": attempted,
        "attempted": attempted,
        "still_incomplete": still_incomplete,
        "reference": dict(reference),
        "samples": dict(samples),
        "unverified_markets": unverified,
    }


# A stock whose earliest daily_prices row predates this date must already have
# had its since-IPO fetch: the daily importers only ever write recent dates
# (import_daily writes one given day, backfill/backfill_margin walk back ~60
# days), so nothing but deep_backfill itself could have put an older row there.
# 2010 was the previous value, and it was unreachable for anything that listed
# after 2010 — every post-2010 listing and nearly every ETF was re-fetched from
# IPO every single night, for ever. The constant only has to sit far enough back
# that no *daily* import can reach it; keeping it a year or two behind the
# present is enough, and the residual re-fetch is then just this year's IPOs.
#
# What would make it wrong: an importer that starts writing arbitrarily old
# history (a new bulk source, or backfill's window growing to years). Then a
# pre-2026 row would no longer prove a deep fetch happened, and this predicate
# would start skipping stocks that were never deep-filled. The fix at that point
# is a real per-stock marker (import_logs has no stock column today), not a
# newer year — bumping the year would only re-break the post-2026 listings.
DEEP_HISTORY_BEFORE = "2026-01-01"


def is_deep_enough(min_date: str | None) -> bool:
    """True when the stock's earliest stored row proves a since-IPO fetch happened."""
    return bool(min_date) and min_date < DEEP_HISTORY_BEFORE


def deep_backfill(ids: list[str] | None = None, top: int | None = None,
                  all_stocks: bool = False, sleep_s: float = 7.0) -> dict:
    """Since-IPO history via FinMind, one request per stock.

    Selection: explicit ids > --top N by latest turnover > --all (type stock/etf).
    Anonymous quota is low; a free token (RADAR_FINMIND_TOKEN) allows ~600 req/hr.
    On quota exhaustion: stops cleanly; re-run later — a stock is skipped when its
    earliest stored row predates DEEP_HISTORY_BEFORE, which no daily import could
    have written, so it can only have come from an earlier since-IPO fetch.
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
        if is_deep_enough(min_date):
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


def import_warrant_master() -> dict:
    """權證主檔:TPEx 直接含標的代號;TWSE 只有標的名稱 → 用 stocks.name 反查。"""
    from sqlalchemy import text

    init_db()
    engine = get_engine()
    today = datetime.now(ZoneInfo(config.TZ)).strftime("%Y%m%d")

    twse_rows = twse.fetch_warrant_master()
    tpex_rows = tpex.fetch_warrant_master()

    with engine.begin() as conn:
        name_to_id = {r[1]: r[0] for r in conn.execute(text(
            "SELECT id, name FROM stocks WHERE type IN ('stock','etf')"))}
        matched = unmatched = 0
        rows = []
        for r in twse_rows:
            sid = name_to_id.get(r.pop("underlying_name"))
            if sid:
                matched += 1
            else:
                unmatched += 1        # 指數型或名稱不一致 → stock_id NULL
            r["stock_id"] = sid
            rows.append(r)
        rows.extend(tpex_rows)         # TPEx 直接含標的代號
        # 只更新主檔欄位;name/market 由每日行情匯入維護(upsert 只碰帶入欄位)
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        n = 0
        for i in range(0, len(rows), 800):
            batch = rows[i : i + 800]
            stmt = sqlite_insert(schema.warrants).values([
                {"id": r["id"], "name": "", "market": "", "kind": r["kind"],
                 "stock_id": r["stock_id"], "strike": r["strike"],
                 "exercise_ratio": r["exercise_ratio"], "maturity_date": r["maturity_date"]}
                for r in batch])
            stmt = stmt.on_conflict_do_update(index_elements=["id"], set_={
                "kind": stmt.excluded.kind, "stock_id": stmt.excluded.stock_id,
                "strike": stmt.excluded.strike, "exercise_ratio": stmt.excluded.exercise_ratio,
                "maturity_date": stmt.excluded.maturity_date,
            })
            conn.execute(stmt)
            n += len(batch)
        _log(conn, "twse+tpex", "warrant_master", today, n, "ok")
    return {"total": n, "twse_matched": matched, "twse_unmatched": unmatched}


def aggregate_warrants(date: str | None = None) -> int:
    """warrant_daily × warrants → warrant_stock_daily(排除牛熊證;date=None 重建全部)。"""
    from sqlalchemy import text

    init_db()
    where = "AND d.date = :d" if date else ""
    params = {"d": iso(date)} if date else {}
    with get_engine().begin() as conn:
        if date:
            conn.execute(text("DELETE FROM warrant_stock_daily WHERE date = :d"), params)
        else:
            conn.execute(text("DELETE FROM warrant_stock_daily WHERE date IN (SELECT DISTINCT date FROM warrant_daily)"))
        r = conn.execute(text(f"""
            INSERT INTO warrant_stock_daily
                (stock_id, date, call_turnover, call_volume, call_count,
                 put_turnover, put_volume, put_count)
            SELECT w.stock_id, d.date,
                SUM(CASE WHEN w.kind = 'call' THEN COALESCE(d.turnover, 0) ELSE 0 END),
                SUM(CASE WHEN w.kind = 'call' THEN COALESCE(d.volume, 0) ELSE 0 END),
                SUM(CASE WHEN w.kind = 'call' AND COALESCE(d.turnover, 0) > 0 THEN 1 ELSE 0 END),
                SUM(CASE WHEN w.kind = 'put' THEN COALESCE(d.turnover, 0) ELSE 0 END),
                SUM(CASE WHEN w.kind = 'put' THEN COALESCE(d.volume, 0) ELSE 0 END),
                SUM(CASE WHEN w.kind = 'put' AND COALESCE(d.turnover, 0) > 0 THEN 1 ELSE 0 END)
            FROM warrant_daily d
            JOIN warrants w ON w.id = d.warrant_id
            WHERE w.stock_id IS NOT NULL AND w.kind IN ('call', 'put') {where}
            GROUP BY w.stock_id, d.date
        """), params)
        return r.rowcount


def upsert_branch_trades(conn, rows: list[dict]) -> int:
    if not rows:
        return 0
    from sqlalchemy import text
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    branches = {}
    for r in rows:
        branches[r["branch_key"]] = {
            "branch_key": r["branch_key"],
            "broker_id": r.get("broker_id"),
            "branch_name": r["branch_name"]
        }
    
    stmt = sqlite_insert(schema.branch_dim).values(list(branches.values()))
    stmt = stmt.on_conflict_do_nothing(index_elements=["branch_key"])
    conn.execute(stmt)
    
    keys = list(branches.keys())
    binds = {f"k{i}": k for i, k in enumerate(keys)}
    in_clause = ",".join(f":k{i}" for i in range(len(keys)))
    mapping_rows = conn.execute(
        text(f"SELECT branch_key, id FROM branch_dim WHERE branch_key IN ({in_clause})"), 
        binds
    ).fetchall()
    key_to_id = {r[0]: r[1] for r in mapping_rows}
    
    raw_rows = []
    for r in rows:
        d = dict(r)
        d["branch_id"] = key_to_id[d["branch_key"]]
        d.pop("branch_key", None)
        d.pop("broker_id", None)
        d.pop("branch_name", None)
        raw_rows.append(d)
        
    return upsert(conn, schema.branch_trades_raw, raw_rows)


def backfill_branches(top: int = 300, days: int = 60, sleep_s: float = 1.2,
                      max_minutes: int | None = None) -> dict:
    """分點歷史 march-back:由最近交易日往回補 `days` 個交易日的前 15 大買賣超。

    可續跑:每個日期先查已有哪些股票,只補缺的;補齊的日期成本趨近零。
    max_minutes:給 GitHub Actions 夜間窗口的安全閥,到時乾淨停下,下次續跑。
    """
    import time as time_mod

    from sqlalchemy import text

    from .providers import fubon

    init_db()
    engine = get_engine()
    deadline = time_mod.monotonic() + max_minutes * 60 if max_minutes else None

    with engine.connect() as conn:
        trade_dates = [r[0] for r in conn.execute(text(
            "SELECT DISTINCT date FROM daily_prices ORDER BY date DESC LIMIT :n"),
            {"n": days})]
        latest = conn.execute(text(
            "SELECT MAX(date) FROM daily_prices")).scalar()
        if top <= 0:
            # 與 import-branch-trades 一致:0 = 全部當日有報價的 stock(不含 ETF)
            targets = [r[0] for r in conn.execute(text(
                "SELECT p.stock_id FROM daily_prices p "
                "JOIN stocks s ON s.id = p.stock_id AND s.type = 'stock' AND s.is_active = 1 "
                "WHERE p.date = :d AND p.close IS NOT NULL "
                "ORDER BY p.stock_id"), {"d": latest})]
        else:
            targets = [r[0] for r in conn.execute(text(
                "SELECT p.stock_id FROM daily_prices p "
                "JOIN stocks s ON s.id = p.stock_id AND s.type = 'stock' "
                "WHERE p.date = :d AND p.turnover IS NOT NULL "
                "ORDER BY p.turnover DESC LIMIT :n"),
                {"d": latest, "n": top})]

    fetched = skipped_dates = failed = 0
    stopped = None
    for d_iso in trade_dates:                       # 新 → 舊,近期資料價值最高
        date = d_iso.replace("-", "")
        with engine.connect() as conn:
            have = {r[0] for r in conn.execute(text(
                "SELECT DISTINCT stock_id FROM branch_trades WHERE date = :d"),
                {"d": d_iso})}
        missing = [sid for sid in targets if sid not in have]
        if not missing:
            skipped_dates += 1
            continue
        for sid in missing:
            if deadline and time_mod.monotonic() > deadline:
                stopped = f"time budget reached at {d_iso}"
                break
            try:
                rows = fubon.fetch_branch_trades(sid, date, throttle=sleep_s)
            except NoDataError:
                continue
            except Exception as e:  # noqa: BLE001
                failed += 1
                if failed > 30:
                    stopped = f"too many failures at {d_iso}: {str(e)[:80]}"
                    break
                continue
            with engine.begin() as conn:
                upsert_branch_trades(conn, rows)
            fetched += 1
        print(f"backfill-branches {d_iso}: missing={len(missing)} done, "
              f"total fetched={fetched}", flush=True)
        if stopped:
            break
    with engine.begin() as conn:
        _log(conn, "fubon", "branch_hist",
             datetime.now(ZoneInfo(config.TZ)).strftime("%Y%m%d"),
             fetched, "ok" if not stopped else "empty", error=stopped)
    print(f"backfill-branches: fetched={fetched}, complete_dates={skipped_dates}/"
          f"{len(trade_dates)}, failed={failed}, stopped={stopped}", flush=True)
    return {"fetched": fetched, "failed": failed, "stopped": stopped}

WARRANT_BRANCH_DEFAULT_CAP = 25_000


def _warrant_branch_targets(conn, date: str, market: str, cap: int,
                            *, fail_on_cap: bool = True) -> list[str]:
    """Return eligible warrant targets using explicit full/legacy semantics.

    For the new all-market path, ``cap`` is deliberately a circuit breaker and
    never a SQL ``LIMIT``.  Legacy single-market historical jobs retain their
    long-standing top-N behavior so existing supervisor calls remain safe.
    """
    from sqlalchemy import text

    if market not in {"twse", "tpex", "all"}:
        raise ValueError("market must be one of: twse, tpex, all")
    if cap <= 0:
        raise ValueError("warrant branch cap (--top) must be positive")
    markets = ("twse", "tpex") if market == "all" else (market,)
    market_where = "w.market IN (" + ",".join(f":market{i}" for i in range(len(markets))) + ")"
    params = {"date": date, "cap": cap}
    params.update({f"market{i}": value for i, value in enumerate(markets)})
    where = """
        d.date = :date
        AND COALESCE(d.volume, 0) > 0
        AND COALESCE(d.turnover, 0) > 0
        AND w.kind IN ('call', 'put')
        AND s.type = 'stock' AND s.is_active = 1
    """ + f" AND {market_where}"
    if fail_on_cap:
        count = conn.execute(text(f"""
            SELECT COUNT(*)
            FROM warrant_daily d
            JOIN warrants w ON w.id = d.warrant_id
            JOIN stocks s ON s.id = w.stock_id
            WHERE {where}
        """), params).scalar_one()
        if count > cap:
            raise RuntimeError(
                f"warrant branch target count {count} exceeds safety cap {cap}; "
                "refuse to silently truncate the full-market pool"
            )
    limit = "" if fail_on_cap else " LIMIT :cap"
    return [r[0] for r in conn.execute(text(f"""
        SELECT d.warrant_id
        FROM warrant_daily d
        JOIN warrants w ON w.id = d.warrant_id
        JOIN stocks s ON s.id = w.stock_id
        WHERE {where}
        ORDER BY d.turnover DESC, d.warrant_id{limit}
    """), params)]


def _warrant_target_counts(conn, date: str, market: str) -> dict[str, int]:
    """Read-only market split for logs/reports; uses the exact target predicate."""
    counts = {"twse": 0, "tpex": 0}
    for one_market in counts:
        if market in ("all", one_market):
            counts[one_market] = len(_warrant_branch_targets(conn, date, one_market, 10**9))
    return counts


def _atomic_json_write(path: Path, payload: dict) -> None:
    """Atomically save warrant state without ever following a stale ``.tmp``.

    The random ``mkstemp`` path is created with exclusive creation in the
    destination directory, so its inode cannot have been pre-planted as a
    hardlink or symlink.  Re-check the final path before creating that temp
    and again immediately before replacement to fail closed on a path swap.
    """
    state_path = _safe_warrant_branch_state_path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{state_path.name}.", suffix=".tmp", dir=state_path.parent,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        _safe_warrant_branch_state_path(state_path)
        os.replace(tmp_path, state_path)
    finally:
        # os.replace has moved it on success; on failure remove only our
        # exclusive, random temp path, never a caller-supplied ``<state>.tmp``.
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def _load_warrant_branch_state(path: Path, *, date: str, market: str,
                               target_hash: str, targets: list[str]) -> dict:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        state = {}
    # A state file may never be reused across a different day or target pool.
    # Resetting is safer than treating unknown old successes as current data.
    if (state.get("version") != 1 or state.get("date") != date
            or state.get("market") != market or state.get("target_hash") != target_hash):
        state = {
            "version": 1, "date": date, "market": market,
            "target_hash": target_hash, "target_count": len(targets), "results": {},
        }
    state["updated_at"] = datetime.now(ZoneInfo(config.TZ)).isoformat(timespec="seconds")
    return state


def _safe_warrant_branch_state_path(path: str | Path) -> Path:
    """Reject a state file that could overwrite the configured SQLite DB."""
    from .compute.read_only_sqlite import safe_report_output_path

    return safe_report_output_path(
        path, report_name="warrant branch state", path_option="--state-file",
    )


def _backfill_warrant_branch_state_path(
    base: str | Path, *, date: str, market: str,
) -> Path:
    """Derive one bounded state file per date/market from a CLI base path."""
    base_path = Path(base)
    suffix = base_path.suffix or ".json"
    return base_path.with_name(f"{base_path.stem}-{date}-{market}{suffix}")


def import_warrant_branch_trades(date: str | None = None, market: str = "all",
                                 top: int = WARRANT_BRANCH_DEFAULT_CAP,
                                 sleep_s: float = 1.0, max_minutes: int | None = None,
                                 state_file: str | Path | None = None,
                                 dry_run: bool = False) -> dict:
    """Fetch one day's complete eligible TWSE/TPEx warrant branch pool.

    The local JSON state file is intentionally outside SQLite: it gives
    per-warrant ``ok``/``empty``/``error``/``pending`` resume semantics without
    a production schema migration.  Only ok/empty are skipped on retry.
    """
    from sqlalchemy import text
    from .providers import fubon

    if max_minutes is not None and max_minutes <= 0:
        raise ValueError("max_minutes must be positive when provided")
    # Explicit caller paths are validated before any init_db/get_engine path:
    # a typo or alias must never trigger a DB creation/migration first.
    explicit_state_path = (
        _safe_warrant_branch_state_path(state_file) if state_file is not None else None
    )
    if dry_run:
        # A report must not create the DB, run additive migrations, switch WAL,
        # or update file metadata.  Reuse the project's physical SQLite mode=ro
        # connection and fail if the configured DB does not already exist.
        from .compute.branch_point_in_time_report import get_read_only_engine
        engine = get_read_only_engine()
    else:
        init_db()
        engine = get_engine()
    try:
        # Keep every dry-run read after engine creation inside this finally:
        # date=None resolution can fail before the target-pool query runs.
        if date is None:
            with engine.connect() as conn:
                date = conn.execute(text("SELECT MAX(date) FROM warrant_daily")).scalar()
                if date is None:
                    raise RuntimeError("no warrant_daily date available")
                date = date.replace("-", "")
        iso_d = iso(date)
        with engine.connect() as conn:
            targets = _warrant_branch_targets(conn, iso_d, market, top)
            market_counts = _warrant_target_counts(conn, iso_d, market)
    finally:
        if dry_run:
            engine.dispose()
    target_hash = hashlib.sha256(
        json.dumps({"date": iso_d, "market": market, "targets": sorted(targets)}, sort_keys=True).encode()
    ).hexdigest()
    state_path = (explicit_state_path if explicit_state_path is not None else
                  Path(config.DATA_DIR) / f"warrant-branch-state-{iso_d}.json")
    state_path = _safe_warrant_branch_state_path(state_path)
    state = _load_warrant_branch_state(
        state_path, date=iso_d, market=market, target_hash=target_hash, targets=targets
    )
    if dry_run:
        print(f"warrant branch report {iso_d}: twse={market_counts['twse']} "
              f"tpex={market_counts['tpex']} total={len(targets)} cap={top}", flush=True)
        return {"date": iso_d, "targets": len(targets), "market_counts": market_counts,
                "complete": False, "dry_run": True, "state_file": str(state_path)}

    _atomic_json_write(state_path, state)
    deadline = time.monotonic() + max_minutes * 60 if max_minutes else None
    done = empty = failed = skipped = written = 0
    stopped = None
    since_checkpoint = 0
    checkpoint_every = 25
    for sid in targets:
        previous = state["results"].get(sid, {}).get("status")
        if previous in {"ok", "empty"}:
            skipped += 1
            continue
        if deadline and time.monotonic() >= deadline:
            stopped = f"time budget reached after {done + empty + failed + skipped}/{len(targets)} targets"
            break
        state["results"][sid] = {"status": "pending"}
        try:
            rows = fubon.fetch_branch_trades(sid, date, throttle=sleep_s)
            with engine.begin() as conn:
                rows_written = upsert_branch_trades(conn, rows)
            state["results"][sid] = {"status": "ok", "rows": rows_written}
            done += 1
            written += rows_written
        except NoDataError as exc:
            state["results"][sid] = {"status": "empty", "error": str(exc)[:200]}
            empty += 1
        except Exception as exc:  # retry on the next invocation
            state["results"][sid] = {"status": "error", "error": str(exc)[:200]}
            failed += 1
            print(f"warrant branch {sid} FAILED: {str(exc)[:100]}", flush=True)
            # Persist real source failures immediately.  Normal responses are
            # checkpointed in batches, avoiding O(n²) JSON rewrite I/O.
            _atomic_json_write(state_path, state)
            since_checkpoint = 0
            continue
        since_checkpoint += 1
        if since_checkpoint >= checkpoint_every:
            _atomic_json_write(state_path, state)
            since_checkpoint = 0

    # Covers a short final batch and max-minutes exit; a crash can only redo a
    # bounded batch of successful requests.
    _atomic_json_write(state_path, state)
    statuses = [state["results"].get(sid, {}).get("status") for sid in targets]
    complete = bool(targets) and all(status in {"ok", "empty"} for status in statuses)
    # An empty-but-valid pool is complete too; distinguish it from a time limit.
    if not targets and stopped is None:
        complete = True
    with engine.begin() as conn:
        log_status = "ok" if complete and targets else ("empty" if complete else "error")
        _log(conn, "fubon", "warrant_branch", date, written, log_status,
             error=stopped or (f"{failed} warrants failed" if failed else None))
    print(f"warrant branches {iso_d}: twse={market_counts['twse']} tpex={market_counts['tpex']} "
          f"ok={done} empty={empty} retry={failed} skipped={skipped} rows={written} "
          f"complete={complete}", flush=True)
    return {"date": iso_d, "targets": len(targets), "market_counts": market_counts,
            "done": done, "empty": empty, "failed": failed, "skipped": skipped,
            "rows": written, "stopped": stopped, "complete": complete,
            "state_file": str(state_path)}


#: 預設把爬取的頭部往回壓一個日曆日(見 `_warrant_branch_trade_dates`)。
WARRANT_BRANCH_MIN_AGE_DAYS = 1

#: 可續跑的停止理由。權證爬蟲是分塊跑的,每一塊都在時間預算用完時「乾淨地停下」
#: 並把進度留在各日 state 檔裡等下一次續跑——那是設計上的正常路徑,不是故障。
#: 真正的故障只有 "too many failures at ...",不列在這裡。
#:
#: 這個 tuple 定義在本模組而不是 cli,因為寫出這些字串的是本模組的四個迴圈;
#: cli 匯入它來決定離開碼,兩層因此不可能各自漂移。
WARRANT_RESUMABLE_STOPS = ("time budget reached", "resume required")


def _warrant_backfill_status(stopped: str | None) -> str:
    """把 `stopped` 轉成 import_logs 的狀態。

    在此之前兩個呼叫點都寫 `"ok" if not stopped else "error"`,於是每一塊乾淨的
    分塊停止都被記成一次失敗——實測 import_logs 裡 warrant_branch_hist 連三列
    `error`,理由全是 "time budget reached",這條訊號 100% 是雜訊,真的壞掉時
    反而看不出來。cli 早就用 `WARRANT_RESUMABLE_STOPS` 分出 75 與 1 了,資料庫
    卻把兩者壓成同一個字;這裡把那個區別補回去。

    注意 `incomplete` 一詞在本專案有兩個來源不同的用法:這裡是「分塊乾淨停止、
    可續跑」,分點匯入那邊是「單輪內個別標的失敗但覆蓋率仍在帶內」。共用詞彙、
    各自推導——不要把任何一邊接到另一邊的判斷上。
    """
    if not stopped:
        return "ok"
    return "incomplete" if stopped.startswith(WARRANT_RESUMABLE_STOPS) else "error"


def _warrant_branch_trade_dates(engine, days: int, min_age_days: int) -> list[str]:
    """最新在前的交易日清單,但**排除**還太新的日期。

    `fubon.fetch_branch_trades` 在頁面解析出零列時一律丟 `NoDataError`,呼叫端
    無法分辨「這檔權證當天真的沒有分點成交」與「MoneyDJ 還沒發布這一天」——
    兩者都會被記成終端狀態 `empty`,而 `empty` 永遠不會重試。

    當天的 `warrant_daily` 是 16:10 那輪寫進來的(約 1.8 萬個目標),但分點頁的
    第一次日更是 17:40,實測還曾延到 22:00 那輪才有資料。所以在交易日傍晚跑一塊,
    會把最新日期的數千個目標永久標成 empty,而且回報成功。每日目標 hash 救不了:
    它只在目標清單變動時改變,不會因為鏡像後來開始供資料而改變。

    把頭部壓後 `min_age_days` 個日曆日就沒有這個歧義;代價是頭部落後一個交易日,
    與 1d／2d 匯出分桶本來就在承受的落後相同。
    """
    from sqlalchemy import text

    cutoff = (datetime.now(ZoneInfo(config.TZ)).date()
              - timedelta(days=max(0, int(min_age_days)))).isoformat()
    with engine.connect() as conn:
        return [r[0] for r in conn.execute(text(
            "SELECT DISTINCT date FROM daily_prices WHERE date <= :cutoff "
            "ORDER BY date DESC LIMIT :n"), {"n": days, "cutoff": cutoff})]


def _backfill_warrant_branches_legacy(top: int = 200, days: int = 120,
                                      sleep_s: float = 1.2, max_minutes: int | None = None,
                                      market: str = "twse",
                                      min_age_days: int = WARRANT_BRANCH_MIN_AGE_DAYS) -> dict:
    """March back date-scoped warrant pools, newest date first.

    The legacy default remains TWSE top-N.  Explicit ``market='all'`` switches
    ``top`` to a fail-closed safety cap and never truncates either market.
    """
    import time as time_mod
    from sqlalchemy import text
    from .providers import fubon

    init_db()
    engine = get_engine()
    deadline = time_mod.monotonic() + max_minutes * 60 if max_minutes else None

    trade_dates = _warrant_branch_trade_dates(engine, days, min_age_days)

    fetched = skipped_dates = failed = empty = 0
    stopped = None
    for d_iso in trade_dates:
        date = d_iso.replace("-", "")
        with engine.connect() as conn:
            # 每個歷史日期各自撈當天真正有交易的權證(而非用「最新」清單往回查——
            # 權證壽命短,半年前的權證早已下市不在今天清單,今天的權證半年前也還沒發行)。
            targets = _warrant_branch_targets(
                conn, d_iso, market, top, fail_on_cap=(market == "all")
            )
            have = {r[0] for r in conn.execute(text(
                "SELECT DISTINCT stock_id FROM branch_trades WHERE date = :d"),
                {"d": d_iso})}
        missing = [sid for sid in targets if sid not in have]
        if not missing:
            skipped_dates += 1
            continue
        for sid in missing:
            if deadline and time_mod.monotonic() > deadline:
                stopped = f"time budget reached at {d_iso}"
                break
            try:
                rows = fubon.fetch_branch_trades(sid, date, throttle=sleep_s)
            except NoDataError:
                empty += 1
                continue
            except Exception as e:  # noqa: BLE001
                failed += 1
                if failed > 30:
                    stopped = f"too many failures at {d_iso}: {str(e)[:80]}"
                    break
                continue
            with engine.begin() as conn:
                upsert_branch_trades(conn, rows)
            fetched += 1
        print(f"backfill-warrant-branches {d_iso}: missing={len(missing)} done, "
              f"total fetched={fetched}", flush=True)
        if stopped:
            break
    with engine.begin() as conn:
        _log(conn, "fubon", "warrant_branch_hist",
             datetime.now(ZoneInfo(config.TZ)).strftime("%Y%m%d"),
             fetched, _warrant_backfill_status(stopped), error=stopped)
    print(f"backfill-warrant-branches: fetched={fetched}, complete_dates={skipped_dates}/"
          f"{len(trade_dates)}, empty={empty}, failed={failed}, stopped={stopped}", flush=True)
    return {"fetched": fetched, "empty": empty, "failed": failed, "stopped": stopped}


def _backfill_warrant_branches_with_state(
    top: int, days: int, sleep_s: float, max_minutes: int | None,
    market: str, state_file: str | Path,
    min_age_days: int = WARRANT_BRANCH_MIN_AGE_DAYS,
) -> dict:
    """Resume each historical warrant pool from its own bounded state file."""
    import time as time_mod
    from sqlalchemy import text
    from .providers import fubon

    state_base = _safe_warrant_branch_state_path(state_file)
    init_db()
    engine = get_engine()
    deadline = time_mod.monotonic() + max_minutes * 60 if max_minutes else None
    trade_dates = _warrant_branch_trade_dates(engine, days, min_age_days)

    fetched = failed = completed_dates = empty = 0
    stopped = None
    state_files: list[str] = []
    for d_iso in trade_dates:
        date = d_iso.replace("-", "")
        with engine.connect() as conn:
            targets = _warrant_branch_targets(
                conn, d_iso, market, top, fail_on_cap=(market == "all")
            )
            have = {r[0] for r in conn.execute(text(
                "SELECT DISTINCT stock_id FROM branch_trades WHERE date = :d"),
                {"d": d_iso})}
        target_hash = hashlib.sha256(json.dumps(
            {"date": d_iso, "market": market, "targets": sorted(targets)}, sort_keys=True,
        ).encode()).hexdigest()
        state_path = _safe_warrant_branch_state_path(
            _backfill_warrant_branch_state_path(
                state_base, date=d_iso, market=market,
            )
        )
        state_files.append(str(state_path))
        state = _load_warrant_branch_state(
            state_path, date=d_iso, market=market,
            target_hash=target_hash, targets=targets,
        )
        pending: list[str] = []
        for sid in targets:
            if sid in have:
                state["results"][sid] = {"status": "ok", "source": "existing_db"}
                continue
            if state["results"].get(sid, {}).get("status") not in {"ok", "empty"}:
                pending.append(sid)
        _atomic_json_write(state_path, state)

        since_checkpoint = 0
        for sid in pending:
            if deadline and time_mod.monotonic() > deadline:
                stopped = f"time budget reached at {d_iso}"
                break
            state["results"][sid] = {"status": "pending"}
            try:
                rows = fubon.fetch_branch_trades(sid, date, throttle=sleep_s)
                with engine.begin() as conn:
                    rows_written = upsert_branch_trades(conn, rows)
                state["results"][sid] = {"status": "ok", "rows": rows_written}
                fetched += 1
            except NoDataError as exc:
                state["results"][sid] = {"status": "empty", "error": str(exc)[:200]}
                empty += 1
            except Exception as exc:  # retry this target on the next invocation
                state["results"][sid] = {"status": "error", "error": str(exc)[:200]}
                failed += 1
                _atomic_json_write(state_path, state)
                since_checkpoint = 0
                if failed > 30:
                    stopped = f"too many failures at {d_iso}: {str(exc)[:80]}"
                    break
                continue
            since_checkpoint += 1
            if since_checkpoint >= 25:
                _atomic_json_write(state_path, state)
                since_checkpoint = 0

        _atomic_json_write(state_path, state)
        statuses = [state["results"].get(sid, {}).get("status") for sid in targets]
        if not targets or all(status in {"ok", "empty"} for status in statuses):
            completed_dates += 1
        print(f"backfill-warrant-branches {d_iso}: targets={len(targets)} "
              f"pending={len(pending)} total fetched={fetched}", flush=True)
        if stopped:
            break

    if stopped is None and completed_dates != len(trade_dates):
        stopped = (
            f"resume required: {len(trade_dates) - completed_dates} date(s) "
            "remain incomplete"
        )
    with engine.begin() as conn:
        _log(conn, "fubon", "warrant_branch_hist",
             datetime.now(ZoneInfo(config.TZ)).strftime("%Y%m%d"),
             fetched, _warrant_backfill_status(stopped), error=stopped)
    # `empty=` 是「終端 empty 中毒」這一類故障唯一看得見的訊號(鏡像回錯誤頁／
    # 佔位頁會解析成零列 → NoDataError → 永久 empty,而整塊仍回報成功),
    # 所以它必須出現在摘要行上,不能只躺在各日 state 檔裡。
    print(f"backfill-warrant-branches: fetched={fetched}, complete_dates={completed_dates}/"
          f"{len(trade_dates)}, empty={empty}, failed={failed}, stopped={stopped}", flush=True)
    return {
        "fetched": fetched, "empty": empty, "failed": failed, "stopped": stopped,
        "state_files": state_files,
    }


def backfill_warrant_branches(top: int = 200, days: int = 120,
                              sleep_s: float = 1.2, max_minutes: int | None = None,
                              market: str = "twse",
                              state_file: str | Path | None = None,
                              min_age_days: int = WARRANT_BRANCH_MIN_AGE_DAYS) -> dict:
    """March back date-scoped warrant pools, newest date first.

    Without ``state_file`` this preserves the legacy top-N behavior exactly.
    When supplied, the path is a base: each date/market gets its own atomic
    ``<stem>-YYYY-MM-DD-<market>.json`` state, avoiding a giant history file.

    ``min_age_days`` holds the head of the crawl back so that "the mirror has
    not published this date yet" cannot be recorded as a terminal ``empty``
    (see :func:`_warrant_branch_trade_dates`).
    """
    if state_file is None:
        return _backfill_warrant_branches_legacy(
            top, days, sleep_s, max_minutes, market, min_age_days,
        )
    return _backfill_warrant_branches_with_state(
        top, days, sleep_s, max_minutes, market, state_file, min_age_days,
    )


# 分點覆蓋率的**警報**門檻(不是上線閘門,上線閘門是共用的
# `min_market_fraction=0.5`,見 `_branch_date_fit` docstring)。
#
# 這個數字可以、也應該照觀測資料調,因為它調錯的代價是「操作者收到一則不準的
# 通知」,不是「少掉一整天的 publish」。設法不是從觀測到的幾個 session 反推,
# 而是從**基準率**推:合法的「沒有分點資料」大約是被請求股票的 2%(冷門股當天
# 根本沒有分點成交;production 實測約 1,950 / 1,988 ≈ 98%),所以警報設在
# 「缺漏率比基準率高一個數量級」= 20% 缺漏 = 0.8 覆蓋。
#
# 0.75~0.9 之間任何值都做同一件事,這是一顆設計上就打算讓人轉的旋鈕。
_BRANCH_ALARM_FRACTION = 0.8


def _branch_coverage(conn, d_iso: str) -> int:
    """當天有分點資料的**普通股**檔數(distinct stock_id)。

    `JOIN stocks ... type='stock'` 是承重的,不可以拿掉:權證的分點資料和個股
    共用 `branch_trades_raw`,一個被權證回補掃過的日期會多帶最多約 18,000 個
    distinct stock_id,沒被掃到的日期一個都不多。少了這個 JOIN,這個統計量會隨
    「另一支不相干的爬蟲跑到哪一天」上下跳一個數量級,量到的就不是分點來源的
    健康度,而是權證回補的進度。
    """
    from sqlalchemy import text

    return int(conn.execute(text(
        "SELECT COUNT(DISTINCT b.stock_id) FROM branch_trades_raw b "
        "JOIN stocks s ON s.id = b.stock_id AND s.type = 'stock' "
        "WHERE b.date = :d"
    ), {"d": d_iso}).scalar() or 0)


def _branch_date_fit(conn, d_iso: str, expected: int,
                     min_market_fraction: float) -> dict:
    """這個日期的分點資料夠不夠完整到可以拿去算籌碼、上線?

    分母不是歷史基準,是**這一輪自己要的股票檔數**。歷史基準存在的理由是「這一天
    *應該*有幾列?匯入端不知道」——對 `_market_reference` 的上櫃/融資呼叫者那確實
    未知(交易所決定公布幾列)。但分點匯入是自己建目標清單的:夜間設定
    (`vps/scripts/daily-branches.sh`,`--top 0`)下,股票目標就是當日 `daily_prices`
    的整個宇宙。分母因此是同一天、精確已知、完全不涉及歷史。

    這一步同時消掉了舊版的每個弱點:沒有 60 天窗、沒有 regime shift 跨騎(目標池
    變動時分子分母一起動)、沒有冷啟動的 `_MIN_MARKET_SAMPLES` 退路、沒有會漂的
    分位數。這個比例的意思從「佔某個會漂的 60 天分位數多少」變成「我們真的要的
    股票裡,有多少檔帶著資料回來」——可解釋,而且讓門檻可以用結構理由辯護,而不是
    靠「觀測到的 26 天剛好符合」。

    `min(1.0, ...)` 是刻意的:累積覆蓋率可以超過單輪的目標數,因為同一個交易日會被
    匯入兩次(17:40 與 22:00),前一輪可能已經覆蓋了這一輪沒有請求的股票。

    ``min_market_fraction``(0.5)是**扣留**閘門,和上櫃/融資呼叫者共用,因為在三處
    意思相同。它的高度由代價不對稱決定,不是由這個統計量的離散程度決定:誤扣留的
    代價是整天不上線,而在 80% 覆蓋率下誤上線的代價是 20% 的股票當晚少一個分點
    訊號。兩者不對稱,所以閘門壓得很低。**對這個統計量它是一條地板,不是一條窄
    帶**——不要有人後來把它當成窄帶來「修好」。

    這裡本來寫著「實際上只有它當初要抓的那種故障(來源死掉/佔位頁,落點在 0 或
    接近 0)構得到」。**2026-09-17 把這句話否證了**:那天 17:40 那輪 902/1956 =
    46.11%,掉到地板以下;同一輪的匯入計數是 **1412 ok、1054 empty、0 failed**,
    empty 全是 NoDataError——來源活得好好的,只是那些股票還沒公布。同一天 22:44
    的第二輪是 1956/1956 = 100%,前一天 09-16 17:40 也只有 1688/1957 = 86.25%。
    所以在 17:40 這個時間點,這道地板除了「來源死掉」之外,也會被**來源太晚**觸發,
    而這兩件事在當下分不出來(都是資料沒回來)。

    分辨得出來的是時間,不是統計量:等到 22:00 資料就填齊了。這正是
    `vps/scripts/daily-branches.sh` 讓當天第二輪在「今天沒有完成標記」時接手完整鏈
    的理由——與其為了晚到而把 17:40 的地板調鬆(調鬆就會讓唯一分不出「還在填」與
    「死了一半」的那一輪去上線,而 withhold 只能阻止上線、不能撤回已上線的東西),
    不如讓地板維持原樣、由較晚那一輪用同一道閘門補上線。

    警報(`_BRANCH_ALARM_FRACTION`,0.8)是另一回事,見該常數。

    兩個已知的盲點,都是刻意留的:

    1. ``ids`` 模式(明確 --ids):比例只替被指定的那幾檔說話,不代表市場。夜間流程
       從不使用這個模式。
    2. 若上游缺了上櫃報價,``--top 0`` 會建出一份半個宇宙的目標清單,分子分母一起
       縮,分點比例看起來很健康。那是 `daily_prices` 完整性閘門的職責,而它正是對
       這種故障開火。**不要**在這裡再加一道檢查——重複扣留不是額外的安全。
    """
    coverage = _branch_coverage(conn, d_iso)
    ratio = min(1.0, coverage / expected) if expected else 0.0
    fit = coverage > 0 and ratio >= min_market_fraction
    alarm = fit and ratio < _BRANCH_ALARM_FRACTION
    return {
        "coverage": coverage,
        "expected": expected,
        "ratio": ratio,
        "fit": fit,
        "alarm": alarm,
        "reason": None if fit else (
            f"branch coverage {coverage} stocks on {d_iso}, "
            f"{ratio:.0%} of the {expected} stock target(s) this run requested, "
            f"below the {min_market_fraction:.0%} publish floor"
        ),
        "alarm_reason": (
            f"branch coverage {coverage}/{expected} stock target(s) = {ratio:.0%}, "
            f"below the {_BRANCH_ALARM_FRACTION:.0%} alarm level"
        ) if alarm else None,
    }


def import_branch_trades(date: str | None = None, top: int = 80,
                         ids: list[str] | None = None, warrants: int = 200,
                         sleep_s: float = 1.2,
                         warrant_turnover_min: int | None = None,
                         min_market_fraction: float = 0.5) -> dict:
    """富邦公開頁抓分點進出(每筆一請求,節流)。

    池選擇:
    - ``ids`` 指定清單時只用該清單
    - ``top <= 0``: **全部**當日有報價的 ``type=stock``(不含 ETF)
    - 否則: 當日 daily_scores 前 top 檔;無分數則退回成交金額前 top(僅 stock)
    未指定 ``warrant_turnover_min`` 時，另保留當日成交金額前 ``warrants`` 大的
    上市權證作過渡池（legacy 相容）。指定門檻時改為上市認購／認售、標的是
    active 普通股且當日成交金額 ``>= warrant_turnover_min`` 的池（``0`` 合法），
    且不會再疊加 legacy Top-N。
    上市＋上櫃全市場權證仍由可續跑的 ``import_warrant_branch_trades`` 獨立處理。

    狀態欄講的是**這個日期夠不夠格上線**,不是「這一輪有沒有小失誤」:

    - ``ok``         一檔都沒失敗,覆蓋率也在警報線之上(見 :func:`_branch_date_fit`)
    - ``incomplete`` 日期仍然合格,但有個別標的失敗、或覆蓋率低於
                     ``_BRANCH_ALARM_FRACTION``。兩個成因獨立,理由字串分開寫。
    - ``error``      日期不合格(覆蓋率低於 ``min_market_fraction``),不管 failed 是幾

    兩個訊號走兩條路。日期覆蓋率是**跨輪累積**的:同一個交易日 17:40 與 22:00
    各匯入一次、upsert 同一組 key,14:39 那種「來源還沒公布」的空跑因此無害
    (實測 2026-08-14 14:39 記了 rows=0,當天最後仍以 1,964 檔收尾)。但累積性
    會把「來源死掉」對操作者藏起來,所以死來源警報是**單輪**、結構性的:
    ``done == 0`` 而目標清單非空。它由 CLI 用獨立離開碼表達,和上線與否無關。
    """
    from sqlalchemy import text

    from .providers import fubon

    if warrant_turnover_min is not None and warrant_turnover_min < 0:
        raise ValueError("warrant_turnover_min must be >= 0")

    init_db()
    engine = get_engine()
    if date is None:
        with engine.connect() as conn:
            date = conn.execute(text(
                "SELECT MAX(date) FROM daily_prices")).scalar().replace("-", "")
    iso_d = iso(date)

    with engine.connect() as conn:
        if ids:
            targets = ids
        elif top <= 0:
            # 全股票(不含 ETF):當日有收盤價者
            targets = [r[0] for r in conn.execute(text(
                "SELECT p.stock_id FROM daily_prices p "
                "JOIN stocks s ON s.id = p.stock_id AND s.type = 'stock' AND s.is_active = 1 "
                "WHERE p.date = :d AND p.close IS NOT NULL "
                "ORDER BY p.stock_id"), {"d": iso_d})]
        else:
            targets = [r[0] for r in conn.execute(text(
                "SELECT ds.stock_id FROM daily_scores ds "
                "JOIN stocks s ON s.id = ds.stock_id AND s.type = 'stock' "
                "WHERE ds.date = :d "
                "ORDER BY ds.final DESC LIMIT :n"), {"d": iso_d, "n": top})]
            if not targets:
                targets = [r[0] for r in conn.execute(text(
                    "SELECT p.stock_id FROM daily_prices p "
                    "JOIN stocks s ON s.id = p.stock_id AND s.type = 'stock' "
                    "WHERE p.date = :d ORDER BY p.turnover DESC LIMIT :n"),
                    {"d": iso_d, "n": top})]
        # 合格判準的分母:**這一輪要的股票檔數**,必須在權證目標被接上去之前量。
        # 接在後面的權證不進 `_branch_coverage` 的分子(那邊 JOIN 了
        # `type='stock'`),所以把它們算進分母會靜默灌水,讓比例永遠偏低。
        expected = len(targets)
        if not ids and warrant_turnover_min is not None:
            # The threshold pool deliberately replaces (rather than augments)
            # legacy --warrants, so one warrant can never be queued twice.
            targets += [r[0] for r in conn.execute(text(
                "SELECT d.warrant_id FROM warrant_daily d "
                "JOIN warrants w ON w.id = d.warrant_id "
                "JOIN stocks s ON s.id = w.stock_id "
                "AND s.type = 'stock' AND s.is_active = 1 "
                "WHERE d.date = :d AND d.turnover >= :turnover_min "
                "AND w.market = 'twse' AND w.kind IN ('call','put') "
                "ORDER BY d.turnover DESC, d.warrant_id ASC"),
                {"d": iso_d, "turnover_min": warrant_turnover_min})]
        elif warrants > 0 and not ids:
            targets += [r[0] for r in conn.execute(text(
                "SELECT d.warrant_id FROM warrant_daily d "
                "JOIN warrants w ON w.id = d.warrant_id "
                "WHERE d.date = :d AND w.market = 'twse' AND w.kind IN ('call','put') "
                "ORDER BY d.turnover DESC LIMIT :n"), {"d": iso_d, "n": warrants})]

    warrant_pool = (
        f"turnover_min={warrant_turnover_min}"
        if warrant_turnover_min is not None else f"warrants={warrants}"
    )
    print(f"branch trades pool: {len(targets)} targets "
          f"(top={top}, {warrant_pool if not ids else 'warrants=0 (ids override)'})", flush=True)
    done = empty = written = 0
    failed_ids: list[str] = []

    def _fetch_one(sid: str) -> str:
        nonlocal written
        try:
            rows = fubon.fetch_branch_trades(sid, date, throttle=sleep_s)
        except NoDataError:
            return "empty"
        except Exception as e:  # noqa: BLE001
            print(f"branch {sid} FAILED: {str(e)[:100]}", flush=True)
            return "failed"
        with engine.begin() as conn:
            written += upsert_branch_trades(conn, rows)
        return "done"

    def _tally(sid: str, sink: list[str]) -> None:
        nonlocal done, empty
        outcome = _fetch_one(sid)
        if outcome == "done":
            done += 1
        elif outcome == "empty":
            empty += 1
        else:
            sink.append(sid)

    for sid in targets:
        _tally(sid, failed_ids)

    # 剛好一次的重試,不是重試框架。1,988 檔裡的單一次失誤,第二次請求成功的
    # 機率遠高於它是真的壞掉;而同一個標的連兩次都失敗,才值得寫進狀態欄。
    if failed_ids:
        print(f"branch trades retry pass: {len(failed_ids)} target(s)", flush=True)
        retry, failed_ids = failed_ids, []
        for sid in retry:
            _tally(sid, failed_ids)
    failed = len(failed_ids)

    # 合格與否在這一輪的寫入都 commit 之後才量(每檔各自 commit,上面已完成)。
    with engine.connect() as conn:
        fitness = _branch_date_fit(conn, iso_d, expected, min_market_fraction)
    coverage = fitness["coverage"]
    ratio = fitness["ratio"]
    if not fitness["fit"]:
        status, err = "error", fitness["reason"]
    elif fitness["alarm"] or failed:
        # 兩個互相獨立的 `incomplete` 成因,各自帶自己的理由字串:操作者要能從
        # 日誌一眼分辨「覆蓋率低到該看一下」和「有幾檔抓失敗」。
        status = "incomplete"
        err = "; ".join([r for r in (
            fitness["alarm_reason"],
            f"{failed} stocks failed" if failed else None,
        ) if r])
    else:
        status, err = "ok", None
    with engine.begin() as conn:
        _log(conn, "fubon", "branch", date, written, status, error=err)
        # 判準看到的輸入要每晚留痕,否則這條帶狀判斷可能悄悄啟用而從沒被驗證過。
        # 用既有的通用欄位,不需要 schema migration;`dataset='branch_coverage'`
        # 不落在 JSON export 的 `dataset IN ('quotes','insti','margin')` 裡,也不
        # 等於 shell 端查的 `dataset='branch'`,而 prune 是按 date 砍的,一體適用。
        #
        # 分母(`expected`)寫進**同一列**的 error 欄,不另開一列:同一個交易日一晚
        # 會跑兩輪,兩列的話讀日誌的人得自己把 coverage 和 expected 按時間配對,
        # 配錯就得到一個不存在的比例。一列自帶分子分母,比例永遠可重建。
        #
        # `done=` / `empty=` 也寫進同一列,理由同上再加一條:低覆蓋率有兩個成因,
        # 「來源死掉」與「來源還沒公布完」,而只看 coverage/expected 分不出來。
        # 2026-09-17 17:40 那輪(902/1956 = 46%)之所以能當場判定是後者,靠的是
        # cron log 裡的 `1412 ok, 1054 empty, 0 failed`——而 `disk-cleanup.sh` 會
        # 修剪那份 log。把這兩個數字放進資料庫,同一個診斷日後光靠 DB 就做得出來。
        _log(conn, "fubon", "branch_coverage", date, coverage, "ok",
             error=f"expected={expected} ratio={ratio:.4f} "
                   f"done={done} empty={empty}")

    # 單輪的死來源警報,獨立於上線判斷:這一輪一檔都沒抓到,但日期可能早已由
    # 前一輪填滿而完全合格。
    dead_feed = done == 0 and bool(targets)

    print(f"branch trades {iso_d}: {done} stocks ok, {empty} empty, "
          f"{failed} failed, {written} rows", flush=True)
    print(f"branch coverage {iso_d}: {coverage} stocks of {expected} requested "
          f"= {ratio:.1%} → {status}", flush=True)
    if err:
        print(f"branch trades {iso_d}: {err}", flush=True)
    if dead_feed:
        print(f"branch trades {iso_d}: this round fetched nothing from the feed "
              f"({len(targets)} targets)", flush=True)
    return {"done": done, "empty": empty, "failed": failed, "rows": written,
            "status": status, "fit": fitness["fit"], "dead_feed": dead_feed,
            "coverage": coverage, "expected": expected, "ratio": ratio,
            "targets": len(targets)}


# 一個抓得到、解析成功、但沒有成分股的分類是「已觀測到的事實」，不是抓取不完整：
# 富邦分類表通用，台股本來就沒有白酒／煙草／槍枝／麻紡等產業。真正的來源異常會計
# 入 failed（例外），不會變成 empty。
#
# 唯一還要防的是來源整體壞掉、每頁都回傳格式正確卻空白的清單——那會看起來像一次
# 乾淨的全空。門檻設在「超過清單的一半」：2026-08-31 實測 1,062 類中 230 類為空
# （約 22%），離 50% 還有兩倍以上距離，足以容納正常年度波動而仍能擋下全面空白。
THEME_EMPTY_MAX_SHARE = 0.5


def import_themes(limit: int | None = None) -> dict:
    """概念股分類(富邦公開頁):清單 1 請求 + 每類 1 請求(3 秒節流)。

    全量約數百類 → 15 分鐘級;每週更新一次即可(成分變動慢)。
    """
    from sqlalchemy import text

    from .providers import fubon

    init_db()
    engine = get_engine()
    now = datetime.now(ZoneInfo(config.TZ)).isoformat(timespec="seconds")
    today = datetime.now(ZoneInfo(config.TZ)).strftime("%Y%m%d")
    data_date = iso(today)

    def _mark_stale(reason: str) -> dict:
        # 保留既有分類；不以抓取異常推斷 retired。
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE themes SET status = 'stale'
                WHERE source = 'fubon' AND (status IS NULL OR status != 'retired')
            """))
            _log(conn, "fubon", "themes", today, 0, "error", error=reason[:500])
        return {"themes": 0, "links": 0, "failed": 1, "status": "stale"}

    try:
        theme_list = fubon.fetch_theme_list()
    except Exception as e:  # noqa: BLE001 - stale data is safer than deleting classifications
        print(f"themes list FAILED: {str(e)[:80]}", flush=True)
        return _mark_stale(str(e))
    if limit is not None:
        theme_list = theme_list[:limit]
    if not theme_list:
        print("themes: empty list; preserving prior classifications as stale", flush=True)
        return _mark_stale("theme list empty")

    done = failed = links = empty = 0
    staged: list[tuple[str, str, list[str]]] = []
    for code, name in theme_list:
        try:
            members = fubon.fetch_theme_members(code)
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"theme {code} {name} FAILED: {str(e)[:80]}", flush=True)
            continue
        if not members:
            empty += 1
            print(f"theme {code} {name} EMPTY", flush=True)
            continue
        staged.append((code, name, members))
        done += 1
        links += len(members)
        if done % 25 == 0:
            print(f"themes {done}/{len(theme_list)} ...", flush=True)

    # 只有整份清單都實際觀測過（staged + empty 恰等於清單長度）、無任何 failed、
    # 且非 --limit，才把 staged 的分類設為 active；否則保留舊資料並 stale，避免把
    # 暫缺誤解為 retired。空成分不算不完整，但整體空比例過高視為來源壞掉。
    empty_sweep = empty > THEME_EMPTY_MAX_SHARE * len(theme_list)
    complete = (
        limit is None and failed == 0 and not empty_sweep
        and len(staged) + empty == len(theme_list)
    )
    if complete:
        with engine.begin() as conn:
            # A fetched listing has no authority to reverse an explicit retired
            # lifecycle decision. Preserve both the row and its old memberships.
            retired_ids = {
                row[0] for row in conn.execute(text("""
                    SELECT id FROM themes WHERE source = 'fubon' AND status = 'retired'
                """))
            }
            # A full list confirms only the returned IDs. Older IDs remain
            # auditable but lose active status; absence is still not retirement.
            conn.execute(text("""
                UPDATE themes SET status = 'stale'
                WHERE source = 'fubon' AND (status IS NULL OR status != 'retired')
            """))
            for code, name, members in staged:
                if code in retired_ids:
                    continue
                upsert(conn, schema.themes, [{
                    "id": code, "name": name, "source": "fubon",
                    "source_updated_at": now, "data_date": data_date,
                    "status": "active", "updated_at": now,
                }])
                conn.execute(text("DELETE FROM stock_themes WHERE theme_id = :t"), {"t": code})
                upsert(conn, schema.stock_themes,
                       [{"theme_id": code, "stock_id": sid} for sid in members])
            _log(conn, "fubon", "themes", today, links, "ok")
        print(f"themes: {done} groups, {links} memberships, complete", flush=True)
        return {"themes": done, "links": links, "failed": 0, "status": "active"}

    rule = ("empty sweep (>%.0f%% of list)" % (THEME_EMPTY_MAX_SHARE * 100)) if empty_sweep \
        else "fetch failed" if failed else "limit" if limit is not None else "unobserved categories"
    reason = (f"partial themes [{rule}]: failed={failed}, empty={empty}/{len(theme_list)}, "
              f"limit={limit}")
    result = _mark_stale(reason)
    result.update({"themes": done, "links": links, "failed": failed, "empty": empty})
    print(f"themes: {done} groups staged, {links} memberships; {reason}; prior data kept", flush=True)
    return result


BUYBACK_MAX_DAYS = 365


def _validate_buyback_range(date_from: str, as_of: str) -> tuple[str, str]:
    """Return ISO dates after rejecting unbounded, reversed, or oversized spans."""
    try:
        start = date_cls.fromisoformat(date_from)
        end = date_cls.fromisoformat(as_of)
    except ValueError as exc:
        raise ValueError("buyback dates must be ISO YYYY-MM-DD") from exc
    if start > end:
        raise ValueError("buyback date_from must not be after as_of")
    if (end - start).days > BUYBACK_MAX_DAYS:
        raise ValueError(f"buyback range must not exceed {BUYBACK_MAX_DAYS} days")
    return start.isoformat(), end.isoformat()


def _buyback_row_dict(row, imported_at: str) -> dict:
    return {
        "plan_id": row.plan_id,
        "stock_id": row.stock_id, "name": row.name, "market": row.market,
        "board_date": row.board_date, "purpose": row.purpose,
        "total_amount_limit": row.total_amount_limit, "planned_shares": row.planned_shares,
        "price_min": row.price_min, "price_max": row.price_max,
        "start_date": row.start_date, "end_date": row.end_date,
        "completed_flag": row.completed_flag, "executed_shares": row.executed_shares,
        "transferred_shares": row.transferred_shares, "execution_pct": row.execution_pct,
        "executed_amount": row.executed_amount, "avg_price": row.avg_price,
        "share_ratio_pct": row.share_ratio_pct, "incomplete_reason": row.incomplete_reason,
        "report_date": row.report_date, "source_updated_at": row.source_updated_at,
        "source": "mops_t35sc09", "imported_at": imported_at,
    }


def import_buybacks(date_from: str, as_of: str) -> dict:
    """Atomically import official MOPS plans after *both* markets validate.

    The MOPS page is an ephemeral HTML result.  A request, redirect, parser, or
    table-layout failure in either market leaves ``buybacks`` untouched; only an
    ``import_logs`` error record is written for auditability.
    """
    from .providers import mops

    date_from, as_of = _validate_buyback_range(date_from, as_of)
    init_db()
    try:
        staged_twse = mops.fetch_buybacks(date_from, as_of, "twse")
        staged_tpex = mops.fetch_buybacks(date_from, as_of, "tpex")
        if not staged_twse or not staged_tpex:
            raise RuntimeError("MOPS returned no valid buyback rows for one market")
    except Exception as exc:  # fail closed: fetching occurs before the data transaction
        with get_engine().begin() as conn:
            _log(conn, "mops", "buybacks", as_of.replace("-", ""), 0, "error", error=str(exc)[:500])
        raise RuntimeError(f"buyback import failed without writes: {exc}") from exc

    now = datetime.now(ZoneInfo(config.TZ)).isoformat(timespec="seconds")
    rows = [_buyback_row_dict(row, now) for row in staged_twse + staged_tpex]
    with get_engine().begin() as conn:
        written = upsert(conn, schema.buybacks, rows)
        _log(conn, "mops", "buybacks", as_of.replace("-", ""), written, "ok")
    return {"date_from": date_from, "as_of": as_of, "rows": written}


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


def import_descriptions(limit: int | None = None) -> dict:
    """補充爬取各股的基本資料(營收比重)"""
    import time
    from sqlalchemy import select, update
    from . import schema, config
    from .providers import fubon

    with get_engine().begin() as conn:
        q = select(schema.stocks.c.id).where(
            schema.stocks.c.is_active == 1,
            schema.stocks.c.type.in_(["stock", "etf"]),
            schema.stocks.c.description.is_(None)
        )
        if limit:
            q = q.limit(limit)
        missing_ids = [r[0] for r in conn.execute(q)]
        
    if not missing_ids:
        print("No missing descriptions to update.")
        return {"done": 0, "failed": 0}

    print(f"Fetching descriptions for {len(missing_ids)} stocks...")
    done = 0
    failed = 0
    with get_engine().begin() as conn:
        for i, sid in enumerate(missing_ids):
            desc = fubon.fetch_company_profile(sid)
            if desc:
                conn.execute(
                    update(schema.stocks).where(schema.stocks.c.id == sid).values(description=desc)
                )
                done += 1
            else:
                failed += 1
            if (i + 1) % 10 == 0:
                print(f"Descriptions: {i+1}/{len(missing_ids)} (done: {done}, failed: {failed})", flush=True)
            time.sleep(1) # Be polite

    print(f"Descriptions: {done} updated, {failed} failed.")
    return {"done": done, "failed": failed}


def import_tdcc_shareholding() -> dict:
    """Fetch latest TDCC 集保戶股權分散 CSV → shareholding_dispersion (docs/34 B1)."""
    from .providers.tdcc_shareholding import fetch_tdcc_shareholding

    init_db()
    return _upsert_tdcc_rows(fetch_tdcc_shareholding(), source_tag="holders")


def _upsert_tdcc_rows(rows, source_tag: str = "holders") -> dict:
    payload = [
        {
            "stock_id": r.stock_id,
            "as_of": r.as_of,
            "tier": r.tier,
            "holders": r.holders,
            "shares": r.shares,
            "pct": r.pct,
        }
        for r in rows
    ]
    as_of = payload[0]["as_of"] if payload else None
    stocks = len({r["stock_id"] for r in payload})
    with get_engine().begin() as conn:
        n = upsert(conn, schema.shareholding_dispersion, payload, chunk=2000)
        _log(
            conn,
            "tdcc",
            source_tag,
            (as_of or "00000000").replace("-", ""),
            n,
            "ok",
        )
    return {"rows": n, "stocks": stocks, "as_of": as_of}


def backfill_tdcc_from_archive(
    date_from: str = "2026-04-01",
    date_to: str | None = None,
    *,
    sleep_s: float = 0.4,
    dry_run: bool = False,
    skip_existing: bool = True,
) -> dict:
    """從 wirelessr/tdcc-opendata-archive 回補週快照(官方 endpoint 無歷史)。

    預設 2026-04-01～今天;archive 實際約自 2026-04-30 起。
    """
    from datetime import date

    from sqlalchemy import text

    from .providers.tdcc_shareholding import (
        fetch_archive_week,
        list_archive_weeks_in_range,
    )

    init_db()
    if date_to is None:
        date_to = date.today().isoformat()
    weeks = list_archive_weeks_in_range(date_from, date_to)
    existing: set[str] = set()
    if skip_existing:
        with get_engine().connect() as conn:
            existing = {
                r[0]
                for r in conn.execute(
                    text("SELECT DISTINCT as_of FROM shareholding_dispersion")
                ).fetchall()
            }
    planned = [w for w in weeks if not (skip_existing and w in existing)]
    print(
        f"backfill-tdcc archive: range={date_from}..{date_to} "
        f"listed={len(weeks)} skip={len(weeks) - len(planned)} todo={len(planned)}"
        f"{' dry-run' if dry_run else ''}",
        flush=True,
    )
    imported = 0
    skipped = len(weeks) - len(planned)
    errors: list[str] = []
    for i, w in enumerate(planned):
        if dry_run:
            print(f"  would import {w}", flush=True)
            continue
        try:
            rows = fetch_archive_week(w)
            info = _upsert_tdcc_rows(rows, source_tag="holders-archive")
            imported += 1
            print(
                f"  [{i + 1}/{len(planned)}] {w} as_of={info['as_of']} "
                f"stocks={info['stocks']} rows={info['rows']}",
                flush=True,
            )
        except Exception as e:  # noqa: BLE001
            errors.append(f"{w}: {e}")
            print(f"  [{i + 1}/{len(planned)}] {w} ERROR {e}", flush=True)
        if sleep_s > 0 and i + 1 < len(planned):
            time.sleep(sleep_s)
    return {
        "date_from": date_from,
        "date_to": date_to,
        "listed": len(weeks),
        "planned": len(planned),
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "dry_run": dry_run,
    }


def import_directors(ym: str | None = None) -> dict:
    """Fetch latest TWSE+TPEx 董監明細 → director_holdings (docs/34 §4.6 D1).

    OpenAPI 僅最新月;ym 若指定則只保留該月列(不符則錯誤)。
    """
    from sqlalchemy import text

    from .providers.directors import fetch_all_directors

    init_db()
    rows = fetch_all_directors()
    if ym:
        rows = [r for r in rows if r.as_of_ym == ym]
        if not rows:
            raise RuntimeError(f"import-directors: no rows for ym={ym}")
    payload = [
        {
            "stock_id": r.stock_id,
            "as_of_ym": r.as_of_ym,
            "title": r.title,
            "name": r.name,
            "shares": r.shares,
            "shares_at_election": r.shares_at_election,
            "pledged_shares": r.pledged_shares,
            "pledged_pct": r.pledged_pct,
            "related_shares": r.related_shares,
            "market": r.market,
        }
        for r in rows
    ]
    months = sorted({r["as_of_ym"] for r in payload})
    stocks = len({r["stock_id"] for r in payload})
    with get_engine().begin() as conn:
        for m in months:
            conn.execute(
                text("DELETE FROM director_holdings WHERE as_of_ym = :ym"),
                {"ym": m},
            )
        n = upsert(conn, schema.director_holdings, payload, chunk=2000)
        _log(
            conn,
            "mops",
            "directors",
            (months[-1] if months else "0000-00").replace("-", "") + "01",
            n,
            "ok",
        )
    return {"rows": n, "stocks": stocks, "months": months}


# --------------------------------------------------------------------------- 個股期貨
#
# 資料層而已:抓取、解析、落地。這裡沒有任何指標、分數或匯出。


def _futures_daily_payload(rows) -> list[dict]:
    return [
        {
            "contract_code": r.contract_code,
            "date": r.date,
            "contract_month": r.contract_month,
            "session": r.session,
            "open": r.open,
            "high": r.high,
            "low": r.low,
            "last": r.last,
            "change": r.change,
            "volume": r.volume,
            "settlement_price": r.settlement_price,
            "open_interest": r.open_interest,
        }
        for r in rows
    ]


def _upsert_futures_contracts(conn, contracts, seen_on: str) -> int:
    """寫入/更新標的對照,但**永遠不動 first_seen**,也永遠不刪列。

    不能用 `upsert()`:它會把 row dict 裡的每個非主鍵欄都寫進 ON CONFLICT 的
    SET,first_seen 會被每天的 refresh 覆蓋成今天,「第一次看到是哪天」就沒了。

    `contract_multiplier` 是唯一一個**不照抄新值**的欄:用 coalesce(新, 舊),
    也就是「解析得到就更新,解析不到就保留既有值」。理由是兩種錯的代價不對稱——
    官網改版或某一列缺格時,照抄 NULL 會把一個已知的乘數抹掉,而 `docs/38` R2b
    對乘數未知的契約一律否決,於是那檔標的會從此安靜地不再產生任何旗標;反過來,
    保留舊值只在「TAIFEX 真的改了乘數又剛好那次解析失敗」時才會是錯的,而真的改
    乘數時新值是有數字的,coalesce 照樣蓋過去。TAIFEX 不會公布「乘數未知」,
    所以 NULL 永遠是我們這邊讀失敗,不是世界上的事實。
    """
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from sqlalchemy import func

    if not contracts:
        return 0
    values = [
        {
            "contract_code": c.contract_code,
            "stock_id": c.stock_id,
            "stock_name": c.stock_name,
            "is_stock_future": c.is_stock_future,
            "is_stock_option": c.is_stock_option,
            "is_weekly_option": c.is_weekly_option,
            "market": c.market,
            "contract_multiplier": c.contract_multiplier,
            "first_seen": seen_on,
            "last_seen": seen_on,
        }
        for c in contracts
    ]
    stmt = sqlite_insert(schema.futures_contracts).values(values)
    set_ = {
        name: stmt.excluded[name]
        for name in (
            "stock_id", "stock_name", "is_stock_future", "is_stock_option",
            "is_weekly_option", "market", "last_seen",
        )
    }
    set_["contract_multiplier"] = func.coalesce(
        stmt.excluded.contract_multiplier,
        schema.futures_contracts.c.contract_multiplier,
    )
    conn.execute(stmt.on_conflict_do_update(index_elements=["contract_code"], set_=set_))
    return len(values)


def import_futures() -> dict:
    """當日期貨行情 + 標的對照,同一次執行內一起更新。

    兩者必須同一次跑:行情的「哪些是個股期貨」完全由對照表決定
    (join 規則 = 商品代碼 + 'F'),對照表落後一天,新掛牌的契約就會被當成
    指數期貨丟掉,而且丟得無聲無息。

    回傳的 `stock_futures_rows` 是**寫進 futures_daily 的列數**(只有個股期貨),
    `leftover_codes` 是行情裡對不到對照表的契約代碼數(指數期貨等,不入庫)。
    """
    from .providers.taifex import (
        SESSION_AFTER_HOURS,
        SESSION_REGULAR,
        fetch_daily_report,
        fetch_stock_list,
        split_stock_futures,
    )

    init_db()
    t0 = time.monotonic()
    contracts = fetch_stock_list()
    daily_rows = fetch_daily_report()

    dates = sorted({r.date for r in daily_rows})
    if len(dates) != 1:
        # 這個端點只供應最新一天;一次回傳多個日期代表它的行為變了,
        # 而「多個日期」會讓下面的 import_logs 日期欄變成謊言。
        raise RuntimeError(f"taifex daily report carried {len(dates)} dates: {dates[:5]}")
    data_date = dates[0]

    kept, leftover = split_stock_futures(daily_rows, contracts)
    if not kept:
        # +F 的 join 規則是「個股期貨」這個集合的唯一定義。它對不到任何一列時,
        # 正確的行為是炸掉:靜靜寫 0 列會讓排程看起來一切正常。
        raise RuntimeError(
            f"taifex {data_date}: the '+F' join matched 0 of {len(contracts)} "
            f"mapping rows against {len({r.contract_code for r in daily_rows})} feed "
            "codes — the contract-code join rule no longer holds"
        )

    sessions = {r.session for r in kept}
    with get_engine().begin() as conn:
        n_contracts = _upsert_futures_contracts(conn, contracts, data_date)
        n_rows = upsert(conn, schema.futures_daily, _futures_daily_payload(kept), chunk=2000)
        _log(
            conn, "taifex", "futures", data_date.replace("-", ""), n_rows, "ok",
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
    return {
        "date": data_date,
        "contracts": n_contracts,
        # 乘數涵蓋率:docs/38 R2b 對乘數未知的契約一律否決,所以這個數字少一個,
        # 就是少一檔標的**永遠**不會上榜。放在摘要裡是為了讓它一眼看得見。
        "contracts_with_multiplier": sum(
            1 for c in contracts if c.contract_multiplier is not None
        ),
        "stock_futures_rows": n_rows,
        "feed_rows": len(daily_rows),
        "leftover_codes": len(leftover),
        "has_regular": SESSION_REGULAR in sessions,
        "has_after_hours": SESSION_AFTER_HOURS in sessions,
    }


def _month_chunks(date_from: str, date_to: str) -> list[tuple[str, str]]:
    """把 [date_from, date_to] 切成日曆月區塊,**新到舊**。

    一次請求可以涵蓋約一個月(實測 29 天 → 3.9 MB),所以 250 個交易日約 12 次
    請求。由新往舊走,是因為中斷後最有價值的是最近的資料已經到手。
    """
    start = date_cls.fromisoformat(date_from)
    end = date_cls.fromisoformat(date_to)
    chunks: list[tuple[str, str]] = []
    cursor = end
    while cursor >= start:
        first = cursor.replace(day=1)
        lo = max(first, start)
        chunks.append((lo.isoformat(), cursor.isoformat()))
        cursor = first - timedelta(days=1)
    return chunks


def backfill_futures(days: int = 250, sleep_s: float = 1.2, dry_run: bool = False) -> dict:
    """用 futDataDown 的 Big5 CSV 按月回補歷史行情。

    可續跑:每個月區塊先比對「這段期間的市場交易日(取自 daily_prices)」與
    futures_daily 已有的日期,全部到齊就跳過,連請求都不發。中斷後重跑只會去撈
    真正還缺的月份。

    禮貌:區塊之間 sleep。富邦那支爬蟲用 1.0–1.2 秒,而這裡一年只有十幾次請求,
    沿用同一個節奏綽綽有餘。
    """
    from sqlalchemy import text as sql_text

    from .providers.taifex import fetch_history

    init_db()
    engine = get_engine()
    with engine.connect() as conn:
        market_days = [
            r[0]
            for r in conn.execute(sql_text(
                "SELECT DISTINCT date FROM daily_prices ORDER BY date DESC LIMIT :n"
            ), {"n": days}).fetchall()
        ]
        have = {
            r[0]
            for r in conn.execute(sql_text("SELECT DISTINCT date FROM futures_daily")).fetchall()
        }
    if not market_days:
        raise RuntimeError(
            "backfill-futures: daily_prices is empty, so there is no market calendar "
            "to say which dates are missing; import price history first"
        )
    date_from, date_to = market_days[-1], market_days[0]
    wanted = set(market_days)

    chunks = _month_chunks(date_from, date_to)
    planned = []
    for lo, hi in chunks:
        missing = {d for d in wanted if lo <= d <= hi} - have
        if missing:
            planned.append((lo, hi, len(missing)))
    print(
        f"backfill-futures: range={date_from}..{date_to} market_days={len(wanted)} "
        f"already={len(wanted & have)} chunks={len(chunks)} todo={len(planned)}"
        f"{' dry-run' if dry_run else ''}",
        flush=True,
    )

    rows_written = 0
    dates_written: set[str] = set()
    errors: list[str] = []
    for i, (lo, hi, n_missing) in enumerate(planned):
        if dry_run:
            print(f"  would fetch {lo}..{hi} ({n_missing} market days missing)", flush=True)
            continue
        try:
            rows = fetch_history(lo, hi)
            with engine.begin() as conn:
                contract_codes = {
                    r[0]
                    for r in conn.execute(sql_text(
                        "SELECT contract_code FROM futures_contracts"
                    )).fetchall()
                }
                kept = [r for r in rows if r.contract_code in contract_codes]
                n = upsert(conn, schema.futures_daily, _futures_daily_payload(kept), chunk=2000)
                chunk_dates = {r.date for r in kept}
                _log(conn, "taifex", "futures-history", lo.replace("-", ""), n, "ok")
            rows_written += n
            dates_written |= chunk_dates
            print(
                f"  [{i + 1}/{len(planned)}] {lo}..{hi} dates={len(chunk_dates)} rows={n}",
                flush=True,
            )
        except Exception as e:  # noqa: BLE001 - one bad month must not lose the rest
            errors.append(f"{lo}..{hi}: {e}")
            print(f"  [{i + 1}/{len(planned)}] {lo}..{hi} ERROR {e}", flush=True)
        if sleep_s > 0 and i + 1 < len(planned):
            time.sleep(sleep_s)

    with engine.connect() as conn:
        have_after = {
            r[0]
            for r in conn.execute(sql_text("SELECT DISTINCT date FROM futures_daily")).fetchall()
        }
    return {
        "date_from": date_from,
        "date_to": date_to,
        "market_days": len(wanted),
        "chunks_planned": len(planned),
        "dates_written": len(dates_written),
        "rows_written": rows_written,
        "still_missing": sorted(wanted - have_after),
        "errors": errors,
        "dry_run": dry_run,
    }
