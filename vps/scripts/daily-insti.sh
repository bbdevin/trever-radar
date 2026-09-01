#!/usr/bin/env bash
# 16:10 台北(週一–五)— 法人買賣超 + 權證主檔;上櫃日K 保底再抓(主輪在 15:00)。
# 權證主檔偶發 timeout 不得擋正常發布；TPEx 520 部分行情則本輪不發布。
source "$(dirname "$0")/lib.sh"

acquire_db_lock
sync_code

# 15:00 主抓上櫃日K;此處再抓一次當保底(empty 無害)。只有「TWSE 成功、
# TPEx 唯一 HTTP 520」會回 75，保留已入庫行情並讓法人／主檔照常跑。
quotes_rc=0
if radar import-daily --datasets quotes; then
  :
else
  quotes_rc=$?
fi
if [ "$quotes_rc" -ne 0 ] && [ "$quotes_rc" -ne 75 ]; then
  notify "日K匯入失敗（exit ${quotes_rc}），請查看 ~/radar-cron.log" high "失敗"
  exit "$quotes_rc"
fi
if [ "$quotes_rc" -eq 75 ]; then
  notify_warn "TWSE 行情已入庫；TPEx HTTP 520，先續跑三大法人與權證主檔"
fi
radar import-daily --datasets insti
# 權證主檔偶發 timeout 不得擋法人/日K 上線。無論成功與否都在
# 其後彙總：成功時採新主檔；失敗時沿用既有主檔。
if ! radar import-warrant-master; then
  notify_warn "權證主檔暫時抓不到，已略過；請在後續輪重試"
fi
if [ "$quotes_rc" -eq 75 ]; then
  notify_warn "部分已入庫，因TPEx行情未完整，本輪不發布（不做aggregate/compute/export/deploy），待17:40"
  exit 75
fi
radar aggregate-warrants --date "$(taipei_date +%Y%m%d)"
radar compute-indicators --all --days 5
radar compute-scores
radar export-json
deploy_data
notify_ok "三大法人資料已更新並上線"
