#!/usr/bin/env bash
# 正式資料修復窗 — 四件待辦的修復,在一個有守衛、有順序、有前後量測的窗口內一次做完。
#
# 為什麼四件事綁在一起跑,而不是四次手動指令:
#   這四件事今天的做法是維運者早上 07:00 逐條敲指令。每一條都是對**單寫者 SQLite**
#   的全表或跨日期寫入,而整個產品都靠那一顆檔案。真正的風險不在任何一條指令本身,
#   而在於「先跑哪一條、什麼情況下不該開始、跑壞了要不要繼續」這些判斷全部只活在
#   當下那個人的腦袋裡。把它們寫成一支腳本,守衛、順序、前後證據與中止條件就變成
#   可被審閱的東西,而不是每次臨場重新發明一遍。
#
#   而且它們**本來就有先後**:步驟 1 修的是 2026-07-16..08-19 的收盤價缺口,那些
#   日期正好落在步驟 2(分點帳本 20 交易日窗)與步驟 3(20 交易日前瞻報酬)讀取的
#   窗口裡面。先跑 2 或 3,等於用還沒修好的價格算出一份要再算一次的結果。
#
# ── 前置條件(任何一條不成立就印出原因並 exit 0,不做任何事)──────────────
#   1. 權證爬蟲的暫停檔 /tmp/radar-warrant-backfill.pause **必須已經存在**。
#      本腳本刻意**不**自己建立它:建立它就等於讓人在沒有想過那支六週長跑的情況下
#      跑這個窗口。那支爬蟲會在我們的步驟之間搶走 DB 鎖,而我們的四個步驟之間是有
#      順序的——中間被插隊寫入,前後量測就不再是本窗口造成的差額。
#      要求「已存在」而不是「我幫你建」,是把那個決定留在人身上。
#   2. 不在 in_radar_quiet_window 內(排程日更優先,永遠讓路)。
#   3. minutes_until_next_scheduled_writer 必須大於 REPAIR_MIN_MINUTES(預設 90)。
#      90 這個數字的來源:長的是步驟 1 與步驟 3。步驟 1 是 25 個日期各一次探測、
#      每次約 2 個請求,中間夾著匯入寫入;步驟 3 的 compute-performance --all 要走
#      完 27,373 列評分列。兩者相加在正常機器上約一小時上下,90 分鐘是「估計耗時 +
#      餘裕」,不是絕對時刻上界——adjust-backfill.sh 與 warrant-backfill.sh 的檔頭
#      都寫了同一條規則:守衛必須是「剩餘時間 > 預估耗時」,2026-09-03 的事故就是
#      拿絕對上界當守衛出的事。
#   4. /tmp/radar-db.lock(fd 9)**先搶鎖、後 pause 回補容器**,順序不可對調——
#      理由逐字同 adjust-backfill.sh:搶不到鎖是常態,先 pause 會產生大量無謂的
#      pause/unpause,並提高撞上 guard 與 cleanup 之間 state-cache race 的機率
#      (2026-08-27 17:35 曾發生)。
#   5. 可用磁碟 >= MIN_FREE_GB(預設 4)、MemAvailable >= MIN_MEM_MB(預設 900)。
#   6. 完成旗標:跑完就留下 DONE_FLAG,重跑不會默默把四件事再做一遍(FORCE=1 覆寫)。
#      state 檔另外記住「哪幾步已經成功」,所以中途失敗後重跑只會補做剩下的。
#
# ── 四個步驟(固定順序,後一步以前一步沒有失敗為前提)────────────────────
#   1. 日K缺口。2026-07-16..08-19 共 25 個交易日,上櫃只有 466–479 列(目前正常值
#      983);其中 08-11/08-12/08-13 連上市也只有 563–565 列(正常 1,367)。修復路徑
#      是 importer.py 的 backfill() 裡那個「市場相對完整度」檢查(舊的「這個日期在
#      daily_prices 有列就算好」永遠看不到半空的日期)。CLI:
#          radar backfill --days N --datasets quotes
#      --days **不寫死**:寫死的數字下個月就是錯的(缺口起點固定,今天會往前走)。
#      N 由**執行當天的日期**推導:
#          N = (REPAIR_QUOTES_FROM 到執行日之間的平日數) + REPAIR_QUOTES_PAD
#      為什麼平日數就夠:backfill() 從今天往回走日曆日,週六日直接 continue、不消耗
#      額度;只有「已完整的交易日」與「成功匯入的交易日」讓 done 前進,國定假日的
#      空 probe 不算。所以走回 2026-07-16 所需的額度 = 該區間的**交易日數**,而
#      平日數永遠 >= 交易日數(假日只會讓交易日更少),故平日數必然足夠。
#      PAD(預設 5)是純粹的餘裕,不是正確性需求。多給的額度很便宜:走過頭的更舊
#      日期已經完整,在迴圈裡直接 continue,不發任何請求。
#      用執行日推導而不是查資料庫:--days 要回答的本來就是「從缺口起點到今天有多
#      遠」,那是日曆問題;而且這是四步裡的第一步,不該把它的正確性押在一次
#      docker+SQLite 查詢上(那次查詢失敗就等於整個窗口白開)。
#      前後量測:那 25 個日期的每市場列數,以及總列數差額對照預期的約 15,150 列。
#   2. 帳本追補。radar branch-point-in-time-persist --as-of <date>,補 branch_pit_stats
#      缺的 as-of:**2026-09-01、09-02、09-03、09-07,依此順序**(Fable 5.1 於
#      2026-09-14 拍板)。這四個日期是已經決定好的事實,不是本腳本臨場挑出來的,
#      所以寫成單一個陣列常數 LEDGER_DATES_DEFAULT,要改就改那一行;
#      REPAIR_LEDGER_DATES(空白分隔)可覆寫,給的是「同一支腳本補別的日期」這個
#      用法,不是讓預設值變成可有可無。
#      每個日期在開跑前先驗證是市場交易日:CLI 本來就會對非交易日 fail closed,但在
#      腳本裡帶著清楚訊息擋下來,比讓它死在容器裡好——而且是**全部驗完才開始跑**,
#      不會補到一半才發現第三個日期是假日。
#   3. radar compute-performance --all。27,373 列評分列,其中 2,592 列的 20 交易日
#      前瞻窗跨過一次公司行動,所以它們的前瞻報酬是用未還原價算出來的。前後各印一次
#      SUM(fwd_20d) 與 SUM(fwd_5d),讓這一步的改變看得見、也歸得了因。
#      以步驟 1 為前提:這些前瞻報酬正是從被修復的收盤價讀出來的。
#   4. 資券缺口。單一日期 2026-09-02,1,293 列對正常的 2,213 列。走的是同一個市場
#      相對檢查(現在也在 backfill_margin() 裡)。**硬性限制:21:15–23:30 之間絕不
#      執行**——daily-margin.sh 在那段時間寫同一張表。上面的前置條件正常情況下就會
#      擋掉(平日安靜窗涵蓋 2115..2330),但這一條在步驟 4 真正要跑的那一刻**再查
#      一次時鐘**:前面三步會跑掉一個多小時,開跑時合格不代表跑到第四步時還合格。
#
# ── 失敗處理 ──────────────────────────────────────────────────────────
#   某一步失敗**不回滾前面已完成的步驟**:四件事是彼此獨立的修復,補一半比完全沒補
#   好。但它會**停掉後面的步驟**、把已完成的寫進 state 檔、發一則指名該步驟的高優先
#   通知,然後以非零離開。結尾一律印一行摘要:誰跑了、誰被略過、為什麼。
#
# ── 不 export、不 deploy ───────────────────────────────────────────────
#   本腳本刻意不呼叫 export-json / deploy_data。發布是另一個決定,不該搭這班車:
#   下一輪排程(日更或 mid-publish)自己會把修好的資料帶上線。同理也不 sync_code:
#   窗口要跑的是維運者**已經審過的那份 checkout**,不是中途 git pull 換掉的新版。
#
# ── 環境變數 ──────────────────────────────────────────────────────────
#   REPAIR_STATE=$HOME/repair-window.state   已完成步驟;<state>.done 為完成旗標
#   FORCE=1                                  忽略完成旗標與 state,四步全部重做
#   REPAIR_MIN_MINUTES=90                    距下一個排程寫入者至少要有的分鐘數
#   REPAIR_QUOTES_FROM=2026-07-16            日K缺口起點(--days 由它推導)
#   REPAIR_QUOTES_TO=2026-08-19              日K缺口終點(只用於前後量測)
#   REPAIR_QUOTES_PAD=5                      --days 的安全加項(見上)
#   REPAIR_QUOTES_EXPECTED_DELTA=15150       預期補回的列數,只印比較、不當判準
#   REPAIR_LEDGER_DATES=""                   覆寫步驟 2 的 as-of 清單(空白分隔);
#                                            空 = 用 LEDGER_DATES_DEFAULT 那四個
#   REPAIR_LEDGER_WINDOW_DAYS=60             傳給 --window-days
#   REPAIR_MARGIN_DATE=2026-09-02            步驟 4 要修的日期
#   MARGIN_EXCLUDE_FROM=2115 / MARGIN_EXCLUDE_TO=2330   步驟 4 的禁止時段
#   MIN_FREE_GB=4 / MIN_MEM_MB=900
source "$(dirname "$0")/lib.sh"

