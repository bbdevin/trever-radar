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
    Column("margin_buy", Integer),                 # 融資買進(張)
    Column("margin_sell", Integer),
    Column("margin_repay", Integer),               # 融資現金償還
    Column("short_balance", Integer),              # 融券今日餘額(張)
    Column("short_prev", Integer),
    Column("short_buy", Integer),
    Column("short_sell", Integer),
    Column("short_repay", Integer),
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
    # lifecycle v1: keep updated_at for legacy readers; new fields are additive.
    Column("source_updated_at", Text),
    Column("data_date", Text),
    Column("status", Text),                 # active / stale / retired; NULL = legacy unknown
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
    Column("is_daytrade_suspect", Boolean),   # NULL = 觀察數不足,未判定
    Column("daytrade_obs", Integer),          # 判定用觀察數(合併連續段之前)
    Column("daytrade_paybacks", Integer),     # 其中次日回吐筆數
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
    Column("samples", Integer),               # 事件數(合併後)
    Column("matured_samples", Integer),       # 其中已成熟(有 5 日前瞻報酬)的事件數 = 勝率分母
    Column("style", Text), # swing, short, daytrade
    Column("is_daytrade", Boolean),           # NULL = 可判定配對不足,未判定
    Column("daytrade_pairs_determined", Integer),   # 可判定的 (分點,個股) 配對數
    Column("daytrade_pairs_flagged", Integer),      # 其中被標記隔日沖的配對數
    Column("source", Text)
)

# docs/37 E2:分點 point-in-time 觀察帳本。每列 = 一個分點在某個 as_of、
# 某個 trailing window 下「當天可觀察到的事實」。
#
# 只存計數,不存比率:同一個 low_buy 比率,各日平均是 75%,pooled 起來卻是
# 66.7%,差別純粹來自分母權重。存了比率就再也還原不回 pooled;存了分子與分母
# 就兩種都算得出來。同理 fwd5_sum_pct 存的是「總和」而不是平均,跨列 pooled
# 平均才會精確。每個分子都附帶它的分母與 unknown 數,單一列即可自我描述。
#
# computed_at 是「資料可得性」的時戳,不是修改時間:branch_trades 仍在
# backfill,同一個過去日期在不同時間重算會得到不同結果。那不是同一個觀察,
# 是另一個觀察;computed_at 是唯一能區分兩者的欄位。
#
# window_market_days 進 primary key,是為了讓日後第二種 window 長度可以並存,
# 而不必改寫既有歷史。
#
# 這張表**永不 prune**(見 prune.py 的註解):一年約 50 MB。
#
# 框架(docs/37 已明確 defer pairing、禁止歸因):buy 與 sell episode 各自
# 獨立計數,不做 buy→sell 配對、不做交易損益歸因、不宣稱勝率。fwd5 只是
# 描述性觀察,不是分點實際獲利或持倉成本。
branch_pit_stats = Table(
    "branch_pit_stats",
    metadata,
    Column("branch_name", Text, primary_key=True),
    Column("as_of", Text, primary_key=True),            # 必須是市場交易日
    Column("window_market_days", Integer, primary_key=True),  # 實際納入的交易日數
    Column("window_from", Text),                        # window 內第一個市場交易日
    Column("definitions_version", Text),                # 'e2-v1';定義改變才 bump
    Column("computed_at", Text),                        # ISO 時戳 = 資料可得性
    Column("observed_trade_rows", Integer),
    Column("stock_count", Integer),                     # window 內有資料列的相異個股數
    Column("buy_episodes", Integer),
    Column("sell_episodes", Integer),
    Column("buy_pctile_known", Integer),
    Column("buy_pctile_unknown", Integer),
    Column("sell_pctile_known", Integer),
    Column("sell_pctile_unknown", Integer),
    Column("low_buy_count", Integer),                   # 分母 = buy_pctile_known
    Column("high_sell_count", Integer),                 # 分母 = sell_pctile_known
    Column("fwd5_matured", Integer),
    Column("fwd5_unknown", Integer),
    Column("fwd5_positive_count", Integer),             # 分母 = fwd5_matured
    Column("fwd5_sum_pct", Float),                      # 總和,不是平均
    Index("ix_branch_pit_stats_as_of", "as_of"),
)

