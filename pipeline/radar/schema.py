"""Table definitions (SQLAlchemy Core). Dates stored as ISO text 'YYYY-MM-DD'.

Volumes: daily_prices.volume in shares(股); margin tables in lots(張, 交易單位).
"""
from sqlalchemy import (
    Column,
    Float,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
)

metadata = MetaData()

stocks = Table(
    "stocks",
    metadata,
    Column("id", Text, primary_key=True),          # 證券代號
    Column("name", Text, nullable=False),
    Column("market", Text, nullable=False),        # twse / tpex
    Column("type", Text, nullable=False),          # stock / etf / etn / other
    Column("industry", Text),
    Column("is_active", Integer, nullable=False, default=1),
)

warrants = Table(
    "warrants",
    metadata,
    Column("id", Text, primary_key=True),          # 權證代號
    Column("name", Text, nullable=False),
    Column("market", Text, nullable=False),
    Column("kind", Text, nullable=False),          # call / put / bull / bear / bull_ext / bear_ext
    Column("stock_id", Text),                      # underlying, filled by warrant-master import (TODO)
    Column("strike", Float),
    Column("exercise_ratio", Float),
    Column("maturity_date", Text),
    Column("issuer", Text),
)

daily_prices = Table(
    "daily_prices",
    metadata,
    Column("stock_id", Text, primary_key=True),
    Column("date", Text, primary_key=True),
    Column("open", Float),
    Column("high", Float),
    Column("low", Float),
    Column("close", Float),
    Column("volume", Integer),                     # 股
    Column("turnover", Integer),                   # 元
    Column("transactions", Integer),
    Index("ix_daily_prices_date", "date"),
)

warrant_daily = Table(
    "warrant_daily",
    metadata,
    Column("warrant_id", Text, primary_key=True),
    Column("date", Text, primary_key=True),
    Column("close", Float),
    Column("volume", Integer),
    Column("turnover", Integer),
    Column("transactions", Integer),
    Index("ix_warrant_daily_date", "date"),
)

warrant_stock_daily = Table(
    "warrant_stock_daily",
    metadata,
    Column("stock_id", Text, primary_key=True),
    Column("date", Text, primary_key=True),
    Column("call_turnover", Integer),              # 認購成交金額(元),排除牛熊證
    Column("call_volume", Integer),
    Column("call_count", Integer),                 # 有成交的認購檔數
    Column("put_turnover", Integer),
    Column("put_volume", Integer),
    Column("put_count", Integer),
    Index("ix_warrant_stock_daily_date", "date"),
)

daily_institutional = Table(
    "daily_institutional",
    metadata,
    Column("stock_id", Text, primary_key=True),
    Column("date", Text, primary_key=True),
    Column("foreign_net", Integer),                # 外資合計買賣超(股)
    Column("trust_net", Integer),                  # 投信
    Column("dealer_net", Integer),                 # 自營合計
    Column("total_net", Integer),                  # 三大法人合計
    Index("ix_daily_institutional_date", "date"),
)

daily_margins = Table(
    "daily_margins",
    metadata,
    Column("stock_id", Text, primary_key=True),
    Column("date", Text, primary_key=True),
    Column("margin_balance", Integer),             # 融資今日餘額(張)
    Column("margin_prev", Integer),                # 融資前日餘額(張)
    Column("margin_limit", Integer),               # 融資限額(張)
    Column("short_balance", Integer),              # 融券今日餘額(張)
    Column("short_prev", Integer),
    Index("ix_daily_margins_date", "date"),
)

import_logs = Table(
    "import_logs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_at", Text, nullable=False),        # ISO datetime (Asia/Taipei)
    Column("source", Text, nullable=False),        # twse / tpex
    Column("dataset", Text, nullable=False),       # quotes / insti / margin / ...
    Column("date", Text, nullable=False),          # data date
    Column("rows", Integer, nullable=False, default=0),
    Column("status", Text, nullable=False),        # ok / empty / error
    Column("error", Text),
    Column("duration_ms", Integer),
)
