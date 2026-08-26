#!/usr/bin/env bash
# 16:10 台北(週一–五)— 上櫃日K 補抓 + 法人買賣超 + 權證主檔。
# 上櫃 dailyQuotes 14:10 常尚未出表;權證主檔偶發 timeout 不得擋 export。
source "$(dirname "$0")/lib.sh"

acquire_db_lock
sync_code

# 14:10 上櫃 dailyQuotes 常尚未出表(empty);16:10 再抓日K,並重算缺日的指標。
radar import-daily --datasets quotes
radar aggregate-warrants --date "$(taipei_date +%Y%m%d)"
radar compute-indicators --all --days 5
radar import-daily --datasets insti
# 權證主檔偶發 timeout 不得擋法人/日K 上線
if ! radar import-warrant-master; then
  notify "import-warrant-master failed; continuing scores/export" default
fi
radar compute-scores
radar export-json
deploy_data
