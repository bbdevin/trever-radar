# 23 產品功能與視覺優化 Backlog(2026-07-10)

> 供後續 Planner / Executor / Reviewer 接手的**可執行待辦清單**。
> 本檔只規劃「還可以新增什麼」與「視覺怎麼優化」;不取代 `docs/20`/`21`/`22`。
> 設計建議來源:ui-ux-pro-max(`web/.agents/skills/ui-ux-pro-max`)對
> fintech / stock radar / dark OLED / shadcn 的檢索結果,**已依本專案既定 token 過濾**,
> 不得照抄搜尋結果裡的 Inter 字體、紫金配色或改預設淺色主題。

## 0. 硬約束(違反即退回)

1. **優先序不得插隊**:先 `docs/21` Access → `docs/20` B Phase 1–3 → `docs/22` Armed → 本檔 V* / F*。
2. **不新增第 14 策略、不擴 `/explore`、不開五年分點 / LINE / V2 盤中**(見 `docs/20`)。
3. **不引入新配色體系**;一律用 `docs/19` + `web/app/globals.css` 既有 token;紅漲綠跌不可翻。
4. **數字字體維持 Manrope(`.num`)**,不改成 Inter 當全站 body(ui-ux-pro-max 建議僅作參考)。
5. **靜態站原則不變**:無後端 API、無常駐推播伺服器;個人化只走既有 Supabase。
6. **一次只做一個 Phase**;改前看 `git status`/`git diff`;不動 workflow / WAL / `adj_factor` / R2 實作,除非任務明確是那一項。
7. **正式重算、push `main`、Access/R2 外部設定**必須人類另批。

## 1. 全域優先序(單一真相對照)

| 順序 | 文件 | 內容 | 狀態 |
|---|---|---|---|
| 1 | `21` | Access 鎖站 A0–A2 | 待執行(外部 Cloudflare) |
| 2 | `20` | B Phase 1 UI 刪減 | 待確認實作 |
| 3 | `20` | B Phase 2–3 策略解耦+績效 | 待確認 |
| 4 | `22` | Armed A1–A3 狀態池 | 規劃定案、未寫碼 |
| 5 | **本檔 V1–V3** | 視覺優化(可與 Phase 1 後或 Armed UI 同波,但勿混高風險) | 📝 本檔 |
| 6 | **本檔 F1–F4** | 低成本新功能(Armed 之後) | 📝 本檔 |
| 延後 | `20` Phase 4 / `21` R2 / 地緣分點 | 高風險或證據不足 | 延後 |

---

## 2. 視覺優化(V 系列)— ui-ux-pro-max 對齊後的可執行包

設計方向定調:**OLED 深色、資料密集但可掃讀、狀態色(綠/琥珀/紅)輔助、微互動 150–300ms、骨架屏、無 emoji icon**。  
**反模式**(本專案禁止):預設改淺色、裝飾性無限動畫、用 width/height 做條動畫、色彩當唯一訊號、紫金「crypto」調色盤。

### V1 — 資訊密度與掃讀(低風險,建議 B Phase 1 後立刻做)

**目標**:首頁/自選在 5 秒內看出「該盯誰」,減少卡片噪音。

| 工作項 | 做法 | 預計檔案 |
|---|---|---|
| V1.1 卡片層級 | 主數字(漲跌%、綜合分或狀態)最大;次要分數改一行小字或摺疊 | `web/components/StockCard.tsx` |
| V1.2 狀態色條 | 左側 2–3px inset 邊條表達狀態(未來接 Armed/Triggered;現在可用風險/觀察門檻) | `StockCard.tsx` + token |
| V1.3 觸控與 hover | 可點列 `min-h-11`、`cursor-pointer`、`transition-colors duration-200`;icon 鈕補 `aria-label` | 被改到的 list/tab 元件 |
| V1.4 空/載入 | 空狀態寫「為什麼空」;列表載入用 shadcn `Skeleton` 對齊版面,少用 spinner | 首頁、`/watchlist`、`/branch` |

**驗收**:
- [ ] `npm run build` 過
- [ ] 375 / 768 / 1440 無橫向溢出
- [ ] 無新增 emoji icon;lucide 一致
- [ ] 漲跌除顏色外有 +/- 或箭頭
- [ ] 未改配色 token 語意

**不做**:換字體家族、加 Sidebar 導航大改、重做整站玻璃擬態。

### V2 — 榜單/表格一致性(中風險 UI,不動資料語意)

**目標**:分點明細、權證明細、集中度(併入 branch 後)同一套表格式掃讀。

| 工作項 | 做法 | 預計檔案 |
|---|---|---|
| V2.1 表格 | 結構化資料優先 shadcn `Table` + 既有 TanStack(權證已用);分點日報若仍是 div grid,只在「改到的區塊」遷 | `web/app/stock/page.tsx`、branch 相關 |
| V2.2 排序回饋 | 可排序欄位有明確選中態(inset ring / `aria-sort`) | 表格元件 |
| V2.3 Freshness | 過期資料列更醒目(已有 stale 文案處加強對比,勿只靠灰字) | `web/app/page.tsx` |

