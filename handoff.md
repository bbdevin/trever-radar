## Handoff

- **Current Goal**: 非 VPS 三包已落地;等回補結束再 geo + export。
- **Current Branch**: `main`
- **Workflow(2026-08-19)**:規劃 → Grok 4.6 High；執行 → Auto agent；完成 → 更新 md + commit + push（見 `AGENTS.md`、`docs/17` Workflow D）
- **Current Agent**: Cursor
- **Work Completed（本次）**:
  - 個股掃讀:訊號摘要可收合(K 線預設收)、手機 sticky 一級 tab、修正「綜合評分」、法人空態縮短
  - docs/22 A4:Extended/Faded 同日近似(`derive_radar_state`)+`lists.extended/faded`+首頁「追高風險」「失效」+卡片徽章+單元測試
  - docs/20 Phase 4:提案稿改寫對齊 VPS cron(14:10/22:10 資料 deploy 建議);**未改 cron/script**
- **Known Issues**:
  - **`import-geo` 等回補結束**:兩筆回補跑完前不要手動寫 DB。
  - `lists.extended/faded`、`insti_history`、`strategy_meta` badges 需 VPS 下次 `export-json` 後正式站才完整。
- **Not Yet Done**:
  - **docs/27 G3** 庫藏股
  - Phase 4 cron 實作(待確認目標態或變體 B)
  - armed_days / 跨日 Faded
- **Next Suggested Actions**:
  1. 回補結束 → `import-geo` + `export-json` + deploy。
  2. 確認 Phase 4 要用「14:10+22:10」還是變體 B(再加 16:10)。
- **Files That Should Not Be Modified**:
  - Header 品牌 mark / `trever-radar-mark.svg`
  - `.github/workflows/*.yml`(除非另確認)
  - 正式 `radar.db`(回補中)

---

> **Planner(Grok 4.6 High)**:讀 AGENTS.md、docs/17、STATUS、handoff → 產出 Confirmed Scope。
> **Executor(Auto)**:讀 Scope + Workflow D → 實作 → 更新 md → commit → push。Scope 未定或高風險時才「先 plan、等確認」。
