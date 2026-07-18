# 專案狀態(2026-07-18)

> 單一進度真相。每完成一個里程碑就更新本檔。規格細節看各編號文件,別寫在這裡。

## 上線資訊

| 項目 | 值 |
|---|---|
| 正式網址 | https://radar.techtrever.com(= https://trever-radar.pages.dev) |
| 公開狀態 | **已鎖站(私人測試版)**:2026-07-13 使用者於 Cloudflare Zero Trust 手動完成 Access A0-A2(Google IdP + email 白名單,單一 Application 覆蓋 custom domain / pages.dev / preview 三類入口),執行紀錄見 `docs/21` §4 A3。noindex + robots.txt 保留。首份 Google Drive 快照 `radar-20260715.db.gz` 已於 2026-07-15 建立(integrity_check ok)。 |
| 自動排程 | GitHub Actions 6 支 workflow(現行時間表以 `docs/08_scheduler_jobs.md` §0 為單一真相):14:10 `daily-market`、16:10 `daily-insti`、17:40+21:00 `daily-branches`、22:10 `daily-margin`(融資券保底輪)、每日 01:10 `data-backfill`、push main 觸發 `deploy`;各帶 timeout 防呆與共用 `radar-db` cache 續存鏈;觸發來源遷移中,見下方已知債務 |
| Repo | github.com/bbdevin/trever-radar(私有) |
| DB | SQLite。**2026-07-15 起雙軌**:雲端鏈 = Actions cache 續存(**cache 單腿**——release `db-backup` 資料 asset 已依 WP-B1 刪除,GitHub 零資料);VPS 主本 = 唯一長期真相,備份 = VPS 本機 + Google Drive 週快照(`docs/31` §4)。cutover(WP-B3)後雲端鏈退役 |

## AI Workflow Status

2026-07-09 起,本專案開發流程改為**不依賴 Fable 或任一單一模型**的多 agent 協作,完整規則見根目錄 `AGENTS.md`、`docs/17_no_fable_workflow.md`、`docs/18_handoff_template.md`。

- 流程為**模型中立、角色導向**:Planner / Executor / Reviewer 由本次任務指定,不由模型品牌永久決定;規則見 `AGENTS.md` 與 `docs/17_no_fable_workflow.md`。
- 工具清單:Claude Code、AGY/Gemini、Codex、GPT/Grok 等高階模型均可任三角色;Cursor 為 IDE / 確認介面;人類使用者為唯一決策者。

下一步:**資料架構 B 案遷移**(`docs/31` v3,2026-07-15 使用者定案;同日因 R2 需綁卡改「Workers 靜態資產資料層 + Google Drive 單雲備份」,全程免綁卡):radar.db 常駐 VPS 單一寫者、雲端資料鏈退役、repo 轉回 private——WP-B0 人工步驟與 WP-B1 進行中。其後依 `docs/20` B 方案完成策略解耦與績效閉環。

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
- [x] **分點追蹤視角**(2026-07-11,docs/24 Part B B1+B2):export 為每個 tracked branch(manual+auto)產 `branches/track/{hash}.json`(近 120 日曆日的緊湊 `[date,stock_id,net_lots,pct]` 列 + 股名/期末收盤對照;檔名為 branch_name 的 sha1 前 16 碼,index.json 列對照)+ 種子 DB 單元測試;前端 `/branch` 排行榜點分點卡片(或「分點追蹤視角」鈕)切入同 tab 視圖,近 1/5/10/20/自訂日 pills(自訂 clamp 可用交易日數),客戶端純函式 `aggregateBranchRows` 加總出淨買超/反向賣超表(語意化 table、估算金額 net×1000×close、平均佔比),誠實限制標注;`npm run build` 過、pytest 全過、聚合 3 案例 node 驗證通過,未新增依賴/未改 token。
- [x] **WP-V1 首頁/自選 5 秒掃讀優化**(2026-07-11,docs/23 §2 V1):股票卡次要細項(金額/量比/外資/投信)由 4 欄堆疊收斂成一行小字降層級(不刪資料);卡片左側 3px inset 狀態色條(有明顯風險扣分→destructive/風險紅、綜合分≥65 觀察門檻→warn/琥珀、其餘→中性 line,僅用既有 token 且色條非唯一訊號);自選/branch 可點列補 `min-h-11`+`cursor-pointer`+`transition-colors`,★ 鈕與 branch 展開鈕補 `aria-label`/`aria-expanded`;首頁教育性空狀態文案、`/watchlist` 載入改多列 Skeleton;`npm run build` 過,未新增依賴/未改配色 token 語意。
- [x] **UI 全面遷移 Tailwind CSS v4 + shadcn/ui**(2026-07-10):全站 6 頁 + 所有元件從手刻 CSS class 改為 Tailwind utility(僅保留 `.container`/`.num`/裸 `.up`/`.down`/`.flat`/`fadeUp` keyframe 等仍被動態或跨頁共用的少量 class);icon 除品牌 logo 外全改 `lucide-react`;搜尋面板改 shadcn `Command`,登入選單改 `DropdownMenu`,個股頁權證明細表改 **TanStack Table**(可排序 + 展開列);K 線圖仍為 lightweight-charts(未改動);deep design token 對照見 `docs/07_frontend_pages.md`。過程中修掉兩個遷移期間才會暴露的既有 bug:①舊 `.grid` class 與 Tailwind 內建 `grid`/`grid-cols-*` utility 同名碰撞(unlayered 規則蓋過 layered utility),導致多處 4 欄版面被壓成 3 欄;②`@theme inline` 的 `--color-border`/`--color-accent` 一度被誤指到 legacy token,深色模式因數值巧合未現形但會壞掉淺色模式。深色為預設主題,淺色 token 已備妥;**2026-07-11(docs/23 V3.1)已加頂欄 `ThemeToggle` 切換 UI**(接既有 `.dark` class 機制、`localStorage` 記偏好、`<body>` 開頭 inline script 防 FOUC,預設仍深色)。**淺色對比已於 2026-07-12 補強**:被當文字色用的 brand-extension token `--ink-2`/`--warn`/`--accent-2`/`--legacy-accent` 改為雙主題定義(`:root` 淺色可讀值對白 4.9–6.5:1、`.dark` 保留原深色調值,深色逐位元不變);`--up`/`--down` 刻意兩主題一致不覆寫。KChart 格線/軸/水印色亦補淺色組(`chartColors(isDark)` + MutationObserver 即時切換)。

