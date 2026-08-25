"""Shared display window for margin history and TDCC holder tabs (docs/34 §3.2 / §5.5)."""
from __future__ import annotations

from datetime import date, timedelta

# Calendar approximation of「6 個月」; B1 TDCC reuses same helper.
SIX_MONTHS_DAYS = 183


def display_window_bounds(
    today: date,
    *,
    months_days: int = SIX_MONTHS_DAYS,
) -> tuple[str, str]:
    """Return (display_from, display_to) as ISO dates.

    display_from = min(當年-01-01, today − 6 個月) — 當年內看滿 YTD；跨年初約 6 月
    display_to   = today (caller may clamp per-series latest as_of)
    """
    year_start = date(today.year, 1, 1)
    six_m_ago = today - timedelta(days=months_days)
    display_from = min(year_start, six_m_ago)
    return display_from.isoformat(), today.isoformat()


def window_label(display_from: str, display_to: str, today: date) -> str:
    """Human label: 當年度 vs 跨年度近 6 月."""
    if display_from.startswith(f"{today.year}-01-01"):
        return "當年度"
    return "跨年度·近 6 月"
