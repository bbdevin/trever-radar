#!/usr/bin/env bash
# 全市場權證分點歷史回補(docs/30 WP-B6 Phase 2)— 一次一塊、可續跑、對排程讓路。
#
# 目標深度 **120 個交易日**(Fable 5.1,2026-09-08),分兩段:先 90,收到完成
# 通知後改 120。分段不是保守,而是每段結束都是一個有量測撐著的檢查點;調高深度
# 零成本:CLI 對每個「日期＋市場」寫獨立的 atomic state 檔,已完成的日期在下一次
# 呼叫只被判定為 complete,不花任何請求。
#
# ── 容量:先前的估計錯了約 3.7 倍,以下是實測 ──────────────────────────────
# 2026-09-04 一塊 30 分鐘的監督執行(1,465 個標的、0 失敗、1,802 秒)量到:
#     8.34 列/標的、127.7 bytes/列(邏輯)、126.7(含 WAL 落地)、1.23 秒/標的
# 換算全市場 17,979 標的/日 → **約 19 MB/交易日**,故 90 日約 1.7 GB、
# 120 日約 2.3 GB;當時可用磁碟 6.6 GB。
#
# 舊估計(120 日 8.4 GB、90 日 6.3 GB、結論「120 日放不下」)錯在把**股票**分點
# 高成交額池的 23.6 列/標的套到權證上——權證每個標的的分點列少得多。這段留著當
# 紀錄:**借來的比率不是量測值**,而它差點讓一個放得下的工作被砍掉。
#
# 因此真正的限制不是磁碟而是**時間**,且時間是「容量減流入」:每個交易日新增一個
# 日期插隊,每週約 27 小時在原地踏步;淨進度約 13.8 日/週(mid 槽位關掉時)。
#
# 單寫者 SQLite 的 VPS 寫滿磁碟是全面停擺不是變慢,所以 MIN_FREE_GB 仍在,只是它
# 現在保護的是 weekly-backup.sh 的 gzip 空間,不是這份工作自己的需求。
#
# ── 讓路而不是排隊(本腳本存在的主要理由)────────────────────────────────
# 一次呼叫只做**一塊**,塊的長度由「距離下一輪排程還有多久」決定:
#   BUDGET = minutes_until_next_scheduled_writer - WARRANT_SAFETY_MINUTES
# 「下一輪排程」同時涵蓋安靜窗(daily/deep/週末備份)**與 mid-publish 的
# 03/09/12/20 四輪——後者不在安靜窗表裡,但一樣會因為本腳本握著 DB 鎖而被略過。
# (mid-publish 那四輪只在真的有 radar-bf-* 容器時才保留;沒有容器時那一輪自己就是
# noop,見下方 bf_container_running 的判斷。)
# 再以 WARRANT_MAX_MINUTES 封頂,並以 --max-minutes 傳給 CLI。
# 因為塊長是從剩餘時間**推導**出來的,它在定義上不可能跑進下一輪排程裡。
#
# 為什麼絕對時刻上界(例如「17:00 以前都可以開跑」)不等價:絕對上界只回答
# 「現在幾點」,不回答「還剩多久」,所以它允許在 17:38 開一個 20 分鐘的塊——
# 兩分鐘後 17:40 的分點輪就撞上來。2026-09-03 就是這樣出事的,
# adjust-backfill.sh 的檔頭也寫了同一條規則:守衛是「剩餘時間 > 預估耗時」,
# 不是絕對上界。剩下的時間短到不值得為它做一次 pause/unpause(低於
# WARRANT_MIN_CHUNK_MINUTES)就直接略過——略過是正常結果,不是失敗。
#
# ── 鎖 ──────────────────────────────────────────────────────────────────
#   1. /tmp/radar-db.lock(fd 9):**先搶鎖再 pause**,順序不可對調。本腳本會被
#      每隔幾分鐘的迴圈重複呼叫,絕大多數呼叫都會在這裡略過;若先 pause,11 小時
#      的視窗會產生約 220 次無謂的 pause/unpause,還會提高撞上 guard 與 cleanup
#      之間 state-cache race 的機率(2026-08-27 17:35 曾發生)。
#   2. /tmp/radar-branch-source.lock(fd 8):MoneyDJ/Fubon 鏡像是共用外部來源,
#      與 SQLite 寫鎖無關;lib.sh 明講股票分點與權證分點兩支工作絕不可交錯發請求。
#      這裡**刻意不用 acquire_branch_source_lock**:那個函式搶不到時會
#      notify_skip + exit 0,而本腳本被迴圈每 3 分鐘呼叫一次,搶不到是常態,
#      用它等於每 3 分鐘轟一則 ntfy。改成就地 flock -n,印出原因、安靜 exit 0;
#      鎖語意(同一把 /tmp/radar-branch-source.lock、fd 8、非阻塞)逐字相同。
#
# ── 怎麼驅動 ────────────────────────────────────────────────────────────
# 和 adjust-backfill.sh 一樣,本腳本**刻意不在 crontab 裡**,也不要在沒有維運者
# 決定的情況下加進去(排程變更是高風險正式變更,docs/30 §6.2)。迴圈跑:
#     while bash vps/scripts/warrant-backfill.sh; do sleep 180; done
# 任何一次略過都回 0,只有真正的失敗才回非 0。
#
# ── 環境變數 ────────────────────────────────────────────────────────────
#   WARRANT_DAYS=90            深度(交易日);收到 90 日完成通知後改 120
#   WARRANT_CAP=30000          單日目標數安全上限(超過即 fail closed,不截斷)
#   WARRANT_SLEEP=1.0          請求間隔。1.0 是實測值(1.23 秒/標的 = 1.0 sleep
#                              + 0.23 實際工作),**不要再往下調**:這是本專案對
#                              那些免費鏡像最重的一次持續負載,被擋掉會連日更的
#                              分點池一起賠進去
#   WARRANT_SAFETY_MINUTES=15  從「距下一輪還有多久」扣掉的安全邊際
#   WARRANT_MIN_CHUNK_MINUTES=20  低於此值不值得 pause/unpause,直接略過
#   WARRANT_MAX_MINUTES=240    單塊上限
#   WARRANT_STATE_BASE=data/warrant-branch-backfill.json
#                              base path;CLI 在旁邊寫 <stem>-<date>-<market>.json。
#                              **相對路徑是相對於容器的工作目錄 /app/pipeline**,
#                              所以這個預設值落在 `pipeline/data/`(不是 repo 根的
#                              `data/`,原註解寫錯了)。該路徑同樣有掛載,續跑正常;
#                              但傳絕對路徑時務必是掛載點下的容器內路徑
#                              (/app/pipeline、/app/data、/app/web/public/data),
#                              主機路徑(例如 /home/xxx/…)會寫進容器內的匿名層,
#                              --rm 之後直接消失(2026-09-08 已有一份報表這樣不見)。
#   WARRANT_MIN_AGE_DAYS=1     不抓比這更新的日期:分點頁解析出零列一律是
#                              NoDataError,分不出「當天真的沒成交」與「鏡像還沒
#                              發布」,後者會被記成永不重試的 empty
#   WARRANT_MEASURE_LOG=$HOME/warrant-backfill-measure.log
#   WARRANT_PAUSE_FILE=/tmp/radar-warrant-backfill.pause
#                              維運者暫停檔:存在就直接略過(讓人工作業搶白天空檔,
#                              不必砍掉驅動迴圈)
#   MIN_FREE_GB=3              本腳本刻意低於他處的 4:這份工作的目的就是吃磁碟,
#                              但必須在遠早於 ENOSPC 之前停手。地板真正保護的是
#                              weekly-backup.sh——它握著鎖把約 6.8 GB 的 DB gzip
#                              到本機磁碟,2 GB 左右就開始失敗。
#   MIN_MEM_MB=900
source "$(dirname "$0")/lib.sh"

