"""個股期貨成交量異常的事前登記 battery(唯讀,決定這個功能要不要存在)。

它是什麼
--------
``docs/38_futures_volume_anomaly_preregistration.md`` 是一份**事前登記**:它在
250 交易日回補資料可見之前就 commit(``c70f1c2``),裡面每一個數字都不得在看到
資料之後修改。這支 CLI 是那份文件的 §1–§3 的可執行版本——旗標、五條否決條件、
兩個檢定、以及「過不了就整個功能不上線」的裁決,全部寫成程式碼,讓任何人都能
重跑出同一組數字。它**不是**功能本身:它決定功能要不要被寫出來。

它算什麼
--------
§1 旗標
    ``flag(c, t) = V(c, t) > max{ V(c, d) : d ∈ W(c, t) }``,嚴格大於。``V`` 是
    契約 c 在日期 t、``session = '一般'``、非價差組合列的 ``SUM(volume)``(口);
    ``W`` 是 t 之前最近 60 個**期貨交易日**,跳過 R4 排除日。輸出的事實全是整數
    口數(``today`` / ``window_max`` / ``window_median`` / ``oi_change``),
    沒有比率、均值、名次、分數、z。

§2 否決(命中任一條 → 該契約該日不產生旗標,也不進檢定樣本)
    R1 窗口湊不滿 60 天,或窗口內任一天該契約沒有一般時段非價差列(**缺列 ≠ 0 口**)。
    R2a ``window_median == 0``——窗口內過半日子沒有成交,沒有「日常」可比。
    R2b 實質性:``100 × (today − window_median) × multiplier ≥ spot_median_shares``。
        乘數未知(``futures_contracts.contract_multiplier`` 為 NULL)→ **否決**,
        不假設 2,000;窗口內任一天標的股沒有 ``daily_prices`` 列 → 沒有尺 → 否決。
    R3 統計量永遠只用一般時段——這條在**查詢層**就執行了:盤後列從來沒有被讀進來。
    R4 結算日與其前 3 個市場日,同時排除於候選日與比較窗口之外(見
        :mod:`radar.compute.settlement_calendar`)。
    R5 乘數在窗口內變更 → 否決。**目前偵測不到**:本欄只存「現在的」乘數,沒有
        歷史,所以這是一個誠實記錄下來的盲點,不是一條有在跑的檢查。

§3 全案否決
    檢定 A(區辨性,純計數):``|F_only| ≥ LOW_SAMPLE_SURVIVORS``。
    檢定 B(資訊性,唯一的往後看量):F_only 成熟成員在其後 5 個現貨交易日內,
    現貨量是否創其 60 日新高;對照組是**每檔股票逐檔計數配對**的安慰劑,
    種子固定 0..9 共 10 組,**每一組**都要滿足 ``h_F − h_P ≥ 2 σ_P``。

寫入
----
沒有。``mode=ro`` 連線、不呼叫 ``init_db()``、不建表、不寫任何一列,也**不**寫
``futures_contracts.contract_multiplier``——填那一欄是另一個決定。

記憶體
------
與方向 battery 不同,這裡的資料集小到可以一次載入:每個契約一天一個整數
(約 320 契約 × 250 天),加上標的股的日成交量。逐檔串流的複雜度在這個形狀上
買不到東西,所以不做。
"""
from __future__ import annotations

import json
import math
import random
import time
from bisect import bisect_left, bisect_right
from datetime import date as date_cls
from pathlib import Path
from typing import Any, Sequence

from sqlalchemy import text

from .branch_window_direction_battery import LOW_SAMPLE_SURVIVORS
from .read_only_sqlite import get_read_only_sqlite_engine, safe_report_output_path
from .settlement_calendar import settlement_exclusion_set

REPORT_NAME = "futures-volume-battery"

REQUIRED_TABLES = ("futures_contracts", "futures_daily", "daily_prices")

# 這份 battery 執行的是哪一份事前登記的哪一個版本。兩者都寫進 JSON:一份在資料
# 出現之前 commit 的文件,若不能被指認,它的效力就等於零。
PREREGISTRATION_DOC = "docs/38_futures_volume_anomaly_preregistration.md"
PREREGISTRATION_COMMIT = "c70f1c2"

# §0:比較日的長度。60 是 json_export.py 與 commit 訊息一路引用的同一個 60。
WINDOW_DAYS = 60

# §3.1 成熟性 與 §3.3 往後看窗口,都是 5 個**現貨**交易日。同一個 5。
FORWARD_SPOT_DAYS = 5

# §3.3:抽樣種子固定為 0..9 共 10 組,**每一組**都必須過。
PLACEBO_SEEDS = tuple(range(10))
PLACEBO_SIGMA_MULTIPLE = 2.0

# §2 R2b:「超出中位數的那部分期貨量,換成股數,至少要等於現貨日常量的 1%」。
# 1% 寫成整數不等式就是左邊乘 100,程式裡不出現任何浮點比率。
MATERIALITY_INVERSE_FRACTION = 100