FLAG="${MID_PUBLISH_FLAG:-/tmp/radar-mid-publish.flag}"
PAUSE_FILE="${WARRANT_PAUSE_FILE:-/tmp/radar-warrant-backfill.pause}"
STATE_FILE="${REPAIR_STATE:-$HOME/repair-window.state}"
DONE_FLAG="${STATE_FILE}.done"
MIN_MINUTES="${REPAIR_MIN_MINUTES:-90}"
QUOTES_FROM="${REPAIR_QUOTES_FROM:-2026-07-16}"
QUOTES_TO="${REPAIR_QUOTES_TO:-2026-08-19}"
QUOTES_PAD="${REPAIR_QUOTES_PAD:-5}"
QUOTES_EXPECTED_DELTA="${REPAIR_QUOTES_EXPECTED_DELTA:-15150}"
# 步驟 2 的 as-of 清單:Fable 5.1 於 2026-09-14 拍板的四個日期,順序就是補的順序
# (branch_pit_stats 的每個 as-of 各自獨立寫入,但由舊到新補才符合帳本的讀法)。
# 這是**決定好的事實**,所以是一個常數陣列,不是探測出來的。
LEDGER_DATES_DEFAULT=(2026-09-01 2026-09-02 2026-09-03 2026-09-07)
if [ -n "${REPAIR_LEDGER_DATES:-}" ]; then
  read -r -a LEDGER_DATES <<< "$REPAIR_LEDGER_DATES"
