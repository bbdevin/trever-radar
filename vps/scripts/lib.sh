#!/usr/bin/env bash
# 共用函式(docs/31 §2 實作規範)。所有 vps/scripts/*.sh 都 source 本檔。
# 慣例:失敗 → ntfy High;日更／週更成功 → 繁中 notify_ok;非交易日 importer 靠 NoDataError 安全空跑。
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

# 排程中文名(ntfy 標題用)
job_zh() {
  case "$SCRIPT_NAME" in
    daily-market.sh) echo "收盤行情" ;;
    daily-tpex-quotes.sh) echo "上櫃日K" ;;
    daily-insti.sh) echo "三大法人" ;;
    daily-branches.sh) echo "分點籌碼" ;;
    daily-margin.sh) echo "融資融券" ;;
    weekly-backup.sh) echo "週備份" ;;
    weekly-tdcc.sh) echo "大戶持股" ;;
    mid-backfill-publish.sh) echo "回補中途上線" ;;
    safe-branch-stats.sh) echo "分點排行" ;;
    data-backfill.sh) echo "深歷史" ;;
    bf-supervisor.sh) echo "歷史回補" ;;
    monthly-directors.sh) echo "董監持股" ;;
    backfill-margin.sh) echo "資券回補" ;;
    backfill-tdcc.sh) echo "大戶回補" ;;
    disk-cleanup.sh) echo "磁碟清理" ;;
    manual-catchup.sh) echo "手動追補" ;;
    adjust-backfill.sh) echo "還原因子回補" ;;
    warrant-backfill.sh) echo "權證分點回補" ;;
    *) echo "${SCRIPT_NAME%.sh}" ;;
  esac
}

# $1=內文 $2=priority(預設 high) $3=標題後綴(成功/失敗/略過/注意;可空)
notify() {
  [ -n "${NTFY:-}" ] || return 0
  local msg="$1"
  local pri="${2:-high}"
  local kind="${3:-}"
  local title
  if [ -n "$kind" ]; then
    title="$(job_zh) · ${kind}"
  else
    title="$(job_zh)"
  fi
  curl -s -m 10 \
    -H "Priority: ${pri}" \
    -H "Title: ${title}" \
    -d "$msg" "https://ntfy.sh/${NTFY}" >/dev/null || true
}

notify_ok() { notify "$1" default "成功"; }
notify_skip() { notify "$1" default "略過"; }
notify_warn() { notify "$1" default "注意"; }

install_fail_trap() {
  trap 'notify "執行到第 ${LINENO} 行失敗，請查看 ~/radar-cron.log" high "失敗"' ERR
}

# 慣例:失敗 → ntfy High;日更／週更成功 → notify_ok 一則 default。
install_fail_trap

# 互斥鎖:防「上一輪超時未結束」堆疊(WAL+busy_timeout 是第一層,這是第二層保險)。
# 搶不到=跳過本輪並通知。長期歷史回補容器(WP-B6/WP-M4)刻意不拿這把鎖(docs/31 §2)。
acquire_db_lock() {
  exec 9>/tmp/radar-db.lock
  if ! flock -n 9; then
    notify_skip "上一輪還在跑（資料庫鎖占用），本輪略過"
    exit 0
  fi
}