# F_only 的逐筆事實在 JSON 裡留一段可眼看的樣本(依日期、契約排序)。這不是排名
# ——§5 明文不做跨契約排序——只是讓覆核的人不必再開一次資料庫就能抽查幾筆。
F_ONLY_SAMPLE_LIMIT = 200

REFUSAL_CODES = (
    "R1_window_gap",
    "R2a_zero_median",
    "R2b_multiplier_unknown",
    "R2b_spot_history_gap",
    "R2b_immaterial",
)


def _validate_date(value: str, name: str) -> str:
    try:
        return date_cls.fromisoformat(value).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be YYYY-MM-DD: {value!r}") from exc


def lower_median(values: Sequence[int]) -> int:
    """下中位數。偶數個值時取**較小**的那一個,結果仍是整數口數/股數。

    §1 明寫「取下中位數,仍為整數」:平均兩個中間值會生出 .5,而這一節的合約是
    「全部是整數,除法由人做」。
    """
    if not values:
        raise ValueError("lower_median needs at least one value")
    return sorted(values)[(len(values) - 1) // 2]


def comparison_window(
    *, candidate: str, futures_days: Sequence[str], excluded: frozenset[str] | set[str],
) -> list[str] | None:
    """t 之前(不含 t)最近 ``60`` 個期貨交易日,**跳過 R4 排除日**。

    排除日不算在 60 裡,窗口往前延伸補足。湊不滿 60 天時回 ``None``(由 R1 否決),
    **不縮短窗口**:窗口長度是事前定死的,不因歷史不足而放寬。
    """
    index = bisect_left(futures_days, candidate)
    window: list[str] = []
    cursor = index - 1
    while cursor >= 0 and len(window) < WINDOW_DAYS:
        day = futures_days[cursor]
        if day not in excluded:
            window.append(day)
        cursor -= 1
    if len(window) < WINDOW_DAYS:
        return None
    window.reverse()
    return window


def evaluate_contract_day(
    *,
    today_volume: int,
    window_volumes: Sequence[int | None] | None,
    multiplier: int | None,
    spot_window_volumes: Sequence[int | None] | None,
) -> dict[str, Any]:
    """一個契約-日的 §1 旗標與 §2 否決。**純函式**:沒有資料庫,沒有日曆。

    ``window_volumes`` 是比較窗口上該契約的一般時段口數,``None`` 代表**該日沒有
    列**(缺列 ≠ 0 口);整個參數為 ``None`` 代表窗口根本湊不滿 60 天。
    ``spot_window_volumes`` 是同一組比較日上標的股的日成交股數,同樣以 ``None``
    表示缺列。

    否決一旦命中就回傳,順序是 R1 → R2a → R2b,與文件列舉的順序相同;
    ``flag`` 只有在完全沒有否決時才可能為真。
    """
    if window_volumes is None or len(window_volumes) != WINDOW_DAYS:
        return _refused("R1_window_gap", today=today_volume)
    if any(volume is None for volume in window_volumes):
        return _refused("R1_window_gap", today=today_volume)

    window_max = max(window_volumes)
    window_median = lower_median(list(window_volumes))
    facts = {
        "today": today_volume,
        "window_max": window_max,
        "window_median": window_median,
        "window_days": WINDOW_DAYS,
    }
    if window_median <= 0:
        return _refused("R2a_zero_median", **facts)
    if multiplier is None:
        # 三態原則不例外:不知道乘數 ≠ 2,000。這裡沒有預設值可以退。
        return _refused("R2b_multiplier_unknown", **facts)
    if spot_window_volumes is None or len(spot_window_volumes) != WINDOW_DAYS:
        return _refused("R2b_spot_history_gap", **facts)
    if any(volume is None for volume in spot_window_volumes):
        return _refused("R2b_spot_history_gap", **facts)

    spot_median_shares = lower_median(list(spot_window_volumes))
    excess_shares = (today_volume - window_median) * multiplier
    if MATERIALITY_INVERSE_FRACTION * excess_shares < spot_median_shares:
        return _refused(
            "R2b_immaterial",
            spot_median_shares=spot_median_shares,
            excess_shares=excess_shares,
            **facts,
        )
    return {
        "refusal": None,
        "flag": today_volume > window_max,
        "spot_median_shares": spot_median_shares,
        "excess_shares": excess_shares,
        **facts,
    }


def _refused(code: str, **facts: Any) -> dict[str, Any]:
    return {"refusal": code, "flag": False, **facts}


def spot_new_high(
    *, stock_days: Sequence[str], volumes: dict[str, int | None], day: str,
) -> bool | None:
    """S(s, t):現貨量嚴格大於該股前 60 個**現貨**交易日的最大值。

    現貨不轉倉,**不套 R4**;窗口以該股自己的現貨日曆計。歷史不足 60 天、或窗口內
    任一天(含 t 自己)沒有量,答案是 ``None`` = **不知道**,不是 ``False``:
    把「讀不到」塌成「沒創高」會讓 F_only 悄悄變大,而 F_only 正是本案的主角。
    """
    index = bisect_left(stock_days, day)
    if index >= len(stock_days) or stock_days[index] != day:
        return None
    today = volumes.get(day)
    if today is None or index < WINDOW_DAYS:
        return None
    window = [volumes.get(d) for d in stock_days[index - WINDOW_DAYS:index]]
    if any(volume is None for volume in window):
        return None
    return today > max(window)


def forward_spot_days(*, stock_days: Sequence[str], day: str) -> list[str]:
    """t 之後的 ``5`` 個現貨交易日;不足 5 天時回傳能給的那幾天(= 尚未成熟)。"""
    index = bisect_right(stock_days, day)
    return list(stock_days[index:index + FORWARD_SPOT_DAYS])


class _StockCalendar:
    """一檔股票的現貨日曆與日成交量。所有現貨側的問題都只問這個物件。"""

    __slots__ = ("days", "volumes", "_flags")

    def __init__(self, days: list[str], volumes: dict[str, int | None]) -> None:
        self.days = days
        self.volumes = volumes
        self._flags: dict[str, bool | None] = {}

    def new_high(self, day: str) -> bool | None:
        if day not in self._flags:
            self._flags[day] = spot_new_high(
                stock_days=self.days, volumes=self.volumes, day=day,
            )
        return self._flags[day]

    def is_mature(self, day: str) -> bool:
        return len(forward_spot_days(stock_days=self.days, day=day)) == FORWARD_SPOT_DAYS

    def forward_hit(self, day: str) -> bool:
        """t 之後 5 個現貨交易日內任一天現貨量創其 60 日新高。

        只在 ``is_mature`` 為真時才該被問;窗口內某天答案是 ``None``(讀不到)的
        話它不能算成命中,這與「未知不進分母」是同一個原則的下游。
        """
        return any(
            self.new_high(forward) is True
            for forward in forward_spot_days(stock_days=self.days, day=day)
        )

    def days_after(self, day: str, count: int) -> list[str]:
        index = bisect_right(self.days, day)
        return list(self.days[index:index + count])


def placebo_pool(
    *,
    eligible_days: set[str],
    flagged_days: set[str],
    calendar: _StockCalendar,
) -> list[str]:
    """該股的安慰劑合格日,排掉與任一 F 日共用往後窗口的日子。

    文件寫的是「不落在該股任一 F 日**之後** 5 個現貨交易日內」。這裡另外把 F 日
    **自己**也排掉:同一檔股票可以有兩個契約,其中一個在 t 舉旗、另一個在 t 沒舉,
    而那兩者的往後窗口**逐日相同**——抽到它就等於拿旗標臂的同一個觀測當對照,
    正是那條規則要擋的事。這是對文字的一個收緊(只會讓安慰劑池變小、檢定更難過),
    已在報告的 ``choices`` 裡寫明。
    """
    blocked = set(flagged_days)
    for flagged in flagged_days:
        blocked.update(calendar.days_after(flagged, FORWARD_SPOT_DAYS))
    return sorted(eligible_days - blocked)


def draw_placebo(
    *, pools: dict[str, list[str]], counts: dict[str, int], seed: int,
) -> dict[str, list[str]]:
    """逐檔不放回抽樣:在 F_only 有 k 筆的股票就抽 k 天。

    股票依代號排序後依序抽,所以同一個 seed 與同一份資料永遠給出同一組安慰劑。
    池子不足 k 天時抽光它,**不重複抽、不跨股票借**;差額由呼叫端記錄,並且會讓
    檢定 B 變成「不可評估」——用比較少的安慰劑日去湊一個 ``h_P`` 會系統性地把它
    壓低,那是朝著「容易過關」的方向偏。
    """
    rng = random.Random(seed)
    drawn: dict[str, list[str]] = {}
    for stock_id in sorted(counts):
        pool = pools.get(stock_id, [])
        k = min(counts[stock_id], len(pool))
        drawn[stock_id] = sorted(rng.sample(pool, k)) if k else []
    return drawn


def discriminability_verdict(*, f_count: int, f_only_count: int) -> dict[str, Any]:
    """檢定 A:區辨性,純計數。三種結局的文字互不相同,因為它們意思不同。"""
    threshold = LOW_SAMPLE_SURVIVORS
    if f_only_count >= threshold:
        outcome, statement = "PASS", (
            f"|F_only| = {f_only_count} >= {threshold}: futures-only new highs are a "
            "set large enough to be about something"
        )
    elif f_count >= threshold:
        outcome, statement = "REDUNDANT WITH SPOT", (
            f"|F| = {f_count} >= {threshold} but |F_only| = {f_only_count} < {threshold}: "
            "a futures new high is almost always an echo of a spot new high, so the "
            "slice carries no independent content"
        )
    else:
        outcome, statement = "UNDERPOWERED", (
            f"|F| = {f_count} < {threshold}: this is an inconclusive result for want of "
            "power, NOT a refutation; re-run under the rules of §3.5"
        )
    return {
        "test": "A_discriminability",
        "threshold": f"|F_only| >= {threshold} (LOW_SAMPLE_SURVIVORS)",
        "passed": outcome == "PASS",
        "outcome": outcome,
        "observed": {
            "f": f_count, "f_only": f_only_count, "threshold": threshold,
        },
        "line": f"[{outcome}] A_discriminability: {statement}",
    }


def seed_result(*, seed: int, n: int, h_f: int, h_p: int, matched: bool) -> dict[str, Any]:
    """單一 seed 的檢定 B 判準:``h_F − h_P ≥ 2 σ_P``。

    ``p̂ = h_P / n``、``σ_P = max(1, sqrt(n p̂ (1 − p̂)))``——下限 1 是文件寫死的,
    它擋掉 ``p̂`` 為 0 或 1 時 σ 塌成 0、任何差距都「顯著」的退化情形。
    """
    if not n or not matched:
        return {
            "seed": seed, "n": n, "h_f": h_f, "h_p": h_p,
            "p_hat": None, "sigma_p": None, "margin": None,
            "evaluable": False, "passed": False,
        }
    p_hat = h_p / n
    sigma_p = max(1.0, math.sqrt(n * p_hat * (1.0 - p_hat)))
    return {
        "seed": seed,
        "n": n,
        "h_f": h_f,
        "h_p": h_p,
        "p_hat": round(p_hat, 6),
        "sigma_p": round(sigma_p, 6),
        "margin": round(PLACEBO_SIGMA_MULTIPLE * sigma_p, 6),
        "evaluable": True,
        "passed": (h_f - h_p) >= PLACEBO_SIGMA_MULTIPLE * sigma_p,
    }


def informativeness_verdict(*, seeds: list[dict[str, Any]]) -> dict[str, Any]:
    """檢定 B:**每一個** seed 都要過。任一 seed 不過即不過。

    「換 seed 直到過關」正是 seed 參數要暴露的失敗模式(docs/STATUS.md 2026-09-08),
    所以這裡沒有「多數決」「取平均」這種讀法可選。
    """
    threshold = (
        f"every seed in {list(PLACEBO_SEEDS)} must satisfy "
        f"h_F - h_P >= {PLACEBO_SIGMA_MULTIPLE} * sigma_P"
    )
    evaluable = bool(seeds) and all(entry["evaluable"] for entry in seeds)
    if not evaluable:
        return {
            "test": "B_informativeness",
            "threshold": threshold,
            "passed": False,
            "evaluable": False,
            "outcome": "NOT EVALUABLE",
            "seeds": seeds,
            "line": (
                "[NOT EVALUABLE] B_informativeness: the count-matched placebo could not "
                "be drawn at the required size on at least one seed"
            ),
        }
    failed = [entry["seed"] for entry in seeds if not entry["passed"]]
    passed = not failed
    outcome = "PASS" if passed else "FAIL"
    return {
        "test": "B_informativeness",
        "threshold": threshold,
        "passed": passed,
        "evaluable": True,
        "outcome": outcome,
        "seeds": seeds,
        "line": (
            f"[{outcome}] B_informativeness: "
            + ("every seed clears the 2-sigma margin" if passed
               else f"seed(s) {failed} do not clear the 2-sigma margin; "
                    "one failing seed is a failure")
        ),
    }


def overall_verdict(*, test_a: dict[str, Any], test_b: dict[str, Any]) -> dict[str, Any]:
    """§3.4:A 過且 B 過才上線,其餘一律不上線,而且理由不可互換。"""
    if not test_a["passed"]:
        reason = (
            "redundant_with_spot" if test_a["outcome"] == "REDUNDANT WITH SPOT"
            else "underpowered"
        )
        return _decision("DO NOT SHIP", reason, test_a["line"])
    if not test_b["evaluable"]:
        return _decision("DO NOT SHIP", "not_evaluable", test_b["line"])
    if not test_b["passed"]:
        return _decision("DO NOT SHIP", "forward_test_failed", test_b["line"])
    return _decision("SHIP", "a_and_b_passed", "A and B both pass")


def _decision(decision: str, reason: str, detail: str) -> dict[str, Any]:
    return {
        "decision": decision,
        "reason": reason,
        "line": f"[{decision}] futures volume anomaly slice: {reason} ({detail})",
        "note": (
            "numbers stay in this JSON; nothing is written to any table, export or "
            "panel unless the decision is SHIP"
        ),
    }


def _load_futures_calendar(conn, as_of: str) -> list[str]:
    return [row[0] for row in conn.execute(text("""
        SELECT DISTINCT date FROM futures_daily WHERE date <= :as_of ORDER BY date
    """), {"as_of": as_of}).fetchall()]


def _load_market_days(conn, as_of: str) -> list[str]:
    return [row[0] for row in conn.execute(text("""
        SELECT DISTINCT date FROM daily_prices WHERE date <= :as_of ORDER BY date
    """), {"as_of": as_of}).fetchall()]


def _load_contracts(conn) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(text("""
        SELECT contract_code, stock_id, contract_multiplier
        FROM futures_contracts
        ORDER BY contract_code
    """)).mappings()]