else
  LEDGER_DATES=("${LEDGER_DATES_DEFAULT[@]}")
fi
LEDGER_WINDOW_DAYS="${REPAIR_LEDGER_WINDOW_DAYS:-60}"
MARGIN_DATE="${REPAIR_MARGIN_DATE:-2026-09-02}"
MARGIN_EXCLUDE_FROM="${MARGIN_EXCLUDE_FROM:-2115}"
MARGIN_EXCLUDE_TO="${MARGIN_EXCLUDE_TO:-2330}"
MIN_FREE_GB="${MIN_FREE_GB:-4}"
MIN_MEM_MB="${MIN_MEM_MB:-900}"

# 失敗一律自己處理(每個失敗點都要寫 state、發一則指名步驟的通知),不靠 lib 的
# ERR trap,免得同一次失敗發兩則。
trap - ERR

# 串接而非覆蓋既有 EXIT trap(lib.sh 的金鑰暫存檔清理是在第一次呼叫 radar 時才掛
# 上去的,它自己也會串在我們前面;這裡照同樣規則處理反向情況)。
chain_exit_trap() {
  local new="$1" existing="" q="'"
  existing="$(trap -p EXIT)"
  existing="${existing#trap -- }"
  existing="${existing% EXIT}"
  if [ -n "$existing" ]; then
    eval "trap ${existing}${q};${q}${q}${new}${q} EXIT"
  else
    eval "trap ${q}${new}${q} EXIT"
  fi
}

