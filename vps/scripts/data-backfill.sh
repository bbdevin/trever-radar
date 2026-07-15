#!/usr/bin/env bash
# 01:10 台北(每日)— 深歷史增量。鏡像 .github/workflows/data-backfill.yml 的 task=deep。
# 已拉深的股票自動跳過 → 日常只補新上市/缺漏,近零請求。FinMind 600 req/hr → sleep ≥6。
# 注意:與 VPS 手動長回補共用同一 FinMind token 額度,勿同時跑大量任務。
source "$(dirname "$0")/lib.sh"

acquire_db_lock
sync_code

radar deep-backfill --all --sleep 6.5
