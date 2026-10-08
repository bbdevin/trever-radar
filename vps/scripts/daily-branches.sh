#!/usr/bin/env bash
# 16:30 + 22:30 台北(週一–五,同一支跑兩次,冪等)— 法人補抓 + 分點全量。
# (docs/47 §8 新排程;舊 crontab 是 17:30/17:40 + 22:00/22:30,本檔在任何時刻都正確。
#  以下註解的「第一輪」「第二輪」指的是當天兩次執行,不是精確時刻。)
# 第一輪先探測分點來源(probe-branch-day,每 10 分鐘**每站各**抽 12 檔),任一站達門檻
# 或到 20:30 才全量爬;爬是**五站平行、不握 DB 鎖、只抓不寫**(暫存檔),抓完再拿鎖
# 照順序寫入、分級、評分、先上線(分點原始資料),再算分點排行統計、第二次上線。
# 收工時若已過 21:00 順手匯入資券。
# 22:30 由 crontab 設 BRANCH_ROUND_MODE=import:第一輪覆蓋率已是 100% → 直接收工;
# 否則匯入,並在第一輪沒上線的日子接手完整鏈(該變數的名字比行為窄,見下面的說明)。
# 融資融券主輪仍是 daily-margin(20:45 起輪詢;TWSE ~21:00 產製)。
# 非交易日(今天沒有日K)兩輪都直接收工,不再重爬 2,672 檔。
source "$(dirname "$0")/lib.sh"

# 本輪失敗的後果(run_step_or_fail 的通知會接在「本輪中止、未上線」之後)。
# 這一句是**這一輪**的收尾契約:完整鏈跑到底才寫完成標記(見 branch_round_marker),
# 沒寫標記的那一天,00:05 的 safe-branch-stats.sh 會重算分點統計並上線。
# 五支日更輪各有各的一句,因為各輪的補救者完全不同——照抄別人的會在最需要準確的
# 那一則通知裡說謊(lib.sh 的 set_round_consequence 有完整理由)。
set_round_consequence "網站仍是前一輪的內容；本輪不寫完成標記，00:05 夜間作業會重算"

# ── 本輪模式:環境變數 BRANCH_ROUND_MODE ────────────────────────────────
#   未設(或任何其他值) = full:完整鏈,與改動前完全相同。手動執行不受影響。
#   import             = **這是當天的第二輪**:先匯入,然後
#                        今天已有完成標記 → 跳過 compute-branch-stats,但**重算
#                        當日評分**並重新匯出上線(compute-scores、
#                        compute-performance、export-json、prune、deploy_data),
#                        **不重寫完成標記**。理由見下面「只刷新當日評分」那段。
#                        今天沒有完成標記 → 下面那條完整鏈原封不動照跑,
#                        收尾一樣寫標記,由這一輪接手當天的上線。
#
# ⚠️ **這個名字比它實際的行為窄,讀的人不要被它騙了**。變數叫 import,但它的意思是
# 「當天的第二輪:匯入,然後只在今天沒人上線過時才上線」,不是「永遠只匯入」。
# 為什麼不改名:設定它的是正式機 crontab 的那一行
# (`BRANCH_ROUND_MODE=import /...daily-branches.sh`),改名就得再動一次 production
# crontab,而那是使用者的決定、要另外核准,不在這次改動的範圍內。所以名字留著,
# 真正的意思寫在這裡——**讀作「當天第二輪」,不要讀作「只匯入」**。
# 第一輪那條 crontab 不設這個變數,維持完整鏈。
#
# 為什麼備援是放在第二輪,而不是把第一輪的地板調鬆:
# withhold 邏輯只能**阻止**上線,它永遠無法**撤回**已經上線的東西。若把第一輪的
# 地板調低、讓它帶著半殘的資料上線,之後第二輪即使看出問題,能做的也只是
# 自己不上線——第一輪已經放上網站的東西還在原地。所以答案是備援,不是更低的地板:
# 第一輪寧可扣留,第二輪資料填齊之後再用**同一道**閘門決定要不要接手上線。
#
# 為什麼第二輪平常不重算分點統計:compute-branch-stats 要 ~10 分鐘(c1616f0 之前 74 分鐘),
# 而它在第二輪算出來的東西幾乎就是第一輪已經算過的。production 實測 stock_stats 列數
# 兩輪之差是 +326/+48/+170/+119/+0/+105 列(基數約 1,136,000,約 0.011%)。
# 第二輪仍然匯入,是因為當晚較晚才補齊的分點資料要進 DB,供 00:05 夜間作業
# 與隔天使用——而且**當天的評分**要用它重算一次(compute-scores 不到一分鐘,
# 加上 export 與 deploy 約 20 分鐘),否則當天評分永久停在缺分點的版本。
BRANCH_ROUND_MODE="${BRANCH_ROUND_MODE:-full}"

