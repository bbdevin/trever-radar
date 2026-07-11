# 25 任務導向 UI 資訊架構計畫(2026-07-11 規劃落檔)

> 本文件把 Trever Radar 的前端由「資料來源/功能模組導向」改為「使用者任務導向」的
> 可執行計畫。使用者已確認將本規劃寫入共同記憶,供後續 Planner / Executor / Reviewer
> 接手；**這不等於已授權任何 Phase 的程式實作**。每次仍須由使用者確認單一 IA Phase。
>
> 本文件是任務流、頁面層級與功能合併的 source of truth；視覺 token/互動細節仍以
> `docs/19_ui_guidelines.md` 為準，產品刪減與策略治理仍以 `docs/20` 為準，Armed 狀態
> 語意仍以 `docs/22` 為準，既有 V/F backlog 仍以 `docs/23` 為準。

## 0. 狀態與硬約束

| 項目 | 狀態 |
|---|---|
| IA-0 文件化 | ✅ 完成(2026-07-11) |
| IA-1A 首頁任務流 Pilot | ✅ **完成(2026-07-12, commit `8d4aee5`)** — Compact Brief 壓縮、Primary Queue 前置、MoneyFlow 收合面板、DesktopNav active state、桌機導覽任務導向命名 |
| IA-1B 榜單收斂 | ✅ **完成(2026-07-12, commit `df02e6e`)** — 首頁 7 個一級 Tab 收斂為 4 個（綜合、策略、市場掃描、權證），市場掃描內置「熱門/爆量/強勢/弱勢」次切 selector |
| IA-2 個股判讀工作台 | ✅ **完成(2026-07-12, commit `8d4aee5`)** — StockDecisionHeader（reasons≤3/risks≤2/觀察失效+距離%/來源徽章）合入 stock/page.tsx |
| IA-3 分點研究工作台 | ✅ **完成(2026-07-12, commit `df02e6e`)** — rankings 改雙欄 Master-Detail 響應式佈局，左滾動排行榜帶 active 高亮，右即時渲染詳情或無 track 提示，取消獨立追蹤按鈕 |
| IA-4A 自選追蹤手動版 | ✅ **完成(2026-07-12, commit `8d4aee5`)** — 完整重寫 watchlist/page.tsx：距觀察/失效價%、5 種排序、分組（需要注意/一般追蹤） |
| IA-4B Armed 狀態增強 | ⛔ 待 docs/22 A1-A3（受制關卡，不得超前） |

所有 Phase 共用限制:

1. 既有 Python + SQLite + 靜態 JSON + Next.js `output: 'export'` 架構不翻案。
2. 不新增第 14 個策略、不改 `final` 權重、不把權證分點納入綜合分。
3. 不新增一級路由；優先重排、合併或漸進揭露既有功能。
4. 不引入新配色、字體或 icon family；沿用 `globals.css` token、Manrope `.num`、Lucide。
5. 紅漲綠跌不反轉；顏色不可作唯一訊號。
6. 不改 workflow、WAL checkpoint、cache/release DB 鏈、`adj_factor`、Access/R2。
7. 一次只做一個 IA Phase；改前讀 `AGENTS.md`、`STATUS`、`docs/19`、本文件與對應頁面。
8. 每個 Phase 完成後更新本文件狀態表、`STATUS.md`，並依 `docs/18` 留 handoff。

## 1. 為什麼需要新的 UI 思路

2026-07-11 只讀審計現行正式站、DOM 與前端 JSX 後，確認 V1/V2/V3 已改善元件品質、
表格語意、focus、空狀態與主題切換，但尚未解決「使用者每天如何更快完成判斷」。

### 1.1 首頁先講市場，後講該看誰

- 三張市場卡 + 大型 MoneyFlow 佔據首屏；手機要滑過完整資金流才看到股票。
- 七個榜單 tab(綜合/策略/熱門/爆量/強勢/弱勢/權證)多為同一批標的的不同排序。
- 策略再展開 13 個選項，但尚無策略績效/生命週期協助選擇。

