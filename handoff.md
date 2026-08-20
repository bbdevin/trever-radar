## Handoff

- **Current Goal**: docs/27 G2 演算法+export tags 已實作。下一包 G4(口袋名單 UI);G3 庫藏股可繼續延後。
- **Current Branch**: `main`
- **Workflow(2026-08-19)**:規劃 → Grok 4.6 High；執行 → Auto agent；完成 → 更新 md + commit + push（見 `AGENTS.md`、`docs/17` Workflow D）
- **Current Agent**: Cursor
- **Work Completed（本次）**:
  - G2 純函式:`geo_trigger` / `key_buy_trigger` / `hot_theme_trigger` / `pocket_score`
  - export 掛 `pocket_tags`、`pocket_score`、`lists.pocket`(≥2 family,最多 40);`pocket_note` 標涵蓋限制
  - **不進** `daily_scores.final`;不做首頁口袋 tab(G4)
  - 測試:`tests/test_pocket.py` + 既有 export 回歸
- **Known Issues**: GEO tag 要等週一 14:10 `import-geo` 或 VPS 手動 `python -m radar import-geo`。KEY/THEME 下一次 VPS `export-json` 就會出現。地緣目前只涵蓋每日評分池前 15 大。
- **Not Yet Done**:
  - **docs/27 G3–G4** 庫藏股 + 口袋 UI
  - **docs/22** Quiet/Extended/Faded
  - **WP-B6** 回補完後 compute-branch-stats + export-json + deploy
- **Next Suggested Actions**:
  1. 下一包 G4(首頁口袋 tab + badges;可讀已 export 的 `lists.pocket`)。
  2. 今日 14:10 仍可驗收 H3 分時。
- **Files That Should Not Be Modified**:
  - `pipeline/radar/db.py` 的 WAL checkpoint 機制。
  - `.github/workflows/*.yml`
  - 正式 `radar.db`(VPS 唯一寫者)

---

> **Planner(Grok 4.6 High)**:讀 AGENTS.md、docs/17、STATUS、handoff → 產出 Confirmed Scope。
> **Executor(Auto)**:讀 Scope + Workflow D → 實作 → 更新 md → commit → push。Scope 未定或高風險時才「先 plan、等確認」。
