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
    weekly-refdata.sh) echo "題材地緣週更" ;;
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
    adjust-incremental.sh) echo "還原因子日增量" ;;
    warrant-backfill.sh) echo "權證分點回補" ;;
    repair-window.sh) echo "正式修復窗" ;;
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

# 等分點來源鎖最多 $1 秒(docs/47 §8.5):22:30 第二輪撞上還在抓的第一輪時要**等**,不能
# 靜默略過——略過的結果可能是「今天沒有任何一輪上線」。等滿仍拿不到 = 第一輪卡住
# (它的抓取有 7200 秒硬上限,正常不會發生),high 通知、exit 0。
# 鎖序不變:呼叫端先拿 DB 鎖再呼叫這個;握著來源鎖等 DB 鎖的人(warrant-backfill.sh)拿的是
# 非阻塞 DB 鎖,所以兩邊仍不可能互相等待。等的期間**不握 DB 鎖**(呼叫端要先放)。
acquire_branch_source_lock_wait() {
  local secs="$1" t0
  t0="$(date +%s)"
  exec 8>/tmp/radar-branch-source.lock
  if flock -w "$secs" 8; then
    echo "branch source lock acquired waited=$(( $(date +%s) - t0 ))s"
    return 0
  fi
  notify "分點來源鎖等滿 ${secs} 秒仍未釋放（前一輪分點抓取疑似卡住），本輪未執行" high "失敗"
  exit 0
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
# --init(docs/47 §8.7):容器內 python 是 PID 1,沒有 init 時 SIGTERM 會被核心忽略——
# `timeout --signal=TERM` 只殺得掉 docker CLI,容器裡的爬蟲變孤兒、沒人握來源鎖還在打
# 鏡像站(2026-10-07 驗證者抓到)。--init 讓 tini 當 PID 1 轉送 SIGTERM;docker run 前景
# 模式預設 --sig-proxy 會把 CLI 收到的 TERM 送進容器。分點抓取的 CLI 另裝 handler,
# 收到 TERM 寫 checkpoint 後以 143 離開;其他指令照 python 預設直接結束。
radar() {
  local rc=0
  radar_secret_env_new
  docker run --rm --init \
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
    docker run --rm --init \
      --env-file "$RADAR_SECRET_ENV_FILE" \
      -v "$REPO/pipeline":/app/pipeline \
      -v "$REPO/data":/app/data \
      -v "$REPO/web/public/data":/app/web/public/data \
      radar-pipeline python -m radar "$@" || rc=$?
  radar_secret_env_cleanup
  ( exit "$rc" )
  return "$rc"
}

# docs/38 §7.19 每日期貨量異常摘要:在 deploy_data **之後**呼叫(推播講的必須是已經
# 上線的那一份)。讀剛寫好的 web/public/data/radar.json,不開資料庫——容器只唯讀掛
# web/public/data,連 data/ 都不掛,也不需要金鑰,所以不走 radar()/radar_timeout。
#
# 去重:標記檔 $FUTURES_DIGEST_DIR/.futures-digest-<期貨行情日>,**只在 ntfy 確認
# 收到之後**才寫——推送失敗的那一輪不留標記,下一輪(17:40／22:00)會重送。
# 16:10 送成功之後,後面兩輪只有在期貨行情日往前推進時才會再送。超過 14 天的標記
# 每次順手刪掉。
#
# 這一步**絕不影響本輪**(warn-and-continue):硬上限 60 秒;所有可能非零的指令都在
# `|| …` 或 `if` 裡;摘要算不出來只 notify_warn 一則;永遠 return 0。

# 只給 futures_digest 用:送出並**回傳 curl 的結果**(-f:HTTP 錯誤也算失敗)。
# 刻意不改 notify():各輪都在 set -e 底下呼叫它,它必須永遠成功。
# 沒有設定 NTFY → 回 1(沒有送出),標記因此不寫。
futures_digest_send() {
  [ -n "${NTFY:-}" ] || return 1
  curl -sf -m 10 \
    -H "Priority: default" \
    -H "Title: $2" \
    -d "$1" "https://ntfy.sh/${NTFY}" >/dev/null
}

FUTURES_DIGEST_DIR="${FUTURES_DIGEST_DIR:-${HOME:-/tmp}}"
futures_digest() {
  local out="" rc=0 title="" as_of="" marker="" body=""
  find "$FUTURES_DIGEST_DIR" -maxdepth 1 -type f -name '.futures-digest-*' -mtime +14 \
    -delete 2>/dev/null || true
  out="$(timeout --signal=TERM --kill-after=10s 60s \
    docker run --rm \
      -v "$REPO/pipeline":/app/pipeline \
      -v "$REPO/web/public/data":/app/web/public/data:ro \
      radar-pipeline python -m radar futures-anomaly-digest --out /app/web/public/data)" || rc=$?
  if [ "$rc" -ne 0 ]; then
    notify_warn "期貨量異常摘要產生失敗（exit ${rc}），本輪照常；網站已上線" || true
    return 0
  fi
  [ -n "$out" ] || return 0
  title="$(printf '%s\n' "$out" | head -n 1 || true)"
  as_of="${title##* }"
  case "$as_of" in
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) ;;
    *) echo "futures-digest: 標題讀不出期貨行情日(${title}),略過" || true; return 0 ;;
  esac
  marker="${FUTURES_DIGEST_DIR}/.futures-digest-${as_of}"
  if [ -e "$marker" ]; then
    echo "futures-digest: ${as_of} 已送過,略過" || true
    return 0
  fi
  body="$(printf '%s\n' "$out" | tail -n +2 || true)"
  if futures_digest_send "$body" "$title"; then
    : > "$marker" || true
  else
    echo "futures-digest: ${as_of} 推送沒有成功,不寫標記,下一輪重送" || true
  fi
  return 0
}

