"""權證分點持有估算 `wpos-avgcost-v1`(docs/51)。

一個分點在一檔標的的權證上「大概還抱著多少、成本多少、換算成現股大約在什麼價位、
帳面目前估算賺賠多少」。方法與 docs/42 的 `pnl-avgcost-v1` 同一套:只用每檔權證每日
前 15 大進出看得見的淨張數,當日權證收盤價當成交價,平均成本法;窗口起點視為零持股,
看不見的日子視為沒交易;賣超找不到對應持股的張數記為 unattributed,不放空。

與 docs/42 不同的兩件事:

* **每一腿 = (分點, 權證)**,再依標的、認購／認售加總成 (分點, 標的, kind)。認購與
  認售方向相反,永遠不混在同一個數字裡。
* 多了「換算現股均價」:每筆買超都記下**當天標的收盤價**,以該筆買超的金額(張 × 1000
  × 權證收盤)加權平均;賣超依平均成本法等比例扣減。這不是履約價換算的損益兩平點,
  只是「這個分點買這些權證的那幾天,現股大概在什麼價位」——使用者拿來跟今天的現股價
  比(docs/51 §2)。

這是估算,不是帳戶損益;券商分點不等於單一個人;權證有時間價值衰減,持有不動帳面也會
縮水;發行商自家權證多為造市／避險(呼叫端用 self_issued 排除)。純函式,不碰 DB。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping

DEFINITIONS_VERSION = "wpos-avgcost-v1"
SHARES_PER_LOT = 1000
#: 篩選清單(warrant_positions.json)的門檻:仍持有成本(估)≥ 500 萬才列。
SCREEN_MIN_COST = 5_000_000
SCREEN_MAX_ROWS = 300
#: 自家發行占仍持有成本過半 → 視為發行商造市／避險,篩選清單排除。
SCREEN_SELF_MAX_PCT = 50


@dataclass
class WarrantInfo:
    kind: str                      # call / put
    maturity_date: str | None      # YYYY-MM-DD;None = 未知(不當成到期)
    last_price: float | None       # as_of 當日或之前(近 5 個交易日內)最後一個權證收盤
    last_price_date: str | None = None
    name: str | None = None        # 權證簡稱(呼叫端判斷發行商用)


@dataclass
class Leg:
    """一個 (分點, 權證) 的平均成本法累計器。金額為 NT$ 浮點,輸出時才取整。"""
    pos: float = 0.0
    cost: float = 0.0              # 仍持有的成本(NT$)
    under_num: float = 0.0         # Σ 買超金額 × 當日標的收盤(只含標的收盤已知的買超)
    under_cost: float = 0.0        # Σ 買超金額(只含標的收盤已知的買超)
    realized: float = 0.0
    buy_lots: float = 0.0
    sell_attr: float = 0.0
    sell_unattr: float = 0.0
    last_buy_date: str | None = None
    first_date: str | None = None
    #: 任一有交易的日子沒有權證收盤 → 這腿的成本不可信,整腿不估(docs/42 同一規則)。
    price_missing: bool = False
    #: 仍持有部位的「進場日」拆解:[日期, 仍持有張數, 仍持有成本, 當日標的收盤|None]。
    #: 平均成本法沒有先進先出:每次賣超把**每一個**買超日的剩餘張數等比例縮小(docs/51 §2.4)。
    buys: list[list] = field(default_factory=list)

    def trade(self, date: str, net_lots: float, price: float | None, under_close: float | None) -> None:
        if not net_lots:
            return
        if self.first_date is None:
            self.first_date = date
        if price is None or price <= 0:
            self.price_missing = True
            return
        if net_lots > 0:
            amount = net_lots * price * SHARES_PER_LOT
            self.pos += net_lots
            self.cost += amount
            self.buy_lots += net_lots
            self.last_buy_date = date
            if under_close is not None and under_close > 0:
                self.under_num += amount * under_close
                self.under_cost += amount
            if self.buys and self.buys[-1][0] == date:
                self.buys[-1][1] += net_lots
                self.buys[-1][2] += amount
            else:
                self.buys.append([date, net_lots, amount, under_close if under_close and under_close > 0 else None])
        else:
            sold = min(-net_lots, self.pos)
            if sold > 0:
                frac = sold / self.pos
                released = self.cost * frac
                self.realized += sold * price * SHARES_PER_LOT - released
                self.cost -= released
                self.under_num -= self.under_num * frac
                self.under_cost -= self.under_cost * frac
                self.pos -= sold
                keep = 1.0 - frac
                for b in self.buys:
                    b[1] *= keep
                    b[2] *= keep
                if self.pos <= 1e-9:
                    self.pos = self.cost = self.under_num = self.under_cost = 0.0
                    self.buys = []
            self.sell_attr += sold
            self.sell_unattr += -net_lots - sold


@dataclass
class _Agg:
    lots: float = 0.0
    cost: float = 0.0
    cost_valued: float = 0.0
    value: float = 0.0
    under_num: float = 0.0
    under_cost: float = 0.0
    realized: float = 0.0
    buy_lots: float = 0.0
    sell_attr: float = 0.0
    sell_unattr: float = 0.0
    self_cost: float = 0.0
    n_warrants: int = 0
    n_held: int = 0
    n_expired: int = 0
    n_no_price: int = 0
    n_cost_unknown: int = 0
    last_buy_date: str | None = None
    first_date: str | None = None
    warrants: list[dict] = field(default_factory=list)
    #: 日期 → [仍持有張數, 仍持有成本, 當日標的收盤|None](跨權證合併)。
    buy_days: dict[str, list] = field(default_factory=dict)


def _leg_payload(leg: Leg, info: WarrantInfo | None, as_of: str) -> tuple[dict, str]:
    """一腿的輸出與它的估值狀態:valued / expired / no_price / cost_unknown / closed。"""
    if leg.price_missing:
        status = "cost_unknown"
    elif leg.pos <= 0:
        status = "closed"
    elif info and info.maturity_date and info.maturity_date < as_of:
        status = "expired"
    elif not info or info.last_price is None or info.last_price <= 0:
        status = "no_price"
    else:
        status = "valued"
    row: dict = {
        "lots": round(leg.pos),
        "cost": round(leg.cost),
        "buy_lots": round(leg.buy_lots),
        "sell_lots_attributed": round(leg.sell_attr),
        "sell_lots_unattributed": round(leg.sell_unattr),
        "realized": round(leg.realized),
        "status": status,
    }
    if leg.pos > 0 and leg.cost > 0:
        row["avg_cost"] = round(leg.cost / (leg.pos * SHARES_PER_LOT), 3)
    if leg.under_cost > 0:
        row["avg_under"] = round(leg.under_num / leg.under_cost, 2)
    if status == "valued" and info is not None and info.last_price is not None:
        value = leg.pos * info.last_price * SHARES_PER_LOT
        row["last_price"] = info.last_price
        row["value"] = round(value)
        row["unrealized"] = round(value - leg.cost)
    if leg.last_buy_date:
        row["last_buy_date"] = leg.last_buy_date
    return row, status


def _agg_payload(agg: _Agg) -> dict:
    out: dict = {
        "lots": round(agg.lots),
        "cost": round(agg.cost),
        "buy_lots": round(agg.buy_lots),
        "sell_lots_attributed": round(agg.sell_attr),
        "sell_lots_unattributed": round(agg.sell_unattr),
        "realized": round(agg.realized),
        "n_warrants": agg.n_warrants,
        "n_held": agg.n_held,
        "n_expired": agg.n_expired,
        "n_no_price": agg.n_no_price,
        "n_cost_unknown": agg.n_cost_unknown,
        "self_cost": round(agg.self_cost),
        "warrants": agg.warrants,
        # 進場日拆解(仍持有的部分):[日期, 張數, 成本, 當日標的收盤|null],依日期遞增;
        # 四捨五入後不到 1 張的日子不列(等比例縮到幾乎沒有)。
        "buy_days": [
            [d, round(v[0]), round(v[1]), v[2]]
            for d, v in sorted(agg.buy_days.items()) if round(v[0]) >= 1
        ],
    }
    if agg.under_cost > 0:
        out["avg_under"] = round(agg.under_num / agg.under_cost, 2)
    if agg.cost_valued > 0:
        out["cost_valued"] = round(agg.cost_valued)
        out["value"] = round(agg.value)
        out["unrealized"] = round(agg.value - agg.cost_valued)
        out["unrealized_pct"] = round((agg.value - agg.cost_valued) / agg.cost_valued * 100, 1)
    if agg.last_buy_date:
        out["last_buy_date"] = agg.last_buy_date
    if agg.first_date:
        out["first_date"] = agg.first_date
    return out


def warrant_positions(
    trades: Iterable[tuple[str, str, str, str, float, float | None]],
    *,
    warrant_info: Mapping[str, WarrantInfo],
    under_close: Mapping[tuple[str, str], float],
    as_of: str,
    self_issued: Callable[[str, str], bool] = lambda _branch, _warrant: False,
) -> dict[tuple[str, str], dict[str, dict]]:
    """逐列累計並依 (分點, 標的) → {"call": agg, "put": agg} 輸出(沒有那一邊就沒有鍵)。

    trades: (branch_name, underlying_id, warrant_id, date, net_lots, warrant_close),
            **同一腿內依日期遞增**(呼叫端 SQL ORDER BY);晚於 as_of 的列略過。
    warrant_info: warrant_id → WarrantInfo(kind、到期日、最後價)。沒有的權證整腿略過。
    under_close: (underlying_id, date) → 標的收盤;缺就不進換算均價。
    self_issued(branch_name, warrant_id): 這腿是分點自家集團發行的權證。
    """
    legs: dict[tuple[str, str, str], Leg] = {}
    for branch, underlying, warrant_id, date, net, close in trades:
        if date > as_of or warrant_id not in warrant_info:
            continue
        leg = legs.get((branch, underlying, warrant_id))
        if leg is None:
            leg = legs[(branch, underlying, warrant_id)] = Leg()
        leg.trade(date, float(net or 0), close, under_close.get((underlying, date)))

    aggs: dict[tuple[str, str], dict[str, _Agg]] = {}
    for (branch, underlying, warrant_id), leg in legs.items():
        if leg.first_date is None:
            continue
        info = warrant_info[warrant_id]
        row, status = _leg_payload(leg, info, as_of)
        row["warrant_id"] = warrant_id
        agg = aggs.setdefault((branch, underlying), {}).setdefault(info.kind, _Agg())
        agg.n_warrants += 1
        agg.buy_lots += leg.buy_lots
        agg.sell_attr += leg.sell_attr
        agg.sell_unattr += leg.sell_unattr
        if status == "cost_unknown":
            agg.n_cost_unknown += 1
            agg.warrants.append(row)
            continue
        agg.realized += leg.realized
        if leg.first_date and (agg.first_date is None or leg.first_date < agg.first_date):
            agg.first_date = leg.first_date
        if leg.last_buy_date and (agg.last_buy_date is None or leg.last_buy_date > agg.last_buy_date):
            agg.last_buy_date = leg.last_buy_date
        if leg.pos > 0:
            agg.n_held += 1
            agg.lots += leg.pos
            agg.cost += leg.cost
            agg.under_num += leg.under_num
            agg.under_cost += leg.under_cost
            for d, lots, cost, under in leg.buys:
                slot = agg.buy_days.setdefault(d, [0.0, 0.0, under])
                slot[0] += lots
                slot[1] += cost
                if slot[2] is None:
                    slot[2] = under
            if self_issued(branch, warrant_id):
                row["self"] = True
                agg.self_cost += leg.cost
            if status == "valued":
                agg.cost_valued += leg.cost
                agg.value += row["value"]
            elif status == "expired":
                agg.n_expired += 1
            else:
                agg.n_no_price += 1
        agg.warrants.append(row)

    out: dict[tuple[str, str], dict[str, dict]] = {}
    for key, by_kind in aggs.items():
        payload: dict[str, dict] = {}
        for kind in ("call", "put"):
            agg = by_kind.get(kind)
            if agg is None:
                continue
            agg.warrants.sort(key=lambda r: (-r["cost"], r["warrant_id"]))
            payload[kind] = _agg_payload(agg)
        if payload:
            out[key] = payload
    return out


def screening_rows(
    positions: Mapping[tuple[str, str], Mapping[str, dict]],
    *,
    names: Mapping[str, str],
    under_last: Mapping[str, tuple[str, float]],
    is_hq: Callable[[str], bool],
    min_cost: int = SCREEN_MIN_COST,
    max_rows: int = SCREEN_MAX_ROWS,
) -> tuple[list[dict], dict]:
    """全市場「仍持有(估)」清單:仍持有成本 ≥ min_cost 的 (分點, 標的, kind),帳面最差的在前。

    排除:自家發行占仍持有成本 ≥ 50%(發行商造市／避險),以及總公司席位且有任何自家
    發行持有;被排除的筆數回在 meta 裡,畫面要說出來。沒有估值(全部到期／無價)的列保留,
    但沒有 unrealized,排在最後。
    """
    rows: list[dict] = []
    excluded_self = 0
    for (branch, underlying), by_kind in positions.items():
        for kind, agg in by_kind.items():
            if agg["lots"] <= 0 or agg["cost"] < min_cost:
                continue
            self_pct = int(agg["self_cost"] * 100 // agg["cost"]) if agg["cost"] else 0
            if self_pct >= SCREEN_SELF_MAX_PCT or (agg["self_cost"] > 0 and is_hq(branch)):
                excluded_self += 1
                continue
            row = {
                "branch_name": branch,
                "underlying_id": underlying,
                "underlying_name": names.get(underlying, underlying),
                "kind": kind,
                "lots": agg["lots"],
                "cost": agg["cost"],
                "n_held": agg["n_held"],
                "n_unvalued": agg["n_expired"] + agg["n_no_price"],
                "self_pct": self_pct,
            }
            for k in ("value", "unrealized", "unrealized_pct", "avg_under", "last_buy_date", "first_date", "buy_days"):
                if k in agg:
                    row[k] = agg[k]
            if underlying in under_last:
                row["under_last_date"], row["under_last"] = under_last[underlying]
            rows.append(row)
    rows.sort(key=lambda r: (
        0 if "unrealized_pct" in r else 1,
        r.get("unrealized_pct", 0.0),
        -r["cost"],
        r["branch_name"],
        r["underlying_id"],
        r["kind"],
    ))
    meta = {"rows_total": len(rows), "excluded_self": excluded_self, "min_cost": min_cost}
    return rows[:max_rows], meta
