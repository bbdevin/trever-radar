#!/usr/bin/env bash
# 17:40 + 22:00 台北(週一–五,同一支跑兩次,冪等)— 法人補抓 + 分點全量。
# 17:40 跑完整鏈並上線;22:00 由 crontab 設 BRANCH_ROUND_MODE=import:匯入,並在
# 17:40 那輪沒上線的日子接手完整鏈(該變數的名字比行為窄,見下面的說明)。
# 融資融券不在此輪:交由 21:20 daily-margin(TWSE ~21:00 產製)。
# 第二輪改 22:00,讓 21:20 資券先上線、避免搶 lock。
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
#                        **只有在今天還沒有任何一輪上線過時**才續跑完整鏈。
#                        今天已有完成標記 → 到匯入為止:compute-branch-stats、
#                        compute-scores、compute-performance、export-json、prune、
#                        deploy_data 全部不跑,**也不寫完成標記**。
#                        今天沒有完成標記 → 下面那條完整鏈原封不動照跑,
#                        收尾一樣寫標記,由這一輪接手當天的上線。
#
# ⚠️ **這個名字比它實際的行為窄,讀的人不要被它騙了**。變數叫 import,但它的意思是
# 「當天的第二輪:匯入,然後只在今天沒人上線過時才上線」,不是「永遠只匯入」。
# 為什麼不改名:設定它的是正式機 crontab 的那一行
# (`BRANCH_ROUND_MODE=import /...daily-branches.sh`),改名就得再動一次 production
# crontab,而那是使用者的決定、要另外核准,不在這次改動的範圍內。所以名字留著,
# 真正的意思寫在這裡——**讀作「當天第二輪」,不要讀作「只匯入」**。
# 17:40 那條 crontab 不設這個變數,維持完整鏈。
#
# 為什麼備援是放在第二輪,而不是把 17:40 的地板調鬆:
# withhold 邏輯只能**阻止**上線,它永遠無法**撤回**已經上線的東西。若把 17:40 的
# 地板調低、讓它帶著半殘的資料上線,之後 22:00 這輪即使看出問題,能做的也只是
# 自己不上線——17:40 已經放上網站的東西還在原地。那等於把最鬆的閘門裝在唯一
# 分不出「還在填」與「死了一半」的那一輪上。所以答案是備援,不是更低的地板:
# 17:40 寧可扣留,22:00 資料填齊之後再用**同一道**閘門決定要不要接手上線。
#
# 為什麼第二輪平常只匯入:compute-branch-stats 要 ~74 分鐘,而它在 22:00 算出來的
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

# 起訖標記 + 每步計時(run_step 在 lib.sh,與 00:05 的 safe-branch-stats.sh 同一份)。
# 為什麼非有不可:c1616f0 把 compute-branch-stats 的線性掃描換成二分搜尋,profiling
# 說 20 檔從 95.46s 掉到 13.83s,推得出 77 分鐘 → 約 11 分鐘;但那之後夜間作業每晚
# 都走跳過路徑,當天唯一真的跑 compute 的就是本輪——而本輪連一行開始/結束都沒有,
# 於是系統最貴的一步正好在它變成唯一一次的那一刻變成看不見的。
# 標記格式與其他腳本一致,cron log 裡可以直接用時間定位整輪的邊界。
echo "=== daily-branches start $(taipei_date -Is) ==="

acquire_db_lock
acquire_branch_source_lock
sync_code

