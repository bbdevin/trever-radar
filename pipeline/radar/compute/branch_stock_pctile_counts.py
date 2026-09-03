"""「分點 × 個股」的買點／賣點價格分位計數(只留最新一份快照)。

這是什麼
--------
對每一對(分點, 個股),在一段 trailing window 內數四個數字:有幾次買進
episode 的 20 日收盤分位是可知的、其中幾次落在低檔(``low_buy``);有幾次賣出
episode 的分位可知、其中幾次落在高檔(``high_sell``)。分位不可知的 episode
兩側各自另外計數,**永遠不當成「沒做到」**。

定義本身不在這裡重述:``low_buy``/``high_sell``/事件/episode 全部沿用
:mod:`radar.compute.branch_point_in_time_report` 的常數與純函式。

⚠️ 為什麼只有計數,沒有旗標、沒有分數、沒有排名
-----------------------------------------------
2026-09-03 的唯讀量測(``docs/STATUS.md``)結論有兩半,兩半都必須看:

* **傾向為真**:以樣本外時間切分,選出來的 pair 在評估半段仍以 **2.3–2.9×**
  勝過「該股自身 pooled 率」這個 null,而規模配對安慰劑只有 1.12–1.24×(貼著
  機率)。所以篩到的不是曝光度或部位規模。
* **但標籤不可重現**:同一條規則隔一個年度重新標記到同一對的比率只有
  **1.6%–5.4%**。也就是說「某分點**總是**在這檔股票低買高賣」這句話,資料
  並不支持;今年合格的那批,明年幾乎是完全不同的一群。

因此本模組刻意只落地計數與分母,不產生任何布林欄位、分數或名次,也絕不
宣稱某個分點「是」什麼。要不要相信,由讀的人看著分母自己判斷。

⚠️ 兩側基準率不對稱,所以任何比率都必須有尺
--------------------------------------------
全市場 pooled 低買 **53.35%**、高賣 **35.35%**(20 日收盤分位在本市場偏底部)。
一個 60% 的低買率幾乎就是基準值,一個 60% 的高賣率卻是大幅超出。所以每一列
都同時存下**該檔股票自身跨所有分點 pooled 的同一組分子與分母**——那是這一對
唯一有意義的比較基準。少了它,列裡的數字沒辦法被正確地讀。

⚠️ 次日回吐的計數為什麼算在這裡,而不是從 ``branch_stock_stats`` join 過來
------------------------------------------------------------------------
``branch_stock_stats.daytrade_obs`` / ``daytrade_paybacks`` 用的是**全部可得歷史**;
本表的分位計數用的是 490 個交易日的 trailing window。把兩者 join 到同一個面板,
會讓兩個期間不同的數字並排在同一個標題下——這種安靜的錯配正是這個 codebase
一再吃虧的地方。因此這裡在同一次串流中、用**同一個窗口**重算一次,與分位計數
放在同一列。定義本身(``DAYTRADE_PAYBACK``/``DAYTRADE_RATE``/``DAYTRADE_MIN_OBS``
與觀察建構)全部從 :mod:`radar.compute.compute_branch_stats` import,不重寫。

同樣只存計數:觀察數低於 ``DAYTRADE_MIN_OBS`` 是**無法判定**,不是「不會翻單」。
門檻留在讀取端(export 會把它一起帶出去),資料裡不燒任何判定。

不是損益
--------
全部是**進出場價格分位**。``docs/37`` 已 defer 買賣配對並禁止獲利歸因,因此
買方與賣方 episode 各自獨立計數,兩者之間沒有任何配對關係,也沒有任何欄位
是勝率或報酬。

記憶體
------
本模組**刻意不呼叫** :func:`build_branch_point_in_time_report`:那個 builder 會
保留每一筆 episode dict(單一 as_of 約 913k 筆),形狀與 2026-08-25 在 VPS 上
造成 1.7GB OOM 的那次相同。這裡沿用
:mod:`radar.compute.branch_point_in_time_persist` 的做法:交易列以 stock-major
的順序 ``yield_per`` 串流,價格一次只載入一檔個股的區間,任何時候都不持有
episode 清單。額外的限制是輸出本身有約 90 萬列,所以**輸出也不整批堆在記憶體
裡**:一檔個股算完就把那一檔的列寫出去(見 :func:`compute_branch_stock_pctile_counts`)。
"""
from __future__ import annotations

import time
from datetime import date as date_cls
from datetime import datetime
from itertools import groupby
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text

from ..db import get_engine, init_db
from ..schema import branch_stock_pctile_counts
from .branch_point_in_time_persist import (
    _price_rows_for_stock,
    _validate_window_days,
    plan_as_of_window,
    resolve_default_as_of,  # noqa: F401  (re-exported for the CLI)
)
from .branch_point_in_time_report import (
    HIGH_SELL_MIN_PCTILE,
    LOW_BUY_MAX_PCTILE,
    PRICE_WINDOW_DAYS,
    QUAL_PCT,
    _build_universe,
    _episode_runs,
    _price_observation,
)
from .compute_branch_stats import (
    DAYTRADE_MIN_OBS,  # noqa: F401  (re-exported: 讀取端的門檻只有這一份)
    daytrade_counts,
    daytrade_observations,
)

