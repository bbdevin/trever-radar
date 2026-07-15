# Handoff(2026-07-15,B 案遷移 WP-B0→B1 交接)

> 依 `docs/18` 完整版模板。接手前必讀:`AGENTS.md` → `docs/project-context.md` → `docs/STATUS.md` → **`docs/31_plan_b_vps_data_home.md`(本次任務的 source of truth)**。

- **Current Goal**:執行 `docs/31` B 案遷移(radar.db 常駐 VPS 單一寫者 + **Workers 靜態資產資料層,v3**)。目前位置:**WP-B0 ✅、WP-B1 ✅(07-15 晚收尾:首份 Drive 快照就位後已刪 public release asset)、WP-B2 影子驗證進行中(起跑 07-15,需 2–3 交易日)、WP-B3/WP-B6 彈藥已備妥待開工(見下)**。
- **v3 改版(2026-07-15)**:R2 需綁卡 → 使用者定案不採用。資料層改 Workers 靜態資產(VPS `wrangler deploy`)、備份改 Google Drive 單雲。`cloudflare-data-worker/` 已改寫為 assets 模式,`vps/.env.example` 憑證改 `CLOUDFLARE_API_TOKEN`。全方案無綁卡步驟。
- **Current Branch**:`main`(與 origin 同步,工作樹乾淨)
- **已確認範圍(Confirmed Scope)**:使用者已說「開始」授權 **WP-B0 + WP-B1**;WP-B2 起每包需使用者再次確認才可動工(docs/31 §10 規則 1)。
- **Current Role**:Planner + Executor(Claude Code / Claude Fable 5)
- **Next Role**:Executor(WP-B2 影子驗證觀察 → 經使用者確認後 WP-B3 cutover,照 `docs/32` runbook 執行 → WP-B6 合入 bugfix 分支開跑)
- **Suggested Next Agent / Model**:任一高階模型皆可;WP-B7(登入統一)屬資安敏感件,實作時需資安專責流程。
- **Work Completed**(全部已 commit+push):
  - `a6aa42b` 文件同步至 07-14 實況
  - `c23f326` docs/31 v2 定稿 + WP-B0 Executor 件:`cloudflare-data-worker/`(R2 代理 Worker+wrangler.toml,影子路由 `/data-preview/*` 先行、`/data/*` 註解待 cutover)、`pipeline/Dockerfile`、`vps/.env.example`(.gitignore 加 `!vps/.env.example` 例外);AGENTS/STATUS/docs 26/29/30 指標同步
  - `ed6954c`→`cbdd4c4` 備份定案:**GitHub 零資料**,週快照 = R2 `trever-radar-backup` + Google Drive 兩供應商;release 僅回滾臨時用
  - `d2814e3`(main)WP-B1 收尾文件同步(STATUS/docs31/本檔)
  - `a87df0d`(分支 **`wp-b6-warrant-branches-bugfix`,未合 main**)修 `backfill_warrant_branches` 日期範圍 bug + 新增回歸測試 `pipeline/tests/test_backfill_warrant_branches.py`
  - 未提交(main 工作樹)`docs/32_wp_b3_cutover_runbook.md` 新增、AGENTS.md/docs31/本檔文件同步 —— 待本輪結束一併 commit+push
- **Files Changed**:見上列 commit(`git show --stat` 可查)。
- **Current Git Status**:`main` 分支,有未提交的文件變更(見上);另有已推送的獨立分支 `wp-b6-warrant-branches-bugfix`(1 commit,未合併)。
- **Known Issues**:
  1. ~~🔴 release `radar.db.gz` 公開可下載~~ ✅ **07-15 晚已解**(asset 已刪,tag 保留);代價=雲端鏈 cache 單腿至 cutover(已知接受,docs/31 §7)。
  2. 雲端每日資料鏈(5 支 workflow + Cloudflare Worker trigger)**仍在正常運行且不得動**——它要撐到 WP-B3 cutover 才退役。
  3. ~~`docs/30` §3 的 `backfill_warrant_branches` bug 未修~~ ✅ **07-15 晚已修**,分支 `wp-b6-warrant-branches-bugfix`(未合 main,依規則等 cutover 後才合入)。
