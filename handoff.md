## Handoff

- **Current Goal**: 盤中監控 — Fugle 免費 5 檔上限 + VPS worker 重建。
- **Current Branch**: `main`
- **Current Agent**: Cursor Auto (Executor)
- **Work Completed**:
  - 導覽「盤中雷達／盤中」→「盤中監控／監控」
  - `MAX_MONITOR` 預設 5（`FUGLE_WS_MAX_SUBSCRIBE` 可覆寫）
  - VPS：`git pull` + `docker build -t radar-worker`（映像就緒；下交易日 08:50 cron 啟動）
- **Next**: 下交易日確認 log「Loaded N monitor stocks」(N≤5) 與訊號來源徽章。
- **Do not**: 正式 DB destructive；勿把 MAX 調回 40（會超免費 WS）。
