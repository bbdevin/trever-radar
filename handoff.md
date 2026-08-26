- **Done（2026-08-26）**:
  - `docs/sql` 統一時間戳命名（`YYYYMMDDHHMMSS_…`）；見 `docs/sql/README.md`
  - docs/35 S2 已掛 VPS：guard／supervisor／weekly-tdcc crontab
  - `BF_ORDER=warrant,branches`；`disk-cleanup.sh` 每日 07:40
  - TDCC 手動首跑成功（as_of=2026-08-21）
  - `backfill-branches top=0` 修正
- **Next**:
  1. 等 `radar-bf-warrant` 完成 → 自動接分點
  2. 盤後確認 daily-market／guard
  3. 站上驗個股「大戶」tab
- **Branch**: `main`
