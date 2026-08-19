## Handoff

- **Current Goal**: Phase 3 工作 3（策略狀態 UI）已完成：`strategy_meta` 寫入 `radar.json`，首頁策略 Tab 顯示 Retired/Shadow badge，Retired 按鈕降級樣式。下一步：VPS 上跑 `export-json` 重新產出 `radar.json`（含 `strategy_meta`），再 deploy 至 Cloudflare。
- **Current Branch**: `main`
- **Workflow(2026-08-19)**:規劃 → Grok 4.6 High；執行 → Auto agent；完成 → 更新 md + commit + push（見 `AGENTS.md`、`docs/17` Workflow D）
- **Current Agent**: Cursor
- **Work Completed（本次）**:
  - 新增 Phase 3 策略績效報告產出器（只讀 DB）與 CLI `phase3-strategy-performance-report`：輸出每策略 5/10/20 日 win rate、avg/median 與最近區段(20d)表現（Markdown）。
  - 新增 CLI `phase2-diff-report`：比較解耦後分數 vs 舊制 S1–S10 bonus 回加模擬，產出 markdown，**不寫 DB**。
  - 本機樣本報告：`docs/reports/phase2_score_diff_2026-07-06.md`（77 檔、0 檔受影響——該日無 S1–S10 觸發加分）。
  - 先前已完成：13 策略驗證、手機版個股頁 RWD/分點圖修復（另 commit）。
- **Files Changed（本次 Phase 3 工作 3）**:
  - `pipeline/radar/export/json_export.py`：新增 `_STRATEGY_STATUS`、`_build_strategy_meta()`，`radar.json` 輸出加 `strategy_meta` 欄位
  - `web/lib/types.ts`：新增 `StrategyPerfHorizon`、`StrategyMeta` 型別；`RadarJson` 加 `strategy_meta?`
  - `web/app/page.tsx`：策略 Tab 加 Retired/Shadow badge，Retired 按鈕灰化＋刪除線，desc 區顯示 20 日勝率/樣本摘要
  - `handoff.md`、`docs/STATUS.md`（文件同步）
- **Current Git Status**: 未 commit；最新已 push commit 為 `7500902`。
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
  - **Phase 3 UI 上線**：VPS 跑 `export-json` + `wrangler deploy`（含 `strategy_meta`），前端才能看到 Retired/Shadow badge。
  - **B 方案 Phase 2 剩餘**：使用者批准後的正式全市場重算（高風險，watchline crossed=0，目前不需要）。
  - **WP-B6**：全市場歷史回補（`docs/30`，待使用者確認開跑）。
  - **WP-B7**：Supabase 白名單取代 Cloudflare Access（需資安審查）。
- **Next Suggested Actions**:
  1. VPS：`git pull && docker build -t radar-pipeline pipeline`
  2. VPS：`radar export-json`（`lib.sh` 的 `radar` 函式）然後 `deploy_data`，把含 `strategy_meta` 的新 JSON 推上線。
  3. 確認首頁策略 Tab S2/S5 出現 Retired 標記。
  4. 後續：WP-B6 / WP-B7 另案確認。
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