# MoneyDJ/Fubon mirrors are a shared external source, independent of SQLite's
# writer lock.  General-stock and warrant jobs must never interleave requests.
acquire_branch_source_lock() {
  exec 8>/tmp/radar-branch-source.lock
  if ! flock -n 8; then
    notify_skip "分點來源鎖占用，本輪略過（避免與權證／股票分點交錯抓取）"
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
  # Windows 提交常把 mode 存成 100644;pull 後 cron 直呼會 Permission denied。
  # 每次開輪強制 +x,不依賴 git filemode。
  chmod +x "$REPO"/vps/scripts/*.sh 2>/dev/null || true
  docker build -q -t radar-pipeline pipeline >/dev/null
}

# FUGLE_API_KEY:優先 vps/.env;否則讀盤中 worker 的 pipeline/intraday/.env(WP-H3 與盤中同一把)。
if [ -z "${FUGLE_API_KEY:-}" ] && [ -f "$REPO/pipeline/intraday/.env" ]; then
  FUGLE_API_KEY="$(grep -E '^FUGLE_API_KEY=' "$REPO/pipeline/intraday/.env" | tail -n 1 | cut -d= -f2- | tr -d '\r' | sed -e 's/^["'\'']//' -e 's/["'\'']$//' || true)"
  export FUGLE_API_KEY
fi

# 金鑰一律走 --env-file,不用 `-e KEY=值`:argv 在 Linux 上人人可讀
# (`ps` / `/proc/<pid>/cmdline`),用 -e 等於把兩把金鑰完整值攤給本機任一帳號;
# 改走 0600 暫存檔後,容器內拿到的還是同樣兩個環境變數,而 `/proc/<pid>/environ`
# 只有 owner 讀得到,不是外洩面。
#
# docker --env-file 解析規則(值 = 第一個 '=' 之後的整行原文):
#   * 不去引號、不去空白 → 值一律不加引號,中間空白與結尾 '=' 都逐位元保留
#     (FUGLE_API_KEY 兩者都有,加引號會把引號本身當成值的一部分送進去)。
#   * 變數未設／為空 → 仍要寫 `KEY=`,容器內得到空字串,與原本 `-e KEY=` 相同;
#     整行省略會變成「改由 host 環境查找」,語意不同,不可省。
#   * 值內含換行無法用這個格式表達 → fail closed,不默默截斷金鑰。
RADAR_SECRET_ENV_FILE=""
RADAR_SECRET_TRAP_DONE=0

radar_secret_env_cleanup() {
  if [ -n "${RADAR_SECRET_ENV_FILE:-}" ]; then
    rm -f "$RADAR_SECRET_ENV_FILE" 2>/dev/null || true
    RADAR_SECRET_ENV_FILE=""
  fi
}

# EXIT 兜底(正常路徑在每次呼叫後就刪了,這裡收 set -e 中止／被 kill 的殘檔)。
# 多支腳本是在 source lib.sh 之後才裝自己的 EXIT trap(收 flag / unpause 容器),
# 所以延後到「第一次真的要產檔」才掛,並把既有指令串在前面——絕不覆蓋既有 trap。
# 子 shell(如 $(radar …))裡不串:trap 改不回父層,且 bash 不會在子 shell 結束時
# 跑繼承來的 EXIT trap,串進去反而會提早跑掉父層的 flag 清理／unpause。
# 維護約束:新腳本的 `trap … EXIT` 一律要裝在第一次呼叫 radar/radar_timeout 之前,
# 否則會把這裡串好的清理蓋掉(現有腳本都符合;正常路徑另有即時刪檔,不致外洩)。
radar_secret_install_trap() {
  if [ "$RADAR_SECRET_TRAP_DONE" = "1" ]; then
    return 0
  fi
  RADAR_SECRET_TRAP_DONE=1
  local existing="" q="'"
  if [ "${BASHPID:-$$}" = "$$" ]; then
    existing="$(trap -p EXIT)"      # 形如:trap -- 'cmd' EXIT
    existing="${existing#trap -- }"
    existing="${existing% EXIT}"
  fi
  if [ -n "$existing" ]; then
    eval "trap ${existing}${q};${q}${q}radar_secret_env_cleanup${q} EXIT"
  else
    trap 'radar_secret_env_cleanup' EXIT
  fi
}

# 現產一個 0600 暫存檔;mktemp 本來就是 0600,仍明確 chmod 一次。
radar_secret_env_new() {
  case "${RADAR_FINMIND_TOKEN:-}${FUGLE_API_KEY:-}" in
    *$'\n'*)
      notify "金鑰值含換行，無法以 --env-file 完整傳入容器，本輪中止" high "失敗"
      exit 1
      ;;
  esac
  radar_secret_env_cleanup
  radar_secret_install_trap
  RADAR_SECRET_ENV_FILE="$(mktemp "${TMPDIR:-/tmp}/radar-env.XXXXXXXX")"
  chmod 600 "$RADAR_SECRET_ENV_FILE"
  {
    printf 'RADAR_FINMIND_TOKEN=%s\n' "${RADAR_FINMIND_TOKEN:-}"
    printf 'FUGLE_API_KEY=%s\n' "${FUGLE_API_KEY:-}"
  } > "$RADAR_SECRET_ENV_FILE"
}

# 跑管線一個指令。容器內 /app = repo 根;第三個 -v 必掛,export-json 產物才會落地主機。
# 只傳 RADAR_FINMIND_TOKEN / FUGLE_API_KEY 進容器(deploy 憑證留在主機,權限分離)。
radar() {
  local rc=0
  radar_secret_env_new
  docker run --rm \
    --env-file "$RADAR_SECRET_ENV_FILE" \
    -v "$REPO/pipeline":/app/pipeline \
    -v "$REPO/data":/app/data \
    -v "$REPO/web/public/data":/app/web/public/data \
    radar-pipeline python -m radar "$@" || rc=$?
  radar_secret_env_cleanup
  # 失敗語意保持與改動前逐字相同:set -e 生效時就地中止(且不觸發 ERR trap——
  # 函式內失敗本來就不會觸發,ERR trap 不繼承進函式);set -e 被抑制時
  # (`if radar …` / `radar || …`)忠實回傳 docker 的離開碼(daily-insti 的
  # exit 75 分支靠這個碼判斷)。
  ( exit "$rc" )
  return "$rc"
}

# GNU timeout cannot execute the shell function above.  Wrap the real Docker
# invocation so the hard limit is applied to the actual collection container.
radar_timeout() {
  local hard_timeout_seconds="$1"
  shift
  local rc=0
  radar_secret_env_new
  timeout --signal=TERM --kill-after=30s "${hard_timeout_seconds}s" \
    docker run --rm \
      --env-file "$RADAR_SECRET_ENV_FILE" \
      -v "$REPO/pipeline":/app/pipeline \
      -v "$REPO/data":/app/data \
      -v "$REPO/web/public/data":/app/web/public/data \
      radar-pipeline python -m radar "$@" || rc=$?
  radar_secret_env_cleanup
  ( exit "$rc" )
  return "$rc"
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
#
# 範圍字面值只有這一份(在 quiet_window_at 裡)。in_radar_quiet_window 只是
# 「用現在時刻去問」的薄包裝,minutes_until_quiet_window 則是「用未來時刻去問」;
# 三者共用同一組數字,不可能有第二份副本漂移。
# pipeline/tests/test_cron_quiet_window.py 也是直接 regex 解析這個函式的原始碼。
quiet_window_at() {
  local dow="$1" hhmm="$2"
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
  # 平日:14:10 market / 15:00 tpex / 16:10 insti / 17:40 branches / 21:20 margin / 22:00 branches / 01:10 deep
  # + mid 03/09/12/20 附近短窗由 mid flag 另擋;此處對齊 daily 與 deep
  { [ "$hhmm" -ge 1405 ] && [ "$hhmm" -le 1545 ]; } && return 0
  { [ "$hhmm" -ge 1605 ] && [ "$hhmm" -le 1650 ]; } && return 0
  { [ "$hhmm" -ge 1735 ] && [ "$hhmm" -le 1930 ]; } && return 0
  { [ "$hhmm" -ge 2115 ] && [ "$hhmm" -le 2330 ]; } && return 0
  { [ "$hhmm" -ge 55 ] && [ "$hhmm" -le 230 ]; } && return 0
  return 1
}

in_radar_quiet_window() {
  local dow hhmm
  dow=$(TZ=Asia/Taipei date +%u)
  hhmm=$((10#$(TZ=Asia/Taipei date +%H%M)))
  quiet_window_at "$dow" "$hhmm"
}

# 距離「下一個落在安靜窗內的分鐘」還有幾分鐘(整數,印到 stdout)。
#
# 為什麼需要這個:`in_radar_quiet_window` 只能回答「現在在不在窗內」。長工作真正
# 該問的是「在下一輪排程開跑之前,我還剩多少時間」——2026-09-03 事故就是拿絕對
# 時刻當上界(「17:00 以前都可以開跑」),結果在 17:38 開了一個 20 分鐘的塊,
# 兩分鐘後 17:40 的分點輪就撞上來。正確守衛是「剩餘時間 > 預估耗時」,
# 所以要先有辦法算出剩餘時間。
#
# 逐分鐘往前掃(而不是解析範圍算差),因為範圍定義只存在於 quiet_window_at 的
# 分支裡:掃描等於把同一份定義當黑箱來問,平日／週六／週日三組不同範圍、跨午夜、
# 跨 day-of-week 全部自動正確,不需要在這裡重寫一次範圍邏輯。
# 已經在窗內 → 0。掃滿 24 小時仍找不到 → 印出上限 1440(目前每一天都有 00:55
# 那段窗,所以這條路走不到;留著是為了不讓未來把窗全刪掉時回傳無限大)。
#
# 可傳入明確的 <dow> <hhmm>(測試用);不傳則用台北現在時刻。
QUIET_SCAN_CAP_MINUTES=1440
minutes_until_quiet_window() {
  local dow hhmm
  if [ "$#" -ge 2 ]; then
    dow="$1"
    hhmm="$2"
  else
    dow=$(TZ=Asia/Taipei date +%u)
    hhmm=$((10#$(TZ=Asia/Taipei date +%H%M)))
  fi
  local start_min=$(( (hhmm / 100) * 60 + hhmm % 100 ))
  local i abs_min probe_dow probe_min probe_hhmm
  for (( i = 0; i <= QUIET_SCAN_CAP_MINUTES; i++ )); do
    abs_min=$(( start_min + i ))
    probe_dow=$(( ((dow - 1 + abs_min / 1440) % 7) + 1 ))
    probe_min=$(( abs_min % 1440 ))
    probe_hhmm=$(( (probe_min / 60) * 100 + probe_min % 60 ))
    if quiet_window_at "$probe_dow" "$probe_hhmm"; then
      echo "$i"
      return 0
    fi
  done
  echo "$QUIET_SCAN_CAP_MINUTES"
  return 0
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

# Only resume containers this script actually paused.  This preserves a quiet
# window/manual pause and avoids accidentally unpausing another operator's bf.
BF_PAUSED_BY_US=""
pause_bf_for_exclusive_writer() {
  local c running paused
  for c in $BF_CONTAINERS; do
    running=$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null || true)
    paused=$(docker inspect -f '{{.State.Paused}}' "$c" 2>/dev/null || true)
    if [ "$running" = "true" ] && [ "$paused" != "true" ]; then
      docker pause "$c" >/dev/null
      BF_PAUSED_BY_US="$BF_PAUSED_BY_US $c"
    fi
  done
}

resume_bf_paused_by_us() {
  local c
  for c in $BF_PAUSED_BY_US; do docker unpause "$c" 2>/dev/null || true; done
  BF_PAUSED_BY_US=""
}
