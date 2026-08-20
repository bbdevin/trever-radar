## Handoff

- **Current Goal**: iOS 分點追蹤返回被狀態列擋住已修,並清查全站 overlay/sticky/觸控。等使用者實機驗。
- **Current Branch**: `main`
- **Workflow(2026-08-19)**:規劃 → Grok 4.6 High；執行 → Auto agent；完成 → 更新 md + commit + push（見 `AGENTS.md`、`docs/17` Workflow D）
- **Current Agent**: Cursor
- **Work Completed（本次）**:
  - `/branch` 手機蓋屏改 `.safe-overlay`(瀏海 + Home indicator)
  - sticky 題材標題改 `--header-offset`;Dialog/Command 限高;個股「雷達」返回 min-h-11
  - Header 搜尋/主題/帳號、登入頁、個股疊圖 chip 補 safe-area / 44px
- **Known Issues**:
  - **`import-geo` 等回補結束**:兩筆回補跑完前不要手動寫 DB。
  - `design-system/stock/MASTER.md` 可能仍寫舊綠/`#22C55E`/Fira——以現站為準,勿回改 Web。
- **Not Yet Done**:
  - **docs/27 G3** 庫藏股
  - **docs/22** Quiet/Extended/Faded
- **Next Suggested Actions**:
  1. iPhone 實機:分點研究 → 點一檔追蹤 → 「返回」應在瀏海下方可點。
  2. 回補結束 → `import-geo` + `export-json` + deploy。
- **Files That Should Not Be Modified**:
  - Header 品牌 mark / `trever-radar-mark.svg`
  - `.github/workflows/*.yml`
  - 正式 `radar.db`

---

> **Planner(Grok 4.6 High)**:讀 AGENTS.md、docs/17、STATUS、handoff → 產出 Confirmed Scope。
> **Executor(Auto)**:讀 Scope + Workflow D → 實作 → 更新 md → commit → push。Scope 未定或高風險時才「先 plan、等確認」。
