# 31 B 案:VPS 資料主本 + Workers 資料層(單一寫者架構)遷移計畫

> **狀態:使用者已於 2026-07-15 定案採用 B 案,本檔為遷移的 source of truth**(Planner:Claude Fable 5)。
> **同日修訂(v2)**:經與使用者討論,部署設計由「VPS 輪詢 build+deploy」改為「R2 資料層」——資料與網站部署徹底解耦,GitHub push→deploy 流程維持現狀不變;並新增 WP-B7 登入統一(方向已定,細部待資安審查)。v1 的 VPS build/wrangler/輪詢設計全部作廢。
> **同日修訂(v3,現行版)**:R2 啟用需綁信用卡,使用者定案**不採用 R2**——資料層改「**Workers 靜態資產**」(VPS `wrangler deploy` 上傳 JSON,體感與 R2 即傳即生效相同),備份改 **Google Drive 單雲**(使用者接受單雲風險,見 §4)。全方案免費且無需綁卡。v2 的 R2 bucket/rclone-R2 設計作廢;「VPS 不裝 node/不跑 wrangler」限制放寬為「僅為資料上傳裝 node+wrangler,仍不 build 前端、不開對外 port」。
> 依 `docs/17` 高風險流程:架構方向已由使用者拍板;各工作包(WP-B*)動工前仍需使用者逐包確認,Executor 不得自行擴張。
> 本檔取代/凍結的舊規劃見 §9(退役清單)。接手的 agent 請先讀 §0 與 §10,再看自己被指派的工作包。

## 0. 一頁摘要(給接手 agent 的最速理解)

**現況(遷移前)**:SQLite `radar.db` 以「GitHub Actions cache 續存 + release `db-backup` 種子」活在雲端,6 支 GitHub Actions workflow 由 Cloudflare Worker 定時觸發,每日抓資料→算分→匯出 JSON→build→部署 Cloudflare Pages。VPS 只做歷史回補,靠「整檔 gzip 上傳 release + 清 cache」與雲端同步。

**三個根因問題**(2026-07-14 分析定案,詳見 `docs/29` 與對話):
1. **容量天花板**:release 單檔 2GB / cache 10GB;4 年×全市場的最終目標必然再撞。
2. **雙寫者同步**:雲端與 VPS 都寫 `radar.db`,整檔覆蓋上傳有競態——07-13 資料斷層事故的病灶。
3. **合規**:repo 為解 Actions 額度改 public 後,`db-backup` release 整包資料庫(TWSE/TPEx/MoneyDJ 資料)公開可下載,踩 `docs/10` §3「資料再散布」紅線。

**B 案目標架構(v3,Workers 靜態資產資料層)**:

```
【網站/code — 與現狀幾乎相同】
你 git push main → GitHub Actions:npm build(不再碰 DB/資料)→ wrangler 部署 Pages
  ※ push→上線仍為 2–3 分鐘,操作體感零改變;repo 轉回 private

【資料 — 全部在 VPS】
VPS(radar.db 唯一常駐、唯一寫者)
  cron(台北時間,沿用現行時刻表)跑每日管線(docker)
  → export-json → cd cloudflare-data-worker && npx wrangler deploy
    (JSON 當 Worker 靜態資產上傳;內容 hash 去重只傳變動檔,數十秒生效)
  ※ 資料更新不觸發任何 Pages build/deploy,deploy 完即生效

【串接 — 一次性設定】
radar.techtrever.com/data/* → Cloudflare Worker(zone route)→ 回應隨附靜態資產
  Phase 1:Cloudflare Access 照舊擋在最前面(門鎖不動)
  Phase 2(WP-B7):Worker 驗 Supabase JWT + email 白名單,Access 退役

【備份】
每週:wal_checkpoint → integrity_check → gzip → rclone 上傳 Google Drive(單雲;GitHub 零資料)
```

**三個根因的解法**:①VPS 磁碟裝 4 年全歷史無壓力,2GB/10GB 上限與 WP-M3 拆分工程全部消失;②只剩一個寫者,不再有任何 DB 上下傳;③repo 轉 private + 資料只經 VPS→Worker 資產(有門禁)。

**明確不做**(2026-07-15 使用者確認):**不架 FastAPI、不架任何常駐 API/資料庫服務、不用任何需綁信用卡的服務(含 R2)**;VPS 不 build 前端、不開任何對外 port(裝 node **僅**為 wrangler 資料上傳,v3 放寬)。網站可用性不依賴 VPS 存活(VPS 掛=資料停更,網站照開)。重新考慮 API 的觸發條件記錄於 §11。

## 1. 設計原則

