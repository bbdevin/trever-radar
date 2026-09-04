"""
Phase 3: strategy performance backfill (report-only).

We compute objective stats per frozen S code:
- samples: count of matured rows with fwd_{h}d not null
- win_rate: % of matured rows with fwd_{h}d > 0
- avg_ret / median_ret: average/median of fwd_{h}d
- recent segment: last N matured events (by date) per strategy

Important:
- This module does NOT write to DB. It only reads frozen daily_scores
  (fwd_* returns are already computed by compute-performance).
- Strategy codes S1-S10 are stored in indicators_daily.reasons; S11-S13 are
  stored in daily_scores.reasons.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text

from .. import config
from .read_only_sqlite import get_read_only_sqlite_engine, safe_report_output_path

HORIZONS = (5, 10, 20)

STRATEGIES: list[dict[str, str]] = [
    {"key": "S1_REBOUND", "label": "漲停二次發動"},
    {"key": "S2_BREAKOUT20", "label": "20日爆量突破"},
    {"key": "S3_MA_CONVERGE_BREAKOUT", "label": "均線糾結突破"},
    {"key": "S4_VOLATILITY_CONTRACTION", "label": "波動收斂突破"},
    {"key": "S4_COMPRESSION_SETUP_V2", "label": "S4 壓縮蓄勢 V2"},
    {"key": "S4_COMPRESSION_BREAKOUT_V2", "label": "S4 壓縮突破 V2"},
    {"key": "S5_PULLBACK_SUPPORT", "label": "強勢量縮回踩"},
    {"key": "S6_HIGH_BASE_BREAKOUT", "label": "高檔平台突破"},
    {"key": "S7_MACD_ZERO_CROSS", "label": "MACD零軸金叉"},
    {"key": "S8_GAP_BREAKOUT", "label": "跳空不回補"},
    {"key": "S9_MA5_TREND", "label": "五日線強攻"},
    {"key": "S10_BOTTOM_MACD", "label": "底部MACD轉強"},
    {"key": "S11_INSTI_BREAKOUT", "label": "法人連買突破"},
    {"key": "S12_BRANCH_ACCUMULATION", "label": "分點集中未發動"},
    {"key": "S13_SHORT_SQUEEZE", "label": "融券減＋帶量長紅"},
]

STRATEGY_CODE_SET = {s["key"] for s in STRATEGIES}
STRATEGY_BY_KEY = {s["key"]: s for s in STRATEGIES}

# S1 has a relaxed variant historically. UI/JSON uses only S1_REBOUND key.
CODE_ALIASES = {"S1_REBOUND_RELAXED": "S1_REBOUND"}


def _parse_reasons(reasons_json: str | None) -> list[dict[str, Any]]:
    if not reasons_json:
        return []
    try:
        v = json.loads(reasons_json)
    except json.JSONDecodeError:
        return []
    if not isinstance(v, list):
        return []
    return [x for x in v if isinstance(x, dict)]


def extract_strategy_codes(reasons_items: list[dict[str, Any]]) -> list[str]:
    """Extract triggered strategy codes from a parsed reasons list."""
    out: list[str] = []
    for item in reasons_items:
        raw = item.get("code")
        if not raw or not isinstance(raw, str):
            continue
        code = CODE_ALIASES.get(raw, raw)
        if code in STRATEGY_CODE_SET:
            out.append(code)
    return out


@dataclass(frozen=True)
class StrategyEvent:
    date: str
    fwd_5d: float | None
    fwd_10d: float | None
    fwd_20d: float | None
    stock_id: str = ""


def dedupe_setup_episodes(
    events: list[StrategyEvent], *, trading_dates: list[str],
) -> list[StrategyEvent]:
    """Keep the first event of each consecutive per-stock setup episode.

    S4 setup may validly remain true on consecutive trading days.  Its
    performance sample is an episode, not one sample per day.  The caller
    supplies the market's trading-date order so weekend/holiday gaps do not
    accidentally create new episodes.
    """
    date_index = {d: n for n, d in enumerate(sorted(set(trading_dates)))}
    out: list[StrategyEvent] = []
    by_stock: dict[str, list[StrategyEvent]] = {}
    for event in events:
        by_stock.setdefault(event.stock_id, []).append(event)
    for stock_events in by_stock.values():
        previous_index: int | None = None
        for event in sorted(stock_events, key=lambda e: e.date):
            current_index = date_index.get(event.date)
            if current_index is None or previous_index is None or current_index != previous_index + 1:
                out.append(event)
            previous_index = current_index
    return sorted(out, key=lambda e: (e.date, e.stock_id))


def summarize_fwd_values(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"samples": 0, "win_rate": None, "avg_ret": None, "median_ret": None}
    wr = 100.0 * sum(1 for v in values if v > 0) / len(values)
    return {
        "samples": len(values),
        "win_rate": wr,
        "avg_ret": mean(values),
        "median_ret": median(values),
    }


def compute_recent_segment_stats(
    events: list[StrategyEvent],
    *,
    horizon: int,
    recent_events: int,
) -> dict[str, float | int | None]:
    """Take last N matured events (by date) for a horizon and summarize."""
    key = f"fwd_{horizon}d"
    matured = [e for e in events if getattr(e, key) is not None]
    if not matured:
        return {"samples": 0, "win_rate": None, "avg_ret": None, "median_ret": None}
    matured.sort(key=lambda e: e.date)
    tail = matured[-recent_events:] if recent_events > 0 else matured
    values = [getattr(e, key) for e in tail if getattr(e, key) is not None]
    return summarize_fwd_values(values)  # type: ignore[arg-type]


def compute_strategy_performance_from_events(
    events_by_code: dict[str, list[StrategyEvent]],
    *,
    recent_events: int = 50,
) -> dict[str, Any]:
    """Pure computation layer for unit tests."""
    out: dict[str, Any] = {}
    for code in sorted(events_by_code.keys()):
        events = events_by_code[code]
        events.sort(key=lambda e: e.date)
        per_h: dict[str, Any] = {}
        for h in HORIZONS:
            key = f"fwd_{h}d"
            values = [getattr(e, key) for e in events if getattr(e, key) is not None]
            per_h[f"h{h}"] = summarize_fwd_values(values)

        recent20 = compute_recent_segment_stats(
            events, horizon=20, recent_events=recent_events
        )
        out[code] = {
            "label": STRATEGY_BY_KEY.get(code, {}).get("label", code),
            "per_horizon": per_h,
            "recent20": recent20,
        }
    return out


def _norm_date_arg(date: str | None) -> str | None:
    if not date:
        return None
    if len(date) == 8:
        return f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    return date


def fetch_strategy_events(
    *,
    min_date: str | None = None,
    lookback_dates: int = 180,
) -> dict[str, list[StrategyEvent]]:
    """Read DB and build StrategyEvent lists per strategy (report-only)."""
    engine = get_read_only_sqlite_engine(
        report_name="phase3 strategy performance report",
        required_tables=("daily_scores", "indicators_daily", "daily_prices"),
    )
    try:
        with engine.connect() as conn:
            # Resolve min_date by most recent distinct daily_scores dates unless user fixes it.
            if not min_date:
                dates = [
                    r[0]
                    for r in conn.execute(text(
                        """
                        SELECT DISTINCT date
                        FROM daily_scores
                        WHERE fwd_5d IS NOT NULL OR fwd_10d IS NOT NULL OR fwd_20d IS NOT NULL
                        ORDER BY date DESC
                        LIMIT :n
                        """
                    ), {"n": lookback_dates}).fetchall()
                ]
                if not dates:
                    return {}
                min_date = min(dates)

            requested_min_date = min_date
            # One prior actual trading day is enough to tell whether a setup on
            # the report boundary continues an earlier episode. A NULL-only price
            # date is not a trading bar for this purpose.
            warmup_date = conn.execute(text("""
                SELECT MAX(date) FROM daily_prices
                WHERE date < :min_date AND close IS NOT NULL
            """), {"min_date": requested_min_date}).scalar()
            query_start = warmup_date or requested_min_date

            rows = conn.execute(text(
                """
                SELECT
                    ds.stock_id,
                    ds.date,
                    ds.fwd_5d,
                    ds.fwd_10d,
                    ds.fwd_20d,
                    ds.reasons AS ds_reasons,
                    ti.reasons AS ti_reasons
                FROM daily_scores ds
                LEFT JOIN indicators_daily ti
                  ON ti.stock_id = ds.stock_id AND ti.date = ds.date
                WHERE ds.date >= :query_start
                  AND (
                    ds.fwd_5d IS NOT NULL OR ds.fwd_10d IS NOT NULL OR ds.fwd_20d IS NOT NULL
                    OR ds.date = :warmup_date
                  )
                ORDER BY ds.date DESC, ds.stock_id
                """
            ), {"query_start": query_start, "warmup_date": warmup_date}).fetchall()

        events_by_code: dict[str, list[StrategyEvent]] = {}
        event_dates = [r[1] for r in rows]
        # Episode continuity must follow the complete price calendar, not merely
        # dates that happen to have matured fwd returns/daily_scores rows.
        if event_dates:
            with engine.connect() as conn:
                trading_dates = [r[0] for r in conn.execute(text("""
                    SELECT DISTINCT date FROM daily_prices
                    WHERE date >= :start AND date <= :end AND close IS NOT NULL
                    ORDER BY date
                """), {"start": min(event_dates), "end": max(event_dates)}).fetchall()]
        else:
            trading_dates = []
    finally:
        engine.dispose()
    for r in rows:
        _sid, date, fwd5, fwd10, fwd20, ds_reasons, ti_reasons = r
        ds_items = _parse_reasons(ds_reasons)
        ti_items = _parse_reasons(ti_reasons)

        codes: set[str] = set()
        codes.update(extract_strategy_codes(ds_items))
        codes.update(extract_strategy_codes(ti_items))
        if not codes:
            continue

        ev = StrategyEvent(
            date=date, fwd_5d=fwd5, fwd_10d=fwd10, fwd_20d=fwd20, stock_id=_sid,
        )
        for c in codes:
            events_by_code.setdefault(c, []).append(ev)

    if "S4_COMPRESSION_SETUP_V2" in events_by_code:
        events_by_code["S4_COMPRESSION_SETUP_V2"] = dedupe_setup_episodes(
            events_by_code["S4_COMPRESSION_SETUP_V2"], trading_dates=trading_dates,
        )

    # Warm-up events only establish continuity; no strategy's performance
    # window may expand to include a pre-min_date row.
    for code, events in events_by_code.items():
        events_by_code[code] = [event for event in events if event.date >= requested_min_date]

    return events_by_code


def build_phase3_strategy_performance_report(
    *,
    date_from: str | None = None,
    lookback_dates: int = 180,
    recent_events: int = 50,
    out: str | None = None,
) -> dict[str, Any]:
    """Compute + write markdown report for Phase 3."""
    tz = ZoneInfo(config.TZ)
    now = datetime.now(tz).isoformat(timespec="seconds")
    min_date = _norm_date_arg(date_from)
    if out is None:
        tag = (min_date or "latest").replace("-", "")
        out_path = Path(config.ROOT) / "docs" / "reports" / f"phase3_strategy_performance_{tag}.md"
    else:
        out_path = Path(out)
    out_path = safe_report_output_path(
        out_path, report_name="phase3 strategy performance report",
    )

    events_by_code = fetch_strategy_events(
        min_date=min_date,
        lookback_dates=lookback_dates,
    )
    perf = compute_strategy_performance_from_events(
        events_by_code,
        recent_events=recent_events,
    )

    lines: list[str] = []
    lines.append("# Phase 3 策略績效閉環（每策略客觀報表）")
    lines.append("")
    lines.append(f"- 產生時間: `{now}`")
    lines.append(f"- min_date: `{min_date or 'latest-lookback'}`")
    lines.append(f"- lookback_dates: `{lookback_dates}`（取最近 N 個有 fwd returns 的交易日）")
    lines.append(f"- recent_events: `{recent_events}`（每策略最近 N 個成熟事件, 僅用 20d）")
    lines.append("")
    lines.append("## 計算定義")
    lines.append("- samples(h): `fwd_{h}d` 不為 null 的事件數")
    lines.append("- win_rate(h): `fwd_{h}d > 0` 的事件占比")
    lines.append("- avg/median: `fwd_{h}d` 的平均/中位數（單位: 百分比回報）")
    lines.append("")

    lines.append("## 結果（依 samples_20d 由大到小）")
    lines.append("")
    # Build sorted table.
    def _samples20(code: str) -> int:
        return int(perf.get(code, {}).get("per_horizon", {}).get("h20", {}).get("samples") or 0)

    sorted_codes = sorted(perf.keys(), key=lambda c: _samples20(c), reverse=True)
    header = (
        "| code | label | "
        "N5 | WR5 | Avg5 | Med5 | "
        "N10 | WR10 | Avg10 | Med10 | "
        "N20 | WR20 | Avg20 | Med20 | "
        "Recent20(N) | Recent20(WR) | Recent20(Avg) |"
    )
    lines.append(header)
    lines.append(
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    )

    for code in sorted_codes:
        p = perf[code]
        label = p.get("label", code)
        h = p["per_horizon"]
        h5 = h["h5"]
        h10 = h["h10"]
        h20 = h["h20"]
        r20 = p["recent20"]

        def fmt_wr(x: float | None) -> str:
            return "-" if x is None else f"{x:.1f}%"

        def fmt_ret(x: float | None) -> str:
            return "-" if x is None else f"{x:.2f}%"

        lines.append(
            "| "
            f"{code} | {label} | "
            f"{int(h5['samples'])} | {fmt_wr(h5['win_rate'])} | {fmt_ret(h5['avg_ret'])} | {fmt_ret(h5['median_ret'])} | "
            f"{int(h10['samples'])} | {fmt_wr(h10['win_rate'])} | {fmt_ret(h10['avg_ret'])} | {fmt_ret(h10['median_ret'])} | "
            f"{int(h20['samples'])} | {fmt_wr(h20['win_rate'])} | {fmt_ret(h20['avg_ret'])} | {fmt_ret(h20['median_ret'])} | "
            f"{int(r20['samples'])} | {fmt_wr(r20['win_rate'])} | {fmt_ret(r20['avg_ret'])} |"
        )

    lines.append("")
    lines.append(f"（共 {sum(int(perf[c]['per_horizon']['h20']['samples']) for c in perf)} 個 matured 20d 樣本分布在各策略上）")

    report = "\n".join(lines) + "\n"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")

    # Light info for CLI output.
    total_events = sum(len(v) for v in events_by_code.values()) if events_by_code else 0
    return {
        "out": str(out_path),
        "min_date": min_date,
        "date_from": date_from,
        "codes": len(perf),
        "events": total_events,
        "recent_events": recent_events,
        "lookback_dates": lookback_dates,
    }


def _cli_float_or_none(v: str | None) -> float | None:
    if v is None:
        return None
    if v == "":
        return None
    return float(v)
