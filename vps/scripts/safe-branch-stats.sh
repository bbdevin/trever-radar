#!/usr/bin/env bash
# 低負載分點統計 + 分數 + 上線(docs/33 S1.1 + S2 / docs/35 Layer 3)。
# 與 mid-backfill-publish 分離:mid 只負責加深 JSON;本腳本專跑 stats→scores→export。
# 避開 daily-* 窗;pause bf;記憶體不足則跳過;stats 失敗則中止(不跑 scores/export)。
#
# 環境變數:MIN_FREE_GB=4;MIN_MEM_MB=900;SKIP_EXPORT=1 只算不上線;SKIP_SCORES=1 略過分數;
#           SKIP_PIT=1 略過 point-in-time 帳本;
#           SKIP_PAIR_PCTILE=1 略過分點×個股價格分位計數。
source "$(dirname "$0")/lib.sh"

FLAG="${MID_PUBLISH_FLAG:-/tmp/radar-mid-publish.flag}"
STATE_FILE="${SAFE_STATS_STATE:-$HOME/safe-branch-stats.state}"
MIN_FREE_GB="${MIN_FREE_GB:-4}"
MIN_MEM_MB="${MIN_MEM_MB:-900}"
CONTAINERS="${BF_CONTAINERS:-radar-bf-branches radar-bf-warrant}"
# 2026-08-31~09-03 事故(docs/STATUS.md):安靜窗 off-by-one 讓本作業四天沒跑,
# 卻只送出 default 優先權的略過通知,沒人注意到。STALE_HOURS 是「連續幾小時
# 沒有一次成功完成」的門檻,超過就改吹 high 優先權(見 skip_or_alarm)。
STALE_HOURS="${STALE_HOURS:-30}"

trap - ERR
trap 'rm -f "$FLAG" 2>/dev/null || true; unpause_bf_containers' EXIT

free_gb() {
  df -PB1 "$REPO" | awk 'NR==2 {printf "%.1f", $4/1024/1024/1024}'
}

mem_available_mb() {
  awk '/MemAvailable:/ {printf "%d", $2/1024}' /proc/meminfo
}

# 計時 wrapper `run_step` 定義在 lib.sh(本檔 source 它):17:40 / 22:00 的
# daily-branches.sh 也用同一份,兩輪的 log 才是同一個格式,可以用同一個 grep
# 比較同一步在兩輪的耗時。搬過去時語意逐字未變(見 lib.sh 的註解)。

# 唯一決定「這次略過該用 default 還是 high 優先權」的地方,五個 skip 出口都呼叫它。
# 邏輯:讀 $STATE_FILE 的 finished= 時間戳,離現在超過 $STALE_HOURS 小時(或
# state 檔不存在、或時間戳解析失敗)就視為「已經連續失敗/被擋一段時間」,
# 改用 high 優先權自己發一則(而不是 notify_skip 固定的 default),文字帶上
# 距上次成功完成多久,讓值班的人一眼看出這不是單次、無害的略過。
skip_or_alarm() {
  local reason="$1" finished_raw="" finished_epoch now_epoch age_h
  now_epoch="$(date +%s)"
  if [ -f "$STATE_FILE" ]; then
    finished_raw="$(grep -m1 '^finished=' "$STATE_FILE" 2>/dev/null | cut -d= -f2- || true)"
  fi
  if [ -n "$finished_raw" ] && finished_epoch="$(date -d "$finished_raw" +%s 2>/dev/null)"; then
    age_h=$(( (now_epoch - finished_epoch) / 3600 ))
    if [ "$age_h" -lt "$STALE_HOURS" ]; then
      notify_skip "$reason"
    else
      notify "${reason}；距上次成功完成已 ${age_h} 小時（超過 ${STALE_HOURS} 小時門檻）" high "略過"
    fi
  else
    # state 檔不存在，或 finished= 缺失／無法解析 → 寧可吵不要靜默重演 08-31~09-03。
    notify "${reason}；找不到可解析的上次成功完成紀錄（$STATE_FILE）" high "略過"
  fi
}

echo "=== safe-branch-stats start $(taipei_date -Is) ==="

