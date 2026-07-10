# 專案狀態(2026-07-10)

> 單一進度真相。每完成一個里程碑就更新本檔。規格細節看各編號文件,別寫在這裡。

## 上線資訊

| 項目 | 值 |
|---|---|
| 正式網址 | https://radar.techtrever.com(= https://trever-radar.pages.dev) |
| 公開狀態 | **目前仍公開**,noindex + robots.txt;2026-07-10 使用者已決定改 A 私人測試版,Access 尚未設定。實作與驗收照 `docs/21`/`DEPLOY.md` §4,未驗收前不得宣稱私有。 |
| 自動排程 | GitHub Actions 6 支 workflow(現行時間表以 `docs/08_scheduler_jobs.md` §0 為單一真相):14:10 `daily-market`、16:10 `daily-insti`、17:40+21:00 `daily-branches`、22:10 `daily-margin`(融資券保底輪)、每日 01:10 `data-backfill`、push main 觸發 `deploy`;各帶 timeout 防呆與共用 `radar-db` cache 續存鏈;觸發來源遷移中,見下方已知債務 |
| Repo | github.com/bbdevin/trever-radar(私有) |
| DB | SQLite,Actions cache 續存 + release `db-backup` 週備份(週五/手動觸發時) |

## AI Workflow Status

2026-07-09 起,本專案開發流程改為**不依賴 Fable 或任一單一模型**的多 agent 協作,完整規則見根目錄 `AGENTS.md`、`docs/17_no_fable_workflow.md`、`docs/18_handoff_template.md`。

- 流程為**模型中立、角色導向**:Planner / Executor / Reviewer 由本次任務指定,不由模型品牌永久決定;規則見 `AGENTS.md` 與 `docs/17_no_fable_workflow.md`。
- 工具清單:Claude Code、AGY/Gemini、Codex、GPT/Grok 等高階模型均可任三角色;Cursor 為 IDE / 確認介面;人類使用者為唯一決策者。

下一步:先完成 `docs/21` Access A0-A2,把目前公開站真正鎖成私人測試版;再依 `docs/20` B 方案刪減 UI、策略解耦與績效閉環。R2 先做 shadow backup/restore drill,不得直接取代 cache/Release。**再下一刀(待開發)**:`docs/22` Armed/Triggered 狀態追蹤——須另確認後才實作。

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
- [x] **WP-V1 首頁/自選 5 秒掃讀優化**(2026-07-11,docs/23 §2 V1):股票卡次要細項(金額/量比/外資/投信)由 4 欄堆疊收斂成一行小字降層級(不刪資料);卡片左側 3px inset 狀態色條(有明顯風險扣分→destructive/風險紅、綜合分≥65 觀察門檻→warn/琥珀、其餘→中性 line,僅用既有 token 且色條非唯一訊號);自選/branch 可點列補 `min-h-11`+`cursor-pointer`+`transition-colors`,★ 鈕與 branch 展開鈕補 `aria-label`/`aria-expanded`;首頁教育性空狀態文案、`/watchlist` 載入改多列 Skeleton;`npm run build` 過,未新增依賴/未改配色 token 語意。
- [x] **UI 全面遷移 Tailwind CSS v4 + shadcn/ui**(2026-07-10):全站 6 頁 + 所有元件從手刻 CSS class 改為 Tailwind utility(僅保留 `.container`/`.num`/裸 `.up`/`.down`/`.flat`/`fadeUp` keyframe 等仍被動態或跨頁共用的少量 class);icon 除品牌 logo 外全改 `lucide-react`;搜尋面板改 shadcn `Command`,登入選單改 `DropdownMenu`,個股頁權證明細表改 **TanStack Table**(可排序 + 展開列);K 線圖仍為 lightweight-charts(未改動);deep design token 對照見 `docs/07_frontend_pages.md`。過程中修掉兩個遷移期間才會暴露的既有 bug:①舊 `.grid` class 與 Tailwind 內建 `grid`/`grid-cols-*` utility 同名碰撞(unlayered 規則蓋過 layered utility),導致多處 4 欄版面被壓成 3 欄;②`@theme inline` 的 `--color-border`/`--color-accent` 一度被誤指到 legacy token,深色模式因數值巧合未現形但會壞掉淺色模式。深色為預設主題,淺色 token 已備妥但站上尚無切換 UI(留待之後加)。

