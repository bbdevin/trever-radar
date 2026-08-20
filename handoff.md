## Handoff

- **Current Goal**: docs/27 G4 口袋 UI 已實作。剩餘 G3 庫藏股可繼續延後。
- **Current Branch**: `main`
- **Workflow(2026-08-19)**:規劃 → Grok 4.6 High；執行 → Auto agent；完成 → 更新 md + commit + push（見 `AGENTS.md`、`docs/17` Workflow D）
- **Current Agent**: Cursor
- **Work Completed（本次）**:
  - 記錄:兩筆回補(分點 / 權證分點)跑完前**不要**手動 `import-geo`(見 `docs/27`、`vps/README.md`)
  - G4:首頁「口袋」tab、`PocketBadges`、個股頁 F3 人話理由、`/branch` 關鍵徽章
- **Known Issues**:
  - **`import-geo` 等回補結束**(2026-08-20 使用者確認):不覆蓋回補表,但會搶 `radar.db` 寫鎖。回補完後再跑 `import-geo` + `export-json` + `wrangler deploy`;或不手動,等下週一 14:10。
  - 口袋榜在 GEO 入庫前可能偏空(KEY/THEME 下一次 export 即可)。
  - `/branch` 未做「地緣分點對某股」徽章(缺個股對照)。
- **Not Yet Done**:
  - **docs/27 G3** 庫藏股(無 OpenAPI)
  - **docs/22** Quiet/Extended/Faded
  - **WP-B6** 回補完後 compute-branch-stats + export-json + deploy
- **Next Suggested Actions**:
  1. 兩筆回補結束 → VPS `import-geo` + `export-json` + deploy(指令見上次對話)。
  2. 驗收首頁「口袋」tab(可能先空;KEY/THEME 有 export 就會有檔)。
- **Files That Should Not Be Modified**:
  - `pipeline/radar/db.py` 的 WAL checkpoint 機制。
  - `.github/workflows/*.yml`
  - 正式 `radar.db`(VPS 唯一寫者)

---

> **Planner(Grok 4.6 High)**:讀 AGENTS.md、docs/17、STATUS、handoff → 產出 Confirmed Scope。
> **Executor(Auto)**:讀 Scope + Workflow D → 實作 → 更新 md → commit → push。Scope 未定或高風險時才「先 plan、等確認」。
