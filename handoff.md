## Handoff

- **Current Goal**: 回補中途動態上線 S1 已實作並掛 VPS cron
- **Branch**: `main`
- **Scripts**: `vps/scripts/mid-backfill-publish.sh`, `vps/scripts/bf-cron-guard.sh`
- **Cron**: `0 3,9,12,20 * * *` mid-publish; guard `@reboot` + `*/5` 保活
- **Safety**: 腳本內跳過 daily 窗與 flock;20:00 避開 17:40–19:30
- **Next**: 今晚 20:00 觀察 ntfy「mid-publish ok」;14:10 daily-market 不應被擋