**挑戰假設**:首頁最重要的不是先展示所有市場資訊，而是先回答「今天該進一步檢查誰」；
市場資金流應作判讀脈絡，不應把行動清單推到第二、三屏。

### 1.2 分點頁把大量比較資料全部卡片化

- 現有資料約 481 個入榜分點，多數勝率/平均報酬仍為 `-` 或樣本不足。
- 卡片適合焦點，不適合 400+ 筆橫向比較；缺少「可追蹤/樣本足夠/候選/隔日沖」篩選。
- 「排行榜」與「分點追蹤視角」是兩個模式，只有 track index 內分點有一致下鑽。

**挑戰假設**:不是所有資料都應做 Bento/Card。大量比較用 compact table/list；選中後再用
卡片或詳情面板。

### 1.3 個股頁把圖表放在判讀之前

- 大型 K 線與多組均線/副圖/主力控制先出現。
- 理由、風險、觀察價、失效價在圖表下方；使用者要先操作工具才看到結論脈絡。
- K 線視圖與分點 tab 都顯示完整 `BranchFlowSection`，程式雖共用但心智入口重複。

**挑戰假設**:圖表不是個股頁的唯一 hero。先回答「為什麼出現、風險在哪、何時失效」，
圖表才是驗證工具。

### 1.4 自選頁尚未成為每天的追蹤工作台

- 現況是平面列表，僅顯示價格、漲跌、分數、觀察/失效價。
- 沒有距觀察/失效價、風險優先排序或需要處理的項目分組。

**挑戰假設**:自選不是收藏夾，而是「我已決定持續觀察」的工作佇列。

## 2. 目標任務模型

前端資訊架構改以三個使用者工作組織，不以資料源數量決定頁面與 tab:

```text
掃描 Scan
  今天有哪些標的值得進一步檢查？
        ↓
判讀 Evaluate
  為什麼出現？風險、觀察價、失效條件是什麼？
        ↓
追蹤 Monitor
  我選定的標的距關鍵價格多遠？是否出現新風險/狀態變化？
```

頁面對應:

| 任務 | 主要入口 | 次要入口 |
|---|---|---|
| 掃描 | 首頁 | `/branch` 今日動向 |
| 判讀 | `/stock` | 首頁卡片摘要、分點選取詳情 |
| 追蹤 | `/watchlist` | 未來 `docs/22` Armed/Triggered 狀態 |

桌機與手機共用同一任務順序；RWD 只改版面，不用 `order-*` 改變 DOM 閱讀順序。

## 3. 目標全域導覽與視覺文法

### 3.1 一級導覽

短期保留三入口，不新增路由:

- `今日雷達`：掃描與今日焦點。
- `分點研究`：現行「分點排行」可評估改名，強調研究而非勝率已成熟。
- `自選追蹤`：現行「自選」可評估改名，強調每日監控。

是否改文案由 IA-1 / IA-4 各自確認；未確認時只補 active state，不改名稱。

### 3.2 共用畫面層級

1. **Page Brief**：頁名、資料日、資料限制、最重要 1–3 個數字。
2. **Primary Queue**：本頁真正要處理的列表/選取項目，首屏可見。
3. **Context**：市場脈絡、圖表、來源細節、教育文案，次層或可展開。
4. **Evidence / Details**：完整表格、原始分點、權證明細，按需查看。

### 3.3 元件選擇原則

- 1–12 個焦點項目：卡片。
- 12 個以上且要比較欄位：table/compact list。
- 一個選取項目 + 多欄詳情：桌機 master-detail；手機 list → detail。
- 控制超過 5 個：保留常用 3–5 個，其餘放「更多/圖表設定」。
- 資料來源/排序不是天然一級 tab；優先用同一視圖的 filter/segmented control。

## 4. IA-1 首頁任務流 Pilot

### 4.1 目標

打開首頁 5 秒內先看到「今天該檢查誰」，市場資金流仍保留但降為判讀脈絡。

### 4.2 建議版面順序