# docs/37 E2 pair 粒度:一個「分點 × 個股」在一段 trailing window 內,
# 買進 episode 有幾次落在 20 日收盤分位的低檔、賣出 episode 有幾次落在高檔。
#
# ⚠️ 讀這張表之前必須知道的兩件事(2026-09-03 唯讀量測,見 docs/STATUS.md):
#   1. **兩側基準率不對稱**:全市場 pooled 低買 53.35%、高賣 35.35%。所以
#      「低買率 60%」在買側幾乎是基準值,在賣側卻是大幅超出。任何一個比率
#      單獨看都沒有意義,必須跟**同一檔股票自己的 pooled 率**比。這就是每列
#      都帶 stock_* 分子與分母的原因——它們是尺,不是裝飾。
#   2. **這個性質不持久**:同一條規則在下一個年度重新標記到同一對的比率只有
#      1.6%–5.4%。傾向(pair 樣本外仍以 2.3–2.9× 勝過自己那檔股票的 null)為真,
#      「總是低買高賣」不成立。因此本表**不存任何布林旗標、不存分數、不排名**,
#      只存計數;要不要相信,由讀的人看著分母自己判斷。請不要把它變成徽章。
#
# 只存最新一份快照:整張表每次重算就被取代,鍵是 (branch_name, stock_id)。
# 約 90 萬列、數十 MB。若改成跨 as_of 的 point-in-time 序列,實測約 140 GB,
# 磁碟放不下——那條路已被否決,這張表刻意不是那個東西。
# 因此本表也**不進 prune.py**:它沒有可刪的歷史,只有一份當下的快照。
#
# 不存比率(同 branch_pit_stats):比率不可還原成 pooled,分子與分母才可以。
# unknown 分位另外計數,永遠不當成「沒做到」。
#
# 全部是**進出場價格分位**,不是損益:docs/37 禁止買賣配對與獲利歸因,
# 因此買方與賣方 episode 各自獨立計數,沒有任何欄位是勝率或報酬。
branch_stock_pctile_counts = Table(
    "branch_stock_pctile_counts",
    metadata,
    Column("branch_name", Text, primary_key=True),
    Column("stock_id", Text, primary_key=True),
    Column("as_of", Text),                        # 市場交易日
    Column("window_market_days", Integer),        # 實際納入的交易日數
    Column("window_from", Text),                  # window 內第一個市場交易日
    Column("definitions_version", Text),
    Column("computed_at", Text),                  # ISO 時戳 = 資料可得性
    Column("buy_pctile_known", Integer),          # 分母
    Column("buy_pctile_unknown", Integer),        # 分位不可知,不是失敗
    Column("low_buy_count", Integer),             # 分子,分母 = buy_pctile_known
    Column("sell_pctile_known", Integer),         # 分母
    Column("sell_pctile_unknown", Integer),
    Column("high_sell_count", Integer),           # 分子,分母 = sell_pctile_known
    # 該檔股票自身、跨所有分點 pooled 的同一組計數(= 這一對的比較基準)。
    Column("stock_buy_pctile_known", Integer),
    Column("stock_low_buy_count", Integer),
    Column("stock_sell_pctile_known", Integer),
    Column("stock_high_sell_count", Integer),
    Index("ix_branch_stock_pctile_counts_stock", "stock_id"),
)

# docs/27 G1:公司與券商分點地址(口袋名單前置)。
company_profiles = Table(
    "company_profiles",
    metadata,
    Column("stock_id", Text, primary_key=True),
    Column("address", Text),
    Column("city", Text),
    Column("district", Text),
    Column("market", Text, nullable=False),
    # 官方公司基本資料的 additive 欄位；地緣邏輯仍只使用 address/city/district。
    Column("industry_code", Text),
    Column("transfer_agent", Text),
    Column("transfer_agent_phone", Text),
    Column("transfer_agent_address", Text),
    Column("source", Text),
    Column("source_updated_at", Text),
    Column("updated_at", Text, nullable=False),
)

# docs/37 E1: MOPS t35sc09 官方庫藏股事實。金額=元、股數=股、價格=元/股、百分比=百分點。
# plan_id is deterministic so one issuer can retain multiple historical plans.
buybacks = Table(
    "buybacks",
    metadata,
    Column("plan_id", Text, primary_key=True),
    Column("stock_id", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("market", Text, nullable=False),       # twse / tpex
    Column("board_date", Text),
    Column("purpose", Text),
    Column("total_amount_limit", Integer),
    Column("planned_shares", Integer),
    Column("price_min", Float),
    Column("price_max", Float),
    Column("start_date", Text),
    Column("end_date", Text),
    Column("completed_flag", Text),                # preserve MOPS Y/N/raw value
    Column("executed_shares", Integer),
    Column("transferred_shares", Integer),
    Column("execution_pct", Float),
    Column("executed_amount", Integer),
    Column("avg_price", Float),
    Column("share_ratio_pct", Float),
    Column("incomplete_reason", Text),
    Column("report_date", Text),
    Column("source_updated_at", Text),
    Column("source", Text, nullable=False),
    Column("imported_at", Text, nullable=False),
    Index("ix_buybacks_stock_report", "stock_id", "report_date"),
)

broker_branch_geo = Table(
    "broker_branch_geo",
    metadata,
    Column("name_key", Text, primary_key=True),   # 正規化名稱,與 branch_trades.branch_name join
    Column("broker_id", Text),
    Column("branch_name", Text, nullable=False),
    Column("address", Text),
    Column("city", Text),
    Column("district", Text),
    Column("kind", Text, nullable=False),         # branch / hq / foreign
    Column("updated_at", Text, nullable=False),
)

# docs/34 B1:集保戶股權分散(TDCC 週更)
shareholding_dispersion = Table(
    "shareholding_dispersion",
    metadata,
    Column("stock_id", Text, primary_key=True),
    Column("as_of", Text, primary_key=True),      # YYYY-MM-DD 週結算日
    Column("tier", Integer, primary_key=True),    # 1–15(合計列不入庫)
    Column("holders", Integer),
    Column("shares", Integer),
    Column("pct", Float),                         # 占集保庫存％
    Index("ix_shareholding_dispersion_as_of", "as_of"),
)

# docs/34 §4.6 D1:董監事持股餘額明細(月更 OpenAPI)
director_holdings = Table(
    "director_holdings",
    metadata,
    Column("stock_id", Text, primary_key=True),
    Column("as_of_ym", Text, primary_key=True),   # YYYY-MM
    Column("title", Text, primary_key=True),
    Column("name", Text, primary_key=True),
    Column("shares", Integer),                    # 目前持股(股)
    Column("shares_at_election", Integer),
    Column("pledged_shares", Integer),
    Column("pledged_pct", Float),
    Column("related_shares", Integer),
    Column("market", Text),                       # twse | tpex
    Index("ix_director_holdings_ym", "as_of_ym"),
)
