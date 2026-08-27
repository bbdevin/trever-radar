"""唯讀的 branch × stock point-in-time shadow 報表。

本模組刻意不呼叫 ``init_db()``：它只讀既有資料庫，既不建表、不 migration，
也不更新任何業務資料。這份報表是 E2 的稽核工具，不是排行或交易績效功能。
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from .. import config


QUAL_PCT = 1.0
PRICE_WINDOW_DAYS = 20
FORWARD_CLOSE_DAY = 5


def _sqlite_db_path() -> Path:
    """Resolve the configured physical SQLite file without creating anything."""
    url = make_url(config.DB_URL)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise ValueError("branch point-in-time report requires a physical SQLite DB_URL")
    db_path = Path(url.database).expanduser().resolve()
    if not db_path.is_file():
        raise FileNotFoundError(f"configured SQLite database does not exist: {db_path}")
    return db_path


def get_read_only_engine() -> Engine:
    """Return a dedicated SQLite URI ``mode=ro`` engine for this report only."""
    db_path = _sqlite_db_path()
    db_uri = db_path.as_uri() + "?mode=ro"
    return create_engine(
        "sqlite+pysqlite://",
        creator=lambda: sqlite3.connect(db_uri, uri=True, check_same_thread=False),
    )


def _safe_output_path(out: str | Path) -> Path:
    """Reject overwriting the database before any report query is attempted."""
    db_path = _sqlite_db_path()
    out_path = Path(out).expanduser().resolve()
    if out_path == db_path:
        raise ValueError("report --out must not be the configured SQLite database path")
    return out_path


def _validate_date(value: str, name: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be YYYY-MM-DD: {value!r}") from exc


def validate_report_window(*, as_of: str, date_from: str, date_to: str) -> tuple[str, str, str]:
    """Validate the inclusive window; the report must never inspect future dates."""
    as_of = _validate_date(as_of, "as_of")
    date_from = _validate_date(date_from, "from")
    date_to = _validate_date(date_to, "to")
    if date_from > date_to:
        raise ValueError("from must be on or before to")
    if date_to > as_of:
        raise ValueError("to must be on or before as_of")
    return as_of, date_from, date_to


def _rate(numerator: int, denominator: int) -> float | None:
    return round(100.0 * numerator / denominator, 6) if denominator else None


def _mean(values: list[float]) -> float | None:
    return round(mean(values), 6) if values else None


def _true_count(episodes: list[dict[str, Any]], field: str) -> int:
    """Count affirmative evidence only; ``None`` is unknown, never false."""
    return sum(episode[field] is True for episode in episodes)


def _episode_runs(dates: list[str], market_index: dict[str, int]) -> list[tuple[str, str, list[str]]]:
    """Merge only adjacent *market* trading days, never adjacent calendar days."""
    out: list[tuple[str, str, list[str]]] = []
    current: list[str] = []
    previous_index: int | None = None
    for event_date in sorted(set(dates)):
        index = market_index.get(event_date)
        if index is None or previous_index is None or index != previous_index + 1:
            if current:
                out.append((current[0], current[-1], current))
            current = [event_date]
        else:
            current.append(event_date)
        previous_index = index
    if current:
        out.append((current[0], current[-1], current))
    return out


def _price_observation(
    *,
    event_date: str,
    price_rows: list[dict[str, Any]],
    market_index: dict[str, int],
) -> dict[str, Any]:
    """Return event-day percentile and a descriptive forward five-day observation.

    The event price is the unadjusted daily close, which is available after that
    trading session.  The percentile window contains only the event day and the
    preceding 19 market days.  No future price chooses an event or percentile.
    """
    row_by_date = {row["date"]: row for row in price_rows}
    market_days = sorted(market_index, key=market_index.get)
    event_index = market_index.get(event_date)
    event_row = row_by_date.get(event_date)
    result: dict[str, Any] = {
        "event_price": None,
        "price_percentile_20d": None,
        "price_percentile_status": "unknown",
        "price_percentile_reason": None,
        "fwd5_pct": None,
        "fwd5_status": "unknown",
        "fwd5_reason": None,
        "entry_open_date": None,
        "exit_close_date": None,
    }
    if event_index is None:
        result["price_percentile_reason"] = "event_not_in_market_calendar"
        result["fwd5_reason"] = "event_not_in_market_calendar"
        return result
    if event_row is None or event_row["close"] is None:
        result["price_percentile_reason"] = "missing_event_close"
    else:
        result["event_price"] = event_row["close"]
        start = event_index - (PRICE_WINDOW_DAYS - 1)
        if start < 0:
            result["price_percentile_reason"] = "insufficient_prior_market_days"
        else:
            window_days = market_days[start:event_index + 1]
            closes = [row_by_date.get(day, {}).get("close") for day in window_days]
            if any(value is None for value in closes):
                result["price_percentile_reason"] = "missing_close_in_20d_window"
            else:
                low, high = min(closes), max(closes)
                if high == low:
                    result["price_percentile_reason"] = "zero_price_range"
                else:
                    result["price_percentile_20d"] = round((event_row["close"] - low) / (high - low), 6)
                    result["price_percentile_status"] = "known"

    entry_index = event_index + 1
    exit_index = event_index + FORWARD_CLOSE_DAY
    if exit_index >= len(market_days):
        result["fwd5_reason"] = "insufficient_mature_market_window"
        return result
    entry_date, exit_date = market_days[entry_index], market_days[exit_index]
    entry_open = row_by_date.get(entry_date, {}).get("open")
    exit_close = row_by_date.get(exit_date, {}).get("close")
    result["entry_open_date"] = entry_date
    result["exit_close_date"] = exit_date
    if entry_open is None or entry_open <= 0:
        result["fwd5_reason"] = "missing_or_nonpositive_entry_open"
    elif exit_close is None:
        result["fwd5_reason"] = "missing_exit_close"
    else:
        result["fwd5_pct"] = round((exit_close / entry_open - 1.0) * 100.0, 6)
        result["fwd5_status"] = "matured"
    return result


def _build_universe(conn, as_of: str) -> tuple[dict[str, set[str]], list[str]]:
    """Manual tracked branches plus names identifiable in snapshots at ``as_of``."""
    sources: dict[str, set[str]] = defaultdict(set)
    for branch_name, _added_at in conn.execute(text("""
        SELECT branch_name, added_at
        FROM tracked_branches
        WHERE source = 'manual'
          AND added_at IS NOT NULL
          AND substr(added_at, 1, 10) <= :as_of
    """), {"as_of": as_of}).fetchall():
        sources[branch_name].add("manual_tracked")
    unknown_manual_timestamp_names = [row[0] for row in conn.execute(text("""
        SELECT branch_name
        FROM tracked_branches
        WHERE source = 'manual' AND added_at IS NULL
        ORDER BY branch_name
    """)).fetchall()]
    for (branch_name,) in conn.execute(text("""
        SELECT DISTINCT branch_name
        FROM branch_rankings
        WHERE as_of <= :as_of
    """), {"as_of": as_of}).fetchall():
        sources[branch_name].add("ranking_identifiable")
    return sources, unknown_manual_timestamp_names


def build_branch_point_in_time_report(
    *, as_of: str, date_from: str, date_to: str,
) -> dict[str, Any]:
    """Build E2's deterministic, JSON-serialisable, read-only report."""
    as_of, date_from, date_to = validate_report_window(
        as_of=as_of, date_from=date_from, date_to=date_to,
    )
    engine = get_read_only_engine()
    try:
        with engine.connect() as conn:
            universe, unknown_manual_timestamp_names = _build_universe(conn, as_of)
            market_days = [row[0] for row in conn.execute(text("""
            SELECT DISTINCT date
            FROM daily_prices
            WHERE date <= :as_of
            ORDER BY date
        """), {"as_of": as_of}).fetchall()]
            market_index = {day: index for index, day in enumerate(market_days)}
            raw_rows = conn.execute(text("""
            SELECT b.branch_name, b.stock_id, s.name, b.date, b.net_lots, b.pct
            FROM branch_trades b
            JOIN stocks s ON s.id = b.stock_id
            WHERE s.type = 'stock'
              AND b.date >= :date_from
              AND b.date <= :date_to
              AND b.date <= :as_of
            ORDER BY b.branch_name, b.stock_id, b.date
        """), {
            "as_of": as_of, "date_from": date_from, "date_to": date_to,
            }).mappings().all()

            rows_by_pair: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
            stock_names: dict[str, str] = {}
            missing_pct_rows = 0
            for row in raw_rows:
                branch_name = row["branch_name"]
                if branch_name not in universe:
                    continue
                row = dict(row)
                rows_by_pair[(branch_name, row["stock_id"])].append(row)
                stock_names[row["stock_id"]] = row["name"]
                if row["pct"] is None:
                    missing_pct_rows += 1

            stock_ids = sorted(stock_names)
            price_rows_by_stock: dict[str, list[dict[str, Any]]] = defaultdict(list)
            # Keep parameter lists below SQLite's practical limits while avoiding
            # string interpolation; each statement remains a SELECT.
            for offset in range(0, len(stock_ids), 500):
                chunk = stock_ids[offset:offset + 500]
                if not chunk:
                    continue
                placeholders = ", ".join(f":stock_{i}" for i in range(len(chunk)))
                params = {"as_of": as_of, **{f"stock_{i}": sid for i, sid in enumerate(chunk)}}
                price_rows = conn.execute(text(f"""
                SELECT stock_id, date, open, close
                FROM daily_prices
                WHERE date <= :as_of AND stock_id IN ({placeholders})
                ORDER BY stock_id, date
            """), params).mappings().all()
                for price_row in price_rows:
                    price_rows_by_stock[price_row["stock_id"]].append(dict(price_row))
    finally:
        engine.dispose()

    episodes: list[dict[str, Any]] = []
    report_rows: list[dict[str, Any]] = []
    for (branch_name, stock_id), trade_rows in sorted(rows_by_pair.items()):
        by_direction: dict[str, list[str]] = {"buy": [], "sell": []}
        for row in trade_rows:
            net_lots, pct = row["net_lots"], row["pct"]
            if net_lots is None or pct is None:
                continue
            if net_lots > 0 and pct >= QUAL_PCT:
                by_direction["buy"].append(row["date"])
            elif net_lots < 0 and abs(pct) >= QUAL_PCT:
                by_direction["sell"].append(row["date"])

        pair_episodes: list[dict[str, Any]] = []
        for direction in ("buy", "sell"):
            for start_date, end_date, episode_dates in _episode_runs(by_direction[direction], market_index):
                observation = _price_observation(
                    event_date=start_date,
                    price_rows=price_rows_by_stock[stock_id],
                    market_index=market_index,
                )
                percentile = observation["price_percentile_20d"]
                episode = {
                    "branch_name": branch_name,
                    "stock_id": stock_id,
                    "stock_name": stock_names[stock_id],
                    "direction": direction,
                    "start_date": start_date,
                    "end_date": end_date,
                    "trading_day_count": len(episode_dates),
                    **observation,
                    "low_buy": (
                        percentile <= 0.40
                        if direction == "buy" and observation["price_percentile_status"] == "known"
                        else None
                    ),
                    "high_sell": (
                        percentile >= 0.60
                        if direction == "sell" and observation["price_percentile_status"] == "known"
                        else None
                    ),
                }
                pair_episodes.append(episode)
                episodes.append(episode)

        buys = [episode for episode in pair_episodes if episode["direction"] == "buy"]
        sells = [episode for episode in pair_episodes if episode["direction"] == "sell"]
        known_buys = [episode for episode in buys if episode["price_percentile_status"] == "known"]
        known_sells = [episode for episode in sells if episode["price_percentile_status"] == "known"]
        matured_buys = [episode for episode in buys if episode["fwd5_status"] == "matured"]
        fwd_values = [episode["fwd5_pct"] for episode in matured_buys]
        # This is deliberately an availability label, not a statistical or
        # product-launch threshold.  Consumers must inspect the counts.
        evidence_status = "evidence" if known_buys and known_sells else "insufficient"
        report_rows.append({
            "branch_name": branch_name,
            "stock_id": stock_id,
            "stock_name": stock_names[stock_id],
            "universe_sources": sorted(universe[branch_name]),
            "observed_trade_rows": len(trade_rows),
            "buy_episode_count": len(buys),
            "sell_episode_count": len(sells),
            "buy_price_percentile_known": len(known_buys),
            "buy_price_percentile_unknown": len(buys) - len(known_buys),
            "sell_price_percentile_known": len(known_sells),
            "sell_price_percentile_unknown": len(sells) - len(known_sells),
            "low_buy_count": _true_count(known_buys, "low_buy"),
            "low_buy_rate": _rate(_true_count(known_buys, "low_buy"), len(known_buys)),
            "high_sell_count": _true_count(known_sells, "high_sell"),
            "high_sell_rate": _rate(_true_count(known_sells, "high_sell"), len(known_sells)),
            "fwd5_matured_buy_episodes": len(matured_buys),
            "fwd5_unknown_buy_episodes": len(buys) - len(matured_buys),
            "fwd5_positive_rate": _rate(sum(value > 0 for value in fwd_values), len(fwd_values)),
            "fwd5_avg_pct": _mean(fwd_values),
            "low_buy_high_sell_status": evidence_status,
        })

    episodes.sort(key=lambda item: (item["branch_name"], item["stock_id"], item["direction"], item["start_date"]))
    report_rows.sort(key=lambda item: (item["branch_name"], item["stock_id"]))
    buy_episodes = [episode for episode in episodes if episode["direction"] == "buy"]
    sell_episodes = [episode for episode in episodes if episode["direction"] == "sell"]
    known_buys = [episode for episode in buy_episodes if episode["price_percentile_status"] == "known"]
    known_sells = [episode for episode in sell_episodes if episode["price_percentile_status"] == "known"]
    matured_buys = [episode for episode in buy_episodes if episode["fwd5_status"] == "matured"]
    fwd_values = [episode["fwd5_pct"] for episode in matured_buys]
    source_counts = {
        "manual_tracked": sum("manual_tracked" in sources for sources in universe.values()),
        "ranking_identifiable": sum("ranking_identifiable" in sources for sources in universe.values()),
    }

    return {
        "metadata": {
            "report": "branch_point_in_time_shadow",
            "as_of": as_of,
            "from": date_from,
            "to": date_to,
            "read_only": True,
            "schema_changes": False,
            "ranking_or_score_changes": False,
        },
        "definitions": {
            "universe": "manual tracked branches available at as_of plus branches identifiable in branch_rankings snapshots at or before as_of",
            "event": "buy: net_lots > 0 and pct >= 1%; sell: net_lots < 0 and abs(pct) >= 1%; same branch-stock-direction adjacent market trading days are one episode",
            "event_price": "unadjusted event-day daily close, available after that market session",
            "price_percentile_20d": "(event close - min close) / (max close - min close) using exactly the event day and preceding 19 market trading days; missing/zero-range/short windows are unknown",
            "low_buy": "buy episode with known 20-day price percentile <= 0.40",
            "high_sell": "sell episode with known 20-day price percentile >= 0.60",
            "fwd5_observation": "descriptive only: (fifth subsequent market-day close / next market-day open - 1) * 100; incomplete price windows are unknown, not zero",
            "low_buy_high_sell_status": "evidence means at least one known buy percentile and one known sell percentile for that branch-stock row; it is not a launch, ranking, or statistical-sufficiency threshold",
        },
        "coverage": {
            "universe_branch_count": len(universe),
            "universe_source_counts": source_counts,
            "manual_tracked_unknown_timestamp_count": len(unknown_manual_timestamp_names),
            "manual_tracked_unknown_timestamp_names": unknown_manual_timestamp_names,
            "market_trading_days_through_as_of": len(market_days),
            "market_trading_days_in_requested_window": sum(date_from <= day <= date_to for day in market_days),
            "observed_branch_stock_rows": len(report_rows),
            "observed_branch_trade_rows": sum(len(rows) for rows in rows_by_pair.values()),
            "trade_rows_missing_pct": missing_pct_rows,
            "branch_trade_capture_note": "branch_trades is a retrieved top-15 buy/sell slice. Missing a row, including a sell row, means not observed in this data slice; it must not be interpreted as no sell or no trade.",
        },
        "summary": {
            "buy_episode_count": len(buy_episodes),
            "sell_episode_count": len(sell_episodes),
            "buy_price_percentile_known": len(known_buys),
            "buy_price_percentile_unknown": len(buy_episodes) - len(known_buys),
            "sell_price_percentile_known": len(known_sells),
            "sell_price_percentile_unknown": len(sell_episodes) - len(known_sells),
            "low_buy_count": _true_count(known_buys, "low_buy"),
            "low_buy_rate": _rate(_true_count(known_buys, "low_buy"), len(known_buys)),
            "high_sell_count": _true_count(known_sells, "high_sell"),
            "high_sell_rate": _rate(_true_count(known_sells, "high_sell"), len(known_sells)),
            "fwd5_matured_buy_episodes": len(matured_buys),
            "fwd5_unknown_buy_episodes": len(buy_episodes) - len(matured_buys),
            "fwd5_positive_rate": _rate(sum(value > 0 for value in fwd_values), len(fwd_values)),
            "fwd5_avg_pct": _mean(fwd_values),
            "fwd5_matured_denominator": len(fwd_values),
            "fwd5_note": "後續表現的描述性觀察；不是分點實際獲利、持倉成本或勝率。",
        },
        "branch_stock_rows": report_rows,
        "episode_samples": episodes,
    }


def write_branch_point_in_time_report(
    *, as_of: str, date_from: str, date_to: str, out: str | Path,
) -> dict[str, Any]:
    """Build and deterministically write the standalone JSON report."""
    out_path = _safe_output_path(out)
    report = build_branch_point_in_time_report(
        as_of=as_of, date_from=date_from, date_to=date_to,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report
