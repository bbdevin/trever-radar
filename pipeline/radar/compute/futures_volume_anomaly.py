"""個股期貨成交量異常的 **export 切片**(docs/38 §4 步驟 5)。

它為什麼可以存在
----------------
``docs/38`` 是一份事前登記,它的 §3 寫著「過不了就整個功能不上線」。這個模組只在
battery 判 SHIP 之後才被寫出來:

    as_of 2026-09-17,run 1,250 個期貨交易日,485,686 列,320/320 契約乘數已知
    檢定 A:|F_only| = 680 >= 30                                     PASS
    檢定 B:十組 seed 全部過 2 sigma(h_F = 141/680;安慰劑 h_P 43-67)  PASS
    裁決:a_and_b_passed -> SHIP

證據committed 在 ``docs/evidence/futures-volume-battery-20260921.json``。

它為什麼不自己算
----------------
**被檢定過的是 battery 那條規則,不是「一條長得很像 battery 的規則」。**
旗標與那五個事實一律從 :mod:`radar.compute.futures_volume_battery` 取:窗口用它的
:func:`~radar.compute.futures_volume_battery.comparison_window`,否決與旗標用它的
:func:`~radar.compute.futures_volume_battery.evaluate_contract_day`,未平倉差用它的
:func:`~radar.compute.futures_volume_battery.oi_change`,R4 排除日用
:mod:`radar.compute.settlement_calendar`,連讀資料的那幾句 SQL 都是同一份。
這個模組自己負責的只有三件 battery 沒有的事:**挑出 as_of 那一天**、把結果掛到
契約上、以及把 §4 步驟 5 的兩段文字填好。若有人在這裡重寫一次規則,上線的就會是
一條沒有被 §3 檢定過的規則,而它還穿著 battery 的外衣——事前登記整份文件存在的
理由正是要擋這件事。

它輸出什麼
----------
``futures.contracts[].anomaly`` 底下 §1 表格的**五個整數鍵**,一個不多:
``today`` / ``window_max`` / ``window_median`` / ``oi_change`` / ``window_days``。
沒有比率、均值、名次、分數、z——除法由讀的人自己做(§1)。

沒有 ``anomaly`` 區塊 = **沒有主張**,與 ``futures`` 鍵本身的三態約定同一個習慣。
被 §2 否決(R1 窗口缺口、R2a 中位數為 0、R2b 乘數未知/現貨缺口/不實質)與
「規則看過了但沒創高」在輸出上不可分辨,也不該分辨:兩者都不是一個異常。
絕不用 0 或 null 去冒充其中任何一種。

另外由 :func:`anomaly_index` 把**同一次**計算的結果排成市場層級的清單(§7.5)。
那是純粹的重新排列,不是第二次計算:§1 要的是「名單短到能逐檔看」,§5 要的是
「今天 − 前高」的順序,兩者都不需要、也不允許再跑一次規則。
"""
from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import text

from .futures_volume_battery import (
    FORWARD_SPOT_DAYS,
    WINDOW_DAYS,
    anomaly_facts,
    comparison_window,
    evaluate_contract_day_in_calendar,
    forward_spot_days,
    load_contracts,
    load_futures_calendar,
    load_market_days,
    load_regular_session_volumes,
    load_spot_daily,
    spot_new_high,
)
from .settlement_calendar import settlement_exclusion_set, settlement_is_determinable

# 觸發理由與風險提醒各一個代碼,形狀同 ``indicators.score_technical`` 產出的
# ``{"code": ..., "text": ...}``。這裡沒有 ``points``:異常旗標不進任何分數,
# §5 明文不做跨契約排序,給它一個分數等於偷偷建立一個名次。
REASON_CODE = "F1_FUTURES_VOLUME_60D_HIGH"
RISK_CODE = "R_FUTURES_VOLUME_NO_DIRECTION"


def reason_text(*, code: str, facts: dict[str, int]) -> str:
    """§4 步驟 5 的觸發理由範本,逐字。

    ``oi_change`` 被省略時(任一邊為 NULL,§1 表格),連同它那個子句一起拿掉,
    句子在「新高(...)」之後收尾。範本沒有寫這個情況;把未知的未平倉印成
    ``+0`` 會把「沒公布」講成「一口都沒變」,而那是本專案在每一處都拒絕的塌陷。
    """
    head = (
        f"{code} 期貨一般時段成交 {facts['today']} 口,"
        f"創 {facts['window_days']} 個比較日新高"
        f"(前高 {facts['window_max']} 口、中位數 {facts['window_median']} 口)"
    )
    if "oi_change" not in facts:
        return head + "。"
    return head + f",未平倉較前日 {facts['oi_change']:+} 口。"


