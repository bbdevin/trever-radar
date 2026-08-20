## Handoff

- **Current Goal**: 三大法人買賣超 tab 已對齊截圖版面,等實機掃讀。
- **Current Branch**: `main`
- **Workflow(2026-08-19)**:規劃 → Grok 4.6 High；執行 → Auto agent；完成 → 更新 md + commit + push（見 `AGENTS.md`、`docs/17` Workflow D）
- **Current Agent**: Cursor
- **Work Completed（本次）**:
  - 個股一級分頁：`K線 | 籌碼日報 | 三大法人 | 技術 | 權證`
  - `InstiPanel`：外資/投信/自營商/三大法人全寬次切 → 買賣超柱+股價線 → 日表（比照截圖）
  - 買方/賣方全寬對半切；手機 K 線放大
- **Known Issues**:
  - **`import-geo` 等回補結束**:兩筆回補跑完前不要手動寫 DB。
  - `insti_history` 需 VPS 下次 `export-json` 後正式站才有完整日表。
- **Not Yet Done**:
  - **docs/27 G3** 庫藏股
  - **docs/22** Quiet/Extended/Faded
- **Next Suggested Actions**:
  1. 手機：個股 → 三大法人，對照截圖看次切/圖/表。
  2. 回補結束 → `import-geo` + `export-json` + deploy。
- **Files That Should Not Be Modified**:
  - Header 品牌 mark / `trever-radar-mark.svg`
  - `.github/workflows/*.yml`
  - 正式 `radar.db`

---

> **Planner(Grok 4.6 High)**:讀 AGENTS.md、docs/17、STATUS、handoff → 產出 Confirmed Scope。
> **Executor(Auto)**:讀 Scope + Workflow D → 實作 → 更新 md → commit → push。Scope 未定或高風險時才「先 plan、等確認」。