FLAG="${MID_PUBLISH_FLAG:-/tmp/radar-mid-publish.flag}"
DAYS="${WARRANT_DAYS:-90}"
CAP="${WARRANT_CAP:-30000}"
SLEEP="${WARRANT_SLEEP:-1.0}"
SAFETY_MINUTES="${WARRANT_SAFETY_MINUTES:-15}"
MIN_CHUNK_MINUTES="${WARRANT_MIN_CHUNK_MINUTES:-20}"
MAX_MINUTES="${WARRANT_MAX_MINUTES:-240}"
STATE_BASE="${WARRANT_STATE_BASE:-data/warrant-branch-backfill.json}"
MIN_AGE_DAYS="${WARRANT_MIN_AGE_DAYS:-1}"
MEASURE_LOG="${WARRANT_MEASURE_LOG:-$HOME/warrant-backfill-measure.log}"
PAUSE_FILE="${WARRANT_PAUSE_FILE:-/tmp/radar-warrant-backfill.pause}"
RUN_LOG="${WARRANT_RUN_LOG:-/tmp/radar-warrant-backfill.run.log}"
# 吞吐塌陷門檻:實測基準 12,223 列 / 1,802 秒 = 6.8 列/秒、1,465 抓取 / 1,802 秒
# = 0.81 抓取/秒。低於下列值代表鏡像在餵錯誤頁／佔位頁(解析成零列 → NoDataError
# → 永久 empty,而整塊仍會回報成功),必須停手而不是繼續把資料庫寫成空的。
THROUGHPUT_MIN_ELAPSED="${WARRANT_THROUGHPUT_MIN_ELAPSED:-600}"
MIN_ROWS_PER_SEC="${WARRANT_MIN_ROWS_PER_SEC:-1.5}"
MIN_FREE_GB="${MIN_FREE_GB:-3}"
MIN_MEM_MB="${MIN_MEM_MB:-900}"
MARKET="all"
DONE_FLAG="$HOME/.warrant-backfill.done-${DAYS}d"

