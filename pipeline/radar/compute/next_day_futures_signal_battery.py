"""「期貨先爆量、現貨未跟上」之後買得到那一天漲 ≥ 3% 的次數:事前登記 battery(唯讀)。

它是什麼
--------
``docs/40_futures_signal_next_day_preregistration.md`` 是一份**事前登記**,凍結於
``e9212bd``(2026-10-02,台北時間):commit 時沒有任何人查詢過任何期貨旗標之後的
股價。這支程式是那份文件 §0–§3 的可執行版本,**不是**功能本身:它決定功能要不要
被寫出來。

它算什麼
--------
§0 訊號日 (s, t)
    t 是期貨交易日、不在 R4 排除日;s 至少一個契約在 t 無否決且 ``flag = True``,
    **且** ``S(s, t)`` 已知為 False。契約-日判讀、R4、S 全部 import 自
    :mod:`futures_volume_battery` / :mod:`settlement_calendar`,這裡沒有第二條規則。
§0 事件
    期貨日曆上前一個期貨交易日不是 s 的訊號日 → t 是事件。段落在完整日曆上認定,
    **然後**才套用剔除窗 X = [2026-09-18, 2026-10-02]。
§0 進場日 e(t)
    市場日曆 D(``daily_prices`` 任一列存在的日期)中 t 之後的**第 2 個**市場日,
    由日曆算,不讀任何儲存欄位。
§0 hit / drop
    ``100 × close(s, e) ≥ 103 × open(s, e)`` / ``≤ 97 × open(s, e)``,原始價、同一列、
    十進位比較(``next_day_surge_battery._dec``)。
§2 否決
    R1 不成熟或無列、R2 停牌(e 日量 0 或 NULL)。R3 鎖漲停開盤不否決,只報告。
§3 全案否決
    A ``n ≥ 30`` 且 ``h ≥ 30``;B 兩組等量對照 × seed 0..9 的 20 個 ``h − h_P ≥ 2σ_P``;
    D 同一批抽樣的 20 個 ``(h − d) − (h_P − d_P) ≥ 2σ_N``;C 兩半 × 兩組 × 10 seed 的
    40 個 ``h(半) − h_P(半) > 0``。

``--coverage-only``(§4 步驟 2)
-------------------------------
只算評估期起訖、訊號日數、事件數。那條路徑**結構上碰不到結果價格**:它不呼叫
:func:`load_outcome_bars`,而且連線被裝上 SQLite authorizer,``daily_prices`` 除了
``stock_id``、``date``、``volume``(``S`` 與 R2b 的輸入,不是價格)以外的欄位一律拒讀。

寫入
----
沒有。``mode=ro`` 連線、不呼叫 ``init_db()``、不建表、不寫任何一列。
"""
from __future__ import annotations

import json
import math
import sqlite3
from bisect import bisect_right
from datetime import date as date_cls
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from sqlalchemy import text

from .branch_window_direction_battery import LOW_SAMPLE_SURVIVORS, split_window
from .futures_volume_battery import (
    PLACEBO_SEEDS,
    PLACEBO_SIGMA_MULTIPLE,
    evaluate_contract_day_in_calendar,
    load_contracts,
    load_futures_calendar,
    load_market_days,
    load_regular_session_volumes,
    load_spot_daily,
    seed_result,
    spot_new_high,
)
from .next_day_surge_battery import (
    LIMIT_PROXY_PERMILLE,
    _dec,
    consistency_verdict,
    draw_matched,
    informativeness_verdict,
)
from .read_only_sqlite import get_read_only_sqlite_engine, safe_report_output_path
from .settlement_calendar import settlement_exclusion_set, settlement_is_determinable

REPORT_NAME = "next-day-futures-signal-battery"

REQUIRED_TABLES = ("futures_contracts", "futures_daily", "daily_prices", "stocks")

PREREGISTRATION_DOC = "docs/40_futures_signal_next_day_preregistration.md"
PREREGISTRATION_COMMIT = "e9212bd"

# §0 剔除窗 X:期貨旗標上正式站時最大期貨日(09-18)到凍結 commit 的台北日期。
EXCLUSION_FROM = "2026-09-18"
EXCLUSION_TO = "2026-10-02"

# §0 母體。
POPULATION_TYPE = "stock"

# §0 v(t) = t 之後第 1 個市場日、e(t) = 第 2 個。
VISIBLE_MARKET_DAYS_AFTER = 1
ENTRY_MARKET_DAYS_AFTER = 2

# §0 hit / drop 的門檻;§3.6 伴隨門檻。
THRESHOLD_PCT = 3
COMPANION_THRESHOLDS_PCT = (5, 7)
LEG = "entry_open_to_close"

# §1 的形狀,照表格順序。export 若有一天加上這個鍵,就是這幾個、一個不多。
FACT_KEYS = (
    "from", "to", "events", "hits", "drops",
    "placebo_stock_hits", "placebo_stock_drops",
    "placebo_date_hits", "placebo_date_drops",
    "threshold_pct", "leg",
)

REFUSAL_CODES = (
    "R1_no_entry_day",
    "R1_no_entry_row",
    "R1_bad_open",
    "R1_no_close",
    "R2_suspended",
)

# --coverage-only 時**唯一**可讀的表與欄位(白名單)。daily_prices.volume 是 S 與 R2b
# 的輸入;期貨只讀量、未平倉與鍵。其餘一切(價格、結算價、fwd_*、指標……)拒讀。
COVERAGE_READABLE_COLUMNS = {
    "daily_prices": frozenset({"stock_id", "date", "volume"}),
    "futures_daily": frozenset({
        "contract_code", "date", "contract_month", "session", "volume", "open_interest",
    }),
    "futures_contracts": frozenset({"contract_code", "stock_id", "contract_multiplier"}),
    "stocks": frozenset({"id", "type"}),
}


def _validate_date(value: str, name: str) -> str:
    try:
        return date_cls.fromisoformat(value).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be YYYY-MM-DD: {value!r}") from exc


def in_exclusion_window(day: str) -> bool:
    return EXCLUSION_FROM <= day <= EXCLUSION_TO


