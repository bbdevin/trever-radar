"""「隔天大漲」次數的事前登記 battery(唯讀,決定這個功能要不要存在)。

它是什麼
--------
``docs/39_next_day_surge_count_preregistration.md`` 是一份**事前登記**:它在任何人
對 ``daily_scores`` 的 ``fwd_*`` 做過彙總、或把 ``daily_scores`` 與次日價格 JOIN
過之前就 commit(``f8a57b5``),裡面每一個數字都不得在看到資料之後修改。這支程式
是那份文件 §0–§3 的可執行版本。它**不是**功能本身:它決定功能要不要被寫出來。

它算什麼
--------
§0 上榜
    與 ``json_export.py`` 的綜合榜逐字相同:``daily_prices`` 當日有收盤價、
    ``stocks.type = 'stock'``、有 ``daily_scores`` 列;``final >= 65``,依
    ``(final, branch_score(None 視為 −∞), turnover)`` 由大到小,取前 40;
    第 40 名三鍵完全同分者一併上榜(``tie_at_cap``)。
§0 上榜事件
    同一檔股票在**連續市場交易日**上榜的一段,只取首日。
§0 命中
    ``100 × close(s, e) ≥ 107 × open(s, e)``,``e`` = t 之後第一個市場交易日,
    原始價、同一列,所以與 ``adj_factor`` 結構上無關。比較用 ``Decimal(repr(x))``
    做:價格是兩位小數,浮點乘法會讓恰好 7.00% 的那一天落在哪一邊變成運氣。
§2 否決
    R1 進場日不成熟或無列;R2 儲存的 ``entry_date``/``fwd_1d`` 與重算不符
    (完整性閘門——儲存值**只作對照**,統計量永遠從 ``daily_prices`` 重算)。
§3 全案否決
    A ``n >= 30`` 且 ``h_L >= 30``;B 兩組等量對照(P_stock 同股同半段、
    P_date 同日他股)× seed 0..9,20 個判準**全部** ``h_L − h_P ≥ 2σ_P``;
    C 兩半各自 ``h_L(h) − h_P(h) > 0``。任一抽不滿 → NOT EVALUABLE。

它不重寫的東西
--------------
``LOW_SAMPLE_SURVIVORS``(30)從 ``branch_window_direction_battery`` import;
``PLACEBO_SEEDS``、``PLACEBO_SIGMA_MULTIPLE`` 與 ``seed_result``(2σ 判準本身)
從 ``futures_volume_battery`` import。第二份 30 或第二份 2σ 就是第二條規則。

寫入
----
沒有。``mode=ro`` 連線、不呼叫 ``init_db()``、不建表、不寫任何一列。
"""
from __future__ import annotations

import json
import random
from bisect import bisect_right
from datetime import date as date_cls
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Sequence

from sqlalchemy import text

from .branch_window_direction_battery import LOW_SAMPLE_SURVIVORS, split_window
from .futures_volume_battery import PLACEBO_SEEDS, PLACEBO_SIGMA_MULTIPLE, seed_result
from .read_only_sqlite import get_read_only_sqlite_engine, safe_report_output_path

REPORT_NAME = "next-day-surge-battery"

REQUIRED_TABLES = ("daily_scores", "daily_prices", "stocks")

PREREGISTRATION_DOC = "docs/39_next_day_surge_count_preregistration.md"
PREREGISTRATION_COMMIT = "f8a57b5"

# §0 命中:7 借自 docs/04 §13 S1_REBOUND_RELAXED「近 20 日曾大漲 ≥7%」。
SURGE_THRESHOLD_PCT = 7
# §1 的 ``leg`` 欄位:讓讀者知道量的是哪一段。
LEG = "entry_open_to_close"

# §0 上榜:與 json_export.py 綜合榜同一組數字。兩處不同步由
# ``test_next_day_surge_battery`` 裡讀 export 原始碼的絆線抓。
LIST_MIN_FINAL = 65
LIST_CAP = 40

# §2 R2:儲存的 fwd_1d 四捨五入到兩位,所以容差是 0.01。
FWD_TOLERANCE = 0.01

