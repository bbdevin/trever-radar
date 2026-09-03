"""把 E2 point-in-time 觀察落地成分點層級的計數帳本(``branch_pit_stats``)。

為什麼要「落地」而不是需要時重算
--------------------------------
本工具讀的是 ``branch_trades WHERE date <= as_of``,而 490 天的 backfill 仍在
持續寫入,同一個過去日期在不同時間查會得到不同的列。因此「幾個月後重算」
不是同一個觀察,是另一個觀察。帶著 ``computed_at`` 的一列,是「那一天實際
看得到什麼」的唯一紀錄。

為什麼只存計數、不存比率
------------------------
比率不可還原:同一個 low_buy 比率各日平均是 75%,pooled 起來是 66.7%,差別
純粹來自分母權重。而且 unknown 的量很大(某個 as_of 的 913,078 筆 buy episode
裡,226,356 筆 fwd5 未成熟、212,140 筆沒有可知的 20 日分位)。只存一個比率會
把四分之一的資料藏起來。每個分子都跟著它的分母與 unknown 數一起存,
``fwd5_sum_pct`` 存總和而非平均,pooled 平均因此可以精確重建。

為什麼是分點層級,不是 branch × stock,也不是市場層級
----------------------------------------------------
branch × stock 粒度實測 9 個 as_of 就產生 945,131 個 entity / 5.07 GB JSON,
~250 個日期的 backfill 約 140 GB,磁碟放不下。市場層級則是分點列的行加總,
需要時在讀取端 pool 即可。分點層級每個 as_of 約 821 列、200 KB,一年約 50 MB。

記憶體
------
本模組**刻意不呼叫** :func:`build_branch_point_in_time_report`:那個 builder 會
保留每一筆 episode dict(單一 as_of 約 913k 筆),形狀與 2026-08-25 在 VPS 上
造成 OOM 的那次相同(見 ``vps/README.md``、``compute_branch_stats.py`` 的註解、
``crontab.example`` 的「避免 1.7G RAM OOM」)。這裡重用它的純函式,但在 pair
迴圈內直接累加到每個分點的計數器,任何時候都不持有 episode 清單。交易列以
stock-major 的順序串流,價格一次只載入一檔個股的區間。

保留策略
--------
這張表**永不 prune**,也不在 ``prune.py`` 裡(該檔有對應註解)。

框架(docs/37 已 defer pairing 並禁止歸因)
------------------------------------------
buy 與 sell episode **各自獨立計數**:不做 buy→sell 配對、不做交易損益歸因、
不宣稱勝率。fwd5 僅為描述性觀察,不是分點實際獲利或持倉成本。
"""
from __future__ import annotations

import time
from datetime import date as date_cls
from datetime import datetime
from itertools import groupby
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text

from ..db import get_engine, init_db, upsert
from ..schema import branch_pit_stats
from .branch_point_in_time_report import (
    HIGH_SELL_MIN_PCTILE,
    LOW_BUY_MAX_PCTILE,
    PRICE_WINDOW_DAYS,
    QUAL_PCT,
    _build_universe,
    _episode_runs,
    _price_observation,
)
from .branch_point_in_time_series import plan_as_of_walk

# 定義版本:買/賣事件、20 日分位、fwd5 的定義若改變就 bump,舊列因此仍可辨識。
DEFINITIONS_VERSION = "e2-v1"

DEFAULT_WINDOW_DAYS = 60