# ── §0:日曆 ──────────────────────────────────────────────────────────────

def market_day_after(market_days: Sequence[str], day: str, count: int) -> str | None:
    """D 中 ``day`` 之後的第 ``count`` 個市場日(``day`` 本身不必在 D 裡)。"""
    index = bisect_right(market_days, day) + count - 1
    return market_days[index] if index < len(market_days) else None


def entry_day(market_days: Sequence[str], day: str) -> str | None:
    """e(t):D 中 t 之後第 2 個市場日。讀者最早買得到的那一天。"""
    return market_day_after(market_days, day, ENTRY_MARKET_DAYS_AFTER)


def visible_day(market_days: Sequence[str], day: str) -> str | None:
    """v(t):D 中 t 之後第 1 個市場日。旗標第一次出現的那一晚;§3.6 只報告。"""
    return market_day_after(market_days, day, VISIBLE_MARKET_DAYS_AFTER)


def check_as_of(
    *, as_of: str, max_futures_date: str | None, max_price_date: str | None,
    historical: bool, price_horizon: str | None = None,
) -> str:
    """§0:as_of **就是** ``min(max futures_daily.date, max daily_prices.date)``。

    回傳價格視界(R1 的 ``max daily_prices.date``)。``historical`` 只給「在同一個
    as_of 重現舊裁決」用:那時的價格視界讀不回來,所以預設保守地取 as_of 本身;
    要逐位元重現一次視界是 as_of 之後那一天的執行,把那次 JSON 的
    ``metadata.price_horizon`` 用 ``price_horizon`` 傳回來(只在 ``historical`` 時可用)。
    """
    if price_horizon is not None and not historical:
        raise ValueError("--price-horizon is only allowed with --historical")
    if max_futures_date is None:
        raise ValueError("futures_daily is empty")
    if max_price_date is None:
        raise ValueError("daily_prices is empty")
    required = min(max_futures_date, max_price_date)
    if as_of > required:
        raise ValueError(
            f"as-of {as_of} is after the last day both futures and spot are imported "
            f"({required})"
        )
    if as_of != required:
        if not historical:
            raise ValueError(
                f"as-of {as_of} is not min(max futures_daily.date, max daily_prices.date) "
                f"= {required} (docs/40 §0); pass --historical only to reproduce an "
                "earlier run"
            )
        if price_horizon is None:
            return as_of
        if not as_of <= price_horizon <= max_price_date:
            raise ValueError(
                f"price-horizon {price_horizon} must lie in [as-of {as_of}, last "
                f"daily_prices date {max_price_date}]"
            )
        return price_horizon
    if price_horizon is not None and price_horizon != max_price_date:
        raise ValueError("price-horizon on a current run is max daily_prices.date")
    return max_price_date


# ── §0 / §3.1:訊號、事件、對照候選(不碰任何結果價格) ──────────────────────

def judge_stock_days(
    *,
    futures_days: Sequence[str],
    excluded: frozenset[str],
    undeterminable: frozenset[str],
    contracts: Sequence[dict[str, Any]],
    per_contract: dict[str, dict[str, Any]],
    spot: dict[str, tuple[list[str], dict[str, int | None]]],
) -> dict[str, Any]:
    """每一個契約-日交給上線中的那條規則判讀,再依 (股票, 日) 彙總。

    彙總只保留 §0 與 §3.1 用得到的三件事:幾個契約舉旗、有沒有契約被看過且無否決
    且沒舉旗、有沒有契約以 ``R2b_immaterial`` 被否決。
    """
    by_day: dict[tuple[str, str], dict[str, Any]] = {}
    refusals: dict[str, int] = {}
    counts = {
        "contract_days_evaluated": 0,
        "contract_days_in_settlement_window": 0,
        "contract_days_settlement_undeterminable": 0,
        "contract_days_without_regular_session_row": 0,
    }
    for contract in contracts:
        daily = per_contract.get(contract["contract_code"])
        if daily is None:
            continue
        stock_id = contract["stock_id"]
        calendar = spot.get(stock_id)
        volumes = daily["volume"]
        for day in futures_days:
            if day in excluded:
                counts["contract_days_in_settlement_window"] += 1
                continue
            if day in undeterminable:
                # docs/38 §7.13:算不出結算窗口 ⇒ 不主張,絕不當成「沒有被排除」。
                counts["contract_days_settlement_undeterminable"] += 1
                continue
            if volumes.get(day) is None:
                counts["contract_days_without_regular_session_row"] += 1
                continue
            counts["contract_days_evaluated"] += 1
            outcome = evaluate_contract_day_in_calendar(
                candidate=day,
                futures_days=futures_days,
                excluded=excluded,
                volumes=volumes,
                open_interest=daily["open_interest"],
                multiplier=contract["contract_multiplier"],
                spot_volumes=None if calendar is None else calendar[1],
            )
            cell = by_day.setdefault(
                (stock_id, day), {"flags": 0, "seen_quiet": False, "immaterial": False},
            )
            refusal = outcome["refusal"]
            if refusal is not None:
                refusals[refusal] = refusals.get(refusal, 0) + 1
                if refusal == "R2b_immaterial":
                    cell["immaterial"] = True
            elif outcome["flag"]:
                cell["flags"] += 1
            else:
                cell["seen_quiet"] = True
    return {"by_day": by_day, "contract_refusals": dict(sorted(refusals.items())), **counts}


def _spot_flag(
    spot: dict[str, tuple[list[str], dict[str, int | None]]], stock_id: str, day: str,
) -> bool | None:
    calendar = spot.get(stock_id)
    if calendar is None:
        return None
    return spot_new_high(stock_days=calendar[0], volumes=calendar[1], day=day)


def event_days(
    *, signal_days: set[tuple[str, str]], futures_days: Sequence[str],
) -> list[tuple[str, str]]:
    """連續段取首日:**期貨日曆上**前一個期貨交易日不是 s 的訊號日 → 事件。

    段落在完整日曆上認定;非訊號日(含 R4 排除日、該股沒舉旗的日子)切斷段落。
    """
    previous_of = {day: futures_days[i - 1] for i, day in enumerate(futures_days) if i}
    return sorted(
        (stock_id, day) for stock_id, day in signal_days
        if (stock_id, previous_of.get(day)) not in signal_days
    )


