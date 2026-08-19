## Handoff

- **Current Goal**: ~~實作 13 項選股策略~~ → **已於 2026-07-10 完成**；本次交接任務為**驗證現況 + 更新過期 handoff**（2026-08-19 確認）。
- **Current Branch**: `main`（working tree clean）
- **Current Agent**: Cursor（接手上任 AGY 的過期交接稿）
- **Work Completed（本次）**:
  - 比對 codebase 與 handoff，確認 13 策略後端/匯出/前端**均已實作**，原 handoff「Not Yet Done」為過期內容。
  - 跑 `pytest tests/test_indicators.py tests/test_scores.py`：**63 passed**（含 S1–S10 正/反例、S 策略不解耦分數斷言）。
  - 靜態核對：`json_export.py` 輸出 `strategies: { code: [stock_id] }`，與 `web/lib/types.ts` 及 `page.tsx` 消費方式一致；前後端 13 個 S code 清單一致。
- **Files Changed**: `handoff.md`（本檔更新）；程式碼無 bug，未改 pipeline/web。
- **Current Git Status**: 僅 `handoff.md` 待 commit（使用者未要求 commit 前不提交）。
- **Known Issues**: 無策略相關 bug。策略邏輯改動後正式榜單需等 VPS 下一交易日增量重算才反映（見 `STATUS.md` 已知債務）。
- **Errors/Logs**: 無
- **Tests Run**:
  - `pytest tests/test_indicators.py tests/test_scores.py` → 63 passed
  - `pytest tests/test_json_export.py` → 3 failed（Windows 本機 `ModuleNotFoundError: pipeline` 路徑問題，與策略無關；非本次範圍）
- **13 策略實作位置（已完成，供後續 agent 參考）**:
  | 策略 | 位置 | 備註 |
  |---|---|---|
  | S1–S10 | `pipeline/radar/compute/indicators.py` → `score_technical()` | S1 雙軌（嚴謹/放寬），放寬版 alias 併入 S1 榜 |
  | S11–S13 | `pipeline/radar/compute/scores.py` | 法人連買、分點集中、融券軋空 |
  | 匯出 | `pipeline/radar/export/json_export.py` L235–262, L502 | `strategies` 只存 `stock_id[]`，每榜 ≤40 檔 |
  | 前端 | `web/app/page.tsx` | Tab `mark` + F4.2 四類分群 pills；`web/lib/types.ts` L181 |
  | 測試 | `pipeline/tests/test_indicators.py` | S2–S10 正/反例 + 解耦回歸 |
- **Not Yet Done（專案層級，非本 handoff 原目標）**:
  - **B 方案 Phase 2 剩餘**：舊/新分數差異報告；VPS 全市場重算需使用者批准（高風險）。
  - **B 方案 Phase 3**：各 S code 績效閉環（5/10/20 日勝率報告）。
  - **WP-B6**：全市場歷史回補（`docs/30`，待使用者確認開跑）。
  - **WP-B7**：Supabase 白名單取代 Cloudflare Access（需資安審查）。
- **Next Suggested Actions**:
  1. 若需確認正式站策略榜有資料：登入後看首頁「策略」Tab 各 pill 檔數（需 VPS 已跑過當日管線）。
  2. 若策略規則要調整：改 `indicators.py`/`scores.py` → 補測試 → **VPS pull 最新 main 後重算**（不可只 push 就期待榜單變）。
  3. 下一個 agent 請依 `docs/STATUS.md` 優先序選任務，勿重複實作 13 策略。
- **Files That Should Not Be Modified**:
  - `pipeline/radar/db.py` 的 WAL checkpoint 機制。
  - `docs/*` 核心規則文件（除 `STATUS.md` / `handoff.md` 外不應隨意更動）。
  - `.github/workflows/*.yml`（排程部署設定）。
- **Risk Notes**:
  - 13 策略榜單在 `radar.json` 只存 `stock_id` 陣列，體積可控。
  - S12 分點集中已在 `scores.py` 實作，依賴評分池分點資料（前 15 大買賣超裁剪）。

---

> 你現在是接手本專案的 agent。請先閱讀 AGENTS.md、docs/17_no_fable_workflow.md、docs/18_handoff_template.md、docs/STATUS.md 與此交接文件 handoff.md。請先輸出你理解的狀態、下一步計畫、你預計修改哪些檔案。等待使用者確認後才開始修改。