def risk_text(*, spot_new_high_today: bool | None) -> str:
    """§4 步驟 5 的風險提醒範本,逐字。

    範本的 ``{有/無}`` 只有兩個選項,但現貨旗標有三態:該股不足 60 個現貨交易日、
    或窗口內有一天沒有量,答案就是**不知道**(見
    :func:`~radar.compute.futures_volume_battery.spot_new_high`)。不知道的時候
    整個子句拿掉,句子在「盤後未計」之後收尾——把未知寫成「無同步創高」是一個
    憑空的否定主張,比少講一句話糟。
    """
    head = "量創高不代表方向;結算週已排除;盤後未計"
    if spot_new_high_today is None:
        return head + "。"
    return head + f";現貨當日{'有' if spot_new_high_today else '無'}同步創高。"


def futures_volume_anomalies(
    conn, as_of: str, *, market_days_as_of: str | None = None,
) -> dict[str, dict[str, Any]] | None:
    """``{contract_code: {"anomaly": {...}, "reasons": [...], "risks": [...]}}``。

    只有**當天真的舉旗**的契約會出現在回傳值裡;被否決的、以及被規則看過但沒創高
    的,一律不出現(呼叫端因此什麼都不加,= 沒有主張)。

    回傳 ``None`` 與回傳 ``{}`` 是**兩件不同的事**:

    * ``None`` = 這一天根本沒有算過——``as_of`` 沒有期貨資料(TAIFEX 落後 export
      日是常態,見 §7.8)。沒有算過就不該有任何主張,連「今天沒有異常」都不該有。
    * ``{}``   = 算過了,今天沒有契約舉旗。這是一個**有日期的正面主張**。

    ``as_of`` 落在 R4 結算窗口內、或比較窗口湊不滿 60 天時回傳 ``{}``:規則看過了
    而且對每一個契約同時否決,而 §2 的否決與「看過但沒創高」在輸出上本來就刻意
    不可分辨(§7.7)。

    ``market_days_as_of``(§7.13):市場日日曆要讀到哪一天。R4 的排除窗口是往
    **未來**看的(結算日與其前 3 個市場日),所以日曆多一天就多一天的先見之明;
    export 的現貨日比期貨日新一天,把那一天給進來是白拿的。預設沿用 ``as_of``。
    日曆答不出候選日的結算窗口時整個回傳 ``None``——**不可判定就不主張**,
    絕不當成「沒有被排除」(§7.13)。
    """
    futures_days = load_futures_calendar(conn, as_of)
    if not futures_days or futures_days[-1] != as_of:
        # 期貨資料還沒跟上 export 日。沒有那一天的量就沒有那一天的主張——
        # 這是「沒有算」,不是「算過而且沒有」。
        return None
    market_days = load_market_days(conn, market_days_as_of or as_of)
    if not settlement_is_determinable(candidate=as_of, market_days=market_days):
        # R4 的排除窗口在這本日曆上算不出來。算不出來不是「沒有被排除」:
        # 那會讓上線的規則在日曆邊緣比被檢定過的規則寬鬆(§7.13)。
        return None
    excluded = settlement_exclusion_set(
        date_from=futures_days[0], date_to=as_of, market_days=market_days,
    )
    if as_of in excluded:
        # R4:結算日與其前 3 個市場日不得上榜(候選側的排除)。
        return {}
    excluded_frozen = frozenset(excluded)
    window = comparison_window(
        candidate=as_of, futures_days=futures_days, excluded=excluded_frozen,
    )
    if window is None:
        # R1:湊不滿 60 個比較日。窗口不縮短,整天沒有人有資格。
        return {}

    contracts = load_contracts(conn)
    # 窗口與契約無關(它只看期貨日曆與排除日),所以 window[0] 是每一個契約都夠用的
    # 讀取下界:期貨側剛好蓋住 W,現貨側蓋住的是該股真實日曆的一段連續尾巴。
    per_contract = load_regular_session_volumes(conn, as_of, date_from=window[0])
    spot = load_spot_daily(
        conn,
        as_of=as_of,
        stock_ids=[contract["stock_id"] for contract in contracts],
        date_from=window[0],
    )

    anomalies: dict[str, dict[str, Any]] = {}
    for contract in contracts:
        code = contract["contract_code"]
        daily = per_contract.get(code)
        if daily is None or as_of not in daily["volume"]:
            # 缺列 ≠ 0 口(R1 的同一條理由):今天沒有一般時段列就沒有 V(c, t)。
            continue
        spot_days, spot_volumes = spot.get(contract["stock_id"], (None, None))
        outcome = evaluate_contract_day_in_calendar(
            candidate=as_of,
            futures_days=futures_days,
            excluded=excluded_frozen,
            volumes=daily["volume"],
            open_interest=daily["open_interest"],
            multiplier=contract["contract_multiplier"],
            spot_volumes=spot_volumes,
        )
        facts = anomaly_facts(outcome)
        if facts is None:
            continue
        today_spot_high = (
            None if spot_days is None
            else spot_new_high(stock_days=spot_days, volumes=spot_volumes, day=as_of)
        )
        anomalies[code] = {
            "anomaly": facts,
            "reasons": [{"code": REASON_CODE, "text": reason_text(code=code, facts=facts)}],
            "risks": [{"code": RISK_CODE,
                       "text": risk_text(spot_new_high_today=today_spot_high)}],
            # docs/38 §7.17(2026-10-02):現貨當日有沒有同步創高,結構化地給前端。
            # 檢定 B 證明的是 F_only——期貨創高而**現貨還沒跟上**——所以這是讀這個
            # 旗標時最重要的一個位元;以前它只寫在風險句的最後一個子句裡。三態:
            # true / false / null(現貨窗口不足,不知道)。與風險句用的是同一個值。
            "spot_new_high": today_spot_high,
        }
    return anomalies


