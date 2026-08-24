#!/usr/bin/env bash
# 回補中途動態上線(docs/33 S1):pause bf → compute-branch-stats → export → deploy → resume。
# 不長時間握 /tmp/radar-db.lock,避開 daily-* 窗與已在跑的 daily script。
# 環境變數:SKIP_STATS=1 略過統計;MIN_FREE_GB=4 磁碟門檻。
source "$(dirname "$0")/lib.sh"

FLAG="${MID_PUBLISH_FLAG:-/tmp/radar-mid-publish.flag}"
STATE_FILE="${MID_PUBLISH_STATE:-$HOME/mid-publish.state}"
MIN_FREE_GB="${MIN_FREE_GB:-4}"
CONTAINERS="radar-bf-branches radar-bf-warrant"

# 本腳本的「跳過」不應觸發 ERR→ntfy High
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

bf_running() {
  local c
  for c in $CONTAINERS; do
    if docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null | grep -q true; then
      return 0
    fi
  done
  return 1
}

free_gb() {
  df -PB1 "$REPO" | awk 'NR==2 {printf "%.1f", $4/1024/1024/1024}'
}

echo "=== mid-backfill-publish start $(taipei_date -Is) ==="

if ! bf_running; then
  echo "no radar-bf-* containers — noop"
  exit 0
fi

if in_daily_window; then
  echo "inside daily cron window — skip (protect daily-*)"
  notify "mid-publish skipped: daily cron window" default
  exit 0
fi

if fuser /tmp/radar-db.lock >/dev/null 2>&1; then
  echo "radar-db.lock held — skip"
  notify "mid-publish skipped: radar-db.lock held" default
  exit 0
fi

FREE="$(free_gb)"
awk -v f="$FREE" -v m="$MIN_FREE_GB" 'BEGIN { exit !(f+0 >= m+0) }' || {
  echo "disk free ${FREE}G < ${MIN_FREE_GB}G — skip"
  notify "mid-publish skipped: disk free ${FREE}G < ${MIN_FREE_GB}G" default
  exit 0
}

# 恢復失敗告警(正式步驟)
trap 'notify "FAILED at line $LINENO (tail ~/radar-cron.log)"' ERR
trap 'rm -f "$FLAG" 2>/dev/null || true' EXIT

touch "$FLAG"
echo "pause backfill containers"
for c in $CONTAINERS; do docker pause "$c" 2>/dev/null || true; done
# 等既有寫入沉澱
sleep 3

cd "$REPO"
# 不強制 sync_code(避免中途 pull 干擾);需要時可 MID_SYNC=1
if [ "${MID_SYNC:-0}" = "1" ]; then
  sync_code
fi

STATS_NOTE="skipped"
if [ "${SKIP_STATS:-0}" != "1" ]; then
  echo "compute-branch-stats"
  radar compute-branch-stats
  STATS_NOTE="ok"
fi

echo "export-json + deploy"
radar export-json
deploy_data

{
  echo "finished=$(taipei_date -Is)"
  echo "stats=$STATS_NOTE"
  echo "free_gb_before=$FREE"
  docker logs --tail 1 radar-bf-branches 2>/dev/null | sed 's/^/branches_log=/' || true
  docker logs --tail 1 radar-bf-warrant 2>/dev/null | sed 's/^/warrant_log=/' || true
} > "$STATE_FILE"

rm -f "$FLAG"
echo "unpause backfill"
for c in $CONTAINERS; do docker unpause "$c" 2>/dev/null || true; done

# 確保 guard 活著
if ! pgrep -f 'vps/scripts/bf-cron-guard.sh' >/dev/null 2>&1; then
  nohup bash "$REPO/vps/scripts/bf-cron-guard.sh" >> "${BF_GUARD_LOG:-$HOME/bf-cron-guard.log}" 2>&1 &
fi

notify "mid-publish ok (stats=$STATS_NOTE) site refreshed; backfill resumed" default
echo "=== mid-backfill-publish done $(taipei_date -Is) ==="
