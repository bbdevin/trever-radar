- **Done（2026-08-26）**:
  - 上櫃晚公布：保留 14:10 上市閃電；新增 `daily-tpex-quotes.sh` @ 15:00（crontab.example；**VPS 掛載待人工**）
- **Next**:
  1. VPS `crontab -e` 加：`0 15 * * 1-5  .../daily-tpex-quotes.sh >> ~/radar-cron.log`
  2. 掛 crontab 董監月槽（16 日 07:00）
- **Branch**: `main`
