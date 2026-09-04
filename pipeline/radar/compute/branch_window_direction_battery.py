"""唯讀的「買低賣高窗口方向」樣本外 battery（可重現的撤回決策依據）。

為什麼這支必須存在
------------------
2026-09-03 那次驗證是用臨時 scratchpad 腳本跑的，**只有結果留在**
``docs/STATUS.md``，腳本沒有進版控。已經上線的「關鍵分點證據面板」靠那份結果
存活，而 2026-09-04 又替「往後看」窗口寫死了一組撤回條件——**一個能讓已上線
功能下架的決策，卻沒有任何人能重跑它**。這支 CLI 就是在補這個缺陷：把協定、
兩個對照組、以及四條撤回條件全部變成可重現的程式碼與可重算的數字。

它算什麼
--------
以 ``--as-of`` 為終點取 490 個市場交易日，**依交易日對半切**：較舊的 245 天是
形成半段、較新的 245 天是評估半段。**episode 在各半段獨立重建**——跨越邊界的
連續買（賣）日會在兩個半段各成為一個 episode，這正是真的用 245 天窗口去跑會
得到的東西。

兩個方向一律平起平坐：

``backward``
    事件日＋**前** 19 個市場日（已上線的定義，唯一的篩選條件與顯示數字）。
``forward``
    事件日＋**後** 19 個市場日（``_forward_price_observation``，尚未上線）。

兩個對照組（缺一不可）
----------------------
**張數配對安慰劑**：每個被標記的 pair，在同一檔股票上抽一個**未被標記**、且
形成半段兩側 episode 數各在 ±25% 內、**事件日 ``abs(pct)`` 中位數也在 ±25% 內**
的 pair。配對到「規模」是重點：每個被觀測到的事件依定義都是流量集中到擠進該
股前 15 大的日子，集中買盤會在其後數日推動價格，因此**往後看時該分點自己的
價格衝擊落在自己的窗內**。該股 pooled 基準吸收的是*平均*衝擊，吸收不了*這一個*
分點的衝擊，而後者與它的張數成正比。2026-09-03 那套安慰劑只配對 episode 數，
所以從未測到這件事。

**lag 測試**：把參考價從事件日收盤改成**次一市場交易日**的還原收盤，窗口定義
不變。買在消息前的分點，次日仍會落在低分位；靠自己的價格衝擊「做出來」的低
分位則不會。

不是損益
--------
全部是**進出場價格分位的計數**。買方與賣方各自獨立計數，沒有配對成一筆交易，
本模組不產生任何獲利、報酬或勝率。「exceeds」指的是**該 pair 的分位命中率高於
該股自身在同一半段、同一方向的 pooled 命中率**，與賺賠無關。

記憶體
------
與 :mod:`radar.compute.branch_stock_pctile_counts` 同一種形狀：交易列以
stock-major 順序 ``yield_per`` 串流，價格一次只載入一檔個股，**任何時候都不持有
episode 清單**（2026-08-25 在 VPS 上造成 1.7GB OOM 的 builder 正是那個形狀）。
每一對只留下八個計數器與一個中位數；每一檔股票算完就把該檔的結果併進全域的
少數幾個整數，然後丟掉。

寫入
----
沒有。``mode=ro`` 連線、不呼叫 ``init_db()``、不建表、不寫任何一列。
"""
from __future__ import annotations

import json
import math
import random
import time
from datetime import date as date_cls
from itertools import groupby
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from sqlalchemy import text

from .branch_point_in_time_persist import _price_rows_for_stock
from .branch_point_in_time_report import (
    HIGH_SELL_MIN_PCTILE,
    LOW_BUY_MAX_PCTILE,
    PRICE_WINDOW_DAYS,
    QUAL_PCT,
    _build_universe,
    _close_range_percentile,
    _episode_runs,
    _forward_price_observation,
    _price_observation,
)
from .read_only_sqlite import get_read_only_sqlite_engine, safe_report_output_path

REPORT_NAME = "branch-window-direction-battery"

REQUIRED_TABLES = (
    "branch_trades", "daily_prices", "stocks", "tracked_branches", "branch_rankings",
)

# 窗口與切分：490 個市場交易日，對半切成形成／評估兩段。
DEFAULT_WINDOW_DAYS = 490

# 形成半段的標記規則（協定同 2026-09-03，不得為了湊樣本而放寬）。
FLAG_MIN_KNOWN_PER_SIDE = 10
FLAG_MIN_RATE = 0.70

# 評估半段的可測門檻：兩側各至少這麼多次分位可知才算「存活」。
EVAL_MIN_KNOWN_PER_SIDE = 3

# 安慰劑配對帶寬：episode 數與事件日 abs(pct) 中位數各 ±25%。
PLACEBO_BAND = 0.25
DEFAULT_SEED = 20260904

# 撤回條件的門檻（2026-09-04 事先寫死，見 docs/STATUS.md）。
PLACEBO_SIGMA_MULTIPLE = 2.0
PLACEBO_MAX_OBS_EXP = 1.5
LAG_MIN_RETAINED_RATIO = 0.5
FORWARD_MIN_OBS_EXP = 2.0
BACKWARD_STRONG_OBS_EXP = 2.5
BACKWARD_PULL_OBS_EXP = 1.5

# 純提示，不是門檻、不改變任何判定：存活樣本少於此值時點估計不可讀到兩位數。
LOW_SAMPLE_SURVIVORS = 30

DIRECTIONS = ("backward", "forward")
SIDES = ("buy", "sell")
_COUNT_KEYS = tuple(
    (direction, lagged, side)
    for direction in DIRECTIONS
    for lagged in (False, True)
    for side in SIDES
)


