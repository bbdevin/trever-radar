# 專案狀態(2026-07-10)

> 單一進度真相。每完成一個里程碑就更新本檔。規格細節看各編號文件,別寫在這裡。

## 上線資訊

| 項目 | 值 |
|---|---|
| 正式網址 | https://radar.techtrever.com(= https://trever-radar.pages.dev) |
| 公開狀態 | 公開網址、noindex + robots.txt;Access 未開(使用者決定,要鎖照 DEPLOY.md §4) |
| 自動排程 | GitHub Actions 6 支 workflow(現行時間表以 `docs/08_scheduler_jobs.md` §0 為單一真相):14:10 `daily-market`、16:10 `daily-insti`、17:40+21:00 `daily-branches`、22:10 `daily-margin`(融資券保底輪)、每日 01:10 `data-backfill`、push main 觸發 `deploy`;各帶 timeout 防呆與共用 `radar-db` cache 續存鏈;觸發來源遷移中,見下方已知債務 |
| Repo | github.com/bbdevin/trever-radar(私有) |
| DB | SQLite,Actions cache 續存 + release `db-backup` 週備份(週五/手動觸發時) |

## AI Workflow Status

2026-07-09 起,本專案開發流程改為**不依賴 Fable 或任一單一模型**的多 agent 協作,完整規則見根目錄 `AGENTS.md`、`docs/17_no_fable_workflow.md`、`docs/18_handoff_template.md`。

- **Claude Code**:主力執行者(有額度時)。
- **AGY(Google model)**:fallback planner / secondary executor,Claude Code 沒額度時接手,不擴張 MVP、不重寫架構。
- **Codex**:independent reviewer,只 review git diff/安全性/測試覆蓋,不代表可自動 merge。
- **Cursor**:IDE 控制中心,看檔案、看 diff、管 branch、人工確認。
- **人類使用者**:唯一能決定 merge / deploy / 架構變更 / 資料刪除重建的人。

下一步:先完成 AI workflow 文件整理本身(本次任務),之後功能開發任務排序仍照本檔「未完成(依優先序)」清單走,**不因引入多 agent 流程而直接大改既有功能**。

## 已完成 ✅

