## Handoff

- **Current Goal**: 今日 UI 修正全數完成並上線（Phase 3 strategy_meta + KChart 工具列 + BranchFlowSection + 分點頁統計 card）。下一步可選：WP-B6 全市場回補（需使用者批准）或繼續 UI 細化。
- **Current Branch**: `main`
- **Workflow(2026-08-19)**:規劃 → Grok 4.6 High；執行 → Auto agent；完成 → 更新 md + commit + push（見 `AGENTS.md`、`docs/17` Workflow D）
- **Current Agent**: Cursor
- **Work Completed（本次）**:
  - 新增 Phase 3 策略績效報告產出器（只讀 DB）與 CLI `phase3-strategy-performance-report`：輸出每策略 5/10/20 日 win rate、avg/median 與最近區段(20d)表現（Markdown）。
  - 新增 CLI `phase2-diff-report`：比較解耦後分數 vs 舊制 S1–S10 bonus 回加模擬，產出 markdown，**不寫 DB**。
  - 本機樣本報告：`docs/reports/phase2_score_diff_2026-07-06.md`（77 檔、0 檔受影響——該日無 S1–S10 觸發加分）。
  - 先前已完成：13 策略驗證、手機版個股頁 RWD/分點圖修復（另 commit）。
- **Files Changed（本次，2026-08-19）**:
  - `pipeline/radar/export/json_export.py`：新增 `_STRATEGY_STATUS`、`_build_strategy_meta()`，`radar.json` 輸出加 `strategy_meta`
  - `web/lib/types.ts`：新增 `StrategyPerfHorizon`、`StrategyMeta` 型別
  - `web/app/page.tsx`：策略 Tab Retired/Shadow badge；Retired 按鈕降級樣式（灰化、hover 提示）；desc 欄顯示 20 日勝率/樣本摘要
  - `web/components/KChart.tsx`：工具列拆成兩列（Row1 固定可見：日K/週K/月K + MACD/KD/RSI + 手機版主力/分點；Row2 均線 wrap：5日到年線 + 布林 + 桌機主力）
  - `web/components/BranchFlowSection.tsx`：摘要 card 改對稱排列；時間範圍改 wrap 換行全部可見；說明文字縮短防截斷
  - `web/app/branch/page.tsx`：統計列改 `grid-cols-2`（2×2）；標籤文字更清楚（「績效樣本足夠」「有歷史明細」「排行榜分點數」「資料起始日」）
  - `handoff.md`、`docs/STATUS.md`（文件同步）
- **Current Git Status**: clean；最新 push `450f284`（branch page stats fix）。
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
- **Phase 2 diff report 用法**:
  ```bash
  python -m pipeline.radar.cli phase2-diff-report
  python -m pipeline.radar.cli phase2-diff-report --date 20260706 --out docs/reports/phase2_score_diff_20260706.md
  ```
  VPS 上對 `radar.db` 跑最新 `daily_scores` 日，產出報告後交 Reviewer/使用者確認，再決定是否批准全市場重算。
- **Not Yet Done（專案層級）**:
  - **WP-B6**：全市場歷史回補（`docs/30`，待使用者確認開跑，高風險，改正式 DB）。
  - **B 方案 Phase 2 剩餘**：全市場重算（watchline crossed=0，目前不急，待使用者另案批准）。
  - **WP-B7**：Supabase 白名單取代 Cloudflare Access（需資安審查）。
  - **Phase 3 下一步**：策略績效接 UI（Active 升級流程、首頁策略績效卡細化）。
- **Next Suggested Actions**:
  1. 使用者確認手機 UI 改動無誤（個股頁工具列 / 分點區 / 分點頁統計 card）。
  2. 批准 WP-B6 全市場回補（VPS 執行，約 1–2 小時）。
  3. 或繼續 UI 細化 / Phase 3 策略 UI 接 export。
- **Files That Should Not Be Modified**:
  - `pipeline/radar/db.py` 的 WAL checkpoint 機制。
  - `docs/*` 核心規則文件（任務相關的 `STATUS`/規劃檔/workflow 檔依 Workflow D 必須同步；勿無關改動）。
  - `.github/workflows/*.yml`（排程部署設定）。
- **Risk Notes**:
  - 13 策略榜單在 `radar.json` 只存 `stock_id` 陣列，體積可控。
  - S12 分點集中已在 `scores.py` 實作，依賴評分池分點資料（前 15 大買賣超裁剪）。

---

> **Planner(Grok 4.6 High)**:讀 AGENTS.md、docs/17、STATUS、handoff → 產出 Confirmed Scope。  
> **Executor(Auto)**:讀 Scope + Workflow D → 實作 → 更新 md → commit → push。Scope 未定或高風險時才「先 plan、等確認」。
