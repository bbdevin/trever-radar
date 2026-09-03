#!/usr/bin/env bash
# 還原因子(adj_factor)全市場修復 — 一次一塊、可續跑、對排程讓路。
#
# 缺陷(2026-09-02 查出):`daily_prices.adj_factor` 從來沒有全市場算過。除了 2330
# 之外每一檔都停在 migration 預設值 1.0,於是除權息與分割被當成真實漲跌:
# 緯穎 6669 在 2026-09-02 顯示 -66.5%「暴跌」,實際上是 1 股換 3 股的分割。
# 指標、未來報酬與分點勝率全都乘上這個因子,等於整條評分鏈建立在未還原價之上。
# 2026-09-02 的 4 檔實測修好了 6669(還原收盤 2,614.99 → 2,610.00,即 -0.19%
# 而非 -66.5%),4 檔 12 秒(每檔約 3 秒)、更新 22,975 列價格。
# 全市場推估:約 2,494 檔、2.1 小時、約 1,400 萬列更新。
#
# 為什麼要分塊:VPS 排程沒有乾淨的多小時空檔(14:10 跑到 ~15:11、15:00、16:10、
# 17:40 跑到 ~19:21、21:20、22:00、23:30、01:10)。單一長跑會抓著
# /tmp/radar-db.lock 不放,害當輪日更 acquire_db_lock 搶不到而整輪略過。
# 所以工作必須可切、可續,而且「讓路而不是排隊」:
#   * 一次呼叫只做一塊(ADJUST_CHUNK,預設 200 檔,約 10 分鐘)然後結束。
#   * 鎖被占用 / 日更輪進行中 / 在安靜窗內 → 印出原因並 exit 0。略過是正常結果,
#     不是失敗;`flock -n` 絕不等待。
#   * 剩餘工作留在 state 檔,下一次呼叫接著跑。
#
# 怎麼驅動(本腳本刻意不在 crontab 裡,也不要在沒有維運者決定的情況下加進去):
#   平日 02:30–14:05 是唯一的長空檔(約 11.5 小時),2.1 小時的總量塞得進去。
#   迴圈跑:
#     while bash vps/scripts/adjust-backfill.sh; do sleep 180; done
#   或就手動重複呼叫直到印出 "all done"。任何一次略過都回 0,失敗才回非 0。
#
# 不跑重算鏈:本腳本只修 adj_factor。compute-indicators / compute-performance /
# compute-branch-stats / compute-scores / export 是還原完成之後由維運者另外
# 刻意執行的一步,不要把它們接到這裡來。
#
# 環境變數:ADJUST_CHUNK=200;ADJUST_STATE=$HOME/adjust-backfill.state;
#           MIN_FREE_GB=4;MIN_MEM_MB=900。
source "$(dirname "$0")/lib.sh"

FLAG="${MID_PUBLISH_FLAG:-/tmp/radar-mid-publish.flag}"
STATE_FILE="${ADJUST_STATE:-$HOME/adjust-backfill.state}"
DONE_FLAG="${STATE_FILE}.done"
CHUNK="${ADJUST_CHUNK:-200}"
MIN_FREE_GB="${MIN_FREE_GB:-4}"
MIN_MEM_MB="${MIN_MEM_MB:-900}"

# 失敗一律自己處理(每個失敗點都要留住 state 並 unpause),不靠 lib 的 ERR trap
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

# 原子寫:同目錄暫存檔 → mv。中斷絕不留下半截 state。
write_state() {
  local tmp
  tmp="$(mktemp "${STATE_FILE}.XXXXXX")"
  cat > "$tmp"
  mv -f "$tmp" "$STATE_FILE"
}

state_count() {
  [ -s "$STATE_FILE" ] || { echo 0; return 0; }
  awk 'NF { n++ } END { print n+0 }' "$STATE_FILE"
}

echo "=== adjust-backfill start $(taipei_date -Is) chunk=${CHUNK} state=${STATE_FILE} ==="

if in_radar_quiet_window; then
  echo "inside quiet window — skip (yield to the scheduled round)"
  exit 0
fi

if [ -f "$FLAG" ]; then
  echo "mid-publish flag present — skip"
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