# 這一輪屬於哪一天,在**開跑時**就定下來,不能等收工才算。
# 第二輪的完整鏈可能跨過午夜(實測 2026-09-15 那輪 deploy 收在隔天 00:25)——
# 用收工當下的日曆日命名完成標記,會得到 09-16 這個名字,而夜間作業找的是 09-15,
# 於是標記永遠對不上。偏偏「跨過午夜」正是這個標記存在的理由(夜間作業 00:05 起跑,
# 撞上的就是還沒收工的那一輪),等於在唯一需要它的情況下失效。開跑日是資料日。
ROUND_DATE="$(taipei_date +%F)"

# 分點暫存檔(docs/47 §8):抓到的原始列先落在這裡,**不握 DB 鎖**;拿到鎖之後才照順序
# 寫進資料庫。容器內路徑(radar() 把 $REPO/data 掛成 /app/data),主機端刪檔用 HOST 那個。
# 每 50 檔寫一次 checkpoint:抓到一半被硬上限/SIGTERM 砍掉,已抓到的留著,同一天下一次
# --stage-to(第二輪、或人工重跑)從它續抓,只重抓沒抓到的。所以**不在每個離開路徑都刪它**:
# 寫進資料庫之後刪;不合格那一支留著給第二輪續抓;別天的在開輪時清掉。.tmp 一律清。
STAGE_FILE="/app/data/branch-stage-${ROUND_DATE}.json"
STAGE_FILE_HOST="$REPO/data/branch-stage-${ROUND_DATE}.json"
branch_stage_cleanup() {
  rm -f "${STAGE_FILE_HOST}.tmp" 2>/dev/null || true
}
# ⚠️ 清理(trap 與 find)都在**拿到分點來源鎖之後**才做(見下面):鎖拿到之前,今天的
# .tmp 可能正是還在抓的第一輪在寫的檔(2026-10-07 第二次驗證抓到的競賽)。

# 第二輪且今天已有完成標記:失敗後果的那一句**從第一步起**就要換掉。預設那句
# 「00:05 夜間作業會重算」在這裡不成立——safe-branch-stats.sh 看到標記就整夜略過
# (分點統計、評分、匯出都不跑),所以匯入階段失敗時也不能拿它安慰值班的人。
# 網站此時是 21:20 資券輪上線的內容(daily-margin.sh 也跑 compute-scores 與 deploy),
# 不是第一輪的。
REFRESH_CONSEQUENCE="網站維持 21:20 那輪上線的內容,當日評分停在缺晚到分點的版本；完成標記已由 17:40 寫下,夜間作業不會補算評分"
# (條件順序刻意與下面的模式守衛不同:測試以守衛那一行的字面定位它。)
if [ -s "$(branch_round_marker "$ROUND_DATE")" ] && [ "$BRANCH_ROUND_MODE" = "import" ]; then
  set_round_consequence "$REFRESH_CONSEQUENCE"
fi

