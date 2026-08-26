## Handoff

- **Done（2026-08-26）**:
  - docs/35 S2 已掛 VPS：guard／supervisor／weekly-tdcc crontab
  - `BF_ORDER=warrant,branches`（先權證後分點）；`~/bf-supervisor.env`
  - `disk-cleanup.sh` 每日 07:40（docker dangling／log／npm；不動 `radar.db`）；首跑已 +2G（7→9G free）
  - `backfill-branches top=0` 修正（`7b2c003`）
- **Done（TDCC 手動首跑 2026-08-26 13:50–13:59）**: `as_of=2026-08-21`、3369 檔／50535 列；export＋deploy 2461 assets 成功；權證回補已 unpause（14:05–15:00 安靜窗內 guard 會再 pause）
- **Next**:
  1. 等 `radar-bf-warrant` 完成（ntfy）→ supervisor 自動接分點
  2. 盤後確認 14:10 daily-market／guard PAUSE→UNPAUSE
  3. 站上開個股「大戶」tab 驗資料
- **Branch**: `main`
- **Watch**: `tail -f ~/bf-supervisor.log` / `docker logs -f radar-bf-warrant`