- [x] **Armed 狀態追蹤**(2026-07-12,docs/22 A1-A2):實作於 `json_export.py`，基於 S12 分點與權證 W1 訊號推導 Armed (未發動) 與 Triggered (已發動) 兩大狀態池。首頁 Tab 收斂後將狀態池前置，並依據 `ui-ux-pro-max` 規範在股票卡片加入 `lucide-react` 狀態徽章 (ShieldCheck/Zap)，不新增資料表，即時運算輸出。

### 基礎設施
- [x] **凌晨長任務常態化**:data-backfill 每天 01:10 深歷史增量(已拉深跳過,日常近零請求);週六 01:10 DB 備份(**週六全市場還原因子+指標全重算已於 2026-07-10 停用,改 VPS 跑後回灌,雲端 fallback=手動 task=adjust**);排程總表 = docs/08 §0
- [x] **分批即時更新**:14:10 收盤閃電更新(日K+權證+指標+分數→部署,資料日當天變今天)→ 16:10 法人+權證主檔 → 17:40 融資券+分點全量 → 21:00 補抓;各資料集「有效日」寫進 radar.json `freshness`,晚公布的前端標「今日尚未公布,暫用前一日」並以前一日數值填充
- [x] 管線效能優化(docs/15):指標增量計算(`--days 5`,全市場 26 秒,原全歷史重算數十分)、release 備份週五化(原三支 workflow 每日各 gzip 1GB)、修正 daily-warrants/branches 繞過 cache 的分岔 bug、pip/npm 快取
- [x] GitHub Actions 全自動管線 + Cloudflare Pages 部署 + 自訂網域
- [x] `main` push 觸發正式部署;push 事件跳過資料匯入,只用 cache/release DB 匯出 JSON、build、deploy
- [x] FinMind 免費 token(600 req/hr,`RADAR_FINMIND_TOKEN`,GitHub secret 已設)
- [x] **排程觸發改用 Cloudflare Worker**(2026-07-09):GitHub 原生 `schedule:` 實測延遲 2.5–3.5 小時,6 支資料 workflow 已全數改為 `workflow_dispatch:` only,由 `cloudflare-trigger/`(單一 10 分鐘 cron trigger + 程式碼比對時間表,繞開 Cloudflare 免費方案 3/Worker、5/帳號 的 cron 上限)準時觸發;新增 `daily-margin`(22:10 台北,融資券保底輪)

## 未完成(依優先序)

