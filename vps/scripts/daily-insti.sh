#!/usr/bin/env bash
# 16:10 台北(週一–五)— 法人買賣超 + 權證主檔。鏡像 .github/workflows/daily-insti.yml。
source "$(dirname "$0")/lib.sh"

acquire_db_lock
sync_code

radar import-daily --datasets insti
radar import-warrant-master
radar compute-scores
radar export-json
deploy_data
