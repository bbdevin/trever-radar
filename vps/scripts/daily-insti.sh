#!/usr/bin/env bash
# 16:10 台北(週一–五)— 法人買賣超 + 權證主檔;上櫃日K 保底再抓(主輪在 15:00)。
# 權證主檔偶發 timeout 不得擋 export。
source "$(dirname "$0")/lib.sh"

acquire_db_lock
sync_code

# 15:00 主抓上櫃日K;此處再抓一次當保底(empty 無害)。
radar import-daily --datasets quotes
radar aggregate-warrants --date "$(taipei_date +%Y%m%d)"
radar compute-indicators --all --days 5
radar import-daily --datasets insti
# 權證主檔偶發 timeout 不得擋法人/日K 上線
if ! radar import-warrant-master; then
  notify_warn "權證主檔暫時抓不到，已略過；三大法人與日K仍會上線"
fi
radar compute-scores
radar export-json
deploy_data
notify_ok "三大法人資料已更新並上線"