```text
Compact Daily Brief
  資料日｜上市/上櫃成交額與漲跌家數｜freshness

今日焦點 Primary Queue
  焦點｜掃描｜策略
  股票 compact card / desktop compact grid

市場脈絡 Context
  MoneyFlow 摘要(Top 流入/流出) → 展開完整產業/題材

方法與免責 Evidence
```

### 4.3 兩段式範圍，避免偷做 Armed/F4

#### IA-1A：可獨立核准的低風險 Pilot

- 將現有綜合榜/焦點列表移到 MoneyFlow 前。
- 三張市場卡收斂為 compact brief，手機不依賴裁切到看不見的第三張卡。
- MoneyFlow 保留完整資料與下鑽，但預設先顯示摘要或移到焦點列表後。
- 重排 StockCard 層級：身份/價格 → 狀態與理由 → 觀察/失效 → 次要市場數字。
- 導覽補真正的 active state；內部連結優先 `next/link`。
- **不合併任何 list key、不改 tab 名稱、不加入 Armed。**

#### IA-1B：榜單模式收斂，需使用者另行明示

- 七榜收斂為三個使用者模式:
  - `焦點`：既有 `score`。
  - `掃描`：hot/surge/strong/weak/warrant 作 filter，不刪資料。
  - `策略`：先依 `docs/20` 四類分群，保留每個 S code。
- Phase 3 未完成前，策略仍顯示 Shadow/樣本不足，不宣稱有效。
- 不得把「掃描」UI 分組誤寫成新的評分或新 JSON 語意。

IA-1B 與 `docs/23` F4、`docs/22` A2 重疊。若 Armed 尚未實作，必須在 Confirmed Scope
明寫「只做既有 list 的前端 remap，不加入 Armed/Triggered 狀態」。

### 4.4 預計檔案

- `web/app/page.tsx`
- `web/components/MoneyFlow.tsx`
- `web/components/StockCard.tsx`
- `web/app/layout.tsx`
- `web/components/BottomNav.tsx`
- 必要時新增一個首頁 view/filter 元件；不得藉機抽象整站元件庫

### 4.5 驗收

- 375px 首屏可看到至少一部分 Primary Queue，不被完整 MoneyFlow 佔滿。
- 768/1024/1440 無 overflow；市場摘要不靠水平裁切才可理解。
- 首頁所有原有資料仍可到達；IA-1A 不改 list key/排序/評分。
- active nav 對首頁、branch、watchlist、stock 下鑽皆有可理解狀態。
- `npm run build` 通過；無新依賴、無 pipeline 變更。

## 5. IA-2 個股判讀工作台

### 5.1 目標

先看懂「為何值得檢查、風險與失效條件」，再進圖表驗證；減少重複分點入口。

### 5.2 目標結構

```text
Stock Decision Header
  股票/價格/資料日/自選
  為什麼出現(最多3)｜風險(最多2)｜觀察/失效價

摘要 Overview
  分數來源、理由/風險、分點/權證摘要

圖表 Chart
  常用:區間 + 日/週/月
  更多設定:均線、布林、副圖、主力/選取分點疊加

籌碼 Evidence
  分點｜權證 次層切換；完整明細只留這一個主入口
```

實際 tab 名稱可由 Executor 提案，但語意固定為「摘要優先、圖表驗證、籌碼證據」。

### 5.3 互動規則

- `watch_price`/`stop_price` 與距離%在 decision header；距離可前端計算，不改資料。
- 首屏理由最多 3、風險最多 2；完整內容可展開，不能刪除失敗/風險資訊。
- KChart 常用控制保留在外；其餘進設定 popover/drawer，仍要可鍵盤操作。
- `BranchFlowSection` 完整列表只在籌碼主入口出現一次。
- 圖表上的「分點進出」pane 保留；從籌碼選取後回到圖表要能看出已選集合。

### 5.4 預計檔案

- `web/app/stock/page.tsx`
- `web/components/KChart.tsx`
- `web/components/BranchFlowSection.tsx`
- 可能新增 `StockDecisionHeader` / `ChartSettings` 小元件

### 5.5 驗收與風險

