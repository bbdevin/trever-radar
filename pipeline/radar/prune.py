"""Database pruning utilities.

刻意不刪的表:``branch_pit_stats``(docs/37 E2 的 point-in-time 觀察帳本)。
它的每一列都帶著 ``computed_at``,記錄「那一天實際看得到什麼」;因為
``branch_trades`` 仍在 backfill,刪掉之後重算得到的是**另一個觀察**,不是同一
筆資料。一年約 50 MB,是這顆磁碟上最不值得刪的東西。請不要順手把它加進來。

同樣刻意不刪的還有 ``branch_stock_pctile_counts``(分點 × 個股 的價格分位計數)。
它**只有一份最新快照**,每次重算就整份被取代,所以沒有可以 prune 的歷史;
在這裡刪它只會讓個股頁短暫變空,不會省下任何長期空間。

``futures_daily``(TAIFEX 期貨日行情)**也永不 prune**。它一年約 40 MB,而它的
上游回補成本不對稱:當日端點只供應最新一天(``?date=`` 參數被忽略),歷史只能走
Big5 CSV 的 futDataDown 一個月一次請求慢慢撈回來。刪掉一年份,要重抓大約 12 次
請求;省下的 40 MB 換來的是一段再也不保證抓得回來的歷史。``futures_contracts``
同理不刪:它記的是「哪一天還看得到這檔標的」,刪列等於改寫那段歷史。

``branch_trades_raw`` 的保留政策(2026-10-04 Planner 定案,docs/29 §2.4、docs/44 §6.4):

- **權證分點列**(``LENGTH(stock_id) = 6``)保留 150 個交易日,與 ``warrant_daily``
  用**同一個** ``war_cutoff``(嚴格 ``<`` 刪除,等於 cutoff 的那天保留)。權證壽命短,
  過期權證的分點明細沒有產品用途,卻是這張表成長的主力。
- **個股/ETF 分點列**(4 碼)**永久保留**——它是評分、分點勝率、E2 帳本的根資料,
  且歷史只能靠慢速回補撈回來。不要把 4 碼列加進任何刪除條件。
- 只在新版面(有 ``ix_branch_trades_raw_date_cover``)啟用:舊版面沒有依日期連續的
  覆蓋索引,逐日 COUNT/DELETE 會在全表跳。舊版面一律跳過並印出原因。
- 由新到舊、一個日期一個交易;每輪最多處理 ``max_dates`` 個日期,連續 3 個空日期就停
  ——不做一次性補刪,過期資料靠每天 17:40 那輪自然消化。刪除只把頁面放回 freelist
  給之後的寫入重用,**不 VACUUM**(VACUUM 要整顆 DB 的暫存空間與長鎖)。
"""
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text

from . import config, schema
from .branch_source import COVER_INDEX, has_date_cover
from .db import get_engine, init_db

EMPTY_DATES_STOP = 3