# JSON 上線:wrangler 讀 vps/.env 的 CLOUDFLARE_API_TOKEN/ACCOUNT_ID(已 set -a 載入),
# 資產 hash 去重只傳變動檔,deploy 完即生效(影子期只掛 /data-preview/*)。
#
# 離開碼要**自己**接住,不能靠 set -e——這個函式會被 run_step / run_step_or_fail
# 包在 `if` 的測試式裡跑,而 if 的測試式整段關掉 set -e(關掉是連同被呼叫函式
# 內部一起關)。舊寫法的最後一行是 `cd "$REPO"`,於是 `npx wrangler deploy` 失敗
# 之後函式照樣往下跑,回傳 cd 的 0:整輪把「沒上線」報成成功,還會去寫完成標記、
# 發 notify_ok,而 00:05 的夜間備援看到標記就整夜略過。實測(stub npx 回 9):
#   裸 deploy_data              rc=9  中止          ← set -e 在這裡有效
#   run_step "deploy" deploy_data  rc=0  繼續(!)   ← 舊寫法,失敗被吃掉
# 修好之後兩者都是 9。收尾 `( exit "$rc" ); return "$rc"` 與 radar() 同一個形狀,
# 理由也相同:裸呼叫時就地帶著原碼中止(逐位元同於改動前),被 if 包住時忠實回傳。
deploy_data() {
  local rc=0
  cd "$REPO/cloudflare-data-worker" || return $?
  if [ ! -d node_modules ]; then
    npm install --no-audit --no-fund || rc=$?
  fi
  if [ "$rc" -eq 0 ]; then
    npx wrangler deploy || rc=$?
  fi
  cd "$REPO" || true
  ( exit "$rc" )
  return "$rc"
}

# 首頁「多方榜」(docs/48 §1.1):export-json 之後、deploy_data 之前呼叫。
# 只讀剛匯出的 web/public/data/*.json(radar.json + stocks/core|chips|hist),不開資料庫,
# 在主機上直接跑 Node(22+,--experimental-strip-types 跑 web/lib 的 TS),不進容器。
# 產物:web/public/data/bull_board.json(原子寫)、data/bull_board_log/YYYY-MM.jsonl
# (追加)及其當月副本 web/public/data/bull_board_log/,隨後由 deploy_data 一起上線。
# 實測 2,418 檔 33.5 s;硬上限 BULL_BOARD_TIMEOUT_SECS(預設 600 s)+30 s kill。
#
# 這一步**絕不擋本輪**(warn-and-continue,本函式自己就是那個不中止的 helper):
#   * 計時 log 走 run_step(同一行 `step bull-board start/done rc= elapsed=`),
#     包在 if 的測試式裡取碼——set -e 不會中止、ERR trap 也不觸發。
#   * 失敗(含逾時 124/137、node 不在 PATH 127)只發一則 notify_warn,永遠 return 0;
#     首頁沿用上一版 bull_board.json(畫面以 data_date 自述是哪一天的名單),
#     deploy_data 與之後的步驟照跑。
#   * 呼叫端一律裸呼叫 `build_bull_board`,不可包進 run_step_or_fail(那會讓它
#     變成中止型步驟)。
BULL_BOARD_TIMEOUT_SECS="${BULL_BOARD_TIMEOUT_SECS:-600}"
build_bull_board() {
  local rc=0
  if run_step "bull-board" timeout --signal=TERM --kill-after=30s "${BULL_BOARD_TIMEOUT_SECS}s" \
      node --experimental-strip-types --no-warnings "$REPO/web/scripts/build-bull-board.mjs" \
      --data "$REPO/web/public/data" --log "$REPO/data/bull_board_log"; then
    return 0
  else
    rc=$?
  fi
  notify_warn "多方榜建置失敗（碼 ${rc}），本輪照常上線；首頁多方榜沿用上一版" || true
  return 0
}