free_gb() {
  df -PB1 "$REPO" | awk 'NR==2 {printf "%.1f", $4/1024/1024/1024}'
}

mem_available_mb() {
  awk '/MemAvailable:/ {printf "%d", $2/1024}' /proc/meminfo
}

disk_ok() {
  local free="$1"
  awk -v f="$free" -v m="$MIN_FREE_GB" 'BEGIN { exit !(f+0 >= m+0) }'
}

# 用管線映像的 python 跑 SQL(主機不需裝 sqlite3),逐列印出第一欄。
db_col() {
  docker run --rm -v "$REPO/data":/app/data radar-pipeline \
    python -c "import sqlite3,sys
for r in sqlite3.connect('/app/data/radar.db').execute(sys.argv[1]):
    print(r[0])" "$1"
}

# REPAIR_QUOTES_FROM 到執行日(含兩端)之間的平日數。backfill() 的 days 額度只被
# 交易日消耗,而平日數 >= 交易日數,所以這個數字必然涵蓋得回起點(見檔頭推導)。
weekdays_since() {
  local from="$1" today cur dow n=0
  today="$(taipei_date +%Y-%m-%d)"
  cur="$from"
  while [[ "$cur" < "$today" || "$cur" == "$today" ]]; do
    dow="$(date -d "$cur" +%u)"
    [ "$dow" -le 5 ] && n=$(( n + 1 ))
    cur="$(date -d "$cur + 1 day" +%Y-%m-%d)"
  done
  echo "$n"
}

# 原子寫:同目錄暫存檔 → mv。中斷絕不留下半截 state。
write_state() {
  local tmp
  tmp="$(mktemp "${STATE_FILE}.XXXXXX")"
  cat > "$tmp"
  mv -f "$tmp" "$STATE_FILE"
}

STEP1_STATUS=""
STEP2_STATUS=""
STEP3_STATUS=""
STEP4_STATUS=""
SUMMARY=""

persist_state() {
  {
    echo "# repair-window state $(taipei_date -Is)"
    echo "step1=${STEP1_STATUS:-pending}"
    echo "step2=${STEP2_STATUS:-pending}"
    echo "step3=${STEP3_STATUS:-pending}"
    echo "step4=${STEP4_STATUS:-pending}"
  } | write_state
}

note() { SUMMARY="${SUMMARY}${SUMMARY:+; }$1"; }

skip_step() {
  local step="$1" reason="$2"
  echo "--- ${step} SKIPPED: ${reason}"
  note "${step} skipped (${reason})"
}

# 前一步「沒有失敗」才放行。ok / ok-prior(上一次執行就成功了)/ skipped 都算放行;
# 失敗路徑其實在 fail_step 就已經離開了,這道閘是明寫出來的第二層,讓順序這件事
# 在原始碼裡看得見,而不是靠「反正它會 exit」。
gate_clear() {
  local prev="$1" status="$2"
  case "$status" in
    ok|ok-prior|skipped) return 0 ;;
    *) echo "gate: ${prev} status=${status:-none} — not clear" ; return 1 ;;
  esac
}

# 失敗:不回滾前面的步驟(獨立的修復,補一半好過完全沒補),但停掉後面的步驟。
fail_step() {
  local step="$1" rc="$2" detail="$3"
  echo "--- ${step} FAILED rc=${rc}: ${detail}"
  note "${step} FAILED rc=${rc}"
  persist_state
  echo "=== repair-window aborted $(taipei_date -Is) — ${SUMMARY}"
  notify "正式修復窗在 ${step} 失敗（碼 ${rc}，${detail}）；先前完成的步驟保留不回滾，其餘步驟已停止，state=${STATE_FILE}" high "失敗"
  exit "$rc"
}

