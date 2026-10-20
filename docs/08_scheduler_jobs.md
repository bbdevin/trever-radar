# 08 排程與資料流程

## 0. 現行 VPS cron 排程總表(2026-07-18 WP-B3 cutover 後,單一真相)

> **架構變更(2026-07-18 WP-B3 cutover)**:`radar.db` 常駐 VPS,VPS 為唯一寫者。VPS cron(`vps/scripts/`,見 `vps/crontab.example` 樣板實體在 `vps/scripts/crontab.example`)跑完每輪管線後直接 `export-json` + `cd cloudflare-data-worker && npx wrangler deploy`,把 JSON 當 Cloudflare Worker 靜態資產上傳,`radar.techtrever.com/data/*` 即傳即生效(不經 GitHub、不經 Pages build)。GitHub Actions 只剩 push `main` 觸發的 `deploy.yml`(純 code build+deploy,不碰資料)。詳細規劃見 `docs/31` §2/§3,實際指令序見 `vps/README.md` §9。
>
> **四層總圖（日更／歷史回補／發布／大戶）**:見 [`docs/35_vps_schedule_architecture.md`](35_vps_schedule_architecture.md)（2026-08-27 唯讀核對：S2、TDCC 06:30、董監每月 16 日 07:00 均已掛正式 crontab）。
>
> **2026-08-31 12:16–12:26 +08 唯讀稽核**：SSH alias 為 `trever-vps`（`trever_vps` 無法解析）；本機與 VPS `main` 皆為 `8603f3a`。正式 crontab 已見平日 14:10／15:00／16:10／17:40／21:20／22:00、01:10、mid 03／09／12／20、23:30、TDCC 週六 06:30、董監每月 16 日 07:00；`radar-bf-branches` 與 `radar-worker` 各有一個 guard/supervisor。VPS 有未追蹤 `data/`、`package-lock.json`、`radar-quick-catchup.sh`、`run-backfill.sh`，歷史上曾使 `git pull` 失敗，**不得刪除或自行 pull**。本段是快照，不授權重啟、清理、DB 寫入或 cron 變更；細節與待驗項見 `docs/35`、`vps/README.md`。
>
> **2026-08-31 上櫃鎖／520 與手動恢復**：14:10 `daily-market.sh` 因週一題材／公司資料流程跑到 15:11，15:00 `daily-tpex-quotes.sh` 搶不到 `/tmp/radar-db.lock`，依設計安全略過並送 ntfy；15:43 後已無 holder，0-byte lock path 不是 stale lock，勿刪。16:10 與後續三次手動完整腳本均因 `dailyQuotes` HTTP 520 fail closed；response 為 Cloudflare SJC、16-byte body，同 URL／IP 在分鐘內交替 200／520，且不是 429。只能確認 Cloudflare edge 到 TPEx origin 路徑發生間歇異常；沒有供應商內部 log，不能斷言更深層原因。使用者授權後，以同一官方 URL 的 curl 長退避取得 payload，先驗 `date=20260831`、`stat=ok`、19 欄／10,713 rows，再交既有 parser＋transaction 匯入；後續彙總、指標、分數、export、Worker deploy 均成功（version `51b690a4-9b50-407d-b981-1d6c26e9533c`），正式站 6488 已顯示 2026-08-31。未改 cron／code／workflow；永久 retry／隔離方案須另案確認。
>
> **2026-08-31 22:00 日常權證過渡池成功**：現行上市 active 普通股標的、認購／認售且成交額 `>=100萬` 的輪次完成 2,619 targets／61,687 rows／0 failed，`23:53:26 CMDEND`，data Worker=`5548186b-8d40-4fae-a00b-a596dee59564`。這不代表今日 TPEx endpoint 穩定；其狀態仍 unknown。2026-09-01 13:13 已在無鎖／無日更程序下 ff-only 同步 520 重試／安全降級程式至 VPS `e9ce054`；未手動跑正式 DB／import／export／deploy，未改 cron。