- 375px 首屏看到股票、價格、理由/風險與觀察/失效，不需先滑完整 K 線。
- 分點 checkbox、最多 10 個限制、D/W/M 重取樣與圖表疊加行為不可退步。
- K 線資料、指標計算、lightweight-charts 不重寫。
- 直接網址載入與 browser back 正常；若 tab state 改 URL，須用靜態站可用的 query/hash。
- `npm run build` 通過，並以至少一檔有分點/權證、一檔缺資料股票驗證。

## 6. IA-3 分點研究工作台

### 6.1 目標

讓大量分點可比較、可篩選、可下鑽；樣本不足時不把低可信分數包裝成成熟排行榜。

### 6.2 建議預設

- 當多數資料仍樣本不足時，預設 `今日動向`；何時切回排行榜預設由使用者決定。
- Page Brief 誠實顯示：總分點數、足夠樣本數、可追蹤數、資料起始日。
- `權證分點異動(實驗)` 保留實驗與造市/避險限制文案。

### 6.3 目標結構

桌機:

```text
Filter/Search
  可追蹤｜樣本足夠｜候選｜隔日沖｜分點名稱

Master list/table                 Selected detail
分點/樣本/5日勝率/報酬/可信度  →  1/5/10/20/自訂日股票動向
```

手機:

```text
compact list → 分點 detail → 明確返回
```

### 6.4 實作原則

- 不刪 481 筆資料；預設可只顯示 Top N +「載入更多」或 filter 後集合。
- RankCard 可保留作 selected/featured；大量主清單改 table/compact row。
- 排行榜與 `BranchTrackView` 合併成同一 master-detail 任務，不再用獨立「追蹤視角」模式鈕。
- 沒有 track JSON 的分點仍可顯示排名，但下鑽需明確 disabled/說明，不可看似可點卻無作用。
- filter/sort 若只作用前端，URL query/hash 可選；不得因此新增 API。

### 6.5 預計檔案

- `web/app/branch/page.tsx`
- `web/components/BranchTrackView.tsx`
- `web/lib/branchTrack.ts` 僅在需要新增純前端 selector/sort 時修改

### 6.6 驗收

- 481 筆不再全部以等權卡片搶注意力；10 秒內能篩到可追蹤/樣本足夠分點。
- 鍵盤可操作 filter、排序與選取；手機返回路徑清楚。
- 排名、今日動向、權證實驗資料值完全不變。
- `npm run build`；既有 `aggregateBranchRows` 純函式案例仍通過。

## 7. IA-4 自選追蹤工作台

### 7.1 目標

把 `/watchlist` 從收藏清單改成每天可處理的追蹤佇列，不等待 Armed 也可先做手動版。

### 7.2 IA-4A：不依賴 Armed 的手動版

- 顯示現價距觀察價、距失效價百分比(用既有 JSON 前端計算)。
- 排序：接近觀察價、接近失效價、風險、漲跌、加入順序。
- 預設先列「接近失效/有明顯風險」；其餘在一般追蹤區。
- 沒有快取 JSON 的自選仍保留，誠實顯示原因。

### 7.3 IA-4B：Armed 完成後的增強

- 顯示 Armed/Triggered/Extended/Faded 狀態與來源。
- 可選一鍵加入今日 Armed；不得自動把所有 Armed 寫入使用者自選。
- 狀態定義完全依 `docs/22`，本文件不另定門檻。

### 7.4 預計檔案與驗收

- `web/app/watchlist/page.tsx`
- 必要時新增純前端排序 helper 與測試
- 不改 Supabase schema/RLS；不新增後端。
- 375px 可清楚看到股票、距關鍵價、風險；排序有可見選中態與鍵盤操作。
- `npm run build`；未登入、空清單、缺 JSON、正常資料四種狀態皆驗證。

## 8. Phase 關係與建議順序