echo "=== repair-window start $(taipei_date -Is) state=${STATE_FILE} ==="

# ── 前置條件 ────────────────────────────────────────────────────────────
# 1. 權證爬蟲暫停檔必須已經存在;本腳本刻意不建立它(見檔頭)。
if [ ! -f "$PAUSE_FILE" ]; then
  echo "warrant crawler pause file ${PAUSE_FILE} is ABSENT — refuse to start"
  echo "  (this script will not create it: a six-week crawl can take the db lock"
  echo "   between our steps, and deciding to pause it is the operator's call)"
  exit 0
fi

if in_radar_quiet_window; then
  echo "inside quiet window — skip (yield to the scheduled round)"
  exit 0
fi

if [ -f "$FLAG" ]; then
  echo "mid-publish flag present — skip"
  exit 0
fi

if [ "${FORCE:-0}" != "1" ] && [ -f "$DONE_FLAG" ]; then
  echo "already complete (${DONE_FLAG}) — skip (FORCE=1 to redo all four steps)"
  exit 0
fi

FREE="$(free_gb)"
if ! disk_ok "$FREE"; then
  echo "disk free ${FREE}G < ${MIN_FREE_GB}G — skip"
  exit 0
fi

MEM="$(mem_available_mb)"
if [ "${MEM:-0}" -lt "$MIN_MEM_MB" ]; then
  echo "MemAvailable ${MEM}MB < ${MIN_MEM_MB}MB — skip"
  exit 0
fi

# 3. 時間守衛:要的是「還剩多久」,不是「現在幾點」(見檔頭)。
UNTIL="$(minutes_until_next_scheduled_writer)"
if [ "$UNTIL" -lt "$MIN_MINUTES" ]; then
  echo "next scheduled writer in ${UNTIL}min < ${MIN_MINUTES}min — skip (not enough room for steps 1 and 3)"
  exit 0
fi
echo "next scheduled writer in ${UNTIL}min (floor ${MIN_MINUTES}min); mem=${MEM}MB free_disk=${FREE}G"

# 4. 先搶鎖、後 pause 回補容器,順序不可對調(見檔頭)。
exec 9>/tmp/radar-db.lock
if ! flock -n 9; then
  echo "radar-db.lock held — skip (a scheduled round or another writer is running)"
  exit 0
fi

# EXIT trap 必須在 pause 之前、也在第一次呼叫 radar 之前掛好(lib.sh 的維護約束)。
chain_exit_trap 'unpause_bf_containers'

echo "pause backfill containers (if any)"
pause_bf_containers

FREE2="$(free_gb)"
if ! disk_ok "$FREE2"; then
  echo "disk free ${FREE2}G < ${MIN_FREE_GB}G after taking the lock — refuse to start the window"
  exit 0
fi

cd "$REPO"

# 上一次執行已經成功的步驟不重做(步驟 1 與 3 都是長跑)。FORCE=1 全部重來。
if [ "${FORCE:-0}" != "1" ] && [ -s "$STATE_FILE" ]; then
  while IFS='=' read -r k v; do
    case "$k=$v" in
      step1=ok) STEP1_STATUS="ok-prior" ;;
      step2=ok) STEP2_STATUS="ok-prior" ;;
      step3=ok) STEP3_STATUS="ok-prior" ;;
      step4=ok) STEP4_STATUS="ok-prior" ;;
    esac
  done < "$STATE_FILE"
  echo "resuming from ${STATE_FILE}: step1=${STEP1_STATUS:-pending} step2=${STEP2_STATUS:-pending} step3=${STEP3_STATUS:-pending} step4=${STEP4_STATUS:-pending}"
fi