def _load_regular_session_volumes(conn, as_of: str) -> dict[str, dict[str, Any]]:
    """R3 在查詢層執行:``session = '一般'``,盤後列從來沒有被讀進來。

    價差組合列(``'202609/202610'``)一併排除,與 ``json_export._futures_by_stock``
    同一條件。``SUM(volume)`` 為 NULL 代表來源沒有給數字——那是「不知道」,不是
    0 口,所以它與「沒有列」在下游受同樣待遇。
    """
    per_contract: dict[str, dict[str, Any]] = {}
    rows = conn.execute(text("""
        SELECT contract_code, date,
               SUM(volume) AS volume,
               SUM(open_interest) AS open_interest
        FROM futures_daily
        WHERE date <= :as_of
          AND session = '一般'
          AND contract_month NOT LIKE '%/%'
        GROUP BY contract_code, date
    """), {"as_of": as_of}).mappings()
    for row in rows:
        entry = per_contract.setdefault(
            row["contract_code"], {"volume": {}, "open_interest": {}},
        )
        if row["volume"] is not None:
            entry["volume"][row["date"]] = int(row["volume"])
        if row["open_interest"] is not None:
            entry["open_interest"][row["date"]] = int(row["open_interest"])
    return per_contract


def _load_spot(conn, as_of: str, stock_ids: Sequence[str]) -> dict[str, _StockCalendar]:
    calendars: dict[str, _StockCalendar] = {}
    if not stock_ids:
        return calendars
    wanted = set(stock_ids)
    rows = conn.execute(text("""
        SELECT stock_id, date, volume FROM daily_prices
        WHERE date <= :as_of ORDER BY stock_id, date
    """), {"as_of": as_of}).mappings()
    staged: dict[str, tuple[list[str], dict[str, int | None]]] = {}
    for row in rows:
        stock_id = row["stock_id"]
        if stock_id not in wanted:
            continue
        days, volumes = staged.setdefault(stock_id, ([], {}))
        days.append(row["date"])
        volumes[row["date"]] = None if row["volume"] is None else int(row["volume"])
    for stock_id, (days, volumes) in staged.items():
        calendars[stock_id] = _StockCalendar(days, volumes)
    return calendars