# 失敗一律自己處理(每個失敗點都要 unpause 並留住 state),不靠 lib 的 ERR trap
# 高優先通知,免得同一次失敗發兩則。
trap - ERR

# 串接而非覆蓋既有 EXIT trap(lib.sh 的金鑰暫存檔清理是在第一次呼叫 radar 時
# 才掛上去的,它自己也會串在我們前面;這裡照同樣規則處理反向情況)。
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

# page_count * page_size = SQLite 主檔的邏輯大小(不含 WAL)。
db_logical_bytes() {
  db_col "SELECT (SELECT page_count FROM pragma_page_count()) * (SELECT page_size FROM pragma_page_size())"
}

# 實際落在磁碟上的位元組(含 -wal / -shm)。維運者真正受限的是這個數字,
# page_count 在 checkpoint 之前會低估。
db_on_disk_bytes() {
  du -cb "$REPO/data/radar.db" "$REPO/data/radar.db-wal" "$REPO/data/radar.db-shm" 2>/dev/null \
    | awk 'END { print $1+0 }'
}

# 分點列數。權證分點與股票分點共用 branch_trades(權證的 stock_id 是權證代號),
# 但量測期間 db lock 在我們手上、bf 容器也被 pause,除了本塊之外沒有其他寫者,
# 所以總列數的差額就是本塊寫進去的權證分點列數——不必為了分辨而付一次
# JOIN warrants 全表掃描的代價。
branch_rows() {
  db_col "SELECT COUNT(*) FROM branch_trades"
}

echo "=== warrant-backfill start $(taipei_date -Is) days=${DAYS} market=${MARKET} state=${STATE_BASE} ==="

if [ -f "$PAUSE_FILE" ]; then
  echo "operator pause file ${PAUSE_FILE} present — skip (rm it to resume)"
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

if [ -f "$DONE_FLAG" ]; then
  echo "already complete for days=${DAYS} (${DONE_FLAG}) — skip; raise WARRANT_DAYS to go deeper"
  exit 0
fi

FREE="$(free_gb)"
if ! disk_ok "$FREE"; then
  echo "disk free ${FREE}G < ${MIN_FREE_GB}G — skip (refusing to start a chunk whose whole job is eating disk)"
  exit 0
fi

MEM="$(mem_available_mb)"
if [ "${MEM:-0}" -lt "$MIN_MEM_MB" ]; then
  echo "MemAvailable ${MEM}MB < ${MIN_MEM_MB}MB — skip"
  exit 0
fi

