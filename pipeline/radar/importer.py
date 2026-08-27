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
) -> dict:
    """Backfill TWSE/TPEx margin for recent trading days with gaps or missing buy fields.

    Unlike ``backfill()``, checks ``daily_margins`` completeness per date instead of
    skipping when ``daily_prices`` already has the day.
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
    targets = list(reversed(trading_days[:days]))

    imported = skipped = errors = 0
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
        need = cnt < min_rows or (cnt > 0 and null_buy > cnt * 0.05)
        if not need:
            skipped += 1
            continue
        if dry_run:
            print(
                f"backfill-margin dry-run {d_iso}: rows={cnt} null_buy={null_buy}",
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
    }


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

def backfill_warrant_branches(top: int = 200, days: int = 120, sleep_s: float = 1.2,
                              max_minutes: int | None = None) -> dict:
    """權證分點歷史 march-back:由最近交易日往回補 `days` 個交易日的前 `top` 大權證分點。"""
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

    fetched = skipped_dates = failed = 0
    stopped = None
    for d_iso in trade_dates:
        date = d_iso.replace("-", "")
        with engine.connect() as conn:
            # 每個歷史日期各自撈當天真正有交易的權證(而非用「最新」清單往回查——
            # 權證壽命短,半年前的權證早已下市不在今天清單,今天的權證半年前也還沒發行)。
            targets = [r[0] for r in conn.execute(text(
                "SELECT d.warrant_id FROM warrant_daily d "
                "JOIN warrants w ON w.id = d.warrant_id "
                "WHERE d.date = :d "
                "AND w.market = 'twse' AND w.kind IN ('call','put') "
                "ORDER BY d.turnover DESC LIMIT :n"),
                {"d": d_iso, "n": top})]
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
        print(f"backfill-warrant-branches {d_iso}: missing={len(missing)} done, "
              f"total fetched={fetched}", flush=True)
        if stopped:
            break
    with engine.begin() as conn:
        _log(conn, "fubon", "warrant_branch_hist",
             datetime.now(ZoneInfo(config.TZ)).strftime("%Y%m%d"),
             fetched, "ok" if not stopped else "empty", error=stopped)
    print(f"backfill-warrant-branches: fetched={fetched}, complete_dates={skipped_dates}/"
          f"{len(trade_dates)}, failed={failed}, stopped={stopped}", flush=True)
    return {"fetched": fetched, "failed": failed, "stopped": stopped}


def import_branch_trades(date: str | None = None, top: int = 80,
                         ids: list[str] | None = None, warrants: int = 200,
                         sleep_s: float = 1.2) -> dict:
    """富邦公開頁抓分點進出(每筆一請求,節流)。

    池選擇:
    - ``ids`` 指定清單時只用該清單
    - ``top <= 0``: **全部**當日有報價的 ``type=stock``(不含 ETF)
    - 否則: 當日 daily_scores 前 top 檔;無分數則退回成交金額前 top(僅 stock)
    另抓當日成交金額前 ``warrants`` 大的上市權證(權證分點;上櫃權證該頁無資料)。
    """
    from sqlalchemy import text

    from .providers import fubon

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
        if warrants > 0 and not ids:
            targets += [r[0] for r in conn.execute(text(
                "SELECT d.warrant_id FROM warrant_daily d "
                "JOIN warrants w ON w.id = d.warrant_id "
                "WHERE d.date = :d AND w.market = 'twse' AND w.kind IN ('call','put') "
                "ORDER BY d.turnover DESC LIMIT :n"), {"d": iso_d, "n": warrants})]

    print(f"branch trades pool: {len(targets)} targets "
          f"(top={top}, warrants={0 if ids else warrants})", flush=True)
    done = empty = failed = written = 0
    for sid in targets:
        try:
            rows = fubon.fetch_branch_trades(sid, date, throttle=sleep_s)
        except NoDataError:
            empty += 1
            continue
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"branch {sid} FAILED: {str(e)[:100]}", flush=True)
            continue
        with engine.begin() as conn:
            written += upsert_branch_trades(conn, rows)
        done += 1
    with engine.begin() as conn:
        _log(conn, "fubon", "branch", date, written,
             "ok" if failed == 0 else "error",
             error=None if failed == 0 else f"{failed} stocks failed")
    print(f"branch trades {iso_d}: {done} stocks ok, {empty} empty, "
          f"{failed} failed, {written} rows", flush=True)
    return {"done": done, "empty": empty, "failed": failed, "rows": written}


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

    # 只有全來源、全題材成功才把任何分類設為 active；partial/empty/--limit
    # 皆保留舊資料並 stale，避免把暫缺誤解為 retired 或新鮮完整資料。
    complete = limit is None and failed == 0 and empty == 0 and len(staged) == len(theme_list)
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

    reason = f"partial themes: failed={failed}, empty={empty}, limit={limit}"
    result = _mark_stale(reason)
    result.update({"themes": done, "links": links, "failed": failed, "empty": empty})
    print(f"themes: {done} groups staged, {links} memberships; {reason}; prior data kept", flush=True)
    return result


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
