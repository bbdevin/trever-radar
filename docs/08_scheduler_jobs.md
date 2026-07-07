# 08 排程與資料流程

## 0. 現行 V1-Free 工作流(2026-07-07)

實作檔:`.github/workflows/nightly-radar.yml`。

- `schedule`:每交易日 17:30 / 21:00 台北時間,還原 Actions cache/release DB → 匯入今日資料 → 更新權證主檔與當日彙總 → `export-json` → Next build → Cloudflare Pages deploy → 保存 DB cache,週五/手動時備份 release。
- `workflow_dispatch`:同 schedule,可手動重跑並觸發 DB 備份。
- `push` 到 `main`:還原 Actions cache/release DB → **跳過資料匯入** → `export-json` → Next build → Cloudflare Pages deploy。用途是程式/UI 修正立刻上正式版,不在非收盤時間誤抓資料。
- 本機開發仍走同一 CLI:`cd pipeline; .venv\Scripts\python -m radar export-json`,前端讀 `web/public/data/*.json`。

## 1. 盤後管線(V1,交易日執行)

依賴關係用 Laravel job chain / batch,單一步驟失敗自動重試 3 次(間隔 10 分鐘),仍失敗 → 告警 + 後續步驟依「降級規則」續跑或中止。

| 時間 | Job | 內容 | 失敗降級 |
|---|---|---|---|
| 14:30 | ImportDailyPrices | TWSE MI_INDEX + TPEx 日成交(含權證價量) | 中止管線(基礎資料) |
| 14:40 | ImportAlertStocks | 注意/處置 | 續跑,標記缺 |
| 15:10 | ImportInstitutional | 法人 T86 + TPEx | 續跑 |
| 15:30 | ImportWarrantMaster | 權證主檔增量(新發行/到期) | 續跑 |
| 16:30 | ImportMargins | 融資券(公布較晚) | 續跑 |
| 17:00 | ImportBranchTrades | FinMind 分點 → 裁剪入 branch_trades_top/watch | 重試至 18:00;仍失敗 → 出「無分點版」清單並大字標註 |
| 17:30 | DataHealthCheck | 各表筆數/缺漏/合理性;寫 import_logs;異常 → Telegram | — |
| 17:40 | ComputeIndicators | 還原價調整 → 技術指標 → adv20 → 量比基準曲線(給 V2) | — |
| 17:50 | ComputeScores | 權證分 → 分點分(含 branch_stock_stats 增量更新)→ 技術/題材/法人分 → 風險 → 綜合分 + reasons | — |
| 18:10 | BuildWatchlist | 觀察清單 Top30 + 權證特別榜 + 明日監控池(綜合分≥55 前 60 檔 + 全體自選)| — |
| 18:20 | NotifyDaily | Telegram 推「今日清單已產生 + 前 5 名摘要 + 資料完整度」 | — |
| 21:00 | BackfillReturns | 回填歷史清單/訊號的 fwd 報酬(V2) | — |
| 02:00 | Housekeeping | pg_dump 備份、滾動刪除(warrant_daily>2年、bars>60日)、log 清理 | — |

註:各所公布時間偶有延遲,每個 Import job 先打「資料日期檢查」,拿到的還是舊資料就延後重試,不硬吞。非交易日(假日/颱風)以 TWSE 行事曆 + 當日有無資料雙重判斷,自動跳過。

## 2. 盤中管線(V2,08:55–13:35)

```
08:55 worker 啟動:讀今日 intraday_pool(昨 18:10 產生)
      ├─ 前 N 檔(依盤後分)→ Fugle WS 訂閱逐筆
      └─ 其餘 → REST snapshot 每 60 秒輪詢
09:00–13:30 迴圈:
  tick → 記憶體聚合(1分K、VWAP、累積量、5分鐘滑窗)
       → 大單判定(04 §9.1)、主動買賣(§9.2)、量比(§9.3)
       → 事實事件寫 intraday_events + Redis publish
  Laravel 訂閱 → 套盤後底分評級(§9.5)→ 防抖/冷卻
       → intraday_signals 落地 → Reverb 推前端 → A/B 級 Telegram
13:35 worker 收盤:flush 1分K 入庫、當日事件統計、心跳結束
18:10 盤後管線順帶:盤中訊號納入 BackfillReturns
```

容錯:worker 每 30 秒心跳寫 Redis,Laravel 偵測斷訊 90 秒 → 告警;WS 斷線自動重連 + 以 REST snapshot 補狀態(VWAP 與累積量用 snapshot 的累計值重建,不因斷線歸零)。

## 3. 每週/每月

- 週六 03:00:branch_stock_stats 全量重算(平日增量,週末校正)、分點隔日沖自動判定更新、關鍵分點自動晉降(V2)。
- 每月 1 日:題材成分股人工維護提醒、備份還原演練提醒、磁碟用量報告。
