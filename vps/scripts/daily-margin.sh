#!/usr/bin/env bash
# 22:10 台北(週一–五)— 融資融券保底輪。鏡像 .github/workflows/daily-margin.yml。
# 與 daily-branches 的抓取重疊是刻意的:import-daily 是 upsert,這支只補漏。
source "$(dirname "$0")/lib.sh"

acquire_db_lock
sync_code

radar import-daily --datasets margin
radar compute-scores
radar compute-performance
radar export-json
deploy_data