> **2026-10-04 排程優化(`docs/47`)**:程式與 `crontab.example` 已改為「各輪是起點、腳本輪詢到來源公布為止、搶不到鎖會等、沒變動不上線、非交易日分點/資券/夜間輪收工」。**正式 crontab 尚未套用**(`vps/scripts/crontab.proposed.diff`,待人類核准);下表為**新時刻(舊時刻)**,腳本在舊時刻下也正確。
>
> 新增:週一 11:00 `weekly-refdata.sh`(題材/地緣/產業別,只寫 DB;crontab 套用前由 `daily-market.sh` 在 deploy 後補跑)。
>
> 長工作讓路表(2026-10-15):warrant-backfill／repair-window／build-branch-cover-index 的預算用 `lib.sh` `minutes_until_next_scheduled_writer` = 安靜窗(`quiet_window_at`)＋ overlay:mid-publish 03/09/12/20:00 起 20 分(`mid_publish_at`)、每天 00:05–00:54(`nightly_stats_at`)、每月 16 日 07:00 起 20 分(`monthly_directors_at`)、**平日 08:00–08:45 morning-index 與 13:15–13:35 adjust-incremental(`WEEKDAY_SHORT_JOBS`/`weekday_short_job_at`)**。overlay 不進 `quiet_window_at`(短輪自己不能判定在安靜窗裡);adjust-incremental 問預算時排除自己的 13:15。新增會拿 DB 鎖的排程輪時,要同步加進 overlay(10-14／15 morning-index 被 06:36 開的回補塊擋掉,見 `docs/49` §12.6.5)。

