#!/usr/bin/env bash
# 董監持股月更(docs/34 §4.6 D1):每月 16 日 07:00。
# pause bf → import-directors → export → deploy → unpause。
source "$(dirname "$0")/lib.sh"

FLAG="/tmp/radar-directors.flag"
PAUSED=0

trap - ERR
trap 'rm -f "$FLAG" 2>/dev/null || true; if [ "${PAUSED:-0}" -eq 1 ]; then unpause_bf_containers; fi' EXIT

echo "=== monthly-directors start $(taipei_date -Is) ==="

if [ "${SKIP_QUIET:-0}" != "1" ] && in_radar_quiet_window; then
  echo "inside quiet window — skip (SKIP_QUIET=1 to run anyway)"
  notify "directors skipped: quiet window" default
  exit 0
fi

if fuser /tmp/radar-db.lock >/dev/null 2>&1; then
  echo "radar-db.lock held — skip"
  notify "directors skipped: db lock" default
  exit 0
fi

touch "$FLAG"
if bf_container_running; then
  echo "pause bf containers"
  pause_bf_containers
  PAUSED=1
  sleep 3
fi

trap 'notify "FAILED at line $LINENO (tail ~/radar-cron.log)"' ERR

acquire_db_lock
sync_code

echo "import-directors"
radar import-directors
radar export-json
deploy_data

rm -f "$FLAG"
if [ "$PAUSED" -eq 1 ]; then
  echo "unpause bf"
  unpause_bf_containers
  PAUSED=0
fi

notify "directors monthly ok" default
echo "=== monthly-directors done $(taipei_date -Is) ==="
