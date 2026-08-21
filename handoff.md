## Handoff

- **Current Goal**: 正式資料已補到 2026-08-20;今日 14:10 起應自動恢復。
- **Current Branch**: `main`
- **Workflow(2026-08-19)**:規劃 → Grok 4.6 High；執行 → Auto agent；完成 → 更新 md + commit + push
- **Current Agent**: Cursor
- **Work Completed（本次 VPS 搶修）**:
  - 根因:VPS `git pull` 被本地 dirty `vps/scripts/*` 擋住 → 全日 cron 在 sync_code 失敗,資料凍在 08-19
  - 停兩筆回補容器/tmux;repo pull 到 `adb0185`;`core.filemode false`
  - 手動補 `20260820` quotes/insti/margin + scores + export + deploy → 正式 `data_date=2026-08-20`
  - 盤中 worker:重建映像後已上線(舊影像 401;金鑰本身 OK)
  - `lib.sh` sync_code 加 filemode 防護 + pull 失敗時 reset scripts 重試
- **Known Issues**:
  - 分點/權證分點歷史回補已暫停,要續跑需另開(可 resumable)
  - 今日盤中 worker 靠手動啟動;明日 08:50 cron 應可自動(映像已 rebuild)
- **Next Suggested Actions**:
  1. 下午看 14:10 `daily-market` 是否自動成功(資料日應變 08-21)
  2. 需要時再重開 backfill-branches / warrant
- **Files That Should Not Be Modified**:
  - 正式 `radar.db` destructive 操作
  - Header 品牌 mark

---

> **Planner(Grok 4.6 High)**:讀 AGENTS.md、docs/17、STATUS、handoff → Confirmed Scope。
> **Executor(Auto)**:實作 → 更新 md → commit → push。
