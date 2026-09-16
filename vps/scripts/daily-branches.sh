#!/usr/bin/env bash
# 17:40 + 22:00 台北(週一–五,同一支跑兩次,冪等)— 法人補抓 + 分點全量。
# 17:40 跑完整鏈並上線;22:00 由 crontab 設 BRANCH_ROUND_MODE=import,只匯入(見下)。
# 融資融券不在此輪:交由 21:20 daily-margin(TWSE ~21:00 產製)。
# 第二輪改 22:00,讓 21:20 資券先上線、避免搶 lock。
source "$(dirname "$0")/lib.sh"

# ── 本輪模式:環境變數 BRANCH_ROUND_MODE ────────────────────────────────
#   未設(或任何其他值) = full:完整鏈,與改動前完全相同。手動執行不受影響。
#   import             = 只匯入:import-daily / compute-indicators / seed-branches /
#                        import-branch-trades 照跑,compute-branch-stats、
#                        compute-scores、compute-performance、export-json、prune、
#                        deploy_data 全部不跑,**也不寫完成標記**。
#
# 設定它的是 22:00 那一條 crontab(`BRANCH_ROUND_MODE=import /...daily-branches.sh`);
# 17:40 那條不設,維持完整鏈。
#
# 為什麼 22:00 只匯入:compute-branch-stats 要 ~74 分鐘,而它在 22:00 算出來的
# 東西幾乎就是 17:40 已經算過的。production 實測 stock_stats 列數 17:40→22:00
# 的差是 +326/+48/+170/+119/+0/+105 列(基數約 1,136,000,約 0.011%),而 22:00
# 那輪要到隔天 00:25 才上線。17:40 那輪 20:30 左右就上線,使用者還醒著;為了
# 0.011% 的差異讓第二輪再跑一次 74 分鐘、並在深夜佔住 DB 鎖,不划算。
# 22:00 仍然匯入,是因為當晚較晚才補齊的分點資料要進 DB,供 00:05 夜間作業
# 與隔天使用。
BRANCH_ROUND_MODE="${BRANCH_ROUND_MODE:-full}"

# 這一輪屬於哪一天,在**開跑時**就定下來,不能等收工才算。
# 22:00 那輪的 compute-branch-stats 要跑一個多小時,實測 2026-09-15 那輪的
# deploy 收在隔天 00:25 —— 用收工當下的日曆日命名完成標記,會得到 09-16 這個
# 名字,而夜間作業找的是 09-15,於是標記永遠對不上。偏偏「跨過午夜」正是這個
# 標記存在的理由(夜間作業 00:05 起跑,撞上的就是還沒收工的那一輪),等於在
# 唯一需要它的情況下失效。開跑日是資料日:17:40 與 22:00 兩輪都在當天交易日內。
ROUND_DATE="$(taipei_date +%F)"

acquire_db_lock
acquire_branch_source_lock
sync_code

# 上櫃日K 若 14:10/16:10 仍 empty,此輪再抓,否則 --top 0 會漏掉無當日報價的上櫃。
radar import-daily --datasets quotes,insti
radar compute-indicators --all --days 5
radar seed-branches
# top=0: 當日有報價的全部 type=stock(不含 ETF)。
# 全市場權證輪尚未通過容量/時間 PoC；過渡池只含標的是 active 普通股的
# 上市認購／認售、當日成交金額至少 100 萬的權證。此模式取代 legacy --warrants Top-N，不能疊加。
# 分點匯入的離開碼是本輪唯一的判斷依據。
#
# 以前這裡是裸的一行:`import-branch-trades` 在記了 status='error' 之後仍然
# return 0（`_run` 的「never raise」),於是 set -e 看不到任何異常,整條
# compute → export → deploy 照跑,把一批自己知道有問題的資料送上線。
# 2026-09-14 22:54 就是這樣上線的。
#
#   0   全部標的都回來了
#   75  有個別標的失敗,但當日覆蓋率仍在帶內 —— 可以上線,留紀錄
#   76  這一輪一筆都沒抓到(來源掛了),當日可能已被前一輪填滿 —— 可以上線,但要叫醒人
#   其他 當日覆蓋率掉出帶狀範圍,這一天不合格,不重算也不上線
#
# 75 與 76 都「繼續」是刻意的:withhold 一整天 1,987 檔正確的資料,只因為 1 檔
# 抓失敗,比讓那 1 檔的分點面板晚一天還糟;次日 17:40 會冪等重抓補齊。
# 這裡必須顯式 set +e 取 rc,不能靠 set -e —— set -e 對 75 跟對 1 一樣是直接中止,
# 那等於把「可上線」判成「不可上線」,方向剛好相反。
set +e
radar import-branch-trades --top 0 --warrant-turnover-min 1000000 --sleep 1.0
branch_rc=$?
set -e
case "$branch_rc" in
  0) ;;
  75) notify_warn "分點匯入有個別標的失敗（碼 75），當日覆蓋率仍在帶內，照常上線；次日 17:40 會重抓" ;;
  76) notify "分點來源本輪一筆都沒抓到（碼 76），當日資料沿用前一輪，仍照常上線" high "注意" ;;
  *)  notify "分點匯入不合格（碼 ${branch_rc}），本輪不重算也不上線" high "失敗"
      exit "$branch_rc" ;;
esac

# 以上(匯入 + 上面那個 case)是兩個模式共用的**同一份**實作:離開碼 0/75/76/其他
# 的分級只寫在上面那一個 case 裡,絕不為了 import 模式複製第二份——兩份遲早會漂移,
# 而漂移的後果是某一個模式悄悄把不合格的一天當成正常。
#
# import 模式到此為止:不重算、不匯出、不上線。
# 而且**不寫完成標記**。標記的意思是「算完而且上線了」,這一輪兩件都沒做;
# 寫了就會讓 00:05 的夜間備援作業以為今天已經有人算過而整夜略過,
# 於是這一天從頭到尾沒有任何一輪算過分點統計。
if [ "$BRANCH_ROUND_MODE" = "import" ]; then
  notify_ok "本輪僅匯入分點與法人資料（BRANCH_ROUND_MODE=import）：未重算、未匯出、未上線,網站仍是 17:40 那輪的內容"
  exit 0
fi

radar compute-branch-stats
radar compute-scores
radar compute-performance
radar export-json
radar prune
deploy_data
# 只有走到這裡才算「整輪跑完」。夜間備援作業讀這個標記決定今晚要不要重算,
# 所以它必須在 deploy_data 之後——在之前寫就等於承諾了一件還沒發生的事。
taipei_date -Is > "$(branch_round_marker "$ROUND_DATE")"
notify_ok "分點籌碼已更新並上線（含法人補抓）"