class _BranchCounter:
    """一個分點在一個 as_of 的累加器。只有整數與一個總和,永不持有 episode。"""

    __slots__ = (
        "observed_trade_rows", "stock_count",
        "buy_episodes", "sell_episodes",
        "buy_pctile_known", "buy_pctile_unknown",
        "sell_pctile_known", "sell_pctile_unknown",
        "low_buy_count", "high_sell_count",
        "fwd5_matured", "fwd5_unknown", "fwd5_positive_count", "fwd5_sum_pct",
    )

    def __init__(self) -> None:
        for name in self.__slots__:
            setattr(self, name, 0)
        self.fwd5_sum_pct = 0.0

    def add_pair_rows(self, trade_rows: int) -> None:
        self.observed_trade_rows += trade_rows
        self.stock_count += 1  # stock-major iteration visits each pair exactly once

    def add_buy(self, observation: dict[str, Any]) -> None:
        """買方 episode。與賣方各自獨立計數,兩者之間沒有任何配對關係。"""
        self.buy_episodes += 1
        if observation["price_percentile_status"] == "known":
            self.buy_pctile_known += 1
            if observation["price_percentile_20d"] <= LOW_BUY_MAX_PCTILE:
                self.low_buy_count += 1
        else:
            self.buy_pctile_unknown += 1
        # fwd5 是描述性觀察,不是獲利歸因;未成熟就是 unknown,不是 0。
        if observation["fwd5_status"] == "matured":
            self.fwd5_matured += 1
            value = observation["fwd5_pct"]
            self.fwd5_sum_pct += value
            if value > 0:
                self.fwd5_positive_count += 1
        else:
            self.fwd5_unknown += 1

    def add_sell(self, observation: dict[str, Any]) -> None:
        """賣方 episode。fwd5 只在買方 episode 上觀察,此處不做任何出場歸因。"""
        self.sell_episodes += 1
        if observation["price_percentile_status"] == "known":
            self.sell_pctile_known += 1
            if observation["price_percentile_20d"] >= HIGH_SELL_MIN_PCTILE:
                self.high_sell_count += 1
        else:
            self.sell_pctile_unknown += 1

    def as_row(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__slots__}


def _validate_window_days(window_days: int) -> int:
    if not isinstance(window_days, int) or isinstance(window_days, bool) or window_days < 1:
        raise ValueError("window-days must be an integer >= 1")
    return window_days


def plan_as_of_window(*, trading_days: list[str], as_of: str, window_days: int) -> dict[str, Any]:
    """Resolve the trailing window for one as_of, reusing the series walk planner.

    ``as_of`` must be a market trading day.  A window with too little prior
    history is truncated and the real first market day is recorded in
    ``window_from``; it is never padded and never interpolated.
    """
    plan = plan_as_of_walk(
        trading_days=trading_days, as_of_from=as_of, as_of_to=as_of,
        step=1, window_days=window_days,
    )
    if not plan:
        raise ValueError(f"as-of must be a market trading day with price data: {as_of}")
    return plan[0]


def resolve_default_as_of() -> str:
    """最新一個「有價格資料」的市場交易日,作為省略 ``--as-of`` 時的預設。

    為什麼是 ``daily_prices`` 而不是 ``compute_branch_stats`` 用的
    ``MAX(branch_trades.date)``:本模組的 as_of 必須落在 ``daily_prices`` 的交易日
    上(見 :func:`plan_as_of_window`),分點資料的最新日期不保證有價格列,拿它當
    預設會在分點比價格早到的那幾天直接失敗。因此沿用 ``adjustments.py`` /
    ``importer.py`` 的 ``SELECT MAX(date) FROM daily_prices`` 慣例。

    沒有任何交易日就 raise:寧可讓夜間排程看到明確錯誤,也不要靜默寫 0 列。
    """
    init_db()
    with get_engine().connect() as conn:
        as_of = conn.execute(text("SELECT MAX(date) FROM daily_prices")).scalar()
    if not as_of:
        raise ValueError(
            "no market trading day with price data: daily_prices is empty; "
            "import prices first or pass --as-of explicitly"
        )
    return as_of


def _price_rows_for_stock(conn, *, stock_id: str, date_from: str, date_to: str) -> dict[str, dict[str, Any]]:
    """One stock's close/open slice, keyed by date. Dropped before the next stock."""
    return {
        row["date"]: {"open": row["open"], "close": row["close"]}
        for row in conn.execute(text("""
            SELECT date, open, close
            FROM daily_prices
            WHERE stock_id = :stock_id AND date >= :date_from AND date <= :date_to
        """), {"stock_id": stock_id, "date_from": date_from, "date_to": date_to}).mappings()
    }