def anomaly_index(
    anomalies: dict[str, dict[str, Any]] | None,
    *,
    stock_id_by_code: dict[str, str],
    multiplier_by_code: dict[str, int | None] | None = None,
) -> list[dict[str, Any]] | None:
    """市場層級的今日名單(§7.5)。``{stock_id, code, multiplier, anomaly, reasons, risks,
    spot_new_high}``。

    ``multiplier``(docs/38 §7.19)是契約乘數(股/口),給前端把代碼換成白話的
    「個股期貨 / 小型個股期貨」。舉旗的契約乘數一定已知(R2b 的前置條件),乘數
    未知時鍵整個不輸出,不寫 null。它只是契約的身分,不是一個排序或比較用的數字。

    三態與 ``futures`` 鍵同一個約定,而且三態就是 :func:`futures_volume_anomalies`
    的三態:``None``(沒算)進來就 ``None``(呼叫端整個鍵不輸出),``{}``(算了、
    今天沒有)進來就是空陣列——一個有日期的「今日無異常」。

    順序是 ``today − window_max`` 由大到小,同分用 ``code`` 由小到大;後者只為了
    檔案可重現,不是一條經濟意義。這是**順序,不是名次**:§5 明文不做跨契約排序,
    所以這裡不輸出 rank / position / score 之類的鍵,讀的人拿到的是一份短名單。

    一檔股票可以有兩個不同乘數的契約(1565 的 MYF 與 OMF),兩個可以同一天都舉旗;
    單位是契約,所以絕不依股票去重。
    """
    if anomalies is None:
        return None
    multipliers = multiplier_by_code or {}
    entries = [
        {
            "stock_id": stock_id_by_code[code], "code": code,
            **({"multiplier": multipliers[code]}
               if multipliers.get(code) is not None else {}),
            **payload,
        }
        for code, payload in anomalies.items()
        if code in stock_id_by_code
    ]
    entries.sort(key=lambda entry: (
        -(entry["anomaly"]["today"] - entry["anomaly"]["window_max"]), entry["code"],
    ))
    return entries


