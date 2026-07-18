# 08 排程與資料流程

## 0. 現行 VPS cron 排程總表(2026-07-18 WP-B3 cutover 後,單一真相)

> **架構變更(2026-07-18 WP-B3 cutover)**:`radar.db` 常駐 VPS,VPS 為唯一寫者。VPS cron(`vps/scripts/`,見 `vps/crontab.example` 樣板實體在 `vps/scripts/crontab.example`)跑完每輪管線後直接 `export-json` + `cd cloudflare-data-worker && npx wrangler deploy`,把 JSON 當 Cloudflare Worker 靜態資產上傳,`radar.techtrever.com/data/*` 即傳即生效(不經 GitHub、不經 Pages build)。GitHub Actions 只剩 push `main` 觸發的 `deploy.yml`(純 code build+deploy,不碰資料)。詳細規劃見 `docs/31` §2/§3,實際指令序見 `vps/README.md` §9。

| 台北時間 | 執行者(VPS cron script / GitHub Actions) | 內容 |
|---|---|---|
| 平日 14:10 | VPS `vps/scripts/daily-market.sh` | 日K+權證成交(14:00 公布)→ 當日權證彙總 → 指標增量(--days 5)→ 綜合分 →(週一)概念股更新 → export-json → `wrangler deploy` |
| 平日 16:10 | VPS `vps/scripts/daily-insti.sh` | 法人買賣超(16:00 公布)+ 權證主檔 → 重算分數 → export-json → deploy |
| 平日 17:40 | VPS `vps/scripts/daily-branches.sh` | 融資券 + 法人補抓 + 分點爬蟲(80檔+15權證)+ 分點統計 + 分數 + 績效回填 → export-json → prune → deploy |
| 平日 21:00 | VPS `vps/scripts/daily-branches.sh`(第二輪,同一支 script) | 同上,補晚公布/前段失敗(全部冪等) → export-json → deploy |
| 平日 22:10 | VPS `vps/scripts/daily-margin.sh` | 融資券保底輪:只補 margin(不含分點爬蟲)+ 重算分數,因 TWSE MI_MARGN 公布時間可能晚於 21:00 → export-json → deploy |
| 每天 01:10 | VPS `vps/scripts/data-backfill.sh` | 深歷史增量(已拉深自動跳過 → 日常近零請求,只補新上市/缺漏) |
| 週六 05:00 | VPS `vps/scripts/weekly-backup.sh` | 備份:`wal_checkpoint(TRUNCATE)` → `integrity_check`(必須 `ok`)→ gzip → `rclone` 上傳 Google Drive(唯一雲端備份;retention 近 4 份+每月 1 份) |
| 平日 08:50–13:35 | 盤中訊號雷達 worker(docker+cron,同一台 VPS,docs/24 Part A) | 讀 `https://radar.techtrever.com/data/radar.json`(Cloudflare Access service token)判定 I-1~I-4 訊號,寫 Supabase,首頁盤中面板即時顯示;13:35 自動收工 |
| push `main` | GitHub Actions `deploy.yml` | checkout → npm build → wrangler pages deploy(**只管程式碼/前端,不碰資料**) |

- **共用機制**(`vps/scripts/lib.sh`):`flock -n /tmp/radar-db.lock` 互斥(搶不到=跳過本輪+ntfy 通知)、開輪先 `git pull --ff-only`+docker build(layer cache)、失敗 ntfy High 告警成功靜默、非交易日靠 `NoDataError` 安全空跑。
- **DB 續存**:VPS `data/radar.db` 為唯一常駐主本,無 Actions cache/release 續存鏈(已隨 WP-B3 退役)。
- **舊 GitHub Actions 資料 workflow 已無觸發**:`daily-market/daily-insti/daily-branches/daily-margin/data-backfill.yml` 檔案仍在 repo(Cloudflare Worker trigger 的 cron 已清空,回滾窗保留),預定 ~2026-08-01 回滾窗結束後依 `docs/31` §9 刪除。
- 本機開發:同一套 CLI,`python -m radar export-json` 後前端讀 `web/public/data/*.json`;本機 DB 僅開發用,**正式真相在 VPS**。

> §1(舊版盤後管線,Laravel job chain 格式)已刪除——與 §0 矛盾且從未實作,§0(現為 VPS cron 表)是唯一真相。以下 §2/§3 是 V2 尚未實作的設計參考,保留。

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