1. **單一寫者**:`radar.db` 只存在 VPS 一份;任何流程不得再把 DB 上傳/下載到雲端(備份快照除外,且快照永不被自動還原回線上路徑)。
2. **資料與部署解耦**:網站外殼(build 產物)不含任何資料;資料經 Workers 資產 deploy 即傳即生效。改前端=GitHub 的事;改資料=VPS 的事;兩邊互不等待、互不觸發。
3. **管線程式碼零改動**:`python -m radar <指令>` 介面不變;變的只是「在哪裡跑、產物送去哪」。
4. **金鑰只進 VPS `.env` / Cloudflare secret**(使用者既有定案),絕不入 repo。
5. **保留 WAL 教訓**:備份腳本 gzip 前必須 `PRAGMA wal_checkpoint(TRUNCATE)` + `integrity_check`——這條從 workflow 搬進 VPS 腳本,不是作廢。
6. **一次只換一個高風險零件**:遷移期間 Access 門鎖原封不動;登入統一(WP-B7)在遷移驗收後才動。
7. **可回滾**:切換後兩週內保留全部舊 workflow 檔與 Worker trigger 程式(停用不刪),回滾步驟見 §8。

## 2. VPS 排程設計(cron,台北時間)

時刻表沿用現行 Worker 時間(`docs/08` §0),**刻意不在遷移時順手改排程**——排程簡化(原 docs/20 Phase 4)等 B 案穩定後另案。

| Cron | 任務(對應現行 workflow) | 內容 |
|---|---|---|
| `10 14 * * 1-5` | daily-market | import-daily(日K+權證)→ aggregate-warrants → compute-indicators --days 5 → compute-scores → compute-performance → export-json → **deploy 資料(§3.1)** |
| `10 16 * * 1-5` | daily-insti | import-daily --datasets insti → import-warrant-master → compute-scores → export-json → deploy 資料 |
| `40 17 * * 1-5` | daily-branches 第1輪 | import-daily --datasets margin → import-branch-trades(池依 WP-B6 決策)→ compute-branch-stats → compute-scores → compute-performance → export-json → prune → deploy 資料 |
| `0 21 * * 1-5` | daily-branches 第2輪 | 補抓輪(同上,冪等) |
| `10 22 * * 1-5` | daily-margin | 融資券保底輪 → compute-scores → export-json → deploy 資料 |
| `10 1 * * *` | data-backfill | 深歷史增量(已拉深自動跳過) |
| `0 3 * * 6` | 週六全重算(可選) | --all 級重算常態化(首版可先不排,人工觸發) |
| `0 5 * * 6` | **備份** | wal_checkpoint → integrity_check → gzip → rclone 上傳 Google Drive(§4) |

實作規範:
- 每個 cron 項對應 `vps/scripts/` 下一支 shell script,內容 = `docker run --rm` 跑管線映像 + 失敗時 `curl ntfy.sh/$NTFY`(High priority)告警;成功靜默(或每日一則摘要,PoC 時定)。
- **管線映像**:新增 `pipeline/Dockerfile`(python:3.11 + requirements 烤進映像,比照 `pipeline/intraday` 的 radar-worker 作法),避免每輪 `pip install` 浪費 1–2 分鐘。`git pull` 拉到 requirements 變更時 rebuild。
- **互斥鎖**:所有會寫 DB 的 script 用 `flock -n /tmp/radar-db.lock` 包住;搶不到鎖=跳過本輪並 ntfy 通知(SQLite WAL+busy_timeout 本身可並行,flock 是防「上一輪超時未結束」堆疊的第二層保險)。長期歷史回補容器(WP-B6/WP-M4)**不拿這把鎖**——它與日常輪並行寫入已由 WAL 驗證可行。
- **VPS 也要 `git pull`**:cron script 開頭 `git pull --ff-only`(管線邏輯在程式碼裡,舊碼算出舊 reasons——既有教訓,見 STATUS 已知債務)。
- 非交易日:維持現行「靠 NoDataError 安全空跑」哲學,不手刻假日曆(既有定案,不翻案)。

## 3. 資料層與部署

### 3.1 資料熱更:export → wrangler deploy(不 build 前端、不動 Pages)

```
export-json 寫 web/public/data/(程式不改,輸出路徑照舊)
  → cd cloudflare-data-worker && npx wrangler deploy
    (web/public/data 整目錄作為 Worker 靜態資產;wrangler 以內容 hash 去重,只上傳變動檔)
  → 完成。前端下一次 fetch 就拿到新資料(數十秒生效)
```

- 免費額度:Workers 免費版 10 萬 req/日(≤10 人遠夠);資產單檔 25MB(現最大 ~0.5MB)、上限 2 萬檔(現 ~1,000+)。每日 5 次 deploy 遠低於平台限制。
- **快取策略**:Worker 回應 `radar.json`/`meta.json` 設 `Cache-Control: no-store`(榜單必須即時);個股 K 線等大檔設短 TTL(300s)——細節 WP-B2 實測定。

