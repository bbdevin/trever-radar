"""唯讀的 E2 point-in-time shadow「跨 as_of 穩定度」聚合報表。

單一 as_of 的 shadow 報表只能回答「這一天看起來如何」，無法回答
「這個訊號是穩定的，還是我們剛好挑到的那一天的產物」。本模組把既有的
:mod:`radar.compute.branch_point_in_time_report` 在多個 as_of 交易日上重複執行
（每次都用該 as_of 的 trailing window），再把結果聚合成帶有離散度的序列。

本模組刻意不呼叫 ``init_db()``、不建表、不 migration、不寫任何業務資料；
它只讀既有資料庫，並且完全重用既有報表的定義與計算，不改變其輸出契約。

它同樣**不做** buy→sell 配對、不做交易損益歸因、不宣稱勝率：buy 與 sell
episode 各自獨立統計，fwd5 僅為描述性觀察。
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import text

from .branch_point_in_time_report import (
    build_branch_point_in_time_report,
    get_read_only_engine,
)
from .read_only_sqlite import safe_report_output_path

REPORT_NAME = "branch-point-in-time-series"

RATE_FIELDS = ("low_buy_rate", "high_sell_rate", "fwd5_positive_rate")


def _validate_date(value: str, name: str) -> str:
    from datetime import date

    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be YYYY-MM-DD: {value!r}") from exc


def validate_series_window(
    *, as_of_from: str, as_of_to: str, step: int, window_days: int,
) -> tuple[str, str, int, int]:
    """Validate the as_of walk parameters before any query is attempted."""
    as_of_from = _validate_date(as_of_from, "as_of_from")
    as_of_to = _validate_date(as_of_to, "as_of_to")
    if as_of_from > as_of_to:
        raise ValueError("as-of-from must be on or before as-of-to")
    if not isinstance(step, int) or isinstance(step, bool) or step < 1:
        raise ValueError("step must be an integer >= 1")
    if not isinstance(window_days, int) or isinstance(window_days, bool) or window_days < 1:
        raise ValueError("window-days must be an integer >= 1")
    return as_of_from, as_of_to, step, window_days


def market_trading_days(*, through: str) -> list[str]:
    """Distinct market trading days at or before ``through`` (read-only)."""
    engine = get_read_only_engine()
    try:
        with engine.connect() as conn:
            return [
                row[0]
                for row in conn.execute(text("""
                    SELECT DISTINCT date
                    FROM daily_prices
                    WHERE date <= :through
                    ORDER BY date
                """), {"through": through}).fetchall()
            ]
    finally:
        engine.dispose()


def plan_as_of_walk(
    *, trading_days: list[str], as_of_from: str, as_of_to: str, step: int, window_days: int,
) -> list[dict[str, Any]]:
    """Land every as_of on a market trading day; never on a non-trading date.

    The trailing window is counted in *market trading days* ending on the as_of
    day inclusive, so a window is comparable across dates regardless of holidays.
    When fewer prior trading days exist the window is truncated and flagged; it
    is never padded and never interpolated.
    """
    in_range = [day for day in trading_days if as_of_from <= day <= as_of_to]
    index_of = {day: index for index, day in enumerate(trading_days)}
    plan: list[dict[str, Any]] = []
    for offset in range(0, len(in_range), step):
        as_of = in_range[offset]
        end_index = index_of[as_of]
        start_index = end_index - (window_days - 1)
        truncated = start_index < 0
        start_index = max(start_index, 0)
        plan.append({
            "as_of": as_of,
            "window_from": trading_days[start_index],
            "window_to": as_of,
            "window_market_days": end_index - start_index + 1,
            "window_market_days_requested": window_days,
            "window_truncated": truncated,
        })
    return plan


def _rate(numerator: int, denominator: int) -> float | None:
    return round(100.0 * numerator / denominator, 6) if denominator else None


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def _stats(values: list[float]) -> dict[str, Any]:
    """Central tendency **and** spread; a mean alone would mislead here."""
    if not values:
        return {
            "count": 0, "mean": None, "median": None, "stdev": None,
            "min": None, "max": None, "range": None,
        }
    return {
        "count": len(values),
        "mean": _round(statistics.mean(values)),
        "median": _round(statistics.median(values)),
        # Sample standard deviation is undefined for a single observation; a
        # single as_of date must not be presented as if it had no spread.
        "stdev": _round(statistics.stdev(values)) if len(values) > 1 else None,
        "min": _round(min(values)),
        "max": _round(max(values)),
        "range": _round(max(values) - min(values)),
    }


def _true_count(episodes: Iterable[dict[str, Any]], field: str) -> int:
    """Count affirmative evidence only; ``None`` is unknown, never false."""
    return sum(episode[field] is True for episode in episodes)


def _entity_observation(
    *, episodes: list[dict[str, Any]], observed_trade_rows: int,
) -> dict[str, Any]:
    """One as_of observation for one entity, reusing the per-date report's fields.

    Buy and sell episodes are summarised independently. Nothing here pairs a buy
    with a sell, attributes profit, or computes a win rate.
    """
    buys = [episode for episode in episodes if episode["direction"] == "buy"]
    sells = [episode for episode in episodes if episode["direction"] == "sell"]
    known_buys = [item for item in buys if item["price_percentile_status"] == "known"]
    known_sells = [item for item in sells if item["price_percentile_status"] == "known"]
    matured_buys = [item for item in buys if item["fwd5_status"] == "matured"]
    fwd_values = [item["fwd5_pct"] for item in matured_buys]
    low_buy_count = _true_count(known_buys, "low_buy")
    high_sell_count = _true_count(known_sells, "high_sell")
    fwd5_positive_count = sum(value > 0 for value in fwd_values)
    return {
        "observed_trade_rows": observed_trade_rows,
        "buy_episode_count": len(buys),
        "sell_episode_count": len(sells),
        "buy_price_percentile_known": len(known_buys),
        "buy_price_percentile_unknown": len(buys) - len(known_buys),
        "sell_price_percentile_known": len(known_sells),
        "sell_price_percentile_unknown": len(sells) - len(known_sells),
        "low_buy_count": low_buy_count,
        "low_buy_rate": _rate(low_buy_count, len(known_buys)),
        "low_buy_rate_denominator": len(known_buys),
        "high_sell_count": high_sell_count,
        "high_sell_rate": _rate(high_sell_count, len(known_sells)),
        "high_sell_rate_denominator": len(known_sells),
        "fwd5_matured_buy_episodes": len(matured_buys),
        "fwd5_unknown_buy_episodes": len(buys) - len(matured_buys),
        "fwd5_positive_count": fwd5_positive_count,
        "fwd5_positive_rate": _rate(fwd5_positive_count, len(fwd_values)),
        "fwd5_positive_rate_denominator": len(fwd_values),
        "fwd5_avg_pct": _round(statistics.mean(fwd_values)) if fwd_values else None,
        "low_buy_high_sell_status": (
            "evidence" if known_buys and known_sells else "insufficient"
        ),
    }


_RATE_NUMERATOR = {
    "low_buy_rate": "low_buy_count",
    "high_sell_rate": "high_sell_count",
    "fwd5_positive_rate": "fwd5_positive_count",
}


def _aggregate_entity(
    *, identity: dict[str, Any], observations: dict[str, dict[str, Any]], as_of_dates: list[str],
) -> dict[str, Any]:
    """Aggregate one entity across the as_of series without hiding instability."""
    present_dates = [day for day in as_of_dates if day in observations]
    absent_dates = [day for day in as_of_dates if day not in observations]
    present = [observations[day] for day in present_dates]

    rates: dict[str, Any] = {}
    for field in RATE_FIELDS:
        denominator_field = f"{field}_denominator"
        defined_dates = [
            day for day in present_dates if observations[day][field] is not None
        ]
        values = [observations[day][field] for day in defined_dates]
        denominators = [observations[day][denominator_field] for day in defined_dates]
        pooled_numerator = sum(item[_RATE_NUMERATOR[field]] for item in present)
        pooled_denominator = sum(item[denominator_field] for item in present)
        rates[field] = {
            "as_of_dates_defined": len(defined_dates),
            "as_of_dates_undefined": len(present_dates) - len(defined_dates),
            "defined_as_of_dates": defined_dates,
            "values": values,
            "stats": _stats(values),
            "episode_denominator_series": denominators,
            "episode_denominator_stats": _stats([float(value) for value in denominators]),
            "pooled_numerator": pooled_numerator,
            "pooled_denominator": pooled_denominator,
            "pooled_rate": _rate(pooled_numerator, pooled_denominator),
        }

    fwd_avg_dates = [day for day in present_dates if observations[day]["fwd5_avg_pct"] is not None]
    fwd_avg_values = [observations[day]["fwd5_avg_pct"] for day in fwd_avg_dates]
    fwd_weight = sum(observations[day]["fwd5_positive_rate_denominator"] for day in fwd_avg_dates)
    weighted_sum = sum(
        observations[day]["fwd5_avg_pct"] * observations[day]["fwd5_positive_rate_denominator"]
        for day in fwd_avg_dates
    )

    status_counts = {"evidence": 0, "insufficient": 0}
    for item in present:
        status_counts[item["low_buy_high_sell_status"]] += 1

    def _series(field: str) -> list[int]:
        return [observations[day][field] for day in present_dates]

    def _total(field: str) -> int:
        return sum(item[field] for item in present)

    def _peak(field: str) -> int:
        return max((item[field] for item in present), default=0)

    return {
        **identity,
        "as_of_dates_evaluated": len(as_of_dates),
        "as_of_dates_present": len(present_dates),
        "as_of_dates_absent": len(absent_dates),
        "presence_rate_pct": _rate(len(present_dates), len(as_of_dates)),
        "present_as_of_dates": present_dates,
        "absent_as_of_dates": absent_dates,
        "gap_handling": "absent as_of dates are listed, never interpolated or carried forward",
        "observed_trade_rows_series": _series("observed_trade_rows"),
        "buy_episode_count_series": _series("buy_episode_count"),
        "sell_episode_count_series": _series("sell_episode_count"),
        "buy_episode_count_stats": _stats([float(value) for value in _series("buy_episode_count")]),
        "sell_episode_count_stats": _stats([float(value) for value in _series("sell_episode_count")]),
        "rates": rates,
        "fwd5_avg_pct_observation": {
            "as_of_dates_defined": len(fwd_avg_dates),
            "as_of_dates_undefined": len(present_dates) - len(fwd_avg_dates),
            "values": fwd_avg_values,
            "stats": _stats(fwd_avg_values),
            "pooled_matured_buy_episodes": fwd_weight,
            "pooled_weighted_avg_pct": _round(weighted_sum / fwd_weight) if fwd_weight else None,
            "note": "描述性觀察；不是分點實際獲利、持倉成本或勝率。",
        },
        "known_unknown_totals": {
            "buy_price_percentile_known_total": _total("buy_price_percentile_known"),
            "buy_price_percentile_unknown_total": _total("buy_price_percentile_unknown"),
            "buy_price_percentile_unknown_max_on_one_as_of": _peak("buy_price_percentile_unknown"),
            "sell_price_percentile_known_total": _total("sell_price_percentile_known"),
            "sell_price_percentile_unknown_total": _total("sell_price_percentile_unknown"),
            "sell_price_percentile_unknown_max_on_one_as_of": _peak("sell_price_percentile_unknown"),
            "fwd5_matured_buy_episodes_total": _total("fwd5_matured_buy_episodes"),
            "fwd5_unknown_buy_episodes_total": _total("fwd5_unknown_buy_episodes"),
            "fwd5_unknown_buy_episodes_max_on_one_as_of": _peak("fwd5_unknown_buy_episodes"),
        },
        "low_buy_high_sell_status_counts": status_counts,
    }


def build_branch_point_in_time_series(
    *, as_of_from: str, as_of_to: str, step: int = 1, window_days: int = 60,
) -> dict[str, Any]:
    """Run the existing per-date shadow report across many as_of dates and aggregate."""
    as_of_from, as_of_to, step, window_days = validate_series_window(
        as_of_from=as_of_from, as_of_to=as_of_to, step=step, window_days=window_days,
    )
    trading_days = market_trading_days(through=as_of_to)
    plan = plan_as_of_walk(
        trading_days=trading_days, as_of_from=as_of_from, as_of_to=as_of_to,
        step=step, window_days=window_days,
    )
    as_of_dates = [entry["as_of"] for entry in plan]

    per_as_of: list[dict[str, Any]] = []
    branch_observations: dict[str, dict[str, dict[str, Any]]] = {}
    branch_stock_observations: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    branch_stock_names: dict[tuple[str, str], str] = {}
    capture_note = ""
    empty_as_of_dates: list[str] = []

    for entry in plan:
        report = build_branch_point_in_time_report(
            as_of=entry["as_of"], date_from=entry["window_from"], date_to=entry["window_to"],
        )
        capture_note = report["coverage"]["branch_trade_capture_note"]
        rows = report["branch_stock_rows"]
        if not rows:
            empty_as_of_dates.append(entry["as_of"])
        per_as_of.append({
            **entry,
            "universe_branch_count": report["coverage"]["universe_branch_count"],
            "observed_branch_stock_rows": report["coverage"]["observed_branch_stock_rows"],
            "observed_branch_trade_rows": report["coverage"]["observed_branch_trade_rows"],
            "trade_rows_missing_pct": report["coverage"]["trade_rows_missing_pct"],
            "market_trading_days_in_requested_window":
                report["coverage"]["market_trading_days_in_requested_window"],
            "summary": report["summary"],
        })

        trade_rows_by_branch: dict[str, int] = {}
        trade_rows_by_pair: dict[tuple[str, str], int] = {}
        for row in rows:
            key = (row["branch_name"], row["stock_id"])
            trade_rows_by_branch[row["branch_name"]] = (
                trade_rows_by_branch.get(row["branch_name"], 0) + row["observed_trade_rows"]
            )
            trade_rows_by_pair[key] = trade_rows_by_pair.get(key, 0) + row["observed_trade_rows"]
            branch_stock_names[key] = row["stock_name"]

        episodes_by_branch: dict[str, list[dict[str, Any]]] = {}
        episodes_by_pair: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for episode in report["episode_samples"]:
            key = (episode["branch_name"], episode["stock_id"])
            episodes_by_branch.setdefault(episode["branch_name"], []).append(episode)
            episodes_by_pair.setdefault(key, []).append(episode)

        for branch_name, observed_trade_rows in trade_rows_by_branch.items():
            branch_observations.setdefault(branch_name, {})[entry["as_of"]] = _entity_observation(
                episodes=episodes_by_branch.get(branch_name, []),
                observed_trade_rows=observed_trade_rows,
            )
        for key, observed_trade_rows in trade_rows_by_pair.items():
            branch_stock_observations.setdefault(key, {})[entry["as_of"]] = _entity_observation(
                episodes=episodes_by_pair.get(key, []),
                observed_trade_rows=observed_trade_rows,
            )

    branch_series = [
        _aggregate_entity(
            identity={"branch_name": branch_name},
            observations=observations,
            as_of_dates=as_of_dates,
        )
        for branch_name, observations in sorted(branch_observations.items())
    ]
    branch_stock_series = [
        _aggregate_entity(
            identity={
                "branch_name": key[0],
                "stock_id": key[1],
                "stock_name": branch_stock_names[key],
            },
            observations=observations,
            as_of_dates=as_of_dates,
        )
        for key, observations in sorted(branch_stock_observations.items())
    ]

    return {
        "metadata": {
            "report": "branch_point_in_time_shadow_series",
            "source_report": "branch_point_in_time_shadow",
            "as_of_from": as_of_from,
            "as_of_to": as_of_to,
            "step_market_days": step,
            "window_market_days": window_days,
            "read_only": True,
            "schema_changes": False,
            "ranking_or_score_changes": False,
            "buy_sell_pairing": False,
            "trade_profit_attribution": False,
        },
        "definitions": {
            "question": "is a branch or branch-stock signal stable across as_of dates, or an artefact of the one date we happened to look at?",
            "as_of_walk": "every step-th market trading day between as-of-from and as-of-to inclusive; non-trading calendar dates are never used as an as_of",
            "window": "each as_of runs the existing per-date shadow report over the trailing window-days market trading days ending on that as_of inclusive; short history truncates the window and is flagged, never padded",
            "per_date_computation": "unchanged: definitions, episodes, percentiles and fwd5 come from branch_point_in_time_shadow and are reused verbatim",
            "entity_presence": "an entity is present at an as_of only if that as_of's report observed at least one branch-stock row for it; absence is reported, never interpolated",
            "rate_stats": "each rate is summarised with count, mean, median, sample stdev (None for a single observation), min, max and range, plus the per-as_of episode denominators behind it",
            "pooled_rate": "numerator and denominator summed across as_of dates; overlapping trailing windows re-observe the same episodes, so a pooled rate is not a sample of independent observations",
            "buy_sell_independence": "buy and sell episodes are aggregated independently; nothing here pairs them, attributes profit, or computes a win rate",
            "fwd5_observation": "descriptive only, inherited from the per-date report; incomplete price windows stay unknown, never zero",
        },
        "coverage": {
            "market_trading_days_through_as_of_to": len(trading_days),
            "market_trading_days_in_as_of_range": sum(
                as_of_from <= day <= as_of_to for day in trading_days
            ),
            "as_of_dates_evaluated": len(as_of_dates),
            "as_of_dates": as_of_dates,
            "as_of_dates_with_no_branch_stock_rows": empty_as_of_dates,
            "as_of_dates_with_truncated_window": [
                entry["as_of"] for entry in plan if entry["window_truncated"]
            ],
            "branch_entity_count": len(branch_series),
            "branch_stock_entity_count": len(branch_stock_series),
            "branch_trade_capture_note": capture_note,
            "series_overlap_note": "consecutive as_of windows overlap by window-days minus step market trading days; treat the series as repeated overlapping views, not independent samples.",
        },
        "per_as_of": per_as_of,
        "branch_series": branch_series,
        "branch_stock_series": branch_stock_series,
    }


def write_branch_point_in_time_series(
    *, as_of_from: str, as_of_to: str, step: int, window_days: int, out: str | Path,
) -> dict[str, Any]:
    """Build and deterministically write the standalone aggregate JSON."""
    out_path = safe_report_output_path(out, report_name=REPORT_NAME)
    report = build_branch_point_in_time_series(
        as_of_from=as_of_from, as_of_to=as_of_to, step=step, window_days=window_days,
    )
    out_path = Path(out_path).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report