# 時間守衛:塊長 = 距下一輪排程的剩餘時間 - 安全邊際,再封頂。
# 用 minutes_until_next_scheduled_writer 而不是 minutes_until_quiet_window:
# mid-backfill-publish 的 03/09/12/20 四輪**不在**安靜窗表裡(quiet_window_at 的
# 註解自己寫著那四輪由 mid flag 另擋),而 mid-backfill-publish.sh 開頭是
# `fuser /tmp/radar-db.lock` → 略過,所以本腳本只要握著鎖跨過整點,那一輪就
# 靜默消失。只問安靜窗的話,02:31 起跑一個 240 分鐘的塊會一口氣吃掉 03:00;
# 19:31 起跑 30 分鐘會吃掉 20:00。一支要跑數週的爬蟲,那是數十次被吃掉的發布。
#
# 但那四輪只有在真的有事可做時才值得保留:mid-backfill-publish.sh 現在開頭就是
# 「沒有 radar-bf-* 容器 → noop」直接離開(歷史回補容器已於 2026-09-07 跑完),
# 而保留這四輪要價 31% 的淨爬取進度。所以在消費端(只在這裡,不動 lib.sh)先問
# 同一個述詞、同一份 BF_CONTAINERS 清單:沒有容器就把時段清空,`mid_publish_at`
# 迭代空清單等於永不成立。這是每次呼叫重新評估的,將來只要再有回補容器起來,
# 保留就自動恢復,不會漂移成兩份真相。
if ! bf_container_running; then
  echo "no radar-bf-* container running — mid-publish is a noop this round; not reserving 03/09/12/20"
  MID_PUBLISH_HOURS=""
fi

UNTIL="$(minutes_until_next_scheduled_writer)"
BUDGET=$(( UNTIL - SAFETY_MINUTES ))
if [ "$BUDGET" -lt "$MIN_CHUNK_MINUTES" ]; then
  echo "next scheduled writer in ${UNTIL}min; budget ${BUDGET}min < ${MIN_CHUNK_MINUTES}min — skip (too short to be worth a pause/unpause cycle)"
  exit 0
fi
if [ "$BUDGET" -gt "$MAX_MINUTES" ]; then
  BUDGET="$MAX_MINUTES"
fi
echo "next scheduled writer in ${UNTIL}min; chunk budget ${BUDGET}min (safety ${SAFETY_MINUTES}min, cap ${MAX_MINUTES}min)"

# 讓路、不排隊:搶不到就走,絕不 block 等鎖(先搶鎖、後 pause,見檔頭)。
exec 9>/tmp/radar-db.lock
if ! flock -n 9; then
  echo "radar-db.lock held — skip (a scheduled round or another writer is running)"
  exit 0
fi

# 分點來源鎖:就地取,不用 acquire_branch_source_lock(見檔頭:那個函式會
# notify_skip,而本腳本搶不到是常態,會變成每 3 分鐘一則 ntfy)。
exec 8>/tmp/radar-branch-source.lock
if ! flock -n 8; then
  echo "radar-branch-source.lock held — skip (the stock branch backfill is hitting the same MoneyDJ mirrors)"
  exit 0
fi

# EXIT trap 必須在 pause 之前、也在第一次呼叫 radar 之前掛好(lib.sh 的維護約束)。
chain_exit_trap 'unpause_bf_containers'

echo "pause backfill (if any); mem=${MEM}MB free_disk=${FREE}G"
pause_bf_containers

# pause 與搶鎖之間磁碟可能已經被別的工作吃掉。
FREE2="$(free_gb)"
if ! disk_ok "$FREE2"; then
  echo "disk free ${FREE2}G < ${MIN_FREE_GB}G after taking the lock — refuse to start a chunk"
  exit 0
fi

cd "$REPO"

# 量測(本次分段跑的重點):塊前／塊後各取一次,算出這一塊真實的 bytes/row。
ROWS_BEFORE="$(branch_rows)"
DB_BEFORE="$(db_logical_bytes)"
DISK_BEFORE="$(db_on_disk_bytes)"
echo "before: branch_rows=${ROWS_BEFORE} db_logical_bytes=${DB_BEFORE} db_on_disk_bytes=${DISK_BEFORE} free=${FREE2}G"

START=$(date +%s)
set +e
# stdout 另存一份:吞吐守衛需要 CLI 自己數的 fetched=(列數差額看不見「抓了很多次
# 但每次都零列」這種塌陷)。rc 取 PIPESTATUS[0],離開碼語意與加 tee 之前逐字相同。
radar backfill-warrant-branches \
  --market "$MARKET" \
  --top "$CAP" \
  --days "$DAYS" \
  --sleep "$SLEEP" \
  --min-age-days "$MIN_AGE_DAYS" \
  --max-minutes "$BUDGET" \
  --state-file "$STATE_BASE" | tee "$RUN_LOG"