0. **資料架構 B 案遷移**(`docs/31` v3「Workers 靜態資產資料層」,2026-07-15 定案,最高優先):WP-B0 前置(**Executor 部分已完成 2026-07-15,同日改版 v3**:cloudflare-data-worker/(assets 模式)、pipeline/Dockerfile、vps/.env.example;人工部分待做:Cloudflare API token(Workers scope)、VPS node/rclone gdrive、VPS 首次 wrangler deploy)→ ~~WP-B1 合規止血~~(✅ **2026-07-15 完成**:首份 Drive 快照 `radar-20260715.db.gz` 就位後,public release 的 `radar.db.gz` asset 已刪,docs/10 §3 紅線解除;雲端鏈進入 cache 單腿期,cutover 目標 ≤1 週)→ ~~WP-B2 VPS cron 影子跑~~ ✅ **2026-07-18 驗收通過**(連續交易日 07-16/07-17 shadow 與正式站 freshness/榜單一致、ntfy 無 High 告警)→ **WP-B3 cutover 前置條件全滿足,執行手冊已備妥(`docs/32`),待使用者敲定執行日**(deploy.yml 改純 build、Worker trigger 停用、repo 轉 private)→ WP-B4/B5 加固與文件同步 → WP-B6 開跑 WP-M4(前置:修 `backfill_warrant_branches` bug,docs/30 §3)→ WP-B7 登入統一(Supabase 白名單取代 Access,資安審查後)。每包動工前需使用者確認。
1. ~~**私人測試版 Access**(`docs/21` A0-A2)~~ ✅ **2026-07-13 完成**:使用者手動於 Cloudflare Zero Trust 設定(Google IdP + email 白名單,單一 Application 覆蓋三類入口),執行紀錄見 `docs/21` §4 A3;R2 部分見第 6 項,仍未動。
2. **B 方案 Phase 2—策略/分數解耦**(`docs/20`,高風險資料語意變更):S1-S13 只產生 tag/reason,不得再增加 `tech_score` 或其他分項;~~補 S2-S13 測試~~ **2026-07-10 完成**(S2-S13 正例/邊界反例 36 項 + 解耦回歸斷言,S11-S13 抽純函式零行為變化,pytest 91 全過,verifier 窮舉探針 CONFIRMED)。仍缺:舊/新分數差異報告;正式全市場重算、回灌及部署必須另獲使用者批准。
3. **B 方案 Phase 3—策略績效閉環**(`docs/20`):輸出各 S code 的成熟樣本、5/10/20 日勝率與平均/中位報酬;預設 Shadow,使用者看報告後決定 Active/Retired。
4a. **盤中訊號雷達 + 分點追蹤視角**(`docs/24`,2026-07-11 使用者指定排入):~~Part B 分點追蹤視角~~ **2026-07-11 完成**(B1 export + B2 前端);~~Part A 盤中雷達~~ **2026-07-12 程式碼完成**(I1-I3 完成,含 `worker.py` 與前端 `IntradayPanel.tsx` 即時推播),部署方向為 VPS docker+cron(非本機,2026-07-12 使用者定案,`docs/vps_backfill_plan.md` Step 5)。Supabase SQL 已執行、Fugle 金鑰已備。排查發現 Step 5 手冊寫於 2026-07-13 Cloudflare Access 上線前,`.env` 缺 Access service token,worker 抓 `radar.json` 會被 Access 擋 403 fatal exit;已補 `pipeline/intraday/.env.example`(六變數)與 crontab 整合。2026-07-16 使用者建立 Access Service Token 並掛上既有 Access Application 原則後,VPS 首次 live smoke test 炸出 `fugle-marketdata` 套件 API 飄移(`connect()/subscribe()` 官方已改同步呼叫、WebSocket callback 給原始 JSON 字串非 dict),當晚修復(commit `fcb3aef`,回歸測試 pytest 104 全過)。**✅ 2026-07-18 確認:已跟上盤中實跑、cron 常態化,首頁盤中面板穩定 online**。Part A 全流程完成上線。
5. **功能·視覺 backlog**(`docs/23`)：✅ **2026-07-12 F 系列全數完成**。已完成清單：V1/V2/V3.1/V3.2(2026-07-11)；F2 日報摘要、F3 訊號摘要（合入個股頁）、F1.1/F1.2 自選距關鍵價%+排序（合入 IA-4A）、V3.3 Sonner toast、**F1.3 一鍵加入今日 Armed**、**F4.1 掃描收斂（合入 IA-1B）+ F4.2 策略四類分群**（2026-07-12）。~~剩餘僅 V3 淺色 token 對比為「只回報未改」~~ **V3 淺色 token 對比已於 2026-07-12 補強(含 KChart 淺色主題)**。不得插隊，Executor 依 WP-* 工作包執行。
5a. **任務導向 UI 資訊架構**(`docs/25`)：✅ **2026-07-12 IA-1A/IA-1B/IA-2/IA-3/IA-4A/IA-4B 全部完成並 push main**。已完成：IA-1A 首頁重排；IA-1B 首頁榜單模式收斂；IA-4A 自選追蹤；IA-2 個股判讀；IA-3 分點研究；IA-4B Armed 狀態增強（結合 docs/22 A1-A2，完成首頁狀態池 Tab 與 StockCard Badge 視覺整合）。
6. ~~R2 R0-R2(`docs/21`)~~ **2026-07-15 作廢**:R2 啟用需綁信用卡,不採用;快照職責改 Google Drive、還原演練併入 `docs/31` WP-B4。
7. **B 方案 Phase 4—排程簡化提案**(`docs/20`,獨立高風險任務):保留資料取得時點,評估完整 build/deploy 由每日最多 5 次降為 14:10/22:10 兩次;不得在未完整審查 WAL/cache/release 鏈前修改 workflow。
  5b. **首頁掃讀體驗+個股頁資訊架構統一**(docs/28,2026-07-12 規劃定案):WP-H2 語意色彩層次(已完成 2026-07-12)→ **WP-H4 個股頁分點統一(2026-07-12 完成,commit 83649ae)**:移除分點 Tab，K 線下方 BranchFlowSection 升級為單一真相，傳入 branchScore+B*/S11-S13 理由 pills，forwardRef+id 供 #branch 錨點捲動→ WP-H1 榜單依題材分組(等使用者喊開工)→ WP-H3 卡片走勢改當日分時(**A 案已批准**:Fugle key 進 Actions secret RADAR_FUGLE_TOKEN，使用者親自設 secret，等喊開工)→ **WP-H5 手機版(2026-07-12 完成,commit 83649ae)**:工具列橫滑、vertTouchDrag=false、手機版 pane segmented chips、買賣超 tabs+勾選浮動 chip。**剩餘:WP-H1/WP-H3**。