| 順序 | Phase | 可否現在獨立做 | 依賴/關卡 |
|---|---|---|---|
| 1 | IA-1A 首頁 Pilot | ✅ 可另確認 | 純前端重排，不做 Armed/F4 語意 |
| 2 | IA-2 個股判讀 | ✅ 可另確認 | 不改資料契約；先保護分點/KChart 行為 |
| 3 | IA-3 分點研究 | ✅ 可另確認 | 既有 track JSON；不改排名算法 |
| 4 | IA-4A 自選手動版 | ✅ 可另確認 | 現有 stock JSON + Supabase watchlist |
| 之後 | IA-1B 榜單收斂 | ⚠️ 另確認 | 與 `docs/23` F4 / `docs/22` A2 重疊 |
| 之後 | IA-4B Armed 增強 | ⛔ 待 Armed | `docs/22` A1–A3 |

Access A0–A2 仍是全專案最高外部狀態優先；本文件不代表 UI 工作可自行插隊。
若使用者明示允許 UI Pilot 與 Access/B Phase 2–3 並行，Executor 才可依單一 Phase 開工。

## 9. 不做清單

- 不做全站換色、Fira/Inter 全站換字、crypto 紫金風、重新設計 logo。
- 不把每個區塊都改 Bento；不重寫 shadcn primitive 或 K 線庫。
- 不新增後端/API、即時推播、LINE、五年分點、地緣/關鍵分點。
- 不新增「總覽之外又一個總覽」頁；不復活 `/explore`。
- 不把 UI 名稱變更當成資料語意變更。
- 不因卡片顯示新狀態就自行定義 Armed/Active 門檻。

## 10. 共用驗收矩陣

每個 Phase 至少驗收:

- `cd web; npm run build`
- 375 / 768 / 1024 / 1440，無非預期水平 overflow
- 深色、淺色；已知淺色 brand token 問題只回報，不順手重畫
- keyboard focus、active/selected/expanded state、合理 tab order
- `prefers-reduced-motion`；動畫 150–300ms，只用 transform/opacity
- loading skeleton、教育性 empty state、error/fetch failure
- 漲跌/流入流出/風險不只靠顏色
- 資料日與免費資料限制仍可見
- `git diff` 無 pipeline/workflow/DB/部署檔案

## 11. Reviewer 必查

1. 是否真的讓 Primary Queue 更早出現，而非只換陰影/圓角。
2. 是否把大量比較資料誤做更多卡片。
3. 是否遺失現有榜、理由、風險、分點或權證資料的到達路徑。
4. IA-1B 是否偷加入 Armed/Triggered 或改 list/score 語意。
5. IA-2 是否破壞分點勾選、KChart pane、D/W/M 重取樣或 localStorage 偏好。
6. IA-3 是否把樣本不足分點包裝成可靠績效，或把權證實驗描述成確定主力。
7. IA-4 是否改 Supabase schema/RLS，或自動寫入使用者自選。
8. 是否新增色票/字體/依賴/路由，或擴張到無關重構。
9. 是否通過 build、RWD、keyboard 與空/錯誤狀態驗證。

## 12. 給下一個 Executor 的固定起手式

複製 `docs/24` §1，並將以下內容填入；**一次只選一個 IA Phase**:

```text
必讀加檔:
docs/19_ui_guidelines.md、docs/25_ui_information_architecture_plan.md、
docs/07_frontend_pages.md 對應章節、以及本 Phase 涉及的現有頁面/元件。
若做 IA-1B/IA-4B，再加 docs/20、docs/22、docs/23。

Confirmed Scope:
- Phase:【IA-1A / IA-1B / IA-2 / IA-3 / IA-4A / IA-4B，只填一個】
- 目標:依 docs/25 對應章節
- 可動檔案:僅該章列出的 web 檔案 + STATUS/docs/25 狀態更新
- 驗收:docs/25 §10 + 該 Phase 專屬驗收
- 不做:pipeline、評分、JSON 語意、workflow、WAL、Access/R2、push main
```

Executor 開工前仍須先回報理解、檔案、風險與測試，等待使用者確認。完成後更新本檔
§0 狀態表與 `STATUS.md`，Reviewer 只 review 該 Phase diff，不順便實作下一 Phase。
