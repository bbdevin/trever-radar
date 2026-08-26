- **Done（2026-08-26）**:
  - `radar backfill-tdcc`：從 wirelessr archive 回補大戶週（預設 2026-04-01～今；實際約 04-30 起）
  - `vps/scripts/backfill-tdcc.sh`（`SKIP_QUIET=1` 可手動）
  - 大戶表 UI 紅漲綠跌；export `retail_pct`
- **Next**:
  1. **VPS 手動**：`SKIP_QUIET=1 bash ~/trever-radar/vps/scripts/backfill-tdcc.sh`（先 git pull）
  2. 驗個股大戶表多週＋散戶欄
  3. 權證回補／盤後 daily
- **Branch**: `main`
