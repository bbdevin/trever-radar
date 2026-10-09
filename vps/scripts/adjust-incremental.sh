#!/usr/bin/env bash
# 還原因子(adj_factor)日增量 — 平日 13:15,14:05 收盤輪之前的空檔。
#
# 缺陷(2026-10-09 查出):adj_factor 只在手動跑 compute-adjustments 時更新
# (adjust-backfill.sh 刻意不在 crontab)。最後一次正式跑是 2026-09-04,之後
# 任何除權息日的個股,還原序列在除權息日都是斷的,指標、分數、價格位置跟著錯。
#
# 做法(只挑股票,不改因子邏輯):
#   1. compute-adjustments --ex-dates-since N --print-ids:證交所 TWT49U +
#      櫃買 exDailyQ 各一次請求,挑出近 N 個日曆日(預設 10)有除權息日的代號,
#      再與本庫 stock/etf 取交集。FinMind 全市場查詢免費 token 不開放(400)。
#   2. compute-adjustments --ids:與 adjust-backfill.sh 同一條路——逐檔 FinMind
#      TaiwanStockDividendResult、factors_for_dates、整檔覆寫。冪等。
#   3. compute-indicators --ids(不帶 --days = 只對這幾檔全歷史重算)。
# 不 export、不 deploy:14:05 收盤輪會把結果上線。
#
# 為什麼窗是 10 天:FinMind 的除權息結果可能晚於除權息日才出現。同一檔在窗內每天
# 都會再跑一次(冪等),所以晚到、某天被略過、某天指標失敗,隔天都會自己補上。
# 旺季(7 月)10 天窗實測約 260 檔(上市 142 + 上櫃 122,2026-07-10..07-20),
# 約 3 秒/檔 → ~13 分鐘,低於 FinMind 免費 token 每小時 ~600 次。
#
# 守衛(同 adjust-backfill.sh):安靜窗內 / mid-publish 進行中 / 距下一個排程寫入者
# ≤ 30 分鐘 → 略過;`flock -n` 搶不到 DB 鎖 → 略過,絕不等待。
# 每一步都有硬上限,算到「下一個排程寫入者開跑前 5 分鐘」為止。
#
# 一次性追補(例:2026-09-04 之後全部漏掉的):
#   ADJUST_SINCE=2026-09-04 bash vps/scripts/adjust-incremental.sh
# 環境變數:ADJUST_SINCE=10(天數或 YYYY-MM-DD);ADJUST_MIN_LEFT_MIN=30。
source "$(dirname "$0")/lib.sh"

SINCE="${ADJUST_SINCE:-10}"
FLAG="${MID_PUBLISH_FLAG:-/tmp/radar-mid-publish.flag}"
MIN_LEFT_MIN="${ADJUST_MIN_LEFT_MIN:-30}"
SAFETY_MIN=5
WORK_LOG=""

# 失敗一律自己處理(每個失敗點各發一則),不靠 lib 的 ERR trap,免得同一次失敗發兩則。
trap - ERR

adjust_incremental_cleanup() {
  if [ -n "$WORK_LOG" ]; then
    rm -f "$WORK_LOG"
  fi
  resume_bf_paused_by_us
}

echo "=== adjust-incremental start $(taipei_date -Is) since=${SINCE} ==="

if in_radar_quiet_window; then
  echo "inside quiet window — skip (yield to the scheduled round)"
  exit 0
fi

if [ -f "$FLAG" ]; then
  echo "mid-publish flag present — skip"
  exit 0
fi

LEFT="$(minutes_until_next_scheduled_writer)"
if [ "$LEFT" -le "$MIN_LEFT_MIN" ]; then
  echo "only ${LEFT} min until the next scheduled writer (need > ${MIN_LEFT_MIN}) — skip"
  exit 0
fi

# 讓路、不排隊:搶不到就走。先搶鎖再 pause(理由見 adjust-backfill.sh)。
exec 9>/tmp/radar-db.lock
if ! flock -n 9; then
  echo "radar-db.lock held — skip (a scheduled round or another writer is running)"
  notify_skip "資料庫鎖占用，本次略過；近 ${SINCE} 天內除權息的個股明天會再處理"
  exit 0
fi

# EXIT trap 必須在 pause 之前、也在第一次呼叫 radar 之前掛好(lib.sh 的維護約束)。
trap 'adjust_incremental_cleanup' EXIT
pause_bf_for_exclusive_writer

cd "$REPO"
START=$(date +%s)
DEADLINE=$(( START + (LEFT - SAFETY_MIN) * 60 ))
secs_left() { echo $(( DEADLINE - $(date +%s) )); }
echo "budget: ${LEFT} min until next scheduled writer, hard deadline in $(secs_left)s"

