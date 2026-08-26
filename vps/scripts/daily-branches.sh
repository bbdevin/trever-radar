#!/usr/bin/env bash
# 17:40 + 21:00 台北(週一–五,同一支跑兩次,冪等)— 融資券/法人補抓 + 分點全量。
# 鏡像 .github/workflows/daily-branches.yml(當日最重的一輪,含 MoneyDJ 鏡像爬蟲)。
source "$(dirname "$0")/lib.sh"

acquire_db_lock
sync_code

radar import-daily --datasets insti,margin
radar seed-branches
# top=0: 當日有報價的全部 type=stock(不含 ETF);另含熱門上市權證分點
radar import-branch-trades --top 0 --sleep 1.0
radar compute-branch-stats
radar compute-scores
radar compute-performance
radar export-json
radar prune
deploy_data