def anomaly_index_meta(
    index: list[dict[str, Any]] | None, *, as_of: str,
) -> dict[str, Any] | None:
    """市場層級名單的隨附事實:``{"as_of": ..., "window_days": WINDOW_DAYS}``。

    ``as_of``(docs/38 §7.12)是**這份名單講的是哪一天**——期貨行情日,不是
    ``radar.json`` 的 ``data_date``。兩者常態差一個交易日(21:20 那一輪拿到的是
    前一天的完整報告),所以名單自己必須帶日期:少了它,UI 只剩下頁面的現貨日
    可用,而那句話會把期貨的結果掛在錯的日子上。日期是**明講的**,不是從條目裡
    推出來的——空名單那一態一個條目都沒有,推不出任何東西。

    **為什麼需要它**:§7.10 規定 UI 要講「N 個比較日」時一律讀 payload,不准在前端
    寫死 60。但 §7.5 的第二態(**有鍵、空陣列**)是一個有日期的正面主張——「算過了,
    今天沒有契約舉旗」——而那一態裡一個 ``anomaly`` 區塊都沒有,前端無處可讀。
    沒有這個鍵,那句話就只能少講比較窗口(弱)或在前端寫死 60(§7.10 禁止)。

    **為什麼是平行的鍵而不是把名單包進物件**:``radar.json`` 既有的習慣就是
    ``strategies`` 與 ``strategy_meta`` 這種「清單 + 同名的隨附事實」兩個平行鍵。
    更重要的是三態:§7.5 的「**沒有這個鍵**」必須是一個真的不存在的鍵。把陣列包進
    物件之後,「沒算過」與「算過但是空的」就要靠物件裡面某個欄位去分辨,而那正是
    §7.5 點名不可以塌掉的那條界線。名單這個鍵的三態因此**一個字都沒有動**。

    ``index is None``(沒有算過)→ ``None``:呼叫端兩個鍵一起不輸出。meta 由名單
    本身導出,所以結構上不可能在名單缺席時單獨出現一個孤兒 ``window_days``。

    數字來自 :data:`~radar.compute.futures_volume_battery.WINDOW_DAYS` 本人。
    §3.5 把 60 凍結了;在這裡另寫一個字面的 60,就是造出第二個可以各自漂移的真相。
    """
    if index is None:
        return None
    return {"as_of": as_of, "window_days": WINDOW_DAYS}


# ── 近 N 個期貨交易日的舉旗紀錄(docs/38 §7.19,post-data,只動呈現)─────────────
#
# 使用者要的是「之前舉過旗的,後來現貨有沒有跟上」。這一段**不新增任何規則**:
# 每一天都呼叫上面那個 ``futures_volume_anomalies`` 本人(battery 的規則),之後
# 補三個「事後才知道」的欄位,而那三個欄位用的也是 battery 自己的
# ``forward_spot_days`` 與 ``spot_new_high``——與 §3 檢定 B 的「之後 5 個現貨交易日
# 內現貨量創 60 日新高」是同一個問題、同一套函式。
#
# **價格只給原始觀測值,不給任何除法**(使用者 2026-10-03:「用點位看…漲了幾%跌了
# 幾%」;reviewer 裁定加 ``spot_after``)。docs/40 第 1 次執行量過,F_only 之後第二個
# 交易日漲 ≥3% 81 次、跌 ≥3% 112 次(共 551 次)——它預告的是**波動**不是上漲。
# 所以 ``spot_after`` 只有現貨收盤、之後最高/最低與天數,永遠同時給上下兩邊;百分比
# 由前端在單一個純函式裡算給人看,payload 裡沒有比率、報酬、名次,也不依它排序。
# 價格是**現貨**(daily_prices),不是期貨結算價;未經還原(窗內有除權息就標出來)。
#
# **這是今天重算的,不是「那一天頁面上顯示的東西」**:日曆、R4 結算窗口、比較窗口
# 都是用今天的資料重算。兩者在絕大多數日子相同,但不保證(例:某天的期貨列是後來
# 才補進來的)。前端的說明句講明這一點。

HISTORY_DAYS = 10

# 條目的鍵集合,一個不多(``spot_followed_on`` 只在 ``spot_followed`` 為真時出現,
# ``multiplier`` 只在乘數已知時出現——舉旗的契約乘數一定已知)。
HISTORY_ENTRY_KEYS = (
    "stock_id", "code", "multiplier", "anomaly", "reasons", "risks", "spot_new_high",
    "spot_followed", "forward_days_observed",
)
HISTORY_ENTRY_OPTIONAL_KEYS = ("spot_followed_on", "spot_after")
SPOT_AFTER_KEYS = ("flag_close", "last_close", "last_date", "high", "low", "days", "ex_rights")


