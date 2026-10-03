"""區間損益(估算):分點 × 個股的平均成本法估算,`pnl-avgcost-v1`(docs/42)。

只用這檔股票每日前 15 大進出「看得見」的淨張數,當日收盤價當成交價。看不見的
日子視為沒交易,區間起點視為零持股;賣出找不到對應持股的張數記為 unattributed,
不放空、不計損益。這是估算,不是帳戶損益——畫面與 docs/42 都照實講。

純函式,不碰 DB:json_export 在個股迴圈裡把已載入、尚未裁成前 12 名的
branch_trades 列與 K 線交給 `branch_pnl_payload`。
"""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from typing import Iterable

DEFINITIONS_VERSION = "pnl-avgcost-v1"
WINDOWS: tuple[tuple[str, int | None], ...] = (("60", 60), ("240", 240), ("all", None))
MIN_BUY_LOTS = 50
MIN_MAX_COST = 1_000_000
TOP_N = 15
SHARES_PER_LOT = 1000
_AF_EPS = 1e-9


@dataclass
class PairResult:
    """一個 (分點, 個股) 在一個窗口內的模擬結果;金額為 NT$ 浮點,尚未四捨五入。"""
    realized: float
    unrealized: float
    pos_lots: float
    avg_cost: float
    buy_lots: float
    sell_lots_attributed: float
    sell_lots_unattributed: float
    max_cost: float
    buy_cost: float
    sell_proceeds: float

    @property
    def est_total(self) -> float:
        return self.realized + self.unrealized


def simulate_pair(trades: Iterable[tuple[float, float]], p_last: float) -> PairResult:
    """依時間順序的 (net_lots, price) 跑平均成本法。

    net>0 → 加碼並重算均價;net<0 → 先賣掉手上的(sold=min(|net|,pos)),
    超過持股的部分記為 unattributed(不放空)。
    """
    pos = avg = realized = 0.0
    buy = sold_attr = sold_unattr = max_cost = 0.0
    buy_cost = proceeds = 0.0
    for net, price in trades:
        if net > 0:
            avg = (pos * avg + net * price) / (pos + net)
            pos += net
            buy += net
            buy_cost += net * price * SHARES_PER_LOT
        elif net < 0:
            sold = min(-net, pos)
            realized += sold * (price - avg) * SHARES_PER_LOT
            proceeds += sold * price * SHARES_PER_LOT
            pos -= sold
            sold_attr += sold
            sold_unattr += -net - sold
            if pos == 0:
                avg = 0.0
        max_cost = max(max_cost, pos * avg * SHARES_PER_LOT)
    unrealized = pos * (p_last - avg) * SHARES_PER_LOT
    return PairResult(
        realized=realized, unrealized=unrealized, pos_lots=pos, avg_cost=avg,
        buy_lots=buy, sell_lots_attributed=sold_attr, sell_lots_unattributed=sold_unattr,
        max_cost=max_cost, buy_cost=buy_cost, sell_proceeds=proceeds,
    )


@dataclass
class _Branch:
    """一個分點在這檔股票的全部可見日,依日期排序;價格已換算(缺價為 None)。"""
    dates: list[str]          # 每個可見日(含淨額 0 的列)
    nets: list[float]
    prices: list[float | None]
    af_moved: list[bool]


def _prepare(
    by_branch: dict[str, dict[str, float]],
    prices: dict[str, tuple[float, float]],
    af_last: float | None,
) -> dict[str, _Branch]:
    out: dict[str, _Branch] = {}
    for name in sorted(by_branch):
        days = sorted(by_branch[name].items())
        px: list[float | None] = []
        moved: list[bool] = []
        for d, _ in days:
            hit = prices.get(d)
            if hit is None or af_last is None:
                px.append(None)
                moved.append(False)
            else:
                close, af = hit
                px.append(close * af / af_last)
                moved.append(abs(af - af_last) > _AF_EPS)
        out[name] = _Branch([d for d, _ in days], [n for _, n in days], px, moved)
    return out


