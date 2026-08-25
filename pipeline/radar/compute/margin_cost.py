"""融資成本估算(docs/34 §5.2):官方無公布均價,用買進張數+收盤價遞推。"""


def next_margin_cost(
    prev_cost: float | None,
    buy_lots: int | None,
    balance_lots: int | None,
    close: float | None,
) -> float | None:
    """Single-day margin average cost (元/股, unadjusted close)."""
    if balance_lots is None or balance_lots == 0:
        return None
    buy = buy_lots or 0
    if close is None:
        return prev_cost
    if prev_cost is None:
        return close if buy > 0 else None
    remaining = max(balance_lots - buy, 0)
    return (prev_cost * remaining + close * buy) / balance_lots


def build_margin_cost_series(
    rows: list[tuple[int | None, int | None, float | None]],
) -> list[float | None]:
    """rows: ascending date — (buy_lots, balance_lots, close)."""
    out: list[float | None] = []
    prev: float | None = None
    for buy, bal, close in rows:
        prev = next_margin_cost(prev, buy, bal, close)
        out.append(prev)
    return out
