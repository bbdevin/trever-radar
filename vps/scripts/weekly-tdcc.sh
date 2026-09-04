#!/usr/bin/env bash
# TDCC 大戶週更(docs/34 B1 / docs/35):週六 06:30(週備份 05:00 之後)。
# pause bf → import-tdcc → export → deploy → unpause;失敗 ntfy High。
# 故意不呼叫 in_radar_quiet_window(本槽就在安靜窗內跑,靠 flag+guard 擋 bf)。
source "$(dirname "$0")/lib.sh"

FLAG="/tmp/radar-tdcc.flag"
PAUSED=0

trap - ERR
trap 'rm -f "$FLAG" 2>/dev/null || true; if [ "${PAUSED:-0}" -eq 1 ]; then unpause_bf_containers; fi' EXIT

echo "=== weekly-tdcc start $(taipei_date -Is) ==="

if fuser /tmp/radar-db.lock >/dev/null 2>&1; then
  echo "radar-db.lock held — skip"
  notify_skip "資料庫鎖占用，大戶週更略過"
  exit 0
fi

touch "$FLAG"
if bf_container_running; then
  echo "pause bf containers"
  pause_bf_containers
  PAUSED=1
  sleep 3
fi

# 正式步驟恢復 High 告警
install_fail_trap

acquire_db_lock
sync_code

echo "import-tdcc"
radar import-tdcc
radar export-json
deploy_data

rm -f "$FLAG"
if [ "$PAUSED" -eq 1 ]; then
  echo "unpause bf"
  unpause_bf_containers
  PAUSED=0
fi

# flock 綁在 open file description 上,而下面兩個 nohup 出來的是常駐程序,
# 會繼承 acquire_db_lock 開的 fd 9 並在本腳本結束後繼續持有那把鎖。真的發生時
# (兩個 daemon 剛好都不在跑,例如重開機後 @reboot 尚未生效),之後每一輪日更的
# acquire_db_lock 都會搶不到而 exit 0。DB 工作在上面已全部結束,此處放鎖是安全的。
# 同樣的處理見 manual-catchup.sh:36。
exec 9>&-

if ! pgrep -f 'vps/scripts/bf-cron-guard.sh' >/dev/null 2>&1; then
  nohup bash "$REPO/vps/scripts/bf-cron-guard.sh" >> "${BF_GUARD_LOG:-$HOME/bf-cron-guard.log}" 2>&1 &
fi
if ! pgrep -f 'vps/scripts/bf-supervisor.sh' >/dev/null 2>&1; then
  nohup bash "$REPO/vps/scripts/bf-supervisor.sh" >> "${BF_SUPERVISOR_LOG:-$HOME/bf-supervisor.log}" 2>&1 &
fi

notify_ok "大戶持股週更完成並上線"
echo "=== weekly-tdcc done $(taipei_date -Is) ==="