def build_futures_volume_battery(*, as_of: str, run_number: int = 1) -> dict[str, Any]:
    """跑完整個 battery 並回傳可序列化的結果。全程唯讀。"""
    as_of = _validate_date(as_of, "as-of")
    if not isinstance(run_number, int) or isinstance(run_number, bool) or run_number < 1:
        raise ValueError("run-number must be an integer >= 1")
    started = time.monotonic()

    engine = get_read_only_sqlite_engine(
        report_name=REPORT_NAME, required_tables=REQUIRED_TABLES,
    )
    try:
        with engine.connect() as conn:
            futures_days = _load_futures_calendar(conn, as_of)
            market_days = _load_market_days(conn, as_of)
            contracts = _load_contracts(conn)
            per_contract = _load_regular_session_volumes(conn, as_of)
            spot = _load_spot(
                conn, as_of, [contract["stock_id"] for contract in contracts],
            )
            futures_row_count = conn.execute(text(
                "SELECT COUNT(*) FROM futures_daily WHERE date <= :as_of"
            ), {"as_of": as_of}).scalar_one()
    finally:
        engine.dispose()

    excluded = (
        settlement_exclusion_set(
            date_from=futures_days[0], date_to=as_of, market_days=market_days,
        )
        if futures_days else set()
    )
    return _assemble(
        as_of=as_of,
        run_number=run_number,
        futures_days=futures_days,
        market_days=market_days,
        excluded=excluded,
        contracts=contracts,
        per_contract=per_contract,
        spot=spot,
        futures_row_count=futures_row_count,
        started=started,
    )


