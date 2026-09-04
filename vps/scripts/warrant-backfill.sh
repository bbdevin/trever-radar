#!/usr/bin/env bash
# 全市場權證分點歷史回補(docs/30 WP-B6 Phase 2)— 一次一塊、可續跑、對排程讓路。
#
# 使用者決定的目標深度是 **90 個交易日**,但不能一口氣跑。2026-09-04 在正式機
# 實測:可用磁碟 7.52 GB(8,070,471,680 bytes)。120 日的估算需求約 8.4 GB
# (由「每列上界約 156 bytes」推得,而那個上界是從另一張表推論出來的,不是權證
# 分點實測),因此 120 日在現有磁碟上根本放不下;90 日約 6.3 GB,而仍在跑的
# 490 日股票分點回補還要再吃約 0.6 GB,只剩約 0.6 GB 餘裕——而這份工作連續抓
# 要約 20 天,只塞平日 11.5 小時空檔的話約 41 天,期間日常排程還在持續寫入。
# 單寫者 SQLite 的 VPS 一旦寫滿磁碟是全面停擺,不是變慢。
#
# 所以深度是參數,分三段跑:WARRANT_DAYS=30 → 60 → 90。
#   * 第一段(30 日)存在的理由不是「保守」,是**量測**:它會把「推論出來的
#     bytes/row 上界」換成權證分點自己的實測值,寫進 WARRANT_MEASURE_LOG。
#     若實測值比上界低,90 日放得下;若更高,維運者在吃掉約 2 GB 的時候就知道,
#     而不是在第 35 天才發現。
#   * 讀完量測日誌之後,維運者把 WARRANT_DAYS 調到 60、再調到 90 即可。
#     調高是安全的:CLI 對每個「日期＋市場」寫一個獨立的 atomic state 檔,
#     已經跑完的日期在下一次呼叫只會被判定為 complete,不花任何請求。
#
# ── 讓路而不是排隊(本腳本存在的主要理由)────────────────────────────────
# 一次呼叫只做**一塊**,塊的長度由「距離下一輪排程還有多久」決定:
#   BUDGET = minutes_until_quiet_window - WARRANT_SAFETY_MINUTES
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
#   WARRANT_DAYS=30            深度(交易日);讀完量測日誌後改 60 → 90
#   WARRANT_CAP=30000          單日目標數安全上限(超過即 fail closed,不截斷)
#   WARRANT_SLEEP=1.2          請求間隔(全市場合計)
#   WARRANT_SAFETY_MINUTES=15  從「距下一輪還有多久」扣掉的安全邊際
#   WARRANT_MIN_CHUNK_MINUTES=20  低於此值不值得 pause/unpause,直接略過
#   WARRANT_MAX_MINUTES=240    單塊上限
#   WARRANT_STATE_BASE=data/warrant-branch-backfill.json
#                              base path;CLI 在旁邊寫 <stem>-<date>-<market>.json。
#                              必須落在容器看得到的掛載點(/app/data)之下。
#   WARRANT_MEASURE_LOG=$HOME/warrant-backfill-measure.log
#   MIN_FREE_GB=2              本腳本刻意低於他處的 4:這份工作的目的就是吃磁碟,
#                              但必須在遠早於 ENOSPC 之前停手
#   MIN_MEM_MB=900
source "$(dirname "$0")/lib.sh"

FLAG="${MID_PUBLISH_FLAG:-/tmp/radar-mid-publish.flag}"
DAYS="${WARRANT_DAYS:-30}"
CAP="${WARRANT_CAP:-30000}"
SLEEP="${WARRANT_SLEEP:-1.2}"
SAFETY_MINUTES="${WARRANT_SAFETY_MINUTES:-15}"
MIN_CHUNK_MINUTES="${WARRANT_MIN_CHUNK_MINUTES:-20}"
MAX_MINUTES="${WARRANT_MAX_MINUTES:-240}"
STATE_BASE="${WARRANT_STATE_BASE:-data/warrant-branch-backfill.json}"
MEASURE_LOG="${WARRANT_MEASURE_LOG:-$HOME/warrant-backfill-measure.log}"
MIN_FREE_GB="${MIN_FREE_GB:-2}"
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
UNTIL="$(minutes_until_quiet_window)"
BUDGET=$(( UNTIL - SAFETY_MINUTES ))
if [ "$BUDGET" -lt "$MIN_CHUNK_MINUTES" ]; then
  echo "next quiet window in ${UNTIL}min; budget ${BUDGET}min < ${MIN_CHUNK_MINUTES}min — skip (too short to be worth a pause/unpause cycle)"
  exit 0
fi
if [ "$BUDGET" -gt "$MAX_MINUTES" ]; then
  BUDGET="$MAX_MINUTES"
fi
echo "next quiet window in ${UNTIL}min; chunk budget ${BUDGET}min (safety ${SAFETY_MINUTES}min, cap ${MAX_MINUTES}min)"

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

RUN_LOG="$(mktemp "${TMPDIR:-/tmp}/warrant-backfill-run.XXXXXX")"
chain_exit_trap "rm -f '$RUN_LOG'"

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
radar backfill-warrant-branches \
  --market "$MARKET" \
  --top "$CAP" \
  --days "$DAYS" \
  --sleep "$SLEEP" \
  --max-minutes "$BUDGET" \
  --state-file "$STATE_BASE" 2>&1 | tee "$RUN_LOG"
rc="${PIPESTATUS[0]}"
set -e
ELAPSED=$(( $(date +%s) - START ))

# CLI 的離開碼語意(讀 pipeline/radar/importer.py 的
# `_backfill_warrant_branches_with_state` 與 cli.py 的
# `cmd_backfill_warrant_branches` 確認過,不是猜的):
#   rc=0  → 這個 days 深度內每一個日期都已完整。
#   rc!=0 → cli 一律 `raise SystemExit(f"warrant branch backfill incomplete: {stopped}")`,
#           所以「乾淨停下」與「真的壞了」共用同一個離開碼,只能靠 stopped 文字分辨:
#             "time budget reached at <date>"   ← 我們自己的 --max-minutes,成功
#             "resume required: N date(s) ..."  ← 還有日期沒跑完,下次接著跑,成功
#             "too many failures at <date>: .." ← 連續 30 次以上抓取失敗,真失敗
#           其他非零(python traceback、docker 失敗、目標數超過 --top 的
#           fail-closed RuntimeError)都沒有這行,一律當真失敗處理。
VERDICT="unknown"
if [ "$rc" -eq 0 ]; then
  VERDICT="complete"
elif grep -q 'warrant branch backfill incomplete: time budget reached' "$RUN_LOG"; then
  VERDICT="clean-stop-time-budget"
elif grep -q 'warrant branch backfill incomplete: resume required' "$RUN_LOG"; then
  VERDICT="clean-stop-resume-required"
elif grep -q 'warrant branch backfill incomplete: too many failures' "$RUN_LOG"; then
  VERDICT="failed-too-many-failures"
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
echo "chunk ${VERDICT}: rc=${rc}, ${ELAPSED}s, budget=${BUDGET}min, days=${DAYS}"
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

case "$VERDICT" in
  complete)
    echo "all done — every date within days=${DAYS} is complete"
    if [ ! -f "$DONE_FLAG" ]; then
      notify_ok "權證分點回補完成：深度 ${DAYS} 個交易日、全市場（上市＋上櫃）；bytes/row 實測 ${BYTES_PER_ROW}，可據此決定下一段深度"
      : > "$DONE_FLAG"
    fi
    ;;
  clean-stop-*)
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
