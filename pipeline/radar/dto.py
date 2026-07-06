from dataclasses import dataclass


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
    short_balance: int | None
    short_prev: int | None
