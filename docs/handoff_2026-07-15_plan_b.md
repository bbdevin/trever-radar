# Handoff(2026-07-15,B 案遷移 WP-B0→B1 交接)

> 依 `docs/18` 完整版模板。接手前必讀:`AGENTS.md` → `docs/project-context.md` → `docs/STATUS.md` → **`docs/31_plan_b_vps_data_home.md`(本次任務的 source of truth)**。

- **Current Goal**:執行 `docs/31` B 案遷移(radar.db 常駐 VPS 單一寫者 + **Workers 靜態資產資料層,v3**)。目前位置:**WP-B0 Executor 件已完成(v3 改版後),等使用者做人工步驟;WP-B1 未完成**。
- **v3 改版(2026-07-15)**:R2 需綁卡 → 使用者定案不採用。資料層改 Workers 靜態資產(VPS `wrangler deploy`)、備份改 Google Drive 單雲。`cloudflare-data-worker/` 已改寫為 assets 模式,`vps/.env.example` 憑證改 `CLOUDFLARE_API_TOKEN`。全方案無綁卡步驟。
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
- **進度快照(2026-07-15 晚,本機關機前最後更新)**:
  - ✅ WP-B0 全部完成:token/node/rclone gdrive/.env/首次 deploy+兩測(紀錄=`vps/README.md`,docs/31 §12)。
  - ✅ WP-B2 Executor 件 + 使用者側安裝完成:`vps/scripts/` 七支 + `manual-catchup.sh`;**crontab 已掛**(七條,`crontab.example`);ntfy 已訂閱並實測通(主題在 `vps/.env`)。
  - 🔄 **`manual-catchup.sh` 正在 VPS 背景跑**(nohup,1–2 小時):收掉誤參數 `--top 20000` 權證容器 → 抓今日資料 → 補近 6 日缺口(權證分點以正確 Top 200)→ 全重算 → deploy 影子 → **自動接 weekly-backup.sh 做首份 Drive 快照**。完成=ntfy 兩則(「資料追補完成」「weekly snapshot ok」)。
- **Not Yet Done**(依序):
  1. 【使用者】確認收到「weekly snapshot ok」ntfy(或 `rclone ls gdrive:trever-radar-backup/` 有檔)。
  2. 【Agent,WP-B1 收尾】**確認步驟 1 後**執行:`gh release view db-backup --repo bbdevin/trever-radar` → `gh release delete-asset db-backup radar.db.gz -y --repo bbdevin/trever-radar`(絕不可在快照未就位前刪)→ 更新 STATUS/docs31 §12/本檔,WP-B1 完成。
  3. 【使用者+Agent】影子驗證 2–3 交易日(WP-B2 驗收,清單=`vps/README.md` §9):每日收盤後比對 `/data-preview/radar.json` vs 正式站 `/data/radar.json` freshness/榜單檔數一致、ntfy 無錯誤。第一發實彈=今晚 22:10 daily-margin。
  4. 【Agent+使用者確認】WP-B3 cutover(docs/31 §6,選交易日盤前;目標 WP-B1 後 ≤1 週)。
- **其他懸掛事項**:
  - 使用者問過「權證分點 Top 200 → 500」:結論=數據說話,查詢指令已給(rank 200/500 成交額涵蓋率);若使用者拍板改 500,實作=`importer.py` 開 `--warrants` 參數(遷移期管線凍結,排 cutover 後與 WP-B6 一起)。
  - 今日(07-15)融資券公布晚:manual-catchup 跑時可能 NoDataError 空跑,由 22:10 cron 輪自動補,屬預期。
- **Next Suggested Actions**:同上 5→6。
- **Files That Should Not Be Modified**:`.github/workflows/*.yml`(cutover 前一律不動)、`pipeline/radar/*` 管線邏輯(WP-B6 的權證 bug 修正除外)、Cloudflare Access 設定(WP-B7 前不動)、`cloudflare-trigger/`(仍在服役)。AGENTS.md 危險清單(WAL/cache/release 鏈)在 cutover 前全部仍然有效。
- **Risk Notes**:
  - WP-B1 刪 public asset 後,雲端鏈剩 Actions cache 單腿(已知且使用者接受,docs/31 §7);cache 若被逐出,資料 workflow 會失敗、網站停更(不壞資料)——因此 cutover 目標 ≤1 週,影子期不要拖。
  - 影子期(WP-B2)雲端與 VPS 並行抓資料屬預期,**不得**因此提前停雲端鏈。
  - 備份「GitHub 零資料」原則:任何 agent 不得再把 DB 檔上傳 release(回滾例外,見 docs/31 §8)。
