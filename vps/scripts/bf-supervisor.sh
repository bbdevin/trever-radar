#!/usr/bin/env bash
# 歷史回補管家(docs/35 Layer 2):同時只一個寫者、Exit 後自啟、完成 ntfy。
# 順序:預設 branches → warrant;BF_ORDER=warrant,branches 可改(仍單寫者,不並跑)。
# 安靜窗／mid flag／db lock／margin flag 期間不新開容器(已跑的交給 bf-cron-guard pause)。
#
# 環境:
#   BF_BRANCH_TOP(預設 0 全股票) BF_BRANCH_DAYS(490) BF_WARRANT_TOP(200) BF_WARRANT_DAYS(120)
#   BF_SLEEP(1.2) BF_RESTART_SLEEP(120) BF_DONE_DIR(~)
#   BF_ORDER=branches,warrant|warrant,branches
#   FORCE_BF=1 忽略 done flag 重跑
# crontab:@reboot + */10 保活(見 crontab.example)
source "$(dirname "$0")/lib.sh"

# 可選覆寫:~/bf-supervisor.env(例 BF_ORDER=warrant,branches)
if [ -f "${BF_SUPERVISOR_ENV:-$HOME/bf-supervisor.env}" ]; then
  set -a
  # shellcheck disable=SC1090
  . "${BF_SUPERVISOR_ENV:-$HOME/bf-supervisor.env}"
  set +a
fi

trap - ERR

STATE_FILE="${BF_SUPERVISOR_STATE:-$HOME/bf-supervisor.state}"
LOG="${BF_SUPERVISOR_LOG:-$HOME/bf-supervisor.log}"
DONE_DIR="${BF_DONE_DIR:-$HOME}"
BRANCHES_DONE="$DONE_DIR/bf-branches.done"
WARRANT_DONE="$DONE_DIR/bf-warrant.done"
MID_FLAG="${MID_PUBLISH_FLAG:-/tmp/radar-mid-publish.flag}"
MARGIN_FLAG="/tmp/radar-margin-backfill.flag"
TDCC_FLAG="/tmp/radar-tdcc.flag"
BRANCH_NAME="radar-bf-branches"
WARRANT_NAME="radar-bf-warrant"
BRANCH_TOP="${BF_BRANCH_TOP:-0}"
BRANCH_DAYS="${BF_BRANCH_DAYS:-490}"
WARRANT_TOP="${BF_WARRANT_TOP:-200}"
WARRANT_DAYS="${BF_WARRANT_DAYS:-120}"
SLEEP_S="${BF_SLEEP:-1.2}"
RESTART_SLEEP="${BF_RESTART_SLEEP:-120}"
MAX_FAILS="${BF_MAX_FAILS:-8}"

exec 7>/tmp/radar-bf-supervisor.lock
if ! flock -n 7; then
  exit 0
fi

log() { echo "$(TZ=Asia/Taipei date '+%F %T') $*" | tee -a "$LOG"; }

write_state() {
  {
    echo "updated=$(taipei_date -Is)"
    echo "phase=$1"
    echo "detail=$2"
  } > "$STATE_FILE"
}

should_hold() {
  in_radar_quiet_window && return 0
  [ -f "$MID_FLAG" ] && return 0
  [ -f "$MARGIN_FLAG" ] && return 0
  [ -f "$TDCC_FLAG" ] && return 0
  fuser /tmp/radar-db.lock >/dev/null 2>&1 && return 0
  return 1
}

container_status() {
  # running | paused | exited | missing
  local name="$1" st
  if ! docker inspect "$name" >/dev/null 2>&1; then
    echo missing
    return
  fi
  st=$(docker inspect -f '{{.State.Status}}' "$name" 2>/dev/null || echo missing)
  echo "$st"
}

container_exit_code() {
  docker inspect -f '{{.State.ExitCode}}' "$1" 2>/dev/null || echo 1
}

ensure_image() {
  if ! docker image inspect radar-pipeline >/dev/null 2>&1; then
    log "build radar-pipeline image"
    docker build -q -t radar-pipeline "$REPO/pipeline" >/dev/null
  fi
}

start_job() {
  local name="$1"
  shift
  ensure_image
  docker rm -f "$name" >/dev/null 2>&1 || true
  log "START $name: $*"
  if ! docker run -d --name "$name" \
    -e RADAR_FINMIND_TOKEN="${RADAR_FINMIND_TOKEN:-}" \
    -e FUGLE_API_KEY="${FUGLE_API_KEY:-}" \
    -v "$REPO/pipeline":/app/pipeline \
    -v "$REPO/data":/app/data \
    -v "$REPO/web/public/data":/app/web/public/data \
    radar-pipeline python -m radar "$@" >/dev/null; then
    log "FAILED to start $name"
    notify "無法啟動容器 ${name}" high "失敗"
    return 1
  fi
  return 0
}

mark_done() {
  local flag="$1" label="$2"
  taipei_date -Is > "$flag"
  log "DONE $label → $flag"
}

BRANCH_FAILS=0
WARRANT_FAILS=0
# 逗號分隔相位;預設先分點。使用者可設 BF_ORDER=warrant,branches
BF_ORDER="${BF_ORDER:-branches,warrant}"

