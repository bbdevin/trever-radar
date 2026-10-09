"""Backward-adjustment factors for daily prices."""
from __future__ import annotations

import time
from array import array
from datetime import date as date_cls
from datetime import datetime, timedelta
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
            ORDER BY turnover DESC, stock_id
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
            params = [{"sid": sid, "d": d, "factor": f} for d, f in factors.items()]
            if params:  # executemany:全市場跑才不會被逐列 UPDATE 拖死
                conn.execute(text(
                    "UPDATE daily_prices SET adj_factor = :factor "
                    "WHERE stock_id = :sid AND date = :d"), params)
                rows_updated += len(params)
            _log(conn, "finmind", "adj_factor", today, len(events), "ok")

        done += 1
        events_seen += len(events)
        print(f"adjust {sid} ok: {len(events)} events, {len(factors)} price rows", flush=True)
        if sleep_s > 0:
            time.sleep(sleep_s)

    return {"done": done, "failed": failed, "events": events_seen, "rows": rows_updated}


# ── 增量選股(compute-adjustments --ex-dates-since)───────────────────────────
#
# 以下只負責「挑哪幾檔要重算」與「重算前後比對」,不碰上面的因子邏輯:
# 挑出來的代號原樣交給 compute_adjustments(ids=…),同一個 FinMind 逐檔請求、
# 同一個 factors_for_dates、同一個整檔覆寫。
#
# 為什麼不用 FinMind 一次全市場:TaiwanStockDividendResult 不帶 data_id 只開放
# 贊助會員,免費 token 回 status 400「Your level is free」(2026-10-09 實測)。
# 改用證交所 TWT49U 與櫃買 bulletin/exDailyQ(公開、無驗證碼、各一次請求)
# **只當代號挑選器**。

def resolve_since(value: str, today: date_cls) -> str:
    """``--ex-dates-since`` 的值:整數 N(往前 N 個日曆日)或 YYYY-MM-DD。回傳 ISO 日期。"""
    v = str(value).strip()
    if v.isdigit():
        return (today - timedelta(days=int(v))).isoformat()
    try:
        return date_cls.fromisoformat(v).isoformat()
    except ValueError:
        raise SystemExit(f"--ex-dates-since needs N (days) or YYYY-MM-DD, got {value!r}") from None


def ex_date_candidates(since: str, until: str) -> list[str]:
    """上市＋上櫃在 [since, until](ISO,含兩端)內有除權息日的代號,去重排序。

    任一市場抓失敗就整個失敗(不要靜默只做一半);隔天的 N 日窗會再涵蓋到。
    """
    from .providers import tpex, twse

    start, end = since.replace("-", ""), until.replace("-", "")
    rows = twse.fetch_ex_rights(start, end) + tpex.fetch_ex_rights(start, end)
    return sorted({r["code"] for r in rows if since <= r["date"] <= until})


def select_ex_date_ids(since: str, until: str) -> list[str]:
    """ex_date_candidates ∩ 本庫可還原的標的(與 --all 同一宇宙:stocks.type IN
    ('stock','etf') 且有 daily_prices 列)。唯讀,不呼叫 init_db。"""
    candidates = ex_date_candidates(since, until)
    if not candidates:
        return []
    with get_engine().connect() as conn:
        known = {r[0] for r in conn.execute(text("""
            SELECT s.id FROM stocks s
            WHERE s.type IN ('stock', 'etf')
              AND EXISTS (SELECT 1 FROM daily_prices p WHERE p.stock_id = s.id)
        """))}
    return [c for c in candidates if c in known]


def factor_snapshot(ids: list[str]) -> dict[str, array]:
    """{stock_id: 依日期排序的 adj_factor 陣列}。只給前後比對用。

    用 array('d')(每列 8 bytes)而不是 (date, factor) tuple:旺季一次 ~300 檔 ×
    數千列,tuple 版要幾百 MB,VPS 只有 1.7 GB。比對期間持 DB 鎖、回補容器已暫停,
    日期集合不會變,所以只比因子序列即可。
    """
    out: dict[str, array] = {}
    with get_engine().connect() as conn:
        for sid in ids:
            out[sid] = array("d", (r[0] for r in conn.execute(text(
                "SELECT adj_factor FROM daily_prices WHERE stock_id = :sid ORDER BY date"
            ), {"sid": sid})))
    return out


def diff_factor_snapshots(before: dict[str, array],
                          after: dict[str, array]) -> tuple[list[str], int]:
    """回傳 (因子有變的代號, 因子有變的列數)。列數不同時整檔算變動。"""
    changed_ids: list[str] = []
    changed_rows = 0
    for sid in sorted(set(before) | set(after)):
        b = before.get(sid, array("d"))
        a = after.get(sid, array("d"))
        if len(a) != len(b):
            n = max(len(a), len(b))
        else:
            n = sum(1 for x, y in zip(a, b) if x != y)
        if n:
            changed_ids.append(sid)
            changed_rows += n
    return changed_ids, changed_rows
