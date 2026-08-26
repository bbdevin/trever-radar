#!/usr/bin/env bash
# 共用函式(docs/31 §2 實作規範)。所有 vps/scripts/*.sh 都 source 本檔。
# 慣例:失敗 → ntfy High 告警;成功靜默。非交易日 importer 靠 NoDataError 安全空跑(既有哲學)。
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="$REPO/vps/.env"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

SCRIPT_NAME="$(basename "${0:-lib.sh}")"

# $1=訊息,$2=priority(預設 high;成功摘要用 default)
notify() {
  [ -n "${NTFY:-}" ] || return 0
  curl -s -m 10 \
    -H "Priority: ${2:-high}" \
    -H "Title: radar-vps ${SCRIPT_NAME}" \
    -d "$1" "https://ntfy.sh/${NTFY}" >/dev/null || true
}

trap 'notify "FAILED at line $LINENO (tail ~/radar-cron.log)"' ERR

# 互斥鎖:防「上一輪超時未結束」堆疊(WAL+busy_timeout 是第一層,這是第二層保險)。
# 搶不到=跳過本輪並通知。長期歷史回補容器(WP-B6/WP-M4)刻意不拿這把鎖(docs/31 §2)。
acquire_db_lock() {
  exec 9>/tmp/radar-db.lock
  if ! flock -n 9; then
    notify "skipped: previous round still holds /tmp/radar-db.lock" default
    exit 0
  fi
}

# 開輪先拉 code(策略邏輯在程式碼裡,舊碼算出舊 reasons——既有教訓);
# 映像重 build 靠 docker layer cache,requirements.txt 沒變時近零成本。
# core.filemode=false:VPS 上 chmod +x script 不會被 git 當成「本地修改」擋 pull
# (2026-08-21 事故:本地 dirty scripts → pull Aborting → 全日無 export)。
sync_code() {
  cd "$REPO"
  git config core.filemode false
  if ! git pull --ff-only; then
    # 常見殘渣:手動改過 / CRLF / 舊 filemode;丟掉 vps/scripts 本地改動後重試一次
    git checkout -- vps/scripts/ || true
    git pull --ff-only
  fi
  docker build -q -t radar-pipeline pipeline >/dev/null
}

# FUGLE_API_KEY:優先 vps/.env;否則讀盤中 worker 的 pipeline/intraday/.env(WP-H3 與盤中同一把)。
if [ -z "${FUGLE_API_KEY:-}" ] && [ -f "$REPO/pipeline/intraday/.env" ]; then
  FUGLE_API_KEY="$(grep -E '^FUGLE_API_KEY=' "$REPO/pipeline/intraday/.env" | tail -n 1 | cut -d= -f2- | tr -d '\r' | sed -e 's/^["'\'']//' -e 's/["'\'']$//' || true)"
  export FUGLE_API_KEY
fi

# 跑管線一個指令。容器內 /app = repo 根;第三個 -v 必掛,export-json 產物才會落地主機。
# 只傳 RADAR_FINMIND_TOKEN / FUGLE_API_KEY 進容器(deploy 憑證留在主機,權限分離)。
radar() {
  docker run --rm \
    -e RADAR_FINMIND_TOKEN="${RADAR_FINMIND_TOKEN:-}" \
    -e FUGLE_API_KEY="${FUGLE_API_KEY:-}" \
    -v "$REPO/pipeline":/app/pipeline \
    -v "$REPO/data":/app/data \
    -v "$REPO/web/public/data":/app/web/public/data \
    radar-pipeline python -m radar "$@"
}

# JSON 上線:wrangler 讀 vps/.env 的 CLOUDFLARE_API_TOKEN/ACCOUNT_ID(已 set -a 載入),
# 資產 hash 去重只傳變動檔,deploy 完即生效(影子期只掛 /data-preview/*)。
deploy_data() {
  cd "$REPO/cloudflare-data-worker"
  [ -d node_modules ] || npm install --no-audit --no-fund
  npx wrangler deploy
  cd "$REPO"
}

taipei_date() { TZ=Asia/Taipei date "$@"; }

# 安靜窗(docs/35):daily-* / deep / 週六備份+TDCC / mid 期間不應開新 bf 寫者。
# 回傳 0 = 在窗內(應 pause / 勿啟動回補)。
# 單一真相:bf-cron-guard / mid-publish / safe-stats / margin-bf / bf-supervisor 共用。
in_radar_quiet_window() {
  local dow hhmm
  dow=$(TZ=Asia/Taipei date +%u)
  hhmm=$((10#$(TZ=Asia/Taipei date +%H%M)))
  # 週六:01:10 deep;05:00 backup → 06:30 TDCC(涵蓋至 07:30)
  if [ "$dow" -eq 6 ]; then
    { [ "$hhmm" -ge 55 ] && [ "$hhmm" -le 230 ]; } && return 0
    { [ "$hhmm" -ge 450 ] && [ "$hhmm" -le 730 ]; } && return 0
    return 1
  fi
  # 週日:01:10 deep;02:30 margin-bf
  if [ "$dow" -eq 7 ]; then
    { [ "$hhmm" -ge 55 ] && [ "$hhmm" -le 400 ]; } && return 0
    return 1
  fi
  # 平日:14:10 market / 15:00 tpex quotes / 16:10 insti / 17:40+21:00 branches / 22:10 margin / 01:10 deep
  # + mid 03/09/12/20 附近短窗由 mid flag 另擋;此處對齊 daily 與 deep
  { [ "$hhmm" -ge 1405 ] && [ "$hhmm" -le 1545 ]; } && return 0
  { [ "$hhmm" -ge 1605 ] && [ "$hhmm" -le 1650 ]; } && return 0
  { [ "$hhmm" -ge 1735 ] && [ "$hhmm" -le 1930 ]; } && return 0
  { [ "$hhmm" -ge 2055 ] && [ "$hhmm" -le 2200 ]; } && return 0
  { [ "$hhmm" -ge 2205 ] && [ "$hhmm" -le 2250 ]; } && return 0
  { [ "$hhmm" -ge 55 ] && [ "$hhmm" -le 230 ]; } && return 0
  return 1
}

# bf 具名容器(歷史回補;不拿 flock)
BF_CONTAINERS="${BF_CONTAINERS:-radar-bf-branches radar-bf-warrant}"

bf_container_running() {
  local c
  for c in $BF_CONTAINERS; do
    if docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null | grep -q true; then
      return 0
    fi
  done
  return 1
}

pause_bf_containers() {
  local c
  for c in $BF_CONTAINERS; do docker pause "$c" 2>/dev/null || true; done
}

unpause_bf_containers() {
  local c
  for c in $BF_CONTAINERS; do docker unpause "$c" 2>/dev/null || true; done
}
