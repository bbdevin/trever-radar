#!/usr/bin/env bash
# Disabled PoC / future daily all-market warrant branch round.
# It is intentionally NOT active in crontab: 2026-08-28 VPS free space is
# below the 20GB gate and runtime must first be benchmarked for three days.
source "$(dirname "$0")/lib.sh"

MIN_FREE_GB="${WARRANT_BRANCH_MIN_FREE_GB:-20}"
CAP="${WARRANT_BRANCH_CAP:-25000}"
MAX_MINUTES="${WARRANT_BRANCH_MAX_MINUTES:-480}"
HARD_TIMEOUT_SECONDS="${WARRANT_BRANCH_HARD_TIMEOUT_SECONDS:-30600}"
STATE_FILE="${WARRANT_BRANCH_STATE_FILE:-}"

if ! command -v timeout >/dev/null 2>&1; then
  notify "權證分點未啟動：系統缺少 GNU timeout，無法保證硬逾時" high "失敗"
  exit 1
fi

args=(import-warrant-branch-trades --market all --top "$CAP" --sleep 1.0 \
  --max-minutes "$MAX_MINUTES")
if [ -n "$STATE_FILE" ]; then
  args+=(--state-file "$STATE_FILE")
fi
if [ "${WARRANT_BRANCH_DRY_RUN:-0}" = "1" ]; then
  # Report mode is read-only: it works below the capacity gate and never
  # pauses backfill, takes writer/source locks, rebuilds code, or deploys.
  args+=(--dry-run)
  radar "${args[@]}"
  notify_ok "權證分點唯讀目標報告完成，未寫入／未發布"
  exit 0
fi

avail_kb=$(df -Pk "$REPO/data" | awk 'NR==2 {print $4}')
if [ -z "${avail_kb:-}" ] || [ "$avail_kb" -lt $((MIN_FREE_GB * 1024 * 1024)) ]; then
  notify "權證分點未啟動：可用空間 ${avail_kb:-unknown}KB，低於 ${MIN_FREE_GB}GB 閘門" high "失敗"
  exit 1
fi

# Pause BF before acquiring write/source locks so no running request or SQLite
# transaction overlaps this one.  The trap resumes only containers paused here.
trap 'resume_bf_paused_by_us' EXIT INT TERM
pause_bf_for_exclusive_writer
acquire_db_lock
acquire_branch_source_lock
sync_code

# A nonzero command means incomplete/error/timeout.  Do not export or deploy a
# partial day, and let the atomic state file provide the next-run resume point.
if ! radar_timeout "$HARD_TIMEOUT_SECONDS" "${args[@]}"; then
  notify "權證分點未完成，未 export/deploy；保留按權證資料日命名的 state 供續跑" high "失敗"
  exit 1
fi

# PoC is measurement-only even after a complete run.  Publishing belongs to a
# later, separately approved production script after capacity/runtime gates.
notify_ok "權證分點全市場 PoC 完成；未匯出、未發布"