6a. **地緣券商+庫藏股分點+關鍵分點同買 → 口袋名單**(`docs/27`,2026-07-12 規劃定案、未實作):地緣改演算法判定(公司地址×分點地址官方開放資料;雙北用行政區級+排除集)、KB1 買回窗事實 tag/KB2 疑似執行分點推測、K1 關鍵分點=手動種子∪可信度≥70、H1 題材熱門;reason stacking ≥2 family 入口袋名單(pocket_score 僅排序,**不進綜合分**);~~G0 資料 PoC~~ **2026-07-12 完成**(端點全通、分公司級名稱匹配 100%、地緣假設以 2476 實測命中、庫藏股無 OpenAPI 需深挖——結果與 G1 設計修訂見 docs/27 G0 節);G1-G4 建議 VPS 回灌穩定後;地緣涵蓋度在 7a 全市場每日池後才完整。**這項同時解掉 docs/13 卡了很久的地緣/關鍵分點人工名單問題**。
7a. **全市場擴容**(`docs/26`,2026-07-12 使用者定案「有幾檔抓幾檔」):WP-M1 個股 JSON 池全市場 → ~~WP-M3 branch_hist.db 拆分~~(**2026-07-15 因 B 案取消**,見 docs/31 §9)→ WP-M2 一輪制與 WP-M4 全市場 march-back 併入 `docs/31` WP-B6,於 cutover 後執行。
8. ~~deep-backfill --all~~ **執行狀態需另行查證**:完成與否不得只信本檔舊紀錄;若需 `task=adjust` 或 VPS 回灌,先依 `vps_backfill_plan.md` 與高風險流程確認。
9. **分點排行資料累積**:可信度排行榜已完成,統計效力需 2–3 個月。地緣/關鍵分點人工名單、五年分點擴容、LINE Bot 依 B 方案延後;~~V2 盤中延後~~ 盤中已依 `docs/24` 重新規劃排入(見 4a)。

## 已知債務 / 注意

- ~~分點 5 年全量的架構前置(release 2GB/cache 10GB 上限、R2 拆檔)~~ **2026-07-15 因 B 案(`docs/31`)大幅緩解**:cutover 後 DB 常駐 VPS 磁碟,雲端上限消失;P2 是否開跑改由 VPS 磁碟餘量與來源站禮貌率決定,仍待使用者另案確認。

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
- **策略/技術評分邏輯改動不會立即反映在正式資料**:S1-S10 的代碼存於 `indicators_daily.reasons`(S11-S13 在 `daily_scores.reasons`),而增量重算(`compute-indicators --days 5`)會直接跳過「指標日期已跟上價格日期」的股票,不會因程式改版重算。改了策略程式後:當日榜要等**下一交易日 14:10** 的 `daily-market` 增量才會用新邏輯產生當日 reasons;全歷史回補則靠 **VPS 全重算後回灌**(週六雲端全重算已於 2026-07-10 停用,見 docs/08 §0)或手動 `gh workflow run data-backfill -f task=adjust`。**注意:VPS 重算前務必 pull 最新 main**(策略邏輯在程式碼裡,舊碼重算出來還是舊 reasons)。2026-07-10 策略上線首日 S1-S10 全部 0 檔即此因(當日指標已算過、增量跳過),非邏輯錯誤。freshness 跳過機制本身不改

## 最近完成

