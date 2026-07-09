# 08 排程與資料流程

## 0. 現行 V1-Free 排程總表(2026-07-08 定案,單一真相)

依交易所公布時間分批,每階段跑完直接部署;晚到的資料集由前端 `freshness` 標「暫用前一日」。
所有資料 workflow 共用 `radar-db` 併發群(依序執行);**手動觸發請一次一支,等跑完再下一支**,否則排隊互相取消。

> **觸發機制(2026-07-09 起)**:GitHub 原生 `schedule:` 實測延遲 2.5–3.5 小時(見 `cloudflare-trigger/README.md`),5 支資料 workflow 已改為只留 `workflow_dispatch:`,改由 Cloudflare Worker(`cloudflare-trigger/`)在下表時間點準時呼叫觸發。下表時間仍是唯一真相,只是「誰來準時觸發」換人。

| 台北時間 | workflow | 內容 | 部署 |
|---|---|---|---|
| 平日 14:10 | `daily-market` | 日K+權證成交(14:00 公布)→ 當日權證彙總 → 指標增量(--days 5)→ 綜合分 →(週一)概念股更新 | ✓ 資料日變當天 |
| 平日 16:10 | `daily-insti` | 法人買賣超(16:00 公布)+ 權證主檔 → 重算分數 | ✓ |
| 平日 17:40 | `daily-branches` | 融資券 + 法人補抓 + 分點爬蟲(80檔+15權證)+ 分點統計 + 分數 + 績效回填 | ✓ |
| 平日 21:00 | `daily-branches`(第二輪) | 同上,補晚公布/前段失敗(全部冪等) | ✓ |
| 平日 22:10 | `daily-margin`(新) | 融資券保底輪:只補 margin(不含分點爬蟲)+ 重算分數,因 TWSE MI_MARGN 公布時間可能晚於 21:00 | ✓ |
| 每天 01:10 | `data-backfill` | 深歷史增量(已拉深自動跳過 → 日常近零請求,只補新上市/缺漏) | ✗ |
| 週六 01:10 | `data-backfill`(同支) | + 全市場還原因子重抓(除權息)+ 指標全歷史重算 + DB 備份 | ✗ |
| 週五 17:40/21:00 | `daily-branches` 內 | DB 備份上傳 release `db-backup` | — |
| push `main` | `deploy` | 用現有雲端 DB:分數+績效+export+build+deploy(不抓資料) | ✓ |

- **DB 續存**:Actions cache 為主(每支跑完必存、下一支接續),cache miss 才從 release `db-backup` 種子還原;release 備份僅週五/週六/手動更新。
- 本機開發:同一套 CLI,`python -m radar export-json` 後前端讀 `web/public/data/*.json`;本機 DB 僅開發用,**正式真相在雲端**。

> §1(舊版盤後管線,Laravel job chain 格式)已刪除——與 §0 矛盾且從未實作,§0 是唯一真相。以下 §2/§3 是 V2 尚未實作的設計參考,保留。

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
