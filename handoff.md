## Handoff

- **Current Goal**: WP-H3 當日分時已實作。下一包 docs/27 G1–G4 或等 14:10 後驗收分時線。
- **Current Branch**: `main`
- **Workflow(2026-08-19)**:規劃 → Grok 4.6 High；執行 → Auto agent；完成 → 更新 md + commit + push（見 `AGENTS.md`、`docs/17` Workflow D）
- **Current Agent**: Cursor
- **Work Completed（本次）**:
  - WP-H3: Fugle 當日 1 分 K → `spark_day`/`spark_open`;卡片分時圖;缺資料標「30日」
  - `lib.sh` 把盤中 `.env` 的 `FUGLE_API_KEY` 注入 radar-pipeline 容器
- **Known Issues**: 今日若已過 14:10,要等到下一輪 `export-json`(或 VPS 手動跑一次)才看得到分時;push 只部署前端,舊 radar.json 仍是 30 日線直到 VPS 匯出。
- **Not Yet Done**:
  - **docs/27 G1–G4** 口袋名單(建議回補穩定後)
  - **docs/22** Quiet/Extended/Faded
  - **WP-B6** 回補完後 compute-branch-stats + export-json + deploy
- **Next Suggested Actions**:
  1. VPS `git pull` 後等 14:10,或手動 `vps/scripts/daily-market.sh`(會重跑當日管線)後看卡片是否為分時、無資料檔是否標「30日」。
- **Files That Should Not Be Modified**:
  - `pipeline/radar/db.py` 的 WAL checkpoint 機制。
  - `.github/workflows/*.yml`
  - 正式 `radar.db`(VPS 唯一寫者)

---

> **Planner(Grok 4.6 High)**:讀 AGENTS.md、docs/17、STATUS、handoff → 產出 Confirmed Scope。
> **Executor(Auto)**:讀 Scope + Workflow D → 實作 → 更新 md → commit → push。Scope 未定或高風險時才「先 plan、等確認」。
