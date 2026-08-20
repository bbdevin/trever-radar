## Handoff

- **Current Goal**: WP-H1 首頁題材分組已實作。下一包是 WP-H3(當日分時),需 VPS `RADAR_FUGLE_TOKEN`。
- **Current Branch**: `main`
- **Workflow(2026-08-19)**:規劃 → Grok 4.6 High；執行 → Auto agent；完成 → 更新 md + commit + push（見 `AGENTS.md`、`docs/17` Workflow D）
- **Current Agent**: Cursor
- **Work Completed（本次）**:
  - 綜合/市場掃描榜可切分數或題材分組
  - 一檔多題材只歸當日 vs20 最高題材;無題材進「其他」
  - sticky section header、前 3 組預設展開
- **Known Issues**: 空題材日(`radar.themes` 空)自動 fallback 原排序。Armed/Triggered/策略不套題材分組(依 docs/28)。
- **Not Yet Done**:
  - **WP-H3** 卡片當日分時(下一包;A 案,需 Fugle token)
  - **docs/27 G1–G4** 口袋名單(建議回補穩定後)
  - **docs/22** Quiet/Extended/Faded
  - **WP-B6** 回補完後 compute-branch-stats + export-json + deploy
- **Next Suggested Actions**:
  1. 站上綜合榜切「題材」驗收 sticky / 一檔不重複。
  2. 下一包 WP-H3 前先在 VPS 備好 `RADAR_FUGLE_TOKEN`(cutover 後金鑰在 VPS,不是 Actions secret)。
- **Files That Should Not Be Modified**:
  - `pipeline/radar/db.py` 的 WAL checkpoint 機制。
  - `.github/workflows/*.yml`
  - 正式 `radar.db`(VPS 唯一寫者)

---

> **Planner(Grok 4.6 High)**:讀 AGENTS.md、docs/17、STATUS、handoff → 產出 Confirmed Scope。
> **Executor(Auto)**:讀 Scope + Workflow D → 實作 → 更新 md → commit → push。Scope 未定或高風險時才「先 plan、等確認」。