- 2026-07-18 **WP-B2 影子驗證驗收通過 + 盤中訊號雷達 Part A 全流程上線**:B 案影子驗證連續交易日(07-16/07-17)shadow 與正式站 freshness/榜單一致、ntfy 無 High 告警,**WP-B3 cutover 前置條件全滿足,執行手冊 `docs/32` 已備妥,待使用者敲定執行日**。盤中 worker 側:07-16 首次 VPS live smoke test 炸出 `fugle-marketdata` 套件 API 飄移(`connect()/subscribe()` 官方已改同步、WS callback 給原始 JSON 字串非 dict),當晚修復(commit `fcb3aef`,回歸測試 pytest 104 全過);07-18 確認已跟上盤中實跑、cron 常態化,首頁面板穩定 online。
- 2026-07-15 **WP-B0/B1 完成 + WP-B2 影子驗證起跑**(`docs/31` §12):WP-B0 全套人工+Executor 件完成(token/node/rclone gdrive/.env/docker 映像/首次 wrangler deploy,影子路由 `/data-preview/*` 兩測過);`vps/scripts/` 七支 + `manual-catchup.sh` 落地,crontab 七條已掛、ntfy 實測通;manual-catchup 一條龍完成(當日+近 6 日追補、全重算、990 檔資產 deploy)→ 首份 Drive 快照 `radar-20260715.db.gz`(integrity ok)→ **刪除 public release `radar.db.gz` asset,docs/10 §3 合規紅線解除**。雲端鏈 cache 單腿(已知風險),WP-B3 cutover 目標 ≤1 週;影子驗證第一發實彈 = 07-15 22:10 daily-margin。
- 2026-07-15 **docs/31 v3 改版:不採 R2(啟用需綁卡),資料層改 Workers 靜態資產、備份改 Google Drive 單雲**:使用者定案全方案不得使用需綁信用卡的服務;資料層 A 案(VPS `wrangler deploy` JSON 為 Worker assets,`/data/*` 路由,即傳即生效體感不變)取代 R2 bucket;備份 = VPS 本機 + Drive 兩份(單雲風險知情接受,§4 留 B2/MEGA 後路);`cloudflare-data-worker/` 改寫 assets 模式、`vps/.env.example` 憑證改 `CLOUDFLARE_API_TOKEN`(scope 限 Workers Scripts/Routes Edit);AGENTS/STATUS/project-context/handoff 同步;`docs/21` R0-R4 作廢。
- 2026-07-15 **資料架構 B 案定案並落檔 `docs/31`(v2 R2 資料層)+ WP-B0 Executor 件產出**:Planner(Fable 5)分析三根因(容量天花板/雙寫者同步/repo public 資料散布合規)後,使用者定案 radar.db 常駐 VPS 單一寫者;v1「VPS 輪詢 build+deploy」因部署延遲與管控面過大被使用者否決,v2 改「資料與部署解耦」——VPS 匯出 JSON 直傳 R2、`/data/*` 由 Cloudflare Worker 讀 R2 回應(快照放獨立 backup bucket 實體隔離)、GitHub push→deploy 維持現狀;明確不做 FastAPI/常駐 API;立項 WP-B7 登入統一(Supabase JWT+白名單,Access 驗證後退役,需資安審查);WP-M3 取消、docs/29 Phase 2 剩餘項作廢。同日完成 WP-B0 Executor 件:`cloudflare-data-worker/`(R2 代理 Worker+wrangler.toml+README)、`pipeline/Dockerfile`(依賴烤入映像)、`vps/.env.example`。
- 2026-07-14 `49c4a39` **分點進出標示籌碼日**(web):分點資料落後價格日時,明確標示所用籌碼日並警示暫用舊資料。
- 2026-07-13~14 **雲端 DB 瘦身 Phase 0-2 + VPS 分點歷史回灌**:`docs/29`(WP-M3R)落檔(`3df1976`)後實作 Phase 0/1(`980524d`)與 Phase 2 branch_dim 正規化(`3a72c8d`,同 commit 追加 WP-M4 全市場回補計畫);VPS 490 天分點歷史回補完成並回灌雲端,期間修掉 VPS 指令中 db download 會覆蓋 490 天歷史的風險(`7db809a`)、以還原後完整歷史 DB 觸發部署並 force deploy 清 cache(`5029ab5`→`fa464d3`);另新增 Actions `task=backfill-recent`/`backfill-branches-recent`/唯讀 `debug-query`(`fd1f002`/`9e4ffe0`/`0f0fd45`),補 07-10(五)缺漏交易日資料(`92a1e10`)。
- 2026-07-13 **Cloudflare Access 鎖站完成(docs/21 A0-A2)**:使用者手動於 Cloudflare Zero Trust 完成 Google IdP + email 白名單,單一 Access Application 覆蓋 `radar.techtrever.com` / `trever-radar.pages.dev` / `*.trever-radar.pages.dev`;執行紀錄寫入 `docs/21` §4 A3(commit `ff2b05f`)。
- 2026-07-14 **compute-branch-stats OOM 修復**(pipeline,已入 commit `4587c6f`;另新增 Actions `task=branch-stats` 讓 7GB RAM 雲端 runner 跑統計,commit `45787c4`):`compute_all()` 舊版一次把整張 `branch_trades`(回補後約 600 萬列)連同全部 500 檔完整價格序列載進記憶體,1–2GB RAM 的 VPS 被 OOM killer 殺掉(`51 Killed`)。改為**串流式逐檔處理**——先查 distinct stock_id,再逐檔載入單股價格 ctx + 該股 branch_trades 列(走 PK `(stock_id,…)` 前導,無需新索引),算完累加分點層事件池後即釋放。彙總/排行/auto in-out/落地全部不動,純函式不動,行為零變化;既有 28 項測試 + 全 106 項 pytest 全過。合成 1.2M 列(比生產密集)實測:舊版全表 fetchall Python 峰值 488MB(且舊版還在其上疊 stock_ctx+by_bs 兩份)→ 新版全程峰值 161.7MB(主要是跨檔事件池,單檔資料僅數 MB)。重跑指令見 `docs/vps_backfill_plan.md` 4c 後的 OOM 小節。
- 2026-07-14 **docs/28 WP-H4(個股頁分點統一)+ WP-H5(K 線圖/分點明細手機版)**(commits `83649ae`/`8b04b77`/`4587c6f`):H4 移除「分點」tab(收為 K線/權證),K 線下方 BranchFlowSection 升級為唯一分點區(標頭併分點分徽章+分點理由 pills,`#branch` 錨點捲動,BranchPanel 刪除);H5 手機(<768px,全 media/斷點 gated,桌機逐位元不變)子 pane 副圖/主力/分點三選一(獨立 localStorage、分點無勾選 disabled、總高 clamp(360,52vh,480)、stretch 使子 pane ≥120px)、`vertTouchDrag=false` 垂直手勢還頁面、游標值改上方 compact legend、工具 chips 單行橫滑+min-h-11、買賣超 segmented tabs+前8展開、勾選右下 fixed chip(z-30,點擊捲回 KChart)。修正前次 commit(83649ae/8b04b77)遺留的手機仍渲染 4 pane、桌機 chips 被改成單行不換行、主力 pane 綁 settings.mainForce 等缺陷。`web` `npm run build` 全過;未動 token/依賴/pipeline(僅 globals.css 加一個 `.scrollbar-hide` 工具 class)。
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
- 2026-07-11 個股頁 K 線下方分點進出:抽出共用元件 `web/components/BranchFlowSection.tsx`(時間範圍+N日淨流/家數摘要+前13大買/賣超兩欄列表,聚合邏輯自原 BranchPanel 原樣搬移),掛進 K 線視圖技術摘要之後(標題「分點進出」),分點 Tab 改引用同一元件——同一份邏輯兩處用;區塊自帶期間 state(預設 5 日)不與 K 線區間連動;`pillTabClass` 提到 `lib/utils.ts` 供兩處共用;`cd web; npm run build` 全過。
- 2026-07-10 觀察價/失效價 + 自選股 + 探索頁(集中度/題材):`daily_scores` 新增 `watch_price`/`stop_price`/`buy_concentration`/`concentration_avg20`(additive migration);純函式 `watch_stop_prices`/`buy_concentration` 各有單元測試,`buy_concentration` 從既有 B3 評分邏輯抽出重用;`export-json` 帶出至股票卡/個股頁/新的 `radar.json.concentration` 榜;前端新增 Supabase-backed 自選股(`web/lib/watchlist.tsx` Context + `WatchlistButton` + `/watchlist` 頁,需人工執行 `docs/sql/watchlist.sql` 建表)與 `/explore` 頁(集中度+題材 2 個 tab,地緣/關鍵分點/分點績效榜/權證異動因人工名單或與 `/branch` 重疊而暫緩);全專案 `npm run build`(含 static export)與 16 項 pytest 皆過。
- 2026-07-10 前端 UI 遷移 Tailwind CSS v4 + shadcn/ui(尚未 commit):分階段(header/nav/搜尋/auth → 首頁 → 個股頁 → branch/explore/watchlist → 清理舊 CSS)把全站手刻 CSS 換成 Tailwind utility + shadcn 元件,視覺目標是與遷移前逐頁比對不走樣(每階段皆截圖比對深色模式,並用本機 DB 產出的真實資料而非空狀態驗證);過程中發現並修掉兩個遷移期間才浮現的既有 bug——① 舊 `.grid` class 名稱與 Tailwind 內建 `grid`/`grid-cols-*` utility 直接碰撞,unlayered 規則蓋過 Tailwind 的 layered utility,導致多處 4 欄版面被壓成 3 欄且會換行,已刪除該舊規則;② shadcn `@theme inline` 的 `--color-border`/`--color-accent` 一度被誤指到 legacy brand token,深色模式因數值巧合沒發作,但淺色模式的邊框/hover 底色會全部跑掉,已修正並補上 body 背景色改用 shadcn token,讓淺色模式真正可用(站上切換 toggle 已於 2026-07-11 補上,見 docs/23 V3.1)。`npm run build` 全過,globals.css 從 912 行清到約 210 行。

