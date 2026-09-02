"""唯讀的「排行 V2」shadow 報表(docs/13 §8,2026-08-27 稽核建議)。

這份報表**不是** V2 的實作,而是 V2 的**證據**:它把 V1 現行口徑與 docs/13 §8
提出的 V2 口徑並列量化,讓人類拿數字決定門檻,而不是憑感覺拍板。

刻意不做的事:
  * 不呼叫 ``init_db()``、不建表、不 migration、不寫任何資料庫欄位。
  * 不改 ``compute_branch_stats`` 的行為;所有公式都從該模組 **匯入重用**,
    本模組不重新推導勝率、買點分位、近效性、可信度分數或隔日沖回吐判定。
  * 不決定「成熟樣本 <10 不評分」該怎麼解讀 —— 三種解讀同時計算並列,
    差異交給人看。

三種解讀(docs/13 §8「成熟樣本 <10 不評分」的歧義):
  a_score_and_flag  照樣評分、照樣入榜,只加註「樣本不足」標記。
  b_no_score        仍列在榜單上,但不給分數、不給名次(score/rank 為 null)。
  c_exclude         直接不列入榜單。

三者對「已評分分點」的名次是一致的;差別在於低成熟度分點是否還出現在榜上,
以及 V1 榜上被移除的分點讓出多少名次(rank drift)。報表把這件事量化。
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date as date_cls
from datetime import timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any

from sqlalchemy import text

# V1 的公式與門檻一律匯入重用,絕不在本模組重新推導。
from .compute_branch_stats import (
    DAYTRADE_MIN_OBS,
    DAYTRADE_RATE,
    MIN_RANK_EVENTS,
    QUAL_PCT,
    _BranchAgg,
    credibility_score,
    daytrade_flag,
    merge_consecutive_events,
    price_percentile,
    recency_factor,
)
from .performance import forward_returns
from .read_only_sqlite import get_read_only_sqlite_engine, safe_report_output_path

REPORT_NAME = "branch-ranking-v2-shadow"

REQUIRED_TABLES = (
    "branch_trades", "branch_trades_raw", "branch_dim",
    "daily_prices", "stocks", "branch_rankings",
)

# docs/13 §8 的 V2 提案值(本報表只用來量化,不寫入任何設定)。
V2_MATURED_PROVISIONAL = 10     # 成熟樣本 >= 10 → 暫定
V2_MATURED_SUFFICIENT = 30      # 成熟樣本 >= 30 → 充分
V2_DAYTRADE_MIN_OBS = 8         # 隔日沖最低觀察數(V1 為 4)

INTERPRETATIONS: dict[str, str] = {
    "a_score_and_flag": (
        "matured_samples < 10 仍評分並保留名次,只標記樣本不足"
        " (ranked set 與 V1 完全相同)"
    ),
    "b_no_score": (
        "matured_samples < 10 仍列在榜上,但 score 與 rank 皆為 null"
    ),
    "c_exclude": (
        "matured_samples < 10 直接不列入榜單"
    ),
}


def _validate_as_of(value: str) -> str:
    try:
        return date_cls.fromisoformat(value).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"as_of must be YYYY-MM-DD: {value!r}") from exc


def maturity_tier(matured_samples: int) -> str:
    """docs/13 §8 的成熟度級距:<10 不足 / 10-29 暫定 / >=30 充分。"""
    if matured_samples >= V2_MATURED_SUFFICIENT:
        return "sufficient"
    if matured_samples >= V2_MATURED_PROVISIONAL:
        return "provisional"
    return "insufficient"


def daytrade_verdicts(observations: list[tuple[float, float]]) -> dict[str, Any]:
    """同一組觀察值在 4 筆與 8 筆最低門檻下的隔日沖判定。

    回吐比率一律由 ``daytrade_flag`` 產生(不在此重新推導);觀察數不足時
    V1 回傳 (False, None) —— 亦即「未判定卻預設為否」,V2 則明確記為 unknown。
    """
    obs_count = sum(1 for net, _sell in observations if net and net > 0)
    is_dt_v1, rate = daytrade_flag(observations)
    v1 = {
        "min_obs": DAYTRADE_MIN_OBS,
        "verdict": is_dt_v1,
        "status": "determined" if obs_count >= DAYTRADE_MIN_OBS else "not_determined_defaults_false",
    }
    if obs_count >= V2_DAYTRADE_MIN_OBS and rate is not None:
        v2 = {
            "min_obs": V2_DAYTRADE_MIN_OBS,
            "verdict": rate >= DAYTRADE_RATE,
            "status": "determined",
        }
    else:
        v2 = {"min_obs": V2_DAYTRADE_MIN_OBS, "verdict": None, "status": "unknown"}
    return {
        "observations": obs_count,
        "payback_rate": round(rate, 6) if rate is not None else None,
        "payback_rate_status": "computed" if rate is not None else "below_v1_min_obs",
        "v1_min4": v1,
        "v2_min8": v2,
        "verdict_differs": v1["verdict"] is not v2["verdict"],
    }


def _assign_ranks(scored: list[tuple[str, float]]) -> dict[str, int]:
    """名次:分數高者在前,同分以分點名稱升冪決勝(輸出必須可重現)。"""
    ordered = sorted(scored, key=lambda item: (-item[1], item[0]))
    return {name: index for index, (name, _score) in enumerate(ordered, 1)}


def _interpretation_placement(
    key: str, *, eligible: bool, matured: int, score: float,
) -> dict[str, Any]:
    if not eligible:
        return {
            "listed": False, "scored": False, "score": None,
            "status": "below_v1_event_threshold",
        }
    if matured >= V2_MATURED_PROVISIONAL:
        return {"listed": True, "scored": True, "score": score, "status": "scored"}
    if key == "a_score_and_flag":
        return {
            "listed": True, "scored": True, "score": score,
            "status": "scored_insufficient_maturity_flagged",
        }
    if key == "b_no_score":
        return {
            "listed": True, "scored": False, "score": None,
            "status": "listed_without_score",
        }
    return {
        "listed": False, "scored": False, "score": None,
        "status": "excluded_insufficient_maturity",
    }


def _drift_stats(drifts: list[int]) -> dict[str, Any]:
    """存活分點的名次漂移統計(正值 = V2 名次上升)。"""
    if not drifts:
        return {
            "survivors": 0, "moved": 0, "unchanged": 0,
            "max_improvement": None, "max_worsening": None,
            "mean_abs": None, "median_abs": None,
            "status": "no_surviving_ranked_branches",
        }
    absolute = [abs(value) for value in drifts]
    return {
        "survivors": len(drifts),
        "moved": sum(1 for value in drifts if value != 0),
        "unchanged": sum(1 for value in drifts if value == 0),
        "max_improvement": max(drifts),
        "max_worsening": min(drifts),
        "mean_abs": round(mean(absolute), 6),
        "median_abs": round(median(absolute), 6),
        "status": "computed",
    }


def _fetch(conn, as_of: str) -> tuple[dict[str, _BranchAgg], dict[str, list[tuple[float, float]]], dict[str, Any]]:
    """Point-in-time 重算 V1 的分點 pooled 累加器(只讀 as_of 當日與之前的資料)。"""
    stock_ids = [row[0] for row in conn.execute(text("""
        SELECT DISTINCT b.stock_id
        FROM branch_trades b
        JOIN stocks s ON s.id = b.stock_id
        WHERE s.type = 'stock' AND s.name NOT LIKE '%指%' AND b.date <= :as_of
        ORDER BY b.stock_id
    """), {"as_of": as_of}).fetchall()]

    as_of_d = date_cls.fromisoformat(as_of)
    cutoff90 = (as_of_d - timedelta(days=90)).isoformat()
    cutoff2y = (as_of_d - timedelta(days=730)).isoformat()

    aggs: dict[str, _BranchAgg] = {}
    observations: dict[str, list[tuple[float, float]]] = defaultdict(list)
    observed_trade_rows = 0
    branch_stock_pairs = 0

    for sid in stock_ids:
        prows = conn.execute(text("""
            SELECT date, open, close, adj_factor
            FROM daily_prices
            WHERE stock_id = :sid AND close IS NOT NULL AND date <= :as_of
            ORDER BY date
        """), {"sid": sid, "as_of": as_of}).fetchall()
        trading_dates = [row[0] for row in prows]
        date_index = {day: index for index, day in enumerate(trading_dates)}
        adj_candles = [
            {"date": row[0], "open": (row[1] or 0) * (row[3] or 1.0),
             "close": (row[2] or 0) * (row[3] or 1.0)}
            for row in prows
        ]
        adj_close = [(row[2] or 0) * (row[3] or 1.0) for row in prows]
        close_by_date = {row[0]: row[2] for row in prows}

        trade_rows = conn.execute(text("""
            SELECT branch_name, date, net_lots, sell_lots, pct
            FROM branch_trades
            WHERE stock_id = :sid AND date <= :as_of
        """), {"sid": sid, "as_of": as_of}).fetchall()
        observed_trade_rows += len(trade_rows)

        by_branch: dict[str, dict[str, dict]] = defaultdict(dict)
        for branch_name, day, net, sell, pct in trade_rows:
            by_branch[branch_name][day] = {"net": net, "sell": sell, "pct": pct}

        for branch_name, datemap in by_branch.items():
            qual_dates = sorted(
                day for day, row in datemap.items()
                if (row["net"] or 0) > 0 and row["pct"] is not None and row["pct"] >= QUAL_PCT
            )
            if not qual_dates:
                continue
            branch_stock_pairs += 1

            agg = aggs.get(branch_name)
            if agg is None:
                agg = _BranchAgg()
                aggs[branch_name] = agg

            for qual_date in qual_dates:
                net = datemap[qual_date]["net"]
                index = date_index.get(qual_date)
                next_sell = 0
                if index is not None and index + 1 < len(trading_dates):
                    next_row = datemap.get(trading_dates[index + 1])
                    next_sell = (next_row["sell"] if next_row else 0) or 0
                observations[branch_name].append((net, next_sell))
                agg.add_obs(net, next_sell)

            for event_date in merge_consecutive_events(qual_dates, date_index):
                perf = forward_returns(adj_candles, event_date)
                fwd5 = perf["fwd_5d"] if perf else None
                index = date_index.get(event_date)
                pctile = 0.5
                if index is not None:
                    window = [value for value in adj_close[max(0, index - 19):index + 1] if value is not None]
                    if window:
                        pctile = price_percentile(adj_close[index], min(window), max(window))
                agg.add_event(event_date, fwd5, pctile, cutoff90, cutoff2y)

            for qual_date in qual_dates:
                if qual_date >= cutoff90:
                    close = close_by_date.get(qual_date)
                    if close:
                        agg.amount += (datemap[qual_date]["net"] or 0) * 1000 * close

    coverage = {
        "stocks_scanned": len(stock_ids),
        "observed_branch_trade_rows": observed_trade_rows,
        "branch_stock_pairs_with_events": branch_stock_pairs,
        "cutoff_90d": cutoff90,
        "cutoff_2y": cutoff2y,
    }
    return aggs, observations, coverage


def _stored_snapshot(conn, as_of: str) -> tuple[str | None, dict[str, dict[str, Any]]]:
    """最近一次 <= as_of 的 branch_rankings 快照,僅作對照,不作為計算來源。"""
    snapshot_as_of = conn.execute(text(
        "SELECT MAX(as_of) FROM branch_rankings WHERE as_of <= :as_of"
    ), {"as_of": as_of}).scalar()
    if not snapshot_as_of:
        return None, {}
    rows = conn.execute(text("""
        SELECT branch_name, rank_score, samples, is_daytrade
        FROM branch_rankings
        WHERE as_of = :snapshot
    """), {"snapshot": snapshot_as_of}).fetchall()
    return snapshot_as_of, {
        row[0]: {"rank_score": row[1], "samples": row[2], "is_daytrade": bool(row[3]) if row[3] is not None else None}
        for row in rows
    }


def build_branch_ranking_v2_shadow_report(*, as_of: str) -> dict[str, Any]:
    """建立 V1 vs V2 排行差異的唯讀 JSON 報表(可重現、可序列化)。"""
    as_of = _validate_as_of(as_of)
    engine = get_read_only_sqlite_engine(
        report_name=REPORT_NAME, required_tables=REQUIRED_TABLES,
    )
    try:
        with engine.connect() as conn:
            aggs, observations, coverage = _fetch(conn, as_of)
            snapshot_as_of, snapshot = _stored_snapshot(conn, as_of)
            market_days = conn.execute(text(
                "SELECT COUNT(DISTINCT date) FROM daily_prices WHERE date <= :as_of"
            ), {"as_of": as_of}).scalar() or 0
    finally:
        engine.dispose()

    # 分點層級彙總:比例式沿用 compute_branch_stats.compute_all 的定義。
    metrics: dict[str, dict[str, Any]] = {}
    for branch_name, agg in aggs.items():
        matured = agg.n_matured
        win_rate = (100.0 * agg.win_count / matured) if matured else None
        avg_ret5 = (agg.sum_ret5 / matured) if matured else None
        avg_pctile = (agg.sum_pctile / agg.n_events) if agg.n_events else 0.5
        avg90 = (agg.sum_ret5_90 / agg.n_matured_90) if agg.n_matured_90 else None
        recency = recency_factor(avg90, avg_ret5)
        metrics[branch_name] = {
            "events_count": agg.n_events,
            "matured_samples": matured,
            "win_rate": win_rate,
            "avg_ret5": avg_ret5,
            "score": credibility_score(win_rate, avg_ret5, avg_pctile, agg.amount, recency),
            "events_90d": agg.n_ev_90,
            "events_2y": agg.n_ev_2y,
        }

    v1_ranks = _assign_ranks([
        (name, item["score"]) for name, item in metrics.items()
        if item["events_count"] >= MIN_RANK_EVENTS
    ])

    placements: dict[str, dict[str, dict[str, Any]]] = {}
    v2_ranks: dict[str, dict[str, int]] = {}
    for key in INTERPRETATIONS:
        placement = {
            name: _interpretation_placement(
                key,
                eligible=item["events_count"] >= MIN_RANK_EVENTS,
                matured=item["matured_samples"],
                score=item["score"],
            )
            for name, item in metrics.items()
        }
        placements[key] = placement
        v2_ranks[key] = _assign_ranks([
            (name, entry["score"]) for name, entry in placement.items() if entry["scored"]
        ])

    rows: list[dict[str, Any]] = []
    for branch_name in sorted(metrics):
        item = metrics[branch_name]
        matured = item["matured_samples"]
        v1_rank = v1_ranks.get(branch_name)
        interpretations: dict[str, Any] = {}
        for key in INTERPRETATIONS:
            entry = dict(placements[key][branch_name])
            rank = v2_ranks[key].get(branch_name)
            entry["rank"] = rank
            entry["rank_drift"] = (v1_rank - rank) if (rank is not None and v1_rank is not None) else None
            entry["rank_drift_status"] = "computed" if entry["rank_drift"] is not None else (
                "not_ranked_in_v2" if v1_rank is not None else "not_ranked_in_v1"
            )
            interpretations[key] = entry
        stored = snapshot.get(branch_name)
        rows.append({
            "branch_name": branch_name,
            # V1 的 samples 就是事件總數 —— 這正是被稽核指出的混用。
            "v1_samples": item["events_count"],
            "events_count": item["events_count"],
            "matured_samples": matured,
            "immature_events": item["events_count"] - matured,
            "maturity_tier": maturity_tier(matured),
            "win_rate": round(item["win_rate"], 6) if item["win_rate"] is not None else None,
            "avg_ret5": round(item["avg_ret5"], 6) if item["avg_ret5"] is not None else None,
            "win_rate_status": "computed" if matured else "no_matured_events",
            "events_90d": item["events_90d"],
            "events_2y": item["events_2y"],
            "v1_score": item["score"],
            "v1_rank": v1_rank,
            "v1_ranked": v1_rank is not None,
            "v1_rank_status": "ranked" if v1_rank is not None else "below_v1_event_threshold",
            "v2_interpretations": interpretations,
            "daytrade": daytrade_verdicts(observations.get(branch_name, [])),
            "stored_ranking_snapshot": {
                "as_of": snapshot_as_of,
                "status": (
                    "no_snapshot_at_or_before_as_of" if snapshot_as_of is None
                    else ("present" if stored else "absent_from_snapshot")
                ),
                "rank_score": stored["rank_score"] if stored else None,
                "samples": stored["samples"] if stored else None,
                "is_daytrade": stored["is_daytrade"] if stored else None,
            },
        })

    tier_counts = {tier: 0 for tier in ("insufficient", "provisional", "sufficient")}
    for row in rows:
        tier_counts[row["maturity_tier"]] += 1

    v1_listed = {name for name in v1_ranks}
    interpretation_summary: dict[str, Any] = {}
    for key in INTERPRETATIONS:
        placement = placements[key]
        listed = {name for name, entry in placement.items() if entry["listed"]}
        scored = {name for name, entry in placement.items() if entry["scored"]}
        drifts = [
            v1_ranks[name] - v2_ranks[key][name]
            for name in sorted(scored & v1_listed)
        ]
        interpretation_summary[key] = {
            "definition": INTERPRETATIONS[key],
            "listed_count": len(listed),
            "scored_count": len(scored),
            "entered_ranked_set": sorted(listed - v1_listed),
            "entered_count": len(listed - v1_listed),
            "left_ranked_set": sorted(v1_listed - listed),
            "left_count": len(v1_listed - listed),
            "listed_without_score": sorted(listed - scored),
            "listed_without_score_count": len(listed - scored),
            "rank_drift": _drift_stats(drifts),
            "top10_v1": [
                {"rank": v1_ranks[name], "branch_name": name, "score": metrics[name]["score"]}
                for name in sorted(v1_listed, key=lambda item: v1_ranks[item])[:10]
            ],
            "top10_v2": [
                {
                    "rank": v2_ranks[key][name],
                    "branch_name": name,
                    "score": placement[name]["score"],
                    "v1_rank": v1_ranks.get(name),
                }
                for name in sorted(scored, key=lambda item: v2_ranks[key][item])[:10]
            ],
        }

    daytrade_rows = [row["daytrade"] for row in rows]
    daytrade_summary = {
        "branches": len(daytrade_rows),
        "determined_min4": sum(item["v1_min4"]["status"] == "determined" for item in daytrade_rows),
        "not_determined_min4_defaulting_false": sum(
            item["v1_min4"]["status"] == "not_determined_defaults_false" for item in daytrade_rows
        ),
        "determined_min8": sum(item["v2_min8"]["status"] == "determined" for item in daytrade_rows),
        "unknown_min8": sum(item["v2_min8"]["status"] == "unknown" for item in daytrade_rows),
        "flagged_min4": sum(item["v1_min4"]["verdict"] is True for item in daytrade_rows),
        "flagged_min8": sum(item["v2_min8"]["verdict"] is True for item in daytrade_rows),
        "verdict_differs": sum(item["verdict_differs"] for item in daytrade_rows),
    }

    return {
        "metadata": {
            "report": "branch_ranking_v2_shadow",
            "as_of": as_of,
            "read_only": True,
            "schema_changes": False,
            "ranking_or_score_changes": False,
            "thresholds": {
                "qualifying_pct": QUAL_PCT,
                "v1_min_rank_events": MIN_RANK_EVENTS,
                "v1_daytrade_min_obs": DAYTRADE_MIN_OBS,
                "v2_daytrade_min_obs": V2_DAYTRADE_MIN_OBS,
                "v2_matured_provisional": V2_MATURED_PROVISIONAL,
                "v2_matured_sufficient": V2_MATURED_SUFFICIENT,
                "daytrade_payback_rate": DAYTRADE_RATE,
            },
        },
        "definitions": {
            "point_in_time": "只讀 as_of 當日與之前的 branch_trades 與 daily_prices;分數以該時點重算,不使用之後才存在的價格。",
            "events_count": "V1 事件定義(net_lots > 0 且 pct >= 1%,連續交易日合併,取首日)的事件總數,含尚未成熟者。",
            "matured_samples": "上述事件中 forward_returns fwd_5d 已可計算者;勝率與平均報酬只用這些。",
            "v1_samples": "V1 branch_rankings.samples 現行寫入值,等同 events_count —— 成熟與未成熟混用,即稽核指出的缺陷。",
            "maturity_tier": "docs/13 §8:matured_samples <10 insufficient、10-29 provisional、>=30 sufficient。",
            "score": "分數公式未變,沿用 compute_branch_stats.credibility_score;V2 三種解讀只改『誰被評分/入榜』,不改公式。",
            "rank": "分數高者在前,同分以分點名稱升冪決勝;名次為序數 1..N。",
            "rank_drift": "v1_rank - v2_rank;正值代表該分點在 V2 名次上升(通常因為前面的低成熟度分點被移除)。",
            "entered_ranked_set": "V2 三種解讀的入榜資格都是 V1 入榜集合的子集,因此結構上不可能有新進者;此欄位仍列出以供驗證。",
            "daytrade_unknown": "觀察數 < 該門檻時,V1 回傳 False(未判定卻預設為否),V2 記為 unknown 且 verdict 為 null。",
            "null_policy": "任何無法計算的值一律為 null 並附狀態欄位,絕不以 0 或 False 冒充。",
        },
        "coverage": {
            **coverage,
            "market_trading_days_through_as_of": market_days,
            "branches_evaluated": len(rows),
            "stored_ranking_snapshot_as_of": snapshot_as_of,
            "stored_ranking_snapshot_status": (
                "no_snapshot_at_or_before_as_of" if snapshot_as_of is None else "present"
            ),
            "branch_trade_capture_note": (
                "branch_trades 只是每日前 15 大買/賣超切片。缺列代表未被觀察到,不等於沒有交易或沒有賣出。"
            ),
        },
        "summary": {
            "branches_evaluated": len(rows),
            "maturity_tiers": tier_counts,
            "v1_ranked_count": len(v1_listed),
            "v1_ranked_with_insufficient_maturity": sum(
                1 for row in rows
                if row["v1_ranked"] and row["maturity_tier"] == "insufficient"
            ),
            "total_events": sum(row["events_count"] for row in rows),
            "total_matured_samples": sum(row["matured_samples"] for row in rows),
            "total_immature_events": sum(row["immature_events"] for row in rows),
            "interpretations": interpretation_summary,
            "daytrade": daytrade_summary,
        },
        "branch_rows": rows,
    }


def write_branch_ranking_v2_shadow_report(*, as_of: str, out: str | Path) -> dict[str, Any]:
    """先擋掉危險輸出路徑,再查詢與寫出決定性的 JSON。"""
    out_path = safe_report_output_path(out, report_name=REPORT_NAME)
    report = build_branch_ranking_v2_shadow_report(as_of=as_of)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report
