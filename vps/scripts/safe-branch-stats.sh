#!/usr/bin/env bash
# 低負載分點統計 + 分數 + 上線(docs/33 S1.1 + S2 / docs/35 Layer 3)。
# 與 mid-backfill-publish 分離:mid 只負責加深 JSON;本腳本專跑 stats→scores→export。
# 避開 daily-* 窗;pause bf;記憶體不足則跳過;stats 失敗則中止(不跑 scores/export)。
#
# 環境變數:MIN_FREE_GB=4;MIN_MEM_MB=900;SKIP_EXPORT=1 只算不上線;SKIP_SCORES=1 略過分數;
#           SKIP_PIT=1 略過 point-in-time 帳本;
#           SKIP_PAIR_PCTILE=1 略過分點×個股價格分位計數。
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
PIT_NOTE="skipped"
PAIR_PCTILE_NOTE="skipped"
if [ "$rc" -ne 0 ]; then
  STATS_NOTE="failed_rc_${rc}"
  echo "compute-branch-stats failed rc=$rc"
  notify "分點統計失敗（碼 ${rc}），本輪中止" high "失敗"
  rm -f "$FLAG"
  unpause_bf_containers
  exit "$rc"
fi

# branch-point-in-time-persist 落在這裡、而不是自己一條 cron:
#   1. 它需要的守衛這支腳本已經全做過了 —— 安靜窗、/tmp/radar-db.lock、
#      mid-publish flag、磁碟與記憶體門檻,以及 backfill 容器的 pause。
#      獨立排程等於把這五道保護重寫一遍,而且遲早會漂移。
#   2. 這個 DB 是單一寫入者。多一條 cron 就是多一個寫入者,會跟本腳本
#      與回補容器搶鎖;折進這裡則沿用同一把鎖、同一個時間窗。
#   3. 成本 31~50 秒,對一支本來就跑好幾分鐘的工作可忽略。
# 必須在 compute-branch-stats 成功之後(帳本讀的是它剛更新的資料),
# 在 compute-scores 之前(順序固定,便於對照 state 檔)。
# 失敗不中止本輪:這張帳本次要於分數/匯出/上線,不能因為它而擋住當天的價格上線。
if [ "${SKIP_PIT:-0}" != "1" ]; then
  echo "branch-point-in-time-persist"
  set +e
  radar branch-point-in-time-persist
  prc=$?
  set -e
  if [ "$prc" -ne 0 ]; then
    PIT_NOTE="failed_rc_${prc}"
    echo "branch-point-in-time-persist failed rc=$prc (continue to scores)"
    notify_warn "分點 point-in-time 帳本落地失敗（碼 ${prc}），仍繼續分數與匯出"
  else
    PIT_NOTE="ok"
  fi
else
  PIT_NOTE="skipped_env"
fi

# branch-stock-pctile-counts:同一批原料的 pair 粒度快照(分點 × 個股 的低買/
# 高賣計數),個股頁要用。折在這裡的理由與上面那段完全相同(共用五道守衛、
# 單一寫入者、成本可忽略),而且它讀的也是 compute-branch-stats 剛更新的資料。
# 整張表每輪被取代,失敗只是舊快照留著,所以**同樣不中止本輪**:它次要於
# 分數、匯出與上線,不能因為它擋住當天的價格上線。
if [ "${SKIP_PAIR_PCTILE:-0}" != "1" ]; then
  echo "branch-stock-pctile-counts"
  set +e
  radar branch-stock-pctile-counts
  qrc=$?
  set -e
  if [ "$qrc" -ne 0 ]; then
    PAIR_PCTILE_NOTE="failed_rc_${qrc}"
    echo "branch-stock-pctile-counts failed rc=$qrc (continue to scores)"
    notify_warn "分點×個股價格分位計數失敗（碼 ${qrc}），仍繼續分數與匯出"
  else
    PAIR_PCTILE_NOTE="ok"
  fi
else
  PAIR_PCTILE_NOTE="skipped_env"
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
  echo "pit=$PIT_NOTE"
  echo "pair_pctile=$PAIR_PCTILE_NOTE"
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

notify_ok "分點排行與分數夜間重算完成（統計=${STATS_NOTE}，帳本=${PIT_NOTE}，分位計數=${PAIR_PCTILE_NOTE}，分數=${SCORES_NOTE}）"
echo "=== safe-branch-stats done $(taipei_date -Is) ==="
