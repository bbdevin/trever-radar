## Handoff

- **Current Goal**: 實作 13 項選股策略（策略 1~13，略過無資料的策略 14 營收成長），並於前端加入「策略」頁籤與下拉/次選單以動態過濾。
- **Current Branch**: `main` (目前工作區是乾淨的)
- **Current Agent**: AGY (Google model)
- **Work Completed**:
  - 完成了上一個未提交的「產業下鑽子題材與 UI/UX 規範」之測試與 Push。
  - 完成了「13 項選股策略」的實作規劃與評估。
- **Files Changed**: 本次新任務尚未開始修改檔案。
- **Current Git Status**: `working tree clean` (剛完成 push)。
- **Known Issues**: 無
- **Errors/Logs**: 無
- **Tests Run**: 無
- **Not Yet Done**:
  - **後端實作**：
    1. 在 `pipeline/radar/compute/indicators.py` 加入新技術指標（如布林通道寬度、跳空缺口等），並在 `compute_series`/`score_technical` 實作策略 1 ~ 10。
    2. 在 `pipeline/radar/compute/scores.py` 實作依賴籌碼的策略 11 ~ 13（法人連買、分點集中、融券軋空）。
    3. 在 `pipeline/radar/export/json_export.py` 導出 `strategies: { "S1": [...], ... }` 以供前端使用。
  - **前端實作**：
    1. 修改 `web/lib/types.ts` 新增 `strategies` 型別。
    2. 修改 `web/app/page.tsx`，將 `mark` 頁籤擴展為通用的 `strategies` 選單（如下拉選單或 pill-selector），讓使用者可切換並列出對應策略的股票清單。
- **Next Suggested Actions**:
  - 接手的 agent 請依照上方 **Not Yet Done** 的步驟，優先在 `indicators.py` 與 `scores.py` 實作這 13 個策略邏輯。若觸發策略，將 `code` (如 `S1_REBOUND`) 塞進 `reasons` 欄位。接著修改 `json_export.py` 將這 13 個策略的股票清單分別打包到 `radar.json`，最後實作前端切換介面。
- **Files That Should Not Be Modified**:
  - `pipeline/radar/db.py` 的 WAL checkpoint 機制。
  - `docs/*` 核心規則文件（除 `STATUS.md` 外不應隨意更動）。
  - `.github/workflows/*.yml`（排程部署設定）。
- **Risk Notes**:
  - 需留意 13 個策略可能造成 `radar.json` 體積變大，請確保 `json_export.py` 中的 `strategies` 清單只存放 `stock_id` 陣列（如同原本的 `lists.mark`）。
  - S12（主力分點集中）需計算前幾大買進分點的連續性與股價狀態，可能需要先載入多天的分點資料進行過濾，請留意記憶體與 SQL 查詢效能。

---

> 你現在是接手本專案的 agent。請先閱讀 AGENTS.md、docs/17_no_fable_workflow.md、docs/18_handoff_template.md、docs/STATUS.md 與此交接文件 handoff.md。請先輸出你理解的狀態、下一步計畫、你預計修改哪些檔案。等待使用者確認後才開始修改。