if in_radar_quiet_window; then
  echo "inside quiet window — skip"
  skip_or_alarm "正值日更安靜窗，分點排行略過"
  exit 0
fi

# 直接搶鎖(而不是像過去只用 fuser 偷看),搶到就一路持有到本程序結束
# (fd 9 在 EXIT 時由 kernel 自動關閉即釋放,不需要、也不應該手動 close/reuse fd 9)。
# 只「看」不「拿」曾是本次事故唯一真正的第二層保護——安靜窗算錯之後,
# 這裡就形同虛設,才會四天寫進 0 列都沒人擋下來。
# 拿到鎖之後,01:10 的 data-backfill.sh 若撞上本作業仍在跑會自行讓路一晚:
# 深歷史回補是可續跑的,晚一夜不損失任何資料;夜間帳本不是,這正是本次
# 事故要保護的東西,所以刻意選邊。不要「修好」成雙方都不持鎖。
#
# 2026-09-08:改「搶不到就立刻放棄」為「最多等 50 分鐘」。22:00 那輪的尾巴實測
# 23:53 / 約 00:12 / 一次超過 00:05,而 00:05 撞上它就整夜略過。那一夜的代價
# 被 log 藏起來了:branch_point_in_time_persist 的 as_of 預設取
# MAX(date) FROM daily_prices,PK 是 (branch_name, as_of, window_market_days),
# 同一個 as_of 重跑是**覆蓋**。production 實測 09-05/06/07 三次成功全部解析到
# as_of=2026-09-04 互相覆蓋成一列;唯一會產生新 as_of 的那一次(09-07)正好被
# 略過——被吞掉的是一個再也補不回誠實 computed_at 的帳本日期。
LOCK_WAIT_SECS="${LOCK_WAIT_SECS:-3000}"   # 50 分鐘:00:05 起算,最晚 00:55 放棄
exec 9>/tmp/radar-db.lock
_lock_t0="$(date +%s)"
echo "step lock-wait start $(taipei_date -Is)"
if flock -w "$LOCK_WAIT_SECS" 9; then
  # 這行秒數就是「22:00 那輪的尾巴還在不在長」的唯一量測值;沒有它,這次改動
  # 無法被驗證,下次是要再加時間還是要搬時段也就沒有依據。保留這行原文,
  # 下面的 `step lock-wait done` 只是併入其他步驟共用的計時格式,不取代它。
  echo "waited $(( $(date +%s) - _lock_t0 ))s for radar-db.lock"
  echo "step lock-wait done rc=0 elapsed=$(( $(date +%s) - _lock_t0 ))s"
else
  echo "radar-db.lock held — gave up after $(( $(date +%s) - _lock_t0 ))s"
  echo "step lock-wait done rc=1 elapsed=$(( $(date +%s) - _lock_t0 ))s"
  # 刻意不走 skip_or_alarm:STALE_HOURS 是 30,而週三漏到週六只隔約 24 小時,
  # 走 staleness 判斷會判成 default 優先權,損失又一次靜默。等到 00:55 還拿不到,
  # 代表 22:00 那輪已經跑了 175 分鐘——這是要叫人起來看的事故,不是例行略過。
  # 標題用「失敗」而非「略過」:其餘五個 skip 出口是「條件不合、今晚不做」,
  # 讀者可以放心滑過去;這一則不是。等滿 50 分鐘代表 22:00 那輪已經跑了 175
  # 分鐘還沒放手,而代價是一個補不回誠實 computed_at 的帳本日期。標成「略過」
  # 會讓它混進例行通知裡,那正是 08-31~09-03 那四天沒人發現的原因。
  notify "資料庫鎖等滿 ${LOCK_WAIT_SECS} 秒仍未釋放（22:00 那輪疑似卡住），分點排行與帳本本夜落空" high "失敗"
  exit 0
fi
# data-backfill.sh(01:10)刻意維持 lib.sh 的 `acquire_db_lock`(`flock -n`,搶不到
# 就讓路一晚)。不要把它也「修好」成會等:深歷史回補是可續跑的,晚一夜零損失,
# 而讓它排隊只會多出第二個等待者,把 00:05~00:55 這段窗口變成互相堆疊。
# 單一寫入者的不變式不受本次改動影響:flock 仍是獨占,而等待中的程序不持有任何東西。

