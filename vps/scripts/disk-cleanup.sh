#!/usr/bin/env bash
# 定時清磁碟(docs/35 ops):只清 Docker dangling／log／npm cache,絕不碰 radar.db。
# crontab:每天 07:40(日更前、週六備份/TDCC 之後)
source "$(dirname "$0")/lib.sh"

trap - ERR

LOG="${DISK_CLEANUP_LOG:-$HOME/disk-cleanup.log}"
MIN_FREE_GB="${DISK_MIN_FREE_GB:-4}"

log() { echo "$(TZ=Asia/Taipei date '+%F %T') $*" | tee -a "$LOG"; }

free_gb() {
  df -BG --output=avail / | tail -1 | tr -dc '0-9'
}

BEFORE=$(free_gb)
log "start free=${BEFORE}G"

# 1) 懸空映像／停止容器／build cache(不動 running 容器與 tagged latest)
docker container prune -f >/dev/null 2>&1 || true
docker image prune -f >/dev/null 2>&1 || true
docker builder prune -f --filter until=168h >/dev/null 2>&1 || true
docker volume prune -f >/dev/null 2>&1 || true

# 2) 過大 log 截斷(保留尾端)
for f in "$HOME/radar-cron.log" "$HOME/radar-worker.log" \
         "$HOME/bf-supervisor.log" "$HOME/bf-cron-guard.log" \
         "$HOME/disk-cleanup.log"; do
  [ -f "$f" ] || continue
  sz=$(stat -c%s "$f" 2>/dev/null || echo 0)
  # > 20MB → 只留最後 2MB
  if [ "$sz" -gt 20971520 ]; then
    tail -c 2097152 "$f" > "${f}.trim" && mv "${f}.trim" "$f"
    log "trimmed $f (was ${sz} bytes)"
  fi
done

# 3) npm cache(wrangler 安裝殘渣)
if [ -d "$HOME/.npm/_cacache" ]; then
  npm cache clean --force >/dev/null 2>&1 || true
  log "npm cache cleaned"
fi

AFTER=$(free_gb)
FREED=$((AFTER - BEFORE))
log "done free=${AFTER}G delta=${FREED}G"

if [ "$AFTER" -lt "$MIN_FREE_GB" ]; then
  notify "disk-cleanup: only ${AFTER}G free (need ≥${MIN_FREE_GB}G)" high
else
  notify "disk-cleanup: ${AFTER}G free (Δ${FREED}G)" default
fi