### 3.2 `/data/*` Worker(一次性,~40 行)

- Cloudflare Worker(`cloudflare-data-worker/`)以 **assets 模式**(`[assets] run_worker_first`)服務 JSON;zone route:`radar.techtrever.com/data/*`。**DB 快照不在資產內**(備份只走 Google Drive,§4),路徑上實體搆不到。
- 職責:把 `/data/x`、`/data-preview/x` 映射到資產 `/x` 回應(404 透傳、Content-Type/ETag/304 由資產層處理、Worker 覆寫 Cache-Control;拒絕 `..`/`//` 等異常 path)。**Phase 1 不做任何身分驗證**——Access 在更前面擋。
- 部署由 **VPS** 執行(資產目錄=export 產物,只存在於 VPS;金鑰見 §5.1)。首次 deploy 也在 VPS。
- **驗收必測**:未登入(無 Access session)直接 `curl https://radar.techtrever.com/data/radar.json` 必須被 Access 擋下(302 到登入頁),登入後正常回 JSON。若實測發現 Worker route 繞過 Access(理解上不會,但必須實測),fallback:Worker 內驗 Access JWT(`Cf-Access-Jwt-Assertion` header,官方標準做法),擋不住就不切換。
- 影響:`pages.dev` 網域下不再有 `/data`(Worker route 只掛自訂網域)——資料入口統一 `radar.techtrever.com`;盤中 worker 的 `RADAR_JSON_URL` 改自訂網域,並啟用其**既有**的 Access service token 支援(`CF_ACCESS_CLIENT_ID/SECRET`,worker.py 已內建,見 `vps_backfill_plan.md` 5-b)。

### 3.3 網站部署(GitHub,幾乎照舊)

- `deploy.yml` 保留 push 觸發,**刪掉** DB restore/seed、compute-scores、compute-performance、export-json 步驟——剩 checkout → npm build → wrangler pages deploy。push→上線 2–3 分鐘,與現狀相同。
- build 產物不含 `public/data`(該目錄本來就 gitignore,Actions 不再產生它)→ Pages 上不再有資料檔。
- repo 轉 private 後,code build 每次 ~2–3 分鐘,月用量 <100 分鐘,額度無虞。
- 5 支資料 workflow(daily-market/insti/branches/margin/data-backfill):cutover 時停用(保留檔案,拿掉觸發),兩週回滾窗後刪。
- Cloudflare Worker **trigger**(排程觸發器)退役;§5.3 建議改造為站外看門狗。

## 4. 備份與還原

| 層 | 內容 | 頻率 |
|---|---|---|
| 主本 | VPS `~/trever-radar/data/radar.db` | 即時(唯一真相) |
| 快照 | Google Drive `radar-YYYYMMDD.db.gz`(rclone gdrive remote,15GB 免費) | 每週六 05:00;保留最近 4 份 + 每月 1 份輪替 |

**單雲取捨(2026-07-15 v3 使用者定案)**:原 v2 的 R2 快照因綁卡門檻取消,備份=VPS 本機+Drive 共兩份。已知風險:**Google 帳號被鎖/誤刪時只剩 VPS 單份**——使用者知情接受。日後若要補第二朵雲,候選=Backblaze B2/MEGA(免卡、rclone 支援),加一行 `rclone copy` 即可,不動架構。

**GitHub 零資料原則(2026-07-15 使用者定案)**:git repo 與 release 平時**都不存放任何資料庫檔案**;`db-backup` release 只在回滾/災難(§8)時臨時上傳、事後即刪。就算日後 repo 再轉 public,也不存在可外洩的資料 asset。

- 備份腳本:`wal_checkpoint(TRUNCATE)` → `integrity_check` 必須 `ok` → gzip → 上傳;任一步失敗 ntfy High 告警。**integrity_check 不過的快照絕不上傳覆蓋舊版**。
- Drive retention:快照保留最近 4 份 + 每月 1 份(約 400MB×5≈2GB,15GB 免費額度內有版本與安全餘裕),超標優先刪最舊週份快照。
- **還原演練(WP-B4 必做)**:從 Google Drive 下載最新快照 → gunzip → integrity_check → 暫存目錄跑 `export-json` 比對線上 JSON。演練通過前,操作備份資料夾時不得刪除任何既有快照。
- **災難恢復認知**(為何週備份的 RPO 可接受):快照之後那幾天的資料幾乎全部可重建——日K/法人/融資券/權證走官方 `backfill --days N`,分點走 MoneyDJ 鏡像按日期補抓,指標/分數/績效重算即可。VPS 全滅的實際代價=「還原快照+重跑數小時回補」,不是資料永久損失。
- Google Drive 的 rclone OAuth token 存於 VPS `rclone.conf`,屬 VPS 側金鑰,同 §5.1 紀律。

