#!/usr/bin/env bash
# 資券 240 交易日回補 + export(docs/34 A4)。
# 輕量(~480 HTTP);與 branch/warrant bf 並行時 pause bf 數分鐘。
# 一次性:預設若 ~/margin-backfill.done 存在則跳過;FORCE=1 可重跑。
# 建議窗:週日 02:30、或平日 23:15(22:10 margin 後、23:30 stats 前)。
source "$(dirname "$0")/lib.sh"

DONE_FLAG="${MARGIN_BF_DONE:-$HOME/margin-backfill.done}"
DAYS="${MARGIN_BF_DAYS:-240}"
CONTAINERS="radar-bf-branches radar-bf-warrant"
FLAG="/tmp/radar-margin-backfill.flag"

trap - ERR
trap 'rm -f "$FLAG" 2>/dev/null || true' EXIT

in_daily_window() {
  local dow hhmm
  dow=$(TZ=Asia/Taipei date +%u)
  hhmm=$((10#$(TZ=Asia/Taipei date +%H%M)))
  if [ "$dow" -eq 6 ]; then
    { [ "$hhmm" -ge 450 ] && [ "$hhmm" -le 630 ]; } && return 0
    return 1
  fi
  if [ "$dow" -eq 7 ]; then return 1; fi
  { [ "$hhmm" -ge 1405 ] && [ "$hhmm" -le 1500 ]; } && return 0
  { [ "$hhmm" -ge 1605 ] && [ "$hhmm" -le 1650 ]; } && return 0
  { [ "$hhmm" -ge 1735 ] && [ "$hhmm" -le 1930 ]; } && return 0
  { [ "$hhmm" -ge 2055 ] && [ "$hhmm" -le 2200 ]; } && return 0
  { [ "$hhmm" -ge 2205 ] && [ "$hhmm" -le 2250 ]; } && return 0
  { [ "$hhmm" -ge 55 ] && [ "$hhmm" -le 230 ]; } && return 0
  return 1
}

bf_running() {
  local c
  for c in $CONTAINERS; do
    docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null | grep -q true && return 0
  done
  return 1
}

echo "=== backfill-margin start $(taipei_date -Is) ==="

if [ "${FORCE:-0}" != "1" ] && [ -f "$DONE_FLAG" ]; then
  echo "already done ($DONE_FLAG) — skip (FORCE=1 to rerun)"
  exit 0
fi

if in_daily_window; then
  echo "inside daily cron window — skip"
  notify "margin backfill skipped: daily window" default
  exit 0
fi

if fuser /tmp/radar-db.lock >/dev/null 2>&1; then
  echo "radar-db.lock held — skip"
  notify "margin backfill skipped: db lock" default
  exit 0
fi

touch "$FLAG"
PAUSED=0
if bf_running; then
  echo "pause bf containers"
  for c in $CONTAINERS; do docker pause "$c" 2>/dev/null || true; done
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
  for c in $CONTAINERS; do docker unpause "$c" 2>/dev/null || true; done
fi

notify "margin backfill ${DAYS}d + export done" default
echo "=== backfill-margin done $(taipei_date -Is) ==="