run_branches_phase() {
  if [ "${FORCE_BF:-0}" != "1" ] && [ -f "$BRANCHES_DONE" ]; then
    return 1
  fi
  bst=$(container_status "$BRANCH_NAME")
  case "$bst" in
    running|paused)
      write_state branches "alive:$bst"
      sleep 60
      return 0
      ;;
    exited)
      ec=$(container_exit_code "$BRANCH_NAME")
      if [ "$ec" = "0" ]; then
        BRANCH_FAILS=0
        mark_done "$BRANCHES_DONE" "分點"
        docker rm -f "$BRANCH_NAME" >/dev/null 2>&1 || true
        if [ -f "$WARRANT_DONE" ]; then
          notify_ok "分點與權證歷史回補全部完成"
          write_state idle "all_complete"
        else
          notify_ok "分點歷史回補完成，接著跑權證分點"
        fi
      else
        BRANCH_FAILS=$((BRANCH_FAILS + 1))
        log "branches exited rc=$ec fails=$BRANCH_FAILS/$MAX_FAILS"
        if [ "$BRANCH_FAILS" -ge "$MAX_FAILS" ]; then
          notify "分點回補連續失敗 ${MAX_FAILS} 次（碼 ${ec}），暫時放棄" high "失敗"
          write_state branches "gave_up:$ec"
          sleep 600
          return 0
        fi
        notify_warn "分點回補異常結束（碼 ${ec}），將重啟（${BRANCH_FAILS}/${MAX_FAILS}）"
        write_state branches "restart_wait:$ec"
        sleep "$RESTART_SLEEP"
        if should_hold; then return 0; fi
        start_job "$BRANCH_NAME" backfill-branches --top "$BRANCH_TOP" --days "$BRANCH_DAYS" --sleep "$SLEEP_S" || true
      fi
      return 0
      ;;
    missing|*)
      wst=$(container_status "$WARRANT_NAME")
      if [ "$wst" = "running" ] || [ "$wst" = "paused" ]; then
        write_state wait "warrant_still_alive"
        sleep 60
        return 0
      fi
      start_job "$BRANCH_NAME" backfill-branches --top "$BRANCH_TOP" --days "$BRANCH_DAYS" --sleep "$SLEEP_S" || true
      write_state branches "started"
      sleep 30
      return 0
      ;;
  esac
}

run_warrant_phase() {
  if [ "${FORCE_BF:-0}" != "1" ] && [ -f "$WARRANT_DONE" ]; then
    return 1
  fi
  wst=$(container_status "$WARRANT_NAME")
  case "$wst" in
    running|paused)
      write_state warrant "alive:$wst"
      sleep 60
      return 0
      ;;
    exited)
      ec=$(container_exit_code "$WARRANT_NAME")
      if [ "$ec" = "0" ]; then
        WARRANT_FAILS=0
        mark_done "$WARRANT_DONE" "權證分點"
        docker rm -f "$WARRANT_NAME" >/dev/null 2>&1 || true
        if [ -f "$BRANCHES_DONE" ]; then
          notify_ok "分點與權證歷史回補全部完成"
          write_state idle "all_complete"
        else
          notify_ok "權證分點歷史回補完成，接著跑分點"
        fi
      else
        WARRANT_FAILS=$((WARRANT_FAILS + 1))
        log "warrant exited rc=$ec fails=$WARRANT_FAILS/$MAX_FAILS"
        if [ "$WARRANT_FAILS" -ge "$MAX_FAILS" ]; then
          notify "權證分點回補連續失敗 ${MAX_FAILS} 次（碼 ${ec}），暫時放棄" high "失敗"
          write_state warrant "gave_up:$ec"
          sleep 600
          return 0
        fi
        notify_warn "權證分點回補異常結束（碼 ${ec}），將重啟（${WARRANT_FAILS}/${MAX_FAILS}）"
        write_state warrant "restart_wait:$ec"
        sleep "$RESTART_SLEEP"
        if should_hold; then return 0; fi
        start_job "$WARRANT_NAME" backfill-warrant-branches --top "$WARRANT_TOP" --days "$WARRANT_DAYS" --sleep "$SLEEP_S" || true
      fi
      return 0
      ;;
    missing|*)
      bst=$(container_status "$BRANCH_NAME")
      if [ "$bst" = "running" ] || [ "$bst" = "paused" ]; then
        write_state wait "branches_still_alive"
        sleep 60
        return 0
      fi
      start_job "$WARRANT_NAME" backfill-warrant-branches --top "$WARRANT_TOP" --days "$WARRANT_DAYS" --sleep "$SLEEP_S" || true
      write_state warrant "started"
      sleep 30
      return 0
      ;;
  esac
}

# 單實例長跑
log "supervisor start (repo=$REPO order=$BF_ORDER)"
write_state boot "start"

while true; do
  if [ "${FORCE_BF:-0}" != "1" ] && [ -f "$BRANCHES_DONE" ] && [ -f "$WARRANT_DONE" ]; then
    write_state idle "both_done"
    log "both jobs done — idle (FORCE_BF=1 to rerun)"
    sleep 300
    continue
  fi

  if should_hold; then
    write_state hold "quiet_or_lock"
    sleep 60
    continue
  fi

  handled=0
  IFS=',' read -r -a phases <<< "$BF_ORDER"
  for phase in "${phases[@]}"; do
    phase=$(echo "$phase" | tr -d '[:space:]')
    case "$phase" in
      branches)
        if run_branches_phase; then handled=1; break; fi
        ;;
      warrant)
        if run_warrant_phase; then handled=1; break; fi
        ;;
    esac
  done

  if [ "$handled" = "0" ]; then
    sleep 120
  fi
done
