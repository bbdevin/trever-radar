#!/usr/bin/env bash
# 17:40 + 21:00 台北(週一–五,同一支跑兩次,冪等)— 法人補抓 + 分點全量。
# 融資融券不在此輪:TWSE MI_MARGN 約 21:00 才產製,17:40 幾乎必 empty;交由 22:40 daily-margin。
source "$(dirname "$0")/lib.sh"

acquire_db_lock
sync_code

# 上櫃日K 若 14:10/16:10 仍 empty,此輪再抓,否則 --top 0 會漏掉無當日報價的上櫃。
radar import-daily --datasets quotes,insti
radar compute-indicators --all --days 5
radar seed-branches
# top=0: 當日有報價的全部 type=stock(不含 ETF);另含熱門上市權證分點
radar import-branch-trades --top 0 --sleep 1.0
radar compute-branch-stats
radar compute-scores
radar compute-performance
radar export-json
radar prune
deploy_data
notify_ok "分點籌碼已更新並上線（含法人補抓）"