| 台北時間 | 執行者(VPS cron script / GitHub Actions) | 內容 |
|---|---|---|
| 平日 08:00(2026-10-13 新增;**已裝進正式 crontab 2026-10-13 12:34**,使用者核准;備份 `~/crontab.bak.20261013123449`;行見 `docs/49` §12.6.5) | VPS `vps/scripts/morning-index.sh` | 早上台指期夜盤上線:週末收工 → 等鎖(≤300 s)→ `sync_code` → 每 10 分輪詢 `import-index`(加權/櫃買/台指期一般時段早上必 75,正常)直到今天的 `tx_night` 入庫,截止 08:40;每次印 `morning-index tx_night date=… present=yes|no … at=HH:MM`(期交所最早幾點公布的量測紀錄)→ `export-index`(只重寫 radar.json 的 `indices`、`home/{head,stocks}.json`、`market/indices_hist.json`;資料日讀現有 radar.json,`generated_at` 不動)→ deploy。截止仍無 = 休市/未公布,只寫 log 不通知;失敗只 warn(14:05 收盤輪照常帶上)。約 1–2 分鐘;08:50 盤中 worker、09:00 mid-backfill-publish 之前收工 |
| 平日 13:15(2026-10-09 新增;**正式 crontab 待人類套用**) | VPS `vps/scripts/adjust-incremental.sh` | 除權息還原因子日增量:安靜窗/mid flag/距下一個排程寫入者 ≤30 分 → 略過;`flock -n` 搶不到 → 略過(notify_skip)→ `compute-adjustments --ex-dates-since 10 --print-ids`(證交所 TWT49U + 櫃買 exDailyQ 只當代號挑選器)→ `compute-adjustments --ids`(逐檔 FinMind,因子邏輯不變)→ `compute-indicators --ids`(全歷史)。不 export/deploy,14:05 輪上線;有因子變動才 notify_ok。旺季 ~260 檔約 20–25 分 |
| 平日 14:05(舊 14:10) | VPS `vps/scripts/daily-market.sh` | 每 3 分輪詢上市日K(`--require twse:quotes`)至 14:40 → 當日權證彙總 → 指標增量(--days 5)→ 綜合分 → fetch-intraday(**放 DB 鎖抓 Fugle 當日 1 分 K spark_day + 5 分 K**,2026-10-19 起,見下方)→ export-json → `wrangler deploy`。截止仍沒到 → warn、不上線。週一題材/地緣已搬到 11:00 |
| 平日 14:45(舊 15:00) | VPS `vps/scripts/daily-tpex-quotes.sh` | 等鎖(≤45 分)→ 每 3 分輪詢**上櫃日K**(`--require tpex:quotes:0.8`,≥前一交易日 80% 列數)至 15:30 → 權證彙總 + 指標增量 + 分數 → export-json → deploy |
| 平日 16:00(舊 16:10) | VPS `vps/scripts/daily-insti.sh` | **上櫃日K 保底再抓** → 每 5 分輪詢法人(上市＋上櫃都要到)至 17:10,每次順手試個股期貨當日 → 權證主檔(失敗不擋)/庫藏股 → **當日權證重新彙總** → 指標 → 分數 → export → deploy。截止仍缺 → 有其他變動先上線已到部分、否則略過。TPEx HTTP 520(TWSE 已成功)仍 exit 75 不發布,留給分點輪;非 75 仍 High fail |
| 平日 17:30(舊 17:40) | VPS `vps/scripts/daily-branches.sh` | 非交易日收工 → **再補日K** + 法人補抓 + 期貨當日(已有則略過)+ 指標增量 → **探測分點來源**(`probe-branch-day`,每 15 分抽 24 檔、≥22 檔有資料或到 20:30 才爬;等待期間不握 DB 鎖)→ **分點全股票 `--top 0`（不含 ETF）＋標的是 active 普通股的上市認購／認售、當日成交金額 `>=1,000,000` 元權證過渡池** + 分點統計 →(已過 21:00 順手匯入資券)→ 分數 + 績效回填 → export-json → prune → deploy → 完成標記(第二行 `coverage_ratio=`) |
| 平日 20:45(舊 21:20) | VPS `vps/scripts/daily-margin.sh` | **融資券主輪**:非交易日/資券已是今天(分點輪帶入)→ 收工;否則等鎖(≤90 分)→ 每 5 分輪詢資券(上市＋上櫃)至 22:15 → 期貨官方覆核 → 分數 → 績效 → export → deploy;若仍落後價格日則對齊再抓 + ntfy warn |
| 平日 22:30(舊 22:00) | VPS `vps/scripts/daily-branches.sh`(第二輪,`BRANCH_ROUND_MODE=import`) | 第一輪覆蓋率 100%(標記 `coverage_ratio=1.0000`)→ `publish skipped: first round complete`;<100% → 重爬並跳過 `compute-branch-stats`、**重算當日評分**並重新上線、不重寫完成標記;無標記 → 接手完整鏈 |
| 每天 01:10 | VPS `vps/scripts/data-backfill.sh` | 深歷史增量(已拉深自動跳過 → 日常近零請求,只補新上市/缺漏) |
| 每天 03/09/12/20:00 | VPS `mid-backfill-publish.sh` | 回補中途上線:pause bf → 預設只 export → deploy(docs/33) |
| 週二–六 00:05 | VPS `safe-branch-stats.sh` | 前一日非交易日 → 收工;pause bf → compute-branch-stats → 帳本/分位 → **compute-scores** → export → deploy(evening ok 時只在帳本或分位有算出才 export+deploy,docs/47) |
| 週六 05:00 | VPS `vps/scripts/weekly-backup.sh` | 備份:`wal_checkpoint(TRUNCATE)` → `integrity_check`(必須 `ok`)→ gzip → `rclone` 上傳 Google Drive(唯一雲端備份;retention 近 4 份+每月 1 份) |
| 週六 06:30 | VPS `weekly-tdcc.sh` | TDCC 大戶全市場週更 → export → deploy（docs/34 B1；正式 cron 已掛） |
| 週日 02:30 | VPS `backfill-margin.sh` | 資券約 240 日回補(done flag 則跳過;docs/34 A4) |
| 每月 16 日 07:00 | VPS `monthly-directors.sh` | 董監持股月更 → export → deploy（正式 cron 已掛；2026-08-26 已成功匯入 2026-07 月資料，下一次正式 cron 為 2026-09-16） |
| @reboot + */5 | `bf-cron-guard.sh` | 安靜窗／mid／margin／tdcc flag → pause 歷史 bf |
| @reboot + */10 | `bf-supervisor.sh` | 歷史 bf 單寫者自啟(branches→warrant)＋完成 ntfy |
| 平日 08:50–13:35 | 盤中訊號雷達 worker(docker+cron,同一台 VPS,docs/24 Part A) | 讀 `https://radar.techtrever.com/data/radar.json` 判定 I-1~I-4 訊號,寫 Supabase,首頁盤中面板即時顯示;13:35 自動收工 |
| push `main` | GitHub Actions `deploy.yml` | checkout → npm build → wrangler pages deploy(**只管程式碼/前端,不碰資料**) |

