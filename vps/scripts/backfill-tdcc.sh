#!/usr/bin/env bash
# TDCC 大戶 archive 回補 + export(docs/34)。
# 來源:wirelessr/tdcc-opendata-archive（官方 getOD 僅最新週）。
# 預設 2026-04-01～今天;archive 實際約自 2026-04-30。
# 一次性:~/tdcc-archive-backfill.done 存在則跳過;FORCE=1 重跑。
# 手動建議:盤後／非 daily 窗;會 pause bf 數分鐘。
source "$(dirname "$0")/lib.sh"

DONE_FLAG="${TDCC_BF_DONE:-$HOME/tdcc-archive-backfill.done}"
FROM="${TDCC_BF_FROM:-2026-04-01}"
TO="${TDCC_BF_TO:-}"
FLAG="/tmp/radar-tdcc-backfill.flag"

trap - ERR
trap 'rm -f "$FLAG" 2>/dev/null || true' EXIT

echo "=== backfill-tdcc start $(taipei_date -Is) ==="

if [ "${FORCE:-0}" != "1" ] && [ -f "$DONE_FLAG" ]; then
  echo "already done ($DONE_FLAG) — skip (FORCE=1 to rerun)"
  exit 0
fi

if [ "${SKIP_QUIET:-0}" != "1" ] && in_radar_quiet_window; then
  echo "inside quiet window — skip (SKIP_QUIET=1 to run anyway)"
  notify_skip "正值安靜窗，大戶歷史回補略過"
  exit 0
fi

if fuser /tmp/radar-db.lock >/dev/null 2>&1; then
  echo "radar-db.lock held — skip"
  notify_skip "資料庫鎖占用，大戶歷史回補略過"
  exit 0
fi

touch "$FLAG"
PAUSED=0
if bf_container_running; then
  echo "pause bf containers"
  pause_bf_containers
  PAUSED=1
  sleep 3
fi

install_fail_trap

acquire_db_lock
sync_code

echo "backfill-tdcc --from $FROM ${TO:-"(to=today)"}"
if [ -n "$TO" ]; then
  radar backfill-tdcc --from "$FROM" --to "$TO" --sleep 0.4
else
  radar backfill-tdcc --from "$FROM" --sleep 0.4
fi
radar export-json
deploy_data

date -Iseconds > "$DONE_FLAG"
echo "marked done: $DONE_FLAG"

rm -f "$FLAG"
if [ "$PAUSED" -eq 1 ]; then
  echo "unpause bf"
  unpause_bf_containers
fi

notify_ok "大戶歷史回補完成（自 ${FROM} 起）並上線"
echo "=== backfill-tdcc done $(taipei_date -Is) ==="