### 資料管線(pipeline/,Python + SQLite)
- [x] TWSE/TPEx 日K + 權證每日成交(全市場,每日 2 請求)
- [x] 法人買賣超(T86 / TPEx insti)、融資融券、匯入紀錄與健檢基礎(import_logs)
- [x] `backfill`:官方端點回補近 240 交易日(已完成)
- [x] `deep-backfill`:FinMind 上市以來全歷史(每檔 1 請求;榜單股已拉,全市場待跑)
- [x] `import-stock-info`:官方產業別(FinMind TaiwanStockInfo)
- [x] `import-warrant-master`:權證主檔(TWSE t187ap37_L + TPEx OpenAPI;標的/履約價/行使比例/到期日;TWSE 以名稱反查代號,匹配率 94.5%)
- [x] `aggregate-warrants`:warrant_stock_daily 彙總(認購/認售金額量檔數,排除牛熊證;已回填 240 日,每晚增量)
- [x] `export-json`:radar/meta/個股 K 線 JSON + 權證異動榜 + 個股權證 60 日趨勢/熱門權證明細
- [x] `compute-adjustments`:用 FinMind `TaiwanStockDividendResult` 免費資料計算 `daily_prices.adj_factor`(除權息前後價比累乘;已用 2330 實測)
- [x] `compute-indicators`:以還原價計算 MA5/10/20/60、RSI14、KD、MACD、20日新高、60日箱型、ADV20、volume_ratio、tech_score、reasons/risks
- [x] `import-branch-trades`:富邦公開頁分點進出(每股前15大買/賣超,張+佔比;每晚評分池80檔;2026-07-07 起累積)
- [x] `import-themes`:概念股分類爬蟲(富邦 zha/zhc,~1,060 類含矽晶圓/AI晶片等細分)→ themes/stock_themes;每週一自動更新;首次全量走 data-backfill task=themes
- [x] 首頁資金流向改版:**Treemap 熱力圖**(大小=金額、紅綠=漲跌、▲▼=vs20日量能流入/流出)+ 產業/題材雙模式 + 流入/退潮領頭 chips + 點格下鑽成分股 + **資金量能與漲跌幅排序切換** (可秒看族群性大漲/大跌)
- [x] 股票卡資訊優化:移除干擾性的評分細項、新增動態 **概念股題材標籤 (Themes)** 與 **公司基本業務說明 (Description)**，並採用 `UI/UX Pro Max` 設計美學。
- [x] 波段二(docs/14):**日K/週K/月K 切換**(前端重取樣,指標自動變週/月線)、**全站搜尋**(/ 快捷鍵,索引 2,470 檔,個股 JSON 池擴至評分池 959 檔、非榜單裁 600 根)、**權證分點張數**(每晚抓成交前 15 大上市權證,個股頁權證列可展開分點進出;上櫃權證無免費來源)
- [x] K 線圖升級:均線 5/10/20/季/半年/年 + 布林(預設開、可勾選關、localStorage 記偏好)、副圖 MACD/KD/RSI 切換、十字游標 OHLC+均線 legend、指標以全歷史計算再切區間
- [x] `compute-scores`:盤後綜合分數(分點35/權證20/技術20/法人15/題材10 加權;風險扣分:短線過熱/爆量長上影/開高走低/RSI過熱/外資連賣/融資過熱;法人買超設佔成交量1%顯著性門檻)→ `daily_scores` + 理由/風險 JSON;首頁「綜合」榜(預設 tab)
- [x] `branch_score`:分點籌碼分 V1 接入綜合分(04 §2):連買、多分點同步、買方集中度、大戶淨流、反手倒貨風險;使用富邦公開頁前15大買賣超裁剪資料,地緣/關鍵分點待人工名單
- [x] `compute-performance`:訊號績效回填,以次一交易日還原開盤價為 entry,回填 `daily_scores` 的 fwd_1d/3d/5d/10d/20d 報酬;nightly/push 皆會更新已成熟訊號
- [x] upsert 只更新帶入欄位(防止日常匯入洗掉補充欄位)
- [x] SQLite WAL + busy timeout(回補與匯出可並行)

### 前端(web/,Next.js 15 靜態輸出)
- [x] 今日雷達:市場總覽卡、**族群資金流面板**(產業別金額佔比 / vs20日均 / 廣度 / 龍頭)、**綜合/熱門/爆量/強勢/權證/Mark策略六榜**
- [x] 股票卡:權證認購成交金額、20日倍數、購售比、成交檔數摘要
- [x] 個股頁:上市以來 K 線 + 成交量(lightweight-charts)、區間切換 1月/3月/1年/5年/全部、**權證 Tab**(60 日認購/認售金額趨勢 + 當日熱門權證明細)
- [x] 個股頁:**分點 Tab**(分點分、分點觸發理由/風險、當日前15大買賣超分點明細:買張/賣張/淨張/佔比)
- [x] 個股頁 K 線疊加 MA5/20/60,下方顯示技術分、MA20/60、RSI14、量比與觸發理由
- [x] 現代 fintech UI:深色、玻璃頂欄、手機底部導航、SVG 圖示、Manrope 數字字體、骨架屏、RWD 375–1440
- [x] 台股慣例紅漲綠跌、免責聲明常駐
- [x] **觀察價/失效價**(2026-07-10,04 §10):`daily_scores` 新增 `watch_price`/`stop_price`,股票卡與個股頁技術面板顯示
- [x] **自選股**(2026-07-10):Supabase `watchlist` 表 + RLS(見 `docs/sql/watchlist.sql`,需人工在 Supabase 執行一次);全站 Context 只查一次、卡片與個股頁 ★ 按鈕、新頁 `/watchlist`
- [x] **探索頁**(2026-07-10,部分):新頁 `/explore`,先做**集中度**(前5大買超分點佔量躍升排行,新純函式 `buy_concentration` 從既有 B3 評分邏輯抽出)與**題材**(重用首頁資金流 `themes` 資料)兩個 tab;地緣/關鍵分點/分點績效榜/權證異動因需人工名單或與 `/branch` 重疊,暫緩