**驗收**:鍵盤可辨識目前排序欄;手機表可橫滑或改關鍵欄優先,不裁掉代號/漲跌。

### V3 — 主題與焦點(可選,低優先)

| 工作項 | 做法 | 備註 |
|---|---|---|
| V3.1 淺色切換 UI | token 已備妥;加明確 toggle + `localStorage` | **預設仍深色**;ui-ux-pro-max 建議 dark-only,本專案允許「可切、不預設淺」 |
| V3.2 Focus ring | 鍵盤 focus 可見(`ring` token),勿 `outline-none` 無替代 | a11y High |
| V3.3 Toaster | layout 掛 shadcn Sonner,用於自選加入成功等短回饋 | 非必須;有做才加依賴使用面 |

**不做**:為淺色重畫品牌色;不做 landing marketing hero(本站是工具不是行銷頁)。

### V 系列與 ui-ux-pro-max 對照(給 Reviewer)

| 建議來源 | 本專案採納 | 本專案拒絕 |
|---|---|---|
| Dark OLED / 高對比 | ✅ 已是預設 | — |
| 150–300ms、transform/opacity | ✅ 見 `docs/19` | 裝飾 bounce / 長於 500ms |
| Skeleton > spinner | ✅ V1.4 | — |
| shadcn Table / DataTable | ✅ V2 | 全站硬上 Sidebar |
| Inter + 工業 slate 新色 | — | ❌ 維持既有 token + Manrope 數字 |
| Fintech 紫金配色 | — | ❌ |
| Heatmap 換庫(D3/Plotly) | — | ❌ 資金流 Treemap 已存在,不重做 |

---

## 3. 功能新增(F 系列)— 在 Armed 之後、仍符合簡化

以下**不是**現在就開做;標依賴。每項都要能用既有 JSON/SQLite 欄位或小幅 export 擴充完成。

### F1 — 自選戰情板強化(依賴 `22` A2/A3 或可先做手動版)

| ID | 功能 | 做法 | 依賴 |
|---|---|---|---|
| F1.1 | 自選列顯示觀察價/失效價距離% | 前端算 `(price-watch)/watch` | 欄位已有 |
| F1.2 | 自選依「距失效近→遠」排序 | 純前端 sort | 無 |
| F1.3 | 一鍵加入今日 Armed | 呼叫既有 watchlist API | `22` A1 有 `lists.armed` |

**驗收**:未登入仍有教育性空狀態;不新增後端。

### F2 — 今日變化摘要(低成本「日報感」)

| ID | 功能 | 做法 | 不做 |
|---|---|---|---|
| F2.1 | 首頁頂部 3 句摘要 | export 產出 `radar.summary`(例:Armed N 檔、雙來源 M、權證倍數異常 K) | LLM 文案 |
| F2.2 | 「較昨日新進池」標記 | 比對前一交易日 lists(需 export 帶 `prev_ids` 或前端 localStorage 記昨日) | 推播 |

**風險**:localStorage 方案跨裝置不一致;偏好 export 帶差集。

### F3 — 個股頁「為什麼在池裡」面板

| ID | 功能 | 做法 |
|---|---|---|
| F3.1 | 單一「訊號摘要」區塊 | 合併 reasons/risks/分點/權證重點,上限 5 條理由 + 3 條風險 |
| F3.2 | 來源徽章 | branch / warrant / both / strategy tag(只顯示,不改分) |

**對齊**:`docs/04`「人看得懂的觸發理由 + 風險」;禁止只顯示分數。

### F4 — 市場掃描收斂(配合 `20` Phase 1 + `22`)

| ID | 功能 | 做法 |
|---|---|---|
| F4.1 | hot/surge/strong 收成「掃描」次選 | 單一表 + filter(金額/漲跌/量比),減少一級 tab |
| F4.2 | 策略 tab 四類分群 | 見 `docs/20` §4.1;預設展開「籌碼事件」S11–S13 |

**禁止**:再加獨立 Mark 類死碼榜。

### 明確不進本 Backlog(已否決或延後)

- 第 14+ 策略、地緣/關鍵分點 UI、五年分點、LINE Bot、盤中 V2、付費牆、公開註冊
- 權證分點納入綜合分、把「實驗」改回「大戶確定」文案
- 為視覺重寫 K 線庫(維持 lightweight-charts)

---

## 4. Executor 工作包(複製即可開任務)

每個工作包 = 使用者確認後的**單一**任務。完成後更新 `STATUS.md` + 本檔狀態欄。

### 工作包 WP-V1(視覺掃讀)

```
角色: Executor
範圍: docs/23 §2 V1 全部;不得改 pipeline、不得改評分
必讀: AGENTS.md, docs/19, docs/07, docs/23
驗收: §2 V1 清單 + npm run build
禁止: 新依賴(除非已有 skeleton)、改 globals 色票語意、push main 未另批
```

