#!/usr/bin/env bash
# 資券 240 交易日回補 + export(docs/34 A4)。
# 輕量(~480 HTTP);與 branch/warrant bf 並行時 pause bf 數分鐘。
# 一次性:預設若 ~/margin-backfill.done 存在則跳過;FORCE=1 可重跑。
# 建議窗:週日 02:30、或平日 23:15(22:10 margin 後、23:30 stats 前)。
source "$(dirname "$0")/lib.sh"

DONE_FLAG="${MARGIN_BF_DONE:-$HOME/margin-backfill.done}"
DAYS="${MARGIN_BF_DAYS:-240}"
FLAG="/tmp/radar-margin-backfill.flag"

trap - ERR
trap 'rm -f "$FLAG" 2>/dev/null || true' EXIT

echo "=== backfill-margin start $(taipei_date -Is) ==="

if [ "${FORCE:-0}" != "1" ] && [ -f "$DONE_FLAG" ]; then
  echo "already done ($DONE_FLAG) — skip (FORCE=1 to rerun)"
  exit 0
fi

# 週日 02:30 槽本身就在 quiet 窗內定義,允許本腳本跑;僅擋平日 daily 窗
dow=$(TZ=Asia/Taipei date +%u)
if [ "$dow" -ne 7 ] && in_radar_quiet_window; then
  echo "inside quiet window — skip"
  notify "margin backfill skipped: quiet window" default
  exit 0
fi

if fuser /tmp/radar-db.lock >/dev/null 2>&1; then
  echo "radar-db.lock held — skip"
  notify "margin backfill skipped: db lock" default
  exit 0
fi

touch "$FLAG"
PAUSED=0
if bf_container_running; then
  echo "pause bf containers"
  pause_bf_containers
  PAUSED=1
fi

acquire_db_lock
sync_code

echo "backfill-margin --days $DAYS"
radar backfill-margin --days "$DAYS" --sleep 0.4
radar export-json
deploy_data

date -Iseconds > "$DONE_FLAG"
echo "marked done: $DONE_FLAG"

if [ "$PAUSED" -eq 1 ]; then
  echo "unpause bf"
  unpause_bf_containers
fi

rm -f "$FLAG"
notify "margin backfill ok (${DAYS}d)" default
echo "=== backfill-margin done $(taipei_date -Is) ==="
