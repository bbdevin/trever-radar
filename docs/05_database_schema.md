# 05 資料庫設計(PostgreSQL 16)

> 原則:分點與 tick 是唯二會爆量的資料,入庫前先裁剪;分數與訊號永久保存(回測資產);其餘照常。

## 1. 主檔類(小,永久)

| 表 | 用途 | 關鍵欄位 |
|---|---|---|
| `stocks` | 股票主檔 | id(代號 PK), name, market(twse/tpex), industry, address_city(地緣用), is_active, listed_at |
| `warrants` | 權證主檔 | id(權證代號), stock_id FK, type(call/put), strike, exercise_ratio, maturity_date, issuer |
| `brokers` | 券商 | id, name |
| `branches` | 分點 | id, broker_id FK, name, city, is_daytrade(隔日沖標記), is_key(關鍵), key_source(manual/auto) |
| `geo_branch_map` | 地緣對照 | stock_id, branch_id, reason(hq/factory), verified_by |
| `themes` / `stock_themes` | 題材 | theme: id, name, note;pivot: stock_id, theme_id, weight |
| `users` | 使用者 | Laravel 標準 + role(admin/user), invited_by |

## 2. 日級時序(中,永久,按年成長可控)

| 表 | 用途 | 量級 |
|---|---|---|
| `daily_prices` | 日K:OHLCV、成交金額、還原因子 adj_factor | 2000 檔×250 日/年 = 50 萬列/年 |
| `daily_institutional` | 法人買賣超 | 同級 |
| `daily_margins` | 融資券 | 同級 |
| `warrant_daily` | 權證每日價量金額 | ~2 萬檔權證,500 萬列/年 → **只保留 2 年明細,更早彙總到 `warrant_stock_daily`** |
| `warrant_stock_daily` | 以標的股彙總:認購/認售 金額、量、檔數、20日倍數 | 50 萬列/年,永久(評分只用這張) |
| `alert_stocks` | 注意/處置紀錄 | 小 |
| `indicators_daily` | 技術指標快取:ma5/10/20/60, rsi14, kd, macd, 20日高, 箱型邊界, adv20 | 50 萬列/年;可重算,只留 2 年 |

索引通則:`(stock_id, date)` 複合 PK 或唯一索引;date 單欄索引供全市場單日查詢。

## 3. 分點資料(最大,入庫前裁剪 — 核心設計決策)

**不存全量**(全量 = 每股×每有交易分點×每日 ≈ 每日數十萬列,一年近億)。存三層:

| 表 | 內容 | 量級 |
|---|---|---|
| `branch_trades_top` | 每股每日買超前 15 + 賣超前 15 分點:buy/sell 張數與金額、netbuy、佔成交量比 | 2000×30×250 ≈ 1,500 萬列/年,可接受;`(stock_id, date)`、`(branch_id, stock_id, date)` 索引 |
| `branch_trades_watch` | 關鍵分點 + 地緣分點 + 隔日沖名單分點的**全量**紀錄(即使不在前 15) | 小得多 |
| `branch_stock_stats` | 分點×股票滾動統計:連買天數、事件數、5日勝率、平均報酬、買點分位、隔日沖率、可信度分數、最後活躍日 | 只存「曾入前 15 或名單內」的組合,每日 upsert,約數十萬列總量 |

> 取捨後果(誠實面對):非前 15 名的小額分點歷史會缺,某分點「當年只買第 18 名」的紀錄查不到。對本產品目標(追主力)可接受。FinMind 原始資料仍在其雲端,V3 要補算可重拉。

## 4. 分數與訊號(小,永久 — 回測資產)

| 表 | 用途 |
|---|---|
| `daily_scores` | 每股每日:branch/warrant/tech/theme/inst 各分項、risk_penalty、final、reasons(JSONB)、risks(JSONB)、entry_price(次日開盤)、fwd_1d/3d/5d/10d/20d(批次回填) — V1-Free 直接作為回測資產 |
| `daily_watchlist` | 每日觀察清單快照:rank, score, entry_price/fwd 欄可由 `daily_scores` 衍生;V1-Free 暫不另建 |
| `intraday_pool` | 每日監控池(股票、入池原因、盤後分) |
| `intraday_events` | 大單事件:time, price, amount, side, cum_5m, active_ratio |
| `intraday_signals` | 盤中訊號:level, triggered_at, price, reasons(JSONB), is_chase_warning, fwd 回填欄 |
| `signal_rule_stats` | 各規則代碼的滾動勝率統計(回測輸出) |

`daily_prices.adj_factor` 現行由 `compute-adjustments` 以 FinMind `TaiwanStockDividendResult` 免費資料計算;技術指標與 `compute-performance` 的進出場報酬使用 `price * adj_factor` 還原價欄位,原始 OHLC 保留不覆蓋。

## 5. 盤中行情(V2,固定大小,滾動清理)

| 表 | 保留策略 |
|---|---|
| `intraday_bars_1m` | 監控池 1 分 K(80 檔×270 根/日 ≈ 2.2 萬列/日),保留 60 日後刪(大單事件已提煉,原始 bar 不需久留) |
| `volume_baseline_5m` | 每股 5 分鐘粒度累積量基準曲線(量比分母),每晚重算,只留當前版 |
| 原始 tick | **不入庫**。worker 記憶體內聚合,僅事件落地。除錯需要時寫檔案 log 留 7 日 |

## 6. 系統表

`import_logs`(source, dataset, date, rows, status, error, duration)、`provider_settings`(來源開關與額度設定)、`notifications_log`、`user_watchlists`(自選股)、`audit_logs`(admin 操作)。

## 7. 回答你的清單問題

- **會很大的**:branch_trades_top(裁剪後可控)、warrant_daily(2 年滾動)、intraday_bars_1m(60 日滾動)。
- **必須永久**:daily_prices、warrant_stock_daily、branch_stock_stats、全部分數與訊號表(回測命脈)。
- **可彙總**:warrant_daily → warrant_stock_daily;tick → events。
- **避免無限成長**:上述滾動刪除 + 每月 `pg_repack`/VACUUM 排程 + 磁碟用量進健檢告警。
- **支援回測**:daily_scores 存完整 reasons JSONB = 當日決策全紀錄,重放不需重算;參數化回測(V3)另建 `backtest_runs`/`backtest_results`。
- **支援籌碼 K 線**:個股頁一次查詢 = `daily_prices` + `indicators_daily` + `branch_trades_top`(該股)+ `branch_stock_stats`(該股)四張表,皆有 `(stock_id, date)` 索引,240 日資料 < 100ms。

## 8. 容量估算(V1+V2,單機綽綽有餘)

年增:日級 ~200 萬列 + 分點 1,500 萬列 + 權證 500 萬列 ≈ 2,200 萬列/年 ≈ 3–5 GB/年(含索引)。PostgreSQL 單機 10 年不是問題;不需要分庫分表,不需要 TimescaleDB(V3 若 tick 要落地再議)。
