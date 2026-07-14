"""Table definitions (SQLAlchemy Core). Dates stored as ISO text 'YYYY-MM-DD'.

Volumes: daily_prices.volume in shares(股); margin tables in lots(張, 交易單位).
"""
from sqlalchemy import (
    Boolean,
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
    Column("description", Text),                   # 公司主要業務說明/營收比重
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
    Column("adj_factor", Float, nullable=False, server_default="1.0"),
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

indicators_daily = Table(
    "indicators_daily",
    metadata,
    Column("stock_id", Text, primary_key=True),
    Column("date", Text, primary_key=True),
    Column("ma5", Float),
    Column("ma10", Float),
    Column("ma20", Float),
    Column("ma60", Float),
    Column("rsi14", Float),
    Column("k9", Float),
    Column("d9", Float),
    Column("macd", Float),
    Column("macd_signal", Float),
    Column("macd_hist", Float),
    Column("high20", Float),
    Column("box_high60", Float),
    Column("box_low60", Float),
    Column("adv20", Float),
    Column("volume_ratio", Float),
    Column("tech_score", Integer),
    Column("reasons", Text),
    Column("risks", Text),
    Index("ix_indicators_daily_date", "date"),
)

themes = Table(
    "themes",
    metadata,
    Column("id", Text, primary_key=True),          # 來源分類代碼,例 C023322
    Column("name", Text, nullable=False),          # 例:矽晶圓
    Column("source", Text, nullable=False, server_default="fubon"),
    Column("updated_at", Text),
)

stock_themes = Table(
    "stock_themes",
    metadata,
    Column("theme_id", Text, primary_key=True),
    Column("stock_id", Text, primary_key=True),
    Index("ix_stock_themes_stock", "stock_id"),
)

branch_dim = Table(
    "branch_dim",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("branch_key", Text, nullable=False, unique=True),
    Column("broker_id", Text),
    Column("branch_name", Text, nullable=False)
)

branch_trades_raw = Table(
    "branch_trades_raw",
    metadata,
    Column("stock_id", Text, primary_key=True),
    Column("date", Text, primary_key=True),
    Column("branch_id", Integer, primary_key=True),
    Column("buy_lots", Integer),
    Column("sell_lots", Integer),
    Column("net_lots", Integer),
    Column("pct", Float),
    Column("source", Text, nullable=False, server_default="fubon"),
    Index("ix_branch_trades_raw_date", "date"),
    Index("ix_branch_trades_raw_branch", "branch_id", "date"),
)

daily_scores = Table(
    "daily_scores",
    metadata,
    Column("stock_id", Text, primary_key=True),
    Column("date", Text, primary_key=True),
    Column("branch_score", Integer),               # 分點籌碼分,無分點資料則 NULL
    Column("warrant_score", Integer),              # 0-100,無權證資料則 NULL
    Column("tech_score", Integer),
    Column("inst_score", Integer),                 # 法人+融資
    Column("theme_score", Integer),                # 題材(未實作,NULL → 權重重分配)
    Column("risk_penalty", Integer),               # 0 ~ -40
    Column("final", Integer, nullable=False),      # clamp(加權 + 扣分, 0, 100)
    Column("reasons", Text),                       # JSON [{code,points,text,value}]
    Column("risks", Text),                         # JSON [{code,points,text,value}]
    Column("entry_date", Text),                    # 次一交易日(進場基準)
    Column("entry_price", Float),                  # 次一交易日開盤價
    Column("fwd_1d", Float),                       # entry日起第1/3/5/10/20個交易日收盤報酬%
    Column("fwd_3d", Float),
    Column("fwd_5d", Float),
    Column("fwd_10d", Float),
    Column("fwd_20d", Float),
    Column("fwd_updated_at", Text),
    Column("watch_price", Float),                  # 觀察價 = max(今日高點, 箱型上緣) x 1.005
    Column("stop_price", Float),                   # 失效價 = min(5日線, 今日低點)
    Column("buy_concentration", Float),            # 前5大買超分點佔今日成交量比
    Column("concentration_avg20", Float),          # 上述比值近20日均(不含當日)
    Index("ix_daily_scores_date", "date"),
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

tracked_branches = Table(
    "tracked_branches",
    metadata,
    Column("branch_name", Text, primary_key=True),
    Column("source", Text, nullable=False), # manual, auto
    Column("note", Text),
    Column("added_at", Text)
)

branch_stock_stats = Table(
    "branch_stock_stats",
    metadata,
    Column("branch_name", Text, primary_key=True),
    Column("stock_id", Text, primary_key=True),
    Column("events_count", Integer),
    Column("win_rate", Float),
    Column("avg_ret5", Float),
    Column("is_daytrade_suspect", Boolean),
    Column("last_active_date", Text),
    Column("updated_at", Text)
)

branch_rankings = Table(
    "branch_rankings",
    metadata,
    Column("branch_name", Text, primary_key=True),
    Column("as_of", Text, primary_key=True),
    Column("rank_score", Float),
    Column("win_rate", Float),
    Column("avg_ret5", Float),
    Column("samples", Integer),
    Column("style", Text), # swing, short, daytrade
    Column("is_daytrade", Boolean),
    Column("source", Text)
)