# 上線 = export → 多方榜 → deploy。兩段式上線(先原始分點、後排行統計)共用這**一份**,
# 不複製第二份——兩份會漂移,漂移的結果是某一次上線悄悄少做一步。
# 裡面每一步都是 run_step_or_fail(失敗 high 通知 + 原碼 exit,函式內 exit 一樣結束整輪);
# build_bull_board 是 warn-and-continue(見 lib.sh),不可包進 run_step_or_fail。
publish_site() {
  run_step_or_fail "export-json" radar export-json
  build_bull_board
  run_step_or_fail "deploy" deploy_data
  # 期貨量異常摘要(docs/38 §7.19):上線之後才送;永不失敗;同一個期貨行情日只送一次
  # (標記檔),所以一輪上線兩次也只會送一則。
  futures_digest
}

# 起訖標記 + 每步計時(run_step 在 lib.sh,與 00:05 的 safe-branch-stats.sh 同一份)。
# 標記格式與其他腳本一致,cron log 裡可以直接用時間定位整輪的邊界。
echo "=== daily-branches start $(taipei_date -Is) ==="

# 等鎖不略過(docs/47):第一輪前面可能還有法人輪在輪詢、第二輪前面可能是資券輪。
# 鎖的順序是**分點來源鎖 → DB 鎖**(docs/47 §8.5):22:30 第二輪撞上還在抓的第一輪時,要在
# **不握 DB 鎖**的情況下等來源鎖(最多 3600 秒)——反過來先拿 DB 鎖再等來源鎖,第一輪
# 抓完要寫入時就拿不到 DB 鎖,兩輪互相等到逾時。其他拿這把來源鎖的腳本
# (warrant-backfill.sh、daily-warrant-branches-poc.sh)都是 flock -n,搶不到就收工,
# 所以沒有人會握著 DB 鎖**等**來源鎖。
acquire_branch_source_lock_wait 3600
# 來源鎖在手:今天的暫存檔沒有別人會寫。現在才清 .tmp(EXIT trap;裝在第一次呼叫 radar
# 之前,lib.sh 的金鑰暫存檔清理會把既有 EXIT trap 串在前面)與別天的暫存檔。
trap 'branch_stage_cleanup' EXIT
branch_stage_cleanup
find "$REPO/data" -maxdepth 1 -name 'branch-stage-*.json*' ! -name "branch-stage-${ROUND_DATE}.json" \
  -delete 2>/dev/null || true
# 探測的連勝數檔(內容帶日期,別天的會被程式自己作廢;這裡只清 .tmp)。
rm -f "$REPO/data/branch-probe-state-latest.json.tmp" 2>/dev/null || true
acquire_db_lock_wait 3600
sync_code

# ── 前置步驟(docs/47 §8.3):哪些失敗可以續跑、哪些必須中止 ──────────────
# 2026-10-06 的事故:這一步只是**補抓**(日K 14:05、法人 16:00 早就進庫),TPEx 一個瞬時的
# ChunkedEncodingError 讓它回 1,舊寫法 run_step_or_fail 把整輪中止,當天分點拖到 ~00:00。
# 現在:失敗而今天的日K已在庫 → warn 續跑;失敗而今天的日K**不在庫** → 這一步就是當天
# 唯一的補救,照舊 high 通知 + 中止(lib.sh run_step_or_fail_unless)。
# 上櫃日K 若 14:45/16:00 仍 empty,此輪再抓,否則 --top 0 會漏掉無當日報價的上櫃。
run_step_or_fail_unless "import-daily" price_date_is_today radar import-daily --datasets quotes,insti

# 非交易日(docs/47):**先匯入、再判斷**。今天的日K在自己匯入之後仍不在庫裡 →
# 休市(或交易所整天沒出表),不爬 2,672 檔、不匯出(09-25、09-28 實測每輪照樣
# 重爬、export + deploy 一份沒變的網站,約 3.5 小時鎖、~5,000 個請求)。
# 不能在匯入之前就判斷:前面幾輪若壞掉(sync_code/docker/來源),本輪自己的日K
# 匯入就是當天唯一的補救,先判斷會把整天靜默丟掉(2026-10-04 驗證者抓到)。
# 用 warn 而不是只寫 log:休市日一則提醒,遠好過真的出事卻沒人知道。
if ! price_date_is_today; then
  notify_warn "匯入後仍沒有今天的日K（休市或交易所未出表），分點輪不爬、不上線"
  echo "=== daily-branches done $(taipei_date -Is) ==="
  exit 0
