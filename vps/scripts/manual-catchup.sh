#!/usr/bin/env bash
# 手動追補一條龍(2026-07-15 首次使用,之後有缺口可重跑,全程冪等/可中斷):
#   收掉舊 catch-up 容器 → 抓今日資料 → 補近 N 日缺口(已完整自動跳過)
#   → 全套重算 → export → deploy(影子路由)→ 首份快照上 Google Drive。
# 跑很久(1–2 小時),建議:nohup vps/scripts/manual-catchup.sh >> ~/radar-cron.log 2>&1 &
source "$(dirname "$0")/lib.sh"

DAYS="${DAYS:-6}"   # 近 N 交易日缺口窗;可 DAYS=10 vps/scripts/manual-catchup.sh 覆寫

acquire_db_lock
sync_code

# 舊的 --top 20000 catch-up 容器還在就收掉(march-back 是 resumable,中斷不丟已抓資料)
docker rm -f radar-quick-catchup 2>/dev/null || true

# 今日資料(雲端鏈抓的是它自己那顆 DB;VPS 主本要自己抓一份,upsert 冪等)
radar import-daily --datasets quotes,insti,margin
radar aggregate-warrants --date "$(taipei_date +%Y%m%d)"
radar seed-branches
radar import-branch-trades --top 2500 --sleep 1.0   # 內建同日前 200 大權證分點

# 近 N 日缺口(每個日期先查已有資料,完整日自動跳過,重跑成本近零)
radar backfill-branches --top 2500 --days "$DAYS" --sleep 1.2
radar backfill-warrant-branches --top 200 --days "$DAYS" --sleep 1.2

# 重算(指標窗開 10 天涵蓋修補範圍)+ 上線影子路由
radar compute-indicators --all --days 10
radar compute-scores
radar compute-performance
radar compute-branch-stats
radar export-json
deploy_data

notify "manual-catchup 資料追補完成,開始快照" default

# 釋放本程序的 DB 鎖,讓 weekly-backup.sh 自己拿鎖做快照
exec 9>&-
"$REPO/vps/scripts/weekly-backup.sh"
