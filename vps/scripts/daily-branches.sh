#!/usr/bin/env bash
# 17:40 + 21:00 台北(週一–五,同一支跑兩次,冪等)— 融資券/法人補抓 + 分點全量。
# 鏡像 .github/workflows/daily-branches.yml(當日最重的一輪,含 MoneyDJ 鏡像爬蟲)。
source "$(dirname "$0")/lib.sh"

acquire_db_lock
sync_code

# 上櫃日K 若 14:10/16:10 仍 empty,此輪再抓,否則 --top 0 會漏掉無當日報價的上櫃。
radar import-daily --datasets quotes,insti,margin
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
