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
2026-09-08 在修好還原因子的資料上重跑的方向 battery(``docs/STATUS.md``)結論
有兩半,兩半都必須看:

* **群體層級的傾向為真**:以樣本外時間切分,被標記的 pair 在評估半段以
  **obs/exp 2.40** 勝過「該股自身 pooled 率」這個 null,而**張數配對**安慰劑
  只有 **0.91**(比機率還低一點),兩者相距約 6.8 個 sigma。所以篩到的不是
  曝光度或部位規模。
* **但標籤不可重現**:嚴格旗標(兩側各 ≥10 次已知分位、命中率各 ≥0.7)在評估
  半段只被 **2.0%** 的 pair 重新賺回來。也就是說「某分點**總是**在這檔股票
  低買高賣」這句話,資料並不支持。

這兩個數字不衝突,因為它們問的不是同一件事,而 2.0% **不是**「這個傾向只延續
2% 的時間」——嚴格旗標要求兩側各 10 次已知分位,一個在評估半段單純交易得比較
少的分點,不論行為如何都不可能重新達標,所以那個比率把交易量混進了持續性。
真正回答「這份紀錄有沒有帶到下一段」的是存活 pair 的 exceeds-both:**57.4%,
對上約 22–24% 的機率值**。

因此本模組刻意只落地計數與分母,不產生任何布林欄位、分數或名次,也絕不
宣稱某個分點「是」什麼:2% 禁止任何徽章,57 對 24 則足以支持把計數呈現出來,
要不要相信,由讀的人看著分母自己判斷。

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

張數(2026-10-02 起)
--------------------
次數把「低檔一口氣買 836 張」與「低檔買 5 張」記成同樣的一次。因此每個分類
旁邊再存一份**張數**:一個 episode 的張數 = 該 episode 每個合格日 ``|net_lots|``
的加總(見 :func:`episode_lots`),歸到哪一格完全跟著該 episode 的次數分類走
(``low_buy_count`` ↔ ``low_buy_lots``、``buy_pctile_known`` ↔ ``buy_lots_known``);
分位不可知的 episode 張數同樣不進分母。該股 pooled 的張數一樣存一份當尺。

兩派(2026-10-02 起)
--------------------
* **短線派**(既有欄位,無後綴):事件日收盤在**近 20 個市場交易日**收盤區間的
  位置。定義一個字都沒改。次日回吐只屬於這一派。
* **長線派**(欄位後綴 ``_120d``):**同一批 episode**、同一個 ≤40%/≥60% 門檻、
  同一套張數算法,只把區間換成**近 120 個市場交易日**(約半年)。事件日之前不足
  119 個市場交易日、或區間內任何一天缺收盤價 → 不可知(不會改用較短的區間)。

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
from collections import deque
from datetime import date as date_cls
from datetime import datetime
from itertools import groupby
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text

from ..db import get_engine, init_db, insert_many
from ..schema import branch_stock_pctile_counts
from .branch_same_day import merge_by_date
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
# v2(2026-09-04):價格改用 adj_factor 還原。兩張表共用
# :func:`radar.compute.branch_point_in_time_persist._price_rows_for_stock`,
# 所以這裡與 ``branch_point_in_time_persist.DEFINITIONS_VERSION`` 必須同時 bump。
DEFINITIONS_VERSION = "e2-pair-v2"

# 490 個市場交易日:與 backfill 目標、以及 2026-09-03 那次量測的窗口一致。
DEFAULT_WINDOW_DAYS = 490

# 每累積這麼多列就寫出一次,避免把 ~90 萬個 dict 一次堆在記憶體裡。
WRITE_CHUNK_ROWS = 2000


# 長線派:同一套 episode、同一個「低 40%／高 40%」規則,只把收盤區間從近 20 個
# 交易日換成近 120 個交易日(約半年)。20 日那一套(短線派)完全不動。
LONG_PRICE_WINDOW_DAYS = 120

# 兩派的欄位後綴。短線派沿用既有欄名(無後綴),長線派一律加 ``_120d``。
CAMP_SUFFIXES = ("", "_120d")

# 每一派、每一對各自的計數與張數欄位(加上 CAMP_SUFFIXES 的後綴即欄名)。
_PAIR_CAMP_FIELDS = (
    "buy_pctile_known", "buy_pctile_unknown", "low_buy_count",
    "sell_pctile_known", "sell_pctile_unknown", "high_sell_count",
    "buy_lots_known", "low_buy_lots", "sell_lots_known", "high_sell_lots",
)


def episode_lots(episode_dates: list[str], datemap: dict[str, dict[str, Any]]) -> int:
    """一個 episode 的張數 = 該 episode 每一個合格日 ``|net_lots|`` 的加總。

    episode 由 :func:`_episode_runs` 把**相鄰市場交易日**的合格日併成一段,分位
    只看起始日;張數則把這一段裡每個合格日的淨買(或淨賣)張數都算進去——
    2025-04-08/09 連兩天的 836 張是**一個** episode、836 張,不是兩筆。
    非合格日(``|pct| < QUAL_PCT`` 的同向小量)不在 episode 裡,也不算張數。
    """
    return int(sum(abs(datemap[day]["net"] or 0) for day in episode_dates))


