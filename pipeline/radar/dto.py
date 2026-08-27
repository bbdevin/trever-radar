from dataclasses import dataclass
from hashlib import sha256


@dataclass(slots=True)
class Quote:
    code: str
    name: str
    market: str                 # twse / tpex
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int | None          # 股
    turnover: int | None        # 元
    transactions: int | None


@dataclass(slots=True)
class InstiRow:
    code: str
    foreign_net: int
    trust_net: int
    dealer_net: int
    total_net: int


@dataclass(slots=True)
class MarginRow:
    code: str
    margin_balance: int | None  # 張
    margin_prev: int | None
    margin_limit: int | None
    margin_buy: int | None = None
    margin_sell: int | None = None
    margin_repay: int | None = None
    short_balance: int | None = None
    short_prev: int | None = None
    short_buy: int | None = None
    short_sell: int | None = None
    short_repay: int | None = None


@dataclass(slots=True)
class BuybackRow:
    """One MOPS t35sc09 buyback plan.  Shares are 股; amounts are 元."""

    stock_id: str
    name: str
    market: str                    # twse / tpex
    board_date: str | None
    purpose: str | None
    total_amount_limit: int | None
    planned_shares: int | None
    price_min: float | None
    price_max: float | None
    start_date: str | None
    end_date: str | None
    completed_flag: str | None     # MOPS raw Y / N; unknown values stay raw
    executed_shares: int | None
    transferred_shares: int | None
    execution_pct: float | None    # percentage points, not a 0–1 ratio
    executed_amount: int | None
    avg_price: float | None
    share_ratio_pct: float | None  # percentage points, not a 0–1 ratio
    incomplete_reason: str | None
    report_date: str | None
    source_updated_at: str | None

    @property
    def plan_id(self) -> str:
        """Stable identity that permits more than one plan for the same stock."""
        parts = (
            self.market, self.stock_id, self.board_date, self.start_date,
            self.end_date, self.planned_shares, self.price_min, self.price_max,
            self.purpose,
        )
        return sha256("\x1f".join("" if value is None else str(value) for value in parts).encode()).hexdigest()