rc=${PIPESTATUS[0]}
set -e
ELAPSED=$(( $(date +%s) - START ))
# 摘要行與各日進度行都印 fetched=<n>(皆為累計),取最後一個即整塊的總數。
# (pipefail 生效中,抓不到就是 grep 回 1 → 整條管線非零,所以一律 `|| true`。)
FETCHED="$(grep -oE 'fetched=[0-9]+' "$RUN_LOG" 2>/dev/null | tail -n 1 | cut -d= -f2 || true)"
FETCHED="${FETCHED:-0}"
EMPTY="$(grep -oE 'empty=[0-9]+' "$RUN_LOG" 2>/dev/null | tail -n 1 | cut -d= -f2 || true)"
EMPTY="${EMPTY:-0}"

# CLI 的離開碼語意(見 cli.py 的 `cmd_backfill_warrant_branches`):
#   rc=0  → 這個 days 深度內每一個日期都已完整。
#   rc=75 → 乾淨停下、可續跑(我們自己的 --max-minutes 到了,或還有日期沒跑完)。
#           **這是成功**,不是失敗:下一次呼叫從 state 接著跑。
#   其他非零 → 真失敗(連續抓取失敗、python traceback、docker 失敗、目標數
#           超過 --top 的 fail-closed RuntimeError)。
#
# 這裡刻意用離開碼而不是比對 log 文字。先前兩者共用 exit 1,唯一的分辨方式是
# grep `stopped` 的字面訊息——把這支 shell 綁在一個 Python f-string 上,改一個
# 字就靜默壞掉,而且壞的方向是把真失敗當成正常繼續跑。cli.py 已改為回 75
# (沿用該檔 `cmd_import_daily` 對「預期內的不完整」既有的慣例)。
VERDICT="unknown"
if [ "$rc" -eq 0 ]; then
  VERDICT="complete"
elif [ "$rc" -eq 75 ]; then
  VERDICT="clean-stop"
else
  VERDICT="failed"
fi

ROWS_AFTER="$(branch_rows)"
DB_AFTER="$(db_logical_bytes)"
DISK_AFTER="$(db_on_disk_bytes)"
FREE3="$(free_gb)"

ROWS_DELTA=$(( ROWS_AFTER - ROWS_BEFORE ))
DB_DELTA=$(( DB_AFTER - DB_BEFORE ))
DISK_DELTA=$(( DISK_AFTER - DISK_BEFORE ))
FREE_DELTA="$(awk -v a="$FREE2" -v b="$FREE3" 'BEGIN { printf "%.1f", b - a }')"
if [ "$ROWS_DELTA" -gt 0 ]; then
  BYTES_PER_ROW="$(awk -v d="$DB_DELTA" -v r="$ROWS_DELTA" 'BEGIN { printf "%.1f", d / r }')"
  DISK_BYTES_PER_ROW="$(awk -v d="$DISK_DELTA" -v r="$ROWS_DELTA" 'BEGIN { printf "%.1f", d / r }')"
else
  BYTES_PER_ROW="n/a"
  DISK_BYTES_PER_ROW="n/a"
fi

echo "after: branch_rows=${ROWS_AFTER} (+${ROWS_DELTA}) db_logical_bytes=${DB_AFTER} (+${DB_DELTA}) db_on_disk_bytes=${DISK_AFTER} (+${DISK_DELTA})"
echo "chunk ${VERDICT}: rc=${rc}, ${ELAPSED}s, budget=${BUDGET}min, days=${DAYS}, fetched=${FETCHED}, empty=${EMPTY}"
echo "disk free ${FREE2}G → ${FREE3}G (${FREE_DELTA}G); bytes/row logical=${BYTES_PER_ROW} on-disk=${DISK_BYTES_PER_ROW}"

if [ ! -f "$MEASURE_LOG" ]; then
  printf '# ts\tdays\tbudget_min\telapsed_s\trc\tverdict\trows_before\trows_after\trows_delta\tdb_before\tdb_after\tdb_delta\tdisk_delta\tfree_before_g\tfree_after_g\tbytes_per_row\tdisk_bytes_per_row\n' \
    > "$MEASURE_LOG"
