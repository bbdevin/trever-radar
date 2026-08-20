## Handoff

- **Current Goal**: IA-5b（法人/技術 tab、手機 K 線放大、買方賣方對半切）已落地,等實機掃讀。
- **Current Branch**: `main`
- **Workflow(2026-08-19)**:規劃 → Grok 4.6 High；執行 → Auto agent；完成 → 更新 md + commit + push（見 `AGENTS.md`、`docs/17` Workflow D）
- **Current Agent**: Cursor
- **Work Completed（本次）**:
  - 個股一級分頁：`K線 | 籌碼日報 | 法人 | 技術 | 權證`
  - K 線 tab 不再堆技術卡；手機圖高 `clamp(440px,68vh,640px)`
  - 既有 `InstiPanel` 掛上法人 tab
  - 買方/賣方改全寬左右對半切（籌碼日報 + 分點追蹤）
- **Known Issues**:
  - **`import-geo` 等回補結束**:兩筆回補跑完前不要手動寫 DB。
  - `insti_history` 需 VPS 已跑過含該欄的 `export-json`；缺資料時法人 tab 仍顯示分數/理由與誠實空狀態。
- **Not Yet Done**:
  - **docs/27 G3** 庫藏股
  - **docs/22** Quiet/Extended/Faded
- **Next Suggested Actions**:
  1. 手機：個股 → K線確認圖變大 → 法人/技術/籌碼日報對半切。
  2. 回補結束 → `import-geo` + `export-json` + deploy。
- **Files That Should Not Be Modified**:
  - Header 品牌 mark / `trever-radar-mark.svg`
  - `.github/workflows/*.yml`
  - 正式 `radar.db`

---

> **Planner(Grok 4.6 High)**:讀 AGENTS.md、docs/17、STATUS、handoff → 產出 Confirmed Scope。
> **Executor(Auto)**:讀 Scope + Workflow D → 實作 → 更新 md → commit → push。Scope 未定或高風險時才「先 plan、等確認」。