def load_spot_prices(
    conn, *, stock_ids: Sequence[str], date_from: str, as_of: str,
) -> dict[str, list[dict[str, Any]]]:
    """舉旗股票的現貨日 K(``date_from`` ≤ 日期 ≤ ``as_of``),每檔遞增排序。

    battery 的 :func:`load_spot_daily` 只讀量;價格是呈現用的另一件事,所以另寫一句
    讀取,不去動被 §3 檢定過的那一句。只讀舉旗的那幾檔。
    """
    if not stock_ids:
        return {}
    wanted = set(stock_ids)
    out: dict[str, list[dict[str, Any]]] = {}
    rows = conn.execute(text("""
        SELECT stock_id, date, high, low, close, adj_factor FROM daily_prices
        WHERE date >= :date_from AND date <= :as_of
        ORDER BY stock_id, date
    """), {"date_from": date_from, "as_of": as_of}).mappings()
    for row in rows:
        if row["stock_id"] in wanted:
            out.setdefault(row["stock_id"], []).append(dict(row))
    return out


def spot_after(prices: Sequence[dict[str, Any]], *, day: str) -> dict[str, Any] | None:
    """舉旗日 ``day`` 的現貨收盤,以及之後(不含當天)觀察到的原始價格。

    * 當天沒有價格列(或收盤是 NULL)→ ``None``:沒有參考點,整個鍵不輸出。
    * 之後還沒有交易日 → ``{"flag_close", "days": 0}``。
    * 否則七個鍵:``last_close``/``last_date`` 是最後一個有收盤的日子,``high``/``low``
      是之後最高價的最大值/最低價的最小值(缺高低價時以收盤代替),``days`` 是之後
      有收盤的交易日數,``ex_rights`` = 舉旗日到最後一天之間 ``adj_factor`` 有變
      (除權息,價格未經還原)。全部是觀測值,沒有一個除法。

    **``ex_rights`` 為假不代表沒有除權息**:production 的 ``adj_factor`` 由平日 13:15
    adjust-incremental.sh 補(docs/47 §3.2;2026-10-09 前只在手動跑時更新),FinMind
    晚到的那一天、以及排程套用前的舊資料仍可能是 1.0;daily_prices 也沒有漲跌價
    / 參考價欄位、資料庫沒有除權息日表。所以多數除權息缺口偵測不到,前端每一句
    價格都標「未扣除權息」,只有偵測得到時才改講「窗內有除權息」。
    """
    flag = next((p for p in prices if p["date"] == day), None)
    if flag is None or flag["close"] is None:
        return None
    after = [p for p in prices if p["date"] > day and p["close"] is not None]
    if not after:
        return {"flag_close": flag["close"], "days": 0}
    factors = {p["adj_factor"] for p in [flag, *after]}
    return {
        "flag_close": flag["close"],
        "last_close": after[-1]["close"],
        "last_date": after[-1]["date"],
        "high": max(p["high"] if p["high"] is not None else p["close"] for p in after),
        "low": min(p["low"] if p["low"] is not None else p["close"] for p in after),
        "days": len(after),
        "ex_rights": len(factors) > 1,
    }


def spot_follow_up(
    *, stock_days: Sequence[str], volumes: dict[str, int | None], day: str,
) -> dict[str, Any]:
    """舉旗日 ``day`` 之後,現貨量有沒有在 5 個現貨交易日內創 60 日新高。

    三態,與 battery 的成熟性規則(§6 修訂 2)同一個紀律:

    * ``True``  = 往後已經過去的日子裡,有一天 ``S`` 為真(附上那一天)。
    * ``False`` = 往後 5 天**全部**已經過去、**全部**算得出來,而且沒有一天為真。
    * ``None``  = 還沒滿 5 天(觀察中),或有一天算不出來——未知不是否定。

    ``forward_days_observed`` 是已經過去的往後現貨交易日數(0–5)。
    """
    forwards = forward_spot_days(stock_days=stock_days, day=day)
    all_known = True
    for forward in forwards:
        hit = spot_new_high(stock_days=stock_days, volumes=volumes, day=forward)
        if hit is True:
            return {"spot_followed": True, "spot_followed_on": forward,
                    "forward_days_observed": len(forwards)}
        if hit is None:
            all_known = False
    followed = False if (len(forwards) == FORWARD_SPOT_DAYS and all_known) else None
    return {"spot_followed": followed, "forward_days_observed": len(forwards)}


