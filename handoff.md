## Handoff

- **Done（2026-08-26）**: docs/35 S2 — bf-supervisor、safe-stats＋scores、TDCC B1/B2＋週六 06:30 腳本；Reviewer 🔴 已修
- **Next（人工 VPS）**:
  1. `git pull` + `chmod +x vps/scripts/*.sh`
  2. 停掉舊的雙寫 bf 容器（若還在）後啟動 `bf-supervisor.sh`（或掛 crontab.example 新列）
  3. 手動首跑：`vps/scripts/weekly-tdcc.sh`（或 `radar import-tdcc`）驗大戶 tab
  4. crontab 貼上 supervisor／weekly-tdcc 列（路徑改家目錄）
- **Branch**: `main`
- **Tests**: `pytest tests/test_tdcc_shareholding.py` 過
- **Review**: [bf/mid](a92f99d3-3ff7-4ab3-ac77-ef3b702a1bc5) / [TDCC](72a7f753-ec05-46d2-b619-c287ec11e086) → APPROVE_WITH_FIXES（已跟進）