- 2026-07-10 分點可信度排行榜(docs/13 §2b/§3a/§3b,commit `cae4fd1`):`compute_branch_stats.py` 由佔位邏輯改為真實統計——事件擷取(淨買超≥成交值1%、連續交易日合併、事件日=段首日)、重用 `forward_returns` 以還原價計前瞻報酬與 5 日勝率、隔日沖判定(次日回吐≥70% 比率≥60%)、可信度分數 0-100(勝率30/報酬25/買點分位15/規模10/近效20,級距為 V1 起始值待校準);`branch_rankings` 保留歷史快照(只刪同 as_of);`tracked_branches` 自動入選/移出(僅動 source='auto');export 只取最新快照且隔日沖獨立輸出;/branch 排行榜 tab 補樣本不足/來源徽章/隔日沖獨立區;新增 27 項單元測試(全套 44 過),verifier 種子 DB 實測 CONFIRMED。
- 2026-07-10 權證大戶追蹤 (Warrant Branch Tracker):於 export_json 實作跨權證彙總演算法，以標的股票為中心加總特定分點的多檔權證淨買賣額，支援 1D/2D/5D/30D 區間，並篩選出大於 500 萬台幣的大單。前端 `/branch` 頁面新增「權證大戶」Tab，透過 Bento Grid 卡片與 Pill Selector 呈現 UI/UX PRO MAX 質感。並且支援點擊卡片直接展開明細 (Accordion)，列出構成該大單的每一檔權證代號、名稱、屬性及金額佔比。（新增半年 120D 追蹤：排程範圍擴大至 Top 200 權證，並支援 120D 時間切換，用於追蹤大戶低檔佈局尚未出清之籌碼。）（新增視角切換功能：支援「依標的檢視」與「依分點檢視」雙模式，將相同標的或分點的卡片進行聚合，減少畫面散亂，大幅提升追蹤主力的效率。）**（導入 UI/UX PRO MAX 視覺升級：卡片漸層與立體陰影、懸浮式手風琴子卡片 (Nested Cards)、紅綠邊框指示條、以及 Apple 風格立體切換器，徹底跳脫傳統表格框架。）**
- 2026-07-10 資金流向面板改善與 UI 規範文件化(commit `a221995`,verifier CONFIRMED):①修條圖蓋字 bug——每列改「名稱|條軌|數值區」三欄 grid,條以 scaleX 在自己的 overflow-hidden 條軌內縮放,結構上不可能再壓到金額文字;②流入欄移到左邊(DOM 順序=視覺順序,移除 order hack);③產業下鑽子題材——export 為每產業輸出 `sectors[].subs`(成分 ≥2 檔題材、排除同產業名、金額前 10、每 sub 帶前 5 成分股),前端點產業先列子題材(如 BBU、被動元件)再展成分股,保留全部成分股入口;新增種子 DB 測試 `test_json_export.py`;④新增 `docs/19_ui_guidelines.md`(專案 UI/UX 規範,ui-ux-pro-max 對照),`AGENTS.md` 動前端必讀行同步更新——**日後改前端頁面先讀 docs/19 + docs/07**。
- 2026-07-10 13 項選股策略與獨立榜單重構:`indicators.py` 及 `scores.py` 實作涵蓋技術與籌碼（如「漲停二次發動」、「法人連買突破」、「均線糾結突破」等）共 13 種量化策略；前端首頁「策略」頁籤內，新增了可動態切換 13 種不同策略條件的選單，並移除個別策略按鈕上的雜訊數字，介面大幅升級。
- 2026-07-10 S1 雙軌還原 + mark 死碼移除:S1「漲停二次發動」還原舊版嚴謹/放寬雙軌(嚴謹 `S1_REBOUND` 20 分,elif 放寬 `S1_REBOUND_RELAXED` 15 分;放寬=20日內漲7%+5日量1.5倍+任意金叉),兩代碼同入 `strategies.S1_REBOUND` 榜、嚴謹排前,解決嚴謹單軌常態 0 檔;同時移除已無消費者的舊 T6 mark 榜死碼(`json_export.py` 的 mark 掃描/`lists.mark` 輸出、`web/lib/types.ts` ListKey 的 mark)並補 S1 單元測試;另把「策略邏輯改動需等增量/週六全重算才生效」文件化於上方已知債務。
- 2026-07-10 Armed 追蹤規劃落檔(`docs/22`):確認下一產品方向為狀態池(Quiet→Armed→Triggered→Extended→Faded),首頁「未發動/已發動」、重用 S12/W3/B3,不新增策略/不抬綜合分;程式未實作,排在 Access + B Phase 1–3 之後。
- 2026-07-10 功能·視覺 backlog 落檔(`docs/23`):ui-ux-pro-max 對齊後寫入 V1–V3 / F1–F4 與 WP-* Executor 工作包;拒絕新配色與 Inter 全站字體;程式未實作。
- 2026-07-10 B 方案 Phase 1 (UI 刪減與合併):集中度併入 `/branch` 今日動向、題材只留首頁、移除 `/explore` 與空殼盤中導航、權證大戶降級為「權證分點異動(實驗)」、移除未使用依賴 `recharts`。
- 2026-07-11 WP-V2 榜單/表格一致性(docs/23 §2 V2,只動 UI 不動資料語意):①權證明細標竿表補排序回饋——表頭可排序欄改鍵盤可聚焦 `<button>` + `aria-sort=ascending/descending`,選中欄加 inset ring + 亮字選中態;②`/branch` 集中度榜與「今日買超」兩個 div-grid 真表格遷成語意化 `<table>/<thead>/<tbody>`(對齊權證表字級/分隔線,`overflow-x-auto` 手機可橫滑,不裁代號/漲跌,淨額補 +/- 號),分點前13大買賣超與權證大戶群組維持卡片列不硬遷;③首頁 stale freshness 標示改琥珀徽章 + lucide `Clock`(用既有 `--warn` token,不新增色票)。無新增依賴,`npm run build` 過。
- 2026-07-11 個股頁多層圖:復刻籌碼K線版面——KChart 新增「主力買賣超(前15大)」pane(branch_history 每日全分點 net 加總柱 + 累計線,工具列可開關並記憶於既有 settings localStorage)與勾選驅動的「分點進出」pane(BranchFlowSection 前13大買/賣列表加 checkbox,上限 10,勾選集合每日 net 加總 + 累計線,無勾選不渲染);單 chart 實例 X 軸全 pane 同步,D/W/M 用新 `periodKey` 對齊 K 棒桶重取樣,pane 標題與游標當日/累計數值(帶正負號)以 v5 `createTextWatermark` 畫在對應 pane;無 branch_history 時兩 pane 不渲染、高度回原本。`npm run build` 過,以正式站 2330 真實資料 headless 驗證柱/累計數字與來源吻合。
- 2026-07-12 **docs/25 IA-1B (首頁榜單收斂) 與 IA-3 (分點研究 Master-Detail 整合) 實作**（commit `df02e6e`）：
  - **IA-1B 首頁榜單收斂**：首頁 7 個一級 Tab 壓縮為 4 個，將「熱門/爆量/強勢/弱勢」榜單合併收合為「市場掃描」一級 Tab，當切換到此 Tab 時下方顯示 Segmented sub-selector pill 切換，且正確顯示各子模式 counts，解決行動端排版擁擠。
  - **IA-3 分點研究 Master-Detail 整合**：改寫 `branch/page.tsx`。桌機版在排行榜採用 `grid-cols-[380px_1fr]` 雙欄佈局（左欄過濾名單可獨立滾動並顯示 active focus-ring，右欄即時加載 `BranchTrackView` 或無 track 資料提示）；手機版保留單欄列表並覆蓋下鑽，帶有 ArrowLeft 安全返回，徹底移除了原本獨立的「追蹤視角」模式按鈕。
  - **BranchTrackView.tsx 改造**：支援 `hideBack` prop，在桌機詳情面板上隱藏返回鍵。