def anomaly_history(conn, *, as_of: str | None, spot_date: str) -> list[dict[str, Any]] | None:
    """``as_of``(期貨行情日)之前 ``HISTORY_DAYS`` 個期貨交易日的舉旗紀錄,新到舊。

    每一天 ``{"as_of": d, "entries": [...]}``,三態與今日名單同一個約定:
    ``entries`` 缺鍵 = 那一天規則答不出來(§7.13 不主張);``[]`` = 算過、沒有人舉旗。
    條目 = 今日名單的條目(同一個 :func:`anomaly_index`,同一個順序)+
    :func:`spot_follow_up` 的三個欄位。同一個契約連續幾天舉旗就出現幾次,不合併。

    ``spot_date`` 是現貨資料日:R4 的市場日日曆讀到那一天(同今日名單),往後現貨
    也只看到那一天為止。
    """
    if as_of is None:
        return None
    futures_days = load_futures_calendar(conn, as_of)
    prior = [d for d in futures_days if d < as_of][-HISTORY_DAYS:]
    contracts = load_contracts(conn)
    stock_id_by_code = {c["contract_code"]: c["stock_id"] for c in contracts}
    multiplier_by_code = {c["contract_code"]: c["contract_multiplier"] for c in contracts}

    days: list[tuple[str, list[dict[str, Any]] | None]] = []
    for day in reversed(prior):
        # 規則本人,一天一次。這裡若改成自己判斷「創不創高」,就是一條沒被檢定過的規則。
        index = anomaly_index(
            futures_volume_anomalies(conn, day, market_days_as_of=spot_date),
            stock_id_by_code=stock_id_by_code,
            multiplier_by_code=multiplier_by_code,
        )
        days.append((day, index))

    flagged_ids = sorted({e["stock_id"] for _, index in days if index for e in index})
    spot: dict[str, tuple[list[str], dict[str, int | None]]] = {}
    prices: dict[str, list[dict[str, Any]]] = {}
    if flagged_ids:
        oldest = min(day for day, index in days if index)
        market_days = load_market_days(conn, spot_date)
        # 讀取下界(不是規則):往後每一天都要它自己前 60 個現貨交易日,所以從最舊的
        # 舉旗日往前留 2 × 60 個市場日。停牌太久的股票在這個範圍裡湊不滿 60 天,
        # 答案會變成「不知道」——方向是保守的,絕不會把不知道讀成知道。
        start = max(0, bisect_left(market_days, oldest) - 2 * WINDOW_DAYS)
        spot = load_spot_daily(
            conn, as_of=spot_date, stock_ids=flagged_ids,
            date_from=market_days[start] if market_days else None,
        )
        prices = load_spot_prices(
            conn, stock_ids=flagged_ids, date_from=oldest, as_of=spot_date,
        )

    history: list[dict[str, Any]] = []
    for day, index in days:
        if index is None:
            history.append({"as_of": day})
            continue
        entries = []
        for entry in index:
            stock_days, volumes = spot.get(entry["stock_id"], ([], {}))
            after = spot_after(prices.get(entry["stock_id"], []), day=day)
            entries.append({
                **entry,
                **spot_follow_up(stock_days=stock_days, volumes=volumes, day=day),
                **({"spot_after": after} if after is not None else {}),
            })
        history.append({"as_of": day, "entries": entries})
    return history


def anomaly_history_meta(
    history: list[dict[str, Any]] | None, *, as_of: str, observed_through: str,
) -> dict[str, Any] | None:
    """紀錄的隨附事實:天數全部來自常數本人,前端不寫死 5 / 10 / 60。

    ``observed_through`` 是往後現貨看到哪一天(現貨資料日)。與紀錄同生共死。
    """
    if history is None:
        return None
    return {
        "as_of": as_of,
        "window_days": WINDOW_DAYS,
        "history_days": HISTORY_DAYS,
        "forward_days": FORWARD_SPOT_DAYS,
        "observed_through": observed_through,
    }