def signal_structure(
    *,
    as_of: str,
    futures_days: Sequence[str],
    market_days: Sequence[str],
    contracts: Sequence[dict[str, Any]],
    stock_types: dict[str, str | None],
    per_contract: dict[str, dict[str, Any]],
    spot: dict[str, tuple[list[str], dict[str, int | None]]],
) -> dict[str, Any]:
    """§0 與 §3.1 中**不需要任何結果價格**的那一半。--coverage-only 只走到這裡。

    ``market_days`` 是 D 到價格視界為止;``futures_days`` 到 as_of 為止。
    """
    futures_days = [day for day in futures_days if day <= as_of]
    if not futures_days:
        raise ValueError("no futures trading day at or before as-of")
    excluded = frozenset(settlement_exclusion_set(
        date_from=futures_days[0], date_to=as_of, market_days=market_days,
    ))
    undeterminable = frozenset(
        day for day in futures_days
        if day not in excluded
        and not settlement_is_determinable(candidate=day, market_days=market_days)
    )
    judged = judge_stock_days(
        futures_days=futures_days, excluded=excluded, undeterminable=undeterminable,
        contracts=contracts, per_contract=per_contract, spot=spot,
    )
    by_day = judged["by_day"]

    def in_population(stock_id: str) -> bool:
        return stock_types.get(stock_id) == POPULATION_TYPE

    signal_all: set[tuple[str, str]] = set()
    non_population_signal_days = 0
    two_contract_signal_days = 0
    spot_unknown_flag_days = 0
    pool_candidates: list[tuple[str, str]] = []
    first_seen: str | None = None
    for (stock_id, day), cell in sorted(by_day.items(), key=lambda item: (item[0][1], item[0][0])):
        population = in_population(stock_id)
        if population and (cell["flags"] or cell["seen_quiet"]):
            if first_seen is None or day < first_seen:
                first_seen = day
        spot_flag = _spot_flag(spot, stock_id, day) if (cell["flags"] or cell["seen_quiet"]) else None
        if cell["flags"]:
            if spot_flag is None:
                spot_unknown_flag_days += int(population)
            if spot_flag is False:
                if not population:
                    non_population_signal_days += 1
                    continue
                signal_all.add((stock_id, day))
                if cell["flags"] >= 2:
                    two_contract_signal_days += 1
            continue
        # §3.1 合格對照日 1–4(第 5 條要結果價格,在 assemble 才判)。
        if (
            population
            and cell["seen_quiet"]
            and not cell["immaterial"]
            and spot_flag is False
            and not in_exclusion_window(day)
        ):
            pool_candidates.append((stock_id, day))

    if first_seen is None:
        raise ValueError("no contract-day in the population was seen by the rule unrefused")

    events_all = event_days(signal_days=signal_all, futures_days=futures_days)
    events = [key for key in events_all if not in_exclusion_window(key[1])]
    signal_days = sorted(key for key in signal_all if not in_exclusion_window(key[1]))

    eval_days = [
        day for day in market_days
        if first_seen <= day <= as_of and not in_exclusion_window(day)
    ]
    halves = split_window(trading_days=eval_days, window_days=len(eval_days))
    h1_last = halves["formation_to"]

    def half_of(day: str) -> str:
        return "H1" if day <= h1_last else "H2"

    return {
        "as_of": as_of,
        "futures_days": futures_days,
        "excluded": excluded,
        "undeterminable": undeterminable,
        "evaluation_from": first_seen,
        "evaluation_to": as_of,
        "eval_days": eval_days,
        "halves": halves,
        "half_of": half_of,
        "signal_days": signal_days,
        "events": events,
        "pool_candidates": pool_candidates,
        "counts": {
            "signal_days_removed_by_x": len(signal_all) - len(signal_days),
            "events_removed_by_x": len(events_all) - len(events),
            "market_days_removed_by_x": sum(
                1 for day in market_days
                if first_seen <= day <= as_of and in_exclusion_window(day)
            ),
            "non_population_signal_days": non_population_signal_days,
            "two_contract_signal_days": two_contract_signal_days,
            "flagged_days_with_unknown_spot_flag": spot_unknown_flag_days,
            "settlement_excluded_days": len(excluded),
            "settlement_undeterminable_days": len(undeterminable),
            "contract_days_evaluated": judged["contract_days_evaluated"],
            "contract_days_in_settlement_window": judged["contract_days_in_settlement_window"],
            "contract_days_settlement_undeterminable": (
                judged["contract_days_settlement_undeterminable"]
            ),
            "contract_days_without_regular_session_row": (
                judged["contract_days_without_regular_session_row"]
            ),
            "contract_refusals": judged["contract_refusals"],
        },
    }


def coverage_summary(structure: dict[str, Any]) -> dict[str, Any]:
    """§4 步驟 2 允許記錄的數:評估期起訖、訊號日數、事件數(未經 R1/R2)。"""
    return {
        "evaluation_from": structure["evaluation_from"],
        "evaluation_to": structure["evaluation_to"],
        "signal_days": len(structure["signal_days"]),
        "events_before_outcome_refusals": len(structure["events"]),
        "x_from": EXCLUSION_FROM,
        "x_to": EXCLUSION_TO,
        "signal_days_removed_by_x": structure["counts"]["signal_days_removed_by_x"],
        "events_removed_by_x": structure["counts"]["events_removed_by_x"],
        "non_population_signal_days": structure["counts"]["non_population_signal_days"],
    }


# ── §0 / §2:單一 (s, t) 的結果 ─────────────────────────────────────────────

def moved_up(*, open_price: float, close_price: float, pct: int) -> bool:
    return _dec(close_price) * 100 >= _dec(open_price) * (100 + pct)