## 5. 憑證、監控與維運

### 5.1 憑證清單

| 憑證 | 用途 | 存放 |
|---|---|---|
| GitHub fine-grained PAT | private repo `git pull` | VPS(既有) |
| Cloudflare API token(scope 只給 Workers Scripts: Edit + Zone Workers Routes: Edit) | 資料 worker `wrangler deploy` | VPS `vps/.env` |
| Google Drive OAuth token(rclone `gdrive` remote) | 週備份 | VPS `rclone.conf` |
| `CLOUDFLARE_API_TOKEN` + `ACCOUNT_ID` | Actions build 後部署 Pages | GitHub secrets(**既有,不動**) |
| `RADAR_FINMIND_TOKEN` | deep-backfill / adjust | 由 GitHub secret 改遷 VPS `.env` |
| Fugle / Supabase service key / Access service token | 盤中 worker(既有) | `pipeline/intraday/.env` |
| `NTFY` topic | 告警 | VPS `vps/.env` |

Worker trigger 的 `GH_TOKEN` PAT 在回滾窗結束後由使用者親自 revoke(退役後它失去日常用途)。**注意:VPS 不需要、也不得持有 Pages 部署權限的 token**——VPS 的 Cloudflare token scope 只能動 Workers scripts/routes,動不了 Pages/DNS/帳戶,資料與部署權限分離。

### 5.2 告警
- 每支 cron script 失敗 → ntfy High(含 script 名與 `docker logs` 提示)。
- 網站 `freshness` 標示(既有)持續作為使用者可見的最後防線。

### 5.3 站外看門狗(建議,解一條既有債務)
現行債務「Worker/GH_TOKEN 壞掉=靜默停更」在 B 案變成「VPS 掛=靜默停更」(VPS 死了連 ntfy 都發不出)。建議:退役的 Cloudflare Worker trigger **改造成 freshness 看門狗**——每日 22:30 fetch `radar.json`(帶 Access service token),`freshness` 落後 >1 個交易日就打 ntfy。站外(Cloudflare)監控站內(VPS),互相獨立。列 WP-B4 可選項。

### 5.4 日常維運 runbook(遷移後)
- 看狀態:`crontab -l`、`docker ps -a`、`tail ~/radar-cron.log`;手動補跑=直接執行對應 `vps/scripts/*.sh`。
- 緊急資料更新(VPS 掛掉時):任何機器以 Google Drive 最新快照還原 DB → 跑 export-json → `npx wrangler deploy` 即可(不需要碰 Pages);寫進 `DEPLOY.md`。

## 6. 遷移工作包(依序;每包動工前使用者確認)

### WP-B0 前置盤點與資源建立(人工為主,0.5 天)
- 【人工】Cloudflare:建 API token(scope 只給 **Account / Workers Scripts: Edit** + **Zone / Workers Routes: Edit**,zone `techtrever.com`;Dashboard → My Profile → API Tokens)。無需建任何 bucket、無需綁卡。
- 【人工】VPS:確認磁碟餘量(≥20GB)、`docker --version`、時區 Asia/Taipei(已設)、裝 node LTS(僅為 wrangler)、裝 rclone 並設 Google Drive remote(`gdrive`,一次性 OAuth)、`vps/.env` 填 `CLOUDFLARE_API_TOKEN`/`CLOUDFLARE_ACCOUNT_ID`。
- 【VPS 首次 deploy】確保 `web/public/data/` 有完整 export 產物後,`cd cloudflare-data-worker && npx wrangler deploy`(只掛 `/data-preview/*` 影子路由,不影響正式站)。
- 【Executor】新增 `pipeline/Dockerfile`、`cloudflare-data-worker/`(assets 模式 Worker+wrangler.toml)、`vps/.env.example`。(v2 R2 版已於 2026-07-15 改寫為 v3 assets 版)
- 驗收:`docker run radar-pipeline python -m radar --help` 正常;`rclone lsd gdrive:` 正常;登入 Access 後 `/data-preview/radar.json` 回 JSON、未登入被 302 擋。

### WP-B1 合規止血(可與 B0 並行,當日完成)
1. VPS 把現行 `radar.db.gz` 上傳 Google Drive(第一份快照,`rclone copy` 手動指令即可;上傳前 wal_checkpoint + integrity_check,回補寫入中不得直接 gzip)。
2. 【人工】刪除 **public** release `db-backup` 的 `radar.db.gz` asset(tag 留著)。
3. known risk(接受):止血後至 cutover 前,雲端鏈剩 Actions cache 單腿;cache 若被逐出,資料 workflow 會失敗、站台停更(不會壞資料)。因此 **cutover 目標 ≤1 週**。
- 驗收:release 頁面無資料 asset;`rclone ls gdrive:` 列得出快照且 integrity_check ok。