### 基礎設施
- [x] **凌晨長任務常態化**:data-backfill 每天 01:10 深歷史增量(已拉深跳過,日常近零請求);週六 01:10 DB 備份(**週六全市場還原因子+指標全重算已於 2026-07-10 停用,改 VPS 跑後回灌,雲端 fallback=手動 task=adjust**);排程總表 = docs/08 §0
- [x] **分批即時更新**:14:10 收盤閃電更新(日K+權證+指標+分數→部署,資料日當天變今天)→ 16:10 法人+權證主檔 → 17:40 融資券+分點全量 → 21:00 補抓;各資料集「有效日」寫進 radar.json `freshness`,晚公布的前端標「今日尚未公布,暫用前一日」並以前一日數值填充
- [x] 管線效能優化(docs/15):指標增量計算(`--days 5`,全市場 26 秒,原全歷史重算數十分)、release 備份週五化(原三支 workflow 每日各 gzip 1GB)、修正 daily-warrants/branches 繞過 cache 的分岔 bug、pip/npm 快取
- [x] GitHub Actions 全自動管線 + Cloudflare Pages 部署 + 自訂網域
- [x] `main` push 觸發正式部署;push 事件跳過資料匯入,只用 cache/release DB 匯出 JSON、build、deploy
- [x] FinMind 免費 token(600 req/hr,`RADAR_FINMIND_TOKEN`,GitHub secret 已設)
- [x] **排程觸發改用 Cloudflare Worker**(2026-07-09):GitHub 原生 `schedule:` 實測延遲 2.5–3.5 小時,6 支資料 workflow 已全數改為 `workflow_dispatch:` only,由 `cloudflare-trigger/`(單一 10 分鐘 cron trigger + 程式碼比對時間表,繞開 Cloudflare 免費方案 3/Worker、5/帳號 的 cron 上限)準時觸發;新增 `daily-margin`(22:10 台北,融資券保底輪)

## 未完成(依優先序)

1. **私人測試版 Access**(`docs/21` A0-A2):保護 `radar.techtrever.com`、正式 `trever-radar.pages.dev` 與所有 preview;只允許明確 email;直接抓 `/data/radar.json` 也必須被擋。
2. **B 方案 Phase 2—策略/分數解耦**(`docs/20`,高風險資料語意變更):S1-S13 只產生 tag/reason,不得再增加 `tech_score` 或其他分項;~~補 S2-S13 測試~~ **2026-07-10 完成**(S2-S13 正例/邊界反例 36 項 + 解耦回歸斷言,S11-S13 抽純函式零行為變化,pytest 91 全過,verifier 窮舉探針 CONFIRMED)。仍缺:舊/新分數差異報告;正式全市場重算、回灌及部署必須另獲使用者批准。
3. **B 方案 Phase 3—策略績效閉環**(`docs/20`):輸出各 S code 的成熟樣本、5/10/20 日勝率與平均/中位報酬;預設 Shadow,使用者看報告後決定 Active/Retired。
4. **Armed 狀態追蹤**(`docs/22`,📝 規劃定案、程式未實作):首頁「未發動/已發動」狀態池,重用 S12/W3/B3 與權證倍數;不新增策略、不抬綜合分、不新開一級路由。建議在 Access + B Phase 1–3 有進度後另確認 A1→A3 實作。
5. **功能·視覺 backlog**(`docs/23`,📝 規劃定案、程式未實作):V1 掃讀優化 → V2 表格一致 → F2 日報摘要 / F1 自選戰情 / F3 訊號摘要 / F4 掃描收斂;不得插隊,Executor 依 WP-* 工作包執行。
6. **R2 R0-R2**(`docs/21`):private Standard bucket → 每週 shadow snapshot → checksum/gzip/SQLite restore drill。R3 workflow fallback 未授權,R4/P2 延後。
7. **B 方案 Phase 4—排程簡化提案**(`docs/20`,獨立高風險任務):保留資料取得時點,評估完整 build/deploy 由每日最多 5 次降為 14:10/22:10 兩次;不得在未完整審查 WAL/cache/release 鏈前修改 workflow。
8. ~~deep-backfill --all~~ **執行狀態需另行查證**:完成與否不得只信本檔舊紀錄;若需 `task=adjust` 或 VPS 回灌,先依 `vps_backfill_plan.md` 與高風險流程確認。
9. **分點排行資料累積**:可信度排行榜已完成,統計效力需 2–3 個月。地緣/關鍵分點人工名單、五年分點擴容、LINE Bot、V2 盤中均依 B 方案延後。

