## Handoff

- **Current Goal**: 盤中雷達 UX 已上碼；VPS worker 需重建才吃到「自選∪Armed」。
- **Current Branch**: `main`
- **Workflow(2026-08-19)**:規劃 → Grok 4.6 High；執行 → Auto agent；完成 → 更新 md + commit + push
- **Current Agent**: Cursor Auto (Executor)
- **Work Completed（本次）**:
  - `/intraday` 頁 + 桌機／底部導覽「盤中雷達／盤中」（分點與自選之間）
  - I-1～I-4 人話：大單／爆量／急拉／發動 + 規則說明；列可點進個股
  - Supabase realtime 維持；`aria-live` 新訊號
  - worker：Armed ∪ 自選、上限 40、每 5 分重整增量訂閱；desc 附「來源:未發動/自選/雙池」
- **Known Issues**:
  - 正式 worker 映像尚未重建 → 線上仍只盯 Armed，直到下次 rebuild+restart
  - 分點歷史回補仍暫停
- **Next Suggested Actions**:
  1. 下個交易日前：VPS `git pull` + rebuild `radar-worker` + 確認 08:50 cron
  2. 看 14:10 daily-market 是否把資料日推到 08-21
- **Files That Should Not Be Modified**:
  - 正式 `radar.db` destructive 操作
  - Header 品牌 mark