- 2026-07-12 **docs/23 F 系列 + docs/25 IA Phase A-F 完整實作**（commit `8d4aee5`，11 files, +597/-138）：
  - **IA-1A 首頁 Pilot**：Compact Brief 壓縮為水平 compact row；Primary Queue（榜單+股票卡）提前至 MoneyFlow 前；MoneyFlow 改可展開/收合（預設收合）；新增 `DesktopNav.tsx` client component（usePathname active state）；桌機導覽標題改為任務導向命名（今日雷達/分點研究/自選追蹤）。
  - **IA-4A + F1.1/F1.2 自選追蹤**：完整重寫 `watchlist/page.tsx`；純前端計算距觀察/失效價%（不動 pipeline）；5 種排序選項（接近失效/觀察/風險/漲跌/加入順序）；分組顯示「需要注意」vs「一般追蹤」；教育性空狀態 + 骨架屏。
  - **IA-2 + F3 個股判讀**：`stock/page.tsx` 加入 `StockDecisionHeader` 元件（reasons ≤3、risks ≤2、觀察/失效價+距離%、來源徽章 分點/權證/both）；接近失效價時紅色警示。
  - **IA-3 分點研究**：`branch/page.tsx` 加入 Page Brief（入榜/樣本足夠/可追蹤/資料起始 4 格）；Filter UI（分點名搜尋、可追蹤、樣本足夠、排除隔日沖）；排行榜改用 filteredMain/filteredDaytrade。
  - **F2 日報摘要**：`json_export.py` 新增 `_build_summary_text()`（規則模板≤3句，無 LLM）；`types.ts` 加 `summary_text?: string[]`；首頁 stale alert 後顯示摘要區塊。
  - **V3.3 Sonner**：`npm install sonner`；`layout.tsx` 掛 `<Toaster position="bottom-center" richColors />`；`WatchlistButton.tsx` 加入/移除觸發 `toast.success/info`。
  - build 兩次均通過（`npm run build`），0 errors；push main → Cloudflare Pages 自動部署。