# ===== step 1: quotes gap 2026-07-16..08-19 =====
# 一切的前提:那 25 個日期落在步驟 2 與步驟 3 讀取的 20 交易日窗裡面。
quotes_market_counts() {
  db_col "SELECT p.date || ' ' || COALESCE(s.market, '__null__') || ' rows=' || COUNT(*)
          FROM daily_prices p LEFT JOIN stocks s ON s.id = p.stock_id
          WHERE p.date BETWEEN '${QUOTES_FROM}' AND '${QUOTES_TO}'
          GROUP BY p.date, COALESCE(s.market, '__null__')
          ORDER BY p.date, 1"
}

quotes_total_rows() {
  db_col "SELECT COUNT(*) FROM daily_prices
          WHERE date BETWEEN '${QUOTES_FROM}' AND '${QUOTES_TO}'"
}

if [ "$STEP1_STATUS" = "ok-prior" ]; then
  skip_step step1 "already ok in ${STATE_FILE} (FORCE=1 to redo)"
else
  # --days 從**執行日**推導,絕不寫死(見檔頭的推導說明)。
  #   N = weekdays(REPAIR_QUOTES_FROM .. 今天) + REPAIR_QUOTES_PAD
  # backfill() 從今天往回走日曆日、週末不消耗額度,只有交易日讓 done 前進;
  # 平日數 >= 交易日數,所以這個 N 必然走得回 QUOTES_FROM。PAD 是餘裕不是需求,
  # 而多走的那幾格都是已完整的舊日期,在迴圈裡直接 continue、不發任何請求。
  WEEKDAYS="$(weekdays_since "$QUOTES_FROM")"
  case "$WEEKDAYS" in
    ''|*[!0-9]*) fail_step step1 1 "could not derive --days: weekdays_since ${QUOTES_FROM} returned '${WEEKDAYS}'" ;;
  esac
  QUOTES_DAYS=$(( WEEKDAYS + QUOTES_PAD ))
  echo "--- step1 quotes gap ${QUOTES_FROM}..${QUOTES_TO}"
  echo "    --days ${QUOTES_DAYS} = ${WEEKDAYS} weekdays from ${QUOTES_FROM} to $(taipei_date +%Y-%m-%d) + ${QUOTES_PAD} pad"
  echo "    (weekdays >= trading days, and only trading days spend backfill()'s budget,"
  echo "     so this always reaches back to ${QUOTES_FROM} however far the run date moves)"

  echo "    before, per market:"
  quotes_market_counts | sed 's/^/      /'
  BEFORE_ROWS="$(quotes_total_rows)"
  echo "    before total rows in range: ${BEFORE_ROWS}"

  START=$(date +%s)
  set +e
  radar backfill --days "$QUOTES_DAYS" --datasets quotes
  rc=$?
  set -e
  ELAPSED=$(( $(date +%s) - START ))
  if [ "$rc" -ne 0 ]; then
    fail_step step1 "$rc" "radar backfill --days ${QUOTES_DAYS} --datasets quotes after ${ELAPSED}s"
  fi

  echo "    after, per market:"
  quotes_market_counts | sed 's/^/      /'
  AFTER_ROWS="$(quotes_total_rows)"
  DELTA=$(( AFTER_ROWS - BEFORE_ROWS ))
  echo "    after total rows in range: ${AFTER_ROWS} (delta ${DELTA}; expected about ${QUOTES_EXPECTED_DELTA})"
  STEP1_STATUS="ok"
  persist_state
  note "step1 ok (+${DELTA} rows, ${ELAPSED}s)"
fi

# ===== step 2: ledger catch-up (branch_pit_stats) =====
if ! gate_clear "step1" "$STEP1_STATUS"; then
  skip_step step2 "step1 did not clear"
elif [ "$STEP2_STATUS" = "ok-prior" ]; then
  skip_step step2 "already ok in ${STATE_FILE} (FORCE=1 to redo)"