if [ -f "$FLAG" ]; then
  echo "mid-publish flag present — skip"
  skip_or_alarm "回補中途上線進行中，分點排行略過"
  exit 0
fi

FREE="$(free_gb)"
awk -v f="$FREE" -v m="$MIN_FREE_GB" 'BEGIN { exit !(f+0 >= m+0) }' || {
  echo "disk free ${FREE}G < ${MIN_FREE_GB}G — skip"
  skip_or_alarm "磁碟空間不足（剩 ${FREE}G），分點排行略過"
  exit 0
}

MEM="$(mem_available_mb)"
if [ "${MEM:-0}" -lt "$MIN_MEM_MB" ]; then
  echo "MemAvailable ${MEM}MB < ${MIN_MEM_MB}MB — skip"
  skip_or_alarm "記憶體不足（${MEM}MB < ${MIN_MEM_MB}MB），分點排行略過"
  exit 0
fi

install_fail_trap
trap 'rm -f "$FLAG" 2>/dev/null || true; unpause_bf_containers' EXIT

touch "$FLAG"
echo "pause backfill (if any); mem=${MEM}MB free_disk=${FREE}G"
pause_bf_containers
sleep 3
# pause 後再量一次(容器凍結後可用記憶體通常上升)
MEM2="$(mem_available_mb)"
echo "mem after pause=${MEM2}MB"

cd "$REPO"
if [ "${SAFE_STATS_SYNC:-0}" = "1" ]; then
  sync_code
fi

# 22:00 那輪(daily-branches.sh)寫的是同一張 import_logs,dataset='branch'。
# date 欄是它抓資料當下的交易日(import_branch_trades 沒給 --date 時預設
# MAX(date) FROM daily_prices),不是本腳本自己執行的日曆日;本腳本 00:05
# 起跑,對應的正是「台北現在的昨天」——22:00 還沒跨過午夜,run_at 與 date
# 兩欄都停在那個日曆日,只有本腳本自己的「現在」翻到了下一天。
# 唯讀連線(?mode=ro):只問狀態,不跟本腳本或其他寫入者搶鎖。
BRANCH_IMPORT_DATE="${BRANCH_IMPORT_DATE:-$(TZ=Asia/Taipei date -d 'yesterday' +%Y-%m-%d)}"

branch_import_row() {
  docker run --rm -v "$REPO/data":/app/data radar-pipeline \
    python -c "import sqlite3,sys
conn = sqlite3.connect('file:/app/data/radar.db?mode=ro', uri=True)
row = conn.execute(
    \"SELECT status, run_at FROM import_logs WHERE dataset='branch' AND date=? \"
    \"ORDER BY id DESC LIMIT 1\",
    (sys.argv[1],)).fetchone()
print('%s\t%s' % (row[0], row[1]) if row else '\t')" "$BRANCH_IMPORT_DATE"
}

BRANCH_ROW="$(branch_import_row 2>/dev/null || true)"
BRANCH_STATUS="${BRANCH_ROW%%	*}"
BRANCH_RUN_AT="${BRANCH_ROW#*	}"
MARKER="$(branch_round_marker "$BRANCH_IMPORT_DATE")"
MARKER_AT="$(cat "$MARKER" 2>/dev/null || true)"
echo "22:00 branch import_logs for ${BRANCH_IMPORT_DATE}: status='${BRANCH_STATUS:-<missing>}' run_at='${BRANCH_RUN_AT:-<missing>}'"
echo "evening round marker: ${MARKER_AT:-<missing>}"