def moved_down(*, open_price: float, close_price: float, pct: int) -> bool:
    return _dec(close_price) * 100 <= _dec(open_price) * (100 - pct)


def _moves(bar: dict[str, Any]) -> dict[int, tuple[bool, bool]]:
    return {
        pct: (
            moved_up(open_price=bar["open"], close_price=bar["close"], pct=pct),
            moved_down(open_price=bar["open"], close_price=bar["close"], pct=pct),
        )
        for pct in (THRESHOLD_PCT, *COMPANION_THRESHOLDS_PCT)
    }


def assess(
    *,
    entry: str | None,
    horizon: str,
    entry_bar: dict[str, Any] | None,
    visible_bar: dict[str, Any] | None,
) -> dict[str, Any]:
    """§2 否決,或 e 日的漲跌與 §3.6 伴隨旗標。

    ``visible_bar`` 是 (s, v) 的價格列,只給 R3 漲停代理與「買不到的那一天」用。
    """
    if entry is None or entry > horizon:
        return {"refusal": "R1_no_entry_day"}
    if entry_bar is None:
        return {"refusal": "R1_no_entry_row"}
    if entry_bar["open"] is None or entry_bar["open"] <= 0:
        return {"refusal": "R1_bad_open"}
    if entry_bar["close"] is None:
        return {"refusal": "R1_no_close"}
    if not entry_bar["volume"]:
        return {"refusal": "R2_suspended"}
    moves = _moves(entry_bar)
    limit_open = visible_moves = None
    if visible_bar is not None:
        close_v = visible_bar["close"]
        if close_v is not None and close_v > 0:
            limit_open = (
                _dec(entry_bar["open"]) * 1000 >= _dec(close_v) * LIMIT_PROXY_PERMILLE
            )
        if visible_bar["open"] is not None and visible_bar["open"] > 0 and close_v is not None:
            visible_moves = _moves(visible_bar)[THRESHOLD_PCT]
    return {
        "refusal": None,
        "hit": moves[THRESHOLD_PCT][0],
        "drop": moves[THRESHOLD_PCT][1],
        "moves": moves,
        "limit_open": limit_open,
        "visible": visible_moves,
    }


def tally(keys: Iterable[tuple[str, str]], assessed: dict[tuple[str, str], dict[str, Any]]) -> dict[str, int]:
    """一批 (s, t) 的漲跌次數;§3.6 的 +5/+7 與 v 日一起數。"""
    counts = {"n": 0, "hits": 0, "drops": 0, "visible_hits": 0, "visible_drops": 0,
              "visible_unknown": 0}
    for pct in COMPANION_THRESHOLDS_PCT:
        counts[f"up_{pct}"] = counts[f"down_{pct}"] = 0
    for key in keys:
        outcome = assessed[key]
        counts["n"] += 1
        counts["hits"] += int(outcome["hit"])
        counts["drops"] += int(outcome["drop"])
        for pct in COMPANION_THRESHOLDS_PCT:
            counts[f"up_{pct}"] += int(outcome["moves"][pct][0])
            counts[f"down_{pct}"] += int(outcome["moves"][pct][1])
        if outcome["visible"] is None:
            counts["visible_unknown"] += 1
        else:
            counts["visible_hits"] += int(outcome["visible"][0])
            counts["visible_drops"] += int(outcome["visible"][1])
    return counts


# ── §3:檢定 ───────────────────────────────────────────────────────────────

def direction_result(
    *, seed: int, n: int, h: int, d: int, h_p: int, d_p: int, matched: bool,
) -> dict[str, Any]:
    """單一 seed 的檢定 D:``(h − d) − (h_P − d_P) ≥ 2σ_N``。

    ``σ_N = max(1, sqrt(h_P + d_P − (h_P − d_P)² / n))``;根號內乘 n 以整數算,
    再除回去,值相同。
    """
    if not n or not matched:
        return {
            "seed": seed, "n": n, "h": h, "d": d, "h_p": h_p, "d_p": d_p,
            "sigma_n": None, "margin": None, "evaluable": False, "passed": False,
        }
    variance_times_n = n * (h_p + d_p) - (h_p - d_p) ** 2
    sigma_n = max(1.0, math.sqrt(variance_times_n / n))
    lhs = (h - d) - (h_p - d_p)
    return {
        "seed": seed, "n": n, "h": h, "d": d, "h_p": h_p, "d_p": d_p,
        "sigma_n": round(sigma_n, 6),
        "margin": round(PLACEBO_SIGMA_MULTIPLE * sigma_n, 6),
        "excess_net_up": lhs,
        "evaluable": True,
        "passed": lhs >= PLACEBO_SIGMA_MULTIPLE * sigma_n,
    }


def power_verdict(*, n: int, h: int) -> dict[str, Any]:
    """檢定 A:``n >= 30`` **且** ``h >= 30``。不足是無結果,不是否證。"""
    threshold = LOW_SAMPLE_SURVIVORS
    passed = n >= threshold and h >= threshold
    outcome = "PASS" if passed else "UNDERPOWERED"
    return {
        "test": "A_power",
        "threshold": f"n >= {threshold} and h >= {threshold} (LOW_SAMPLE_SURVIVORS)",
        "passed": passed,
        "outcome": outcome,
        "observed": {"n": n, "h": h, "threshold": threshold},
        "line": (
            f"[{outcome}] A_power: n = {n}, h = {h}, threshold {threshold}"
            + ("" if passed else
               "; inconclusive for want of power, NOT a refutation; re-run only after "
               ">= 60 new market days since this as_of (§3.7)")
        ),
    }