- 2026-07-12 **docs/23 F4.2 策略四類分群 + F1.3 一鍵加入今日 Armed（純前端，commit `0d70e8a`）**：
  - **F4.2 策略四類分群**（`web/app/page.tsx`）：13 策略 pills 依 `docs/20` §4.1 改為「籌碼事件(S11-13)/突破發動(S2-4,6-8)/趨勢續強·回踩(S1,5,9)/低檔反轉(S10)」四組；每組標題含總檔數 badge + lucide `ChevronDown`（`aria-expanded`、`-rotate-90` 收合，transition-transform 200ms）；預設只展開籌碼事件（`expandedGroups` Set，session 內不持久化）；選中策略落在收合組時「有效展開」自動含入（`expandedGroups.has || codes.includes(strategy)`）；預設選中改籌碼事件組第一個有檔數者（皆無則 S11，radar 載入後 `useRef` 套一次不覆寫使用者選擇）；pill 樣式與 count 沿用既有；未改任何 S code 語意。
  - **F1.3 一鍵加入今日 Armed**（`web/app/watchlist/page.tsx`）：新增 `AddTodayArmedButton` 自足元件（fetch `/data/radar.json` 取 `lists.armed`）；置於三種頁面狀態頂部動作區（未登入 / 空自選 / 主檢視）；N = armed 中尚未在自選者，只加不減（pending 先排除已在自選者，逐檔 `toggle` 新增、失敗不中斷）；完成 Sonner `toast.success`「已加入 X 檔」/`toast.warning`「已加入 X 檔；失敗 Y 檔」；未登入(登入後可用)/今日無 Armed/pending=0 三態 disabled，執行中 `aria-busy`+loading disabled；`lists.armed` 空防禦；不自動同步。
  - `cd web; npm run build` 全過（0 errors）；13 策略與 STRATEGIES 常數逐一比對無缺漏/重複。
- 2026-07-12 **淺色對比補強 + 盤中面板顯示放寬（純前端，commit `331af88`）**：
  - **A 淺色 token 對比**（`web/app/globals.css`）：被當文字色用、原僅 `:root` 定義深色調值的 brand-extension token 改雙主題定義——`.dark` 補回原深色值(逐位元不變)、`:root` 給淺色可讀值：`--ink-2` #c3c2b7→#5f5e52(對白 1.79→6.54)、`--warn` #fab219→#8a5a00(1.83→5.93)、`--accent-2` #35b5c9→#0e7c8c(2.44→4.91)、`--legacy-accent` #3987e5→#2f6fc4(連結/focus,3.64→5.01)；`--up`/`--down` 刻意不動。（另記:非文字的 `--border-strong` rgba(255,255,255,.16) 與 `--line` #2c2c2a 於淺色偏弱,屬邊框類非本次文字對比範圍,留待後續。）
  - **A KChart 淺色主題**（`web/components/KChart.tsx`）：抽 `chartColors(isDark)`(dark=遷移前寫死值逐字不變、light=grid #e6e5e0／文字 #6b6a64／軸 #d8d7d2)；`MutationObserver` 監聽 `<html>` class,主題切換以 `applyOptions` 就地更新 grid/軸/水印色(不重建,不閃爍),水印動態值由 `paneTextRef` 即時跟色；K 棒紅綠/均線/量色不變。
  - **B 盤中面板顯示邏輯**（`web/components/IntradayPanel.tsx`）：移除非盤中隱藏,面板永遠渲染；未登入顯示登入提示外殼；登入後空狀態分「非交易時段(worker 平日 08:50 啟動)」與「交易時段 worker 離線/尚無訊號」；頂欄徽章非交易時段顯示中性「非交易時段」(不用紅色 offline);無訊號時單行精簡不留空白。
  - `cd web; npm run build` 全過（0 errors）；未新增依賴、未動 pipeline；深色 diff 中 `.dark` 值 = 原 `:root` 值逐字相同。

| Pipeline Module (CLI) | 實作的系統功能 |
|---|---|
| `import-daily` | 每日市場收盤價 (`quotes`)、三大法人買賣超 (`insti`)、融資融券餘額 (`margin`) |
| `import-warrant-master` | 每日發行的權證主檔更新，用於配對標的與到期日 |
| `aggregate-warrants` | 每日計算個股認購/認售權證的總成交金額與量比，輸出至首頁權證榜 |
| `import-branch-trades` | 每日下午抓取盤後分點前 15 大進出明細，支撐籌碼日報與分點評分 |
| `import-themes` | 每日/每週抓取概念股與產業題材分類，用於首頁熱力圖與題材分 |
| `compute-indicators` | 計算還原價 MA5/10/20/60、RSI、MACD、乖離率等技術指標 |
| `compute-scores` | 綜合評分引擎 (分點35/權證20/技術20/法人15/題材10)，產生分數與理由/風險 JSON |
| `export-json` | 根據動態閾值產生各類排行榜單 (hot, surge, strong, warrant, weak)，單檔明細，以及分點/權證大戶動向追蹤 |