### 基礎設施
- [x] **凌晨長任務常態化**:data-backfill 每天 01:10 深歷史增量(已拉深跳過,日常近零請求);週六 01:10 加跑全市場還原因子 + 指標全重算 + DB 備份;排程總表 = docs/08 §0
- [x] **分批即時更新**:14:10 收盤閃電更新(日K+權證+指標+分數→部署,資料日當天變今天)→ 16:10 法人+權證主檔 → 17:40 融資券+分點全量 → 21:00 補抓;各資料集「有效日」寫進 radar.json `freshness`,晚公布的前端標「今日尚未公布,暫用前一日」並以前一日數值填充
- [x] 管線效能優化(docs/15):指標增量計算(`--days 5`,全市場 26 秒,原全歷史重算數十分)、release 備份週五化(原三支 workflow 每日各 gzip 1GB)、修正 daily-warrants/branches 繞過 cache 的分岔 bug、pip/npm 快取
- [x] GitHub Actions 全自動管線 + Cloudflare Pages 部署 + 自訂網域
- [x] `main` push 觸發正式部署;push 事件跳過資料匯入,只用 cache/release DB 匯出 JSON、build、deploy
- [x] FinMind 免費 token(600 req/hr,`RADAR_FINMIND_TOKEN`,GitHub secret 已設)
- [x] **排程觸發改用 Cloudflare Worker**(2026-07-09):GitHub 原生 `schedule:` 實測延遲 2.5–3.5 小時,6 支資料 workflow 已全數改為 `workflow_dispatch:` only,由 `cloudflare-trigger/`(單一 10 分鐘 cron trigger + 程式碼比對時間表,繞開 Cloudflare 免費方案 3/Worker、5/帳號 的 cron 上限)準時觸發;新增 `daily-margin`(22:10 台北,融資券保底輪)

## 未完成(依優先序)

1. ~~探索頁、自選股、觀察價/失效價~~ **2026-07-10 完成基本版**(見上方已完成);探索頁地緣/關鍵分點/分點績效榜/權證異動 4 個 tab 仍缺,待人工名單或與 /branch 整合的決定
2. ~~deep-backfill --all~~ **執行中**:FinMind 註冊 token(600/hr)已設本機+雲端 secret;`data-backfill` workflow(手動觸發)正在雲端跑全市場上市以來歷史(約 4.5 小時,可中斷續跑);完成後手動觸發 `task=adjust` 補全市場還原因子:`gh workflow run data-backfill -f task=adjust`
3a. **分點資料擴容**(2026-07-08,docs/vps_backfill_plan.md 修訂版):MoneyDJ 鏡像輪替(富邦+元富,可擴)、每日池 80→**500 檔**(--sleep 1.2)、`backfill-branches` 歷史 march-back(斷點續傳+限時)已接凌晨 01:10,約一週自動補齊 Top300×60 交易日;VPS 為加速選項非必需。首頁新增**弱勢榜**;/branch 新增**權證分點 tab**(近40日對單一權證淨買 ≥300 張);修 /stock/ 與 /branch/ 死連結
3. **分點排行與追蹤**(規格 docs/13):資料已解鎖且分點分已接入——`import-branch-trades` 每晚爬富邦公開頁(評分池前 80 檔前 15 大買賣超),`branch_trades` 累積中。待做:今日動向頁 → branch_stock_stats → 可信度排行榜(需累積 2–3 個月才有統計效力)→ 地緣/關鍵分點人工名單
4. V2 盤中(Fugle + 本機 worker)

## 已知債務 / 注意

- **分點 5 年全量的架構前置**(vps_backfill_plan §3 P2 之前必做):DB 將 +7–9GB → 炸 release 單檔 2GB 與 Actions cache 10GB → 分點歷史拆 branch_hist.db 或搬 Cloudflare R2(免費 10GB);P1(2年,+1.5GB)還安全