def _window(
    dates: list[str],
    days: int | None,
    branches: dict[str, _Branch],
    last_close: float | None,
) -> dict:
    win_dates = dates if days is None else dates[-days:]
    first = win_dates[0]
    considered: list[dict] = []
    skipped = 0
    for name, b in branches.items():
        i0 = bisect_left(b.dates, first)
        if i0 >= len(b.dates):
            continue
        idx = [i for i in range(i0, len(b.dates)) if b.nets[i] != 0]
        if not idx:
            continue
        if last_close is None or any(b.prices[i] is None for i in idx):
            skipped += 1
            continue
        af_adjusted = any(b.af_moved[i] for i in idx)
        res = simulate_pair([(b.nets[i], b.prices[i]) for i in idx], last_close)
        if res.buy_lots < MIN_BUY_LOTS or res.max_cost < MIN_MAX_COST:
            continue
        est = res.est_total
        considered.append({
            "name": name,
            "est_total": round(est),
            "realized": round(res.realized),
            "unrealized": round(res.unrealized),
            "pos_lots": round(res.pos_lots),
            "avg_cost": round(res.avg_cost, 2),
            "last_close": round(last_close, 2),
            "buy_lots": round(res.buy_lots),
            "sell_lots_attributed": round(res.sell_lots_attributed),
            "sell_lots_unattributed": round(res.sell_lots_unattributed),
            "visible_days": len(b.dates) - i0,
            "max_cost": round(res.max_cost),
            "ret_pct": round(est / res.max_cost * 100, 2) if res.max_cost else None,
            "af_adjusted": af_adjusted,
            "first_date": b.dates[i0],
            "last_date": b.dates[-1],
            "_est": est,
        })
    gain = sorted((r for r in considered if r["_est"] > 0), key=lambda r: (-r["_est"], r["name"]))
    loss = sorted((r for r in considered if r["_est"] < 0), key=lambda r: (r["_est"], r["name"]))
    strip = lambda rows: [{k: v for k, v in r.items() if k != "_est"} for r in rows[:TOP_N]]
    return {
        "window_days": len(win_dates),
        "first_date": first,
        "pairs_considered": len(considered),
        "pairs_skipped_missing_price": skipped,
        # 摘要句「估算賺 X 個、賠 Y 個」要全部個數,清單只留前 15。
        "n_gainers": len(gain),
        "n_losers": len(loss),
        "gainers": strip(gain),
        "losers": strip(loss),
    }


def branch_pnl_payload(
    branch_rows: Iterable[tuple],
    candles: Iterable[tuple],
    *,
    as_of_limit: str,
) -> dict | None:
    """個股 JSON 的 `branch_pnl_est`;這檔沒有任何分點列時回傳 None(鍵不輸出)。

    branch_rows: (date, branch_name, net_lots) — 未裁剪的 branch_trades 列。
    candles: (date, close, adj_factor) — close 為 NULL 的列不應出現(視同缺價)。
    as_of_limit: 匯出資料日;晚於它的分點列不算。
    """
    by_branch: dict[str, dict[str, float]] = {}
    date_set: set[str] = set()
    for row in branch_rows:
        d, name, net = row[0], row[1], row[2]
        if d > as_of_limit or not name:
            continue
        date_set.add(d)
        per = by_branch.setdefault(name, {})
        per[d] = per.get(d, 0) + (net or 0)
    if not date_set:
        return None
    dates = sorted(date_set)
    as_of = dates[-1]
    prices: dict[str, tuple[float, float]] = {}
    for c in candles:
        if c[1] is None:
            continue
        prices[c[0]] = (float(c[1]), float(c[2] or 1.0))
    last_dates = [d for d in prices if d <= as_of]
    if last_dates:
        last_close, af_last = prices[max(last_dates)]
    else:
        last_close = af_last = None
    branches = _prepare(by_branch, prices, af_last)
    return {
        "as_of": as_of,
        "definitions_version": DEFINITIONS_VERSION,
        "windows": {
            key: _window(dates, days, branches, last_close)
            for key, days in WINDOWS
        },
    }
