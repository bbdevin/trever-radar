"""大戶門檻彙總(docs/34 §4.1)。純函式,供 import 測試與 export 共用。"""
from __future__ import annotations

from typing import Iterable

# 張門檻 → 應累加的 TDCC tier(含)
# 400張=400,000股 → tier12+;600→13+;800→14+;1000→15
THRESHOLD_TIERS: dict[int, tuple[int, ...]] = {
    400: (12, 13, 14, 15),
    600: (13, 14, 15),
    800: (14, 15),
    1000: (15,),
}
THRESHOLDS = (400, 600, 800, 1000)


def aggregate_threshold(
    tiers: dict[int, tuple[int, int, float]],
    threshold_lots: int,
) -> dict[str, float | int]:
    """tiers: tier → (holders, shares, pct). Return holders + shares_pct."""
    want = THRESHOLD_TIERS.get(threshold_lots)
    if not want:
        raise ValueError(f"unsupported threshold: {threshold_lots}")
    holders = 0
    pct = 0.0
    for t in want:
        if t not in tiers:
            continue
        h, _s, p = tiers[t]
        holders += h or 0
        pct += p or 0.0
    return {"holders": holders, "shares_pct": round(pct, 4)}


def aggregate_all_thresholds(
    tier_rows: Iterable[tuple[int, int, int, float]],
) -> dict[str, dict[str, float | int]]:
    """tier_rows: (tier, holders, shares, pct) → {"400": {...}, ...}."""
    tiers: dict[int, tuple[int, int, float]] = {}
    for tier, holders, shares, pct in tier_rows:
        tiers[int(tier)] = (int(holders or 0), int(shares or 0), float(pct or 0.0))
    return {str(th): aggregate_threshold(tiers, th) for th in THRESHOLDS}