### WP-B2 VPS 管線 cron 化 + 影子驗證(Executor 1–2 天 + 影子跑 2–3 交易日)
- 寫 `vps/scripts/`(§2 各輪 + 備份)與 `vps/README.md`(安裝步驟:crontab 樣板、node/wrangler、rclone gdrive 設定、.env)。
- 影子模式:cron 全開,每輪照常 `wrangler deploy`;worker 只掛 `/data-preview/*` 路由(與正式 `/data/*` 讀同一份資產,但正式站 `/data` 仍由雲端鏈的 Pages 產物供應,互不干擾)。
- PoC 必測:①compute-branch-stats 在真實全量資料下的峰值 RAM(串流版合成測試 162MB,需真機確認,必要時加 swap);②單輪端到端耗時;③`wrangler deploy` 每輪實際上傳檔數與時長;④`/data-preview/radar.json` 經 Access 登入後可讀、未登入被擋。
- 驗收:連續 2–3 個交易日,shadow 的 `radar.json` freshness/榜單檔數與正式站一致(允許分鐘級時間差);所有 cron 無 ntfy 錯誤。
- 注意:影子期間雲端與 VPS 各自對來源站抓一份(雙倍請求但分屬不同 IP、各自守 1.2s 禮貌率),可接受的短期狀態。

### WP-B3 切換(cutover,半天,選交易日盤前;逐指令/diff 展開版見 `docs/32`)
1. Worker route 加掛正式 `/data/*`(解除 `wrangler.toml` 註解,VPS 重 deploy 一次)。
2. 【人工】Cloudflare Worker trigger:清空/停用 cron 觸發表(程式保留)。
3. `deploy.yml` 改純 build+deploy(§3.3);5 支資料 workflow 停用;push 一個 commit 驗證 code 部署鏈(此後 Pages 上無 /data,流量全走 Worker 資產)。
4. 盤中 worker `RADAR_JSON_URL` 改自訂網域 + 啟用 Access service token(`.env` 兩行)。
5. 【人工】repo 轉回 **private**。
6. 當晚驗收:正式站 freshness 全綠;14:10/17:40/21:00/22:10 各輪正常;**未登入 curl `/data/radar.json` 被 Access 擋**;登入後全站功能正常;盤中面板 worker 狀態 online。
- 回滾窗開始(兩週,見 §8)。

### WP-B4 收尾與加固(Executor 1 天)
- Google Drive 還原演練(§4)一次,結果記進 §12。
- 站外看門狗(§5.3,可選)。
- FinMind token 遷 VPS;雲端備援 task(themes/adjust/indicators-only)改為 VPS script 版。

### WP-B5 文件大同步(Executor 0.5 天,cutover 後儘快)
§9 退役清單逐項落文件:AGENTS.md 危險清單改寫(cache/release/WAL-workflow 條退役,換上「單一寫者不得破壞」「備份前 checkpoint+integrity_check」「資料與部署權限分離」)、`docs/08` §0 重寫為 cron 表、`DEPLOY.md`、`vps_backfill_plan.md`(Step 4e 上傳流程作廢)、STATUS.md。

### WP-B6 開跑 WP-M4 全市場歷史回補(依賴 B3 完成)
- **絕對前置**:修 `backfill_warrant_branches` 目標清單 bug(`docs/30` §3,importer.py:415–421——改為迴圈內按歷史日期撈當日活躍權證)。✅ **修正已完成並上分支 `wp-b6-warrant-branches-bugfix`(2026-07-15,未合 main)**:targets 查詢移入 `for d_iso in trade_dates` 迴圈內、以 `d.date = :d` 取代 `MAX(warrant_daily.date)`;新增種子 DB 回歸測試(對照組:還原成舊查詢會紅,證明測試抓得住這個 bug),既有 104 項 pytest + 46 subtests 不受影響。B3 cutover 完成、使用者確認後合入 main 即可直接開跑 B6,無需臨場再修。
- B 案下 M4 大幅簡化:**不再需要 docs/30 §4 的「補洞→上傳→放養」三步驟**——回補容器直接寫唯一主本,每晚 17:40 輪的統計與匯出自然把新累積的歷史帶上線。
- 池範圍(全市場一輪制,原 WP-M2)在此時一併切換:改 cron script 參數即可。

