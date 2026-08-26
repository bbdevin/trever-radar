#!/usr/bin/env bash
# 15:00 台北(週一–五)— 上櫃日K 補抓。14:10 dailyQuotes 常尚未出表;約 14:57 起才有完整表。
# 上市 14:10 已進庫(upsert 冪等);此輪讓上櫃追上並重算指標/分數後上線。
source "$(dirname "$0")/lib.sh"

acquire_db_lock
sync_code

radar import-daily --datasets quotes
radar aggregate-warrants --date "$(taipei_date +%Y%m%d)"
radar compute-indicators --all --days 5
radar compute-scores
radar export-json
deploy_data