def _validate_date(value: str, name: str) -> str:
    try:
        return date_cls.fromisoformat(value).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be YYYY-MM-DD: {value!r}") from exc


def _validate_window_days(window_days: int) -> int:
    if not isinstance(window_days, int) or isinstance(window_days, bool) or window_days < 2:
        raise ValueError("window-days must be an integer >= 2")
    return window_days


def split_window(*, trading_days: list[str], window_days: int) -> dict[str, Any]:
    """把最後 ``window_days`` 個市場交易日對半切成形成／評估兩段。

    切點一定落在**交易日**上：兩段都是 ``trading_days`` 的連續切片，日期本身就是
    真實的市場交易日，不是把日曆對半除出來的。交易日不足時窗口被截斷（記在
    ``window_truncated``），永遠不補、不內插。天數為奇數時多的那一天歸給評估
    半段——這只是一個必須明講的決定，不是統計選擇。
    """
    if len(trading_days) < 2:
        raise ValueError("battery needs at least two market trading days at or before as-of")
    window = trading_days[-window_days:]
    half = len(window) // 2
    formation, evaluation = window[:half], window[half:]
    return {
        "window_market_days": len(window),
        "window_market_days_requested": window_days,
        "window_truncated": len(window) < window_days,
        "window_from": window[0],
        "window_to": window[-1],
        "formation_from": formation[0],
        "formation_to": formation[-1],
        "formation_market_days": len(formation),
        "evaluation_from": evaluation[0],
        "evaluation_to": evaluation[-1],
        "evaluation_market_days": len(evaluation),
    }


def _window_days_for(*, direction: str, event_index: int, market_days: list[str]) -> list[str] | None:
    """``PRICE_WINDOW_DAYS`` 天的市場日切片；不足以構成完整窗口時回 ``None``。

    這是 :func:`_price_observation` 與 :func:`_forward_price_observation` 內部那段
    切片的同一份算術，抽出來只是為了讓 lag 變體能套用**完全相同的窗口**、只換
    參考價。未 lag 的路徑仍然直接呼叫那兩支既有函式，不走這裡，所以定義不會
    在兩處漂移。
    """
    if direction == "backward":
        start = event_index - (PRICE_WINDOW_DAYS - 1)
        return None if start < 0 else market_days[start:event_index + 1]
    end = event_index + (PRICE_WINDOW_DAYS - 1)
    return None if end >= len(market_days) else market_days[event_index:end + 1]


def percentile_observation(
    *,
    direction: str,
    lagged: bool,
    event_date: str,
    market_index: dict[str, int],
    market_days: list[str],
    row_by_date: dict[str, dict[str, Any]],
) -> tuple[float | None, str]:
    """回傳 ``(percentile, status)``，status 為 ``known`` / ``immature`` / ``unknown``。

    ``immature`` 與 ``unknown`` **不可互換**，且兩者都**永遠不進任何分母**：前者
    是「答案還不存在」（窗口或次日尚未發生），後者是「資料讀不到」。
    """
    if not lagged:
        if direction == "backward":
            observation = _price_observation(
                event_date=event_date, market_index=market_index,
                market_days=market_days, row_by_date=row_by_date,
            )
            return observation["price_percentile_20d"], observation["price_percentile_status"]
        observation = _forward_price_observation(
            event_date=event_date, market_index=market_index,
            market_days=market_days, row_by_date=row_by_date,
        )
        return (
            observation["price_percentile_forward_20d"],
            observation["price_percentile_forward_status"],
        )

    event_index = market_index.get(event_date)
    if event_index is None:
        return None, "unknown"
    window_days = _window_days_for(
        direction=direction, event_index=event_index, market_days=market_days,
    )
    if window_days is None:
        # 往前看缺的是歷史（讀不到），往後看缺的是未來（還沒發生）。
        return None, "unknown" if direction == "backward" else "immature"
    reference_index = event_index + 1
    if reference_index >= len(market_days):
        # 次一市場交易日尚未發生：這是日曆事實，不是缺資料。
        return None, "immature"
    reference_close = row_by_date.get(market_days[reference_index], {}).get("close")
    if reference_close is None:
        return None, "unknown"
    percentile, reason = _close_range_percentile(
        close=reference_close, window_days=window_days, row_by_date=row_by_date,
    )
    return (None, "unknown") if reason is not None else (percentile, "known")


def is_hit(*, side: str, percentile: float) -> bool:
    """低買／高賣的判定，門檻直接沿用已上線的常數，不在此重述。"""
    if side == "buy":
        return percentile <= LOW_BUY_MAX_PCTILE
    return percentile >= HIGH_SELL_MIN_PCTILE


class _HalfCounts:
    """一對（分點, 個股）在一個半段的累加器。只有整數，永不持有 episode。"""

    __slots__ = ("buy_episodes", "sell_episodes", "known", "hits", "median_abs_pct")

    def __init__(self) -> None:
        self.buy_episodes = 0
        self.sell_episodes = 0
        self.known = dict.fromkeys(_COUNT_KEYS, 0)
        self.hits = dict.fromkeys(_COUNT_KEYS, 0)
        self.median_abs_pct: float | None = None

    def add_episode(self, side: str) -> None:
        if side == "buy":
            self.buy_episodes += 1
        else:
            self.sell_episodes += 1

    def add_observation(self, *, direction: str, lagged: bool, side: str,
                        percentile: float | None, status: str) -> None:
        if status != "known":
            return  # immature 與 unknown 都不進分母。
        key = (direction, lagged, side)
        self.known[key] += 1
        if is_hit(side=side, percentile=percentile):
            self.hits[key] += 1

    @property
    def episodes(self) -> int:
        return self.buy_episodes + self.sell_episodes