def _assemble(
    *,
    as_of: str,
    run_number: int,
    futures_days: list[str],
    market_days: list[str],
    excluded: set[str],
    contracts: list[dict[str, Any]],
    per_contract: dict[str, dict[str, Any]],
    spot: dict[str, _StockCalendar],
    futures_row_count: int,
    started: float,
) -> dict[str, Any]:
    excluded_frozen = frozenset(excluded)
    refusals = dict.fromkeys(REFUSAL_CODES, 0)
    settlement_window_skips = 0
    no_regular_row = 0
    evaluated = 0
    no_spot_calendar = 0

    flagged: list[dict[str, Any]] = []           # F(不論成熟)
    eligible_by_stock: dict[str, set[str]] = {}  # 安慰劑合格日(未扣共用窗口)

    for contract in contracts:
        code, stock_id = contract["contract_code"], contract["stock_id"]
        multiplier = contract["contract_multiplier"]
        daily = per_contract.get(code)
        if daily is None:
            continue
        volumes = daily["volume"]
        calendar = spot.get(stock_id)
        for candidate in futures_days:
            if candidate in excluded_frozen:
                # R4:結算日與其前 3 個市場日不得上榜。
                settlement_window_skips += 1
                continue
            today_volume = volumes.get(candidate)
            if today_volume is None:
                no_regular_row += 1
                continue
            evaluated += 1
            window = comparison_window(
                candidate=candidate, futures_days=futures_days, excluded=excluded_frozen,
            )
            if calendar is None:
                # 標的股一列現貨都沒有:R2b 的尺不存在。R1 仍然先判,否決的順序
                # 與文件列舉的順序一致,不因為現貨缺席就跳過歷史檢查。
                no_spot_calendar += 1
            outcome = evaluate_contract_day(
                today_volume=today_volume,
                window_volumes=(
                    None if window is None else [volumes.get(day) for day in window]
                ),
                multiplier=multiplier,
                spot_window_volumes=(
                    None if window is None or calendar is None
                    else [calendar.volumes.get(day) for day in window]
                ),
            )
            if outcome["refusal"] is not None:
                refusals[outcome["refusal"]] += 1
                continue
            spot_flag = calendar.new_high(candidate)
            mature = calendar.is_mature(candidate)
            if outcome["flag"]:
                flagged.append({
                    "contract_code": code,
                    "stock_id": stock_id,
                    "date": candidate,
                    "today": outcome["today"],
                    "window_max": outcome["window_max"],
                    "window_median": outcome["window_median"],
                    "oi_change": _oi_change(
                        daily["open_interest"], futures_days, candidate,
                    ),
                    "spot_new_high": spot_flag,
                    "mature": mature,
                })
            elif mature and spot_flag is False:
                eligible_by_stock.setdefault(stock_id, set()).add(candidate)

    return _score(
        as_of=as_of,
        run_number=run_number,
        futures_days=futures_days,
        market_days=market_days,
        excluded=excluded,
        contracts=contracts,
        spot=spot,
        flagged=flagged,
        eligible_by_stock=eligible_by_stock,
        refusals=refusals,
        coverage_counts={
            "futures_trading_days": len(futures_days),
            "futures_daily_rows": futures_row_count,
            "contracts": len(contracts),
            "contract_days_evaluated": evaluated,
            "contract_days_in_settlement_window": settlement_window_skips,
            "contract_days_without_regular_session_row": no_regular_row,
            "contract_days_without_spot_calendar": no_spot_calendar,
            "contracts_with_known_multiplier": sum(
                1 for contract in contracts
                if contract["contract_multiplier"] is not None
            ),
        },
        started=started,
    )


