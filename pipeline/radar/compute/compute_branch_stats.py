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

# 隔日沖判定
DAYTRADE_PAYBACK = 0.7         # 次日回吐 ≥ 當日淨買 70% 視為回吐
DAYTRADE_RATE = 0.6            # 回吐比率 ≥ 60% → 隔日沖
DAYTRADE_MIN_OBS = 4           # 觀察數 < 4 不判定

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


def daytrade_flag(observations: list[tuple[float, float]]) -> tuple[bool, float | None]:
    """隔日沖判定。observations 為 (當日淨買張, 次一交易日同分點賣出張) 清單。

    次日該分點無紀錄(未進前 15 大賣超)→ sell=0,視為未回吐;這是免費資料
    (每日僅前 15 大)的誠實限制。觀察數 < 4 → (False, None) 不判定。
    """
    obs = [(net, sell) for net, sell in observations if net and net > 0]
    if len(obs) < DAYTRADE_MIN_OBS:
        return False, None
    paybacks = sum(1 for net, sell in obs if (sell or 0) >= DAYTRADE_PAYBACK * net)
    rate = paybacks / len(obs)
    return rate >= DAYTRADE_RATE, rate


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


def compute_all():
    """計算 branch_stock_stats + branch_rankings,並自動增減 tracked_branches。"""
    init_db()
    engine = get_engine()
    now = datetime.now(ZoneInfo(config.TZ)).isoformat(timespec="seconds")

    with engine.connect() as conn:
        as_of = conn.execute(text("SELECT MAX(date) FROM branch_trades")).scalar()
        if not as_of:
            print("branch stats: no branch_trades data.")
            return

        tracked = {r[0]: r[1] for r in conn.execute(text(
            "SELECT branch_name, source FROM tracked_branches"))}

        # 只取個股(排除權證與指數),比照 json_export 的個股判定。
        trade_rows = conn.execute(text("""
            SELECT b.branch_name, b.stock_id, b.date, b.net_lots, b.sell_lots, b.pct
            FROM branch_trades b
            JOIN stocks s ON s.id = b.stock_id
            WHERE s.type = 'stock' AND s.name NOT LIKE '%指%'
        """)).fetchall()
        if not trade_rows:
            print(f"branch stats @ {as_of}: no individual-stock branch trades.")
            return

        # 每股價格序列:交易日曆(判連續)、還原 candle(前瞻報酬/買點分位)、未還原收盤(金額)。
        stock_ids = sorted({r[1] for r in trade_rows})
        stock_ctx: dict[str, dict] = {}
        for sid in stock_ids:
            prows = conn.execute(text(
                "SELECT date, open, close, adj_factor FROM daily_prices "
                "WHERE stock_id = :sid AND close IS NOT NULL ORDER BY date"
            ), {"sid": sid}).fetchall()
            dates = [r[0] for r in prows]
            stock_ctx[sid] = {
                "dates": dates,
                "date_index": {d: i for i, d in enumerate(dates)},
                "adj_candles": [
                    {"date": r[0], "open": (r[1] or 0) * (r[3] or 1.0),
                     "close": (r[2] or 0) * (r[3] or 1.0)}
                    for r in prows
                ],
                "adj_close": [(r[2] or 0) * (r[3] or 1.0) for r in prows],
                "close_by_date": {r[0]: r[2] for r in prows},
            }

    by_bs: dict[tuple[str, str], dict[str, dict]] = defaultdict(dict)
    for br, sid, d, net, sell, pct in trade_rows:
        by_bs[(br, sid)][d] = {"net": net, "sell": sell, "pct": pct}

    as_of_d = date_cls.fromisoformat(as_of)
    cutoff90 = (as_of_d - timedelta(days=90)).isoformat()
    cutoff2y = (as_of_d - timedelta(days=730)).isoformat()

    # 分點層級 pool(以事件為單位)。
    branch_events: dict[str, list[dict]] = defaultdict(list)
    branch_obs: dict[str, list[tuple[float, float]]] = defaultdict(list)
    branch_amount: dict[str, float] = defaultdict(float)
    stock_stats: dict[tuple[str, str], dict] = {}

    for (br, sid), datemap in by_bs.items():
        ctx = stock_ctx.get(sid)
        if not ctx:
            continue
        date_index = ctx["date_index"]
        trading_dates = ctx["dates"]
        adj_close = ctx["adj_close"]
        adj_candles = ctx["adj_candles"]
        close_by_date = ctx["close_by_date"]

        qual_dates = sorted(
            d for d, row in datemap.items()
            if (row["net"] or 0) > 0 and row["pct"] is not None and row["pct"] >= QUAL_PCT
        )
        if not qual_dates:
            continue

        # 隔日沖觀察:每個資格買超日 → 次一交易日同分點賣出張(無紀錄=0)。
        obs: list[tuple[float, float]] = []
        for qd in qual_dates:
            net = datemap[qd]["net"]
            idx = date_index.get(qd)
            next_sell = 0
            if idx is not None and idx + 1 < len(trading_dates):
                nrow = datemap.get(trading_dates[idx + 1])
                next_sell = (nrow["sell"] if nrow else 0) or 0
            obs.append((net, next_sell))
        st_daytrade, _ = daytrade_flag(obs)

        # 合併事件 + 前瞻報酬 + 買點分位。
        events = merge_consecutive_events(qual_dates, date_index)
        ev_records: list[dict] = []
        for ed in events:
            perf = forward_returns(adj_candles, ed)
            fwd5 = perf["fwd_5d"] if perf else None
            idx = date_index.get(ed)
            pctile = 0.5
            if idx is not None:
                window = [c for c in adj_close[max(0, idx - 19):idx + 1] if c is not None]
                if window:
                    pctile = price_percentile(adj_close[idx], min(window), max(window))
            ev_records.append({"date": ed, "fwd5": fwd5, "pctile": pctile})

        matured = [e["fwd5"] for e in ev_records if e["fwd5"] is not None]
        win_rate = (100.0 * sum(1 for f in matured if f > 0) / len(matured)) if matured else None
        avg_ret5 = (sum(matured) / len(matured)) if matured else None

        # 近 90 日資格買超日金額(未還原價):net_lots * 1000 股 * 當日收盤。
        amt = 0.0
        for qd in qual_dates:
            if qd >= cutoff90:
                cl = close_by_date.get(qd)
                if cl:
                    amt += (datemap[qd]["net"] or 0) * 1000 * cl

        stock_stats[(br, sid)] = {
            "events_count": len(events),
            "win_rate": _r1(win_rate),
            "avg_ret5": _r2(avg_ret5),
            "is_daytrade_suspect": st_daytrade,
            "last_active_date": qual_dates[-1],
        }

        branch_events[br].extend(ev_records)
        branch_obs[br].extend(obs)
        branch_amount[br] += amt

    # 分點彙總(跨個股 pooled)。
    branch_meta: dict[str, dict] = {}
    for br, evs in branch_events.items():
        n_events = len(evs)
        matured = [e["fwd5"] for e in evs if e["fwd5"] is not None]
        win_rate = (100.0 * sum(1 for f in matured if f > 0) / len(matured)) if matured else None
        avg_ret5 = (sum(matured) / len(matured)) if matured else None
        avg_pctile = sum(e["pctile"] for e in evs) / n_events if n_events else 0.5

        ev90 = [e["fwd5"] for e in evs if e["date"] >= cutoff90 and e["fwd5"] is not None]
        avg90 = (sum(ev90) / len(ev90)) if ev90 else None
        recency = recency_factor(avg90, avg_ret5)
        score = credibility_score(win_rate, avg_ret5, avg_pctile, branch_amount[br], recency)
        is_dt, _ = daytrade_flag(branch_obs[br])

        branch_meta[br] = {
            "score": score,
            "n_events": n_events,
            "win_rate": win_rate,
            "avg_ret5": avg_ret5,
            "is_dt": is_dt,
            "n_ev_90": sum(1 for e in evs if e["date"] >= cutoff90),
            "n_ev_2y": sum(1 for e in evs if e["date"] >= cutoff2y),
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
            "style": "daytrade" if m["is_dt"] else "swing",
            "is_daytrade": m["is_dt"],
            "source": tracked.get(br, "candidate"),
        })

    # branch_stock_stats 只寫入 入榜分點 ∪ 追蹤名單分點(避免表爆量)。
    persist = ranked_names | set(tracked.keys())
    stat_records = [
        {"branch_name": br, "stock_id": sid, **s, "updated_at": now}
        for (br, sid), s in stock_stats.items() if br in persist
    ]

    # 自動入選 / 移出 tracked_branches(§2b)。絕不覆蓋/刪除 source='manual'。
    # 註:規格的「連續 60 日 < 50」移出需快照歷史累積,V1 先以當次分數簡化判定。
    auto_in, auto_out = [], []
    for br, m in branch_meta.items():
        src = tracked.get(br)
        if src is None:
            if (m["n_ev_2y"] >= AUTO_IN_EVENTS_2Y and m["score"] >= AUTO_IN_SCORE
                    and not m["is_dt"] and m["n_ev_90"] >= AUTO_IN_EVENTS_90):
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