class _PairAccum:
    __slots__ = ("formation", "evaluation")

    def __init__(self) -> None:
        self.formation = _HalfCounts()
        self.evaluation = _HalfCounts()


def is_flagged(half: _HalfCounts, direction: str) -> bool:
    """兩側各 ≥10 次分位可知，且兩側命中率各 ≥0.7。門檻不因樣本少而放寬。"""
    for side in SIDES:
        known = half.known[(direction, False, side)]
        if known < FLAG_MIN_KNOWN_PER_SIDE:
            return False
        if half.hits[(direction, False, side)] / known < FLAG_MIN_RATE:
            return False
    return True


def _exceeds(hits: int, known: int, stock_rate: float) -> bool:
    """該 pair 的命中率是否高於該股自身的 pooled 率。與期望值用同一個判定式。"""
    return hits > known * stock_rate


def probability_exceeds(known: int, stock_rate: float) -> float:
    """在 ``Binom(known, stock_rate)`` 下，命中數高於該股自身率的機率。

    判定式與 :func:`_exceeds` 逐字相同，所以 obs 與 exp 永遠問同一個問題。
    """
    total = 0.0
    for hits in range(known + 1):
        if _exceeds(hits, known, stock_rate):
            total += (
                math.comb(known, hits)
                * (stock_rate ** hits)
                * ((1.0 - stock_rate) ** (known - hits))
            )
    return total


class _ArmAggregate:
    """一個「臂」（flagged／placebo × 未 lag／lag）的全域累加結果。"""

    __slots__ = (
        "pairs", "with_evaluation_activity", "survivors", "without_stock_baseline",
        "exceeds_buy", "exceeds_sell", "exceeds_both", "expected_exceeds_both",
        "episodes", "known", "hits",
        "buy_margins_pp", "sell_margins_pp",
    )

    def __init__(self) -> None:
        self.pairs = 0
        self.with_evaluation_activity = 0
        self.survivors = 0
        self.without_stock_baseline = 0
        self.exceeds_buy = 0
        self.exceeds_sell = 0
        self.exceeds_both = 0
        self.expected_exceeds_both = 0.0
        # 被比較的 pair 在評估半段的原始計數。episodes 與 known 的落差就是
        # immature 與 unknown 的量——往後看在 as_of 附近的衰減看的就是這個差。
        self.episodes = dict.fromkeys(SIDES, 0)
        self.known = dict.fromkeys(SIDES, 0)
        self.hits = dict.fromkeys(SIDES, 0)
        # 只存每個存活 pair 的一個 float，不是 episode；長度為存活數量。
        self.buy_margins_pp: list[float] = []
        self.sell_margins_pp: list[float] = []

    def add_pair(self, accum: _PairAccum, *, direction: str, lagged: bool,
                 stock_rates: dict[tuple[bool, str], float | None]) -> None:
        evaluation = accum.evaluation
        self.pairs += 1
        if evaluation.episodes > 0:
            self.with_evaluation_activity += 1
        known = {side: evaluation.known[(direction, lagged, side)] for side in SIDES}
        if any(known[side] < EVAL_MIN_KNOWN_PER_SIDE for side in SIDES):
            # 沒有評估半段活動的被標記 pair 也留在 pairs 分母裡：一條 pair 會消失
            # 的規則不能靠悄悄丟掉它們來看起來有效。
            return
        self.survivors += 1
        rates = {side: stock_rates[(lagged, side)] for side in SIDES}
        if any(rates[side] is None for side in SIDES):
            self.without_stock_baseline += 1
            return
        hits = {side: evaluation.hits[(direction, lagged, side)] for side in SIDES}
        for side in SIDES:
            self.known[side] += known[side]
            self.hits[side] += hits[side]
        self.episodes["buy"] += evaluation.buy_episodes
        self.episodes["sell"] += evaluation.sell_episodes
        exceeds = {
            side: _exceeds(hits[side], known[side], rates[side]) for side in SIDES
        }
        self.exceeds_buy += exceeds["buy"]
        self.exceeds_sell += exceeds["sell"]
        self.exceeds_both += exceeds["buy"] and exceeds["sell"]
        self.buy_margins_pp.append(100.0 * (hits["buy"] / known["buy"] - rates["buy"]))
        self.sell_margins_pp.append(100.0 * (hits["sell"] / known["sell"] - rates["sell"]))
        self.expected_exceeds_both += (
            probability_exceeds(known["buy"], rates["buy"])
            * probability_exceeds(known["sell"], rates["sell"])
        )

    def as_json(self) -> dict[str, Any]:
        survivors = self.survivors - self.without_stock_baseline
        expected = self.expected_exceeds_both
        return {
            "pairs": self.pairs,
            "with_evaluation_activity": self.with_evaluation_activity,
            "survivors": self.survivors,
            "without_stock_baseline": self.without_stock_baseline,
            "compared_pairs": survivors,
            "evaluation_buy_episodes": self.episodes["buy"],
            "evaluation_buy_known": self.known["buy"],
            "evaluation_buy_hits": self.hits["buy"],
            "evaluation_sell_episodes": self.episodes["sell"],
            "evaluation_sell_known": self.known["sell"],
            "evaluation_sell_hits": self.hits["sell"],
            "exceeds_own_stock_buy": self.exceeds_buy,
            "exceeds_own_stock_sell": self.exceeds_sell,
            "exceeds_own_stock_both": self.exceeds_both,
            "exceeds_own_stock_both_rate": (
                round(self.exceeds_both / survivors, 6) if survivors else None
            ),
            "median_margin_pp_buy": (
                round(median(self.buy_margins_pp), 6) if self.buy_margins_pp else None
            ),
            "median_margin_pp_sell": (
                round(median(self.sell_margins_pp), 6) if self.sell_margins_pp else None
            ),
            "expected_exceeds_own_stock_both": round(expected, 6),
            "obs_exp": round(self.exceeds_both / expected, 6) if expected > 0 else None,
            "low_sample": survivors < LOW_SAMPLE_SURVIVORS,
        }


