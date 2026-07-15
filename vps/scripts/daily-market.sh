#!/usr/bin/env bash
# 14:10 台北(週一–五)— 收盤閃電更新。鏡像 .github/workflows/daily-market.yml。
# 日K/權證成交 14:00 後公布;法人/融資券/分點由後續輪分批補,前端 freshness 標示。
source "$(dirname "$0")/lib.sh"

acquire_db_lock
sync_code

radar import-daily --datasets quotes
radar aggregate-warrants --date "$(taipei_date +%Y%m%d)"
radar compute-indicators --all --days 5
radar compute-scores

# 概念股題材每週一更新(鏡像 daily-market.yml 的 Weekly concept-theme refresh)
if [ "$(taipei_date +%u)" = "1" ]; then
  radar import-themes
fi

radar export-json
deploy_data
