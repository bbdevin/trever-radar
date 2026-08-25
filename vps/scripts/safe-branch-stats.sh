#!/usr/bin/env bash
# 低負載分點統計 + 上線(docs/33 S1.1,2026-08-25)。
# 與 mid-backfill-publish 分離:mid 只負責加深 JSON;本腳本專跑 compute-branch-stats。
# 避開 daily-* 窗;pause bf;記憶體不足則跳過;stats 失敗不擋後續(無後續時僅告警)。
#
# 環境變數:MIN_FREE_GB=4;MIN_MEM_MB=900;SKIP_EXPORT=1 只算 stats 不上線。
source "$(dirname "$0")/lib.sh"

FLAG="${MID_PUBLISH_FLAG:-/tmp/radar-mid-publish.flag}"
STATE_FILE="${SAFE_STATS_STATE:-$HOME/safe-branch-stats.state}"
MIN_FREE_GB="${MIN_FREE_GB:-4}"
MIN_MEM_MB="${MIN_MEM_MB:-900}"
CONTAINERS="radar-bf-branches radar-bf-warrant"

trap - ERR
trap 'rm -f "$FLAG" 2>/dev/null || true' EXIT

in_daily_window() {
  local dow hhmm
  dow=$(TZ=Asia/Taipei date +%u)
  hhmm=$((10#$(TZ=Asia/Taipei date +%H%M)))
  if [ "$dow" -eq 6 ]; then
    { [ "$hhmm" -ge 55 ] && [ "$hhmm" -le 230 ]; } && return 0
    { [ "$hhmm" -ge 450 ] && [ "$hhmm" -le 630 ]; } && return 0
    return 1
  fi
  if [ "$dow" -eq 7 ]; then
    { [ "$hhmm" -ge 55 ] && [ "$hhmm" -le 230 ]; } && return 0
    return 1
  fi
  { [ "$hhmm" -ge 1405 ] && [ "$hhmm" -le 1500 ]; } && return 0
  { [ "$hhmm" -ge 1605 ] && [ "$hhmm" -le 1650 ]; } && return 0
  { [ "$hhmm" -ge 1735 ] && [ "$hhmm" -le 1930 ]; } && return 0
  { [ "$hhmm" -ge 2055 ] && [ "$hhmm" -le 2200 ]; } && return 0
  { [ "$hhmm" -ge 2205 ] && [ "$hhmm" -le 2250 ]; } && return 0
  { [ "$hhmm" -ge 55 ] && [ "$hhmm" -le 230 ]; } && return 0
  return 1
}

free_gb() {
  df -PB1 "$REPO" | awk 'NR==2 {printf "%.1f", $4/1024/1024/1024}'
}

mem_available_mb() {
  awk '/MemAvailable:/ {printf "%d", $2/1024}' /proc/meminfo
}

echo "=== safe-branch-stats start $(taipei_date -Is) ==="

if in_daily_window; then
  echo "inside daily cron window — skip"
  notify "safe-stats skipped: daily cron window" default
  exit 0
fi

if fuser /tmp/radar-db.lock >/dev/null 2>&1; then
  echo "radar-db.lock held — skip"
  notify "safe-stats skipped: radar-db.lock held" default
  exit 0
fi

if [ -f "$FLAG" ]; then
  echo "mid-publish flag present — skip"
  notify "safe-stats skipped: mid-publish in progress" default
  exit 0
fi

FREE="$(free_gb)"
awk -v f="$FREE" -v m="$MIN_FREE_GB" 'BEGIN { exit !(f+0 >= m+0) }' || {
  echo "disk free ${FREE}G < ${MIN_FREE_GB}G — skip"
  notify "safe-stats skipped: disk free ${FREE}G" default
  exit 0
}

MEM="$(mem_available_mb)"
if [ "${MEM:-0}" -lt "$MIN_MEM_MB" ]; then
  echo "MemAvailable ${MEM}MB < ${MIN_MEM_MB}MB — skip"
  notify "safe-stats skipped: mem ${MEM}MB < ${MIN_MEM_MB}MB" default
  exit 0
fi

trap 'notify "FAILED at line $LINENO (tail ~/radar-cron.log)"' ERR
trap 'rm -f "$FLAG" 2>/dev/null || true' EXIT

touch "$FLAG"
echo "pause backfill (if any); mem=${MEM}MB free_disk=${FREE}G"
for c in $CONTAINERS; do docker pause "$c" 2>/dev/null || true; done
sleep 3
# pause 後再量一次(容器凍結後可用記憶體通常上升)
MEM2="$(mem_available_mb)"
echo "mem after pause=${MEM2}MB"

cd "$REPO"
if [ "${SAFE_STATS_SYNC:-0}" = "1" ]; then
  sync_code
fi

echo "compute-branch-stats"
set +e
radar compute-branch-stats
rc=$?
set -e

STATS_NOTE="ok"
if [ "$rc" -ne 0 ]; then
  STATS_NOTE="failed_rc_${rc}"
  echo "compute-branch-stats failed rc=$rc"
  notify "safe-stats FAILED: compute-branch-stats rc=$rc" high
  rm -f "$FLAG"
  for c in $CONTAINERS; do docker unpause "$c" 2>/dev/null || true; done
  exit "$rc"
fi

if [ "${SKIP_EXPORT:-0}" != "1" ]; then
  echo "export-json + deploy"
  radar export-json
  deploy_data
fi

{
  echo "finished=$(taipei_date -Is)"
  echo "stats=$STATS_NOTE"
  echo "mem_before=$MEM"
  echo "mem_after_pause=$MEM2"
  echo "free_gb_before=$FREE"
} > "$STATE_FILE"

rm -f "$FLAG"
echo "unpause backfill"
for c in $CONTAINERS; do docker unpause "$c" 2>/dev/null || true; done

if ! pgrep -f 'vps/scripts/bf-cron-guard.sh' >/dev/null 2>&1; then
  nohup bash "$REPO/vps/scripts/bf-cron-guard.sh" >> "${BF_GUARD_LOG:-$HOME/bf-cron-guard.log}" 2>&1 &
fi

notify "safe-stats ok; rankings refreshed" default
echo "=== safe-branch-stats done $(taipei_date -Is) ==="