# 跳過重算需要兩個條件同時成立,少一個都要走完整補跑路徑:
#
#   1. 那一輪的匯入本身合格 —— status 是 ok 或 incomplete。
#      incomplete 也算合格是刻意的:它代表「有個別標的沒抓到,但當日覆蓋率仍在
#      帶內」,資料可用。只有 error(覆蓋率掉出帶狀範圍)才是不合格。
#   2. 當天有完成標記 —— **只看存在,不比時間**。
#      只看 status 不夠 —— 匯入 ok 之後 compute-branch-stats 仍可能 OOM,整輪
#      什麼都沒算出來也沒上線;那時跳過等於把備援關掉,正好在最需要它的那晚。
#
#      這裡以前比的是「標記時間是否晚於那筆匯入的 run_at」。22:00 那輪改成
#      只匯入(daily-branches.sh 的 BRANCH_ROUND_MODE=import)之後,這個比較
#      必然為假:當天最新的那筆分點匯入是 22:00 那輪寫的(約 23:00),而標記
#      是 17:40 那輪寫的(約 20:30),標記永遠比匯入舊,於是每一夜都會重算,
#      省下來的 74 分鐘全部吐回去。
#
#      只看存在就夠了,因為標記只在 deploy_data 成功之後才寫(見
#      daily-branches.sh 結尾與 lib.sh 的 branch_round_marker):它存在本身
#      就證明當天有一輪完整鏈算完並上線了。17:40 那輪若算到一半 OOM,
#      根本不會有標記,夜間作業照常補跑——這正是我們要的 fallback 行為。
#
# 查詢失敗、空字串、標記缺失一律落在「未確認完成」這邊——這支腳本存在的理由
# 就是 fallback,判斷不出來的時候多跑一次的代價遠低於漏跑。
#
# BRANCH_RUN_AT 不再參與這個判斷,但保留:它會寫進 state 檔與上面那行 log,
# 是事後對照「當晚最後一次匯入是幾點」的唯一紀錄。
EVENING_BRANCH_OK=0
if [ "$BRANCH_STATUS" = "ok" ] || [ "$BRANCH_STATUS" = "incomplete" ]; then
  if [ -n "$MARKER_AT" ]; then
    EVENING_BRANCH_OK=1
  else
    echo "找不到完成標記：當天沒有任何一輪算完並上線,本輪照常補跑"
  fi
fi

STATS_NOTE="ok"
SCORES_NOTE="skipped"
PIT_NOTE="skipped"
PAIR_PCTILE_NOTE="skipped"

if [ "$EVENING_BRANCH_OK" = "1" ]; then
  STATS_NOTE="skipped_evening_ok"
  echo "skip compute-branch-stats：${BRANCH_IMPORT_DATE} 那輪已整條跑完並上線（status=${BRANCH_STATUS}，標記 ${MARKER_AT}）"
elif run_step "compute-branch-stats" radar compute-branch-stats; then
  STATS_NOTE="ok"
else
  rc=$?
  STATS_NOTE="failed_rc_${rc}"
  echo "compute-branch-stats failed rc=$rc"
  notify "分點統計失敗（碼 ${rc}），本輪中止" high "失敗"
  rm -f "$FLAG"
  unpause_bf_containers
  exit "$rc"
fi

# branch-point-in-time-persist 落在這裡、而不是自己一條 cron:
#   1. 它需要的守衛這支腳本已經全做過了 —— 安靜窗、/tmp/radar-db.lock、
#      mid-publish flag、磁碟與記憶體門檻,以及 backfill 容器的 pause。
#      獨立排程等於把這五道保護重寫一遍,而且遲早會漂移。
#   2. 這個 DB 是單一寫入者。多一條 cron 就是多一個寫入者,會跟本腳本
#      與回補容器搶鎖;折進這裡則沿用同一把鎖、同一個時間窗。
#   3. 成本 31~50 秒,對一支本來就跑好幾分鐘的工作可忽略。
# 位置在 compute-branch-stats 之後、compute-scores 之前(順序固定,便於對照
# state 檔)。這是排版慣例,不是資料相依:
# branch_point_in_time_persist.py 讀的是 `branch_trades WHERE date <= as_of`
# 與 daily_prices,branch_stock_pctile_counts.py 同樣直接讀 branch_trades,
# 兩者都**不讀** branch_stats / branch_stock_stats。所以即使今晚因為
# EVENING_BRANCH_OK=1 而跳過 compute-branch-stats,帳本一樣看得到 22:00 那輪
# 剛匯入的分點資料,算出來的東西不會少一天。以前這裡寫「帳本讀的是它剛更新
# 的資料」是錯的,而且會讓人以為跳過 compute 就得連帳本一起跳過。
# 失敗不中止本輪:這張帳本次要於分數/匯出/上線,不能因為它而擋住當天的價格上線。
if [ "${SKIP_PIT:-0}" != "1" ]; then
  if run_step "branch-point-in-time-persist" radar branch-point-in-time-persist; then
    PIT_NOTE="ok"
  else
    prc=$?
    PIT_NOTE="failed_rc_${prc}"
    echo "branch-point-in-time-persist failed rc=$prc (continue to scores)"
    notify_warn "分點 point-in-time 帳本落地失敗（碼 ${prc}），仍繼續分數與匯出"
  fi
