# 06 技術架構

## 1. 方案比較(誠實版)

| 方案 | 優 | 劣 | 判定 |
|---|---|---|---|
| A. Laravel + Inertia + Vue 單體 | 一個 repo、一種部署、auth/scheduler/queue 全內建;AI 輔助開發上下文最小;你熟 Laravel 生態(從你列的選項推測) | PHP 算技術指標較無生態(但 MA/RSI/KD/MACD 手寫百行內,夠用);盤中 WS 需 V2 補 Node worker | **V1 採用** |
| B. Laravel API + Next.js | 前後端獨立演進 | 兩個專案、兩次部署、CORS/auth 兩套,10 人內純過度工程;AI 開發要餵兩倍上下文 | 否 |
| C. 全 Node(Nest/Next) | 與 Fugle SDK 同語言、WS 原生強 | scheduler/queue/auth 都要自組;你 Laravel 熟悉度優勢丟掉 | 否(但盤中 worker 用 Node,見下) |
| D. 全 Python(FastAPI+前端) | 資料/回測生態最強 | Web 端(auth、UI、部署)工程量大;pandas 優勢在 V3 回測才真正需要 | 否;V3 以獨立腳本形式引入 Python,不重寫主體 |
| E. Nuxt 全端 | — | 相對 A 無優勢,生態較薄 | 否 |

**結論**:V1 = 方案 A 單體;V2 加掛 Node 盤中 worker(不是改架構,是加一個 process);V3 加 Python 批次腳本。單體優先、按需長出,不預先分離。

## 2. V1 架構圖

```
┌─ VM(4 vCPU / 8GB / 80GB SSD)── Docker Compose ─────────┐
│  caddy(TLS 反代)                                        │
│  app: Laravel 11 + Inertia + Vue 3(php-fpm)             │
│  scheduler: php artisan schedule:work(同 image)          │
│  worker: php artisan queue:work --queue=import,score      │
│  postgres:16(volume + 每日 pg_dump → 異地/物件儲存)      │
└───────────────────────────────────────────────────────────┘
```

- Queue driver = **database**(V1 不裝 Redis;10 人系統的佇列量 database driver 綽綽有餘)。
- 無 WebSocket:V1 全是盤後資料,頁面用普通 HTTP;「匯入進度」用輪詢即可。
- 前端圖表:`lightweight-charts`(TradingView 開源,K 線 + 標記 API 完全符合分點足跡需求)+ Chart.js。
- 手機:RWD,不做原生 App。通知 V1 用 Telegram Bot(資料健檢告警)。

## 3. V2 增量(只加,不改)

```
+ redis(cache + pub/sub)
+ intraday-worker: Node.js(Fugle WS/REST SDK)
    tick 聚合 → 大單/量比/VWAP 判定 → 事件寫 PG + publish Redis
+ reverb: Laravel Reverb(WebSocket 推前端)
  Laravel 訂 Redis channel → 評級(套用盤後底分)→ 訊號落地 + Reverb 推播 + Telegram 通知
```

判定邏輯分工:**Node worker 只做「事實偵測」(大單、量比、VWAP、突破),Laravel 做「訊號評級與文字」**——評分規則只存在一處(PHP),回測與盤中共用,不會出現兩套規則漂移。worker 與主系統只透過 DB/Redis 通訊,掛了不影響盤後功能。

## 4. 回答你的逐項提問

| 問題 | 答案 |
|---|---|
| 需要 Redis? | V1 不要;V2 要(盤中 pub/sub + 快取基準曲線) |
| 需要 Queue? | 要,V1 就要(匯入與評分是長任務),但 database driver 即可 |
| 需要 WebSocket? | V1 不要;V2 要(Reverb 推盤中訊號) |
| 需要 Python 服務? | 不需要「服務」;V3 需要 Python「腳本」(回測/資料科學),由 scheduler 呼叫,無常駐 |
| 前後端分離? | 否,Inertia 單體。未來若真做 App 再抽 API 層(Laravel 加 API routes 即可,不必重構) |
| 一台 VM 夠嗎? | 夠,V1–V3 都夠(容量見 05 §8)。升級路徑:先垂直加規格 → 再把 PG 拆獨立 VM → 才考慮其他。10 人系統大概率永遠停在第一步 |
| 省 token 的架構? | 單體 + 模組資料夾邊界清楚 + 純函式評分層。AI 改評分只需讀 `Modules/Scoring/*` 與 04 文件,不用理解整個系統 |
| 省維運的架構? | Docker Compose 單機 + Caddy 自動 TLS + 每日 pg_dump 上物件儲存 + Uptime Kuma(或 healthchecks.io 免費)監控排程心跳 |
| 未來做完整平台? | 演進序:抽 API → 前端獨立 → PG 拆機 → worker 水平擴。每步都是增量,V1 架構無一步是死路 |

## 5. 部署與維運

- VM:任一雲(Linode/Hetzner/GCP e2-standard-2 級),月費 USD 20–40。放台灣或東京 region(API 延遲低)。
- 備份:每日 02:00 `pg_dump` gzip → rclone 上物件儲存,保留 30 份;每月手動演練還原一次。
- 監控:排程完成後 ping healthchecks.io;失敗/超時 → Telegram。應用錯誤用 Laravel log + 每日錯誤摘要通知。
- 環境:僅 production + 本機開發(docker compose 同檔),不設 staging(10 人系統,過度)。
- 升級:git pull + `docker compose up -d --build` + migrate;資料庫 migration 永遠向後相容(先加欄不刪欄)。