fi
# 個股期貨當日(docs/38 §7.18;2026-10-02 起接上)。資料不齊時 import-futures-day 回 75 且一列都不寫;
# 本輪尚未齊全只記 log 不通知;第二輪是當天最後一次重試,其後資券輪的官方日報會在下個交易日補上。
# 其他失敗只 warn,不擋本輪。法人輪(16:00 起)已拿到今天的就不再重抓(docs/47)。
futures_day_done() {
  local n=""
  n="$(radar_ro_sql "SELECT COUNT(*) FROM import_logs WHERE dataset = 'futures-day' AND status = 'ok' AND date = ?" "$ROUND_DATE" 2>/dev/null || true)"
  [ "${n:-0}" -gt 0 ] 2>/dev/null
}
if futures_day_done; then
  echo "個股期貨當日已匯入(法人輪),本輪不重抓"
else
  fd_rc=0
  if radar import-futures-day; then :; else fd_rc=$?; fi
  if [ "$fd_rc" -eq 75 ]; then
    echo "個股期貨當日尚未公布齊全(exit 75),第二輪重試;仍未齊則資券輪的官方日報會在下個交易日補上"
  elif [ "$fd_rc" -ne 0 ]; then
    notify_warn "個股期貨當日匯入失敗（exit ${fd_rc}），本輪續跑；資券輪的官方日報會在下個交易日補上"
  fi
fi

# 第二輪且第一輪的覆蓋率已是 100%(完成標記的 coverage_ratio=,docs/47):再爬一次
# 2,672 檔也不會多一列,直接收工。<1.0 或舊格式標記(沒有比例)→
# 照舊重爬並刷新評分;沒有標記 → 照舊接手完整鏈。
# 放在日K/法人與期貨當日**之後**:第二輪仍是期貨當日的最後一次重試,也要補晚到的法人。
# (條件順序刻意把模式判斷放後面:測試以 `if [ "$BRANCH_ROUND_MODE" = "import" ]` 字面定位模式守衛。)
FIRST_ROUND_RATIO="$(branch_marker_coverage_ratio "$ROUND_DATE")"
if awk -v r="${FIRST_ROUND_RATIO:-0}" 'BEGIN { exit !(r + 0 >= 1) }' && [ "$BRANCH_ROUND_MODE" = "import" ]; then
  echo "publish skipped: first round complete (coverage_ratio=${FIRST_ROUND_RATIO})"
  echo "=== daily-branches done $(taipei_date -Is) ==="
  exit 0
fi
# 指標:今天的早在 14:05/14:45/16:00 三輪算過(indicators_daily 有今天)→ 這裡失敗只 warn 續跑;
# 今天的指標不在庫才中止(評分會缺技術分)。
run_step_or_fail_unless "compute-indicators" indicators_date_is_today radar compute-indicators --all --days 5
# 追蹤名單同步(Supabase):失敗沿用既有名單,永遠不擋本輪(CLI 本身也設計成永不失敗)。
run_step_or_warn "seed-branches" radar seed-branches

