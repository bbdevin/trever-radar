#!/usr/bin/env bash
# 回補中途動態上線(docs/33):pause bf → (可選)stats → export → deploy → resume。
# 不長時間握 /tmp/radar-db.lock,避開 daily-* 窗與已在跑的 daily script。
#
# 預設 SKIP_STATS=1(2026-08-25):VPS 僅 ~1.7G RAM,含 stats 易 OOM。
# 強制跑統計:RUN_STATS=1 mid-backfill-publish.sh
# 環境變數:MIN_FREE_GB=4 磁碟門檻;MIN_MEM_MB=900 跑 stats 前可用記憶體門檻。
source "$(dirname "$0")/lib.sh"

FLAG="${MID_PUBLISH_FLAG:-/tmp/radar-mid-publish.flag}"
STATE_FILE="${MID_PUBLISH_STATE:-$HOME/mid-publish.state}"
MIN_FREE_GB="${MIN_FREE_GB:-4}"
MIN_MEM_MB="${MIN_MEM_MB:-900}"
CONTAINERS="${BF_CONTAINERS:-radar-bf-branches radar-bf-warrant}"

# 本腳本的「跳過」不應觸發 ERR→ntfy High
trap - ERR
trap 'rm -f "$FLAG" 2>/dev/null || true; unpause_bf_containers' EXIT

free_gb() {
  df -PB1 "$REPO" | awk 'NR==2 {printf "%.1f", $4/1024/1024/1024}'
}

mem_available_mb() {
  awk '/MemAvailable:/ {printf "%d", $2/1024}' /proc/meminfo
}

echo "=== mid-backfill-publish start $(taipei_date -Is) ==="

if ! bf_container_running; then
  echo "no radar-bf-* containers — noop"
  exit 0
fi

if in_radar_quiet_window; then
  echo "inside quiet window — skip (protect daily-*/weekend)"
  notify_skip "正值日更／週末安靜窗，中途上線略過"
  exit 0
fi

if fuser /tmp/radar-db.lock >/dev/null 2>&1; then
  echo "radar-db.lock held — skip"
  notify_skip "資料庫鎖占用，中途上線略過"
  exit 0
fi

FREE="$(free_gb)"
awk -v f="$FREE" -v m="$MIN_FREE_GB" 'BEGIN { exit !(f+0 >= m+0) }' || {
  echo "disk free ${FREE}G < ${MIN_FREE_GB}G — skip"
  notify_skip "磁碟空間不足（剩 ${FREE}G，需 ≥${MIN_FREE_GB}G），中途上線略過"
  exit 0
}

# 恢復失敗告警(正式步驟);stats 失敗另處理,不整輪炸掉
install_fail_trap
trap 'rm -f "$FLAG" 2>/dev/null || true' EXIT

touch "$FLAG"
echo "pause backfill containers"
pause_bf_containers
# 等既有寫入沉澱
sleep 3

cd "$REPO"
# 不強制 sync_code(避免中途 pull 干擾);需要時可 MID_SYNC=1
if [ "${MID_SYNC:-0}" = "1" ]; then
  sync_code
fi

# 預設略過 stats。RUN_STATS=1 才跑;SKIP_STATS=1 仍可明確略過。
STATS_NOTE="skipped"
WANT_STATS=0
if [ "${RUN_STATS:-0}" = "1" ] && [ "${SKIP_STATS:-0}" != "1" ]; then
  WANT_STATS=1
fi

if [ "$WANT_STATS" = "1" ]; then
  MEM="$(mem_available_mb)"
  if [ "${MEM:-0}" -lt "$MIN_MEM_MB" ]; then
    echo "MemAvailable ${MEM}MB < ${MIN_MEM_MB}MB — skip stats, continue export"
    STATS_NOTE="skipped_low_mem"
    notify_warn "記憶體偏低（${MEM}MB），略過分點統計，仍會匯出上線"
  else
    echo "compute-branch-stats (mem=${MEM}MB)"
    set +e
    radar compute-branch-stats
    rc=$?
    set -e
    if [ "$rc" -eq 0 ]; then
      STATS_NOTE="ok"
    else
      STATS_NOTE="failed_rc_${rc}"
      echo "compute-branch-stats failed rc=$rc — continue export"
      notify_warn "分點統計失敗（碼 ${rc}），仍繼續匯出上線"
    fi
  fi
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
unpause_bf_containers

# 確保 guard 活著
if ! pgrep -f 'vps/scripts/bf-cron-guard.sh' >/dev/null 2>&1; then
  nohup bash "$REPO/vps/scripts/bf-cron-guard.sh" >> "${BF_GUARD_LOG:-$HOME/bf-cron-guard.log}" 2>&1 &
fi

# 確保 supervisor 活著(docs/35)
if ! pgrep -f 'vps/scripts/bf-supervisor.sh' >/dev/null 2>&1; then
  nohup bash "$REPO/vps/scripts/bf-supervisor.sh" >> "${BF_SUPERVISOR_LOG:-$HOME/bf-supervisor.log}" 2>&1 &
fi

notify_ok "回補中途上線完成（網站已刷新；統計=${STATS_NOTE}）"
echo "=== mid-backfill-publish done $(taipei_date -Is) ==="