def _oi_change(
    open_interest: dict[str, int], futures_days: Sequence[str], day: str,
) -> int | None:
    """當日總未平倉 − 前一個期貨交易日總未平倉;任一邊為 NULL 則此欄省略。

    前一個期貨交易日是**日曆上的**前一天,不跳過 R4 排除日:這是一個事實欄位,
    不是統計量,而「昨天」就是昨天。
    """
    index = bisect_left(futures_days, day)
    if index <= 0 or index >= len(futures_days) or futures_days[index] != day:
        return None
    today = open_interest.get(day)
    previous = open_interest.get(futures_days[index - 1])
    if today is None or previous is None:
        return None
    return today - previous


def _score(
    *,
    as_of: str,
    run_number: int,
    futures_days: list[str],
    market_days: list[str],
    excluded: set[str],
    contracts: list[dict[str, Any]],
    spot: dict[str, _StockCalendar],
    flagged: list[dict[str, Any]],
    eligible_by_stock: dict[str, set[str]],
    refusals: dict[str, int],
    coverage_counts: dict[str, int],
    started: float,
) -> dict[str, Any]:
    mature_flagged = [entry for entry in flagged if entry["mature"]]
    spot_flag_unknown = sum(
        1 for entry in mature_flagged if entry["spot_new_high"] is None
    )
    f_only = [entry for entry in mature_flagged if entry["spot_new_high"] is False]

    flagged_days_by_stock: dict[str, set[str]] = {}
    for entry in flagged:
        flagged_days_by_stock.setdefault(entry["stock_id"], set()).add(entry["date"])

    counts: dict[str, int] = {}
    for entry in f_only:
        counts[entry["stock_id"]] = counts.get(entry["stock_id"], 0) + 1

    pools = {
        stock_id: placebo_pool(
            eligible_days=eligible_by_stock.get(stock_id, set()),
            flagged_days=flagged_days_by_stock.get(stock_id, set()),
            calendar=spot[stock_id],
        )
        for stock_id in counts
    }
    n = len(f_only)
    h_f = sum(spot[entry["stock_id"]].forward_hit(entry["date"]) for entry in f_only)

    seeds: list[dict[str, Any]] = []
    shortfall_total = 0
    for seed in PLACEBO_SEEDS:
        drawn = draw_placebo(pools=pools, counts=counts, seed=seed)
        drawn_count = sum(len(days) for days in drawn.values())
        shortfall_total += n - drawn_count
        h_p = sum(
            spot[stock_id].forward_hit(day)
            for stock_id, days in drawn.items() for day in days
        )
        seeds.append(seed_result(
            seed=seed, n=n, h_f=h_f, h_p=h_p, matched=drawn_count == n,
        ))

    test_a = discriminability_verdict(f_count=len(mature_flagged), f_only_count=n)
    test_b = informativeness_verdict(seeds=seeds)
    decision = overall_verdict(test_a=test_a, test_b=test_b)
    return {
        "metadata": {
            "report": REPORT_NAME,
            "as_of": as_of,
            "run_number": run_number,
            "preregistration": PREREGISTRATION_DOC,
            "preregistration_commit": PREREGISTRATION_COMMIT,
            "seeds": list(PLACEBO_SEEDS),
            "read_only": True,
            "schema_changes": False,
            "database_writes": False,
            "ranking_or_score_changes": False,
            "elapsed_sec": round(time.monotonic() - started, 3),
        },
        "definitions": _definitions(),
        "coverage": {
            **coverage_counts,
            "futures_from": futures_days[0] if futures_days else None,
            "futures_to": futures_days[-1] if futures_days else None,
            "market_trading_days_through_as_of": len(market_days),
            "settlement_excluded_days": len(excluded),
            "stocks_with_spot_calendar": len(spot),
        },
        "refusals": {
            **refusals,
            "R3_after_hours": (
                "structural: the statistic only ever reads session='一般'; after-hours "
                "rows are never loaded, so there is no count to report"
            ),
            "R5_multiplier_change": (
                "KNOWN BLIND SPOT, not a running check: futures_contracts stores one "
                "current multiplier with no history, so a mid-window change is "
                "undetectable. Recorded as a blind spot exactly as §2 R5 requires"
            ),
        },
        "sets": {
            "f": len(mature_flagged),
            "f_all_including_immature": len(flagged),
            "f_immature": len(flagged) - len(mature_flagged),
            "f_only": n,
            "f_with_spot_new_high": sum(
                1 for entry in mature_flagged if entry["spot_new_high"] is True
            ),
            "f_with_unknown_spot_flag": spot_flag_unknown,
            "placebo_pool_days": sum(len(pool) for pool in pools.values()),
            "placebo_stocks": len(counts),
            "placebo_day_shortfall_across_seeds": shortfall_total,
        },
        "f_only_sample": [
            {
                "contract_code": entry["contract_code"],
                "stock_id": entry["stock_id"],
                "date": entry["date"],
                "today": entry["today"],
                "window_max": entry["window_max"],
                "window_median": entry["window_median"],
                "oi_change": entry["oi_change"],
                "window_days": WINDOW_DAYS,
                "hit": spot[entry["stock_id"]].forward_hit(entry["date"]),
            }
            for entry in sorted(
                f_only, key=lambda item: (item["date"], item["contract_code"]),
            )[:F_ONLY_SAMPLE_LIMIT]
        ],
        "f_only_sample_truncated": n > F_ONLY_SAMPLE_LIMIT,
        "tests": {"A": test_a, "B": {**test_b, "h_f": h_f, "n": n}},
        "verdict": decision,
        "choices": _choices(),
        "notes": [
            "This battery writes nothing: no table, no export, no panel. Its only "
            "product is this JSON and the STATUS entry made from it.",
            "An unknown contract multiplier REFUSES the contract-day. It is never "
            "assumed to be 2,000; a NULL multiplier and a 2,000 multiplier are "
            "different facts and are never collapsed.",
            "A missing row is not zero lots. TAIFEX prints a row every day for a "
            "listed contract, so an absent row means not-listed / not-published / "
            "import-failed, and R1 refuses rather than reading it as no trading.",
            "Every threshold here comes from the pre-registration committed at "
            f"{PREREGISTRATION_COMMIT}, before its data was queried. Loosening any of "
            "them after seeing a reading is the exact move that document exists to stop.",
        ],
    }


