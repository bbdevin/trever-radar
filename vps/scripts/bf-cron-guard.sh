#!/usr/bin/env bash
# 回補容器 cron 保護(docs/33):daily-* 窗或 /tmp/radar-db.lock 被佔 → pause;
# mid-backfill-publish 進行中(flag)→ 維持 pause,勿搶 unpause。
# 單實例:flock /tmp/radar-bf-guard.lock;建議 crontab @reboot + 每 5 分保活。
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONTAINERS="radar-bf-branches radar-bf-warrant"
FLAG="${MID_PUBLISH_FLAG:-/tmp/radar-mid-publish.flag}"
LOG="${BF_GUARD_LOG:-$HOME/bf-cron-guard.log}"

exec 8>/tmp/radar-bf-guard.lock
if ! flock -n 8; then
  exit 0
fi

log() { echo "$(TZ=Asia/Taipei date '+%F %T') $*" >> "$LOG"; }

in_daily_window() {
  local dow hhmm
  dow=$(TZ=Asia/Taipei date +%u)
  hhmm=$((10#$(TZ=Asia/Taipei date +%H%M)))
  # 週末:01:10 deep;週六另加 05:00 weekly-backup
  if [ "$dow" -eq 6 ]; then
    { [ "$hhmm" -ge 55 ] && [ "$hhmm" -le 230 ]; } && return 0
    { [ "$hhmm" -ge 450 ] && [ "$hhmm" -le 630 ]; } && return 0
    return 1
  fi
  if [ "$dow" -eq 7 ]; then
    { [ "$hhmm" -ge 55 ] && [ "$hhmm" -le 230 ]; } && return 0
    return 1
  fi
  # 平日對齊 daily-* + 緩衝(與 docs/33、既有 ~/bf-cron-guard 一致)
  # 14:10 market / 16:10 insti / 17:40+21:00 branches / 22:10 margin / 01:10 deep
  { [ "$hhmm" -ge 1405 ] && [ "$hhmm" -le 1500 ]; } && return 0
  { [ "$hhmm" -ge 1605 ] && [ "$hhmm" -le 1650 ]; } && return 0
  { [ "$hhmm" -ge 1735 ] && [ "$hhmm" -le 1930 ]; } && return 0
  { [ "$hhmm" -ge 2055 ] && [ "$hhmm" -le 2200 ]; } && return 0
  { [ "$hhmm" -ge 2205 ] && [ "$hhmm" -le 2250 ]; } && return 0
  { [ "$hhmm" -ge 55 ] && [ "$hhmm" -le 230 ]; } && return 0
  return 1
}

lock_held() { fuser /tmp/radar-db.lock >/dev/null 2>&1; }
mid_publish() { [ -f "$FLAG" ]; }
should_pause() { mid_publish || lock_held || in_daily_window; }

any_bf_alive() {
  local c
  for c in $CONTAINERS; do
    if docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null | grep -q true; then
      return 0
    fi
  done
  return 1
}

STATE=unknown
log "guard start (repo=$REPO)"
while true; do
  if ! any_bf_alive; then
    # 回補結束後繼續掛著也無妨;每 60s 探一次
    sleep 60
    continue
  fi
  if should_pause; then
    if [ "$STATE" != paused ]; then
      for c in $CONTAINERS; do docker pause "$c" 2>/dev/null || true; done
      STATE=paused
      reason=window
      lock_held && reason=lock
      mid_publish && reason=mid-publish
      log "PAUSE ($reason)"
    fi
  else
    if [ "$STATE" != running ]; then
      for c in $CONTAINERS; do docker unpause "$c" 2>/dev/null || true; done
      STATE=running
      log "UNPAUSE"
    fi
  fi
  sleep 20
done