# 定義版本:買/賣事件、20 日分位門檻若改變就 bump,舊列因此仍可辨識。
DEFINITIONS_VERSION = "e2-pair-v1"

# 490 個市場交易日:與 backfill 目標、以及 2026-09-03 那次量測的窗口一致。
DEFAULT_WINDOW_DAYS = 490

# 每累積這麼多列就寫出一次,避免把 ~90 萬個 dict 一次堆在記憶體裡。
WRITE_CHUNK_ROWS = 2000


class _PairCounter:
    """一對(分點, 個股)的累加器。只有八個整數,永不持有 episode。"""

    __slots__ = (
        "buy_pctile_known", "buy_pctile_unknown", "low_buy_count",
        "sell_pctile_known", "sell_pctile_unknown", "high_sell_count",
        "daytrade_obs", "daytrade_paybacks",
    )

    def __init__(self) -> None:
        for name in self.__slots__:
            setattr(self, name, 0)

    def add_daytrade(self, obs: int, paybacks: int) -> None:
        """次日回吐的原始計數。分子與分母都存,**不存比率也不存旗標**。

        觀察數低於 ``DAYTRADE_MIN_OBS`` 代表「無法判定」,不是「沒有隔日翻單」。
        把門檻套在這裡會把那個區別燒進資料;因此門檻留在讀取端,這裡只存數字。
        """
        self.daytrade_obs += obs
        self.daytrade_paybacks += paybacks

    def add_buy(self, observation: dict[str, Any]) -> None:
        """買方 episode。與賣方各自獨立計數,兩者之間沒有任何配對關係。"""
        if observation["price_percentile_status"] == "known":
            self.buy_pctile_known += 1
            if observation["price_percentile_20d"] <= LOW_BUY_MAX_PCTILE:
                self.low_buy_count += 1
        else:
            # 分位不可知就是不可知,不是「買在高點」。
            self.buy_pctile_unknown += 1

    def add_sell(self, observation: dict[str, Any]) -> None:
        """賣方 episode。此處不做任何出場歸因,也不與買方配對。"""
        if observation["price_percentile_status"] == "known":
            self.sell_pctile_known += 1
            if observation["price_percentile_20d"] >= HIGH_SELL_MIN_PCTILE:
                self.high_sell_count += 1
        else:
            self.sell_pctile_unknown += 1

    @property
    def episodes(self) -> int:
        return (
            self.buy_pctile_known + self.buy_pctile_unknown
            + self.sell_pctile_known + self.sell_pctile_unknown
        )

    def as_row(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in self.__slots__}