taipei_date() { TZ=Asia/Taipei date "$@"; }

# ── docs/47 排程優化:輪詢到公布為止、有變動才上線、等鎖不略過 ─────────────────
#
# 這一段的四個原則(完整理由與 12 個交易日的實測見 docs/47):
#   1. 輪詢到公布為止:每輪有起點/間隔/截止;每次嘗試前 `flock -w` 拿 DB 鎖,
#      匯入只要幾秒,沒到(exit 75)就**先放鎖再睡**——絕不握著鎖等來源。
#   2. 有變動才上線:本輪所有匯入都沒寫進任何列 → 不 compute/export/deploy。
#   3. 分點全量爬由探測觸發(probe-branch-day),不是時間一到就爬。
#   4. 搶不到鎖就等,不略過(acquire_db_lock_wait;data-backfill.sh 仍維持 flock -n)。
# 開關:RADAR_POLL=0 = 只試一次、75 當成已到(舊行為);BRANCH_PROBE=0 = 不探測直接爬。

RADAR_DB_LOCK_FILE="${RADAR_DB_LOCK_FILE:-/tmp/radar-db.lock}"
# 本輪開跑時刻(台北 ISO,與 import_logs.run_at 同格式,可直接字串比較)。
ROUND_STARTED_AT="${ROUND_STARTED_AT:-$(TZ=Asia/Taipei date -Iseconds)}"

# 等 DB 鎖最多 $1 秒。fd 9 還沒開就先開;已經握著同一個 fd 的鎖時立即成功
# (flock 對同一個 open file description 重鎖是轉換,不會自己擋自己)。
# 回傳 flock 的結果,不通知、不 exit——由呼叫端決定逾時的後果。
db_lock_take() {
  local secs="$1"
  if ! { true >&9; } 2>/dev/null; then
    exec 9>"$RADAR_DB_LOCK_FILE"
  fi
  flock -w "$secs" 9
}

# 只放鎖、不關 fd(之後 db_lock_take 用同一個 fd 再鎖)。
release_db_lock() {
  flock -u 9 2>/dev/null || true
}

# 五支日更輪的取鎖:搶不到就**等**(最多 $1 秒),不再像 acquire_db_lock 一樣
# 立刻略過——2026-09 的 log:週一 14:10 那輪的題材/地緣/產業別跑 45–55 分鐘,
# 15:00 上櫃輪 `flock -n` 失敗,整輪上櫃日K 靜默消失。等滿仍拿不到 = 上一輪卡住,
# 這是要叫醒人的事故(high),本輪 exit 0。
acquire_db_lock_wait() {
  local secs="$1" t0
  t0="$(date +%s)"
  if db_lock_take "$secs"; then
    echo "db lock acquired waited=$(( $(date +%s) - t0 ))s"
    return 0
  fi
  notify "資料庫鎖等滿 ${secs} 秒仍未釋放（前一輪疑似卡住），本輪未執行" high "失敗"
  exit 0
}