- 個股 JSON 一檔約 0.5MB(全歷史);擴到數百檔時改「預設 5 年 + 按需載入」
- 權證榜目前是「認購成交金額 / 20 日均值」的異動排序,尚不是 04 定義的完整 0–100 權證分;完整分數與 reasons/risks 等評分模組一起做
- 權證 warrant_daily 約 1,000 萬列/年增速;彙總表已建,依 05 規劃明細僅留 2 年(清理排程未寫)
- 還原價資料層已完成,但尚未接 nightly 全市場自動跑;目前用 `compute-adjustments --ids/--top/--all` 手動或分批補。`TaiwanStockPriceAdj` 是付費資料,本案改用免費 `TaiwanStockDividendResult` 自算
- 技術指標已接 nightly `compute-indicators --all`;若某些股票尚未補還原因子,會先以 `adj_factor=1` 計算,之後補因子再重算即可
- 已下市權證不在主檔,kind 靠代號尾碼推斷可能誤標(認售尾碼不只 P,還有 T/Q/S 等)→ 歷史認購/認售比略失真;認售佔比極低,影響小
- 評分門檻(65 分觀察線、法人 1% 顯著性、權證倍數分段)為 04 起始值,待訊號績效回填後校準;目前寧缺勿濫,達標日常 0–5 檔屬預期
- 分點分 V1 只用「已抓到的前15大買賣超」,不是全市場全量分點;冷門股或未入評分池股票沒有分點史,地緣/關鍵分點/可信度分數尚未納入
- `compute-adjustments` 逐列 UPDATE,跑 --all 會慢;改 executemany 批次後再跑全市場
- Actions 有 Node 20 → 24 的 deprecation 警告(actions 版本升級,無急迫)
- **排程觸發改 Cloudflare Worker,無備援(2026-07-09)**:見 `cloudflare-trigger/README.md`。Worker 或 `GH_TOKEN`(存於 Cloudflare secret 的 fine-grained PAT)一旦壞掉會靜默停止觸發,網站不會報錯只會停止更新——前幾週要偶爾看一下 `gh run list` 或首頁 freshness。`GH_TOKEN` 是每天實際在用的憑證,**不可直接 revoke**,輪替流程見該 README。假日跳過邏輯評估後**決定不做**:管線在非交易日已靠 `NoDataError` 安全空跑(`importer.py` 的 `_run()` 接住例外記 log,不會壞資料),手刻假日曆的「錯殺交易日」風險大於省下的 Actions 分鐘數
- 本機 dev 與雲端 DB 已分岔:雲端為正式真相,本機僅開發;push 部署會從 Actions cache/release DB 產出線上 JSON

## 最近完成