- **Errors/Logs**:無。
- **Tests Run**:`cd pipeline && .venv/Scripts/python -m pytest` —— 新增 1 項回歸測試 PASS(對照組:還原成舊查詢邏輯會紅,證實測試有效);既有 104 項 pytest + 46 subtests 不受影響(3 項既有失敗與本次改動無關,為 `test_json_export.py` 既有的 import path 問題,主線本來就是紅的)。
- **進度快照(2026-07-15 晚,本機關機前最後更新)**:
  - ✅ WP-B0 全部完成:token/node/rclone gdrive/.env/首次 deploy+兩測(紀錄=`vps/README.md`,docs/31 §12)。
  - ✅ WP-B2 Executor 件 + 使用者側安裝完成:`vps/scripts/` 七支 + `manual-catchup.sh`;**crontab 已掛**(七條,`crontab.example`);ntfy 已訂閱並實測通(主題在 `vps/.env`)。
  - ✅ **`manual-catchup.sh` 跑完(07-15 晚)**:當日資料+近 6 日缺口(權證分點正確 Top 200)+ 全重算 + deploy 影子(990 檔資產,38.7s)→ weekly-backup 首份 Drive 快照 `radar-20260715.db.gz`(integrity ok);期間 daily-branches 輪被 flock 正確跳過並 ntfy(保護機制實戰驗證)。
  - ✅ **WP-B1 收尾完成(07-15 晚)**:查證 asset(07-14 21:21 上傳,本就是 VPS 回灌的舊快照,VPS 主本嚴格超集)後,經使用者確認刪除 public release `radar.db.gz` asset(tag 保留),`gh release view` 驗證無資料 asset。
- **Not Yet Done**(依序):
  1. 【使用者+Agent】影子驗證 2–3 交易日(WP-B2 驗收,清單=`vps/README.md` §9):每日收盤後比對 `/data-preview/radar.json` vs 正式站 `/data/radar.json` freshness/榜單檔數一致、ntfy 無錯誤。第一發實彈=07-15 22:10 daily-margin **已成功**(margin freshness 當日、stale:false)。
  2. 【Agent+使用者確認】WP-B3 cutover(docs/31 §6,選交易日盤前;目標 ≤1 週,約 07-22 前)。**執行手冊已備妥**:`docs/32_wp_b3_cutover_runbook.md`(逐指令/diff,含當晚驗收清單);使用者喊開工後照抄執行即可,不用臨場現想。
  3. 【Agent,依賴 B3】WP-B6 全市場歷史回補。**絕對前置已完成**:`backfill_warrant_branches` bug 修正 + 回歸測試在分支 `wp-b6-warrant-branches-bugfix`(未合 main,cutover 後合入即可直接開跑,見 `docs/31` WP-B6 節)。
- **其他懸掛事項**:
  - 使用者問過「權證分點 Top 200 → 500」:結論=數據說話,查詢指令已給(rank 200/500 成交額涵蓋率);若使用者拍板改 500,實作=`importer.py` 開 `--warrants` 參數(遷移期管線凍結,排 cutover 後與 WP-B6 一起)。
  - 今日(07-15)融資券公布晚:manual-catchup 跑時可能 NoDataError 空跑,由 22:10 cron 輪自動補,屬預期。
- **Next Suggested Actions**:同上 5→6。
- **Files That Should Not Be Modified**:`.github/workflows/*.yml`(cutover 前一律不動)、`pipeline/radar/*` 管線邏輯(WP-B6 的權證 bug 修正除外)、Cloudflare Access 設定(WP-B7 前不動)、`cloudflare-trigger/`(仍在服役)。AGENTS.md 危險清單(WAL/cache/release 鏈)在 cutover 前全部仍然有效。
- **Risk Notes**:
  - WP-B1 刪 public asset 後,雲端鏈剩 Actions cache 單腿(已知且使用者接受,docs/31 §7);cache 若被逐出,資料 workflow 會失敗、網站停更(不壞資料)——因此 cutover 目標 ≤1 週,影子期不要拖。
  - 影子期(WP-B2)雲端與 VPS 並行抓資料屬預期,**不得**因此提前停雲端鏈。
  - 備份「GitHub 零資料」原則:任何 agent 不得再把 DB 檔上傳 release(回滾例外,見 docs/31 §8)。
