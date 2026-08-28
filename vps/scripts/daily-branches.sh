#!/usr/bin/env bash
# 17:40 + 22:00 台北(週一–五,同一支跑兩次,冪等)— 法人補抓 + 分點全量。
# 融資融券不在此輪:交由 21:20 daily-margin(TWSE ~21:00 產製)。
# 第二輪改 22:00,讓 21:20 資券先上線、避免搶 lock。
source "$(dirname "$0")/lib.sh"

acquire_db_lock
acquire_branch_source_lock
sync_code

# 上櫃日K 若 14:10/16:10 仍 empty,此輪再抓,否則 --top 0 會漏掉無當日報價的上櫃。
radar import-daily --datasets quotes,insti
radar compute-indicators --all --days 5
radar seed-branches
# top=0: 當日有報價的全部 type=stock(不含 ETF)。
# 全市場權證輪尚未通過容量/時間 PoC，先保留既有上市 Top 200，避免資料斷層；
# 待獨立輪正式啟用時，才在同一次排程變更中切為 --warrants 0。
radar import-branch-trades --top 0 --warrants 200 --sleep 1.0
radar compute-branch-stats
radar compute-scores
radar compute-performance
radar export-json
radar prune
deploy_data
notify_ok "分點籌碼已更新並上線（含法人補抓）"
