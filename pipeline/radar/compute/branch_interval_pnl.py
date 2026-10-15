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
    # export 每輪對全市場呼叫數千萬次(docs/44 §3.5):min()/max() 換成同義的比較、常數放區域變數。
    # 浮點運算的式子與順序一個都沒動,結果逐位元相同(min(a, b) 只在 b < a 時回 b;max 同理)。
    lot = SHARES_PER_LOT
    pos = avg = realized = 0.0
    buy = sold_attr = sold_unattr = max_cost = 0.0
    buy_cost = proceeds = 0.0
    for net, price in trades:
        if net > 0:
            avg = (pos * avg + net * price) / (pos + net)
            pos += net
            buy += net
            buy_cost += net * price * lot
        elif net < 0:
            want = -net
            sold = pos if pos < want else want
            realized += sold * (price - avg) * lot
            proceeds += sold * price * lot
            pos -= sold
            sold_attr += sold
            sold_unattr += want - sold
            if pos == 0:
                avg = 0.0
        cost = pos * avg * lot
        if cost > max_cost:
            max_cost = cost
    unrealized = pos * (p_last - avg) * SHARES_PER_LOT
    return PairResult(
        realized=realized, unrealized=unrealized, pos_lots=pos, avg_cost=avg,
        buy_lots=buy, sell_lots_attributed=sold_attr, sell_lots_unattributed=sold_unattr,
        max_cost=max_cost, buy_cost=buy_cost, sell_proceeds=proceeds,
    )


@dataclass
class _Branch:
    """一個分點在這檔股票的全部可見日,依日期排序;價格已換算(缺價為 None)。

    三個窗口都是同一串日子的後綴,所以「淨額非 0 的日子」與它們的 (淨額, 價格) 先算一次
    (``nz_*``),各窗口只切後綴(2026-10-15 export 提速,docs/44 §3.5;結果逐位元不變):
      * ``nz_pos``:淨額非 0 的日子在 ``dates`` 裡的位置(遞增)。
      * ``nz_pairs``:對應的 (淨額, 價格),``simulate_pair`` 的輸入。
      * ``last_none`` / ``last_moved``:``nz`` 裡最後一個缺價／還原因子有變動的位置(-1 = 沒有);
        後綴 ``nz[k:]`` 有缺價 ⇔ ``last_none >= k``。
      * ``buy_suffix``:``buy_suffix[k]`` = ``nz[k:]`` 的正淨額合計(= simulate_pair 的
        ``buy_lots``);淨額全是整數時才給(整數加總與順序無關,才能拿來先篩),否則 None。
    """
    dates: list[str]          # 每個可見日(含淨額 0 的列)
    nz_pos: list[int]
    nz_pairs: list[tuple[float, float | None]]
    last_none: int
    last_moved: int
    buy_suffix: list[int] | None


def _prepare(
    by_branch: dict[str, dict[str, float]],
    prices: dict[str, tuple[float, float]],
    af_last: float | None,
    dates: Iterable[str],
) -> dict[str, _Branch]:
    # 換算價只跟日期有關(與分點無關):``dates``(全部分點列的日期)每個算一次,分點迴圈只查表。式子不變。
    px_by_date: dict[str, tuple[float, bool]] = {}
    if af_last is not None:
        for d in dates:
            hit = prices.get(d)
            if hit is not None:
                close, af = hit
                px_by_date[d] = (close * af / af_last, abs(af - af_last) > _AF_EPS)
    out: dict[str, _Branch] = {}
    for name in sorted(by_branch):
        days = sorted(by_branch[name].items())
        nz_pos: list[int] = []
        nz_pairs: list[tuple[float, float | None]] = []
        last_none = last_moved = -1
        all_int = True
        for i, (d, net) in enumerate(days):
            if net == 0:
                continue
            hit = px_by_date.get(d)
            if hit is None:
                px = None
                last_none = len(nz_pos)
            else:
                px, moved = hit
                if moved:
                    last_moved = len(nz_pos)
            if type(net) is not int:
                all_int = False
            nz_pos.append(i)
            nz_pairs.append((net, px))
        buy_suffix: list[int] | None = None
        if all_int:
            buy_suffix = [0] * (len(nz_pairs) + 1)
            acc = 0
            for k in range(len(nz_pairs) - 1, -1, -1):
                net = nz_pairs[k][0]
                if net > 0:
                    acc += net
                buy_suffix[k] = acc
        out[name] = _Branch([d for d, _ in days], nz_pos, nz_pairs, last_none, last_moved, buy_suffix)
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
        k0 = bisect_left(b.nz_pos, i0)
        if k0 >= len(b.nz_pos):
            continue
        if last_close is None or b.last_none >= k0:
            skipped += 1
            continue
        # 買進張數不到門檻的配對,模擬完也會被下面那行濾掉;整數淨額時先用後綴和跳過模擬。
        if b.buy_suffix is not None and b.buy_suffix[k0] < MIN_BUY_LOTS:
            continue
        af_adjusted = b.last_moved >= k0
        res = simulate_pair(b.nz_pairs[k0:], last_close)
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
        per = by_branch.get(name)
        if per is None:
            per = by_branch[name] = {}
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
    branches = _prepare(by_branch, prices, af_last, dates)
    return {
        "as_of": as_of,
        "definitions_version": DEFINITIONS_VERSION,
        "windows": {
            key: _window(dates, days, branches, last_close)
            for key, days in WINDOWS
        },
    }