# 每一步都是 `run_step_or_fail`(lib.sh),**不是**裸的 `run_step`,也不再是
# `run_step … || exit "$?"`。三者的離開碼完全相同,差別只有「失敗時誰講話」:
#   裸的 `radar X`(最早的寫法)與 `run_step … || exit "$?"`:失敗發生在 radar
#     **函式內部**(lib.sh 的 `( exit "$rc" )`),而 ERR trap 不繼承進函式,於是
#     bash 當場帶著原碼結束,**一則通知都不發**——整輪靜默死掉,只有 cron log 記得。
#     22:00 改成只匯入之後,這一輪是當天唯一的重算與上線,靜默失敗等於網站停在
#     昨天直到 00:05 夜間作業約 01:30 才補上,而沒有任何人被告知。
#   裸的 `run_step X`:失敗變成在**頂層**回傳非零,ERR trap 於是觸發,送出一則
#     「執行到第 N 行失敗」——有通知了,但措辭只有行號,而且一旦哪天再包一層就
#     會與別的通知重複(5cb7649 修過的雙重通知)。
#   `run_step_or_fail X`:ERR trap 一樣不觸發(實測),但失敗那一步自己送一則
#     指名步驟與離開碼的 high 通知,然後 `exit "$rc"` 逐位元帶回原碼。
# 九個步驟共用 lib.sh 裡的**那一份**實作,措辭不會在九個地方漂移。
# 上櫃日K 若 14:10/16:10 仍 empty,此輪再抓,否則 --top 0 會漏掉無當日報價的上櫃。
run_step_or_fail "import-daily" radar import-daily --datasets quotes,insti
run_step_or_fail "compute-indicators" radar compute-indicators --all --days 5
run_step_or_fail "seed-branches" radar seed-branches
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
#
# 不合格(`*)`)那一支的措辭與優先權,在進 case 之前就按「本輪是第幾輪」選好,
# 塞進變數。case 仍然只有**一份**(見下面那段註解的理由),分岔只發生在字串上。
#
# 為什麼第一輪的不合格不是 high:有了第二輪備援之後,17:40 掉到地板以下**不需要
# 任何人動手**——22:00 資料填齊會自己接手上線。把它報成「失敗」,正是 75/76 那段
# 註解一直在對抗的「把一個正常結果講成故障」,而警報疲勞的代價是真的故障被忽略。
# 第二輪掉到地板以下才是要叫醒人的事:今天沒有任何一輪上線,而 00:05 的夜間作業
# 只重算、不上線,所以網站要停在昨天的內容直到明天 17:40。
case "$BRANCH_ROUND_MODE" in
  import) unfit_pri="high"    ; unfit_kind="失敗"
          unfit_tail="；今天沒有任何一輪上線,00:05 夜間作業會重算但不會上線" ;;
  *)      unfit_pri="default" ; unfit_kind="注意"
          unfit_tail="；今天的第二輪(22:00)會在資料填齊後接手完整鏈" ;;
esac

# 用 if/then/else 取離開碼,不用 `set +e; …; rc=$?; set -e`。兩者都拿得到碼,
# 差別在 ERR trap:lib.sh 在 source 時就裝了 install_fail_trap,而 `set +e`
# **不會**讓 ERR trap 安靜下來(實測:set +e 之下回 75 仍然觸發)。那會讓每一個
# 「個別標的失敗但可上線」的日子都多送一則 high 優先權的「執行到第 N 行失敗」,
# 把一個正常結果講成故障,也就把 75(一般)與 76(high)的分級整個抵銷掉——
# 正是這個專案一直在對抗的警報疲勞。if 的測試式對 set -e 與 ERR trap 都免疫,
# lib.sh 的 run_step 內部用的就是這個形狀,理由相同。
#
# 包上 run_step 之後這個形狀完全沒變:run_step 內部同樣用 if 取碼(所以 ERR trap
# 一樣不會被觸發,而且它是函式,ERR trap 本來就不繼承進函式),收尾 `return "$rc"`
# 逐位元回傳 radar 的離開碼,於是下面的 branch_rc 拿到的還是 0/75/76/其他 原碼。
# 本輪唯一最貴的那一段(import-branch-trades 與 compute-branch-stats)因此也有了
# 跟夜間作業同格式的 elapsed,而分級邏輯一個字都沒動。
#
# 這一步**刻意不用** run_step_or_fail:它的 0/75/76/其他 分級就是下面那個 case,
# 每一種結果都已經有自己的通知(75 一般、76 high、不合格按輪次分級)。套上會
# 自己發通知的 helper,等於每一次非零都先被 helper 報成「本輪中止」再走 case,
# 同一件事送兩則、而且第一則對 75/76 是錯的(它們本來就繼續上線)。
if run_step "import-branch-trades" radar import-branch-trades --top 0 --warrant-turnover-min 1000000 --sleep 1.0; then
  branch_rc=0
else
  branch_rc=$?