def direction_verdict(*, seeds: list[dict[str, Any]]) -> dict[str, Any]:
    """檢定 D:兩組對照 × 10 seed = 20 個判準,**全部**要過。"""
    threshold = (
        f"for both placebos and every seed in {list(PLACEBO_SEEDS)}: "
        f"(h - d) - (h_P - d_P) >= {PLACEBO_SIGMA_MULTIPLE} * sigma_N"
    )
    evaluable = bool(seeds) and all(entry["evaluable"] for entry in seeds)
    if not evaluable:
        return {
            "test": "D_direction", "threshold": threshold,
            "passed": False, "evaluable": False, "outcome": "NOT EVALUABLE",
            "seeds": seeds,
            "line": "[NOT EVALUABLE] D_direction: a placebo could not be drawn at size",
        }
    failed = [f"{entry['placebo']}/seed={entry['seed']}" for entry in seeds if not entry["passed"]]
    outcome = "FAIL" if failed else "PASS"
    return {
        "test": "D_direction", "threshold": threshold,
        "passed": not failed, "evaluable": True, "outcome": outcome,
        "seeds": seeds,
        "line": (
            f"[{outcome}] D_direction: "
            + ("all 20 criteria clear the 2-sigma margin" if not failed
               else f"{failed} do not clear the 2-sigma margin; one failure is a failure")
        ),
    }


DIRECTION_FAILED_STATUS = (
    "多出來的漲,大致被同樣多出來的跌抵掉;這個訊號預告的是波動,不是上漲。"
)


def overall_verdict(
    *,
    test_a: dict[str, Any],
    test_b: dict[str, Any],
    test_d: dict[str, Any],
    test_c: dict[str, Any],
) -> dict[str, Any]:
    """§3.7:A、B、D、C 全過才 SHIP;理由依序取第一個成立者。"""
    if not test_a["passed"]:
        return _decision("DO NOT SHIP", "underpowered", test_a["line"])
    for test in (test_b, test_d, test_c):
        if not test["evaluable"]:
            return _decision("DO NOT SHIP", "not_evaluable", test["line"])
    if not test_b["passed"]:
        return _decision("DO NOT SHIP", "informativeness_failed", test_b["line"])
    if not test_d["passed"]:
        decision = _decision("DO NOT SHIP", "direction_failed", test_d["line"])
        decision["status_text"] = DIRECTION_FAILED_STATUS
        return decision
    if not test_c["passed"]:
        return _decision("DO NOT SHIP", "consistency_failed", test_c["line"])
    return _decision("SHIP", "a_b_d_c_passed", "A, B, D and C all pass")


def _decision(decision: str, reason: str, detail: str) -> dict[str, Any]:
    return {
        "decision": decision,
        "reason": reason,
        "line": f"[{decision}] futures signal next-day count: {reason} ({detail})",
        "note": (
            "numbers stay in this JSON; nothing is written to any table, export or "
            "panel unless the decision is SHIP"
        ),
    }


def signal_facts(
    *,
    date_from: str | None,
    date_to: str | None,
    events: int,
    hits: int,
    drops: int,
    placebo_stock_hits: Sequence[int],
    placebo_stock_drops: Sequence[int],
    placebo_date_hits: Sequence[int],
    placebo_date_drops: Sequence[int],
) -> dict[str, Any] | None:
    """§1 的事實:整數與日期。export 將來要用的**同一個**函式(§3.9)。

    沒有事件、或任一組對照沒有數字 → ``None``:沒有算出來就沒有主張,不塌成 0。
    """
    if not events or not placebo_stock_hits or not placebo_date_hits:
        return None

    def span(values: Sequence[int]) -> dict[str, int]:
        return {"min": int(min(values)), "max": int(max(values))}

    return {
        "from": date_from,
        "to": date_to,
        "events": int(events),
        "hits": int(hits),
        "drops": int(drops),
        "placebo_stock_hits": span(placebo_stock_hits),
        "placebo_stock_drops": span(placebo_stock_drops),
        "placebo_date_hits": span(placebo_date_hits),
        "placebo_date_drops": span(placebo_date_drops),
        "threshold_pct": THRESHOLD_PCT,
        "leg": LEG,
    }


# ── 組裝(需要結果價格) ────────────────────────────────────────────────────

