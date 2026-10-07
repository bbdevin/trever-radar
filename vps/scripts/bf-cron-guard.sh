#!/usr/bin/env bash
# 回補容器 cron 保護(docs/33 / docs/35):安靜窗或 /tmp/radar-db.lock 被佔 → pause;
# mid-backfill-publish 進行中(flag)→ 維持 pause,勿搶 unpause。
# 單實例:flock /tmp/radar-bf-guard.lock;建議 crontab @reboot + 每 5 分保活。
source "$(dirname "$0")/lib.sh"
trap - ERR

CONTAINERS="${BF_CONTAINERS:-radar-bf-branches radar-bf-warrant}"
FLAG="${MID_PUBLISH_FLAG:-/tmp/radar-mid-publish.flag}"
MARGIN_FLAG="/tmp/radar-margin-backfill.flag"
TDCC_FLAG="/tmp/radar-tdcc.flag"
LOG="${BF_GUARD_LOG:-$HOME/bf-cron-guard.log}"

exec 8>/tmp/radar-bf-guard.lock
if ! flock -n 8; then
  exit 0
fi

log() { echo "$(TZ=Asia/Taipei date '+%F %T') $*" >> "$LOG"; }

lock_held() { fuser /tmp/radar-db.lock >/dev/null 2>&1; }
# 分點來源鎖(docs/47 §8):daily-branches.sh 整輪握著它(含不握 DB 鎖的探測與抓取段)。
# bf 容器打的是同五個鏡像站,所以它握著的時候 bf 也要停,否則單站負載加倍。
# 以前這段時間 bf 是被 lock_held「順便」停住的(分點輪的 fd 9 整輪開著);現在明講。
source_held() { fuser /tmp/radar-branch-source.lock >/dev/null 2>&1; }
mid_publish() { [ -f "$FLAG" ]; }
margin_job() { [ -f "$MARGIN_FLAG" ]; }
tdcc_job() { [ -f "$TDCC_FLAG" ]; }
should_pause() { mid_publish || margin_job || tdcc_job || lock_held || source_held || in_radar_quiet_window; }

any_bf_alive() {
  local c
  for c in $CONTAINERS; do
    if docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null | grep -q true; then
      return 0
    fi
    # paused 也算 alive(勿誤以為結束)
    if docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null | grep -q paused; then
      return 0
    fi
  done
  return 1
}

STATE=unknown
log "guard start (repo=$REPO)"
while true; do
  if ! any_bf_alive; then
    sleep 60
    continue
  fi
  if should_pause; then
    if [ "$STATE" != paused ]; then
      pause_bf_containers
      STATE=paused
      reason=window
      lock_held && reason=lock
      source_held && reason=branch-source
      mid_publish && reason=mid-publish
      margin_job && reason=margin
      tdcc_job && reason=tdcc
      log "PAUSE ($reason)"
    fi
  else
    if [ "$STATE" != running ]; then
      unpause_bf_containers
      STATE=running
      log "UNPAUSE"
    fi
  fi
  sleep 20
done
