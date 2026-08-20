## Handoff

- **Current Goal**: docs/27 G1 資料層已實作。下一包 G2(地緣/關鍵/題材演算法,仍不進綜合分)。
- **Current Branch**: `main`
- **Workflow(2026-08-19)**:規劃 → Grok 4.6 High；執行 → Auto agent；完成 → 更新 md + commit + push（見 `AGENTS.md`、`docs/17` Workflow D）
- **Current Agent**: Cursor
- **Work Completed（本次）**:
  - G1:公司住址與券商分點地址入庫、名稱正規化、總公司/外資排除集
  - CLI `import-geo`;週一 `daily-market.sh` 加跑
  - 庫藏股無穩定 OpenAPI,buybacks 不做、不擋 G2
- **Known Issues**: 表要等週一 14:10 或 VPS 手動 `radar import-geo` 才有資料。H3 分時仍等今日 14:10 驗收。
- **Not Yet Done**:
  - **docs/27 G2–G4** 地緣演算法 + 口袋 UI
  - **docs/22** Quiet/Extended/Faded
  - **WP-B6** 回補完後 compute-branch-stats + export-json + deploy
- **Next Suggested Actions**:
  1. 今日 14:10 驗收 H3 分時。
  2. 下一包 G2(使用者說開工再做)。
- **Files That Should Not Be Modified**:
  - `pipeline/radar/db.py` 的 WAL checkpoint 機制。
  - `.github/workflows/*.yml`
  - 正式 `radar.db`(VPS 唯一寫者)

---

> **Planner(Grok 4.6 High)**:讀 AGENTS.md、docs/17、STATUS、handoff → 產出 Confirmed Scope。
> **Executor(Auto)**:讀 Scope + Workflow D → 實作 → 更新 md → commit → push。Scope 未定或高風險時才「先 plan、等確認」。