else
  PIT_NOTE="skipped_env"
fi

# branch-stock-pctile-counts:同一批原料的 pair 粒度快照(分點 × 個股 的低買/
# 高賣計數),個股頁要用。折在這裡的理由與上面那段完全相同(共用五道守衛、
# 單一寫入者、成本可忽略),而且它讀的原料同樣是 branch_trades,不是 stats 表。
# 整張表每輪被取代,失敗只是舊快照留著,所以**同樣不中止本輪**:它次要於
# 分數、匯出與上線,不能因為它擋住當天的價格上線。
if [ "${SKIP_PAIR_PCTILE:-0}" != "1" ]; then
  if run_step "branch-stock-pctile-counts" radar branch-stock-pctile-counts; then
    PAIR_PCTILE_NOTE="ok"
  else
    qrc=$?
    PAIR_PCTILE_NOTE="failed_rc_${qrc}"
    echo "branch-stock-pctile-counts failed rc=$qrc (continue to scores)"
    notify_warn "分點×個股價格分位計數失敗（碼 ${qrc}），仍繼續分數與匯出"
  fi
else
  PAIR_PCTILE_NOTE="skipped_env"
fi

if [ "$EVENING_BRANCH_OK" = "1" ]; then
  SCORES_NOTE="skipped_evening_ok"
  echo "skip compute-scores：${BRANCH_IMPORT_DATE} 那輪已整條跑完並上線（status=${BRANCH_STATUS}，標記 ${MARKER_AT}）"
elif [ "${SKIP_SCORES:-0}" != "1" ]; then
  if run_step "compute-scores" radar compute-scores; then
    SCORES_NOTE="ok"
  else
    src=$?
    SCORES_NOTE="failed_rc_${src}"
    echo "compute-scores failed rc=$src (continue to export)"
    notify_warn "綜合分數重算失敗（碼 ${src}），仍繼續匯出"
  fi
else
  SCORES_NOTE="skipped_env"
fi

# 匯出(export-json)與上線(deploy_data)分開判斷:前者是「今晚是否需要重算」
# (rule 2,evening ok 就跳過),後者是「這批資料能不能上線」(rule 3,22:00
# 那輪 status=error 就不上線)——兩條規則彼此獨立,不能合併成同一個 if。
if [ "$EVENING_BRANCH_OK" = "1" ]; then
  echo "skip export-json：${BRANCH_IMPORT_DATE} 那輪已整條跑完並上線（status=${BRANCH_STATUS}，標記 ${MARKER_AT}）"
elif [ "${SKIP_EXPORT:-0}" != "1" ]; then
  run_step "export-json" radar export-json
fi

if [ "$BRANCH_STATUS" = "error" ]; then
  echo "publish withheld：22:00 那輪 ${BRANCH_IMPORT_DATE} 的分點匯入 status=error，本輪不上線"
  notify_warn "22:00 分點匯入回報 status=error（${BRANCH_IMPORT_DATE}），本輪重算但不上線，待人工確認後再補發"
elif [ "${SKIP_EXPORT:-0}" != "1" ]; then
  run_step "deploy" deploy_data
fi