# ── 分點來源探測 + 平行抓取:這一段**不握 DB 鎖**(docs/47 §8)─────────────
# 探測(docs/47 原則 3;只在第一輪,BRANCH_PROBE=0 = 舊行為直接爬):每 10 分鐘
# **每一站各**抽 12 檔問一次(probe-branch-day,唯讀、不寫 DB;逐站一行 log),一站要**連續兩次**
# ≥11 檔才算就緒(10-08 kgieworld 11/12 → 1/12 → 0 → 10/12 的抖動),**至少 2 站**就緒或到
# 20:30 才全量爬(2 站 0.4 req/s 抓 2,700 檔約 112 分鐘 < 7200 秒硬上限;其餘站在爬的途中
# 待命、連續兩次通過就加入;等第 3 站只會更晚,不會更快——docs/47 §8.8)。
# 等待期間放掉 DB 鎖,只握著分點來源鎖;探測出錯 = 照舊直接爬。
# 抓取(fetch-branch-trades):五站平行、每站一個 worker、單站間隔 = 1.0 × 5 = 5 秒
# (單站節奏與循序輪替相同,來源負載不變),只抓不寫、結果落暫存檔(每 50 檔 checkpoint)。
# 2,000 檔約 33 分鐘,不隨來源變慢而變長(2026-10-05 循序爬 102 分鐘的根因就是一站拖住全部)。
# 這 30–100 分鐘不握 DB 鎖:20:45 資券輪、00:05 夜間作業、mid-backfill-publish 都不必等。
# 硬上限 2 小時(radar_timeout;容器 --init 轉送 SIGTERM,CLI 收到就寫 checkpoint 以 143 離開):
# 超時 = 本步失敗 → 中止,暫存檔留著已抓到的,第二輪從它續抓(成交金額大的先,留在外面的是冷門股)。
release_db_lock
if [ "$BRANCH_ROUND_MODE" != "import" ] && [ "${BRANCH_PROBE:-1}" != "0" ]; then
  if POLL_HOLD_DB_LOCK=0 poll_until "branch-probe" 2030 600 radar_timeout 1200 probe-branch-day --sample 12 --threshold 11 --min-ready-hosts 2 --min-consecutive 2 --sleep 1.0; then
    :
  else
    probe_rc=$?
    if [ "$probe_rc" -eq 75 ]; then
      echo "branch-probe: 20:30 仍未達門檻,照常全量爬(覆蓋率閘門照舊把關)"
    else
      echo "branch-probe: 探測失敗 rc=${probe_rc},照舊直接全量爬"
    fi
  fi
fi
# top=0: 當日有報價的全部 type=stock(不含 ETF),成交金額大的先抓。
# 全市場權證輪尚未通過容量/時間 PoC;過渡池只含標的是 active 普通股的
# 上市認購/認售、當日成交金額至少 100 萬的權證。此模式取代 legacy --warrants Top-N,不能疊加。
run_step_or_fail "fetch-branch-trades" radar_timeout 7200 import-branch-trades --top 0 --warrant-turnover-min 1000000 --sleep 1.0 --workers 5 --stage-to "$STAGE_FILE"
acquire_db_lock_wait 3600

# ── 寫入 + 分級:握著 DB 鎖,只要一兩分鐘 ─────────────────────────────────
# 分點匯入(--from-stage)的離開碼是本輪唯一的判斷依據。
#
# 以前這裡是裸的一行:`import-branch-trades` 在記了 status='error' 之後仍然
# return 0(`_run` 的「never raise」),於是 set -e 看不到任何異常,整條
# compute → export → deploy 照跑,把一批自己知道有問題的資料送上線。
# 2026-09-14 22:54 就是這樣上線的。
#
#   0   全部標的都回來了
#   75  有個別標的失敗,但當日覆蓋率仍在帶內 —— 可以上線,留紀錄
#   76  這一輪一筆都沒抓到(來源掛了),當日可能已被前一輪填滿 —— 可以上線,但要叫醒人
#   其他 當日覆蓋率掉出帶狀範圍,這一天不合格,不重算也不上線
#
# 75 與 76 都「繼續」是刻意的:withhold 一整天 1,987 檔正確的資料,只因為 1 檔
# 抓失敗,比讓那 1 檔的分點面板晚一天還糟;次日第一輪會冪等重抓補齊。
#
# 不合格(`*)`)那一支的措辭與優先權,在進 case 之前就按「本輪是第幾輪」選好,
# 塞進變數。case 仍然只有**一份**(見下面那段註解的理由),分岔只發生在字串上。
#
# 為什麼第一輪的不合格不是 high:有了第二輪備援之後,第一輪掉到地板以下**不需要
# 任何人動手**——第二輪資料填齊會自己接手上線。把它報成「失敗」,正是 75/76 那段
# 註解一直在對抗的「把一個正常結果講成故障」,而警報疲勞的代價是真的故障被忽略。
# 第二輪掉到地板以下才是要叫醒人的事:今天沒有任何一輪上線,而 00:05 的夜間作業
# 只重算、不上線,所以網站要停在昨天的內容直到明天第一輪。
case "$BRANCH_ROUND_MODE" in
  import) unfit_pri="high"    ; unfit_kind="失敗"
          unfit_tail="；今天沒有任何一輪上線,00:05 夜間作業會重算但不會上線" ;;
  *)      unfit_pri="default" ; unfit_kind="注意"
          unfit_tail="；今天的第二輪(22:30)會在資料填齊後接手完整鏈" ;;