## 已知債務 / 注意

- **分點 5 年全量的架構前置**(vps_backfill_plan §3 P2 之前必做):DB 將 +7–9GB → 炸 release 單檔 2GB 與 Actions cache 10GB。依 `docs/21`,R2 只能保存拆出的 `branch_hist.db` 快照,不是線上 DB;Standard 免費 10GB-month 還要容納版本與安全餘裕,因此不保證 P2 仍零成本。P2 繼續延後;P1(2年,+1.5GB)尚可。

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
- 2026-07-10 前端 UI 遷移 Tailwind CSS v4 + shadcn/ui(尚未 commit):分階段(header/nav/搜尋/auth → 首頁 → 個股頁 → branch/explore/watchlist → 清理舊 CSS)把全站手刻 CSS 換成 Tailwind utility + shadcn 元件,視覺目標是與遷移前逐頁比對不走樣(每階段皆截圖比對深色模式,並用本機 DB 產出的真實資料而非空狀態驗證);過程中發現並修掉兩個遷移期間才浮現的既有 bug——① 舊 `.grid` class 名稱與 Tailwind 內建 `grid`/`grid-cols-*` utility 直接碰撞,unlayered 規則蓋過 Tailwind 的 layered utility,導致多處 4 欄版面被壓成 3 欄且會換行,已刪除該舊規則;② shadcn `@theme inline` 的 `--color-border`/`--color-accent` 一度被誤指到 legacy brand token,深色模式因數值巧合沒發作,但淺色模式的邊框/hover 底色會全部跑掉,已修正並補上 body 背景色改用 shadcn token,讓淺色模式（目前僅供之後接 UI 切換用，站上還沒有 toggle）真正可用。`npm run build` 全過,globals.css 從 912 行清到約 210 行。