# 1. 選股(唯讀)
if IDS="$(radar_timeout 300 compute-adjustments --ex-dates-since "$SINCE" --print-ids)"; then
  :
else
  rc=$?
  echo "select-ex-dates FAILED rc=${rc}"
  notify "除權息選股失敗（碼 ${rc}；證交所 TWT49U／櫃買 exDailyQ），本次未重算；明天會再試" high "失敗"
  exit "$rc"
fi
IDS="$(printf '%s\n' "$IDS" | tail -n 1 | tr -d '[:space:]')"
if [ -z "$IDS" ]; then
  echo "adjust-incremental summary: selected=0 (no ex-dates in window) elapsed=$(( $(date +%s) - START ))s"
  echo "=== adjust-incremental done $(taipei_date -Is) ==="
  exit 0
fi
if ! printf '%s\n' "$IDS" | grep -Eq '^[0-9A-Za-z]+(,[0-9A-Za-z]+)*$'; then
  echo "select-ex-dates returned an unexpected id list: ${IDS}"
  notify "除權息選股回傳格式異常，本次未重算" high "失敗"
  exit 1
fi
SELECTED="$(printf '%s' "$IDS" | tr ',' '\n' | grep -c .)"
echo "selected=${SELECTED} ids=${IDS}"

# 2. 還原因子(逐檔 FinMind;輸出另存一份來數 changed/failed)
WORK_LOG="$(mktemp "${TMPDIR:-/tmp}/adjust-incremental.XXXXXX")"
if run_step "compute-adjustments" radar_timeout "$(secs_left)" compute-adjustments --ids "$IDS" 2>&1 | tee "$WORK_LOG"; then
  :
else
  rc=$?
  echo "compute-adjustments FAILED rc=${rc}"
  notify "還原因子增量失敗（碼 ${rc}，${SELECTED} 檔），指標未重算；已寫入的因子保留，明天同一窗會重跑" high "失敗"
  exit "$rc"
fi
CHANGED="$(sed -n 's/^changed: \([0-9]*\) stocks, \([0-9]*\) rows$/\1/p' "$WORK_LOG" | tail -n 1)"
CHANGED_ROWS="$(sed -n 's/^changed: \([0-9]*\) stocks, \([0-9]*\) rows$/\2/p' "$WORK_LOG" | tail -n 1)"
DONE="$(sed -n 's/^adjustments: \([0-9]*\) stocks.*/\1/p' "$WORK_LOG" | tail -n 1)"
FAILED="$(sed -n 's/^adjustments: .* \([0-9]*\) failed$/\1/p' "$WORK_LOG" | tail -n 1)"
QUOTA=0
if grep -q '^quota hit at ' "$WORK_LOG"; then
  QUOTA=1
fi

# 3. 指標:這幾檔全歷史重算(不帶 --days)。對全部選到的檔都算,不只 changed:
#    前一天因子已改、指標卻失敗的檔,今天因子「沒變」,仍要把指標補上。
#    `timeout 0s` 等於沒有上限,所以剩不到 60 秒就不開跑。
if [ "$(secs_left)" -lt 60 ]; then
  echo "compute-indicators skipped: hard deadline reached"
  notify "還原因子已更新 ${CHANGED:-?} 檔，但時間用完、指標未重算；明天同一窗會重算" high "失敗"
  exit 1
fi
if run_step "compute-indicators" radar_timeout "$(secs_left)" compute-indicators --ids "$IDS"; then
  :
else
  rc=$?
  echo "compute-indicators FAILED rc=${rc}"
  notify "還原因子已更新 ${CHANGED:-?} 檔，但指標重算失敗（碼 ${rc}）；14:05 輪會用新因子上線、指標要等明天同一窗重算" high "失敗"
  exit "$rc"
fi

ELAPSED=$(( $(date +%s) - START ))
echo "adjust-incremental summary: selected=${SELECTED} adjusted=${DONE:-?} changed=${CHANGED:-?} changed_rows=${CHANGED_ROWS:-?} failed=${FAILED:-?} quota_hit=${QUOTA} indicators=${SELECTED} elapsed=${ELAPSED}s"

if [ "${FAILED:-0}" -gt 0 ] || [ "$QUOTA" = "1" ]; then
  QUOTA_NOTE=""
  if [ "$QUOTA" = "1" ]; then
    QUOTA_NOTE="、FinMind 額度用完提前停止"
  fi
  notify_warn "還原因子增量：${SELECTED} 檔中 ${FAILED:-0} 檔失敗${QUOTA_NOTE}；明天同一窗會重跑"
fi
if [ "${CHANGED:-0}" -gt 0 ]; then
  notify_ok "除權息還原因子更新 ${CHANGED} 檔（${CHANGED_ROWS} 列）並重算指標，14:05 收盤輪上線"
fi
echo "=== adjust-incremental done $(taipei_date -Is) ==="