### WP-B7 登入統一(方向已定 2026-07-15;細部設計與實作需另過資安審查,B3 驗收後才可動工)
**使用者需求**:單一登入(Supabase Google OAuth,現有)、只有使用者認可的 Gmail 才能存取資料/特定功能、可按 email 做功能級授權;達成後 **Cloudflare Access 退役**。
**設計方向**(實作前由 security 流程細審):
- `/data/*` Worker 加驗證:前端 fetch 帶 Supabase JWT(Authorization header),Worker 以 Supabase JWKS 驗簽 + 查 email 白名單(Worker env/KV 或 Supabase 表),不通過回 401/403。
- 前端:JSON 讀取層(`web/lib`)統一加 token 注入與 401→導登入;未登入=看得到外殼與登入頁,看不到任何資料。
- 盤中 worker 等程式化存取:發專用長效 service secret(Worker 側白名單),取代 Access service token。
- 功能級授權:白名單表帶 feature flags(如 `intraday`, `branch`),Worker 依 path 前綴判定。
- **切換順序**:Worker 驗證上線並實測(未登入 403、白名單外 Gmail 403、白名單內正常)→ 觀察數日 → 才關 Access。Access 關閉前雙鎖並存(使用者會登兩次,過渡期接受)。
- **驗收紅線**:任何時點都不允許「未認證可抓到 /data」的空窗;`docs/21` 在本 WP 完成前仍為門禁 source of truth,完成後其 Access 章節標記退役。

## 7. 各工作包風險表

| WP | 主要風險 | 對策 |
|---|---|---|
| B1 | cache 單腿期被逐出→站台停更 | cutover ≤1 週;真發生就提前 cutover(影子已在跑) |
| B0/B3 | Worker route 意外繞過 Access(理解上不會) | B2 影子期就實測;擋不住則 Worker 驗 Access JWT fallback,驗不過不切換 |
| B2 | compute-branch-stats 真實資料 RAM 超標 | 串流版已修;超標則移週六輪或加 swap |
| B3 | cutover 當日兩邊都跑/都沒跑 | 順序固定「先切資料源、再停 Worker trigger」;當日人工盯 14:10 輪 |
| B3 | JSON 快取殘留舊資料 | radar.json no-store;其餘短 TTL;驗收含「更新後 5 分內前端可見」 |
| B7 | 驗證邏輯寫錯=資料裸奔 | 獨立 WP + security 審查 + Access 先不拆的雙鎖過渡 |
| 長期 | VPS 單點:磁碟壞=最多丟一週資料 | Drive 週快照;快照後幾天可 backfill 重建(§4 災難恢復認知) |
| 長期 | 備份單雲:Google 帳號被鎖=只剩 VPS 單份 | 使用者知情接受(§4);日後可加 B2/MEGA 一行補第二朵雲 |
| 長期 | VPS 靜默死機無告警 | §5.3 站外看門狗 |

## 8. 回滾計畫(cutover 後兩週內有效)

觸發條件:VPS 連續 2 個交易日無法完成任一主輪,且無法當日修復。
步驟:①VPS `radar.db` checkpoint+gzip 上傳 release `db-backup`(repo 已 private,不涉合規;屬 §4「GitHub 零資料」原則的例外臨時用途,回滾結束後該 asset 必須刪除);②重新啟用 5 支資料 workflow 與 Worker trigger cron 表;③`deploy.yml` 還原 DB/export 步驟(git revert 即可);④`gh cache delete --all` 讓雲端自 release 還原;⑤VPS cron 全停。
注意:repo 已 private,Actions 分鐘數受 2,000/月限制——回滾後需人工評估額度(必要時暫時再轉 public,**但 release 資料 asset 保持刪除狀態**,cache 單腿跑)。

## 9. 退役/凍結清單(WP-B5 落實)

| 對象 | 處置 |
|---|---|
| 5 支資料 workflow 的自動觸發 + deploy.yml 的 DB/export 步驟 | cutover 停用/刪步驟,回滾窗後刪 workflow 檔(git 歷史可考) |
| Cloudflare Worker trigger + 其 `GH_TOKEN` PAT | 停用;看門狗改造(可選)或 revoke |
| AGENTS.md 危險清單:WAL checkpoint workflow 條、cache/release 續存鏈條、DB 1GB 上限條 | 改寫(見 WP-B5) |
| `docs/26` WP-M3(branch_hist.db 拆分) | **取消**(B 案下無必要) |
| `docs/29` Phase 2 剩餘項(分點 130 日窗口、hist 拆分)與 §7 待決 2/5/6(R3/R4) | **作廢**;prune 之指標 400/權證 150/logs 180 維持——理由改為控制快照體積 |
| `docs/30` §4 三步驟上傳流程、§5 容量監控 | cutover 後作廢(WP-B6 取代);§3 權證 bug 修正**仍有效且必做** |
| `docs/20` Phase 4 排程簡化 | 吸收:B 案穩定後在 cron 層另案評估 |
| `docs/21` R2 計畫 R0–R2 | **作廢**(v3 不採 R2,綁卡門檻);快照職責由 Google Drive 承接(§4);Access 章節於 WP-B7 完成後標記退役 |
| 本檔 v1(VPS build+wrangler+輪詢部署) | 作廢,以本 v2 為準(git 歷史可考) |