esac

# 用 if/then/else 取離開碼,不用 `set +e; …; rc=$?; set -e`。兩者都拿得到碼,
# 差別在 ERR trap:lib.sh 在 source 時就裝了 install_fail_trap,而 `set +e`
# **不會**讓 ERR trap 安靜下來(實測:set +e 之下回 75 仍然觸發)。那會讓每一個
# 「個別標的失敗但可上線」的日子都多送一則 high 優先權的「執行到第 N 行失敗」,
# 把一個正常結果講成故障,也就把 75(一般)與 76(high)的分級整個抵銷掉——
# 正是這個專案一直在對抗的警報疲勞。if 的測試式對 set -e 與 ERR trap 都免疫,
# lib.sh 的 run_step 內部用的就是這個形狀,理由相同。
#
# 包上 run_step 之後這個形狀完全沒變:run_step 內部同樣用 if 取碼,收尾 `return "$rc"`
# 逐位元回傳 radar 的離開碼,於是下面的 branch_rc 拿到的還是 0/75/76/其他 原碼。
#
# 這一步**刻意不用** run_step_or_fail:它的 0/75/76/其他 分級就是下面那個 case,
# 每一種結果都已經有自己的通知(75 一般、76 high、不合格按輪次分級)。套上會
# 自己發通知的 helper,等於每一次非零都先被 helper 報成「本輪中止」再走 case,
# 同一件事送兩則、而且第一則對 75/76 是錯的(它們本來就繼續上線)。
if run_step "import-branch-trades" radar import-branch-trades --from-stage "$STAGE_FILE"; then
  branch_rc=0
else
  branch_rc=$?
fi
case "$branch_rc" in
  0) ;;
  75) notify_warn "分點匯入有個別標的失敗（碼 75），當日覆蓋率仍在帶內，照常上線；次日第一輪會重抓" ;;
  76) notify "分點來源本輪一筆都沒抓到（碼 76），當日資料沿用前一輪，仍照常上線" high "注意" ;;
  *)  notify "分點匯入不合格（碼 ${branch_rc}），本輪不重算也不上線${unfit_tail}" \
             "$unfit_pri" "$unfit_kind"
      exit "$branch_rc" ;;
esac
# 寫進去了,暫存檔就功成身退(不合格那一支留著給第二輪續抓;容器以 root 寫,目錄是使用者的,刪得掉)。
rm -f "$STAGE_FILE_HOST" 2>/dev/null || true

