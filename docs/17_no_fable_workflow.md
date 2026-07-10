# 17 沒有 Fable 的 AI 開發流程(source of truth)

> **檔名因相容性保留**,本流程實際適用於**所有模型**,不是「沒有 Fable 時才啟用」的降級方案。任何高階模型都可依本次任務被指定為 Planner / Executor / Reviewer。

> 這份是完整版流程的 **source of truth**。`AGENTS.md` 只放精簡規則並指向這裡,避免兩份文件的角色定義互相漂移——改流程只改這裡,`AGENTS.md` 的 Agent Roles 表格保持精簡摘要即可。

## Purpose

本專案**不依賴任何單一高階模型**長期在場,角色由本次任務指定。以下情境都要能正常運作而不停擺:

- 任一高階模型被指定為 Executor、正常開發
- 當前模型中斷/沒額度,換另一個模型接手繼續
- 只有一個模型能做 Reviewer(只 review,不做開發)
- 一個 agent 做到一半,需要交給另一個 agent 接力

## Core Concept

```
文件(docs/、AGENTS.md)                     = 專案的大腦,記住所有決策與現況
人類使用者                                   = 唯一決策者
Executor(如 Claude Code / AGY / Gemini / Codex / GPT)  = 執行者(讀文件 → 做事 → 留下摘要)
Reviewer(同上任一模型)                     = 驗收者(review,不代表可自動放行)
Cursor                                       = 控制中心(看、管、人工確認)
```

**推論**:任何 agent 斷線、換人、換模型,都不影響專案能不能繼續——因為下一個 agent 只要讀文件就能接上,不需要對話歷史。這是本文件存在的唯一目的。

---

## Workflow A:標準流程(任一模型任 Executor)

1. Cursor 開啟專案。
2. Executor 讀 `AGENTS.md` 與相關 `docs/*`(見 `AGENTS.md` Required Reading)。
3. 看 `git status`、`git diff` 確認工作區現況。
4. 提出短 plan(目標、要動的檔案、預期風險)。
5. 執行。
6. 列修改摘要:修改了哪些檔案 / 內容 / 測試方式 / 風險 / 下一步。
7. 交給 Reviewer review `git diff`。
8. 依 review 意見修正。
9. **使用者確認後**才 `commit` / `merge` / `push main`。

## Workflow B:模型/agent 交接流程

1. 交接前,前一個 agent 盡量留下 handoff(見 `docs/18_handoff_template.md`)。若來不及留,接手的 agent 從 `git diff` 與現有文件自行重建現況理解。
2. 接手的 agent 讀 `AGENTS.md` / `docs/STATUS.md` / handoff(若有) / `git diff`。
3. **先輸出理解摘要,不改任何檔案。**
4. 提出**有限範圍**的 plan——不擴張、不重新設計,只完成 handoff 或使用者指定的範圍。
5. 使用者確認後,接手的 agent 只改指定檔案。
6. 列修改摘要(同 Workflow A 步驟 6)。
7. 交 Reviewer review。
8. 使用者決定:保留 / 退回 / 等原 agent 回來後整合。

## Workflow C:未被指定角色的 agent(低信任情境)

- **不做**:架構大改、destructive migration(刪表、改 schema 且無法回滾)、改部署設定(workflow yaml、secrets、DNS)。
- **只做**:文件整理、小 bug 修復、範圍清楚孤立的小改動(isolated changes)。
- 每次改動範圍要小,附 `git diff` 給使用者看。
- 任何看起來「應該一起處理」的相關但未明確要求的事——不做,留給使用者決定要不要展開成新任務。
- 重要決策(要不要合併、要不要繼續某方向)一律留給使用者,不自行判斷。

---

## 高風險決策流程(單一模型不得獨自拍板)

**核心原則:不讓任一 AI 獨自做高風險決策。**

流程:

```
Planner(或當前執行的 agent)提出 A/B/C 方案
        ↓
Reviewer 審查每個方案的風險
        ↓
執行者補充可行性(工時、相依性、副作用)
        ↓
人類選擇
        ↓
選定方案才進入 Workflow A/B/C 執行
```

### 高風險項目清單(必須走此流程,不可跳過)

- 資料庫 schema 大改
- 會影響既有資料的 migration
- 大量資料 backfill(例如分點歷史擴到 5 年、全市場深歷史回補)
- 正式部署(任何形式的 `main` push 觸發生產環境變更)
- 資安/認證授權變更(登入機制、金鑰輪替、權限模型)
- 資料源替換(例如換一個分點資料來源、換一個部署平台)
- 架構重寫(語言、框架、資料庫引擎等級的變更)

這份清單與 `AGENTS.md` 的「本專案專屬危險清單」是同一批風險的兩種呈現方式:`AGENTS.md` 列的是**具體的、已知的地雷**(WAL checkpoint、DB 續存鏈等);這裡列的是**決策層級的分類**,判斷「這個新任務算不算高風險、要不要走 A/B/C 流程」時用這份清單對照。

---

## 統一規劃流程(Planner 必遵)

1. 閱讀 Required Reading(見 `AGENTS.md`)。
2. 查看 `git status` 與必要背景。
3. 只讀取本次任務直接相關的文件及程式碼。
4. 預設不修改任何檔案。
5. 優先分析重複、整合、刪減與 UI 統一,再提出新功能。
6. 每項建議說明效益、成本、風險與優先順序。
7. 輸出可直接交給 Executor 執行的工作清單。
8. 不推翻已定案架構。
9. 不自行擴張 MVP。
10. 不將重要決策只留在對話中。

## Token 節省規則

- 同一任務原則上只由一個高階模型做完整規劃;第二個模型只做交叉審查。
- 交叉審查不重新掃描完整專案,只檢查遺漏 / 矛盾 / 過度設計 / 高風險問題,最多提出 5 項重大修正。
- 小型任務不啟動多模型或 subagent。
- Reviewer 優先只讀 plan 或 git diff。
- 模型切換時必須先讀 handoff、`git status` 與 `git diff`。

---

## 與 `AGENTS.md` 的分工

- `AGENTS.md`:精簡規則、文件現況表、危險清單、Agent Roles 摘要表——**agent 進專案第一眼要看到的東西**。
- 本檔(`docs/17`):完整流程細節、三種 Workflow 的逐步驟、高風險決策流程的完整邏輯——**需要判斷「現在該怎麼做」時查的細節**。
- `docs/18_handoff_template.md`:交接時**填的表格本身**,與流程描述分開,避免這裡越寫越長。

三份文件循環引用但職責不重疊;修改流程規則只改本檔,`AGENTS.md` 的摘要落後於本檔是可接受的(本檔才是 source of truth)。