class _DirectionAggregate:
    __slots__ = (
        "flagged_pairs", "flagged_stocks", "re_flagged_pairs",
        "placebo_matched", "placebo_unmatched", "arms",
    )

    def __init__(self) -> None:
        self.flagged_pairs = 0
        self.flagged_stocks = 0
        self.re_flagged_pairs = 0
        self.placebo_matched = 0
        self.placebo_unmatched = 0
        self.arms = {
            (arm, lagged): _ArmAggregate()
            for arm in ("flagged", "placebo")
            for lagged in (False, True)
        }


def _within_band(value: float, reference: float) -> bool:
    return (1.0 - PLACEBO_BAND) * reference <= value <= (1.0 + PLACEBO_BAND) * reference


def match_placebo(
    *,
    flagged: list[str],
    flagged_set: set[str],
    accums: dict[str, _PairAccum],
    rng: random.Random,
) -> dict[str, str]:
    """為每個被標記的 pair 在同一檔股票上抽一個張數配對的未標記 pair。

    候選必須**同時**滿足兩個帶寬：形成半段的買側與賣側 episode 數各在 ±25% 內，
    **且**形成半段事件日 ``abs(pct)`` 中位數在 ±25% 內。只配 episode 數（2026-09-03
    那套的做法）測不到「該分點自己的價格衝擊」這個混淆，因為衝擊與張數成正比。

    被標記的 pair 自己永遠不會被抽到（候選一律排除整個 flagged 集合），同一個
    安慰劑也不會被重複用在同一檔股票的兩個被標記 pair 上。
    """
    used: set[str] = set()
    matched: dict[str, str] = {}
    pool = sorted(name for name in accums if name not in flagged_set)
    for name in flagged:
        reference = accums[name].formation
        if reference.median_abs_pct is None:
            continue
        candidates = [
            candidate for candidate in pool
            if candidate not in used
            and _within_band(accums[candidate].formation.buy_episodes, reference.buy_episodes)
            and _within_band(accums[candidate].formation.sell_episodes, reference.sell_episodes)
            and accums[candidate].formation.median_abs_pct is not None
            and _within_band(accums[candidate].formation.median_abs_pct, reference.median_abs_pct)
        ]
        if not candidates:
            continue
        drawn = candidates[rng.randrange(len(candidates))]
        used.add(drawn)
        matched[name] = drawn
    return matched


