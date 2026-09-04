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
# 2026-08-31~09-03 事故(docs/STATUS.md):安靜窗 off-by-one 讓本作業四天沒跑,
# 卻只送出 default 優先權的略過通知,沒人注意到。STALE_HOURS 是「連續幾小時
# 沒有一次成功完成」的門檻,超過就改吹 high 優先權(見 skip_or_alarm)。
STALE_HOURS="${STALE_HOURS:-30}"

trap - ERR
trap 'rm -f "$FLAG" 2>/dev/null || true; unpause_bf_containers' EXIT

free_gb() {
  df -PB1 "$REPO" | awk 'NR==2 {printf "%.1f", $4/1024/1024/1024}'
}

mem_available_mb() {
  awk '/MemAvailable:/ {printf "%d", $2/1024}' /proc/meminfo
}

# 唯一決定「這次略過該用 default 還是 high 優先權」的地方,五個 skip 出口都呼叫它。
# 邏輯:讀 $STATE_FILE 的 finished= 時間戳,離現在超過 $STALE_HOURS 小時(或
# state 檔不存在、或時間戳解析失敗)就視為「已經連續失敗/被擋一段時間」,
# 改用 high 優先權自己發一則(而不是 notify_skip 固定的 default),文字帶上
# 距上次成功完成多久,讓值班的人一眼看出這不是單次、無害的略過。
skip_or_alarm() {
  local reason="$1" finished_raw="" finished_epoch now_epoch age_h
  now_epoch="$(date +%s)"
  if [ -f "$STATE_FILE" ]; then
    finished_raw="$(grep -m1 '^finished=' "$STATE_FILE" 2>/dev/null | cut -d= -f2- || true)"
  fi
  if [ -n "$finished_raw" ] && finished_epoch="$(date -d "$finished_raw" +%s 2>/dev/null)"; then
    age_h=$(( (now_epoch - finished_epoch) / 3600 ))
    if [ "$age_h" -lt "$STALE_HOURS" ]; then
      notify_skip "$reason"
    else
      notify "${reason}；距上次成功完成已 ${age_h} 小時（超過 ${STALE_HOURS} 小時門檻）" high "略過"
    fi
  else
    # state 檔不存在，或 finished= 缺失／無法解析 → 寧可吵不要靜默重演 08-31~09-03。
    notify "${reason}；找不到可解析的上次成功完成紀錄（$STATE_FILE）" high "略過"
  fi
}

echo "=== safe-branch-stats start $(taipei_date -Is) ==="

if in_radar_quiet_window; then
  echo "inside quiet window — skip"
  skip_or_alarm "正值日更安靜窗，分點排行略過"
  exit 0
fi

# 直接搶鎖(而不是像過去只用 fuser 偷看),搶到就一路持有到本程序結束
# (fd 9 在 EXIT 時由 kernel 自動關閉即釋放,不需要、也不應該手動 close/reuse fd 9)。
# 只「看」不「拿」曾是本次事故唯一真正的第二層保護——安靜窗算錯之後,
# 這裡就形同虛設,才會四天寫進 0 列都沒人擋下來。
# 拿到鎖之後,01:10 的 data-backfill.sh 若撞上本作業仍在跑會自行讓路一晚:
# 深歷史回補是可續跑的,晚一夜不損失任何資料;夜間帳本不是,這正是本次
# 事故要保護的東西,所以刻意選邊。不要「修好」成雙方都不持鎖。
exec 9>/tmp/radar-db.lock
if ! flock -n 9; then
  echo "radar-db.lock held — skip"
  skip_or_alarm "資料庫鎖占用，分點排行略過"
  exit 0
fi

if [ -f "$FLAG" ]; then
  echo "mid-publish flag present — skip"
  skip_or_alarm "回補中途上線進行中，分點排行略過"
  exit 0
fi

FREE="$(free_gb)"
awk -v f="$FREE" -v m="$MIN_FREE_GB" 'BEGIN { exit !(f+0 >= m+0) }' || {
  echo "disk free ${FREE}G < ${MIN_FREE_GB}G — skip"
  skip_or_alarm "磁碟空間不足（剩 ${FREE}G），分點排行略過"
  exit 0
}

MEM="$(mem_available_mb)"
if [ "${MEM:-0}" -lt "$MIN_MEM_MB" ]; then
  echo "MemAvailable ${MEM}MB < ${MIN_MEM_MB}MB — skip"
  skip_or_alarm "記憶體不足（${MEM}MB < ${MIN_MEM_MB}MB），分點排行略過"
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

# 起 daemon 之前必須先關掉 fd 9 —— flock 綁在 open file description 上,
# 而下面兩個 nohup 出來的是**常駐**程序,會繼承 fd 9 並讓這把鎖在本腳本
# 結束後仍然被持有。那會讓 14:10/15:00/16:10/17:40/21:20/22:00 每一輪的
# acquire_db_lock 全部搶不到而 exit 0(整條日更停擺),而 bf-cron-guard 用
# fuser 偵測時會看到自己,把回補容器永遠 pause 住。
# 此處 DB 工作已全部結束(stats/pit/pctile/scores/export/deploy 都在上面),
# 所以現在放鎖是安全的。同樣的處理見 manual-catchup.sh:36。
exec 9>&-

if ! pgrep -f 'vps/scripts/bf-cron-guard.sh' >/dev/null 2>&1; then
  nohup bash "$REPO/vps/scripts/bf-cron-guard.sh" >> "${BF_GUARD_LOG:-$HOME/bf-cron-guard.log}" 2>&1 &
fi

if ! pgrep -f 'vps/scripts/bf-supervisor.sh' >/dev/null 2>&1; then
  nohup bash "$REPO/vps/scripts/bf-supervisor.sh" >> "${BF_SUPERVISOR_LOG:-$HOME/bf-supervisor.log}" 2>&1 &
fi

notify_ok "分點排行與分數夜間重算完成（統計=${STATS_NOTE}，帳本=${PIT_NOTE}，分位計數=${PAIR_PCTILE_NOTE}，分數=${SCORES_NOTE}）"
echo "=== safe-branch-stats done $(taipei_date -Is) ==="
