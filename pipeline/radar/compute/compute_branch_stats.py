"""分點可信度排行榜(docs/13 §2b/§3a/§3b)。

事件 = 單股單日淨買超 ≥ 該股成交值 1%(net_lots>0 且 pct>=1.0),連續交易日合併,
事件日取連續段第一天(訊號在第一天盤後可觀察,T+1 進場才誠實)。

純函式 merge_consecutive_events / daytrade_flag / price_percentile / recency_factor /
credibility_score 可單元測試;compute_all() 負責取數、彙總與落地。

級距說明:score 各項的門檻(勝率 40→70、報酬 0→5%、金額 1e7→1e9、買點分位、近效性)
皆為 docs/04/13 的 V1 起始值,待績效資料累積後再校準。
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date as date_cls
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text

from .. import config, schema
from ..db import get_engine, init_db, upsert
from .performance import forward_returns

# 事件資格
QUAL_PCT = 1.0                 # 淨買超 ≥ 成交值 1%

# 隔日沖判定(分兩層:pair =(分點,個股),branch = 跨股彙總)
#
# 語意警告:一筆 pair 觀察只有在「次日該分點出現在該股當日前 15 大賣超」時才算回吐。
# 真正的隔日沖desk幾乎全數當沖出場,但免費資料每日只有前 15 大,多數出場看不見,
# 因此連台股最知名的隔日沖分點實測也只到 0.315,而非接近 1.0。
# 所以 branch 層的 DAYTRADE_PAIR_SHARE 讀作:
#   「可判定的(分點×個股)配對中,在每日前 15 大切片內看得到隔日翻單的比例」。
# 絕不可寫成「多數情況下隔日出場」之類的文案。
DAYTRADE_PAYBACK = 0.7         # 次日回吐 ≥ 當日淨買 70% 視為回吐
DAYTRADE_RATE = 0.6            # pair 層:回吐比率 ≥ 60% → 該配對標記隔日沖
DAYTRADE_MIN_OBS = 8           # pair 層:合併連續段「之前」的觀察數 < 8 不判定(換取單一配對的雜訊過濾)
DAYTRADE_MIN_PAIRS = 20        # branch 層:可判定配對 < 20 不判定(換取分點層比例的分母穩定度)
DAYTRADE_PAIR_SHARE = 0.20     # branch 層:被標記配對佔可判定配對 ≥ 20% → 隔日沖分點(換取在前 15 大切片下仍可辨識的門檻)

# 排行 / 追蹤門檻(§2b/§5)
MIN_RANK_EVENTS = 5           # 入榜門檻:pooled 事件數 ≥ 5(前端 <10 顯示樣本不足)
AUTO_IN_EVENTS_2Y = 10        # 自動入選:近 2 年事件 ≥ 10
AUTO_IN_SCORE = 70            # 自動入選:可信度 ≥ 70
AUTO_IN_EVENTS_90 = 2         # 自動入選:近 90 日事件 ≥ 2
AUTO_OUT_SCORE = 50           # 自動移出:可信度 < 50
AUTO_OUT_EVENTS_90 = 2        # 自動移出:近 90 日事件 < 2


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def merge_consecutive_events(qual_dates: list[str], date_index: dict[str, int]) -> list[str]:
    """把同一 (分點, 個股) 的資格日,連續交易日合併為一個事件。

    qual_dates 需已排序(升序);date_index 為該股交易日 → 序號(以 daily_prices
    日期序列判定連續)。回傳每段連續資格日的第一天。資格日不在交易日曆中(理論上
    不應發生)時,獨立成一事件。
    """
    events: list[str] = []
    prev_idx: int | None = None
    for d in qual_dates:
        idx = date_index.get(d)
        if idx is None:
            events.append(d)
            prev_idx = None
            continue
        if prev_idx is not None and idx == prev_idx + 1:
            prev_idx = idx          # 與前一資格日相鄰 → 同一事件,不新增
            continue
        events.append(d)
        prev_idx = idx
    return events


def daytrade_observations(qual_dates: list[str], datemap: dict[str, dict],
                          trading_dates: list[str],
                          date_index: dict[str, int]) -> list[tuple[float, float]]:
    """把每個資格買超日配上「次一交易日同分點的賣出張數」,回傳 (淨買張, 次日賣出張)。

    次日該分點無紀錄(未進該股當日前 15 大賣超)→ sell=0,視為未回吐;這是免費
    資料每日只有前 15 大的誠實限制,不是「確定沒賣」。資格日不在日曆上、或已經
    是日曆最後一天 → 同樣是 0(看不到次日,不是看到沒回吐)。

    日曆由呼叫端給:``compute_all`` 給該股自身有收盤價的交易日;pair 粒度的
    ``branch_stock_pctile_counts`` 給它自己那把市場交易日曆(與它切 episode 的
    同一把),兩邊因此各自窗口一致。這個函式是**唯一**一份觀察建構,任何第二份
    複製都會與這裡漂移。
    """
    observations: list[tuple[float, float]] = []
    for qd in qual_dates:
        net = (datemap.get(qd) or {}).get("net")
        idx = date_index.get(qd)
        next_sell = 0
        if idx is not None and idx + 1 < len(trading_dates):
            nrow = datemap.get(trading_dates[idx + 1])
            next_sell = (nrow["sell"] if nrow else 0) or 0
        observations.append((net, next_sell))
    return observations


def daytrade_counts(observations: list[tuple[float, float]]) -> tuple[int, int]:
    """(可判定觀察數, 其中次日回吐數)。net 缺值或 <=0 的列根本不是一次觀察。

    只回原始計數,不回比率也不回布林:分子與分母存下來,門檻才能只活在一個地方
    (``DAYTRADE_MIN_OBS``),而不是被每個讀取端各自複製一份。
    """
    obs = [(net, sell) for net, sell in observations if net and net > 0]
    paybacks = sum(1 for net, sell in obs if (sell or 0) >= DAYTRADE_PAYBACK * net)
    return len(obs), paybacks


def daytrade_flag(observations: list[tuple[float, float]],
                  min_obs: int | None = None) -> tuple[bool | None, float | None]:
    """單一 (分點, 個股) 配對的隔日沖判定。observations 為 (當日淨買張, 次一交易日同分點賣出張)。

    次日該分點無紀錄(未進前 15 大賣超)→ sell=0,視為未回吐;這是免費資料
    (每日僅前 15 大)的誠實限制。

    觀察數 < min_obs(預設 DAYTRADE_MIN_OBS)→ (None, None):「無法判定」,不是
    「判定為非隔日沖」。呼叫端必須把 None 當 NULL 傳遞,不可與 False 混用。
    min_obs 只給影子報表凍結歷史門檻用,線上計算一律走預設值。
    """
    threshold = DAYTRADE_MIN_OBS if min_obs is None else min_obs
    n_obs, paybacks = daytrade_counts(observations)
    if n_obs < threshold:
        return None, None
    rate = paybacks / n_obs
    return rate >= DAYTRADE_RATE, rate


def auto_in_blocked_by_daytrade(is_daytrade: bool | None) -> bool:
    """自動入選的隔日沖閘門:只有「確定是隔日沖」(True)才擋。

    is_daytrade 為 None 代表「未判定」(可判定配對 < DAYTRADE_MIN_PAIRS),不得擋。
    絕大多數新分點都是未判定,若把這裡寫成 `not is_daytrade` 之類的真值測試,
    自動入選將幾乎永遠不會發生。請勿「修正」成真值測試。
    """
    return is_daytrade is True


def price_percentile(close: float | None, low: float | None, high: float | None) -> float:
    """事件日還原收盤在近 20 日還原收盤 high-low 區間的位置 (close-low)/(high-low)。

    低=買在相對低點(好)。區間為 0(或缺值)時取 0.5。
    """
    if close is None or low is None or high is None:
        return 0.5
    rng = high - low
    if rng <= 0:
        return 0.5
    return clamp((close - low) / rng, 0.0, 1.0)


def recency_factor(avg90: float | None, avg_all: float | None) -> float:
    """近效性:近 90 日事件報酬 vs 全期報酬衰減(0-1)。

    邊界(V1 起始值):
      近 90 日無成熟事件(None)或 <=0 → 0(訊號已失效)。
      近 90 日 > 0 且全期 <=0(或無)→ 1(近期反轉向好)。
      皆 > 0 → clamp(avg90/avg_all, 0, 1)(近期報酬相對全期未衰減程度)。
    """
    if avg90 is None or avg90 <= 0:
        return 0.0
    if avg_all is None or avg_all <= 0:
        return 1.0
    return clamp(avg90 / avg_all, 0.0, 1.0)


def credibility_score(win_rate: float | None, avg_ret5: float | None,
                      avg_buy_percentile: float, amount_90d: float,
                      recency: float) -> float:
    """可信度分數 0-100(docs/13 §3b;分點層級跨個股 pooled)。

    win_rate/avg_ret5 缺(無成熟事件)→ 對應項 0 分。amount<=0 → 規模項 0 分。
    級距為 V1 起始值,待績效校準。
    """
    wr = clamp((win_rate - 40) / 30, 0.0, 1.0) if win_rate is not None else 0.0
    ar = clamp(avg_ret5 / 5, 0.0, 1.0) if avg_ret5 is not None else 0.0
    bp = 1.0 - avg_buy_percentile                        # 買點分位,低=好
    if amount_90d and amount_90d > 0:
        sc = clamp((math.log10(amount_90d) - 7) / 2, 0.0, 1.0)   # 千萬→0,10億→滿分
    else:
        sc = 0.0
    score = 100 * (0.30 * wr + 0.25 * ar + 0.15 * bp + 0.10 * sc + 0.20 * recency)
    return round(score, 1)


def _r1(x: float | None) -> float | None:
    return round(x, 1) if x is not None else None


def _r2(x: float | None) -> float | None:
    return round(x, 2) if x is not None else None


class _BranchAgg:
    """分點跨股 pooled 增量累加器(避免把全部事件 list 留在記憶體)。"""

    __slots__ = (
        "n_events", "sum_pctile", "n_matured", "win_count", "sum_ret5",
        "n_ev_90", "n_matured_90", "sum_ret5_90", "n_ev_2y", "amount",
        "dt_pairs_determined", "dt_pairs_flagged",
    )

    def __init__(self) -> None:
        self.n_events = 0
        self.sum_pctile = 0.0
        self.n_matured = 0
        self.win_count = 0
        self.sum_ret5 = 0.0
        self.n_ev_90 = 0
        self.n_matured_90 = 0
        self.sum_ret5_90 = 0.0
        self.n_ev_2y = 0
        self.amount = 0.0
        self.dt_pairs_determined = 0
        self.dt_pairs_flagged = 0

    def add_pair(self, pair_is_daytrade: bool | None) -> None:
        """每個 (分點, 個股) 配對只計一次。None = 該配對觀察數不足,兩個計數都不動。

        舊版把所有配對的觀察數 pooled 起來算單一比率;分點平均橫跨 ~1,128 檔,
        pooled 比率永遠到不了 0.6,實測 831 個分點全為 false。改計配對比例。
        """
        if pair_is_daytrade is None:
            return
        self.dt_pairs_determined += 1
        if pair_is_daytrade:
            self.dt_pairs_flagged += 1

    def add_event(self, date: str, fwd5: float | None, pctile: float,
                  cutoff90: str, cutoff2y: str) -> None:
        self.n_events += 1
        self.sum_pctile += pctile
        if date >= cutoff90:
            self.n_ev_90 += 1
        if date >= cutoff2y:
            self.n_ev_2y += 1
        if fwd5 is None:
            return
        self.n_matured += 1
        self.sum_ret5 += fwd5
        if fwd5 > 0:
            self.win_count += 1
        if date >= cutoff90:
            self.n_matured_90 += 1
            self.sum_ret5_90 += fwd5

    def is_daytrade(self) -> bool | None:
        """None = 可判定配對不足,無法判定(不等於「不是隔日沖分點」)。"""
        if self.dt_pairs_determined < DAYTRADE_MIN_PAIRS:
            return None
        return (self.dt_pairs_flagged / self.dt_pairs_determined) >= DAYTRADE_PAIR_SHARE


def compute_all():
    """計算 branch_stock_stats + branch_rankings,並自動增減 tracked_branches。"""
    init_db()
    engine = get_engine()
    now = datetime.now(ZoneInfo(config.TZ)).isoformat(timespec="seconds")

    # 分點層級 pool:增量累加(OOM 修復 2026-08-25:不再保留全事件 list)。
    # stock_stats 用緊湊 tuple,峰值 ≈ 單檔 trades + 累加器。
    branch_aggs: dict[str, _BranchAgg] = {}
    stock_stats: dict[tuple[str, str], tuple] = {}

    with engine.connect() as conn:
        as_of = conn.execute(text("SELECT MAX(date) FROM branch_trades")).scalar()
        if not as_of:
            print("branch stats: no branch_trades data.")
            return

        tracked = {r[0]: r[1] for r in conn.execute(text(
            "SELECT branch_name, source FROM tracked_branches"))}

        # 只取個股(排除權證與指數)的 distinct stock_id,比照 json_export 的個股判定。
        stock_ids = [r[0] for r in conn.execute(text("""
            SELECT DISTINCT b.stock_id
            FROM branch_trades b
            JOIN stocks s ON s.id = b.stock_id
            WHERE s.type = 'stock' AND s.name NOT LIKE '%指%'
            ORDER BY b.stock_id
        """)).fetchall()]
        if not stock_ids:
            print(f"branch stats @ {as_of}: no individual-stock branch trades.")
            return

        as_of_d = date_cls.fromisoformat(as_of)
        cutoff90 = (as_of_d - timedelta(days=90)).isoformat()
        cutoff2y = (as_of_d - timedelta(days=730)).isoformat()

        # 逐檔處理:載入單股價格序列與其 branch_trades 列 → 算完累加 → 迭代結束即釋放。
        # branch_trades PK 前導為 stock_id,WHERE b.stock_id=:sid 走 PK,不需額外索引。
        for n_done, sid in enumerate(stock_ids, 1):
            prows = conn.execute(text(
                "SELECT date, open, close, adj_factor FROM daily_prices "
                "WHERE stock_id = :sid AND close IS NOT NULL ORDER BY date"
            ), {"sid": sid}).fetchall()
            # 每股價格序列:交易日曆(判連續)、還原 candle(前瞻報酬/買點分位)、未還原收盤(金額)。
            trading_dates = [r[0] for r in prows]
            date_index = {d: i for i, d in enumerate(trading_dates)}
            adj_candles = [
                {"date": r[0], "open": (r[1] or 0) * (r[3] or 1.0),
                 "close": (r[2] or 0) * (r[3] or 1.0)}
                for r in prows
            ]
            adj_close = [(r[2] or 0) * (r[3] or 1.0) for r in prows]
            close_by_date = {r[0]: r[2] for r in prows}

            strade_rows = conn.execute(text(
                "SELECT branch_name, date, net_lots, sell_lots, pct "
                "FROM branch_trades WHERE stock_id = :sid"
            ), {"sid": sid}).fetchall()

            by_branch: dict[str, dict[str, dict]] = defaultdict(dict)
            for br, d, net, sell, pct in strade_rows:
                by_branch[br][d] = {"net": net, "sell": sell, "pct": pct}

            for br, datemap in by_branch.items():
                qual_dates = sorted(
                    d for d, row in datemap.items()
                    if (row["net"] or 0) > 0 and row["pct"] is not None and row["pct"] >= QUAL_PCT
                )
                if not qual_dates:
                    continue

                agg = branch_aggs.get(br)
                if agg is None:
                    agg = _BranchAgg()
                    branch_aggs[br] = agg

                # 隔日沖觀察:每個資格買超日 → 次一交易日同分點賣出張(無紀錄=0)。
                obs = daytrade_observations(qual_dates, datemap, trading_dates, date_index)
                # pair 層判定用「合併連續段之前」的觀察數(obs 逐資格日,未合併)。
                st_daytrade, _ = daytrade_flag(obs)
                dt_obs, dt_paybacks = daytrade_counts(obs)
                agg.add_pair(st_daytrade)

                # 合併事件 + 前瞻報酬 + 買點分位 → 直接打進累加器。
                events = merge_consecutive_events(qual_dates, date_index)
                matured_vals: list[float] = []
                for ed in events:
                    perf = forward_returns(adj_candles, ed)
                    fwd5 = perf["fwd_5d"] if perf else None
                    idx = date_index.get(ed)
                    pctile = 0.5
                    if idx is not None:
                        window = [c for c in adj_close[max(0, idx - 19):idx + 1] if c is not None]
                        if window:
                            pctile = price_percentile(adj_close[idx], min(window), max(window))
                    agg.add_event(ed, fwd5, pctile, cutoff90, cutoff2y)
                    if fwd5 is not None:
                        matured_vals.append(fwd5)

                win_rate = (100.0 * sum(1 for f in matured_vals if f > 0) / len(matured_vals)) if matured_vals else None
                avg_ret5 = (sum(matured_vals) / len(matured_vals)) if matured_vals else None

                # 近 90 日資格買超日金額(未還原價):net_lots * 1000 股 * 當日收盤。
                amt = 0.0
                for qd in qual_dates:
                    if qd >= cutoff90:
                        cl = close_by_date.get(qd)
                        if cl:
                            amt += (datemap[qd]["net"] or 0) * 1000 * cl
                agg.amount += amt

                # 緊湊 tuple:(events, win, ret5, daytrade, last_active, dt_obs, dt_paybacks)
                stock_stats[(br, sid)] = (
                    len(events), _r1(win_rate), _r2(avg_ret5), st_daytrade, qual_dates[-1],
                    dt_obs, dt_paybacks,
                )

            if n_done % 400 == 0:
                print(f"branch stats progress: {n_done}/{len(stock_ids)} stocks", flush=True)

    # 分點彙總(跨個股 pooled)。
    branch_meta: dict[str, dict] = {}
    for br, agg in branch_aggs.items():
        n_events = agg.n_events
        win_rate = (100.0 * agg.win_count / agg.n_matured) if agg.n_matured else None
        avg_ret5 = (agg.sum_ret5 / agg.n_matured) if agg.n_matured else None
        avg_pctile = (agg.sum_pctile / n_events) if n_events else 0.5
        avg90 = (agg.sum_ret5_90 / agg.n_matured_90) if agg.n_matured_90 else None
        recency = recency_factor(avg90, avg_ret5)
        score = credibility_score(win_rate, avg_ret5, avg_pctile, agg.amount, recency)

        branch_meta[br] = {
            "score": score,
            "n_events": n_events,
            "win_rate": win_rate,
            "avg_ret5": avg_ret5,
            "is_dt": agg.is_daytrade(),
            "n_matured": agg.n_matured,
            "dt_pairs_determined": agg.dt_pairs_determined,
            "dt_pairs_flagged": agg.dt_pairs_flagged,
            "n_ev_90": agg.n_ev_90,
            "n_ev_2y": agg.n_ev_2y,
        }

    # 排行快照:pooled 事件數 >= 5 入榜。
    ranked_names: set[str] = set()
    rank_records: list[dict] = []
    for br, m in branch_meta.items():
        if m["n_events"] < MIN_RANK_EVENTS:
            continue
        ranked_names.add(br)
        rank_records.append({
            "branch_name": br,
            "as_of": as_of,
            "rank_score": m["score"],
            "win_rate": _r1(m["win_rate"]),
            "avg_ret5": _r2(m["avg_ret5"]),
            "samples": m["n_events"],
            "matured_samples": m["n_matured"],
            "style": "daytrade" if m["is_dt"] else "swing",
            "is_daytrade": m["is_dt"],
            "daytrade_pairs_determined": m["dt_pairs_determined"],
            "daytrade_pairs_flagged": m["dt_pairs_flagged"],
            "source": tracked.get(br, "candidate"),
        })

    # branch_stock_stats 只寫入 入榜分點 ∪ 追蹤名單分點(避免表爆量)。
    persist = ranked_names | set(tracked.keys())
    stat_records = [
        {
            "branch_name": br,
            "stock_id": sid,
            "events_count": s[0],
            "win_rate": s[1],
            "avg_ret5": s[2],
            "is_daytrade_suspect": s[3],   # None = 觀察數不足,未判定(不是 False)
            "last_active_date": s[4],
            "daytrade_obs": s[5],
            "daytrade_paybacks": s[6],
            "updated_at": now,
        }
        for (br, sid), s in stock_stats.items() if br in persist
    ]

    # 自動入選 / 移出 tracked_branches(§2b)。絕不覆蓋/刪除 source='manual'。
    # 註:規格的「連續 60 日 < 50」移出需快照歷史累積,V1 先以當次分數簡化判定。
    auto_in, auto_out = [], []
    for br, m in branch_meta.items():
        src = tracked.get(br)
        if src is None:
            # NULL(未判定)不擋自動入選 —— 見 auto_in_blocked_by_daytrade 的說明。
            blocked_by_daytrade = auto_in_blocked_by_daytrade(m["is_dt"])
            if (m["n_ev_2y"] >= AUTO_IN_EVENTS_2Y and m["score"] >= AUTO_IN_SCORE
                    and not blocked_by_daytrade and m["n_ev_90"] >= AUTO_IN_EVENTS_90):
                auto_in.append(br)
        elif src == "auto":
            if m["score"] < AUTO_OUT_SCORE and m["n_ev_90"] < AUTO_OUT_EVENTS_90:
                auto_out.append(br)

    # 本次剛自動入選的分點,快照 source 一併標為 auto(否則首次快照會顯示 candidate)。
    auto_in_set = set(auto_in)
    for rec in rank_records:
        if rec["branch_name"] in auto_in_set:
            rec["source"] = "auto"

    with engine.begin() as conn:
        conn.execute(schema.branch_stock_stats.delete())
        upsert(conn, schema.branch_stock_stats, stat_records)

        # 保留歷史快照:只刪同一 as_of 再插入(排行變化本身是訊號,§5)。
        conn.execute(schema.branch_rankings.delete().where(
            schema.branch_rankings.c.as_of == as_of))
        upsert(conn, schema.branch_rankings, rank_records)

        for br in auto_in:
            conn.execute(schema.tracked_branches.insert().values(
                branch_name=br, source="auto", note="演算法自動入選", added_at=now))
        for br in auto_out:
            conn.execute(schema.tracked_branches.delete().where(
                (schema.tracked_branches.c.branch_name == br)
                & (schema.tracked_branches.c.source == "auto")))

    print(f"branch stats @ {as_of}: {len(branch_meta)} branches evaluated, "
          f"{len(rank_records)} ranked (>= {MIN_RANK_EVENTS} events), "
          f"{len(stat_records)} stock-stat rows, "
          f"+{len(auto_in)} auto-in, -{len(auto_out)} auto-out.")
    for r in sorted(rank_records, key=lambda x: x["rank_score"], reverse=True)[:5]:
        print(f"  {r['branch_name']}: score={r['rank_score']} win={r['win_rate']} "
              f"ret5={r['avg_ret5']} n={r['samples']} "
              f"{'DAYTRADE' if r['is_daytrade'] else r['style']} [{r['source']}]")


if __name__ == "__main__":
    compute_all()