# poll_until LABEL DEADLINE_HHMM INTERVAL_SEC CMD...
#
# 反覆執行 CMD 直到它回 0(已公布)或其他非 75 的碼(錯誤,原碼回傳),
# 或台北時間到了 DEADLINE_HHMM(回 75)。CMD 回 75 = 「還沒到,等一下再來」。
# 每次嘗試前先拿 DB 鎖(POLL_HOLD_DB_LOCK=0 時不碰鎖,給唯讀探測用);
# 75 之後**先 flock -u 放鎖再睡**。成功時回 0、截止時回 75,兩者都仍握著鎖
# (只有「睡覺」那段沒有鎖),呼叫端之後寫 DB 是安全的。
# 每一輪 log 一行可 grep 的結果:
#   poll <label> ready at=HH:MM attempts=N
#   poll <label> deadline at=HH:MM attempts=N
# RADAR_POLL=0:只試一次,75 當成已到(回 0)——舊行為,手動補跑或緊急關閉輪詢用。
POLL_LOCK_WAIT_SECS="${POLL_LOCK_WAIT_SECS:-3600}"
poll_until() {
  local label="$1" deadline="$2" interval="$3"
  shift 3
  local attempts=0 rc=0 now_hhmm now_min dl_min left
  dl_min=$(( (10#$deadline / 100) * 60 + 10#$deadline % 100 ))
  while :; do
    attempts=$(( attempts + 1 ))
    if [ "${POLL_HOLD_DB_LOCK:-1}" = "1" ] && ! db_lock_take "${POLL_LOCK_WAIT_SECS:-3600}"; then
      notify "${label}：資料庫鎖等滿 ${POLL_LOCK_WAIT_SECS:-3600} 秒仍未釋放，本輪中止" high "失敗"
      exit 0
    fi
    if "$@"; then
      rc=0
    else
      rc=$?
    fi
    if [ "$rc" -ne 75 ]; then
      if [ "$rc" -eq 0 ]; then
        echo "poll ${label} ready at=$(taipei_date +%H:%M) attempts=${attempts}"
      fi
      return "$rc"
    fi
    if [ "${RADAR_POLL:-1}" = "0" ]; then
      echo "poll ${label} single attempt at=$(taipei_date +%H:%M) (RADAR_POLL=0: 75 treated as ready)"
      return 0
    fi
    # 截止判斷在放鎖**之前**:截止時回 75 仍握著鎖。呼叫端常在 75 之後還要寫 DB
    # (daily-insti 的權證主檔、庫藏股、部分上線;週一題材補跑),若這裡先放鎖,
    # 那些步驟就會在沒有鎖的情況下寫正式 DB(2026-10-04 驗證者抓到)。
    now_hhmm="$(taipei_date +%H%M)"
    now_min=$(( (10#$now_hhmm / 100) * 60 + 10#$now_hhmm % 100 ))
    if [ "$now_min" -ge "$dl_min" ]; then
      echo "poll ${label} deadline at=$(taipei_date +%H:%M) attempts=${attempts}"
      return 75
    fi
    if [ "${POLL_HOLD_DB_LOCK:-1}" = "1" ]; then
      release_db_lock
    fi
    left=$(( (dl_min - now_min) * 60 ))
    if [ "$interval" -lt "$left" ]; then
      sleep "$interval"
    else
      sleep "$left"
    fi
  done
}

# 唯讀查一個值(?mode=ro,不搶寫鎖):$1 = SQL,其後 = 參數。印出第一列第一欄(NULL → 空)。
radar_ro_sql() {
  docker run --rm -v "$REPO/data":/app/data radar-pipeline \
    python -c "import sqlite3,sys
conn = sqlite3.connect('file:/app/data/radar.db?mode=ro', uri=True)
row = conn.execute(sys.argv[1], sys.argv[2:]).fetchone()
print('' if row is None or row[0] is None else row[0])" "$@"
}

# MAX(date) FROM daily_prices 是否等於 $1(預設台北今天)。非交易日 = 今天沒有
# 日K,分點/資券/夜間輪就不該再爬 5,000 個請求、再 export 一份沒變的網站
# (09-25、09-28 實測各浪費 ~3.5 小時鎖)。查詢失敗 → 視為是(照舊跑,寧可多跑)。
price_date_is_today() {
  local want="${1:-$(taipei_date +%F)}" got=""
  got="$(radar_ro_sql "SELECT MAX(date) FROM daily_prices" 2>/dev/null)" || got=""
  if [ -z "$got" ]; then
    echo "price_date_is_today: 查不到 MAX(date)，視為交易日照常執行"
    return 0
  fi
  echo "price date: max=${got} want=${want}"
  [ "$got" = "$want" ]
}

# 本輪(ROUND_STARTED_AT 之後)有沒有任何匯入真的寫進列:import_logs 的
# ok 且 rows>0(= cron log 裡的 `ok … rows=[1-9]`)。沒有 → 呼叫端印
# `publish skipped: no change` 並不 compute/export/deploy。查詢失敗 → 視為有。
round_has_changes() {
  local n=""
  n="$(radar_ro_sql "SELECT COUNT(*) FROM import_logs WHERE run_at >= ? AND status = 'ok' AND rows > 0 AND dataset IN ('quotes','insti','margin','futures-day','branch')" "$ROUND_STARTED_AT" 2>/dev/null)" || n=""
  if [ -z "$n" ]; then
    echo "round_has_changes: 查詢失敗，視為有變動"
    return 0
  fi
  echo "round changes since ${ROUND_STARTED_AT}: ${n} import(s) wrote rows"
  [ "$n" -gt 0 ]
}

# 分點匯入對 $1(YYYY-MM-DD)最新一次的覆蓋率(import_logs dataset='branch_coverage'
# 的 ratio=,0.0000–1.0000)。查不到 → 空字串。寫進完成標記的 coverage_ratio=。
branch_round_coverage_ratio() {
  local note=""
  note="$(radar_ro_sql "SELECT error FROM import_logs WHERE dataset = 'branch_coverage' AND date = ? ORDER BY id DESC LIMIT 1" "$1" 2>/dev/null)" || note=""
  printf '%s\n' "$note" | sed -n 's/.*ratio=\([0-9.]*\).*/\1/p' | head -n 1
}

# 完成標記($1 = 日期)裡的 coverage_ratio=;舊格式(只有時間一行)→ 空字串。
branch_marker_coverage_ratio() {
  sed -n 's/^coverage_ratio=\([0-9.]*\)$/\1/p' "$(branch_round_marker "$1")" 2>/dev/null | head -n 1 || true
}

# 週一參考資料(題材/地緣/產業別)的「本 ISO 週已完成」標記。weekly-refdata.sh
# (週一 11:00)寫;daily-market.sh 在 crontab 改好之前看不到它就自己補跑。
refdata_marker() { echo "/tmp/radar-refdata-$(taipei_date +%G-W%V).done"; }

# 每週一次的補充資料:失敗一律 warn-and-continue,不得擋當天行情上線。
# (原本定義在 daily-market.sh;2026-10 搬來這裡給 weekly-refdata.sh 共用。)
weekly_step() {
  local label="$1"; shift
  set +e
  "$@"
  local rc=$?
  set -e
  if [ "$rc" -ne 0 ]; then
    echo "${label} failed rc=${rc} (continue)"
    notify_warn "每週${label}失敗（碼 ${rc}），沿用既有資料"
  fi
}

# 統一的計時 wrapper:鎖等待之外,每一個主要步驟(radar 子指令、deploy)都套
# 這個,單一格式才追得出 93→138 分鐘是哪一步在長。用 if/then 取得結果而不是
# set +e/-e 切換,是為了不論成功失敗都印得出 done/elapsed 這行,呼叫端仍可用
# `if run_step ...; then ... else rc=$?; ... fi` 讀到原始離開碼(set -e 對
# if 的測試式免疫,不會在這裡提早中止)。
#
# 這裡的 if 形狀不是可有可無的實作細節:本檔在 source 時就 install_fail_trap,
# 而 `set +e` **不會**讓 ERR trap 安靜下來(實測:set +e 之下回 75 仍然觸發)。
# daily-branches.sh 的分點匯入正是靠 run_step 回傳的原始離開碼做 0/75/76 分級,
# 改成 set +e 取碼會讓每個「個別標的失敗但可上線」的日子多送一則 high 假故障。
#
# 定義放這裡(而不是某一支腳本裡)是因為兩支以上的腳本要用同一份:
# safe-branch-stats.sh(00:05 夜間補跑)與 daily-branches.sh(17:40 / 22:00),
# 兩輪的 log 必須是同一個格式,才能用同一個 grep 比較同一步在兩輪的耗時。
run_step() {
  local label="$1"; shift
  local t0 rc
  t0="$(date +%s)"
  echo "step ${label} start $(taipei_date -Is)"
  if "$@"; then
    rc=0
  else
    rc=$?
  fi
  echo "step ${label} done rc=${rc} elapsed=$(( $(date +%s) - t0 ))s"
  return "$rc"
}

# run_step 的「失敗會自己講出來」版本:跑一步,失敗就發一則 high 通知,再帶著
# **原本的離開碼**中止整輪。
#
# 為什麼非有不可:`radar` 是 shell **函式**,而 ERR trap 不繼承進函式(沒有 set -E),
# 所以 `radar X` 失敗時,本檔在 source 時裝好的那個 ERR trap 一則通知都不發——
# bash 在 radar 內部的 `( exit "$rc" )` 就地帶著原碼結束,只有 cron log 記得這件事。
# 用本檔的形狀寫成的測量 harness(四種形狀,同一個 radar/run_step):
#
#   radar X                        rc=9  ERR trap 不觸發  中止  ← 舊寫法,零通知
#   run_step "X" radar X           rc=9  ERR trap **觸發** 中止  ← 會與本函式雙重通知
#   run_step "X" radar X || exit   rc=9  ERR trap 不觸發  中止  ← 與舊寫法逐位元相同
#   run_step_or_fail "X" radar X   rc=9  ERR trap 不觸發  中止 + **一則通知**
#
# 形狀的三個要點都不是可有可無的:
#   1. 取碼寫在 else 那一支的第一行。失敗與 `$?` 之間不准夾任何指令(連 echo 都不行),
#      夾一個就把碼換成那個指令的碼。也不可以改成 `if …; then return 0; fi; rc=$?`:
#      那個 `$?` 讀到的是整個 if 複合指令的碼(不成立時是 0),不是 run_step 的碼。
#   2. 用 if 取碼,不用 `set +e`:`set +e` **不會**讓 ERR trap 安靜下來(實測,見
#      run_step 上面那段),那會讓同一次失敗多送一則「執行到第 N 行失敗」。
#   3. 收尾用 `exit "$rc"`,不是讓非零回到頂層。回到頂層會觸發 ERR trap,於是同一次
#      失敗送兩則通知——5cb7649 修掉的正是那個雙重通知。
#
# 通知的**前半句**(哪一步、哪個碼、本輪中止、未上線)只有這一份,所有呼叫點共用;
# **後半句**(這一輪失敗的真正後果)每一支腳本自己宣告,見 set_round_consequence。
#
# 為什麼後半句非參數化不可:這個 helper 最初只服務 daily-branches.sh,句尾寫死
# 「本輪不寫完成標記,00:05 夜間作業會重算」——那是**那一輪**的收尾契約
# (見 branch_round_marker)。14:10 / 15:00 / 16:10 / 21:20 四輪都沒有完成標記,
# 而 00:05 的夜間作業只重算分點統計,不會重抓日K、法人或資券。照抄那半句
# 等於在最需要準確的那一則通知裡對值班的人說謊:他會以為凌晨會自動補好而不動手。
#
# 為什麼用「未宣告就拒跑」而不是預設值:預設值會讓忘記宣告的腳本**靜默**繼承
# 別人的後果句,而錯的那一句只在真的失敗的那一晚才被讀到——最晚、最貴的發現時機。
# 這裡改成第一步就檢查:沒宣告的腳本每一次執行(成功的日子也一樣)都會在做任何
# 工作之前就帶著 high 通知 exit 78,第一次上線當天就會被發現。
ROUND_FAIL_CONSEQUENCE=""

# 宣告「這一輪失敗會怎樣」。措辭要求:講網站會停在什麼內容,以及**哪一輪、什麼時候**
# 會補上(沒有人會補就要明講要人工補)。一句話,接在共用的「本輪中止、未上線」之後。
set_round_consequence() {
  ROUND_FAIL_CONSEQUENCE="$1"
}

run_step_or_fail() {
  local label="$1"
  local rc=0
  if [ -z "${ROUND_FAIL_CONSEQUENCE:-}" ]; then
    echo "run_step_or_fail: ${SCRIPT_NAME} 未宣告本輪失敗後果（缺 set_round_consequence），拒絕執行 ${label}" >&2
    notify "${SCRIPT_NAME} 未呼叫 set_round_consequence，拒絕執行步驟 ${label}（這是腳本本身的錯,不是資料問題）" high "失敗"
    exit 78
  fi
  if run_step "$@"; then
    return 0
  else
    rc=$?
  fi
  notify "${label} 失敗（碼 ${rc}），本輪中止、未上線；${ROUND_FAIL_CONSEQUENCE}" high "失敗"
  exit "$rc"
}

# ── 前置步驟的兩種寬鬆版(docs/47 §8.3)─────────────────────────────────
#
# 2026-10-06 的事故:17:30 分點輪第一步 `import-daily quotes,insti` 只是**補抓**
# (日K與法人早在 14:05/16:00 就進庫了),TPEx 一個瞬時的 ChunkedEncodingError 讓它回 1,
# run_step_or_fail 於是把整輪中止——當天的分點要等 22:30 第二輪,約 00:00 才上線,
# 晚了 5 小時。補抓失敗而資料早就在庫,代價只是「少補到晚到的幾列」,不該賠上整輪。
#
# run_step_or_fail_unless LABEL PREDICATE CMD…:失敗時先問 PREDICATE(一個 shell
# 函式,例如 price_date_is_today);成立 → warn 一則、續跑(return 0);不成立 →
# 與 run_step_or_fail 逐字相同的契約(指名步驟與碼的 high 通知 + 原碼 exit)。
# 取碼形狀與 run_step_or_fail 相同(if 取碼、else 第一行接 $?、exit 原碼),理由見該函式。
run_step_or_fail_unless() {
  local label="$1" pred="$2"
  local rc=0
  shift 2
  if [ -z "${ROUND_FAIL_CONSEQUENCE:-}" ]; then
    echo "run_step_or_fail_unless: ${SCRIPT_NAME} 未宣告本輪失敗後果（缺 set_round_consequence），拒絕執行 ${label}" >&2
    notify "${SCRIPT_NAME} 未呼叫 set_round_consequence，拒絕執行步驟 ${label}（這是腳本本身的錯,不是資料問題）" high "失敗"
    exit 78
  fi
  if run_step "$label" "$@"; then
    return 0
  else
    rc=$?
  fi
  if "$pred"; then
    notify_warn "${label} 失敗（碼 ${rc}），但今天的資料已在庫，本輪續跑"
    return 0
  fi
  notify "${label} 失敗（碼 ${rc}）且今天的資料不在庫，本輪中止、未上線；${ROUND_FAIL_CONSEQUENCE}" high "失敗"
  exit "$rc"
}

# run_step_or_warn LABEL CMD…:失敗只 warn 一則、永遠續跑(return 0)。給「沿用既有
# 資料就好」的步驟(seed-branches 的追蹤名單同步)。
run_step_or_warn() {
  local label="$1"
  local rc=0
  if run_step "$@"; then
    return 0
  else
    rc=$?
  fi
  notify_warn "${label} 失敗（碼 ${rc}），本輪續跑，沿用既有資料"
  return 0
}

# MAX(date) FROM indicators_daily 是否等於 $1(預設台北今天):與 price_date_is_today
# 同形,給分點輪的 compute-indicators 當「今天的指標早在 14:05/14:45/16:00 算過了」的述詞。
indicators_date_is_today() {
  local want="${1:-$(taipei_date +%F)}" got=""
  got="$(radar_ro_sql "SELECT MAX(date) FROM indicators_daily" 2>/dev/null)" || got=""
  if [ -z "$got" ]; then
    echo "indicators_date_is_today: 查不到 MAX(date)，視為已算過"
    return 0
  fi
  echo "indicators date: max=${got} want=${want}"
  [ "$got" = "$want" ]
}

# 「那一輪 daily-branches 真的整條跑完(含 deploy_data)」的完成標記。
#
# 為什麼夜間作業不能只看 import_logs 的 status:那一列只講「匯入」這一段。
# 匯入寫下 status=ok 之後,compute-branch-stats 仍可能 OOM(crontab 註記這支是
# 1.7GB OOM 風險最高的一步)而整輪什麼都沒算出來也沒上線。這時夜間作業正是
# 唯一的補救,絕不能因為看到 ok 就跳過——那會把備援本身關掉。
#
# 夜間作業只問這個檔案**存不存在**,不看內容、也不跟任何時間比大小。
# 它只在 deploy_data 成功之後才寫,所以「存在」本身就等於「當天有一輪完整鏈
# 算完並上線了」;算到一半 OOM 的那一輪根本走不到寫標記這一步,夜間作業照常補跑。
#
# 為什麼不比時間:22:00 那輪已改成只匯入(daily-branches.sh 的
# BRANCH_ROUND_MODE=import),當天最新的分點匯入是 23:00 左右寫的,而標記是
# 17:40 那輪 20:30 左右寫的——標記永遠比匯入舊,比時間會讓夜間作業每晚都重算。
#
# 檔名的日期是**開跑日**(資料日),不是收工當下的日曆日:完整鏈可能跨過午夜。
# 內容仍寫完成時間(ISO),純粹給人事後看「那一輪幾點收的工」。
#
# 放 /tmp:重開機後自然消失,而重開機之後我們本來就無從保證上一輪算完了。
branch_round_marker() { echo "/tmp/radar-branch-round-$1.done"; }

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

# mid-backfill-publish 的排程時段(crontab: `0 3,9,12,20 * * *`,每天,與 dow 無關)。
#
# 為什麼要單獨列一份:這四輪**不在** quiet_window_at 裡——那個函式的註解自己寫著
# 「mid 03/09/12/20 附近短窗由 mid flag 另擋」。用 flag 擋對「不要同時開第二個 bf
# 寫者」是夠的,但對「我這個長工作會不會害那一輪跑不成」不夠:
# mid-backfill-publish.sh 一開頭是 `fuser /tmp/radar-db.lock` → 略過,所以任何
# 握著 DB 鎖跨過整點的長工作,都會讓那一輪靜默消失。一支要跑好幾週的爬蟲,
# 這等於吃掉數十次發布。
#
# 刻意不把它們併進 quiet_window_at:那會改變五支既有腳本的行為(它們會開始在
# mid 期間略過),是超出需要的副作用。這裡只多給長工作一個更完整的問法。
#
# 實測耗時 10:43–13:14 分(2026-09-02～09-04 的 radar-cron.log),取 20 分鐘涵蓋。
MID_PUBLISH_HOURS="${MID_PUBLISH_HOURS:-3 9 12 20}"
MID_PUBLISH_RUN_MINUTES="${MID_PUBLISH_RUN_MINUTES:-20}"

mid_publish_at() {
  local hhmm="$1" h m x
  h=$(( hhmm / 100 ))
  m=$(( hhmm % 100 ))
  [ "$m" -lt "$MID_PUBLISH_RUN_MINUTES" ] || return 1
  for x in $MID_PUBLISH_HOURS; do
    [ "$h" -eq "$x" ] && return 0
  done
  return 1
}

# safe-branch-stats.sh(crontab `5 0 * * 2-6`,但排程日 = 前一交易日的隔天,
# 對長工作而言就是「每天 00:05 都可能有人開始寫」)。它握著真鎖跑到約 01:35,
# 而且自 2026-09-08 起開跑前最多會先等到 00:55。
#
# **刻意只加在這層 overlay,不加進 quiet_window_at**:把 00:05 併進共用安靜窗表,
# safe-branch-stats.sh 自己就會判定「我在安靜窗裡」而略過自己——那正是 2026-08-31
# 的停擺;pipeline/tests/test_cron_quiet_window.py 也直接斷言 cron 時刻不得落在
# 安靜窗內。00:55 之後已經在安靜窗裡了,所以這裡只需補 0005–0054。
NIGHTLY_STATS_END_HHMM="${NIGHTLY_STATS_END_HHMM:-54}"
nightly_stats_at() {
  local hhmm="$1"
  [ "$hhmm" -ge 5 ] && [ "$hhmm" -le "$NIGHTLY_STATS_END_HHMM" ]
}

# monthly-directors.sh(crontab `0 7 16 * *`)——每月 16 日 07:00,坐在平日
# 02:31–14:05 那段最長的空檔正中間。
#
# 這一輪是**日期**限定的,`<dow> <hhmm>` 這個既有簽章表達不了它,所以掃描函式
# 多吃一個可選的第三個參數 <dom>(day-of-month)。不傳第三參數 = 「這是一個沒有
# 日期的探測」,此時本述詞一律回 false,而不是假裝每天都會發生:兩參數形式只有
# 測試在用,正式路徑(不帶參數)一定會帶上台北當下的 day-of-month。
MONTHLY_DIRECTORS_DOM="${MONTHLY_DIRECTORS_DOM:-16}"
MONTHLY_DIRECTORS_RUN_MINUTES="${MONTHLY_DIRECTORS_RUN_MINUTES:-20}"
monthly_directors_at() {
  local hhmm="$1" dom="${2:-0}"
  [ "$dom" -eq "$MONTHLY_DIRECTORS_DOM" ] || return 1
  [ "$hhmm" -ge 700 ] && [ "$hhmm" -lt $(( 700 + MONTHLY_DIRECTORS_RUN_MINUTES )) ]
}

# 距離「下一個會有排程寫入者在跑的分鐘」還有幾分鐘——安靜窗與 overlay(mid-publish、
# 00:05 分點排行、每月 16 日董監)取先。長工作要問的是這個,不是只問安靜窗;
# `minutes_until_quiet_window` 保留給只在意 daily/deep 那類窗口的呼叫者。
#
# 2026-09-07 23:40 實測:只認得 00:55 安靜窗的舊版回答 75 分鐘,真正的答案是
# 25 分鐘(00:05 的 safe-branch-stats.sh),守衛因此核准了一個會吃掉整輪分點
# 排行的塊。
#
# 可傳入明確的 <dow> <hhmm> [<dom>](測試用);不傳則用台北現在時刻與日期。
# 省略 <dom> 的兩參數形式是「無日期探測」,月排程述詞在那個形式下一律不成立。
minutes_until_next_scheduled_writer() {
  local dow hhmm dom
  if [ "$#" -ge 2 ]; then
    dow="$1"
    hhmm="$2"
    dom="${3:-0}"
  else
    dow=$(TZ=Asia/Taipei date +%u)
    hhmm=$((10#$(TZ=Asia/Taipei date +%H%M)))
    dom=$((10#$(TZ=Asia/Taipei date +%d)))
  fi
  local start_min=$(( (hhmm / 100) * 60 + hhmm % 100 ))
  local i abs_min probe_dow probe_min probe_hhmm probe_dom day_offset
  for (( i = 0; i <= QUIET_SCAN_CAP_MINUTES; i++ )); do
    abs_min=$(( start_min + i ))
    day_offset=$(( abs_min / 1440 ))
    probe_dow=$(( ((dow - 1 + day_offset) % 7) + 1 ))
    probe_min=$(( abs_min % 1440 ))
    probe_hhmm=$(( (probe_min / 60) * 100 + probe_min % 60 ))
    # 掃描上限是 24 小時,所以最多跨一次午夜;要偵測的是「16 日」,而 15+1=16
    # 每個月都成立,月底 31+1 也永遠不會被誤判成 16,不需要月長度表。
    if [ "$dom" -gt 0 ]; then
      probe_dom=$(( dom + day_offset ))
    else
      probe_dom=0
    fi
    if quiet_window_at "$probe_dow" "$probe_hhmm" \
       || mid_publish_at "$probe_hhmm" \
       || nightly_stats_at "$probe_hhmm" \
       || monthly_directors_at "$probe_hhmm" "$probe_dom"; then
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
