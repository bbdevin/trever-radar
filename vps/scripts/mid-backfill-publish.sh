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
# 這裡的 EXIT trap 只收 flag,**刻意不做 unpause**(第 18 行那版兩件都做)。
# 看起來像漏掉,其實是分工:中途死掉時不要從一個可能死在寫入中途的腳本裡搶著
# unpause,而是把「何時安全」交給 bf-cron-guard.sh——而 guard 唯一會「維持
# pause、不搶 unpause」的條件就是這個 flag 還在(見它的檔頭第 3 行)。所以
# trap 移除 flag 就等於把恢復權交還給 guard,它每 5 分鐘一次,會在條件允許時
# unpause。正常路徑照舊在結尾自己 rm flag 再 unpause。
# 要動這行之前先想清楚:把 unpause 加回來,等於讓一個正在失敗的程序決定
# 「現在可以讓回補容器繼續寫了」,那正是這個分工要避免的。
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
    # 用 if/then/else 取離開碼,不用 `set +e; …; rc=$?; set -e`(同 daily-branches.sh)。
    # 上面第 55 行的 install_fail_trap 已經把 lib.sh 的 ERR trap **重新武裝**回來,
    # 而 `set +e` **不會**讓 ERR trap 安靜下來(實測:set +e 之下回 75 仍然觸發)。
    # 那會讓 stats 的任何一次失敗同時送出 lib 的 high 優先權「執行到第 N 行失敗」
    # 與下面那則 notify_warn——一次失敗兩則通知,而這一則本來就刻意只用一般等級
    # (stats 失敗不該炸掉整輪,匯出上線仍會進行)。警報疲勞是這個專案一直在對抗的事。
    #
    # warrant-backfill.sh 保留 `set +e` 不是不一致:那裡取碼的對象是一條**管線**
    # (`radar … | tee`),必須用 `${PIPESTATUS[0]}`,改成 if 會拿到 tee 的離開碼;
    # 而且那支腳本 `trap - ERR` 之後從不重新武裝,set +e 前後差別為零。
    # 這裡兩個條件都相反:單一指令 + trap 已武裝,所以 if 才是對的形狀。
    # 三支腳本的寫法不同各有理由,不要「統一」。
    if radar compute-branch-stats; then
      rc=0
    else
      rc=$?
    fi
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