## 10. 給接手 agent 的邊界(必讀)

1. 每個 WP 動工前需使用者明確說「開工」;不得因本檔存在就連續執行多包。
2. `pipeline/radar/*` 管線邏輯**零改動**(WP-B6 的權證 bug 修正除外);B 案是搬運不是重構。
3. 影子期間**不得**動正式 Pages 專案、正式 `/data/*` 路由、Actions cache、release(WP-B1 指定的 public asset 除外)。
4. 金鑰見 §5.1:VPS 側金鑰不進 repo/GitHub secrets;既有 GitHub secrets 回滾窗內保留不動;**VPS 永不持有 Pages 部署 token**。
5. VPS 上所有指令由使用者親手貼(比照 `vps_backfill_plan.md` 風格);Executor 產出 script 與逐步指令,不假設能直連 VPS。
6. WP-B7 屬資安敏感件:實作前需獨立資安審查,不得與其他 WP 合併執行,不得在 Access 拆除前留下任何未驗證空窗。
7. 遇到本檔沒覆蓋的決策 → 停下來問使用者,不自行拍板(docs/17 Workflow B)。

## 11. 決策紀錄

- 2026-07-14:Planner 分析出三根因;瘦身(docs/29 Phase 0/1/2)已落地、release 399MB。
- 2026-07-15:使用者定案 **B 案**;確認**不做 FastAPI/自架 DB 服務**。重新考慮 API 的觸發條件:①靜態檔數/體積撞 Pages 上限且裁剪無解;②出現無法預先匯出的自由參數全歷史查詢需求;③個人化資料量超出 Supabase 免費層。屆時第一優先為 Cloudflare Workers+D1/R2 方案,FastAPI 為最後選項。
- 2026-07-15(v2):使用者反饋 v1「VPS 輪詢 build+deploy」多此一舉、延遲不可接受、管控面過大 → 改為 **R2 資料層**:資料與部署解耦,GitHub push→deploy 維持現狀,VPS 不裝前端工具鏈。self-hosted runner 變體已評估並否決(多養常駐 daemon,無必要)。
- 2026-07-15:使用者提出以「認可的 Gmail 登入」取代 Access 做功能級授權 → 立項 **WP-B7 登入統一**(Supabase JWT + Worker 白名單,Access 於驗證通過後退役);與遷移分階段,不併行。
- 2026-07-15:備份定案「**GitHub 零資料**」——週快照 = R2 + Google Drive 兩個獨立供應商;GitHub release 僅回滾/災難時臨時上傳、事後即刪(§4/§8)。
- 2026-07-15(v3):使用者發現 **R2 啟用需綁信用卡**,定案不採用——資料層改 **Workers 靜態資產**(A 案,VPS `wrangler deploy`;B 案 VPS 直出經評估為多養常駐服務而否決),備份改 **Google Drive 單雲**(單雲風險知情接受)。VPS 為此裝 node+wrangler(僅資料上傳,不 build 前端);Cloudflare token scope 限 Workers Scripts/Routes Edit。

## 12. 執行紀錄(隨工作包更新)

