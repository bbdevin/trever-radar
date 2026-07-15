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
sync_code() {
  cd "$REPO"
  git pull --ff-only
  docker build -q -t radar-pipeline pipeline >/dev/null
}

# 跑管線一個指令。容器內 /app = repo 根;第三個 -v 必掛,export-json 產物才會落地主機。
# 只傳 RADAR_FINMIND_TOKEN 進容器(deploy 憑證留在主機,權限分離)。
radar() {
  docker run --rm \
    -e RADAR_FINMIND_TOKEN="${RADAR_FINMIND_TOKEN:-}" \
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