- 2026-07-07 `842b4e0 feat: add warrant radar UI`:首頁新增權證榜,股票卡/個股頁接上權證摘要、趨勢與熱門權證明細。
- 2026-07-07 `ed363b1 ci: deploy site on main push`:正式分支 push 會觸發 Cloudflare Pages 部署;已確認 GitHub Actions `nightly-radar` push run 成功。
- 2026-07-07 還原價資料層:新增 `daily_prices.adj_factor`、SQLite additive migration、`compute-adjustments` CLI、單元測試;2330 實測 6 筆除息事件/8031 日價列更新成功。
- 2026-07-07 技術指標資料層/UI:新增 `indicators_daily`、`compute-indicators`、技術分 reasons/risks、MA5/20/60 K 線疊線與個股頁技術摘要;本機 Top80 實算 18.5 萬列成功。
- 2026-07-08 訊號績效回填:新增 `daily_scores` entry/fwd 欄位、`compute-performance` CLI、單元測試與 nightly step;以次日還原開盤價進場、後續第 1/3/5/10/20 個交易日收盤回填報酬。
- 2026-07-08 分點籌碼分:新增 `daily_scores.branch_score`、`score_branch` 純函式與測試;綜合分權重改為分點35/權證20/技術20/法人15(題材10暫缺自動重分配),首頁卡片顯示分點分。
- 2026-07-08 分點 UI 補齊:個股 JSON 輸出 `branches/scores/reasons/risks`,個股頁新增分點 Tab 顯示分點分、理由、風險與前15大買賣超明細。
- 2026-07-08 題材分數接入:新增題材熱度評分純函數 `score_themes`、更新評分權重（加入題材 10% 權重）、個股頁/卡片 UI 整合與單元測試。
- 2026-07-08 籌碼日報:在個股頁分點 Tab 擴充籌碼日報功能，包含 1-240 日/自訂天數的前 13 大分點買賣超聚合計算，實作 Bento Grid 科技感 UI 與點擊展開的分點紅綠柱狀圖。
- 2026-07-08 分點排行與管線優化: 完成 `/branch` 頁面實作（含勝率排行與今日動向），並正式將 GitHub Actions 拆解為 `daily-market`、`daily-warrants`、`daily-branches` 三條獨立管線，同時新增了 `deploy` 管線負責 Push 時的即時部署。
- 2026-07-08 系統穩定度修正: 修正首頁動態榜單數量邏輯（無論行情好壞皆保底 15 檔，上限 40 檔避免過長）；修復 GitHub Actions 併發限制導致的管線互相取消問題，並將每日抓取管線 Timeout 時間全面延長至 30~40 分鐘。
- 2026-07-08 Mark策略演算法與獨立榜單: 新增「Mark策略」演算法（20日內漲停、5日內爆量、MACD零上金叉），於 `indicators.py` 中進行嚴格判定，並在前端首頁新增獨立的「Mark策略」頁籤。
- 2026-07-09 排程觸發改 Cloudflare Worker:實測發現 GitHub 原生 `schedule:` 延遲 2.5–3.5 小時,新增 `cloudflare-trigger/`(Cloudflare Worker,單一 10 分鐘 cron + 程式碼比對時間表)取代;4 支既有 workflow 拿掉 `schedule:`,新增 `daily-margin.yml`(22:10 台北融資券保底輪);修正隨手發現的 `daily-branches`/`data-backfill` 備份步驟隱性依賴 `event_name=='schedule'` 的 bug(原本手動觸發會意外覆蓋週備份);Worker 已部署並以 `gh run list` 驗證觸發成功;修補 Worker `fetch()` 端點原本無驗證可被任何人觸發 workflow 的漏洞,加上 token 驗證。
- 2026-07-10 觀察價/失效價 + 自選股 + 探索頁(集中度/題材):`daily_scores` 新增 `watch_price`/`stop_price`/`buy_concentration`/`concentration_avg20`(additive migration);純函式 `watch_stop_prices`/`buy_concentration` 各有單元測試,`buy_concentration` 從既有 B3 評分邏輯抽出重用;`export-json` 帶出至股票卡/個股頁/新的 `radar.json.concentration` 榜;前端新增 Supabase-backed 自選股(`web/lib/watchlist.tsx` Context + `WatchlistButton` + `/watchlist` 頁,需人工執行 `docs/sql/watchlist.sql` 建表)與 `/explore` 頁(集中度+題材 2 個 tab,地緣/關鍵分點/分點績效榜/權證異動因人工名單或與 `/branch` 重疊而暫緩);全專案 `npm run build`(含 static export)與 16 項 pytest 皆過。

## 系統模組與功能對應表 (Pipeline Models Mapping)

| Pipeline Module (CLI) | 實作的系統功能 |
|---|---|
| `import-daily` | 每日市場收盤價 (`quotes`)、三大法人買賣超 (`insti`)、融資融券餘額 (`margin`) |
| `import-warrant-master` | 每日發行的權證主檔更新，用於配對標的與到期日 |
| `aggregate-warrants` | 每日計算個股認購/認售權證的總成交金額與量比，輸出至首頁權證榜 |
| `import-branch-trades` | 每日下午抓取盤後分點前 15 大進出明細，支撐籌碼日報與分點評分 |
| `import-themes` | 每日/每週抓取概念股與產業題材分類，用於首頁熱力圖與題材分 |
| `compute-indicators` | 計算還原價 MA5/10/20/60、RSI、MACD、乖離率等技術指標 |
| `compute-scores` | 綜合評分引擎 (分點35/權證20/技術20/法人15/題材10)，產生分數與理由/風險 JSON |
| `export-json` | 根據動態閾值產生各類排行榜單 (hot, surge, strong, warrant)，與單檔股票明細 (K線、分點) |