### 工作包 WP-V2(表格一致)

```
角色: Executor
範圍: docs/23 §2 V2;只改被點名的表區塊
必讀: docs/19, docs/23, 現有 TanStack 權證表實作
驗收: §2 V2 + 手機可讀
禁止: 重構無關頁、引入 Recharts 取代既有圖
```

### 工作包 WP-F2(日報摘要)

```
角色: Executor
範圍: export 增加 summary 欄 + 首頁展示;規則模板字串,不用 LLM
必讀: docs/04 語氣, docs/22 狀態名, docs/23 §3 F2
驗收: pytest 或 export 單元測試;無資料時不崩潰
禁止: 改 final 權重、新增策略 code
```

### 工作包 WP-F1 / WP-F3 / WP-F4

分別對應 §3;須在 `docs/22` 相關 A 段完成或使用者明示可並行後才開。

---

## 5. Reviewer 必查

1. 是否插隊做了 Access/B/Armed 之前的「大功能」?
2. 是否引入新色票、Inter 全站、紫金 crypto 風?
3. 是否又加策略或新一級路由?
4. 動畫是否只用 transform/opacity、≤300ms、尊重 reduced-motion?
5. 空狀態是否可教育?icon-only 是否有 aria-label?
6. 是否誤動 WAL / workflow / adj_factor / R2?

---

## 6. 狀態表(實作時更新)

| ID | 狀態 | 備註 |
|---|---|---|
| V1 | ✅ 完成(2026-07-11) | WP-V1:卡片層級收斂+狀態色條(risk/watch/neutral,僅用既有 token)+觸控/aria-label+骨架屏/教育性空狀態;`npm run build` 過 |
| V2 | ✅ 完成(2026-07-11) | WP-V2:權證標竿表補 `aria-sort`+鍵盤可聚焦排序鈕+選中態(inset ring/亮字);`/branch` 集中度榜與今日買超遷語意化 `<table>`(對齊權證表、`overflow-x-auto` 手機可橫滑、不裁代號/漲跌);首頁 stale 標示改琥珀 `Clock` 徽章。卡片列(分點前13/權證大戶群組)不硬遷;無新依賴、未改配色 token 語意;`npm run build` 過 |
| V3 | ◑ 部分完成(2026-07-11) | **V3.1 淺色切換 ✅**:頂欄加 `ThemeToggle`(lucide `Sun`/`Moon` icon-only+aria-label,深色顯示 Sun/淺色顯示 Moon),接既有 `.dark` class 機制(未新增 token);`localStorage('theme')` 記偏好;FOUC 由 `layout.tsx` `<body>` 開頭極小 inline script 防護(僅在曾選 `light` 時提前移除 `.dark`,預設仍深色);`globals.css` 補 `html`/`html.dark` 的 `color-scheme` 對應。**V3.2 Focus ring ✅**:全站互動元素既有全域 `:focus-visible` outline(globals.css)覆蓋大多數;`/branch` 兩處展開鈕原 `focus:outline-none` 無替代,改 `focus-visible:ring-2 ring-inset ring-ring`(父層 `overflow-hidden` 會裁 outline offset,故用 inset ring)。**V3.3 Sonner ⬜ 未做**:需新增 npm 依賴(`sonner`),依硬約束「新依賴另批」留使用者決定。淺色抽查:body/卡片/表格/muted 文字/destructive 狀態條/邊框皆 ≥4.5:1 可讀;**已知淺色 token 問題(只回報未改,依 docs/23「不為淺色重畫品牌色」)**:①brand-extension token `--ink-2`(綜合分數字)、`--warn`(琥珀徽章/文字)僅有 `:root` 深色調值、`.dark` 未覆寫→兩主題同值,在淺底上 `--ink-2`≈1.8:1、`text-warn`≈1.7:1 偏低;②紅漲綠跌 `--up/--down` 兩主題共用,淺底約 3:1(大/粗數字達標、小字偏低);③KChart 畫布為 `transparent`(淺色下呈白底)但 grid/軸色 `#222220`/`#898781` 寫死深色調,淺底呈較刺眼深格線但可見,依規範不重畫。`npm run build` 過。 |
| F1 | ⏳ 待 Armed | |
| F2 | ⏳ 待確認 | 可與 Armed A1 同波評估 |
| F3 | ⏳ 待確認 | |
| F4 | ⏳ 綁 `20`+`22` | |

## 7. 給下一個 agent 的起手式

1. 讀 `AGENTS.md`、`project-context.md`、`STATUS.md`、`docs/20`、`docs/22`、**本文件**、`docs/19`。
2. 看 `git status` / `git diff`。
3. 只執行使用者點名的 **WP-*** 或單一 V/F ID。
4. 先列檔案與風險 → 等確認再改碼(若使用者用 Pilotfish 模板且明示可直接做,从其指示)。
5. 完成後更新本檔 §6 與 `STATUS.md`,留下 handoff。