fi
case "$branch_rc" in
  0) ;;
  75) notify_warn "分點匯入有個別標的失敗（碼 75），當日覆蓋率仍在帶內，照常上線；次日 17:40 會重抓" ;;
  76) notify "分點來源本輪一筆都沒抓到（碼 76），當日資料沿用前一輪，仍照常上線" high "注意" ;;
  *)  notify "分點匯入不合格（碼 ${branch_rc}），本輪不重算也不上線${unfit_tail}" \
             "$unfit_pri" "$unfit_kind"
      exit "$branch_rc" ;;
esac

# 以上(匯入 + 上面那個 case)是兩個模式共用的**同一份**實作:離開碼 0/75/76/其他
# 的分級只寫在上面那一個 case 裡,絕不為了 import 模式複製第二份——兩份遲早會漂移,
# 而漂移的後果是某一個模式悄悄把不合格的一天當成正常。
#
# 當天第二輪(BRANCH_ROUND_MODE=import)在這裡分岔,而分岔的依據是**今天上線了沒**:
#
#   今天已有完成標記 → 到此為止:不重算、不匯出、不上線,而且**不寫完成標記**。
#     標記的意思是「算完而且上線了」,這一輪兩件都沒做;寫了就會讓 00:05 的夜間
#     備援作業以為今天已經有人算過而整夜略過,於是這一天從頭到尾沒有任何一輪
#     算過分點統計。
#   今天沒有完成標記 → 本輪接手完整鏈(不 exit,直接落到下面那條鏈)。
#     2026-09-17 17:40 那輪覆蓋率 902/1956 = 46%,掉出 0.5 地板而正確地扣留;
#     來源是健康的,只是 17:40 太早、還沒公布完(當輪 1412 ok / 1054 empty)。
#     在那之前的規則下,22:00 只匯入,於是整天沒有任何一輪上線,一直要等 00:05
#     的夜間作業在 ~01:30 才第一次發布。資料到 22:00 早就填齊了,讓這一輪接手
#     只要 ~00:25 就上線,跟改成純匯入之前的舊排程一樣。
#
# 用 `-s`(非空)不用 `-f`:標記的內容是完成時刻,一個空檔案代表寫的過程出了事,
# 那不算「今天上線過」,應該讓第二輪接手,而不是信任它而整天不上線。
#
# 這個區塊必須在上面那個離開碼 case **之後**:第二輪若自己也不合格,要在 case 裡
# 就 exit,不能走到這裡來接手——接手的前提是這一輪的資料合格。
if [ "$BRANCH_ROUND_MODE" = "import" ]; then
  if [ -s "$(branch_round_marker "$ROUND_DATE")" ]; then
    notify_ok "本輪僅匯入分點與法人資料（BRANCH_ROUND_MODE=import）：未重算、未匯出、未上線,網站仍是 17:40 那輪的內容"
    echo "=== daily-branches done $(taipei_date -Is) ==="
    exit 0
  fi
  notify_warn "17:40 那輪未上線（${ROUND_DATE} 無完成標記），本輪接手完整鏈:重算、匯出、上線"
fi

run_step_or_fail "compute-branch-stats" radar compute-branch-stats
run_step_or_fail "compute-scores" radar compute-scores
run_step_or_fail "compute-performance" radar compute-performance
run_step_or_fail "export-json" radar export-json
# prune 與其他步驟同一個待遇(high + 中止),理由是**順序**:它排在 deploy_data
# **之前**,所以 prune 失敗的那一輪根本還沒上線——代價與 compute 失敗完全一樣,
# 是「今天沒有任何一輪上線」,不是「已經上線了只差收尾」。若哪天把 prune 移到
# deploy_data 之後,這個判斷就要跟著重新做一次:那時它才會變成「資料已經在網站上,
# 只是 DB 沒瘦身」,而那不值得用跟上線失敗同一級的警報去叫醒人。
run_step_or_fail "prune" radar prune
run_step_or_fail "deploy" deploy_data
# 只有走到這裡才算「整輪跑完」。夜間備援作業讀這個標記決定今晚要不要重算,
# 所以它必須在 deploy_data 之後——在之前寫就等於承諾了一件還沒發生的事。
taipei_date -Is > "$(branch_round_marker "$ROUND_DATE")"
notify_ok "分點籌碼已更新並上線（含法人補抓）"
echo "=== daily-branches done $(taipei_date -Is) ==="