def rolling_close_ranges(
    closes: list[float | None], span: int,
) -> list[tuple[float, float] | None]:
    """每個位置 i 的 ``closes[i-span+1 .. i]`` 收盤 (min, max);不足 span 筆或
    區間內有任何缺價時為 None。

    與 :func:`radar.compute.branch_point_in_time_report._close_range_percentile`
    同一個規則(缺任何一天的收盤 = 不可知),只是一檔個股算一次 O(n),而不是每個
    episode 重掃 120 天。"""
    out: list[tuple[float, float] | None] = [None] * len(closes)
    lows: deque[int] = deque()
    highs: deque[int] = deque()
    last_missing = -1
    for i, close in enumerate(closes):
        if close is None:
            last_missing = i
            lows.clear()
            highs.clear()
            continue
        while lows and closes[lows[-1]] >= close:
            lows.pop()
        lows.append(i)
        while highs and closes[highs[-1]] <= close:
            highs.pop()
        highs.append(i)
        start = i - span + 1
        while lows[0] < start:
            lows.popleft()
        while highs[0] < start:
            highs.popleft()
        if start >= 0 and last_missing < start:
            out[i] = (closes[lows[0]], closes[highs[0]])
    return out


def long_window_percentile(
    *,
    event_date: str,
    market_index: dict[str, int],
    price_base_index: int,
    closes: list[float | None],
    ranges: list[tuple[float, float] | None],
) -> float | None:
    """長線派的事件日分位;不可知時回 None。

    ``closes``/``ranges`` 以 ``price_base_index`` 為第 0 個市場交易日對齊。事件日
    之前不足 119 個市場交易日 → 不可知(**不會**退而用較短的區間算)。極值相同
    (區間零寬)與事件日缺價同樣不可知,與 20 日那一套一致。
    """
    index = market_index.get(event_date)
    if index is None or index - (LONG_PRICE_WINDOW_DAYS - 1) < 0:
        return None
    pos = index - price_base_index
    if pos < 0 or pos >= len(closes):
        return None
    close, bounds = closes[pos], ranges[pos]
    if close is None or bounds is None:
        return None
    low, high = bounds
    if high == low:
        return None
    return round((close - low) / (high - low), 6)


class _PairCounter:
    """一對(分點, 個股)的累加器。只有整數,永不持有 episode。

    張數欄位與次數欄位用**同一個分類**:同一個 episode 若算進 ``low_buy_count``,
    它的張數就算進 ``low_buy_lots``;分位不可知的 episode 兩者都不進 known。
    短線派(20 日)與長線派(120 日,欄位後綴 ``_120d``)各自一套,同一批 episode。
    """

    __slots__ = (
        "daytrade_obs", "daytrade_paybacks",
        *(f"{name}{suffix}" for suffix in CAMP_SUFFIXES for name in _PAIR_CAMP_FIELDS),
    )

    def __init__(self) -> None:
        for name in self.__slots__:
            setattr(self, name, 0)

    def add_daytrade(self, obs: int, paybacks: int) -> None:
        """次日回吐的原始計數。分子與分母都存,**不存比率也不存旗標**。

        觀察數低於 ``DAYTRADE_MIN_OBS`` 代表「無法判定」,不是「沒有隔日翻單」。
        把門檻套在這裡會把那個區別燒進資料;因此門檻留在讀取端,這裡只存數字。
        只屬於短線派(20 日窗口那一組),長線派沒有這一列。
        """
        self.daytrade_obs += obs
        self.daytrade_paybacks += paybacks

    def _bump(self, name: str, amount: int) -> None:
        setattr(self, name, getattr(self, name) + amount)

    def add_buy(self, pctile: float | None, lots: int, suffix: str = "") -> None:
        """買方 episode。與賣方各自獨立計數,兩者之間沒有任何配對關係。

        ``pctile`` 為 None = 分位不可知:不是「買在高點」,張數同樣不進分母。
        """
        if pctile is None:
            self._bump(f"buy_pctile_unknown{suffix}", 1)
            return
        self._bump(f"buy_pctile_known{suffix}", 1)
        self._bump(f"buy_lots_known{suffix}", lots)
        if pctile <= LOW_BUY_MAX_PCTILE:
            self._bump(f"low_buy_count{suffix}", 1)
            self._bump(f"low_buy_lots{suffix}", lots)

    def add_sell(self, pctile: float | None, lots: int, suffix: str = "") -> None:
        """賣方 episode。此處不做任何出場歸因,也不與買方配對。"""
        if pctile is None:
            self._bump(f"sell_pctile_unknown{suffix}", 1)
            return
        self._bump(f"sell_pctile_known{suffix}", 1)
        self._bump(f"sell_lots_known{suffix}", lots)
        if pctile >= HIGH_SELL_MIN_PCTILE:
            self._bump(f"high_sell_count{suffix}", 1)
            self._bump(f"high_sell_lots{suffix}", lots)

    @property
    def episodes(self) -> int:
        return (
            self.buy_pctile_known + self.buy_pctile_unknown
            + self.sell_pctile_known + self.sell_pctile_unknown
        )

    def as_row(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in self.__slots__}