# 以上(匯入 + 上面那個 case)是兩個模式共用的**同一份**實作:離開碼 0/75/76/其他
# 的分級只寫在上面那一個 case 裡,絕不為了 import 模式複製第二份——兩份遲早會漂移,
# 而漂移的後果是某一個模式悄悄把不合格的一天當成正常。
#
# 當天第二輪(BRANCH_ROUND_MODE=import)在這裡分岔,而分岔的依據是**今天上線了沒**:
#
#   今天已有完成標記 → 不重算分點統計、不寫完成標記,只重算當日評分並重新上線。
#     標記的意思是「算完而且上線了」;寫了就會讓 00:05 的夜間備援作業以為今天
#     已經有人算過而整夜略過。
#   今天沒有完成標記 → 本輪接手完整鏈(不 exit,直接落到下面那條鏈)。
#     2026-09-17 第一輪覆蓋率 902/1956 = 46%,掉出 0.5 地板而正確地扣留;
#     來源是健康的,只是太早、還沒公布完。讓第二輪接手,資料填齊就上線。
#
# 用 `-s`(非空)不用 `-f`:標記的內容是完成時刻,一個空檔案代表寫的過程出了事,
# 那不算「今天上線過」,應該讓第二輪接手,而不是信任它而整天不上線。
#
# 這個區塊必須在上面那個離開碼 case **之後**:第二輪若自己也不合格,要在 case 裡
# 就 exit,不能走到這裡來接手——接手的前提是這一輪的資料合格。
#
# ── 今天已上線時:只刷新當日評分(2026-09-24 起)──────────────────────────
# compute-scores 只寫最新一個價格日,當天那一列在隔天就再也不會被重算。於是第一輪
# 匯入不完整的日子(09-22 涵蓋 983/1964、09-23 1441/1958),當天評分就**永久凍結在
# 缺分點的版本**。缺分項時 combine() 把權重重分給其他分項。所以今天已上線時,本輪
# 仍然跳過 compute-branch-stats(0.011% 的差異不值那一步),但重算當日評分並重新上線。
# compute-scores 只讀原始表(branch_trades 等),不依賴 compute-branch-stats 的產出。
# **不重寫完成標記**:標記的內容是「第一次上線的時刻」,夜間作業只看它存不存在。
# ── 第一段上線的門檻(docs/47 §8.8):只有**真的抓齊**的一天才先上線 ──────────
# 10-08 第一段以覆蓋率 0.946 上線,其中約 100 檔是只公布了一半的鏡像站回的假「空」。
# 假空由另一站確認已在程式裡修掉;這裡再加一道:第一段(先於排行統計的快速上線)只在
# 覆蓋率 ≥ 0.98 時做,否則略過第一段、照舊算完排行統計一併上線(與改動前一次上線相同),
# 通知講明覆蓋率。0.5 的扣留地板不動(那是「這一天合不合格」,共用參數)。
# 10-07 循序爬全市場 empty=0,所以 0.98 給的是「幾檔抓失敗」的餘裕,不是給「還沒公布」的。
# 只刷新評分的第二輪(今天已上線)一律上線,不看這個門檻——它的工作就是重新上線。
BRANCH_FAST_PUBLISH_MIN_RATIO="${BRANCH_FAST_PUBLISH_MIN_RATIO:-0.98}"
COVERAGE_RATIO="$(branch_round_coverage_ratio "$ROUND_DATE")"
FAST_PUBLISH=0
if awk -v r="${COVERAGE_RATIO:-0}" -v m="$BRANCH_FAST_PUBLISH_MIN_RATIO" 'BEGIN { exit !(r + 0 >= m + 0) }'; then
  FAST_PUBLISH=1
fi

SCORES_REFRESH=0
if [ "$BRANCH_ROUND_MODE" = "import" ]; then
  if [ -s "$(branch_round_marker "$ROUND_DATE")" ]; then
    SCORES_REFRESH=1
    FAST_PUBLISH=1
    set_round_consequence "$REFRESH_CONSEQUENCE"
    # 只寫 log,不發成功通知:此刻什麼都還沒重算,成功通知在 deploy 之後才發。
    echo "本輪不重算分點統計（BRANCH_ROUND_MODE=import，今天第一輪已上線）：只以補齊的分點重算當日評分並重新上線"
  else
    notify_warn "第一輪未上線（${ROUND_DATE} 無完成標記），本輪接手完整鏈:重算、匯出、上線"
  fi
fi

# 已過 21:00(TWSE ~21:00 產製資券)→ 順手匯入當天資券,讓這一次的評分與上線就帶著它;
# 資券輪(20:45 起在等這把鎖)拿到鎖後看到資券已是今天就直接收工(docs/47)。
# `--require` 上市+上櫃都要到:只到一邊(75)就整個留給資券輪——資券輪只在**兩個市場**
# 今天都有 ok 紀錄時才收工,所以這裡寫進一半不會讓另一半被靜默跳過。
# 抓不到只 warn:資券輪仍會照常輪詢。跨午夜也算「已過 21:00」(資料日以開跑日為準)。
if [ "$(taipei_date +%H)" -ge 21 ] || [ "$(taipei_date +%F)" != "$ROUND_DATE" ]; then
  margin_rc=0
  if radar import-daily --datasets margin --date "${ROUND_DATE//-/}" --require twse:margin,tpex:margin; then
    :
  else
    margin_rc=$?
  fi
  if [ "$margin_rc" -eq 75 ]; then
    echo "資券尚未兩市場到齊(exit 75),留給資券輪輪詢"
  elif [ "$margin_rc" -ne 0 ]; then
    notify_warn "分點輪順手匯入資券失敗（exit ${margin_rc}），資券輪會照常輪詢"
  fi