- 2026-07-10 分點可信度排行榜(docs/13 §2b/§3a/§3b,commit `cae4fd1`):`compute_branch_stats.py` 由佔位邏輯改為真實統計——事件擷取(淨買超≥成交值1%、連續交易日合併、事件日=段首日)、重用 `forward_returns` 以還原價計前瞻報酬與 5 日勝率、隔日沖判定(次日回吐≥70% 比率≥60%)、可信度分數 0-100(勝率30/報酬25/買點分位15/規模10/近效20,級距為 V1 起始值待校準);`branch_rankings` 保留歷史快照(只刪同 as_of);`tracked_branches` 自動入選/移出(僅動 source='auto');export 只取最新快照且隔日沖獨立輸出;/branch 排行榜 tab 補樣本不足/來源徽章/隔日沖獨立區;新增 27 項單元測試(全套 44 過),verifier 種子 DB 實測 CONFIRMED。
- 2026-07-10 權證大戶追蹤 (Warrant Branch Tracker):於 export_json 實作跨權證彙總演算法，以標的股票為中心加總特定分點的多檔權證淨買賣額，支援 1D/2D/5D/30D 區間，並篩選出大於 500 萬台幣的大單。前端 `/branch` 頁面新增「權證大戶」Tab，透過 Bento Grid 卡片與 Pill Selector 呈現 UI/UX PRO MAX 質感。並且支援點擊卡片直接展開明細 (Accordion)，列出構成該大單的每一檔權證代號、名稱、屬性及金額佔比。（新增半年 120D 追蹤：排程範圍擴大至 Top 200 權證，並支援 120D 時間切換，用於追蹤大戶低檔佈局尚未出清之籌碼。）（新增視角切換功能：支援「依標的檢視」與「依分點檢視」雙模式，將相同標的或分點的卡片進行聚合，減少畫面散亂，大幅提升追蹤主力的效率。）**（導入 UI/UX PRO MAX 視覺升級：卡片漸層與立體陰影、懸浮式手風琴子卡片 (Nested Cards)、紅綠邊框指示條、以及 Apple 風格立體切換器，徹底跳脫傳統表格框架。）**
- 2026-07-10 資金流向面板改善與 UI 規範文件化(commit `a221995`,verifier CONFIRMED):①修條圖蓋字 bug——每列改「名稱|條軌|數值區」三欄 grid,條以 scaleX 在自己的 overflow-hidden 條軌內縮放,結構上不可能再壓到金額文字;②流入欄移到左邊(DOM 順序=視覺順序,移除 order hack);③產業下鑽子題材——export 為每產業輸出 `sectors[].subs`(成分 ≥2 檔題材、排除同產業名、金額前 10、每 sub 帶前 5 成分股),前端點產業先列子題材(如 BBU、被動元件)再展成分股,保留全部成分股入口;新增種子 DB 測試 `test_json_export.py`;④新增 `docs/19_ui_guidelines.md`(專案 UI/UX 規範,ui-ux-pro-max 對照),`AGENTS.md` 動前端必讀行同步更新——**日後改前端頁面先讀 docs/19 + docs/07**。
- 2026-07-10 13 項選股策略與獨立榜單重構:`indicators.py` 及 `scores.py` 實作涵蓋技術與籌碼（如「漲停二次發動」、「法人連買突破」、「均線糾結突破」等）共 13 種量化策略；前端首頁「策略」頁籤內，新增了可動態切換 13 種不同策略條件的選單，並移除個別策略按鈕上的雜訊數字，介面大幅升級。
- 2026-07-10 S1 雙軌還原 + mark 死碼移除:S1「漲停二次發動」還原舊版嚴謹/放寬雙軌(嚴謹 `S1_REBOUND` 20 分,elif 放寬 `S1_REBOUND_RELAXED` 15 分;放寬=20日內漲7%+5日量1.5倍+任意金叉),兩代碼同入 `strategies.S1_REBOUND` 榜、嚴謹排前,解決嚴謹單軌常態 0 檔;同時移除已無消費者的舊 T6 mark 榜死碼(`json_export.py` 的 mark 掃描/`lists.mark` 輸出、`web/lib/types.ts` ListKey 的 mark)並補 S1 單元測試;另把「策略邏輯改動需等增量/週六全重算才生效」文件化於上方已知債務。
- 2026-07-10 Armed 追蹤規劃落檔(`docs/22`):確認下一產品方向為狀態池(Quiet→Armed→Triggered→Extended→Faded),首頁「未發動/已發動」、重用 S12/W3/B3,不新增策略/不抬綜合分;程式未實作,排在 Access + B Phase 1–3 之後。
- 2026-07-10 功能·視覺 backlog 落檔(`docs/23`):ui-ux-pro-max 對齊後寫入 V1–V3 / F1–F4 與 WP-* Executor 工作包;拒絕新配色與 Inter 全站字體;程式未實作。
- 2026-07-10 B 方案 Phase 1 (UI 刪減與合併):集中度併入 `/branch` 今日動向、題材只留首頁、移除 `/explore` 與空殼盤中導航、權證大戶降級為「權證分點異動(實驗)」、移除未使用依賴 `recharts`。

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
| `export-json` | 根據動態閾值產生各類排行榜單 (hot, surge, strong, warrant, weak)，單檔明細，以及分點/權證大戶動向追蹤 |