# 該檔股票 pooled 的欄位:(輸出欄名, 分點層級欄名)。兩派、次數與張數。
_STOCK_TOTAL_FIELDS = tuple(
    (f"stock_{name}{suffix}", f"{name}{suffix}")
    for suffix in CAMP_SUFFIXES
    for name in (
        "buy_pctile_known", "low_buy_count", "sell_pctile_known", "high_sell_count",
        "buy_lots_known", "low_buy_lots", "sell_lots_known", "high_sell_lots",
    )
) + (
    ("stock_daytrade_obs", "daytrade_obs"),
    ("stock_daytrade_paybacks", "daytrade_paybacks"),
)


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
        # 分位只回看事件日前 19(短線派)／119(長線派)個交易日,更早的價格
        # 永遠讀不到,所以也不載入。20 日分位照樣只讀它自己那 20 天,多載入的
        # 舊價格不會改變它。
        lookback = max(PRICE_WINDOW_DAYS, LONG_PRICE_WINDOW_DAYS) - 1
        price_base_index = max(0, market_index[window_from] - lookback)
        price_from = trading_days[price_base_index]
        price_days = trading_days[price_base_index:]

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
                insert_many(write_conn, branch_stock_pctile_counts, buffer)
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
            -- 同名同日多列在 Python 端加總(順序無關);branch_key 只是讓串流順序明確(docs/43)。
            ORDER BY b.stock_id, b.branch_name, b.date, b.branch_key
        """), {"date_from": window_from, "as_of": as_of}).mappings()

        for stock_id, stock_group in groupby(trade_rows, key=lambda row: row["stock_id"]):
            row_by_date: dict[str, dict[str, Any]] | None = None
            long_closes: list[float | None] = []
            long_ranges: list[tuple[float, float] | None] = []
            counters: dict[str, _PairCounter] = {}
            for branch_name, pair_group in groupby(stock_group, key=lambda row: row["branch_name"]):
                if branch_name not in universe:
                    continue
                buy_dates: list[str] = []
                sell_dates: list[str] = []
                # 這一對在窗口內的每一列(不只合格日):次日回吐要查的是次一交易日
                # 的 sell_lots,那一天本身不必是事件。只活到這一對算完為止。
                # 同名同日多個 branch_key → 加總(branch_same_day,docs/43);以前
                # datemap 留最後一列、合格日每列各判一次,結果跟著讀取順序走。
                merged = merge_by_date(pair_group, ("net_lots", "sell_lots", "pct"))
                datemap: dict[str, dict[str, Any]] = {}
                for day, row in merged.items():
                    net_lots, pct = row["net_lots"], row["pct"]
                    datemap[day] = {"net": net_lots, "sell": row["sell_lots"]}
                    if net_lots is None or pct is None:
                        continue
                    if net_lots > 0 and pct >= QUAL_PCT:
                        buy_dates.append(day)
                    elif net_lots < 0 and abs(pct) >= QUAL_PCT:
                        sell_dates.append(day)
                if not buy_dates and not sell_dates:
                    continue
                if row_by_date is None:
                    row_by_date = _price_rows_for_stock(
                        price_conn, stock_id=stock_id, date_from=price_from, date_to=as_of,
                    )
                    # 長線派的 120 日收盤區間,一檔個股算一次。對齊市場交易日曆:
                    # 該股沒有收盤價的市場交易日是缺價,區間因此不可知。
                    long_closes = [row_by_date.get(day, {}).get("close") for day in price_days]
                    long_ranges = rolling_close_ranges(long_closes, LONG_PRICE_WINDOW_DAYS)
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
                    for start_date, _end_date, episode_dates in _episode_runs(dates, market_index):
                        lots = episode_lots(episode_dates, datemap)
                        short = _price_observation(
                            event_date=start_date,
                            market_index=market_index,
                            market_days=trading_days,
                            row_by_date=row_by_date,
                        )
                        add(
                            short["price_percentile_20d"]
                            if short["price_percentile_status"] == "known" else None,
                            lots,
                        )
                        add(long_window_percentile(
                            event_date=start_date,
                            market_index=market_index,
                            price_base_index=price_base_index,
                            closes=long_closes,
                            ranges=long_ranges,
                        ), lots, "_120d")

            if not counters:
                continue
            # 該檔股票自身的 pooled 計數 = 這一檔所有分點的行加總。它是尺:
            # 買側與賣側的基準率差了將近 20 個百分點,沒有它就讀不出一個比率
            # 到底算高還是算普通。張數版同理:分點的張數比率要對照的是這一檔
            # 所有分點 pooled 的張數比率,不是次數比率;兩派各自一把尺。
            stock_totals = {
                out: sum(getattr(c, field) for c in counters.values())
                for out, field in _STOCK_TOTAL_FIELDS
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