def compute_branch_pit_stats(*, as_of: str, window_days: int = DEFAULT_WINDOW_DAYS) -> dict[str, Any]:
    """Compute one as_of and upsert one ``branch_pit_stats`` row per observed branch.

    Re-running the same ``(branch_name, as_of, window_market_days)`` replaces the
    row, so a backfill loop over trading days is cheap to repeat and safe to
    interrupt.  Only branches with at least one observed trade row in the window
    get a row: absence of observation is not the same fact as a zero count.
    """
    window_days = _validate_window_days(window_days)
    try:
        as_of = date_cls.fromisoformat(as_of).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"as-of must be YYYY-MM-DD: {as_of!r}") from exc
    started = time.monotonic()
    init_db()
    engine = get_engine()

    # A second connection keeps the streamed trade cursor and the per-stock
    # price lookups independent; neither is ever buffered whole into memory.
    with engine.connect() as conn, engine.connect() as price_conn:
        trading_days = [row[0] for row in conn.execute(text("""
            SELECT DISTINCT date FROM daily_prices WHERE date <= :as_of ORDER BY date
        """), {"as_of": as_of}).fetchall()]
        plan = plan_as_of_window(trading_days=trading_days, as_of=as_of, window_days=window_days)
        window_from = plan["window_from"]
        market_index = {day: index for index, day in enumerate(trading_days)}
        # Percentiles look back 19 market days before the first event day; no
        # earlier price can ever be read, so no earlier price is loaded.
        price_from = trading_days[max(0, market_index[window_from] - (PRICE_WINDOW_DAYS - 1))]

        universe, _unknown_manual_timestamp_names = _build_universe(conn, as_of)

        counters: dict[str, _BranchCounter] = {}
        # stock-major so each stock's price slice is loaded once and released;
        # branch counters are order-independent, so this costs nothing.
        trade_rows = conn.execution_options(yield_per=2000).execute(text("""
            SELECT b.stock_id, b.branch_name, b.date, b.net_lots, b.pct
            FROM branch_trades b
            JOIN stocks s ON s.id = b.stock_id
            WHERE s.type = 'stock'
              AND b.date >= :date_from
              AND b.date <= :as_of
            ORDER BY b.stock_id, b.branch_name, b.date
        """), {"date_from": window_from, "as_of": as_of}).mappings()

        for stock_id, stock_group in groupby(trade_rows, key=lambda row: row["stock_id"]):
            row_by_date: dict[str, dict[str, Any]] | None = None
            for branch_name, pair_group in groupby(stock_group, key=lambda row: row["branch_name"]):
                if branch_name not in universe:
                    continue
                buy_dates: list[str] = []
                sell_dates: list[str] = []
                observed = 0
                for row in pair_group:
                    observed += 1
                    net_lots, pct = row["net_lots"], row["pct"]
                    if net_lots is None or pct is None:
                        continue
                    if net_lots > 0 and pct >= QUAL_PCT:
                        buy_dates.append(row["date"])
                    elif net_lots < 0 and abs(pct) >= QUAL_PCT:
                        sell_dates.append(row["date"])

                counter = counters.setdefault(branch_name, _BranchCounter())
                counter.add_pair_rows(observed)
                if not buy_dates and not sell_dates:
                    continue
                if row_by_date is None:
                    row_by_date = _price_rows_for_stock(
                        price_conn, stock_id=stock_id, date_from=price_from, date_to=as_of,
                    )
                for dates, add in ((buy_dates, counter.add_buy), (sell_dates, counter.add_sell)):
                    for start_date, _end_date, _episode_dates in _episode_runs(dates, market_index):
                        add(_price_observation(
                            event_date=start_date,
                            market_index=market_index,
                            market_days=trading_days,
                            row_by_date=row_by_date,
                        ))

    computed_at = datetime.now(ZoneInfo("Asia/Taipei")).isoformat(timespec="seconds")
    rows = [
        {
            "branch_name": branch_name,
            "as_of": as_of,
            "window_market_days": plan["window_market_days"],
            "window_from": window_from,
            "definitions_version": DEFINITIONS_VERSION,
            "computed_at": computed_at,
            **counter.as_row(),
        }
        for branch_name, counter in sorted(counters.items())
    ]
    with engine.begin() as conn:
        upsert(conn, branch_pit_stats, rows)

    return {
        "as_of": as_of,
        "window_from": window_from,
        "window_market_days": plan["window_market_days"],
        "window_market_days_requested": window_days,
        "window_truncated": plan["window_truncated"],
        "definitions_version": DEFINITIONS_VERSION,
        "computed_at": computed_at,
        "branches_written": len(rows),
        "elapsed_sec": round(time.monotonic() - started, 3),
    }