def _definitions() -> dict[str, str]:
    return {
        "V": (
            "SUM(volume) for a contract on a date with session='一般' and "
            "contract_month NOT LIKE '%/%' (spread combination rows excluded); an "
            "absent row means V does not exist and is never read as zero lots"
        ),
        "W": (
            f"the {WINDOW_DAYS} futures trading days before t, skipping R4 settlement "
            "window days; skipped days do not count toward the 60 and the window "
            "extends further back to make it up"
        ),
        "flag": "V(c, t) strictly greater than max V over W(c, t)",
        "window_median": (
            "lower median of the 60 window values, an integer number of lots; the "
            "median is a refusal input (R2a, R2b), never a divisor in the output"
        ),
        "R2b": (
            f"{MATERIALITY_INVERSE_FRACTION} x (today - window_median) x multiplier >= "
            "median daily_prices.volume over the same W, i.e. the part of the futures "
            "volume above its own median, converted to shares, is at least 1% of the "
            "underlying's ordinary daily share volume; the 1% is docs/04 §2's existing "
            "materiality bar, not a number picked from futures data"
        ),
        "S": (
            "the same rule moved to the spot side: daily_prices.volume(s, t) strictly "
            f"greater than the max over that stock's previous {WINDOW_DAYS} spot "
            "trading days. Spot does not roll over, so R4 is NOT applied to it"
        ),
        "F_only": (
            "flagged contract-days where the underlying did NOT make a spot volume new "
            "high the same day: what the futures volume says that the spot volume does "
            "not already say on the same page"
        ),
        "hit": (
            f"1 if any of the {FORWARD_SPOT_DAYS} spot trading days after t is itself a "
            "spot volume new high; binary and counted, never a forward return"
        ),
        "mature": (
            f"t has {FORWARD_SPOT_DAYS} spot trading days after it at or before as_of; "
            "immature days enter no denominator and are never counted as misses"
        ),
        "placebo": (
            "per stock with k members of F_only, k days drawn without replacement from "
            "that stock's eligible days: mature, seen by the rule and not flagged "
            "(R1-R5 all pass with flag = 0), not a spot new high, and not sharing a "
            "forward window with any F day of that stock"
        ),
        "sigma_p": (
            "max(1, sqrt(n * p_hat * (1 - p_hat))) with p_hat = h_P / n; the floor of 1 "
            "stops a degenerate p_hat of 0 or 1 from making every difference significant"
        ),
    }


