## Handoff

- **Current Goal**: WP-H1 已上線。下一包 WP-H3(當日分時);金鑰沿用 VPS `FUGLE_API_KEY`。
- **Current Branch**: `main`
- **Workflow(2026-08-19)**:規劃 → Grok 4.6 High；執行 → Auto agent；完成 → 更新 md + commit + push（見 `AGENTS.md`、`docs/17` Workflow D）
- **Current Agent**: Cursor
- **Work Completed（本次）**:
  - 定案 WP-H3 沿用既有 `FUGLE_API_KEY`,不另開 `RADAR_FUGLE_TOKEN`、不進 GitHub Actions secret
- **Known Issues**: H3 開工時需把 `FUGLE_API_KEY` 注入 `radar-pipeline` 容器(目前日常排程只傳 `RADAR_FINMIND_TOKEN`;盤中 worker 已有 key)。
- **Not Yet Done**:
  - **WP-H3** 卡片當日分時(下一包;A 案)
  - **docs/27 G1–G4** 口袋名單(建議回補穩定後)
  - **docs/22** Quiet/Extended/Faded
  - **WP-B6** 回補完後 compute-branch-stats + export-json + deploy
- **Next Suggested Actions**:
  1. 下一包 WP-H3:讀 `FUGLE_API_KEY`(VPS `pipeline/intraday/.env` 已有),注入管線容器抓當日 1 分 K。
- **Files That Should Not Be Modified**:
  - `pipeline/radar/db.py` 的 WAL checkpoint 機制。
  - `.github/workflows/*.yml`
  - 正式 `radar.db`(VPS 唯一寫者)

---

> **Planner(Grok 4.6 High)**:讀 AGENTS.md、docs/17、STATUS、handoff → 產出 Confirmed Scope。
> **Executor(Auto)**:讀 Scope + Workflow D → 實作 → 更新 md → commit → push。Scope 未定或高風險時才「先 plan、等確認」。
