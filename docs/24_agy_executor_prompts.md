# 24 AGY / Executor 交辦提示詞(直接複製)

> 給人類使用者交辦 **AGY(Gemini)** 或其他 Executor 時複製貼上。
> 交接表格仍用 `docs/18`;流程用 `docs/17`。本檔只放**任務提示詞**。
> 原則:**一次只交一個工作包**;Access / R2 外部設定 / push `main` 預設不交自動執行。

## 0. 使用方式

1. 開短 branch(建議):`agy/phase1-ui-trim`、`agy/wp-v1`、`agy/armed-a1` 等。
2. 先貼 **§1 通用起手**,再貼 **§2 對應任務塊**。
3. 每次附上 **§3 防爆加句**。
4. AGY 回 plan 後,你回「確認」再讓它改碼(除非你改用 §4 激進版)。

---

## 1. 通用起手(任何任務都先貼)

```
你現在是 Trever Radar 的 Executor(AGY)。

必讀(依序):
1. AGENTS.md
2. docs/project-context.md
3. docs/STATUS.md
4. docs/17_no_fable_workflow.md
5. docs/18_handoff_template.md
再讀本次任務指定文件。

規則:
- 先看 git status / git diff / 目前 branch
- 先輸出:理解摘要、要改的檔案、風險、測試方式
- 等我回「確認」後才改碼(不要先動手)
- 不重構無關檔、不改 .env/secrets、不改 workflow yaml(除非任務明確要求)
- 不動 WAL checkpoint、cache/release DB 鏈、adj_factor
- 不得 merge、不得自行 push main、不得觸發正式部署
- 完成後用 docs/18 輕量交接格式回報

本次任務:【在這裡填 WP 或 Phase,或直接接下方任務塊】
```

---

## 2. 依優先序的任務塊

### 2.1 B 方案 Phase 1(建議最先交的程式任務)

```
【任務】docs/20 B 方案 Phase 1:UI 刪減與合併

必讀:docs/20 §5 Phase 1、docs/19、docs/07

範圍:
1. 隱藏尚未實作的盤中導覽
2. 集中度併入 /branch 今日動向
3. 題材只留首頁;移除 /explore 導覽與頁面
4. 「權證大戶」改名「權證分點異動(實驗)」並補資料限制說明
5. 移除確認未使用的 recharts 及未引用 UI primitive

禁止:改 pipeline 評分、改 workflow、做 Armed、做 Access/R2 實作

驗收:npm run build 通過;首頁/branch/stock/watchlist 可用;無資料有教育性空狀態
完成後更新 docs/20 Phase 狀態與 docs/STATUS.md
建議 branch:agy/phase1-ui-trim
```

### 2.2 視覺 WP-V1(Phase 1 之後)

```
【任務】docs/23 工作包 WP-V1(視覺掃讀)

必讀:docs/23 §2 V1、docs/19、docs/07

只做 V1.1–V1.4。不改 pipeline、不改評分、不引入新配色/Inter、不加第14策略。
驗收照 docs/23 §2 V1 checklist + npm run build。
完成後更新 docs/23 §6 與 STATUS.md。
建議 branch:agy/wp-v1
```

### 2.3 視覺 WP-V2

```
【任務】docs/23 工作包 WP-V2(表格一致)

必讀:docs/23 §2 V2、docs/19;參考既有 TanStack 權證表實作

只改被點名的表區塊。禁止重構無關頁、禁止引入 Recharts 取代既有圖。
驗收:docs/23 §2 V2 + 手機可讀 + npm run build。
建議 branch:agy/wp-v2
```

### 2.4 Armed A1(Access + B 有進度後)

```
【任務】docs/22 A1:export lists.armed / 來源徽章 / 風險欄

必讀:docs/22、docs/04(W3/B3)、docs/20(策略不解耦前勿改 tech_score)

重用既有 S12/W3/B3/權證倍數;不新增策略 code、不抬綜合分、不新開一級路由。
補單元測試。完成後更新 docs/22 狀態與 STATUS.md。
禁止:push main、全市場重算、改 workflow。
建議 branch:agy/armed-a1
```

### 2.5 Armed A2 / A3

```
【任務】docs/22 A2:首頁「未發動」「已發動」tab(可含市場近似榜收斂的前端部分)

必讀:docs/22 §3、docs/19、docs/23 F4(若一併收斂 tab 須我另確認)

依賴:A1 已有 lists.armed(或 mock 契約已定)。不新開一級路由。
驗收:npm run build;空狀態可教育;權證單來源不宣稱主力卡位。
建議 branch:agy/armed-a2
```

```
【任務】docs/22 A3:自選狀態色 + 可選一鍵加入今日 Armed

必讀:docs/22 §3、既有 web/lib/watchlist.tsx、docs/23 F1

未登入須有教育性空狀態;不新增後端。
建議 branch:agy/armed-a3
```

### 2.6 日報摘要 F2

```
【任務】docs/23 F2 / WP-F2:今日變化摘要

必讀:docs/23 §3 F2、docs/04 語氣、docs/22 狀態名

export 增加 summary(規則模板字串,不用 LLM)+ 首頁展示。
驗收:pytest 或 export 單元測試;無資料不崩潰。
禁止:改 final 權重、新增策略 code。
建議 branch:agy/f2-summary
```

### 2.7 只做 Review(AGY 當 Reviewer)

```
你現在是 Reviewer,只讀不改碼。

請 review 目前 git diff(或指定 PR/branch)。
檢查:AGENTS.md 危險清單、是否偏離 docs/20–23 優先序、測試是否夠、有無過度設計。
只回報問題與建議;若要改,先列檔案等我確認。
```

---

## 3. 防爆加句(建議每次附上)

```
若發現「應該順便做」的相關工作:列出來問我,不要自行擴大範圍。
若任務與 docs/20 或 STATUS 優先序衝突:停止並說明衝突,等我決策。
```

---

## 4. 激進版(已完全信任該範圍時才用)

> 與 §1 互斥:用了這段就**不要**再要求「等確認才動手」。
> 仍禁止 push main / 改 workflow / 高風險外部設定,除非你在任務塊寫明。

```
你是 Executor(AGY)。讀 AGENTS.md、project-context、STATUS、本次任務文件後直接執行下列範圍。
不要擴大需求;不要改無關檔;不要 push main;不要改 workflow/WAL/adj_factor。
做完跑相關測試與 build,用 docs/18 輕量交接回報,並更新 STATUS 與對應 docs 狀態欄。

本次任務:
【貼 §2 任務塊】
```

---

## 5. 不建議交 AGY 自動做的項目

| 項目 | 原因 |
|---|---|
| Cloudflare Access 實際設定 | 外部控制台 + 白名單,需人類 |
| R2 bucket / secrets / workflow 接入 | 高風險,見 `docs/21` |
| `git push main` | 觸發正式部署 |
| B Phase 2 全市場重算回灌 | 資料語意變更,另批 |
| 五年分點 / LINE / 盤中 V2 | `docs/20` 已延後 |

這些改由人類執行,或另開「只產出操作步驟、不改 repo」的 Planner 任務。

---

## 6. 建議交辦順序(給人類)

1. `docs/21` Access(人類在 Cloudflare)
2. §2.1 Phase 1 → AGY
3. §2.2 WP-V1 → AGY(可選)
4. `docs/20` Phase 2–3 → 另確認後再交
5. §2.4–2.5 Armed → AGY
6. §2.6 F2 或其他 `docs/23` WP → AGY