def _verdict(
    *, criterion: str, applies_to: str, threshold: str,
    triggered: bool | None, observed: dict[str, Any], statement: str,
) -> dict[str, Any]:
    if triggered is None:
        outcome = "NOT EVALUABLE"
    elif triggered:
        outcome = f"WITHDRAW {applies_to}"
    else:
        outcome = f"KEEP {applies_to}"
    return {
        "criterion": criterion,
        "applies_to": applies_to,
        "threshold": threshold,
        "evaluable": triggered is not None,
        "triggered": triggered,
        "outcome": outcome,
        "observed": observed,
        "line": f"[{outcome}] {criterion}: {statement}",
    }


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def build_verdicts(directions: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """把四條事先寫死的撤回條件逐條算出 verdict 行，不留給讀者自己比數字。"""
    forward_flagged = directions["forward"]["evaluation"]["unlagged"]
    forward_lag = directions["forward"]["evaluation"]["lag"]
    forward_placebo = directions["forward"]["placebo"]["unlagged"]
    backward_flagged = directions["backward"]["evaluation"]["unlagged"]
    backward_placebo = directions["backward"]["placebo"]["unlagged"]
    verdicts: list[dict[str, Any]] = []

    # ① 往後看 vs 張數配對安慰劑。
    n1, n2 = forward_flagged["compared_pairs"], forward_placebo["compared_pairs"]
    placebo_obs_exp = forward_placebo["obs_exp"]
    if not n1 or not n2:
        verdicts.append(_verdict(
            criterion="forward_vs_flow_matched_placebo",
            applies_to="forward",
            threshold=(
                f"withdraw if |rate difference| <= {PLACEBO_SIGMA_MULTIPLE} sigma "
                f"or placebo obs/exp > {PLACEBO_MAX_OBS_EXP}"
            ),
            triggered=None,
            observed={
                "flagged_compared_pairs": n1, "placebo_compared_pairs": n2,
                "placebo_obs_exp": placebo_obs_exp,
            },
            statement=(
                "cannot be evaluated: "
                f"flagged compared pairs={n1}, flow-matched placebo compared pairs={n2}"
            ),
        ))
    else:
        p1 = forward_flagged["exceeds_own_stock_both"] / n1
        p2 = forward_placebo["exceeds_own_stock_both"] / n2
        sigma = math.sqrt(p1 * (1.0 - p1) / n1 + p2 * (1.0 - p2) / n2)
        within_sigma = abs(p1 - p2) <= PLACEBO_SIGMA_MULTIPLE * sigma
        placebo_high = placebo_obs_exp is not None and placebo_obs_exp > PLACEBO_MAX_OBS_EXP
        verdicts.append(_verdict(
            criterion="forward_vs_flow_matched_placebo",
            applies_to="forward",
            threshold=(
                f"withdraw if |rate difference| <= {PLACEBO_SIGMA_MULTIPLE} sigma "
                f"or placebo obs/exp > {PLACEBO_MAX_OBS_EXP}"
            ),
            triggered=within_sigma or placebo_high,
            observed={
                "flagged_exceeds_both_rate": round(p1, 6),
                "flagged_compared_pairs": n1,
                "placebo_exceeds_both_rate": round(p2, 6),
                "placebo_compared_pairs": n2,
                "difference": round(p1 - p2, 6),
                "sigma": round(sigma, 6),
                "sigma_multiple_threshold": PLACEBO_SIGMA_MULTIPLE,
                "within_sigma_band": within_sigma,
                "placebo_obs_exp": placebo_obs_exp,
                "placebo_obs_exp_threshold": PLACEBO_MAX_OBS_EXP,
                "placebo_obs_exp_exceeded": placebo_high,
            },
            statement=(
                f"exceeds-both {p1:.4f} (n={n1}) vs flow-matched placebo {p2:.4f} (n={n2}); "
                f"difference {p1 - p2:.4f}, {PLACEBO_SIGMA_MULTIPLE} sigma = "
                f"{PLACEBO_SIGMA_MULTIPLE * sigma:.4f}; placebo obs/exp = {placebo_obs_exp}"
            ),
        ))

    # ② lag 測試：往後看的 obs/exp 掉超過一半。
    unlagged_obs_exp, lagged_obs_exp = forward_flagged["obs_exp"], forward_lag["obs_exp"]
    if unlagged_obs_exp is None or lagged_obs_exp is None:
        verdicts.append(_verdict(
            criterion="forward_lag_test",
            applies_to="forward",
            threshold=f"withdraw if lagged obs/exp < {LAG_MIN_RETAINED_RATIO} x unlagged obs/exp",
            triggered=None,
            observed={"unlagged_obs_exp": unlagged_obs_exp, "lagged_obs_exp": lagged_obs_exp},
            statement=(
                f"cannot be evaluated: unlagged obs/exp={unlagged_obs_exp}, "
                f"lagged obs/exp={lagged_obs_exp}"
            ),
        ))
    else:
        verdicts.append(_verdict(
            criterion="forward_lag_test",
            applies_to="forward",
            threshold=f"withdraw if lagged obs/exp < {LAG_MIN_RETAINED_RATIO} x unlagged obs/exp",
            triggered=lagged_obs_exp < LAG_MIN_RETAINED_RATIO * unlagged_obs_exp,
            observed={
                "unlagged_obs_exp": unlagged_obs_exp,
                "lagged_obs_exp": lagged_obs_exp,
                "retained_ratio": round(lagged_obs_exp / unlagged_obs_exp, 6)
                if unlagged_obs_exp else None,
                "retained_ratio_threshold": LAG_MIN_RETAINED_RATIO,
            },
            statement=(
                f"obs/exp {unlagged_obs_exp} unlagged -> {lagged_obs_exp} under next-market-day "
                f"reference price (threshold {LAG_MIN_RETAINED_RATIO} x = "
                f"{LAG_MIN_RETAINED_RATIO * unlagged_obs_exp:.6f})"
            ),
        ))

    # ③ 往後看弱、往前看強。
    backward_obs_exp = backward_flagged["obs_exp"]
    if unlagged_obs_exp is None or backward_obs_exp is None:
        verdicts.append(_verdict(
            criterion="forward_weak_while_backward_strong",
            applies_to="forward",
            threshold=(
                f"withdraw if forward obs/exp < {FORWARD_MIN_OBS_EXP} "
                f"and backward obs/exp >= {BACKWARD_STRONG_OBS_EXP}"
            ),
            triggered=None,
            observed={"forward_obs_exp": unlagged_obs_exp, "backward_obs_exp": backward_obs_exp},
            statement=(
                f"cannot be evaluated: forward obs/exp={unlagged_obs_exp}, "
                f"backward obs/exp={backward_obs_exp}"
            ),
        ))
    else:
        verdicts.append(_verdict(
            criterion="forward_weak_while_backward_strong",
            applies_to="forward",
            threshold=(
                f"withdraw if forward obs/exp < {FORWARD_MIN_OBS_EXP} "
                f"and backward obs/exp >= {BACKWARD_STRONG_OBS_EXP}"
            ),
            triggered=(
                unlagged_obs_exp < FORWARD_MIN_OBS_EXP
                and backward_obs_exp >= BACKWARD_STRONG_OBS_EXP
            ),
            observed={
                "forward_obs_exp": unlagged_obs_exp,
                "forward_obs_exp_threshold": FORWARD_MIN_OBS_EXP,
                "backward_obs_exp": backward_obs_exp,
                "backward_obs_exp_threshold": BACKWARD_STRONG_OBS_EXP,
            },
            statement=(
                f"forward obs/exp = {unlagged_obs_exp} (< {FORWARD_MIN_OBS_EXP}?) while "
                f"backward obs/exp = {backward_obs_exp} (>= {BACKWARD_STRONG_OBS_EXP}?) "
                "on the same data"
            ),
        ))

    # ④ 往前看塌向安慰劑 —— 這一條決定已上線的面板要不要下架。
    if backward_obs_exp is None:
        verdicts.append(_verdict(
            criterion="backward_collapse_toward_placebo",
            applies_to="backward",
            threshold=f"pull the shipped panel if backward obs/exp < {BACKWARD_PULL_OBS_EXP}",
            triggered=None,
            observed={
                "backward_obs_exp": None,
                "backward_placebo_obs_exp": backward_placebo["obs_exp"],
            },
            statement="cannot be evaluated: backward obs/exp is undefined on this data",
        ))
    else:
        verdicts.append(_verdict(
            criterion="backward_collapse_toward_placebo",
            applies_to="backward",
            threshold=f"pull the shipped panel if backward obs/exp < {BACKWARD_PULL_OBS_EXP}",
            triggered=backward_obs_exp < BACKWARD_PULL_OBS_EXP,
            observed={
                "backward_obs_exp": backward_obs_exp,
                "backward_obs_exp_threshold": BACKWARD_PULL_OBS_EXP,
                "backward_placebo_obs_exp": backward_placebo["obs_exp"],
            },
            statement=(
                f"backward obs/exp = {backward_obs_exp} on adjusted prices "
                f"(pull threshold {BACKWARD_PULL_OBS_EXP}); its flow-matched placebo = "
                f"{backward_placebo['obs_exp']}"
            ),
        ))
    return verdicts


def _pair_half_dates(dates: Iterable[str], date_from: str, date_to: str) -> list[str]:
    return [day for day in dates if date_from <= day <= date_to]


def build_pair_counts(
    *,
    dates_by_side: dict[str, list[str]],
    abs_pct_by_date: dict[str, float],
    halves: tuple[tuple[str, str, str], ...],
    market_index: dict[str, int],
    market_days: list[str],
    row_by_date: dict[str, dict[str, Any]],
) -> _PairAccum:
    """一對（分點, 個股）的兩個半段計數。**任何時候都不持有 episode 清單。**

    每個半段只拿到自己那段的日期，所以 episode 是**在各半段內獨立重建**的：跨越
    邊界的一段連續買（賣）日，會在形成半段與評估半段**各成為一個 episode**——
    真的用一個 245 天窗口去跑就會得到這個結果。
    """
    accum = _PairAccum()
    for half_name, half_from, half_to in halves:
        half: _HalfCounts = getattr(accum, half_name)
        event_abs_pct: list[float] = []
        for side in SIDES:
            half_dates = _pair_half_dates(dates_by_side[side], half_from, half_to)
            for start_date, _end, _days in _episode_runs(half_dates, market_index):
                half.add_episode(side)
                event_abs_pct.append(abs_pct_by_date[start_date])
                for direction in DIRECTIONS:
                    for lagged in (False, True):
                        percentile, status = percentile_observation(
                            direction=direction, lagged=lagged, event_date=start_date,
                            market_index=market_index, market_days=market_days,
                            row_by_date=row_by_date,
                        )
                        half.add_observation(
                            direction=direction, lagged=lagged, side=side,
                            percentile=percentile, status=status,
                        )
        # 事件日 abs(pct) 的中位數是安慰劑配對的第二個帶寬。只留下這一個 float,
        # 原始清單當場丟棄。
        half.median_abs_pct = median(event_abs_pct) if event_abs_pct else None
    return accum


def build_branch_window_direction_battery(
    *, as_of: str, window_days: int = DEFAULT_WINDOW_DAYS, seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """跑完整個 battery 並回傳可序列化的結果。全程唯讀。"""
    as_of = _validate_date(as_of, "as-of")
    window_days = _validate_window_days(window_days)
    started = time.monotonic()
    rng = random.Random(seed)

    aggregates = {direction: _DirectionAggregate() for direction in DIRECTIONS}
    stocks_streamed = 0
    pairs_streamed = 0
    trade_rows_streamed = 0

    engine = get_read_only_sqlite_engine(
        report_name=REPORT_NAME, required_tables=REQUIRED_TABLES,
    )
    try:
        with engine.connect() as conn, engine.connect() as price_conn:
            trading_days = [row[0] for row in conn.execute(text("""
                SELECT DISTINCT date FROM daily_prices WHERE date <= :as_of ORDER BY date
            """), {"as_of": as_of}).fetchall()]
            split = split_window(trading_days=trading_days, window_days=window_days)
            market_index = {day: index for index, day in enumerate(trading_days)}
            halves = (
                ("formation", split["formation_from"], split["formation_to"]),
                ("evaluation", split["evaluation_from"], split["evaluation_to"]),
            )
            # 往前看的分位只會回看事件日前 19 個交易日,更早的價格永遠讀不到。
            price_from = trading_days[
                max(0, market_index[split["window_from"]] - (PRICE_WINDOW_DAYS - 1))
            ]
            universe, _unknown_manual_timestamp_names = _build_universe(conn, as_of)

            trade_rows = conn.execution_options(yield_per=2000).execute(text("""
                SELECT b.stock_id, b.branch_name, b.date, b.net_lots, b.pct
                FROM branch_trades b
                JOIN stocks s ON s.id = b.stock_id
                WHERE s.type = 'stock'
                  AND b.date >= :date_from
                  AND b.date <= :date_to
                ORDER BY b.stock_id, b.branch_name, b.date
            """), {"date_from": split["window_from"], "date_to": split["window_to"]}).mappings()

            for stock_id, stock_group in groupby(trade_rows, key=lambda row: row["stock_id"]):
                row_by_date: dict[str, dict[str, Any]] | None = None
                accums: dict[str, _PairAccum] = {}
                for branch_name, pair_group in groupby(
                    stock_group, key=lambda row: row["branch_name"],
                ):
                    dates_by_side: dict[str, list[str]] = {"buy": [], "sell": []}
                    abs_pct_by_date: dict[str, float] = {}
                    for row in pair_group:
                        trade_rows_streamed += 1
                        if branch_name not in universe:
                            continue
                        net_lots, pct = row["net_lots"], row["pct"]
                        if net_lots is None or pct is None:
                            continue
                        if net_lots > 0 and pct >= QUAL_PCT:
                            dates_by_side["buy"].append(row["date"])
                        elif net_lots < 0 and abs(pct) >= QUAL_PCT:
                            dates_by_side["sell"].append(row["date"])
                        else:
                            continue
                        abs_pct_by_date[row["date"]] = abs(pct)
                    if not dates_by_side["buy"] and not dates_by_side["sell"]:
                        continue
                    if row_by_date is None:
                        row_by_date = _price_rows_for_stock(
                            price_conn, stock_id=stock_id, date_from=price_from, date_to=as_of,
                        )
                    accums[branch_name] = build_pair_counts(
                        dates_by_side=dates_by_side,
                        abs_pct_by_date=abs_pct_by_date,
                        halves=halves,
                        market_index=market_index,
                        market_days=trading_days,
                        row_by_date=row_by_date,
                    )
                    pairs_streamed += 1

                if not accums:
                    continue
                stocks_streamed += 1
                _accumulate_stock(accums, aggregates=aggregates, rng=rng)
    finally:
        engine.dispose()

    directions_json = {
        direction: _direction_json(aggregates[direction]) for direction in DIRECTIONS
    }
    return {
        "metadata": {
            "report": REPORT_NAME,
            "as_of": as_of,
            "seed": seed,
            "read_only": True,
            "schema_changes": False,
            "database_writes": False,
            "ranking_or_score_changes": False,
            "elapsed_sec": round(time.monotonic() - started, 3),
        },
        "definitions": _definitions(),
        "split": split,
        "coverage": {
            "universe_branch_count": len(universe),
            "market_trading_days_through_as_of": len(trading_days),
            "stocks_streamed": stocks_streamed,
            "pairs_streamed": pairs_streamed,
            "trade_rows_streamed": trade_rows_streamed,
            "branch_trade_capture_note": (
                "branch_trades is a retrieved top-15 buy/sell slice; every observed event "
                "is by construction a day of concentrated flow, which is exactly why the "
                "placebo is matched on size as well as on episode count."
            ),
            "forward_maturity_note": (
                f"the forward window needs {PRICE_WINDOW_DAYS - 1} market days after the "
                "event, so events in the final stretch of the evaluation half are immature "
                "at as_of. Immature events are excluded from every denominator and are "
                "never counted as misses; the forward direction is therefore measured on "
                "fewer evaluation events than the backward direction, by construction."
            ),
        },
        "directions": directions_json,
        "verdicts": build_verdicts(directions_json),
        "notes": [
            "Re-flag rate is reported for information only and is NOT a withdrawal "
            "criterion: the counts-not-badges design already absorbed the 2026-09-03 "
            "finding that labels do not persist across years. Do not re-litigate it.",
            "Survivorship is stated before any performance number on purpose: a rule "
            "whose flagged pairs vanish is unusable however good the survivors look.",
            "Every number here is a price-percentile count. There is no profit, no "
            "return and no win rate; buy and sell episodes are counted independently "
            "and are never paired into a trade.",
        ],
    }


def _accumulate_stock(
    accums: dict[str, _PairAccum], *,
    aggregates: dict[str, _DirectionAggregate],
    rng: random.Random,
) -> None:
    """把一檔股票的結果併進全域計數，然後這一檔的所有 accum 就可以丟掉。"""
    for direction in DIRECTIONS:
        aggregate = aggregates[direction]
        # 該股自身在評估半段、同一方向的 pooled 率——唯一有意義的比較基準。
        stock_rates: dict[tuple[bool, str], float | None] = {}
        for lagged in (False, True):
            for side in SIDES:
                key = (direction, lagged, side)
                known = sum(a.evaluation.known[key] for a in accums.values())
                hits = sum(a.evaluation.hits[key] for a in accums.values())
                stock_rates[(lagged, side)] = hits / known if known else None

        flagged = [
            name for name in sorted(accums)
            if is_flagged(accums[name].formation, direction)
        ]
        if not flagged:
            continue
        flagged_set = set(flagged)
        aggregate.flagged_pairs += len(flagged)
        aggregate.flagged_stocks += 1
        aggregate.re_flagged_pairs += sum(
            is_flagged(accums[name].evaluation, direction) for name in flagged
        )

        matched = match_placebo(
            flagged=flagged, flagged_set=flagged_set, accums=accums, rng=rng,
        )
        aggregate.placebo_matched += len(matched)
        aggregate.placebo_unmatched += len(flagged) - len(matched)

        for lagged in (False, True):
            for name in flagged:
                aggregate.arms[("flagged", lagged)].add_pair(
                    accums[name], direction=direction, lagged=lagged, stock_rates=stock_rates,
                )
            for name in matched.values():
                aggregate.arms[("placebo", lagged)].add_pair(
                    accums[name], direction=direction, lagged=lagged, stock_rates=stock_rates,
                )


def _direction_json(aggregate: _DirectionAggregate) -> dict[str, Any]:
    flagged_unlagged = aggregate.arms[("flagged", False)]
    return {
        "formation": {
            "flagged_pairs": aggregate.flagged_pairs,
            "flagged_stocks": aggregate.flagged_stocks,
            "min_known_per_side": FLAG_MIN_KNOWN_PER_SIDE,
            "min_rate_per_side": FLAG_MIN_RATE,
            "measurable": aggregate.flagged_pairs > 0,
            "note": (
                "no flagged pairs at this bar" if aggregate.flagged_pairs == 0
                else "flagging bar is fixed by protocol and is never loosened to obtain samples"
            ),
        },
        "survivorship": {
            "flagged_pairs": flagged_unlagged.pairs,
            "with_evaluation_activity": flagged_unlagged.with_evaluation_activity,
            "without_evaluation_activity": (
                flagged_unlagged.pairs - flagged_unlagged.with_evaluation_activity
            ),
            "survivors_min_known_per_side": EVAL_MIN_KNOWN_PER_SIDE,
            "survivors": flagged_unlagged.survivors,
            "activity_rate": _rate(
                flagged_unlagged.with_evaluation_activity, flagged_unlagged.pairs,
            ),
            "survivor_rate": _rate(flagged_unlagged.survivors, flagged_unlagged.pairs),
        },
        "evaluation": {
            "unlagged": aggregate.arms[("flagged", False)].as_json(),
            "lag": aggregate.arms[("flagged", True)].as_json(),
        },
        "placebo": {
            "matched_pairs": aggregate.placebo_matched,
            "unmatched_flagged_pairs": aggregate.placebo_unmatched,
            "band": PLACEBO_BAND,
            "matched_on": ["formation buy episodes", "formation sell episodes",
                           "formation median event-day abs(pct)"],
            "unlagged": aggregate.arms[("placebo", False)].as_json(),
            "lag": aggregate.arms[("placebo", True)].as_json(),
        },
        "re_flag": {
            "formation_flagged_pairs": aggregate.flagged_pairs,
            "re_flagged_on_evaluation_half": aggregate.re_flagged_pairs,
            "rate": _rate(aggregate.re_flagged_pairs, aggregate.flagged_pairs),
            "is_withdrawal_criterion": False,
            "note": (
                "reported only; NOT a withdrawal criterion (counts-not-badges already "
                "absorbed this finding)"
            ),
        },
    }


def _definitions() -> dict[str, str]:
    return {
        "split": (
            "the last N market trading days at or before as_of, halved by trading day: "
            "the older half is formation, the newer half is evaluation; an odd count "
            "gives the extra day to the evaluation half"
        ),
        "episode": (
            "buy: net_lots > 0 and pct >= 1%; sell: net_lots < 0 and abs(pct) >= 1%; "
            "adjacent market trading days of the same branch-stock-direction are one "
            "episode, rebuilt independently inside each half, so a run straddling the "
            "boundary becomes one episode in each half"
        ),
        "backward": (
            "event close's position in the min/max close range of the event day and the "
            "preceding 19 market days (the shipped definition of record)"
        ),
        "forward": (
            "event close's position in the min/max close range of the event day and the "
            "following 19 market days; an incomplete forward window is immature, never "
            "unknown, and never enters a denominator"
        ),
        "lag": (
            "identical windows, but the reference price is the next market day's adjusted "
            "close instead of the event day's; a branch buying ahead of news is still at a "
            "low percentile the next day, a hit created by its own price impact is not. "
            "Flagging always uses the unlagged formation half (that is the shipped rule); "
            "only the evaluation half is recomputed, and its survivor test uses the lagged "
            "known counts, so the lag arm reports its own survivor count"
        ),
        "hit": (
            f"buy episode with known percentile <= {LOW_BUY_MAX_PCTILE}; sell episode with "
            f"known percentile >= {HIGH_SELL_MIN_PCTILE}"
        ),
        "flagged": (
            f"formation half, per direction: >= {FLAG_MIN_KNOWN_PER_SIDE} known episodes on "
            f"each side and both hit rates >= {FLAG_MIN_RATE}"
        ),
        "survivor": (
            f"a flagged pair with >= {EVAL_MIN_KNOWN_PER_SIDE} known episodes per side in "
            "the evaluation half; flagged pairs with no evaluation activity stay in the "
            "denominator and are counted as non-surviving"
        ),
        "exceeds_own_stock": (
            "the pair's evaluation-half hits/known is strictly greater than that stock's "
            "own pooled hits/known in the evaluation half, same direction, same lag "
            "setting; this is a price-percentile comparison and is not profit or a win rate"
        ),
        "obs_exp": (
            "observed exceeds-both count divided by the sum over compared pairs of "
            "P(exceeds buy) * P(exceeds sell) under a per-pair binomial null whose p is "
            "that stock's own evaluation-half rate"
        ),
        "placebo": (
            "for each flagged pair, one unflagged pair on the same stock whose formation "
            f"episode count per side is within +/-{PLACEBO_BAND:.0%} and whose formation "
            f"median event-day abs(pct) is within +/-{PLACEBO_BAND:.0%}; the flagged pair "
            "itself is never drawn and a placebo is used at most once per stock"
        ),
        "median_margin_pp": (
            "median over compared pairs of (pair rate - own-stock rate) in percentage points"
        ),
    }


def write_branch_window_direction_battery(
    *, as_of: str, window_days: int = DEFAULT_WINDOW_DAYS,
    seed: int = DEFAULT_SEED, out: str | Path,
) -> dict[str, Any]:
    """Build and deterministically write the JSON battery result."""
    out_path = safe_report_output_path(out, report_name=REPORT_NAME)
    report = build_branch_window_direction_battery(
        as_of=as_of, window_days=window_days, seed=seed,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report