# state 已存在且已清空 → 全市場跑完了。ok 通知只發一次(靠 .done 標記),
# 否則迴圈每 3 分鐘就會轟一則 ntfy。
if [ -f "$STATE_FILE" ] && [ ! -s "$STATE_FILE" ]; then
  echo "all done — state file is empty, nothing left to adjust"
  if [ ! -f "$DONE_FLAG" ]; then
    notify_ok "還原因子全市場回補完成，adj_factor 已補齊；指標／績效／分點統計重算請另行執行"
    : > "$DONE_FLAG"
  fi
  exit 0
fi

# EXIT trap 必須在 pause 之前、也在第一次呼叫 radar 之前掛好(lib.sh 的維護約束)。
chain_exit_trap 'unpause_bf_containers'

echo "pause backfill (if any); mem=${MEM}MB free_disk=${FREE}G"
pause_bf_containers

# 讓路、不排隊:搶不到就走,絕不 block 等鎖。
exec 9>/tmp/radar-db.lock
if ! flock -n 9; then
  echo "radar-db.lock held — skip (a scheduled round or another writer is running)"
  exit 0
fi

# 這支工作要寫上百萬列,pause 與搶鎖之間磁碟可能已經被別的工作吃掉。
FREE2="$(free_gb)"
if ! disk_ok "$FREE2"; then
  echo "disk free ${FREE2}G < ${MIN_FREE_GB}G after taking the lock — refuse to start a chunk"
  exit 0
fi

cd "$REPO"

# 首次執行:把全市場的股票 id 灌進 state 檔。宇宙定義沿用管線其他地方的
# 「活躍標的」(json_export / importer):type IN ('stock','etf') AND is_active = 1,
# 再 JOIN daily_prices 只留真的有價格列可還原的標的。
if [ ! -f "$STATE_FILE" ]; then
  echo "state file missing — populating from the database"
  set +e
  db_col "SELECT DISTINCT s.id FROM stocks s JOIN daily_prices p ON p.stock_id = s.id
          WHERE s.type IN ('stock','etf') AND s.is_active = 1 ORDER BY s.id" \
    | grep -E '^[0-9A-Za-z]+$' | write_state
  seed_rc=$?
  set -e
  if [ "$seed_rc" -ne 0 ] || [ ! -s "$STATE_FILE" ]; then
    echo "failed to seed the state file (rc=${seed_rc}) — nothing written"
    rm -f "$STATE_FILE"
    notify "還原因子回補無法從資料庫取得股票清單（碼 ${seed_rc}），本次中止" high "失敗"
    exit 1
  fi
  rm -f "$DONE_FLAG"
  echo "seeded $(state_count) stock ids"
fi

REMAIN="$(state_count)"
if [ "$REMAIN" -eq 0 ]; then
  echo "all done — state file is empty, nothing left to adjust"
  if [ ! -f "$DONE_FLAG" ]; then
    notify_ok "還原因子全市場回補完成，adj_factor 已補齊；指標／績效／分點統計重算請另行執行"
    : > "$DONE_FLAG"
  fi
  exit 0
fi

TAKE="$CHUNK"
if [ "$TAKE" -gt "$REMAIN" ]; then
  TAKE="$REMAIN"
fi
IDS="$(head -n "$TAKE" "$STATE_FILE" | paste -sd, -)"

echo "chunk: ${TAKE} ids (${REMAIN} remaining before this chunk)"
echo "ids=${IDS}"

START=$(date +%s)
set +e
radar compute-adjustments --ids "$IDS"
rc=$?
set -e
ELAPSED=$(( $(date +%s) - START ))

if [ "$rc" -ne 0 ]; then
  # state 完全不動:這批 id 下一次呼叫原樣重試。連續失敗是維運者的訊號,
  # 不要吞掉。unpause 交給 EXIT trap,失敗絕不留下被 pause 的回補容器。
  echo "chunk FAILED rc=${rc} after ${ELAPSED}s — state left intact, ${REMAIN} ids still pending"
  notify "還原因子分塊失敗（碼 ${rc}，${TAKE} 檔，${ELAPSED} 秒），state 保留待重試" high "失敗"
  exit "$rc"
fi

# 成功才把這批從 state 移除,一樣原子寫。
tail -n +"$((TAKE + 1))" "$STATE_FILE" | write_state
LEFT="$(state_count)"

echo "chunk ok: ${TAKE} ids, rc=0, ${ELAPSED}s, ${LEFT} ids remaining"
echo "=== adjust-backfill done $(taipei_date -Is) ==="
