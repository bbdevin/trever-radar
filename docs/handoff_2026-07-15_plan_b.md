# Handoff(2026-07-15,B 案遷移 WP-B0→B1 交接)

> 依 `docs/18` 完整版模板。接手前必讀:`AGENTS.md` → `docs/project-context.md` → `docs/STATUS.md` → **`docs/31_plan_b_vps_data_home.md`(本次任務的 source of truth)**。

- **Current Goal**:執行 `docs/31` B 案遷移(radar.db 常駐 VPS 單一寫者 + R2 資料層)。目前位置:**WP-B0 Executor 件已完成、等使用者做人工步驟;WP-B1 未完成**。
- **Current Branch**:`main`(與 origin 同步,工作樹乾淨)
- **已確認範圍(Confirmed Scope)**:使用者已說「開始」授權 **WP-B0 + WP-B1**;WP-B2 起每包需使用者再次確認才可動工(docs/31 §10 規則 1)。
- **Current Role**:Planner + Executor(Claude Code / Claude Fable 5)
- **Next Role**:Executor(WP-B1 收尾 → 經使用者確認後 WP-B2)
- **Suggested Next Agent / Model**:任一高階模型皆可;WP-B7(登入統一)屬資安敏感件,實作時需資安專責流程。
- **Work Completed**(全部已 commit+push):
  - `a6aa42b` 文件同步至 07-14 實況
  - `c23f326` docs/31 v2 定稿 + WP-B0 Executor 件:`cloudflare-data-worker/`(R2 代理 Worker+wrangler.toml,影子路由 `/data-preview/*` 先行、`/data/*` 註解待 cutover)、`pipeline/Dockerfile`、`vps/.env.example`(.gitignore 加 `!vps/.env.example` 例外);AGENTS/STATUS/docs 26/29/30 指標同步
  - `ed6954c`→`cbdd4c4` 備份定案:**GitHub 零資料**,週快照 = R2 `trever-radar-backup` + Google Drive 兩供應商;release 僅回滾臨時用
- **Files Changed**:見上列三個 commit(`git show --stat` 可查);工作樹目前無未提交變更。
- **Current Git Status**:clean,`main` == `origin/main`(HEAD `cbdd4c4`)。
- **Known Issues**:
  1. 🔴 **repo 目前 public,release `db-backup` 的 `radar.db.gz`(399MB)任何人可下載**——踩 `docs/10` §3 紅線,WP-B1 就是要解這個,越快越好。
  2. 雲端每日資料鏈(5 支 workflow + Cloudflare Worker trigger)**仍在正常運行且不得動**——它要撐到 WP-B3 cutover 才退役。
  3. `docs/30` §3 的 `backfill_warrant_branches` bug(importer.py:415-421)未修,是 WP-B6 絕對前置。
- **Errors/Logs**:無。
- **Tests Run**:未跑(本次全為文件+新增未接線檔案;Worker 尚未部署,無可測物)。
- **Not Yet Done**(依序):
  1. 【使用者人工】Cloudflare 建 `trever-radar-data`/`trever-radar-backup` 兩顆私有 bucket + 發涵蓋兩者的 R2 token。
  2. 【使用者人工】本機 `cd cloudflare-data-worker && npx wrangler deploy`(只掛影子路由,不影響正式站)。
  3. 【使用者人工】VPS:裝 rclone、設 `r2` 與 `gdrive` 兩個 remote、`gzip -kf data/radar.db` 後把 `radar.db.gz` 上傳兩朵雲(指令見 docs/31 WP-B0/B1 與對話紀錄;`rclone ls` 兩邊都列得出檔案才算完成)。
  4. 【Agent,WP-B1 收尾】**確認步驟 3 完成後**執行:`gh release delete-asset db-backup radar.db.gz -y --repo bbdevin/trever-radar`(先 `gh release view db-backup` 再刪;絕不可在快照未就位前刪)。
  5. 【Agent,需使用者說開工】WP-B2:寫 `vps/scripts/`(docs/31 §2 各輪 + 備份腳本)與 `vps/README.md`,影子驗證 2–3 交易日。
- **Next Suggested Actions**:同上 4→5。
- **Files That Should Not Be Modified**:`.github/workflows/*.yml`(cutover 前一律不動)、`pipeline/radar/*` 管線邏輯(WP-B6 的權證 bug 修正除外)、Cloudflare Access 設定(WP-B7 前不動)、`cloudflare-trigger/`(仍在服役)。AGENTS.md 危險清單(WAL/cache/release 鏈)在 cutover 前全部仍然有效。
- **Risk Notes**:
  - WP-B1 刪 public asset 後,雲端鏈剩 Actions cache 單腿(已知且使用者接受,docs/31 §7);cache 若被逐出,資料 workflow 會失敗、網站停更(不壞資料)——因此 cutover 目標 ≤1 週,影子期不要拖。
  - 影子期(WP-B2)雲端與 VPS 並行抓資料屬預期,**不得**因此提前停雲端鏈。
  - 備份「GitHub 零資料」原則:任何 agent 不得再把 DB 檔上傳 release(回滾例外,見 docs/31 §8)。