# 警戒線是「幾點收工」,不是「跑了幾分鐘」。
#
# 要保護的是鎖的下一個主人:週六 05:00 的 weekly-backup。用時長當警戒線會把
# 「撞車」跟「變慢」混為一談 —— 2026-09-15 那晚 start-to-done 是 138 分鐘,
# 其中 28 分鐘只是在等 22:00 那輪放鎖;用 180 分鐘的時長門檻,那晚看起來還好,
# 但它離 05:00 其實比帳面近。收工時刻則兩者都算進去,而且算得對。
#
# 每晚同一個 03:30,所以週六那次違規會提前四個晚上先叫。
FINISHED_AT="$(taipei_date -Is)"
FINISHED_HHMM="$(taipei_date +%H%M)"
# 00:05 起跑,收工必然在同一個日曆日的凌晨;>= 0330 且 < 1200 才算超時,
# 免得極端情況下跨到下午的時刻被當成「沒超過」。
if [ "$FINISHED_HHMM" \> "0330" ] && [ "$FINISHED_HHMM" \< "1200" ]; then
  echo "TRIPWIRE: 夜間作業收在 ${FINISHED_AT}，晚於 03:30"
  notify "夜間分點作業收在 ${FINISHED_HHMM}（晚於 03:30 警戒線）；週六 05:00 週備份會被擠到，請看每步耗時" high "注意"
fi

{
  echo "finished=$FINISHED_AT"
  echo "tripwire_hhmm=$FINISHED_HHMM"
  echo "stats=$STATS_NOTE"
  echo "pit=$PIT_NOTE"
  echo "pair_pctile=$PAIR_PCTILE_NOTE"
  echo "scores=$SCORES_NOTE"
  echo "branch_import_date=$BRANCH_IMPORT_DATE"
  echo "branch_import_status=${BRANCH_STATUS:-missing}"
  echo "branch_import_run_at=${BRANCH_RUN_AT:-missing}"
  echo "evening_round_marker=${MARKER_AT:-missing}"
  echo "evening_round_complete=$EVENING_BRANCH_OK"
  echo "mem_before=$MEM"
  echo "mem_after_pause=$MEM2"
  echo "free_gb_before=$FREE"
} > "$STATE_FILE"

rm -f "$FLAG"
echo "unpause backfill"
unpause_bf_containers

# 起 daemon 之前必須先關掉 fd 9 —— flock 綁在 open file description 上,
# 而下面兩個 nohup 出來的是**常駐**程序,會繼承 fd 9 並讓這把鎖在本腳本
# 結束後仍然被持有。那會讓 14:10/15:00/16:10/17:40/21:20/22:00 每一輪的
# acquire_db_lock 全部搶不到而 exit 0(整條日更停擺),而 bf-cron-guard 用
# fuser 偵測時會看到自己,把回補容器永遠 pause 住。
# 此處 DB 工作已全部結束(stats/pit/pctile/scores/export/deploy 都在上面),
# 所以現在放鎖是安全的。同樣的處理見 manual-catchup.sh:36。
exec 9>&-

if ! pgrep -f 'vps/scripts/bf-cron-guard.sh' >/dev/null 2>&1; then
  nohup bash "$REPO/vps/scripts/bf-cron-guard.sh" >> "${BF_GUARD_LOG:-$HOME/bf-cron-guard.log}" 2>&1 &
fi

if ! pgrep -f 'vps/scripts/bf-supervisor.sh' >/dev/null 2>&1; then
  nohup bash "$REPO/vps/scripts/bf-supervisor.sh" >> "${BF_SUPERVISOR_LOG:-$HOME/bf-supervisor.log}" 2>&1 &
fi

PUBLISH_NOTE="ok"
[ "${SKIP_EXPORT:-0}" = "1" ] && PUBLISH_NOTE="skipped_env"
[ "$BRANCH_STATUS" = "error" ] && PUBLISH_NOTE="withheld_evening_error"
notify_ok "分點排行與分數夜間重算完成（統計=${STATS_NOTE}，帳本=${PIT_NOTE}，分位計數=${PAIR_PCTILE_NOTE}，分數=${SCORES_NOTE}，22:00分點=${BRANCH_STATUS:-missing}，上線=${PUBLISH_NOTE}）"
echo "=== safe-branch-stats done $(taipei_date -Is) ==="
