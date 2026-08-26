- **Done（2026-08-26）**:
  - Phase D1/D2：董監持股分頁＋週表內部人％（`import-directors`、export、HoldersPanel）
  - `monthly-directors.sh`＋crontab.example（每月 16 日 07:00；VPS 掛載待人工）
- **Next**:
  1. VPS：`git pull` → `radar import-directors` → export/deploy（或跑 monthly-directors）
  2. 掛 crontab 16 日槽
- **Branch**: `main`