- **共用機制**(`vps/scripts/lib.sh`):`/tmp/radar-db.lock` 互斥。2026-10-04 起五支日更輪與 `weekly-refdata.sh` 用 `acquire_db_lock_wait`(`flock -w`,等不到才 high 通知),輪詢期間每次嘗試之間放鎖(`poll_until`,docs/47);`data-backfill.sh` 等仍是 `flock -n`(搶不到=跳過本輪+ntfy 通知)；開輪的 `git pull --ff-only`+docker build(layer cache)只適用於已獲授權且 working tree clean 的正常狀態。2026-08-31 快照因 VPS 有未追蹤檔，現階段**不得自行 pull**。另有**失敗 ntfy High／日更成功繁中摘要**，非交易日靠 `NoDataError` 安全空跑。
- **首頁多方榜(2026-10-04,docs/48)**:表中每一輪的「export-json → deploy」之間都多一步 `build_bull_board`(`lib.sh`;主機 Node 跑 `web/scripts/build-bull-board.mjs`,只讀匯出的 JSON,硬上限 600 s,實測 ~34 s)→ `bull_board.json` + `data/bull_board_log/YYYY-MM.jsonl`。失敗只 warn、不擋 deploy;沒匯出的輪(publish skipped)不建。log 行 `step bull-board … elapsed=`。
- **Fugle 抓取不握 DB 鎖(2026-10-19,docs/50 §3.1;程式在分支,未合 main)**:五支日更輪(14:05/14:45/16:00/16:30+22:30 分點/20:45)的 `export-json` 前一步多一個 `prefetch_intraday`(`lib.sh`):放 DB 鎖 → `radar fetch-intraday`(唯讀選榜單聯集,打 Fugle 把當日分時 spark_day 與 5 分 K 抓進 `data/spark_day.json`、`data/intraday5/`;硬上限 900 s;抓取之間以 `/tmp/radar-intraday-fetch.lock` 排隊)→ 拿回 DB 鎖(≤3600 s)→ export-json(預設只讀快取,不連 Fugle)。分點輪每輪只在第一次上線前抓一次。抓取失敗只 warn,export 用較舊的快取。上表「export-json(含 Fugle…)」的抓取都改在這一步。回滾:`RADAR_EXPORT_FETCH=1`(vps/.env 或 crontab 前綴)。其他會 export 的腳本(00:05 夜間、mid-publish、週六 TDCC、月董監、manual-catchup)不加這一步、export 也不抓:前三者與月董監跑的時候台北今天 ≠ 價格日,以前本來就不抓;交易日 20:00 的 mid-publish(無回補容器時是 noop)與當天手動 manual-catchup 以前會順手補抓新進聯集的分時/分K,現在不會——要的話先手動跑一次 `radar fetch-intraday`。log 行 `step fetch-intraday … elapsed=`、`fetch-intraday: date= … ok=`。
- **特定分點晚間推播(2026-10-20,`docs/52` §9;程式在分支,未合 main;預設關)**:`daily-branches.sh` 的 `publish_site` 在 `deploy_data`、`futures_digest` 之後多一步 `watch_push "$ROUND_DATE"`(`lib.sh`):只讀剛匯出的 `branches/watch/`(唯讀掛載,不開 DB、不拿鎖、硬上限 60 s)→ `radar watch-push` 決定要不要送 → `curl` 到 `WATCH_PUSH_NTFY_TOPIC`(vps/.env;**與維運 `NTFY` 不同的主題**,沒設 = 整步不做)。同一資料日最多三則(第一段上線一則;第二段權證算進今天後名單有變一則;22:30 再變一則),名單沒變不送;狀態 `data/watch-push-state.json` 只在 ntfy 確認收到後寫。失敗只 warn,永不擋本輪。休市日分點輪在上線前就收工,不會送。log 行 `watch-push: sent …` / `watch-push: SKIP …`。
- **DB 續存**:VPS `data/radar.db` 為唯一常駐主本,無 Actions cache/release 續存鏈(已隨 WP-B3 退役)。
- **權證全市場輪（2026-08-28 code-ready、未啟用）**:`daily-warrant-branches-poc.sh` 與 `import-warrant-branch-trades --market all` 將上市＋上櫃、當日有量有額、普通股標的的認購／認售合併成單一池；`--top` 是 fail-closed 安全上限而非截斷。VPS 2026-08-31 最新實測可用空間為 7.0GB，低於 20GB 閘門，且 sleep=1.0 約需 6–8 小時；正式 crontab 保持未加，未寫正式 DB、未 deploy。見 `docs/30`。
- **舊 GitHub Actions 資料 workflow 已無觸發**:`daily-market/daily-insti/daily-branches/daily-margin/data-backfill.yml` 檔案仍在 repo，Cloudflare Worker trigger 的 cron 已清空。原訂 2026-08-01 後刪除但尚未執行；改 workflow 仍須人工確認，另案處理，勿由本文件更新順手刪除。
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
