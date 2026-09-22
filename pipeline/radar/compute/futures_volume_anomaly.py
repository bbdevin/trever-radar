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

from typing import Any

from .futures_volume_battery import (
    WINDOW_DAYS,
    anomaly_facts,
    comparison_window,
    evaluate_contract_day_in_calendar,
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
        }
    return anomalies


def anomaly_index(
    anomalies: dict[str, dict[str, Any]] | None,
    *,
    stock_id_by_code: dict[str, str],
) -> list[dict[str, Any]] | None:
    """市場層級的今日名單(§7.5)。``{stock_id, code, anomaly, reasons, risks}``。

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
    entries = [
        {"stock_id": stock_id_by_code[code], "code": code, **payload}
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
