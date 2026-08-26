## Handoff

- **Done（2026-08-26）**:
  - docs/35 S2 已掛 VPS：guard／supervisor／weekly-tdcc crontab
  - `BF_ORDER=warrant,branches`（先權證後分點）；`~/bf-supervisor.env`
  - `disk-cleanup.sh` 每日 07:40（docker dangling／log／npm；不動 `radar.db`）；首跑已 +2G（7→9G free）
  - `backfill-branches top=0` 修正（`7b2c003`）
- **Next**:
  1. 等 `radar-bf-warrant` 完成（ntfy）→ supervisor 自動接分點
  2. 14:10 前後看 guard PAUSE／UNPAUSE
  3.（可選）手動首跑 `weekly-tdcc.sh` 驗大戶 tab
- **Branch**: `main`
- **Watch**: `tail -f ~/bf-supervisor.log` / `docker logs -f radar-bf-warrant`