fi

# ── 第一段上線:今天的分點原始資料 + 當日評分(docs/47 §8.2 兩段式)──────────
# compute-branch-stats(~10 分鐘)**不在**第一次上線的路徑上:個股頁的分點明細、籌碼日報
# 讀的是原始列與評分,排行/分位統計是第二段才更新的東西。先把使用者等的那份送上站。
# 這一段上線的資料是**完整的**(覆蓋率閘門已在上面放行),不是部分日;只有排行統計
# 還是前一版,成功通知裡講明。
run_step_or_fail "compute-scores" radar compute-scores
run_step_or_fail "compute-performance" radar compute-performance
# prune 與其他步驟同一個待遇(high + 中止),理由是**順序**:它排在第一段的 publish_site
# **之前**(兩個模式、兩條路徑都走到;改動前它也在 deploy 之前),所以 prune 失敗的那一輪
# 根本還沒上線——代價與 compute 失敗完全一樣。若哪天把 prune 移到上線之後,這個判斷
# 就要跟著重新做一次。
run_step_or_fail "prune" radar prune
if [ "$FAST_PUBLISH" = 1 ]; then
  publish_site
  # 第一段上線之後,失敗的後果變了:分點明細與評分**已經在網站上**,缺的只有排行統計。
  # 通知要講這句實話,不能再說「網站仍是前一輪的內容」。
  set_round_consequence "分點明細與當日評分已於第一段上線；本輪不寫完成標記，00:05 夜間作業會重算排行統計並上線"
  # 只刷新評分的那一輪到此為止:標記早已由第一輪寫下,內容是第一次上線的時刻,不重寫。
  if [ "$SCORES_REFRESH" = 1 ]; then
    notify_ok "當日評分已用補齊的分點重算並上線（分點統計仍是第一輪版本）"
    echo "=== daily-branches done $(taipei_date -Is) ==="
    exit 0
  fi
  notify_ok "分點籌碼已更新並上線（覆蓋率 ${COVERAGE_RATIO:-unknown}，含法人補抓）；分點排行統計約 25 分鐘後更新"
else
  echo "fast publish skipped: coverage_ratio=${COVERAGE_RATIO:-unknown} < ${BRANCH_FAST_PUBLISH_MIN_RATIO}"
  notify_warn "分點覆蓋率 ${COVERAGE_RATIO:-unknown} 未達 ${BRANCH_FAST_PUBLISH_MIN_RATIO}，不先上線；算完分點排行統計後一併上線（第二輪會再補抓）"
fi

# ── 第二段:分點排行統計 → 上線 → 完成標記(第一段略過時這是本輪唯一一次上線)────
run_step_or_fail "compute-branch-stats" radar compute-branch-stats
publish_site
# 只有走到這裡才算「整輪跑完」。夜間備援作業讀這個標記決定今晚要不要重算,
# 所以它必須在第二段 deploy 之後——在之前寫就等於承諾了一件還沒發生的事。
# 第二行 coverage_ratio=:第二輪(import 模式)讀它決定要不要再爬一次(1.0 = 不必,docs/47)。
# 第一行仍是完成時刻(夜間作業與人讀的都是第一行)。
printf '%s\ncoverage_ratio=%s\n' "$(taipei_date -Is)" "${COVERAGE_RATIO:-unknown}" > "$(branch_round_marker "$ROUND_DATE")"
notify_ok "分點排行統計已更新並上線"
echo "=== daily-branches done $(taipei_date -Is) ==="
