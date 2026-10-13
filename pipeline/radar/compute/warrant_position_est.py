"""權證分點持有估算 `wpos-avgcost-v1`(docs/51)。

一個分點在一檔標的的權證上「大概還抱著多少、成本多少、換算成現股大約在什麼價位、
帳面目前估算賺賠多少、是哪幾天進場的」。方法與 docs/42 的 `pnl-avgcost-v1` 同一套:只用
每檔權證每日前 15 大進出看得見的淨張數,當日權證收盤價當成交價,平均成本法;窗口起點視
為零持股,看不見的日子視為沒交易;賣超找不到對應持股的張數記為 unattributed,不放空。

與 docs/42 不同的兩件事:

* **每一腿 = (分點, 權證)**,再依標的、認購／認售加總成 (分點, 標的, kind)。認購與
  認售方向相反,永遠不混在同一個數字裡;牛熊證不進持有估算。
* 多了「換算現股均價」與「進場日」:每筆買超都記下**當天標的收盤價**,以該筆買超的金額
  加權平均;賣超依平均成本法把每個買超日的剩餘等比例扣減(沒有先進先出)。

**記憶體(2026-10-12 verifier)**:正式庫 120 日窗口有 ~490 萬列權證分點列,VPS 只有
1.7 GB。所以這裡是**串流**:呼叫端把列依 (標的, 分點, 權證, 日期) 排序餵進來,一腿處理完
就併進該 (標的, 分點) 的累計器,一組處理完就定稿成輸出 dict 丟掉工作區——常駐的只有輸出
本身,與列數無關。進場日用「縮放因子」維持:每筆買超存 (日索引, 張數÷S, 金額÷S),賣超只
改 S,不逐筆改。

這是估算,不是帳戶損益;券商分點不等於單一個人;權證有時間價值衰減;發行商自家權證多為
造市／避險(呼叫端用 self_issued 排除)。純函式,不碰 DB。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

DEFINITIONS_VERSION = "wpos-avgcost-v1"
SHARES_PER_LOT = 1000
#: 篩選清單(warrant_positions.json)的門檻:仍持有成本(估)≥ 500 萬才列。
SCREEN_MIN_COST = 5_000_000
#: 每一種(認購／認售)的每一邊(帳面為負／為正)各自最多留幾列;總數另外回報,畫面寫「顯示前 N / 共 M 筆」。
SCREEN_MAX_ROWS_PER_SIDE = 400
#: warrant_positions.json 的版本:v3 = 每種再分 down／up 兩邊(docs/51 §4)。
SCREEN_FILE_VERSION = 3
#: 自家發行占仍持有成本過半 → 視為發行商造市／避險,篩選清單排除。
SCREEN_SELF_MAX_PCT = 50
POSITION_KINDS = ("call", "put")
_SCALE_FLOOR = 1e-9


@dataclass(slots=True)
class WarrantInfo:
    """正式庫約 10.5 萬檔權證都要一個;slots 省約四成記憶體。"""
    kind: str                      # call / put / bull / bear / bull_ext / bear_ext
    maturity_date: str | None      # YYYY-MM-DD;None = 未知(不當成到期)
    last_price: float | None       # as_of 當日或之前(近 5 個交易日內)最後一個權證收盤
    last_price_date: str | None = None
    name: str | None = None        # 權證簡稱(呼叫端判斷發行商用)


class _Leg:
    """一個 (分點, 權證) 的平均成本法累計器;一次只活一個(列已依腿排序)。"""
    __slots__ = ("pos", "cost", "under_num", "under_cost", "realized", "buy_lots", "sell_attr",
                 "sell_unattr", "last_buy_date", "traded", "price_missing",
                 "scale", "buy_idx", "buy_lots_raw", "buy_cost_raw")

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.pos = self.cost = self.under_num = self.under_cost = self.realized = 0.0
        self.buy_lots = self.sell_attr = self.sell_unattr = 0.0
        self.last_buy_date: str | None = None
        self.traded = False
        self.price_missing = False
        self.scale = 1.0
        self.buy_idx: list[int] = []
        self.buy_lots_raw: list[float] = []
        self.buy_cost_raw: list[float] = []

    def _clear_buys(self) -> None:
        self.scale = 1.0
        self.buy_idx = []
        self.buy_lots_raw = []
        self.buy_cost_raw = []

    def trade(self, date: str, day_idx: int, net_lots: float, price: float | None,
              under_close: float | None) -> None:
        if not net_lots:
            return
        self.traded = True
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
            if self.buy_idx and self.buy_idx[-1] == day_idx:
                self.buy_lots_raw[-1] += net_lots / self.scale
                self.buy_cost_raw[-1] += amount / self.scale
            else:
                self.buy_idx.append(day_idx)
                self.buy_lots_raw.append(net_lots / self.scale)
                self.buy_cost_raw.append(amount / self.scale)
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
                self.scale *= 1.0 - frac
                if self.pos <= _SCALE_FLOOR or self.scale <= _SCALE_FLOOR:
                    self.pos = self.cost = self.under_num = self.under_cost = 0.0
                    self._clear_buys()
            self.sell_attr += sold
            self.sell_unattr += -net_lots - sold

    def buys(self) -> Iterable[tuple[int, float, float]]:
        s = self.scale
        return zip(self.buy_idx, (x * s for x in self.buy_lots_raw), (x * s for x in self.buy_cost_raw))


class _Agg:
    """一個 (分點, 標的, kind) 的工作區;一組處理完就定稿成 dict。"""
    __slots__ = ("lots", "cost", "cost_valued", "value", "under_num", "under_cost", "realized",
                 "buy_lots", "sell_attr", "sell_unattr", "self_cost", "n_warrants", "n_held",
                 "n_expired", "n_no_price", "n_cost_unknown", "last_buy_date", "first_date", "buy_days")

    def __init__(self) -> None:
        self.lots = self.cost = self.cost_valued = self.value = 0.0
        self.under_num = self.under_cost = self.realized = 0.0
        self.buy_lots = self.sell_attr = self.sell_unattr = self.self_cost = 0.0
        self.n_warrants = self.n_held = self.n_expired = self.n_no_price = self.n_cost_unknown = 0
        self.last_buy_date: str | None = None
        self.first_date: str | None = None
        self.buy_days: dict[int, list[float]] = {}   # day_idx → [lots, cost]


def leg_status(leg: _Leg, info: WarrantInfo, as_of: str) -> str:
    if leg.price_missing:
        return "cost_unknown"
    if leg.pos <= 0:
        return "closed"
    if info.maturity_date and info.maturity_date < as_of:
        return "expired"
    if info.last_price is None or info.last_price <= 0:
        return "no_price"
    return "valued"


def round_buy_days(days: list[tuple[str, float, float, float | None]], total_lots: int,
                   total_cost: int) -> list[list]:
    """進場日四捨五入:最大餘數法讓 Σ張數 = 仍持有(四捨五入後),Σ成本 = 仍持有成本;
    分不到 1 張的日子併入前一天(第一天就併入下一天),不丟。

    days: [(日期, 張數, 成本, 當日標的收盤|None)] 依日期遞增。
    """
    if not days or total_lots <= 0:
        return []
    floors = [int(x[1]) for x in days]
    rem = total_lots - sum(floors)
    if rem > 0:
        order = sorted(range(len(days)), key=lambda i: (-(days[i][1] - floors[i]), i))
        for i in order[:rem]:
            floors[i] += 1
    elif rem < 0:   # 浮點累積讓 Σfloor 超過總數:從最小餘數的日子扣回
        order = sorted(range(len(days)), key=lambda i: ((days[i][1] - floors[i]), -i))
        for i in order[:-rem]:
            floors[i] -= 1
    costs = [round(x[2]) for x in days]
    out: list[list] = []
    for (d, _l, _c, under), lots, cost in zip(days, floors, costs):
        if lots <= 0:
            if out:
                out[-1][2] += cost
            else:
                out.append([d, 0, cost, under])   # 暫存,下一個有張數的日子會收走
            continue
        if out and out[-1][1] == 0:
            cost += out.pop()[2]
        out.append([d, lots, cost, under])
    if out and out[-1][1] == 0:    # 全部分不到 1 張(理論上 total_lots>0 時不會)
        out = []
    if out:
        out[-1][2] += total_cost - sum(x[2] for x in out)
    return out


#: 篩選摘要(每 (分點, 標的, kind) 一個 tuple;只留 scalar,進場日是已序列化的 JSON 字串)。
SUMMARY_FIELDS = ("lots", "cost", "n_held", "n_expired", "n_no_price", "self_cost", "cost_valued", "value",
                  "unrealized", "unrealized_pct", "avg_under", "last_buy_date", "first_date")
#: 進場日最多存幾天(依張數最大),其餘併成 buy_days_rest(verifier 2026-10-12:最壞情況每腿天天有交易)。
ENTRY_DAYS_MAX = 20


class PositionStream:
    """依 (標的, 分點, 權證, 日期) 排序的列 → 每檔標的一段**已序列化**的 JSON(`branches` 物件)。

    用法:`consume(rows)`(或逐列 `feed()`)、最後 `finish()`;結果在 `stock_json[sid]`
    (字串,呼叫端直接拼進分片),篩選用摘要在 `summaries`(tuple)。測試用 `by_stock`(解回 dict)。
    常駐記憶體 = 每檔一段 JSON 字串 + 摘要 tuple + 一腿 + 一組的工作區;與列數無關。
    """

    def __init__(
        self,
        *,
        warrant_info: Mapping[str, WarrantInfo],
        under_close: Mapping[tuple[str, str], float],
        as_of: str,
        self_issued: Callable[[str, str], bool] = lambda _branch, _warrant: False,
        screen_min_cost: int = SCREEN_MIN_COST,
        under_close_by_sid: Mapping[str, Mapping[str, float]] | None = None,
    ) -> None:
        self.warrant_info = warrant_info
        # 只留巢狀版(標的 → 日期 → 收盤):主迴圈一列省掉一個 tuple 配置;呼叫端可直接給巢狀的
        # (export 這樣做,不必再多留一份扁平 dict)。
        if under_close_by_sid is not None:
            self._under_by_sid: Mapping[str, Mapping[str, float]] = under_close_by_sid
        else:
            nested: dict[str, dict[str, float]] = {}
            for (sid, day), close in under_close.items():
                nested.setdefault(sid, {})[day] = close
            self._under_by_sid = nested
        self.as_of = as_of
        self.self_issued = self_issued
        self.screen_min_cost = screen_min_cost
        self.stock_json: dict[str, str] = {}
        self.summaries: list[tuple] = []      # (branch, sid, kind, *SUMMARY_FIELDS, buy_days_json)
        self._dates: list[str] = []
        self._day_idx: dict[str, int] = {}
        self._group: tuple[str, str] | None = None
        self._aggs: dict[str, _Agg] = {}
        self._leg_key: tuple[str, str, str] | None = None
        self._leg = _Leg()
        self._stock: str | None = None
        self._stock_parts: list[str] = []     # 目前這檔標的已定稿的「"券商":{...}」片段

    @property
    def by_stock(self) -> dict[str, dict[str, dict[str, dict]]]:
        """測試／小量用:解回 dict。"""
        return {sid: json.loads(s) for sid, s in self.stock_json.items()}

    # ---- 餵列 ----
    def feed(self, underlying: str, branch: str, warrant_id: str, date: str,
             net_lots: float, close: float | None) -> None:
        self.consume(((underlying, branch, warrant_id, date, net_lots, close),))

    def consume(self, rows: Iterable[tuple[str, str, str, str, float, float | None]]) -> None:
        """主迴圈:正式庫一輪數百萬列,所以把常用的東西放在區域變數、一列只做一次方法呼叫。"""
        wi = self.warrant_info
        under_by_sid = self._under_by_sid
        empty: dict[str, float] = {}
        as_of = self.as_of
        kinds = POSITION_KINDS
        day_idx = self._day_idx
        dates = self._dates
        leg = self._leg
        trade = leg.trade
        cur = self._leg_key
        cur_sid, cur_branch, cur_wid = cur if cur else (None, None, None)
        uc_sid = under_by_sid.get(cur_sid, empty) if cur_sid else empty
        for sid, branch, wid, date, net, close in rows:
            if not net or date > as_of:
                continue
            info = wi.get(wid)
            if info is None or info.kind not in kinds:
                continue
            if wid != cur_wid or branch != cur_branch or sid != cur_sid:
                self._leg_key = (cur_sid, cur_branch, cur_wid) if cur_wid is not None else None
                self._flush_leg()
                if sid != cur_sid or branch != cur_branch:
                    self._flush_group()
                    if sid != self._stock:
                        self._flush_stock()      # 換標的:上一檔的 branches 立刻合成一段 JSON
                    self._group = (sid, branch)
                    uc_sid = under_by_sid.get(sid, empty)
                cur_sid, cur_branch, cur_wid = sid, branch, wid
            idx = day_idx.get(date)
            if idx is None:
                idx = day_idx[date] = len(dates)
                dates.append(date)
            trade(date, idx, net, close, uc_sid.get(date))
        self._leg_key = (cur_sid, cur_branch, cur_wid) if cur_wid is not None else None

    def finish(self) -> None:
        self._flush_leg()
        self._flush_group()
        self._flush_stock()

    # ---- 內部 ----
    def _flush_leg(self) -> None:
        leg, key = self._leg, self._leg_key
        self._leg_key = None
        if key is None or not leg.traded:
            leg.reset()
            return
        underlying, branch, warrant_id = key
        info = self.warrant_info[warrant_id]
        status = leg_status(leg, info, self.as_of)
        agg = self._aggs.get(info.kind)
        if agg is None:
            agg = self._aggs[info.kind] = _Agg()
        agg.n_warrants += 1
        if status == "cost_unknown":
            # 成本不可信的腿不進任何數字(連買賣張數也不進,否則卡上的張數對不起來)。
            agg.n_cost_unknown += 1
            leg.reset()
            return
        agg.buy_lots += leg.buy_lots
        agg.sell_attr += leg.sell_attr
        agg.sell_unattr += leg.sell_unattr
        agg.realized += leg.realized
        first = self._dates[leg.buy_idx[0]] if leg.buy_idx else None
        if leg.last_buy_date and (agg.last_buy_date is None or leg.last_buy_date > agg.last_buy_date):
            agg.last_buy_date = leg.last_buy_date
        if first and (agg.first_date is None or first < agg.first_date):
            agg.first_date = first
        if leg.pos > 0:
            agg.n_held += 1
            agg.lots += leg.pos
            agg.cost += leg.cost
            agg.under_num += leg.under_num
            agg.under_cost += leg.under_cost
            for idx, lots, cost in leg.buys():
                slot = agg.buy_days.get(idx)
                if slot is None:
                    agg.buy_days[idx] = [lots, cost]
                else:
                    slot[0] += lots
                    slot[1] += cost
            if self.self_issued(branch, warrant_id):
                agg.self_cost += leg.cost
            if status == "valued":
                agg.cost_valued += leg.cost
                agg.value += leg.pos * info.last_price * SHARES_PER_LOT   # type: ignore[operator]
            elif status == "expired":
                agg.n_expired += 1
            else:
                agg.n_no_price += 1
        leg.reset()

    def _flush_group(self) -> None:
        group, aggs = self._group, self._aggs
        self._group, self._aggs = None, {}
        if group is None or not aggs:
            return
        underlying, branch = group
        if underlying != self._stock:
            self._flush_stock()
            self._stock = underlying
        payload: dict[str, dict] = {}
        for kind in POSITION_KINDS:
            agg = aggs.get(kind)
            if agg is None:
                continue
            payload[kind] = out = self._agg_payload(agg, underlying)
            if out["lots"] > 0 and out["cost"] >= self.screen_min_cost:
                # 只留 scalar;進場日等篩選定案後再從 stock_json 解回來(最多 800 列,摘要可能有數萬筆)。
                self.summaries.append((branch, underlying, kind, *(out.get(k) for k in SUMMARY_FIELDS)))
        if payload:
            # 立刻序列化、丟掉 dict:正式機數萬個 (券商, 標的),dict 比字串貴好幾倍。
            self._stock_parts.append(
                f"{json.dumps(branch, ensure_ascii=False)}:{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}")

    def _flush_stock(self) -> None:
        if self._stock is not None and self._stock_parts:
            self.stock_json[self._stock] = "{" + ",".join(self._stock_parts) + "}"
        self._stock = None
        self._stock_parts = []

    def _agg_payload(self, agg: _Agg, underlying: str) -> dict:
        lots = round(agg.lots)
        cost = round(agg.cost)
        out: dict = {
            "lots": lots,
            "cost": cost,
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
        # 日索引是「第一次遇到」的順序,不是時間順序(後面的腿可能帶進更早的日期),所以依日期字串排。
        uc_sid = self._under_by_sid.get(underlying, {})
        days = sorted(
            ((self._dates[idx], v[0], v[1], uc_sid.get(self._dates[idx]))
             for idx, v in agg.buy_days.items()),
            key=lambda x: x[0],
        )
        rounded = round_buy_days(days, lots, cost) if lots > 0 else []
        if len(rounded) > ENTRY_DAYS_MAX:
            # 只存張數最大的 ENTRY_DAYS_MAX 天(平手取較早),其餘併成一段摘要;Σ 仍等於仍持有。
            keep = sorted(sorted(range(len(rounded)), key=lambda i: (-rounded[i][1], i))[:ENTRY_DAYS_MAX])
            keep_set = set(keep)
            rest = [r for i, r in enumerate(rounded) if i not in keep_set]
            out["buy_days"] = [rounded[i] for i in keep]
            out["buy_days_rest"] = {
                "n": len(rest),
                "lots": sum(r[1] for r in rest),
                "cost": sum(r[2] for r in rest),
                "first": rest[0][0],
                "last": rest[-1][0],
            }
        else:
            out["buy_days"] = rounded
        return out


def warrant_positions(
    trades: Iterable[tuple[str, str, str, str, float, float | None]],
    *,
    warrant_info: Mapping[str, WarrantInfo],
    under_close: Mapping[tuple[str, str], float],
    as_of: str,
    self_issued: Callable[[str, str], bool] = lambda _branch, _warrant: False,
) -> dict[tuple[str, str], dict[str, dict]]:
    """測試／小量用的方便包裝:先依 (標的, 分點, 權證, 日期) 穩定排序再串流。

    trades: (branch_name, underlying_id, warrant_id, date, net_lots, warrant_close)。
    回傳 {(branch, underlying): {"call": agg, "put": agg}}。
    """
    stream = PositionStream(warrant_info=warrant_info, under_close=under_close, as_of=as_of,
                            self_issued=self_issued, screen_min_cost=0)
    stream.consume(
        (sid, branch, wid, date, net, close)
        for branch, sid, wid, date, net, close in sorted(trades, key=lambda t: (t[1], t[0], t[2], t[3]))
    )
    stream.finish()
    return {
        (branch, sid): payload
        for sid, by_branch in stream.by_stock.items()
        for branch, payload in by_branch.items()
    }


def summary_from_agg(branch: str, underlying: str, kind: str, agg: Mapping) -> tuple:
    """測試用:把一個 agg dict 變成 `PositionStream.summaries` 的 tuple 形狀。"""
    return (branch, underlying, kind, *(agg.get(k) for k in SUMMARY_FIELDS))


def screening_rows(
    summaries: Iterable[tuple],
    *,
    names: Mapping[str, str],
    under_last: Mapping[str, tuple[str, float]],
    is_hq: Callable[[str], bool],
    min_cost: int = SCREEN_MIN_COST,
    max_rows: int = SCREEN_MAX_ROWS_PER_SIDE,
    entry_days: Callable[[str, str, str], tuple[list, dict | None]] | None = None,
) -> dict[str, dict]:
    """全市場「仍持有(估)」清單,**認購／認售各自一份、每份再分帳面為負／為正兩邊**(v3):
    仍持有成本 ≥ min_cost;

    * `down`:帳面 % ≤ 0,最差的在前;估不出值的(全部到期／無價)接在最後(與 v2 相同)。
    * `up`:帳面 % > 0,最好的在前;估不出值的不進來(不能宣稱它帳面為正)。

    每邊各留前 max_rows 列,`total` 是該邊門檻內全部筆數,畫面寫「顯示前 N / 共 M 筆」。
    排除:自家發行占仍持有成本 ≥ 50%(發行商造市／避險),以及總公司席位且有任何自家發行
    持有;被排除的筆數每種各自回在 `excluded_self`(兩邊共用,排除與帳面正負無關)。
    entry_days(branch, sid, kind) → (buy_days, buy_days_rest|None):只對留下來的列呼叫。
    """
    kinds: dict[str, dict] = {k: _empty_screen_bucket() for k in POSITION_KINDS}
    for summary in summaries:
        branch, underlying, kind = summary[0], summary[1], summary[2]
        agg = dict(zip(SUMMARY_FIELDS, summary[3:]))
        if kind not in kinds or agg["lots"] <= 0 or agg["cost"] < min_cost:
            continue
        self_pct = int(agg["self_cost"] * 100 // agg["cost"]) if agg["cost"] else 0
        if self_pct >= SCREEN_SELF_MAX_PCT or (agg["self_cost"] > 0 and is_hq(branch)):
            kinds[kind]["excluded_self"] += 1
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
        for k in ("cost_valued", "value", "unrealized", "unrealized_pct", "avg_under",
                  "last_buy_date", "first_date"):
            if agg.get(k) is not None:
                row[k] = agg[k]
        if underlying in under_last:
            row["under_last_date"], row["under_last"] = under_last[underlying]
        pct = row.get("unrealized_pct")
        kinds[kind]["up" if pct is not None and pct > 0 else "down"]["rows"].append(row)
    for bucket in kinds.values():
        down, up = bucket["down"], bucket["up"]
        down["rows"].sort(key=lambda r: (
            0 if "unrealized_pct" in r else 1,
            r.get("unrealized_pct", 0.0),
            -r["cost"],
            r["branch_name"],
            r["underlying_id"],
        ))
        up["rows"].sort(key=lambda r: (-r["unrealized_pct"], -r["cost"], r["branch_name"], r["underlying_id"]))
        for side in (down, up):
            side["total"] = len(side["rows"])
            kept = side["rows"][:max_rows]
            if entry_days is not None:
                for r in kept:   # 只有留下的列才把進場日解回來
                    days, rest = entry_days(r["branch_name"], r["underlying_id"], r["kind"])
                    r["buy_days"] = days
                    if rest:
                        r["buy_days_rest"] = rest
            side["rows"] = kept
    return kinds


def _empty_screen_bucket() -> dict:
    return {"excluded_self": 0, "down": {"rows": [], "total": 0}, "up": {"rows": [], "total": 0}}


def empty_screening() -> dict[str, dict]:
    """沒有資料時的 kinds(與 screening_rows 同形)。"""
    return {k: _empty_screen_bucket() for k in POSITION_KINDS}


def entry_days_lookup(stock_json: Mapping[str, str]) -> Callable[[str, str, str], tuple[list, dict | None]]:
    """從 `PositionStream.stock_json` 解回某 (分點, 標的, kind) 的進場日;同一檔只解一次(有快取)。"""
    cache: dict[str, dict] = {}

    def lookup(branch: str, sid: str, kind: str) -> tuple[list, dict | None]:
        parsed = cache.get(sid)
        if parsed is None:
            parsed = cache[sid] = json.loads(stock_json.get(sid, "{}"))
        agg = parsed.get(branch, {}).get(kind, {})
        return agg.get("buy_days", []), agg.get("buy_days_rest")

    return lookup