def _prune_warrant_branches(engine, war_cutoff, days, max_dates, dry_run) -> dict:
    result = {"deleted_rows": 0, "dates": [], "skipped_reason": None, "freelist_count": None}

    with engine.connect() as conn:
        if not days:
            result["skipped_reason"] = "disabled (--warrant-branches 0)"
        elif not has_date_cover(conn):
            result["skipped_reason"] = f"no {COVER_INDEX}"
        elif not war_cutoff:
            result["skipped_reason"] = "no war_cutoff (not enough trading days)"
        if result["skipped_reason"]:
            print(f"warrant-branch prune skipped: {result['skipped_reason']}")
            return result
        dates = [r[0] for r in conn.execute(text(
            "SELECT DISTINCT date FROM daily_prices WHERE date < :c ORDER BY date DESC"
        ), {"c": war_cutoff})]

    count_sql = text(
        f"SELECT COUNT(*) FROM branch_trades_raw INDEXED BY {COVER_INDEX} "
        "WHERE date = :d AND LENGTH(stock_id) = 6")
    empty = 0
    for d in dates:
        if len(result["dates"]) >= max_dates:
            break
        with engine.connect() as conn:
            n = conn.execute(count_sql, {"d": d}).scalar()
        if n == 0:
            empty += 1
            if empty >= EMPTY_DATES_STOP:
                break
            continue
        empty = 0
        if dry_run:
            print(f"prune warrant-branch rows date={d} would delete={n}")
        else:
            t0 = time.monotonic()
            with engine.begin() as conn:
                deleted = conn.execute(text(
                    "DELETE FROM branch_trades_raw WHERE date = :d AND LENGTH(stock_id) = 6"
                ), {"d": d}).rowcount
                if deleted != n:
                    raise RuntimeError(f"warrant-branch prune {d}: counted {n}, deleted {deleted}")
                elapsed = time.monotonic() - t0
                conn.execute(schema.import_logs.insert().values(
                    run_at=datetime.now(ZoneInfo(config.TZ)).isoformat(timespec="seconds"),
                    source="prune", dataset="warrant_branch_prune", date=d,
                    rows=n, status="ok", duration_ms=int(elapsed * 1000),
                ))
            print(f"prune warrant-branch rows date={d} deleted={n} elapsed={elapsed:.2f}s")
        result["deleted_rows"] += n
        result["dates"].append(d)

    with engine.connect() as conn:
        result["freelist_count"] = conn.execute(text("PRAGMA freelist_count")).scalar()
    return result


def prune_db(indicators_days: int = 400, warrants_days: int = 150, logs_days: int = 180,
             vacuum: bool = False, warrant_branches_days: int = 150, max_dates: int = 10,
             dry_run: bool = False) -> dict:
    if not dry_run:  # init_db 會開寫交易(migrate/正規化);dry-run 對正式庫只讀
        init_db()
    engine = get_engine()

    with engine.connect() as conn:
        # Get cutoff date for indicators
        ind_cutoff = conn.execute(text(
            "SELECT date FROM (SELECT DISTINCT date FROM daily_prices ORDER BY date DESC LIMIT 1 OFFSET :n)"
        ), {"n": indicators_days}).scalar()

        # Get cutoff date for warrants — 權證分點列(branch_trades_raw 6 碼)共用這一條線。
        war_cutoff = conn.execute(text(
            "SELECT date FROM (SELECT DISTINCT date FROM daily_prices ORDER BY date DESC LIMIT 1 OFFSET :n)"
        ), {"n": warrants_days}).scalar()

    verb = "SELECT COUNT(*) FROM" if dry_run else "DELETE FROM"

    def _run(conn, sql, params):
        res = conn.execute(text(f"{verb} {sql}"), params)
        return res.scalar() if dry_run else res.rowcount

    # dry-run: 只讀,不開寫交易
    ctx = engine.connect() if dry_run else engine.begin()
    with ctx as conn:
        ind_deleted = 0
        if ind_cutoff:
            ind_deleted = _run(conn, "indicators_daily WHERE date < :d", {"d": ind_cutoff})

        war_deleted = 0
        if war_cutoff:
            war_deleted = _run(conn, "warrant_daily WHERE date < :d", {"d": war_cutoff})

        logs_deleted = _run(conn, "import_logs WHERE date < date('now', :modifier)",
                            {"modifier": f"-{logs_days} days"})

    if dry_run:
        print(f"would delete: {ind_deleted} indicators, {war_deleted} warrants, {logs_deleted} logs")

    # 權證分點天數只決定「開/關」;cutoff 本身刻意沿用 war_cutoff(docs/29 §2.4)。
    wb = _prune_warrant_branches(engine, war_cutoff, warrant_branches_days, max_dates, dry_run)

    if vacuum and not dry_run:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text("VACUUM"))

    return {
        "indicators": ind_deleted,
        "warrants": war_deleted,
        "logs": logs_deleted,
        "warrant_branches": wb,
        "vacuum": vacuum and not dry_run,
        "dry_run": dry_run,
    }