fi
printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
  "$(taipei_date -Is)" "$DAYS" "$BUDGET" "$ELAPSED" "$rc" "$VERDICT" \
  "$ROWS_BEFORE" "$ROWS_AFTER" "$ROWS_DELTA" \
  "$DB_BEFORE" "$DB_AFTER" "$DB_DELTA" "$DISK_DELTA" \
  "$FREE2" "$FREE3" "$BYTES_PER_ROW" "$DISK_BYTES_PER_ROW" >> "$MEASURE_LOG"
echo "measurement appended to ${MEASURE_LOG}"

# 磁碟地板:跌破就大聲講並發高優先通知。下一次呼叫會在開頭的 disk 檢查再擋一次,
# 所以「拒絕再開新塊」是自動的,這裡負責讓維運者當下就知道。
if ! disk_ok "$FREE3"; then
  echo "!!! disk free ${FREE3}G < ${MIN_FREE_GB}G AFTER this chunk — refusing to start further chunks"
  notify "權證分點回補：本塊結束後可用磁碟僅剩 ${FREE3}G（地板 ${MIN_FREE_GB}G），已停止再開新塊，請先清理磁碟或降低 WARRANT_DAYS" high "失敗"
fi

# 吞吐塌陷守衛:鏡像改餵錯誤頁／佔位頁時,每一個目標都解析成零列 → NoDataError
# → 被記成**永久** empty,而這一塊仍然會乾淨地回報成功。列數與抓取數是唯一能當場
# 看出「還在跑但什麼都沒收到」的量。太短的塊不判(暖機與純續跑掃描會失真)。
# 判準**只用 rows/s**,刻意不加 fetch/s。fetch/s 要從 CLI stdout 解析 `fetched=`,
# 那是把控制路徑綁在一個 Python 格式字串上——本檔上面的離開碼註解、以及
# `4141a88` 那次修正,講的都是同一件事;而這裡的失敗方向更差:欄位一改名它就
# 靜默變成 0,**誤判塌陷、自己建暫停檔把爬蟲停掉**。
# 它也沒多給資訊:鏡像節流 → 抓取變慢 → 列數同步變少;鏡像餵佔位頁 → fetched
# 照增但列數不增。兩種故障 rows/s 都看得見,而它來自資料庫列數,不依賴任何字串。
# fetched / empty 仍然印出來給人看,只是不參與判決。
if [ "$ELAPSED" -gt "$THROUGHPUT_MIN_ELAPSED" ] && awk \
    -v rows="$ROWS_DELTA" -v e="$ELAPSED" -v minr="$MIN_ROWS_PER_SEC" \
    'BEGIN { exit !(rows / e < minr) }'; then
  RPS="$(awk -v r="$ROWS_DELTA" -v e="$ELAPSED" 'BEGIN { printf "%.2f", r / e }')"
  echo "!!! throughput collapse: ${RPS} rows/s (floor ${MIN_ROWS_PER_SEC}) over ${ELAPSED}s; fetched=${FETCHED} empty=${EMPTY}"
  : > "$PAUSE_FILE"
  notify "權證分點回補：吞吐塌陷（${RPS} 列/秒，基準 6.8;本塊 fetched=${FETCHED} empty=${EMPTY}），疑似鏡像回錯誤頁被記成永久 empty；已建立暫停檔 ${PAUSE_FILE}，不再開新塊，請人工確認來源後刪除該檔" high "失敗"
fi

case "$VERDICT" in
  complete)
    echo "all done — every date within days=${DAYS} is complete"
    if [ ! -f "$DONE_FLAG" ]; then
      notify_ok "權證分點回補完成：深度 ${DAYS} 個交易日、全市場（上市＋上櫃）；bytes/row 實測 ${BYTES_PER_ROW}，可據此決定下一段深度"
      : > "$DONE_FLAG"
    fi
    ;;
  clean-stop)
    # 乾淨停下不是失敗:state 檔留著,下一次呼叫接著跑。不發高優先通知。
    echo "stopped cleanly and incomplete — next invocation resumes from the per-date state files"
    ;;
  *)
    echo "chunk FAILED rc=${rc} after ${ELAPSED}s — state files left intact for retry"
    notify "權證分點回補分塊失敗（碼 ${rc}，${ELAPSED} 秒，深度 ${DAYS} 日），state 保留待重試" high "失敗"
    exit "$rc"
    ;;
esac

echo "=== warrant-backfill done $(taipei_date -Is) ==="