def _choices() -> list[dict[str, str]]:
    """§1–§3 讀起來有一個以上合理解法的地方,連同這裡選了哪一個。

    寫出來是為了讓它們**可被反駁**:事前登記的價值在於事後沒有暗處,而一個埋在
    程式裡、沒人知道要爭論的實作選擇,與事後放寬門檻在效果上是同一件事。
    要改任何一條,走 §3.5 的 v2 路線。
    """
    return [
        {
            "where": "§3.1 maturity vs §3.2 test A",
            "choice": (
                "test A counts the MATURE members of F and F_only. §3.1 says an "
                "immature t enters no denominator; A is a count of the same sample B "
                "uses, so one definition is used for both"
            ),
            "both_reported": "sets.f_all_including_immature and sets.f_immature",
        },
        {
            "where": "§2 R2b applied to days that do not flag",
            "choice": (
                "R2b is evaluated on EVERY contract-day, not only on candidates that "
                "clear the window max, because §3.3 defines the placebo pool as days "
                "where R1-R5 all passed and flag = 0. A day below its own window median "
                "therefore fails R2b and is not placebo-eligible"
            ),
            "both_reported": "refusals.R2b_immaterial counts them",
        },
        {
            "where": "§3.3 placebo pool vs the flagged day itself",
            "choice": (
                "a stock's own F dates are excluded from its placebo pool, not only the "
                "5 days after them: two contracts on one stock can disagree on the same "
                "date, and that date's forward window is identical to the flagged arm's"
            ),
            "both_reported": "sets.placebo_pool_days",
        },
        {
            "where": "§3.3 placebo drawn short",
            "choice": (
                "if any stock's eligible pool is smaller than its k, test B is reported "
                "NOT EVALUABLE rather than scored on fewer placebo days; a short draw "
                "lowers h_P and so biases the comparison toward passing"
            ),
            "both_reported": "sets.placebo_day_shortfall_across_seeds",
        },
        {
            "where": "§3.1 S(s, t) that cannot be computed",
            "choice": (
                "a flagged day whose spot flag is unknown (fewer than 60 spot days of "
                "history, or a missing spot volume) is counted but kept OUT of F_only; "
                "reading unknown as 'no spot new high' would inflate the headline set"
            ),
            "both_reported": "sets.f_with_unknown_spot_flag",
        },
    ]


def write_futures_volume_battery(
    *, as_of: str, run_number: int = 1, out: str | Path,
) -> dict[str, Any]:
    """Build and deterministically write the JSON battery result."""
    out_path = safe_report_output_path(out, report_name=REPORT_NAME)
    report = build_futures_volume_battery(as_of=as_of, run_number=run_number)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report
