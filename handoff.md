## Handoff

- **Current Goal**: IA-5 + IA-3b 籌碼分層已落地,等使用者手機實機掃讀。
- **Current Branch**: `main`
- **Workflow(2026-08-19)**:規劃 → Grok 4.6 High；執行 → Auto agent；完成 → 更新 md + commit + push（見 `AGENTS.md`、`docs/17` Workflow D）
- **Current Agent**: Cursor
- **Work Completed（本次）**:
  - 個股頁一級分頁：K線 / 籌碼日報 / 權證；K 線不再堆完整分點表
  - 籌碼日報：全斷點買超|賣超分頁；點分點 → 進出明細 + 對應 K 線覆層（safe-overlay、Esc/返回）
  - 分點追蹤：買超|賣超分頁；點股票進 `/stock?id=#branch`
  - `#branch` 改開籌碼日報（不再捲到 K 線下方）
- **Known Issues**:
  - **`import-geo` 等回補結束**:兩筆回補跑完前不要手動寫 DB。
  - `design-system/stock/MASTER.md` 可能仍寫舊綠/`#22C55E`/Fira——以現站為準,勿回改 Web。
- **Not Yet Done**:
  - **docs/27 G3** 庫藏股
  - **docs/22** Quiet/Extended/Faded
- **Next Suggested Actions**:
  1. 手機：個股 → 籌碼日報 → 買超/賣超 → 點一分點看明細與 K 線 → 返回。
  2. 分點研究 → 追蹤一檔 → 確認只有一側表格、可切賣超。
  3. 回補結束 → `import-geo` + `export-json` + deploy。
- **Files That Should Not Be Modified**:
  - Header 品牌 mark / `trever-radar-mark.svg`
  - `.github/workflows/*.yml`
  - 正式 `radar.db`

---

> **Planner(Grok 4.6 High)**:讀 AGENTS.md、docs/17、STATUS、handoff → 產出 Confirmed Scope。
> **Executor(Auto)**:讀 Scope + Workflow D → 實作 → 更新 md → commit → push。Scope 未定或高風險時才「先 plan、等確認」。