# §2 R3(只報告):開盤即漲停的代理,``open(s, e) ≥ 1.095 × close(s, t)``。
LIMIT_PROXY_PERMILLE = 1095

# §3.6 依 final 區間的伴隨計數(只在 battery JSON)。
FINAL_BANDS = ((65, 74), (75, 84), (85, None))

REFUSAL_CODES = (
    "R1_no_entry_day",
    "R1_no_entry_row",
    "R1_bad_open",
    "R1_no_close",
    "R2_entry_shifted",
    "R2_fwd_mismatch",
)

# §1 的形狀。export 若有一天加上這個鍵,就是這幾個欄位、一個不多。
FACT_KEYS = (
    "from", "to", "events", "hits",
    "placebo_stock_hits", "placebo_date_hits",
    "threshold_pct", "leg",
)


def _validate_date(value: str, name: str) -> str:
    try:
        return date_cls.fromisoformat(value).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be YYYY-MM-DD: {value!r}") from exc


def _dec(value: float) -> Decimal:
    """浮點價格的**十進位**值。``repr`` 給最短可還原字串,12.35 就是 12.35。"""
    return Decimal(repr(value))


# ── §0:上榜 ────────────────────────────────────────────────────────────────

def list_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    """``json_export.py`` 綜合榜的排序鍵,逐字搬過來。"""
    branch = row["branch_score"]
    return (
        row["final"],
        branch if branch is not None else float("-inf"),
        row["turnover"] or 0,
    )