elif [ "${#LEDGER_DATES[@]}" -eq 0 ]; then
  skip_step step2 "ledger as-of list is empty (REPAIR_LEDGER_DATES overrode it with nothing)"
else
  echo "--- step2 ledger catch-up: ${LEDGER_DATES[*]}"
  # 全部先驗完再開跑:CLI 本來就會對非交易日 fail closed,但補到第三個日期才死在
  # 容器裡,訊息遠不如在這裡擋下來清楚。
  for d in "${LEDGER_DATES[@]}"; do
    case "$d" in
      [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) ;;
      *) fail_step step2 1 "as-of '${d}' is not YYYY-MM-DD" ;;
    esac
    n="$(db_col "SELECT COUNT(*) FROM daily_prices WHERE date = '${d}'")"
    case "$n" in
      ''|*[!0-9]*) fail_step step2 1 "could not verify trading day ${d}: query returned '${n}'" ;;
    esac
    if [ "$n" -eq 0 ]; then
      fail_step step2 1 "as-of ${d} is not a market trading day (no daily_prices rows)"
    fi
    have="$(db_col "SELECT COUNT(*) FROM branch_pit_stats WHERE as_of = '${d}'")"
    echo "    ${d}: trading day ok (${n} price rows), branch_pit_stats rows now=${have:-?}"
  done

  START=$(date +%s)
  for d in "${LEDGER_DATES[@]}"; do
    set +e
    radar branch-point-in-time-persist --as-of "$d" --window-days "$LEDGER_WINDOW_DAYS"
    rc=$?
    set -e
    if [ "$rc" -ne 0 ]; then
      fail_step step2 "$rc" "branch-point-in-time-persist --as-of ${d}"
    fi
    after="$(db_col "SELECT COUNT(*) FROM branch_pit_stats WHERE as_of = '${d}'")"
    echo "    ${d}: branch_pit_stats rows after=${after:-?}"
  done
  ELAPSED=$(( $(date +%s) - START ))
  STEP2_STATUS="ok"
  persist_state
  note "step2 ok (${#LEDGER_DATES[@]} as-of dates, ${ELAPSED}s)"
fi

# ===== step 3: compute-performance --all =====
# 以步驟 1 為前提:前瞻報酬是從被修復的收盤價讀出來的。
perf_sums() {
  db_col "SELECT printf('fwd_20d_sum=%.6f fwd_5d_sum=%.6f rows=%d with_fwd_20d=%d',
            COALESCE(SUM(fwd_20d), 0), COALESCE(SUM(fwd_5d), 0), COUNT(*),
            SUM(CASE WHEN fwd_20d IS NOT NULL THEN 1 ELSE 0 END))
          FROM daily_scores"
}

if ! gate_clear "step2" "$STEP2_STATUS"; then
  skip_step step3 "step2 did not clear"
elif [ "$STEP3_STATUS" = "ok-prior" ]; then
  skip_step step3 "already ok in ${STATE_FILE} (FORCE=1 to redo)"
else
  echo "--- step3 compute-performance --all"
  PERF_BEFORE="$(perf_sums)"
  echo "    before: ${PERF_BEFORE}"
  START=$(date +%s)
  set +e
  radar compute-performance --all
  rc=$?
  set -e
  ELAPSED=$(( $(date +%s) - START ))
  if [ "$rc" -ne 0 ]; then
    fail_step step3 "$rc" "radar compute-performance --all after ${ELAPSED}s"
  fi
  PERF_AFTER="$(perf_sums)"
  echo "    after:  ${PERF_AFTER}"
  STEP3_STATUS="ok"
  persist_state
  note "step3 ok (${ELAPSED}s)"
fi

# ===== step 4: margin gap 2026-09-02 =====
margin_counts() {
  db_col "SELECT COALESCE(s.market, '__null__') || ' rows=' || COUNT(*)
          FROM daily_margins m LEFT JOIN stocks s ON s.id = m.stock_id
          WHERE m.date = '${MARGIN_DATE}'
          GROUP BY COALESCE(s.market, '__null__')
          ORDER BY 1"
}