- 2026-07-15 **WP-B0 完成**:Cloudflare API token(Workers Scripts/Routes Edit,zone 限 techtrever.com)、VPS `vps/.env`、node 22(dnf)、rclone gdrive remote(無頭 OAuth)、`radar-pipeline` docker 映像 build、首次 export-json(130 檔,與回補並行)+ `wrangler deploy` 成功;驗收兩測過(登入 Access 後 `/data-preview/radar.json` 回 JSON、無痕被 302 擋)。設定手冊落檔 `vps/README.md`。
- 2026-07-15 **WP-B1 完成**:manual-catchup 一條龍跑完(收舊容器、當日+近 6 日追補、全重算、影子 deploy 990 檔資產)→ weekly-backup 首份快照 `radar-20260715.db.gz` 上 gdrive(integrity_check ok + 上傳後回讀驗證)→ 刪除 public release `db-backup` 的 `radar.db.gz` asset(tag 保留;該 asset 為 07-14 21:21 由 VPS 回灌的舊快照,VPS 主本內容嚴格超集,刪前已查證)。雲端鏈自此進入 cache 單腿期(§7 已知風險,使用者接受),cutover 目標 ≤1 週。
- 2026-07-15 **WP-B2 Executor 件完成(影子驗證待跑)**:`vps/scripts/` 七件(lib.sh 共用 flock/ntfy/git-pull/docker/deploy + 五條每日輪鏡像 5 支 workflow 指令序 + weekly-backup.sh 含 integrity 紅線與 Drive retention)+ `crontab.example` + `cloudflare-data-worker/package.json`(釘 wrangler 版本,cron 不打 registry);`bash -n` 全過、retention awk 邏輯單測過。crontab 七條已掛、ntfy 已訂閱實測通(07-15);flock 保護已實戰驗證(catchup 持鎖期間 daily-branches 輪正確跳過並通知)。**影子驗證自 07-15 起跑**,第一發實彈 = 07-15 22:10 daily-margin(成功,`margin` freshness 當日、stale:false);驗收 = 連續 2–3 交易日 `/data-preview/radar.json` 與正式站一致(清單 `vps/README.md` §9)。
- 2026-07-15 **WP-B3 cutover 彈藥備妥(草稿,未執行)**:落檔 `docs/32_wp_b3_cutover_runbook.md`,把 §6 WP-B3 六步驟展開成逐指令/diff(Worker route 解註解、trigger crons 清空、deploy.yml diff、intraday `.env` 三行、repo private 人工步驟、當晚驗收清單含未登入必須被擋的紅線測試)。同時完成 WP-B6 絕對前置的權證 bug 修正(見上,分支 `wp-b6-warrant-branches-bugfix`)。兩者皆未合 main/未執行,等 WP-B2 驗收通過 + 使用者喊開工。
- 2026-07-16 **盤中 worker 首次 live smoke test 炸出 API 飄移,已修**(commit `fcb3aef`,獨立於 B 案但同一台 VPS):`fugle-marketdata` 套件版本飄移導致 `connect()/subscribe()` 官方已改同步呼叫(worker.py 07-12 寫成 await 出 TypeError)、WebSocket callback 給原始 JSON 字串而非 dict(`message.get()` 出 AttributeError)。兩者皆修,補回歸測試,pytest 104 全過。
- 2026-07-18 **WP-B2 影子驗證驗收通過 + 盤中 worker 確認常態化**(使用者確認,非 agent 直接觀測):連續多個交易日(07-16/07-17)shadow `/data-preview/radar.json` 與正式站一致、ntfy 無 High 告警;盤中 worker 修完 bug 後已跟上盤中實跑、cron 常態化,首頁盤中面板穩定顯示 online。**WP-B3 cutover 前置條件全數滿足**,待使用者敲定執行日(docs/32 建議選交易日盤前)。
- 2026-07-18 **WP-B3 cutover 執行中(使用者同日喊開工,選在假日執行——理由:VPS 資料鏈已驗證健康,週末無實彈交易輪,可在週一 14:10 第一輪前有更充裕的觀察/修復緩衝)**:Agent 側 Step 1–3 已完成並 push——`cloudflare-data-worker/wrangler.toml` 解除 `/data/*` 路由註解(commit `109c8ad`)、`cloudflare-trigger/wrangler.toml` 清空 `crons`(worker.js 保留,回滾窗內)、`deploy.yml` 精簡為純 checkout→build→wrangler pages deploy(移除 DB restore/seed/compute-scores/compute-performance/export-json,push 後驗證 1m1s 成功、無資料步驟)。**Step 1/2 兩個 Worker 的 `wrangler deploy`、Step 4 intraday `.env` 改 `RADAR_JSON_URL`、Step 5 repo 轉 private 為使用者 VPS/瀏覽器操作,待回報後 Agent 執行 Step 6 未登入驗證並收尾**。同日一併合入 WP-B6 絕對前置的 `backfill_warrant_branches` bug 修正(分支 `wp-b6-warrant-branches-bugfix` 已合併刪除,commit `4ea5f95`,pytest 105 全過)。
- 2026-07-18(晚)**WP-B3 cutover 收尾驗證:Step 1-5 全落地,發現 Actions Billing 阻斷**:使用者回報 VPS/瀏覽器側完成(兩個 Worker deploy、intraday `.env`、repo 轉 private——`gh repo view` 確認 `visibility: PRIVATE`)。Agent Step 6 驗證:①紅線通過——未登入 curl `radar.techtrever.com/data/radar.json`、首頁、`trever-radar.pages.dev/data/radar.json` 全部 302;②5 支資料 workflow 於 07-17 之後零觸發(trigger cron 停用生效);③cutover commit 的 deploy 成功(純 build 1m4s)。**遺留:repo 轉 private 後 Actions 被帳戶帳務擋下**——其後 3 次 deploy 全部 3 秒 instant-fail 零 step,annotation「The job was not started because recent account payments have failed or your spending limit needs to be increased」;僅擋程式碼部署,資料鏈(VPS→Worker assets)不受影響;待使用者修 GitHub Billing & plans 後 re-run 驗證。其餘 Step 6 項目(登入後 freshness/全站功能、VPS cron log、盤中 worker 隔日 08:55 online)待使用者確認;全過後回滾窗兩週倒數(§8),接排 WP-B5。