def published_list(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """一天的綜合榜:``final >= 65``、前 40、第 40 名完全同分者一併上榜。

    export 的 ``sorted`` 是穩定排序,完全同分者的先後取決於 SQL 回傳順序——那個
    順序不可重現。§0 規定**含入**:它是唯一不需要猜的選擇。
    """
    ranked = sorted(
        (row for row in rows if row["final"] >= LIST_MIN_FINAL),
        key=list_sort_key, reverse=True,
    )
    listed = ranked[:LIST_CAP]
    tie_at_cap = 0
    if len(ranked) > LIST_CAP:
        edge = list_sort_key(ranked[LIST_CAP - 1])
        for row in ranked[LIST_CAP:]:
            if list_sort_key(row) != edge:
                break
            listed.append(row)
            tie_at_cap += 1
    return {
        "stock_ids": {row["stock_id"] for row in listed},
        "tie_at_cap": tie_at_cap,
        "over_cap": len(ranked) - len(listed),
    }


def event_first_days(
    *, on_list: dict[str, set[str]], days: Sequence[str],
) -> list[tuple[str, str]]:
    """連續市場交易日上榜的一段只取首日(docs/04 §5)。

    ``days`` 是評估期內的市場交易日。前一個市場日沒有上榜(包含那天整個
    ``daily_scores`` 缺席)就是段落中斷——不跨缺口接起來。評估期第一天上榜的,
    一律視為首日:它之前的日子不在資料裡,不能被讀成「有上榜」。
    """
    events: list[tuple[str, str]] = []
    previous: set[str] = set()
    for day in days:
        today = on_list.get(day, set())
        for stock_id in sorted(today - previous):
            events.append((stock_id, day))
        previous = today
    return events


# ── §0 / §2:單一 (s, t) 的判讀 ───────────────────────────────────────────

def next_market_day(days: Sequence[str], day: str) -> str | None:
    index = bisect_right(days, day)
    return days[index] if index < len(days) else None


def is_surge(*, open_price: float, close_price: float) -> bool:
    """``100 × close ≥ (100 + 7) × open``,十進位比較。"""
    return _dec(close_price) * 100 >= _dec(open_price) * (100 + SURGE_THRESHOLD_PCT)


def assess(
    *,
    score: dict[str, Any],
    entry_day: str | None,
    entry_bar: dict[str, Any] | None,
    signal_bar: dict[str, Any] | None,
) -> dict[str, Any]:
    """一個評分列:否決碼,或命中與三個只報告的伴隨旗標。

    ``signal_bar`` 是 (s, t) 的價格列,只給 §3.6 的板面計數與 R3 的漲停代理用;
    統計量本身只讀 ``entry_bar``。
    """
    if entry_day is None:
        return {"refusal": "R1_no_entry_day"}
    if entry_bar is None:
        return {"refusal": "R1_no_entry_row"}
    open_e, close_e = entry_bar["open"], entry_bar["close"]
    if open_e is None or open_e <= 0:
        return {"refusal": "R1_bad_open"}
    if close_e is None:
        return {"refusal": "R1_no_close"}
    if score["entry_date"] != entry_day:
        return {"refusal": "R2_entry_shifted"}
    recomputed = 100.0 * (close_e / open_e - 1.0)
    stored = score["fwd_1d"]
    if stored is None or abs(stored - recomputed) > FWD_TOLERANCE:
        return {"refusal": "R2_fwd_mismatch"}

    hit = is_surge(open_price=open_e, close_price=close_e)
    board_hit = limit_open = None
    close_t = None if signal_bar is None else signal_bar["close"]
    if close_t is not None and close_t > 0:
        board_hit = (
            _dec(close_e) * _dec(entry_bar["adj_factor"]) * 100
            >= _dec(close_t) * _dec(signal_bar["adj_factor"]) * (100 + SURGE_THRESHOLD_PCT)
        )
        limit_open = _dec(open_e) * 1000 >= _dec(close_t) * LIMIT_PROXY_PERMILLE
    return {
        "refusal": None,
        "hit": hit,
        "board_hit": board_hit,
        "limit_open": limit_open,
    }


# ── §3.3:等量對照 ─────────────────────────────────────────────────────────

def draw_matched(
    *,
    pools: dict[Any, list[tuple[str, str]]],
    counts: dict[Any, int],
    seed: int,
) -> dict[str, Any]:
    """每個鍵不放回抽 k 個;鍵排序後依序抽,所以同 seed 同資料永遠同一組。

    池子不足 k 時**不重複抽、不跨鍵借**,記進 ``short``:用較少的對照去湊一個
    ``h_P`` 會系統性壓低它,方向是朝著過關。
    """
    rng = random.Random(seed)
    drawn: list[tuple[str, str]] = []
    short: list[dict[str, Any]] = []
    for key in sorted(counts):
        k = counts[key]
        pool = pools.get(key, [])
        if len(pool) < k:
            short.append({"key": key, "k": k, "pool_size": len(pool)})
        take = min(k, len(pool))
        if take:
            drawn.extend(rng.sample(pool, take))
    return {"drawn": sorted(drawn), "short": short}


def consistency_verdict(*, entries: list[dict[str, Any]]) -> dict[str, Any]:
    """檢定 C:每一半、每一組對照、每一個 seed,``h_L(h) − h_P(h) > 0``。只看正負。"""
    threshold = "for every half, placebo and seed: h_L(half) - h_P(half) > 0"
    evaluable = bool(entries) and all(entry["evaluable"] for entry in entries)
    if not evaluable:
        return {
            "test": "C_consistency", "threshold": threshold,
            "passed": False, "evaluable": False, "outcome": "NOT EVALUABLE",
            "entries": entries,
            "line": "[NOT EVALUABLE] C_consistency: a placebo could not be drawn at size",
        }
    failed = [
        f"{entry['placebo']}/seed={entry['seed']}/{entry['half']}"
        for entry in entries if not entry["passed"]
    ]
    outcome = "FAIL" if failed else "PASS"
    return {
        "test": "C_consistency", "threshold": threshold,
        "passed": not failed, "evaluable": True, "outcome": outcome,
        "entries": entries,
        "line": (
            f"[{outcome}] C_consistency: "
            + ("positive in both halves for every placebo and seed" if not failed
               else f"not positive in {failed}")
        ),
    }


def power_verdict(*, n: int, h_l: int) -> dict[str, Any]:
    """檢定 A:``n >= 30`` **且** ``h_L >= 30``。不足是無結果,不是否證。"""
    threshold = LOW_SAMPLE_SURVIVORS
    passed = n >= threshold and h_l >= threshold
    outcome = "PASS" if passed else "UNDERPOWERED"
    return {
        "test": "A_power",
        "threshold": f"n >= {threshold} and h_L >= {threshold} (LOW_SAMPLE_SURVIVORS)",
        "passed": passed,
        "outcome": outcome,
        "observed": {"n": n, "h_l": h_l, "threshold": threshold},
        "line": (
            f"[{outcome}] A_power: n = {n}, h_L = {h_l}, threshold {threshold}"
            + ("" if passed else
               "; this is an inconclusive result for want of power, NOT a refutation; "
               "re-run only after >= 60 new market days (§3.7)")
        ),
    }


def informativeness_verdict(*, seeds: list[dict[str, Any]]) -> dict[str, Any]:
    """檢定 B:兩組對照 × 10 seed = 20 個判準,**全部**要過。"""
    threshold = (
        f"for both placebos and every seed in {list(PLACEBO_SEEDS)}: "
        f"h_L - h_P >= {PLACEBO_SIGMA_MULTIPLE} * sigma_P"
    )
    evaluable = bool(seeds) and all(entry["evaluable"] for entry in seeds)
    if not evaluable:
        return {
            "test": "B_informativeness", "threshold": threshold,
            "passed": False, "evaluable": False, "outcome": "NOT EVALUABLE",
            "seeds": seeds,
            "line": (
                "[NOT EVALUABLE] B_informativeness: a count-matched placebo could not "
                "be drawn at the required size"
            ),
        }
    failed = [f"{entry['placebo']}/seed={entry['seed']}" for entry in seeds if not entry["passed"]]
    outcome = "FAIL" if failed else "PASS"
    return {
        "test": "B_informativeness", "threshold": threshold,
        "passed": not failed, "evaluable": True, "outcome": outcome,
        "seeds": seeds,
        "line": (
            f"[{outcome}] B_informativeness: "
            + ("all 20 criteria clear the 2-sigma margin" if not failed
               else f"{failed} do not clear the 2-sigma margin; one failure is a failure")
        ),
    }


def overall_verdict(
    *, test_a: dict[str, Any], test_b: dict[str, Any], test_c: dict[str, Any],
) -> dict[str, Any]:
    """§3.5:A、B、C 全過才上線;其餘一律不上線,理由不可互換。"""
    if not test_a["passed"]:
        return _decision("DO NOT SHIP", "underpowered", test_a["line"])
    if not test_b["evaluable"] or not test_c["evaluable"]:
        return _decision("DO NOT SHIP", "not_evaluable", test_b["line"])
    if not test_b["passed"]:
        return _decision("DO NOT SHIP", "informativeness_failed", test_b["line"])
    if not test_c["passed"]:
        return _decision("DO NOT SHIP", "consistency_failed", test_c["line"])
    return _decision("SHIP", "a_b_c_passed", "A, B and C all pass")


def _decision(decision: str, reason: str, detail: str) -> dict[str, Any]:
    return {
        "decision": decision,
        "reason": reason,
        "line": f"[{decision}] next-day surge count: {reason} ({detail})",
        "note": (
            "numbers stay in this JSON; nothing is written to any table, export or "
            "panel unless the decision is SHIP"
        ),
    }


def surge_facts(
    *,
    date_from: str | None,
    date_to: str | None,
    events: int,
    hits: int,
    placebo_stock_hits: Sequence[int],
    placebo_date_hits: Sequence[int],
) -> dict[str, Any] | None:
    """§1 的事實:整數與日期,沒有比率、百分比、機率、均值、名次。

    這是 export 將來要用的**同一個**函式(§3.8)。沒有事件、或任一組對照沒有
    數字時回 ``None``——沒有算出來就沒有主張,不塌成 0。
    """
    if not events or not placebo_stock_hits or not placebo_date_hits:
        return None
    return {
        "from": date_from,
        "to": date_to,
        "events": int(events),
        "hits": int(hits),
        "placebo_stock_hits": {
            "min": int(min(placebo_stock_hits)), "max": int(max(placebo_stock_hits)),
        },
        "placebo_date_hits": {
            "min": int(min(placebo_date_hits)), "max": int(max(placebo_date_hits)),
        },
        "threshold_pct": SURGE_THRESHOLD_PCT,
        "leg": LEG,
    }


# ── 載入(唯讀) ──────────────────────────────────────────────────────────

def load_market_days(conn, as_of: str) -> list[str]:
    return [row[0] for row in conn.execute(text("""
        SELECT DISTINCT date FROM daily_prices WHERE date <= :as_of ORDER BY date
    """), {"as_of": as_of}).fetchall()]


def load_scores(conn, as_of: str) -> list[dict[str, Any]]:
    """評分列,帶著 export 決定上榜所需的三個欄位。

    ``has_close`` 對應 export 的 ``p.close IS NOT NULL``:當日沒有收盤價的股票
    不在 export 的 ``all_stocks`` 裡,所以不可能上榜。
    """
    return [dict(row) for row in conn.execute(text("""
        SELECT ds.stock_id, ds.date, ds.final, ds.branch_score,
               ds.entry_date, ds.fwd_1d,
               p.turnover,
               CASE WHEN p.close IS NOT NULL THEN 1 ELSE 0 END AS has_close
        FROM daily_scores ds
        JOIN stocks s ON s.id = ds.stock_id AND s.type = 'stock'
        LEFT JOIN daily_prices p ON p.stock_id = ds.stock_id AND p.date = ds.date
        WHERE ds.date <= :as_of
        ORDER BY ds.date, ds.stock_id
    """), {"as_of": as_of}).mappings()]


def load_bars(
    conn, *, as_of: str, date_from: str, stock_ids: set[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    bars: dict[tuple[str, str], dict[str, Any]] = {}
    rows = conn.execute(text("""
        SELECT stock_id, date, open, close, adj_factor FROM daily_prices
        WHERE date >= :date_from AND date <= :as_of
    """), {"date_from": date_from, "as_of": as_of}).mappings()
    for row in rows:
        if row["stock_id"] in stock_ids:
            bars[(row["stock_id"], row["date"])] = {
                "open": row["open"], "close": row["close"],
                "adj_factor": row["adj_factor"],
            }
    return bars


def load_coverage(conn, as_of: str) -> dict[str, Any]:
    """§4 步驟 2 允許記錄的那幾個數,不是任何門檻的輸入。"""
    first, last, dates, rows = conn.execute(text("""
        SELECT MIN(date), MAX(date), COUNT(DISTINCT date), COUNT(*)
        FROM daily_scores WHERE date <= :as_of
    """), {"as_of": as_of}).one()
    return {
        "daily_scores_first_date": first,
        "daily_scores_last_date": last,
        "daily_scores_dates": int(dates or 0),
        "daily_scores_rows": int(rows or 0),
    }


def build_next_day_surge_battery(
    *, as_of: str, run_number: int = 1, historical: bool = False,
) -> dict[str, Any]:
    """跑完整個 battery 並回傳可序列化的結果。全程唯讀。"""
    as_of = _validate_date(as_of, "as-of")
    if not isinstance(run_number, int) or isinstance(run_number, bool) or run_number < 1:
        raise ValueError("run-number must be an integer >= 1")

    engine = get_read_only_sqlite_engine(
        report_name=REPORT_NAME, required_tables=REQUIRED_TABLES,
    )
    try:
        with engine.connect() as conn:
            check_as_of(
                as_of=as_of,
                max_price_date=conn.execute(text(
                    "SELECT MAX(date) FROM daily_prices"
                )).scalar(),
                historical=historical,
            )
            market_days = load_market_days(conn, as_of)
            scores = load_scores(conn, as_of)
            coverage = load_coverage(conn, as_of)
            bars = (
                load_bars(
                    conn, as_of=as_of, date_from=scores[0]["date"],
                    stock_ids={row["stock_id"] for row in scores},
                )
                if scores else {}
            )
    finally:
        engine.dispose()

    report = assemble(
        as_of=as_of, run_number=run_number, market_days=market_days,
        scores=scores, bars=bars, coverage=coverage,
    )
    report["metadata"]["historical_as_of"] = historical
    return report


# ── 組裝 ────────────────────────────────────────────────────────────────

def evaluation_days(*, market_days: Sequence[str], first_score_day: str) -> list[str]:
    """§3.1 評估期:``daily_scores`` 的第一個日期到 as_of 的市場交易日。

    從**第一個評分日**起算,不是第一個市場日:價格歷史遠早於評分,拿整段價格
    日曆去對半切,兩半會落在完全沒有事件的年份上。
    """
    return [day for day in market_days if day >= first_score_day]


def half_assigner(eval_days: Sequence[str]):
    """§3.1 對半:依 ``split_window`` 慣例,奇數時多的那一天歸後半。

    回傳 ``(halves, half_of)``;``half_of(day)`` 對前半最後一天回 ``"H1"``。
    """
    halves = split_window(trading_days=list(eval_days), window_days=len(eval_days))
    h1_last = halves["formation_to"]

    def half_of(day: str) -> str:
        return "H1" if day <= h1_last else "H2"

    return halves, half_of


def check_as_of(*, as_of: str, max_price_date: str | None, historical: bool) -> None:
    """§3.1:as_of **就是** ``daily_prices`` 的最大日期。

    一次性的正式執行若打錯日期,樣本會被靜靜截短,而那一次執行就作廢了。
    ``historical=True`` 只給「在同一個 as_of 重現舊裁決」用,並寫進報告。
    """
    if max_price_date is None:
        raise ValueError("daily_prices is empty")
    if as_of > max_price_date:
        raise ValueError(f"as-of {as_of} is after the last daily_prices date {max_price_date}")
    if as_of != max_price_date and not historical:
        raise ValueError(
            f"as-of {as_of} is not the last daily_prices date {max_price_date} "
            "(docs/39 §3.1); pass --historical only to reproduce an earlier run"
        )


def _band(final: int) -> str:
    for low, high in FINAL_BANDS:
        if final >= low and (high is None or final <= high):
            return f"{low}-{high}" if high is not None else f">={low}"
    return "below"


def assemble(
    *,
    as_of: str,
    run_number: int,
    market_days: list[str],
    scores: list[dict[str, Any]],
    bars: dict[tuple[str, str], dict[str, Any]],
    coverage: dict[str, Any],
) -> dict[str, Any]:
    if not scores:
        raise ValueError("no daily_scores rows at or before as-of")
    eval_days = evaluation_days(market_days=market_days, first_score_day=scores[0]["date"])
    halves, half_of = half_assigner(eval_days)

    # §0 上榜,一天一次。
    by_day: dict[str, list[dict[str, Any]]] = {}
    for row in scores:
        by_day.setdefault(row["date"], []).append(row)
    on_list: dict[str, set[str]] = {}
    tie_at_cap = over_cap_days = 0
    for day, rows in by_day.items():
        result = published_list(row for row in rows if row["has_close"])
        on_list[day] = result["stock_ids"]
        tie_at_cap += result["tie_at_cap"]
        over_cap_days += result["over_cap"]

    # 每一列只判讀一次:兩臂與兩個池子讀同一份判讀。
    assessed: dict[tuple[str, str], dict[str, Any]] = {}
    for row in scores:
        stock_id, day = row["stock_id"], row["date"]
        entry_day = next_market_day(market_days, day)
        assessed[(stock_id, day)] = assess(
            score=row,
            entry_day=entry_day,
            entry_bar=None if entry_day is None else bars.get((stock_id, entry_day)),
            signal_bar=bars.get((stock_id, day)),
        )
    score_by_key = {(row["stock_id"], row["date"]): row for row in scores}

    # 上榜臂 L。
    event_refusals = dict.fromkeys(REFUSAL_CODES, 0)
    events: list[tuple[str, str]] = []
    for key in event_first_days(on_list=on_list, days=eval_days):
        outcome = assessed[key]
        if outcome["refusal"] is not None:
            event_refusals[outcome["refusal"]] += 1
            continue
        events.append(key)
    n = len(events)
    h_l = sum(1 for key in events if assessed[key]["hit"])
    h_l_by_half = {"H1": 0, "H2": 0}
    for key in events:
        if assessed[key]["hit"]:
            h_l_by_half[half_of(key[1])] += 1

    # 對照池:有評分列、不上榜、R1 與 R2 通過。
    pool_refusals = dict.fromkeys(REFUSAL_CODES, 0)
    pool_stock: dict[tuple[str, str], list[tuple[str, str]]] = {}
    pool_date: dict[str, list[tuple[str, str]]] = {}
    for row in scores:
        stock_id, day = row["stock_id"], row["date"]
        if stock_id in on_list.get(day, set()):
            continue
        outcome = assessed[(stock_id, day)]
        if outcome["refusal"] is not None:
            pool_refusals[outcome["refusal"]] += 1
            continue
        pool_stock.setdefault((stock_id, half_of(day)), []).append((stock_id, day))
        pool_date.setdefault(day, []).append((stock_id, day))

    counts_stock: dict[tuple[str, str], int] = {}
    counts_date: dict[str, int] = {}
    for stock_id, day in events:
        counts_stock[(stock_id, half_of(day))] = counts_stock.get((stock_id, half_of(day)), 0) + 1
        counts_date[day] = counts_date.get(day, 0) + 1

    seeds: list[dict[str, Any]] = []
    consistency: list[dict[str, Any]] = []
    placebo_hits: dict[str, list[int]] = {"stock": [], "date": []}
    short_report: dict[str, list[dict[str, Any]]] = {"stock": [], "date": []}
    for placebo, pools, counts in (
        ("stock", pool_stock, counts_stock),
        ("date", pool_date, counts_date),
    ):
        for seed in PLACEBO_SEEDS:
            draw = draw_matched(pools=pools, counts=counts, seed=seed)
            matched = not draw["short"]
            if draw["short"] and not short_report[placebo]:
                # 差額與 seed 無關(池子大小不隨 seed 變),記一次就夠。
                short_report[placebo] = [
                    {**entry, "key": list(entry["key"]) if isinstance(entry["key"], tuple)
                     else entry["key"]}
                    for entry in draw["short"]
                ]
            h_p = sum(1 for key in draw["drawn"] if assessed[key]["hit"])
            if matched:
                placebo_hits[placebo].append(h_p)
            entry = seed_result(seed=seed, n=n, h_f=h_l, h_p=h_p, matched=matched)
            entry = {"placebo": placebo, **entry}
            seeds.append(entry)
            h_p_by_half = {"H1": 0, "H2": 0}
            for key in draw["drawn"]:
                if assessed[key]["hit"]:
                    h_p_by_half[half_of(key[1])] += 1
            for half in ("H1", "H2"):
                consistency.append({
                    "placebo": placebo, "seed": seed, "half": half,
                    "h_l": h_l_by_half[half], "h_p": h_p_by_half[half],
                    "evaluable": matched,
                    "passed": matched and h_l_by_half[half] - h_p_by_half[half] > 0,
                })

    test_a = power_verdict(n=n, h_l=h_l)
    test_b = informativeness_verdict(seeds=seeds)
    test_c = consistency_verdict(entries=consistency)
    verdict = overall_verdict(test_a=test_a, test_b=test_b, test_c=test_c)

    event_days = sorted(day for _, day in events)
    facts = surge_facts(
        date_from=event_days[0] if event_days else None,
        date_to=event_days[-1] if event_days else None,
        events=n, hits=h_l,
        placebo_stock_hits=placebo_hits["stock"],
        placebo_date_hits=placebo_hits["date"],
    )

    # §3.6 伴隨計數:只報告,永遠不是判準。
    board_hits = board_not_entry = board_unknown = limit_open = 0
    by_month: dict[str, dict[str, int]] = {}
    by_band: dict[str, dict[str, int]] = {}
    for key in events:
        outcome = assessed[key]
        if outcome["board_hit"] is None:
            board_unknown += 1
        elif outcome["board_hit"]:
            board_hits += 1
            if not outcome["hit"]:
                board_not_entry += 1
        if outcome["limit_open"]:
            limit_open += 1
        month = key[1][:7]
        band = _band(score_by_key[key]["final"])
        for bucket, name in ((by_month, month), (by_band, band)):
            cell = bucket.setdefault(name, {"events": 0, "hits": 0})
            cell["events"] += 1
            cell["hits"] += int(outcome["hit"])
    all_days = [
        (stock_id, day) for day in eval_days for stock_id in sorted(on_list.get(day, set()))
        if assessed[(stock_id, day)]["refusal"] is None
    ]

    return {
        "metadata": {
            "report": REPORT_NAME,
            "as_of": as_of,
            "run_number": run_number,
            "preregistration_doc": PREREGISTRATION_DOC,
            "preregistration_commit": PREREGISTRATION_COMMIT,
            "read_only": True,
        },
        "coverage": {
            **coverage,
            "market_days_in_evaluation": len(eval_days),
            "evaluation_from": eval_days[0],
            "evaluation_to": eval_days[-1],
        },
        "halves": {
            "H1": [halves["formation_from"], halves["formation_to"]],
            "H2": [halves["evaluation_from"], halves["evaluation_to"]],
            "H1_market_days": halves["formation_market_days"],
            "H2_market_days": halves["evaluation_market_days"],
        },
        "sets": {
            "events": n,
            "hits": h_l,
            "hits_by_half": h_l_by_half,
            "events_by_half": {
                half: sum(1 for _, day in events if half_of(day) == half)
                for half in ("H1", "H2")
            },
            "tie_at_cap": tie_at_cap,
            "placebo_short": short_report,
        },
        "refusals": {"events": event_refusals, "pool": pool_refusals},
        "tests": {"A": test_a, "B": test_b, "C": test_c},
        "verdict": verdict,
        "facts_if_shipped": facts,
        "companion": {
            "board_hits": board_hits,
            "board_hit_not_entry_hit": board_not_entry,
            "board_unknown": board_unknown,
            "entry_open_at_limit_proxy": limit_open,
            "over_cap_days": over_cap_days,
            "tie_at_cap": tie_at_cap,
            "all_days_events": len(all_days),
            "all_days_hits": sum(1 for key in all_days if assessed[key]["hit"]),
            "by_month": dict(sorted(by_month.items())),
            "by_final_band": dict(sorted(by_band.items())),
        },
        "definitions": _definitions(),
    }


def _definitions() -> dict[str, str]:
    return {
        "hit": (
            f"100 x close(s, e) >= {100 + SURGE_THRESHOLD_PCT} x open(s, e) on raw prices "
            "of the entry day e, compared in decimal; buy at the next market day's open, "
            "mark at its close. The overnight gap is excluded because nobody can buy it"
        ),
        "e": (
            "the first date after t in the market calendar (every date with any "
            "daily_prices row); computed from the calendar, never read from the stored "
            "entry_date, which is only the R2 cross-check"
        ),
        "on_list": (
            f"verbatim json_export: close on t, stocks.type='stock', final >= "
            f"{LIST_MIN_FINAL}, sorted by (final, branch_score with None as -inf, "
            f"turnover) desc, first {LIST_CAP}; full ties at the cap are all included"
        ),
        "event": (
            "the first day of a run of consecutive market days on the list; a market "
            "day without the stock on the list breaks the run"
        ),
        "R2": (
            f"stored entry_date != e, or stored fwd_1d NULL or more than {FWD_TOLERANCE} "
            "away from 100 x (close/open - 1): refused and counted, never scored on the "
            "stored value; the remedy is a whole-table compute-performance --all and a "
            "new run number"
        ),
        "pools": (
            "P_stock: same stock, same half, rows not on the list passing R1 and R2; "
            "P_date: same date, other stocks, rows not on the list passing R1 and R2. "
            "Days whose next day is a list day are deliberately NOT removed (§3.3)"
        ),
        "entry_open_at_limit_proxy": (
            f"report only: open(s, e) x 1000 >= close(s, t) x {LIMIT_PROXY_PERMILLE} on "
            "raw prices as §2 R3 writes it; an ex-dividend e understates it"
        ),
        "board_hits": (
            "report only: close(e) x adj(e) >= 1.07 x close(t) x adj(t); this one DOES "
            "depend on adj_factor because it spans two rows"
        ),
    }


def write_next_day_surge_battery(
    *, as_of: str, run_number: int = 1, out: str | Path, historical: bool = False,
) -> dict[str, Any]:
    """Build and deterministically write the JSON battery result."""
    out_path = safe_report_output_path(out, report_name=REPORT_NAME)
    report = build_next_day_surge_battery(
        as_of=as_of, run_number=run_number, historical=historical,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report
