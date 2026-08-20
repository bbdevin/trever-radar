## Handoff

- **Current Goal**: WP-B7 完成並已驗收。門禁 = 站內 Google 登入 + `/data` Worker JWT/`RADAR_SERVICE_KEY`。
- **Current Branch**: `main`
- **Workflow(2026-08-19)**:規劃 → Grok 4.6 High；執行 → Auto agent；完成 → 更新 md + commit + push（見 `AGENTS.md`、`docs/17` Workflow D）
- **Current Agent**: Cursor
- **Work Completed（本次）**:
  - 使用者確認無痕開站為站內 Google 登入、管理員登入後資料正常
  - 文件收尾:STATUS / 21 / 31 / vps README / worker README / app_profiles.sql / handoff
- **Known Issues**: HTML 登入頁對外可見;資料仍必須帶核准 JWT 或 service key。本機不得 wrangler deploy。
- **Not Yet Done（專案層級）**:
  - **WP-B6**:全市場歷史回補仍在 VPS tmux 跑完後需 `compute-branch-stats` + `export-json` + deploy。
  - **B 方案 Phase 2 剩餘**:全市場重算(watchline crossed=0,目前不急)。
- **Next Suggested Actions**:
  1. 分點/權證回補跑完後再 `compute-branch-stats` + `export-json` + VPS `wrangler deploy`。
- **Files That Should Not Be Modified**:
  - `pipeline/radar/db.py` 的 WAL checkpoint 機制。
  - `.github/workflows/*.yml`
  - 正式 `radar.db`(VPS 唯一寫者)

---

> **Planner(Grok 4.6 High)**:讀 AGENTS.md、docs/17、STATUS、handoff → 產出 Confirmed Scope。
> **Executor(Auto)**:讀 Scope + Workflow D → 實作 → 更新 md → commit → push。Scope 未定或高風險時才「先 plan、等確認」。