# 21:15–23:30 是 daily-margin.sh 寫同一張表的時段。前置條件的安靜窗平日已經涵蓋
# 2115..2330,但前三步會跑掉一個多小時——**開跑時合格不代表跑到這裡還合格**,
# 所以這裡重新讀一次時鐘。這是本步驟自己的硬性拒絕,不是重複的守衛。
NOW_HHMM=$((10#$(TZ=Asia/Taipei date +%H%M)))
if ! gate_clear "step3" "$STEP3_STATUS"; then
  skip_step step4 "step3 did not clear"
elif [ "$NOW_HHMM" -ge "$MARGIN_EXCLUDE_FROM" ] && [ "$NOW_HHMM" -le "$MARGIN_EXCLUDE_TO" ]; then
  skip_step step4 "clock is ${NOW_HHMM}, inside the ${MARGIN_EXCLUDE_FROM}-${MARGIN_EXCLUDE_TO} window where daily-margin.sh writes daily_margins"
elif [ "$STEP4_STATUS" = "ok-prior" ]; then
  skip_step step4 "already ok in ${STATE_FILE} (FORCE=1 to redo)"
else
  echo "--- step4 margin gap ${MARGIN_DATE}"
  # backfill_margin 的 days 數的是 daily_prices 的交易日(由新到舊),所以涵蓋
  # MARGIN_DATE 需要的 days = 「>= MARGIN_DATE 的相異交易日數」,同樣由資料庫推導。
  MARGIN_DAYS="$(db_col "SELECT COUNT(DISTINCT date) FROM daily_prices WHERE date >= '${MARGIN_DATE}'")"
  case "$MARGIN_DAYS" in
    ''|*[!0-9]*) fail_step step4 1 "could not derive --days: daily_prices query returned '${MARGIN_DAYS}'" ;;
  esac
  if [ "$MARGIN_DAYS" -eq 0 ]; then
    fail_step step4 1 "${MARGIN_DATE} is not a market trading day (no daily_prices rows)"
  fi
  echo "    --days ${MARGIN_DAYS} = distinct daily_prices dates >= ${MARGIN_DATE}"
  echo "    before, per market:"
  margin_counts | sed 's/^/      /'
  START=$(date +%s)
  set +e
  radar backfill-margin --days "$MARGIN_DAYS" --sleep 0.4
  rc=$?
  set -e
  ELAPSED=$(( $(date +%s) - START ))
  if [ "$rc" -ne 0 ]; then
    fail_step step4 "$rc" "radar backfill-margin --days ${MARGIN_DAYS} after ${ELAPSED}s"
  fi
  echo "    after, per market:"
  margin_counts | sed 's/^/      /'
  STEP4_STATUS="ok"
  persist_state
  note "step4 ok (${ELAPSED}s)"
fi

persist_state

# 完成旗標只在**四步全部成功**時才寫。步驟 4 被 21:15–23:30 擋掉、或任何一步被
# 略過,都代表還有事情沒做完:留著不寫旗標,下一次呼叫才會接著補(state 檔已經
# 記住哪幾步成功,不會重做長跑的步驟 1 與 3)。
ALL_OK=1
for s in "$STEP1_STATUS" "$STEP2_STATUS" "$STEP3_STATUS" "$STEP4_STATUS"; do
  case "$s" in
    ok|ok-prior) ;;
    *) ALL_OK=0 ;;
  esac
done
if [ "$ALL_OK" -eq 1 ]; then
  : > "$DONE_FLAG"
else
  echo "not all four steps are ok — leaving ${DONE_FLAG} unwritten so a re-run finishes the rest"
fi

echo "=== repair-window done $(taipei_date -Is) — ${SUMMARY}"
echo "not exported, not deployed: publishing is a separate decision; the next scheduled round picks the repaired data up"
notify_ok "正式修復窗完成：${SUMMARY}；未 export／未 deploy，下一輪排程會自行帶上線"