def compute_branch_stock_pctile_counts(
    *, as_of: str, window_days: int = DEFAULT_WINDOW_DAYS,
) -> dict[str, Any]:
    """重算並**整份取代** ``branch_stock_pctile_counts``。

    只保留最新一份快照:每次執行都先清空整張表,再寫入這一輪的列。跨 as_of 的
    point-in-time 序列實測約需 140 GB,已被否決;這張表刻意不是那個東西。

    清空與寫入在**同一個交易**裡完成,所以中途失敗會整份 rollback,讀取端看到
    的仍然是上一份完整快照,而不是一份缺了一半個股的殘檔。SQLite 走 WAL,
    這段期間讀取不受阻;唯一的另一個寫入者(回補容器)由呼叫端的
    ``safe-branch-stats.sh`` 先行 pause。

    只有「window 內至少有一次合格 episode」的 pair 會有列。沒有觀察到,和
    觀察到 0 次,不是同一個事實。
    """
    window_days = _validate_window_days(window_days)
    try:
        as_of = date_cls.fromisoformat(as_of).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"as-of must be YYYY-MM-DD: {as_of!r}") from exc
    started = time.monotonic()
    init_db()
    engine = get_engine()
    computed_at = datetime.now(ZoneInfo("Asia/Taipei")).isoformat(timespec="seconds")

    pairs_written = 0
    stocks_written = 0
    # 三條連線各司其職:串流交易列、逐檔取價、以及一個從頭開到尾的寫入交易。
    with engine.connect() as conn, engine.connect() as price_conn, engine.begin() as write_conn:
        trading_days = [row[0] for row in conn.execute(text("""
            SELECT DISTINCT date FROM daily_prices WHERE date <= :as_of ORDER BY date
        """), {"as_of": as_of}).fetchall()]
        plan = plan_as_of_window(trading_days=trading_days, as_of=as_of, window_days=window_days)
        window_from = plan["window_from"]
        market_index = {day: index for index, day in enumerate(trading_days)}
        # 分位只回看事件日前 19 個交易日,更早的價格永遠讀不到,所以也不載入。
        price_from = trading_days[max(0, market_index[window_from] - (PRICE_WINDOW_DAYS - 1))]

        universe, _unknown_manual_timestamp_names = _build_universe(conn, as_of)

        base_row = {
            "as_of": as_of,
            "window_market_days": plan["window_market_days"],
            "window_from": window_from,
            "definitions_version": DEFINITIONS_VERSION,
            "computed_at": computed_at,
        }
        write_conn.execute(branch_stock_pctile_counts.delete())
        buffer: list[dict[str, Any]] = []

        def flush(force: bool = False) -> None:
            if buffer and (force or len(buffer) >= WRITE_CHUNK_ROWS):
                write_conn.execute(branch_stock_pctile_counts.insert(), buffer)
                buffer.clear()

        # stock-major:每檔個股的價格切片只載入一次就釋放,而且一檔算完就能
        # 算出該檔的 pooled 基準(那把尺),當場寫出、當場丟掉。
        trade_rows = conn.execution_options(yield_per=2000).execute(text("""
            SELECT b.stock_id, b.branch_name, b.date, b.net_lots, b.sell_lots, b.pct
            FROM branch_trades b
            JOIN stocks s ON s.id = b.stock_id
            WHERE s.type = 'stock'
              AND b.date >= :date_from
              AND b.date <= :as_of
            ORDER BY b.stock_id, b.branch_name, b.date
        """), {"date_from": window_from, "as_of": as_of}).mappings()

        for stock_id, stock_group in groupby(trade_rows, key=lambda row: row["stock_id"]):
            row_by_date: dict[str, dict[str, Any]] | None = None
            counters: dict[str, _PairCounter] = {}
            for branch_name, pair_group in groupby(stock_group, key=lambda row: row["branch_name"]):
                if branch_name not in universe:
                    continue
                buy_dates: list[str] = []
                sell_dates: list[str] = []
                # 這一對在窗口內的每一列(不只合格日):次日回吐要查的是次一交易日
                # 的 sell_lots,那一天本身不必是事件。只活到這一對算完為止。
                datemap: dict[str, dict[str, Any]] = {}
                for row in pair_group:
                    net_lots, pct = row["net_lots"], row["pct"]
                    datemap[row["date"]] = {"net": net_lots, "sell": row["sell_lots"]}
                    if net_lots is None or pct is None:
                        continue
                    if net_lots > 0 and pct >= QUAL_PCT:
                        buy_dates.append(row["date"])
                    elif net_lots < 0 and abs(pct) >= QUAL_PCT:
                        sell_dates.append(row["date"])
                if not buy_dates and not sell_dates:
                    continue
                if row_by_date is None:
                    row_by_date = _price_rows_for_stock(
                        price_conn, stock_id=stock_id, date_from=price_from, date_to=as_of,
                    )
                counter = counters.setdefault(branch_name, _PairCounter())
                # 次日回吐:與上面的分位計數走**同一個窗口**、同一把市場交易日曆。
                # 觀察建構本身不在這裡重寫,直接用 compute_branch_stats 的那一份;
                # 那張表算的是全期,這裡算的是 window,兩者因此永遠不能併排比較,
                # 也正是這幾個計數不從 branch_stock_stats join 過來的理由。
                # 注意日曆:那邊用該股自身有收盤價的交易日,這裡用市場交易日曆
                # (與 _episode_runs 同一把),停牌股的「次一交易日」可能不同。
                counter.add_daytrade(*daytrade_counts(daytrade_observations(
                    buy_dates, datemap, trading_days, market_index,
                )))
                for dates, add in ((buy_dates, counter.add_buy), (sell_dates, counter.add_sell)):
                    for start_date, _end_date, _episode_dates in _episode_runs(dates, market_index):
                        add(_price_observation(
                            event_date=start_date,
                            market_index=market_index,
                            market_days=trading_days,
                            row_by_date=row_by_date,
                        ))

            if not counters:
                continue
            # 該檔股票自身的 pooled 計數 = 這一檔所有分點的行加總。它是尺:
            # 買側與賣側的基準率差了將近 20 個百分點,沒有它就讀不出一個比率
            # 到底算高還是算普通。
            stock_totals = {
                "stock_buy_pctile_known": sum(c.buy_pctile_known for c in counters.values()),
                "stock_low_buy_count": sum(c.low_buy_count for c in counters.values()),
                "stock_sell_pctile_known": sum(c.sell_pctile_known for c in counters.values()),
                "stock_high_sell_count": sum(c.high_sell_count for c in counters.values()),
                "stock_daytrade_obs": sum(c.daytrade_obs for c in counters.values()),
                "stock_daytrade_paybacks": sum(c.daytrade_paybacks for c in counters.values()),
            }
            for branch_name, counter in sorted(counters.items()):
                buffer.append({
                    "branch_name": branch_name,
                    "stock_id": stock_id,
                    **base_row,
                    **counter.as_row(),
                    **stock_totals,
                })
                pairs_written += 1
            stocks_written += 1
            flush()
        flush(force=True)

    return {
        "as_of": as_of,
        "window_from": window_from,
        "window_market_days": plan["window_market_days"],
        "window_market_days_requested": window_days,
        "window_truncated": plan["window_truncated"],
        "definitions_version": DEFINITIONS_VERSION,
        "computed_at": computed_at,
        "pairs_written": pairs_written,
        "stocks_written": stocks_written,
        "elapsed_sec": round(time.monotonic() - started, 3),
    }
