## Handoff

- **Current Goal**: VPS 歷史回補已恢復(分點+權證分點);今日 cron 有 pause guard
- **Branch**: `main`
- **VPS 進行中**:
  - `radar-bf-branches`: `backfill-branches --top 2500 --days 730 --sleep 1.5`(不拿 flock)
  - `radar-bf-warrant`: `backfill-warrant-branches --top 6000 --days 130 --sleep 2.5`
  - `~/bf-cron-guard.sh`: 排程窗或 `/tmp/radar-db.lock` 被佔時 `docker pause` 兩容器
- **看進度**: `docker logs -f radar-bf-branches` / `radar-bf-warrant`; guard log=`~/bf-cron-guard.log`
- **跑完後**: `compute-branch-stats` → `export-json` → wrangler deploy(勿長時間握 flock);再跑 `import-geo` 或等週一 14:10
- **勿做**: 回補期間手動 `import-geo`、用 `manual-catchup.sh` 包整段回補(會握 flock 擋 cron)
