## Handoff

- **Current Goal**: 歷史回補進行中;stats/geo 已先上線
- **Branch**: `main`
- **Done(2026-08-21 午後)**:
  - `import-geo` 完成(companies=1985…)
  - `compute-branch-stats` 完成(`branch_rankings` as_of=2026-08-20)
  - export + wrangler deploy 完成(正式 `data_date=2026-08-21`, pocket≈40)
  - 未長時間握 flock → 16:10 `daily-insti` 有正常搶到鎖
- **VPS 進行中**:
  - `radar-bf-branches` / `radar-bf-warrant`(cron 窗內由 `bf-cron-guard` pause,窗後自動 unpause)
  - 今日後續 cron:17:40/21:00 branches、22:10 margin
- **看進度**: `docker logs -f radar-bf-branches`; guard=`~/bf-cron-guard.log`
- **回補全跑完後**(可選再跑一次): `compute-branch-stats` → export → deploy