def stock_anomaly_history(
    history: list[dict[str, Any]] | None,
    meta: dict[str, Any] | None,
    stock_id: str,
) -> dict[str, Any] | None:
    """個股頁的舉旗紀錄:同一份 :func:`anomaly_history` 結果,只留這一檔的條目。

    **不重算**——export 已經算好的那一份(radar.json 用的)切出來而已,所以條目與
    radar.json 裡這檔的條目逐字相同。每一天的三態原封不動:那一天缺 ``entries``
    = 規則答不出來(不主張);``[]`` = 算過了、這一檔沒有舉旗(帶日期的正面主張)。
    沒有舉旗的日子**照樣保留**,時間軸才誠實。meta 與 radar.json 的那一份是同一個。
    紀錄或 meta 不存在 → ``None``(呼叫端整個鍵不輸出)。
    """
    if history is None or meta is None:
        return None
    days: list[dict[str, Any]] = []
    for day in history:
        if "entries" not in day:
            days.append({"as_of": day["as_of"]})
            continue
        days.append({
            "as_of": day["as_of"],
            "entries": [e for e in day["entries"] if e["stock_id"] == stock_id],
        })
    return {"meta": meta, "days": days}


# 四個計數鍵,一個不多。**沒有**總數(相加由讀的人做,同 §1 的五個整數)、
# 沒有比率、沒有淨額、沒有旗標。
DIRECTION_COUNT_KEYS = ("increased", "decreased", "unchanged", "undetermined")


def open_interest_direction(
    changes: Iterable[int | None], *, as_of: str | None,
) -> dict[str, Any] | None:
    """市場層級的未平倉方向計數(docs/38 §7.15):今天有幾個契約在建倉、幾個在減倉。

    **為什麼這一個不需要 battery,而成交量異常需要**——這是本函式存在的全部條件,
    寫在這裡是為了日後有人想加一個門檻時,先讀到它:

    * §1 的旗標做的是一個**資訊性**主張:「這一天的量創了新高」這件事**告訴你**
      一些事(使用者原話是「拿來做判斷籌碼或是技術分析成交量的依據」)。一個
      「告訴你某件事」的宣稱可以被否證,所以 §3 要求它先被否證看看:區辨性、
      安慰劑、2σ、十組 seed。過不了就整個不上線。
    * 這裡的計數做的是一個**描述性**陳述:「今天有 N 個契約的未平倉比前一個期貨
      交易日高」。它**沒有**主張這件事之後會發生什麼,也沒有主張今天算不算不尋常,
      所以沒有任何東西可以被否證,也就沒有東西需要被檢定。一份 battery 對它而言
      不是「更嚴謹」,是**無從執行**:沒有假設,就沒有虛無假設。

    這個豁免**只在它保持描述性的時候成立**。以下任何一項都會讓它變成一個穿著本
    功能外衣、卻從來沒有被檢定過的訊號,因此一概不做:

    * **不設門檻、不舉旗、不下判語。** 一旦輸出「今天不尋常」,它就是一個資訊性
      主張,而那個主張沒有被 §3 檢定過。
    * **不算比率、不算百分比、不算淨額。** 只給計數,除法由讀的人做(§1 同一條
      紀律)。「增加減去減少」是一個分數的雛形,而分數會排名。
    * **不排名契約。** §5 明文不做跨契約排序;這裡連契約代碼都不輸出。
    * **UI 只複述計數。** 沒有「偏多 / 偏空」,沒有解讀。

    三態,與這個切片其他每一個鍵同一個約定:

    * ``as_of`` 為 ``None``(沒有期貨行情日,或那一天定不出來)→ ``None``,
      呼叫端整個鍵不輸出。**沒有算過**,沒有主張。
    * 否則 → 四個計數。全部為 0 與「沒有算過」因此分得出來:前者是一個有日期的
      正面主張(我們數過了),後者什麼都沒說。

    ``changes`` 是**每一個契約**的 ``oi_change()`` 結果,一個契約一項:``None``
    = 這個契約今天判不出方向(當天或前一日沒有列、或未平倉是 NULL)。它被數進
    ``undetermined``,**不是**被丟掉——丟掉會讓四個計數的和悄悄變成一個與契約數
    無關的數字,而讀者無從得知今天有多少契約根本沒有答案。判不出來的成因依 R1
    有未掛牌 / 未公布 / 匯入失敗三種,三者不可分辨,所以只數,不分類。
    """
    if as_of is None:
        return None
    counts = dict.fromkeys(DIRECTION_COUNT_KEYS, 0)
    for change in changes:
        if change is None:
            counts["undetermined"] += 1
        elif change > 0:
            counts["increased"] += 1
        elif change < 0:
            counts["decreased"] += 1
        else:
            counts["unchanged"] += 1
    return {"as_of": as_of, **counts}
