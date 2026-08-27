#!/usr/bin/env bash
# 低負載分點統計 + 分數 + 上線(docs/33 S1.1 + S2 / docs/35 Layer 3)。
# 與 mid-backfill-publish 分離:mid 只負責加深 JSON;本腳本專跑 stats→scores→export。
# 避開 daily-* 窗;pause bf;記憶體不足則跳過;stats 失敗則中止(不跑 scores/export)。
#
# 環境變數:MIN_FREE_GB=4;MIN_MEM_MB=900;SKIP_EXPORT=1 只算不上線;SKIP_SCORES=1 略過分數。
source "$(dirname "$0")/lib.sh"

FLAG="${MID_PUBLISH_FLAG:-/tmp/radar-mid-publish.flag}"
STATE_FILE="${SAFE_STATS_STATE:-$HOME/safe-branch-stats.state}"
MIN_FREE_GB="${MIN_FREE_GB:-4}"
MIN_MEM_MB="${MIN_MEM_MB:-900}"
CONTAINERS="${BF_CONTAINERS:-radar-bf-branches radar-bf-warrant}"

trap - ERR
trap 'rm -f "$FLAG" 2>/dev/null || true; unpause_bf_containers' EXIT

free_gb() {
  df -PB1 "$REPO" | awk 'NR==2 {printf "%.1f", $4/1024/1024/1024}'
}

mem_available_mb() {
  awk '/MemAvailable:/ {printf "%d", $2/1024}' /proc/meminfo
}

echo "=== safe-branch-stats start $(taipei_date -Is) ==="

if in_radar_quiet_window; then
  echo "inside quiet window — skip"
  notify_skip "正值日更安靜窗，分點排行略過"
  exit 0
fi

if fuser /tmp/radar-db.lock >/dev/null 2>&1; then
  echo "radar-db.lock held — skip"
  notify_skip "資料庫鎖占用，分點排行略過"
  exit 0
fi

if [ -f "$FLAG" ]; then
  echo "mid-publish flag present — skip"
  notify_skip "回補中途上線進行中，分點排行略過"
  exit 0
fi

FREE="$(free_gb)"
awk -v f="$FREE" -v m="$MIN_FREE_GB" 'BEGIN { exit !(f+0 >= m+0) }' || {
  echo "disk free ${FREE}G < ${MIN_FREE_GB}G — skip"
  notify_skip "磁碟空間不足（剩 ${FREE}G），分點排行略過"
  exit 0
}

MEM="$(mem_available_mb)"
if [ "${MEM:-0}" -lt "$MIN_MEM_MB" ]; then
  echo "MemAvailable ${MEM}MB < ${MIN_MEM_MB}MB — skip"
  notify_skip "記憶體不足（${MEM}MB < ${MIN_MEM_MB}MB），分點排行略過"
  exit 0
fi

install_fail_trap
trap 'rm -f "$FLAG" 2>/dev/null || true; unpause_bf_containers' EXIT

touch "$FLAG"
echo "pause backfill (if any); mem=${MEM}MB free_disk=${FREE}G"
pause_bf_containers
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
SCORES_NOTE="skipped"
if [ "$rc" -ne 0 ]; then
  STATS_NOTE="failed_rc_${rc}"
  echo "compute-branch-stats failed rc=$rc"
  notify "分點統計失敗（碼 ${rc}），本輪中止" high "失敗"
  rm -f "$FLAG"
  unpause_bf_containers
  exit "$rc"
fi

if [ "${SKIP_SCORES:-0}" != "1" ]; then
  echo "compute-scores"
  set +e
  radar compute-scores
  src=$?
  set -e
  if [ "$src" -ne 0 ]; then
    SCORES_NOTE="failed_rc_${src}"
    echo "compute-scores failed rc=$src (continue to export)"
    notify_warn "綜合分數重算失敗（碼 ${src}），仍繼續匯出"
  else
    SCORES_NOTE="ok"
  fi
else
  SCORES_NOTE="skipped_env"
fi

if [ "${SKIP_EXPORT:-0}" != "1" ]; then
  echo "export-json + deploy"
  radar export-json
  deploy_data
fi

{
  echo "finished=$(taipei_date -Is)"
  echo "stats=$STATS_NOTE"
  echo "scores=$SCORES_NOTE"
  echo "mem_before=$MEM"
  echo "mem_after_pause=$MEM2"
  echo "free_gb_before=$FREE"
} > "$STATE_FILE"

rm -f "$FLAG"
echo "unpause backfill"
unpause_bf_containers

if ! pgrep -f 'vps/scripts/bf-cron-guard.sh' >/dev/null 2>&1; then
  nohup bash "$REPO/vps/scripts/bf-cron-guard.sh" >> "${BF_GUARD_LOG:-$HOME/bf-cron-guard.log}" 2>&1 &
fi

if ! pgrep -f 'vps/scripts/bf-supervisor.sh' >/dev/null 2>&1; then
  nohup bash "$REPO/vps/scripts/bf-supervisor.sh" >> "${BF_SUPERVISOR_LOG:-$HOME/bf-supervisor.log}" 2>&1 &
fi

notify_ok "分點排行與分數夜間重算完成（統計=${STATS_NOTE}，分數=${SCORES_NOTE}）"
echo "=== safe-branch-stats done $(taipei_date -Is) ==="