def assemble(
    *,
    structure: dict[str, Any],
    market_days: Sequence[str],
    horizon: str,
    bars: dict[tuple[str, str], dict[str, Any]],
    run_number: int,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    half_of: Callable[[str], str] = structure["half_of"]

    assessed: dict[tuple[str, str], dict[str, Any]] = {}

    def judge(key: tuple[str, str]) -> dict[str, Any]:
        if key not in assessed:
            stock_id, day = key
            entry = entry_day(market_days, day)
            visible = visible_day(market_days, day)
            assessed[key] = assess(
                entry=entry,
                horizon=horizon,
                entry_bar=None if entry is None else bars.get((stock_id, entry)),
                visible_bar=None if visible is None else bars.get((stock_id, visible)),
            )
        return assessed[key]

    event_refusals = dict.fromkeys(REFUSAL_CODES, 0)
    events: list[tuple[str, str]] = []
    for key in structure["events"]:
        refusal = judge(key)["refusal"]
        if refusal is not None:
            event_refusals[refusal] += 1
        else:
            events.append(key)

    pool_refusals = dict.fromkeys(REFUSAL_CODES, 0)
    pool_stock: dict[tuple[str, str], list[tuple[str, str]]] = {}
    pool_date: dict[str, list[tuple[str, str]]] = {}
    for key in structure["pool_candidates"]:
        refusal = judge(key)["refusal"]
        if refusal is not None:
            pool_refusals[refusal] += 1
            continue
        stock_id, day = key
        pool_stock.setdefault((stock_id, half_of(day)), []).append(key)
        pool_date.setdefault(day, []).append(key)

    n = len(events)
    signal = tally(events, assessed)
    h, d = signal["hits"], signal["drops"]
    by_half = {
        half: tally((key for key in events if half_of(key[1]) == half), assessed)
        for half in ("H1", "H2")
    }

    counts_stock: dict[tuple[str, str], int] = {}
    counts_date: dict[str, int] = {}
    for stock_id, day in events:
        counts_stock[(stock_id, half_of(day))] = counts_stock.get((stock_id, half_of(day)), 0) + 1
        counts_date[day] = counts_date.get(day, 0) + 1

    seeds_b: list[dict[str, Any]] = []
    seeds_d: list[dict[str, Any]] = []
    consistency: list[dict[str, Any]] = []
    placebo_counts: dict[str, list[dict[str, Any]]] = {"stock": [], "date": []}
    spans: dict[str, dict[str, list[int]]] = {
        "stock": {"hits": [], "drops": []}, "date": {"hits": [], "drops": []},
    }
    short_report: dict[str, list[dict[str, Any]]] = {"stock": [], "date": []}
    for placebo, pools, counts in (
        ("stock", pool_stock, counts_stock),
        ("date", pool_date, counts_date),
    ):
        for seed in PLACEBO_SEEDS:
            draw = draw_matched(pools=pools, counts=counts, seed=seed)
            matched = not draw["short"]
            if draw["short"] and not short_report[placebo]:
                # 池子大小不隨 seed 變,差額記一次就夠。
                short_report[placebo] = [
                    _short_entry(placebo, entry) for entry in draw["short"]
                ]
            control = tally(draw["drawn"], assessed)
            h_p, d_p = control["hits"], control["drops"]
            if matched:
                spans[placebo]["hits"].append(h_p)
                spans[placebo]["drops"].append(d_p)
            entry_b = seed_result(seed=seed, n=n, h_f=h, h_p=h_p, matched=matched)
            seeds_b.append({"placebo": placebo, **entry_b})
            entry_d = direction_result(
                seed=seed, n=n, h=h, d=d, h_p=h_p, d_p=d_p, matched=matched,
            )
            seeds_d.append({"placebo": placebo, **entry_d})
            placebo_counts[placebo].append({
                "seed": seed, "matched": matched, **control,
                "sigma_p": entry_b["sigma_p"], "sigma_n": entry_d["sigma_n"],
            })
            h_p_by_half = {"H1": 0, "H2": 0}
            for key in draw["drawn"]:
                if assessed[key]["hit"]:
                    h_p_by_half[half_of(key[1])] += 1
            for half in ("H1", "H2"):
                consistency.append({
                    "placebo": placebo, "seed": seed, "half": half,
                    "h": by_half[half]["hits"], "h_p": h_p_by_half[half],
                    "evaluable": matched,
                    "passed": matched and by_half[half]["hits"] - h_p_by_half[half] > 0,
                })

    test_a = power_verdict(n=n, h=h)
    test_b = informativeness_verdict(seeds=seeds_b)
    test_d = direction_verdict(seeds=seeds_d)
    test_c = consistency_verdict(entries=consistency)
    verdict = overall_verdict(test_a=test_a, test_b=test_b, test_d=test_d, test_c=test_c)

    scored_days = sorted(day for _, day in events)
    facts = signal_facts(
        date_from=scored_days[0] if scored_days else None,
        date_to=scored_days[-1] if scored_days else None,
        events=n, hits=h, drops=d,
        placebo_stock_hits=spans["stock"]["hits"],
        placebo_stock_drops=spans["stock"]["drops"],
        placebo_date_hits=spans["date"]["hits"],
        placebo_date_drops=spans["date"]["drops"],
    )

    # §3.6 伴隨計數:只報告,永遠不是判準,永遠不是補救。
    by_month: dict[str, dict[str, int]] = {}
    limit_open = limit_unknown = 0
    for key in events:
        outcome = assessed[key]
        cell = by_month.setdefault(key[1][:7], {"events": 0, "hits": 0, "drops": 0})
        cell["events"] += 1
        cell["hits"] += int(outcome["hit"])
        cell["drops"] += int(outcome["drop"])
        if outcome["limit_open"] is None:
            limit_unknown += 1
        elif outcome["limit_open"]:
            limit_open += 1
    all_signal_refusals = dict.fromkeys(REFUSAL_CODES, 0)
    all_signal_scored: list[tuple[str, str]] = []
    for key in structure["signal_days"]:
        refusal = judge(key)["refusal"]
        if refusal is None:
            all_signal_scored.append(key)
        else:
            all_signal_refusals[refusal] += 1
    all_signal = tally(all_signal_scored, assessed)

    halves = structure["halves"]
    counts = structure["counts"]
    return {
        "metadata": {
            "report": REPORT_NAME,
            "as_of": structure["as_of"],
            "price_horizon": horizon,
            "run_number": run_number,
            "preregistration_doc": PREREGISTRATION_DOC,
            "preregistration_commit": PREREGISTRATION_COMMIT,
            "seeds": list(PLACEBO_SEEDS),
            "read_only": True,
            **(metadata or {}),
        },
        "coverage": {
            "evaluation_from": structure["evaluation_from"],
            "evaluation_to": structure["evaluation_to"],
            "market_days_in_halves": len(structure["eval_days"]),
            "futures_from": structure["futures_days"][0],
            "futures_to": structure["futures_days"][-1],
            "signal_days": len(structure["signal_days"]),
            "events_before_outcome_refusals": len(structure["events"]),
            **{key: value for key, value in counts.items() if key not in (
                "signal_days_removed_by_x", "events_removed_by_x",
                "market_days_removed_by_x", "non_population_signal_days",
                "two_contract_signal_days",
            )},
        },
        "x_window": {
            "from": EXCLUSION_FROM,
            "to": EXCLUSION_TO,
            "signal_days_removed": counts["signal_days_removed_by_x"],
            "events_removed": counts["events_removed_by_x"],
            "market_days_removed": counts["market_days_removed_by_x"],
        },
        "halves": {
            "H1": [halves["formation_from"], halves["formation_to"]],
            "H2": [halves["evaluation_from"], halves["evaluation_to"]],
            "H1_market_days": halves["formation_market_days"],
            "H2_market_days": halves["evaluation_market_days"],
        },
        "sets": {
            "events": n,
            "hits": h,
            "drops": d,
            "events_by_half": {half: by_half[half]["n"] for half in by_half},
            "hits_by_half": {half: by_half[half]["hits"] for half in by_half},
            "drops_by_half": {half: by_half[half]["drops"] for half in by_half},
            "pool_days": sum(len(pool) for pool in pool_date.values()),
            "placebo_short": short_report,
        },
        "refusals": {"events": event_refusals, "pool": pool_refusals},
        "placebo_counts": placebo_counts,
        "tests": {"A": test_a, "B": test_b, "D": test_d, "C": test_c},
        "verdict": verdict,
        "facts": facts,
        "companion": {
            "signal": signal,
            "signal_by_half": by_half,
            "entry_open_at_limit_proxy": limit_open,
            "entry_open_at_limit_proxy_unknown": limit_unknown,
            "by_month": dict(sorted(by_month.items())),
            "two_contract_signal_days": counts["two_contract_signal_days"],
            "all_signal_days": len(structure["signal_days"]),
            "all_signal_days_scored": all_signal["n"],
            "all_signal_days_hits": all_signal["hits"],
            "all_signal_days_drops": all_signal["drops"],
            "all_signal_days_refusals": all_signal_refusals,
            "signal_days_removed_by_x": counts["signal_days_removed_by_x"],
            "events_removed_by_x": counts["events_removed_by_x"],
            "non_population_signal_days": counts["non_population_signal_days"],
        },
        "definitions": _definitions(),
        "choices": _choices(),
    }


def _short_entry(placebo: str, entry: dict[str, Any]) -> dict[str, Any]:
    if placebo == "stock":
        stock_id, half = entry["key"]
        return {"stock_id": stock_id, "half": half, "k": entry["k"],
                "pool_size": entry["pool_size"]}
    return {"date": entry["key"], "k": entry["k"], "pool_size": entry["pool_size"]}


def _definitions() -> dict[str, str]:
    return {
        "signal_day": (
            "t a futures trading day <= as_of, not an R4 settlement-window day; at least "
            "one contract on s seen by the docs/38 rule unrefused with flag = True, AND "
            "S(s, t) established False; unknown S is not a signal day; one per stock"
        ),
        "event": (
            "a signal day whose previous futures trading day (full futures calendar) is "
            "not a signal day of the same stock; runs are found on the full calendar "
            f"BEFORE the exclusion window X = [{EXCLUSION_FROM}, {EXCLUSION_TO}] is applied"
        ),
        "e": (
            "the 2nd market day after t in D (every date with any daily_prices row); "
            "computed from the calendar, never read from a stored column"
        ),
        "hit": (
            f"100 x close(s, e) >= {100 + THRESHOLD_PCT} x open(s, e), raw prices, same "
            "row, decimal comparison"
        ),
        "drop": f"100 x close(s, e) <= {100 - THRESHOLD_PCT} x open(s, e)",
        "pools": (
            "eligible (s, d): s a stock; d a futures day <= as_of, not R4, not in X; some "
            "contract seen unrefused with flag False; no contract flagged (any S) and none "
            "refused R2b_immaterial; S(s, d) established False; (s, e(d)) passes R1-R2. "
            "Days next to events are deliberately NOT removed (§3.1)"
        ),
        "sigma_p": "max(1, sqrt(n * p_hat * (1 - p_hat))), p_hat = h_P / n (seed_result)",
        "sigma_n": "max(1, sqrt(h_P + d_P - (h_P - d_P)^2 / n))",
        "entry_open_at_limit_proxy": (
            f"report only: open(s, e) x 1000 >= close(s, v) x {LIMIT_PROXY_PERMILLE}, raw "
            "prices; an ex-dividend e understates it"
        ),
        "visible_day": (
            "report only: v(t) = the 1st market day after t; its open-to-close >= 3% / "
            "<= -3% counts can never change the verdict (§3.6)"
        ),
    }


def _choices() -> list[dict[str, str]]:
    """docs/40 有一個以上合理讀法的地方,連同這裡選了哪一個。"""
    return [
        {
            "where": "§0 R4 at the calendar edge",
            "choice": (
                "a futures day whose settlement window cannot be located "
                "(settlement_is_determinable False, docs/38 §7.13) is treated like an R4 "
                "day: not a signal day, not a control day, and it breaks runs"
            ),
        },
        {
            "where": "§2 R1 horizon on a current run",
            "choice": (
                "e is checked against max daily_prices.date (the literal R1 text), which "
                "can be one market day after as_of; the R4 calendar is read to the same "
                "horizon (the docs/38 §7.13 data_date reading). metadata.price_horizon "
                "records it"
            ),
        },
        {
            "where": "§0 as_of with --historical",
            "choice": (
                "a historical run cannot know the horizon of the run it reproduces, so by "
                "default it uses as_of itself (more R1 refusals, never more events). A run "
                "whose horizon was as_of + 1 is therefore NOT guaranteed to reproduce "
                "bit-exactly unless its metadata.price_horizon is passed back with "
                "--price-horizon (accepted only together with --historical)"
            ),
        },
        {
            "where": "§3.1 evaluation period and halves",
            "choice": (
                "the evaluation period starts at the earliest futures day on which any "
                "contract-day of a type='stock' underlying was seen by the rule unrefused "
                "(flagged or not); the halves split D's market days in [start, as_of] "
                "minus X with split_window (the odd day to H2)"
            ),
        },
        {
            "where": "§4 step 2 coverage-only",
            "choice": (
                "reads daily_prices.volume on every day (it is the input of S and R2b, not "
                "a price) and never open/close; the connection is sealed by a SQLite "
                "authorizer whitelist. Its events count is before R1/R2; it also reports "
                "what X removed"
            ),
        },
        {
            "where": "§3.6 companion counts",
            "choice": (
                "a control's v-day open-to-close is counted on the same draw; a v-day row "
                "that is missing or has a bad open is counted as visible_unknown. "
                "entry_open_at_limit_proxy counts scored events only, an unknown "
                "close(s, v) counted separately; two_contract_signal_days counts every "
                "stock signal day with >= 2 flagging contracts, X included"
            ),
        },
        {
            "where": "§1 placebo ranges and §3.3 short draws",
            "choice": (
                "min/max are over fully drawn seeds only; any short key makes B, D and C "
                "NOT EVALUABLE and is listed as (stock_id, half, k, pool_size) or "
                "(date, k, pool_size)"
            ),
        },
        {
            "where": "§1 naming",
            "choice": (
                "the §1 object is 'facts' (docs/39 used facts_if_shipped), produced by "
                "signal_facts(), the function §3.9 requires the export to reuse"
            ),
        },
    ]


# ── 載入(唯讀) ──────────────────────────────────────────────────────────

def load_stock_types(conn) -> dict[str, str | None]:
    return {row[0]: row[1] for row in conn.execute(text("SELECT id, type FROM stocks"))}


def load_outcome_bars(
    conn, *, horizon: str, date_from: str, stock_ids: set[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    """結果價格。**唯一**讀 open/close 的地方;--coverage-only 從不呼叫它。"""
    bars: dict[tuple[str, str], dict[str, Any]] = {}
    rows = conn.execute(text("""
        SELECT stock_id, date, open, close, volume FROM daily_prices
        WHERE date >= :date_from AND date <= :horizon
    """), {"date_from": date_from, "horizon": horizon}).mappings()
    for row in rows:
        if row["stock_id"] in stock_ids:
            bars[(row["stock_id"], row["date"])] = {
                "open": row["open"], "close": row["close"], "volume": row["volume"],
            }
    return bars


def seal_outcome_columns(dbapi_connection: sqlite3.Connection) -> None:
    """這條連線只讀得到 :data:`COVERAGE_READABLE_COLUMNS`(SQLite authorizer)。

    白名單而不是黑名單:任何價格、結算價、往後報酬或沒被列出的表,一律拒讀。
    SQLite 自己的系統表(``sqlite_*``)放行。
    """
    def authorizer(action, table, column, _db, _source):
        if action != sqlite3.SQLITE_READ or table is None or table.startswith("sqlite_"):
            return sqlite3.SQLITE_OK
        if column in COVERAGE_READABLE_COLUMNS.get(table, ()):
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    dbapi_connection.set_authorizer(authorizer)


def _load_inputs(conn, *, as_of: str, horizon: str) -> dict[str, Any]:
    contracts = load_contracts(conn)
    return {
        "futures_days": load_futures_calendar(conn, as_of),
        "market_days": load_market_days(conn, horizon),
        "contracts": contracts,
        "stock_types": load_stock_types(conn),
        "per_contract": load_regular_session_volumes(conn, as_of),
        "spot": load_spot_daily(
            conn, as_of=horizon,
            stock_ids=sorted({contract["stock_id"] for contract in contracts}),
        ),
    }


def _open_and_check(
    conn, *, as_of: str, historical: bool, price_horizon: str | None,
) -> str:
    return check_as_of(
        as_of=as_of,
        max_futures_date=conn.execute(text("SELECT MAX(date) FROM futures_daily")).scalar(),
        max_price_date=conn.execute(text("SELECT MAX(date) FROM daily_prices")).scalar(),
        historical=historical,
        price_horizon=price_horizon,
    )


def build_coverage(
    *, as_of: str, historical: bool = False, price_horizon: str | None = None,
) -> dict[str, Any]:
    """§4 步驟 2:只有涵蓋度。不 JOIN、不讀任何結果價格。"""
    as_of = _validate_date(as_of, "as-of")
    if price_horizon is not None:
        price_horizon = _validate_date(price_horizon, "price-horizon")
    engine = get_read_only_sqlite_engine(
        report_name=REPORT_NAME, required_tables=REQUIRED_TABLES,
    )
    try:
        with engine.connect() as conn:
            seal_outcome_columns(conn.connection.dbapi_connection)
            horizon = _open_and_check(conn, as_of=as_of, historical=historical,
                                      price_horizon=price_horizon)
            inputs = _load_inputs(conn, as_of=as_of, horizon=horizon)
    finally:
        engine.dispose()
    structure = signal_structure(as_of=as_of, **inputs)
    return {
        "report": REPORT_NAME,
        "mode": "coverage-only",
        "as_of": as_of,
        "historical_as_of": historical,
        "price_horizon": horizon,
        "preregistration_commit": PREREGISTRATION_COMMIT,
        **coverage_summary(structure),
    }


def build_next_day_futures_signal_battery(
    *, as_of: str, run_number: int = 1, historical: bool = False,
    price_horizon: str | None = None,
) -> dict[str, Any]:
    """跑完整個 battery 並回傳可序列化的結果。全程唯讀。"""
    as_of = _validate_date(as_of, "as-of")
    if price_horizon is not None:
        price_horizon = _validate_date(price_horizon, "price-horizon")
    if not isinstance(run_number, int) or isinstance(run_number, bool) or run_number < 1:
        raise ValueError("run-number must be an integer >= 1")
    engine = get_read_only_sqlite_engine(
        report_name=REPORT_NAME, required_tables=REQUIRED_TABLES,
    )
    try:
        with engine.connect() as conn:
            horizon = _open_and_check(conn, as_of=as_of, historical=historical,
                                      price_horizon=price_horizon)
            inputs = _load_inputs(conn, as_of=as_of, horizon=horizon)
            structure = signal_structure(as_of=as_of, **inputs)
            bars = load_outcome_bars(
                conn, horizon=horizon, date_from=structure["evaluation_from"],
                stock_ids={stock_id for stock_id, _ in structure["pool_candidates"]}
                | {stock_id for stock_id, _ in structure["signal_days"]}
                | {stock_id for stock_id, _ in structure["events"]},
            )
    finally:
        engine.dispose()
    return assemble(
        structure=structure, market_days=inputs["market_days"], horizon=horizon,
        bars=bars, run_number=run_number,
        metadata={"historical_as_of": historical, "x_from": EXCLUSION_FROM,
                  "x_to": EXCLUSION_TO},
    )


def write_next_day_futures_signal_battery(
    *, as_of: str, run_number: int = 1, out: str | Path, historical: bool = False,
    price_horizon: str | None = None,
) -> dict[str, Any]:
    """Build and deterministically write the JSON battery result."""
    out_path = safe_report_output_path(out, report_name=REPORT_NAME)
    report = build_next_day_futures_signal_battery(
        as_of=as_of, run_number=run_number, historical=historical,
        price_horizon=price_horizon,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report
