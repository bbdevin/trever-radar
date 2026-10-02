#!/usr/bin/env bash
# 16:10 台北(週一–五)— 法人買賣超 + 權證主檔;上櫃日K 保底再抓(主輪在 15:00)。
# 權證主檔偶發 timeout 不得擋正常發布；TPEx 520 部分行情則本輪不發布。
source "$(dirname "$0")/lib.sh"

# 本輪失敗的後果(接在 run_step_or_fail 的「本輪中止、未上線」之後)。
# 依據:17:40 的 daily-branches.sh 第一步就是
# `radar import-daily --datasets quotes,insti`,而且那一輪會跑完 compute → export
# → deploy_data(crontab `40 17 * * 1-5`)。所以本輪掛掉 = 法人晚 90 分鐘上線,
# 不需要人工介入。注意 aggregate-warrants 不在 17:40 那輪裡,但 15:00 已經用
# 同一個 --date 跑過同一天的彙總(冪等),本輪那一次是刷新而非唯一機會。
set_round_consequence "網站停在 15:00 那輪的內容，三大法人未上線；17:40 分點輪會再匯入一次三大法人並重算上線"

# docs/38 §7.18 期貨發布時間量測(唯讀、≤70 秒、永不失敗,見 lib.sh futures_probe)。
# 放在拿鎖之前:鎖被占而略過本輪、或下面 exit 75 提早收場的日子也要量到。
futures_probe

acquire_db_lock
sync_code

# 15:00 主抓上櫃日K;此處再抓一次當保底(empty 無害)。只有「TWSE 成功、
# TPEx 唯一 HTTP 520」會回 75，保留已入庫行情並讓法人／主檔照常跑。
quotes_rc=0
if radar import-daily --datasets quotes; then
  :
else
  quotes_rc=$?
fi
if [ "$quotes_rc" -ne 0 ] && [ "$quotes_rc" -ne 75 ]; then
  notify "日K匯入失敗（exit ${quotes_rc}），請查看 ~/radar-cron.log" high "失敗"
  exit "$quotes_rc"
fi
if [ "$quotes_rc" -eq 75 ]; then
  notify_warn "TWSE 行情已入庫；TPEx HTTP 520，先續跑三大法人與權證主檔"
fi
# 上面那一步(日K)刻意**不**走 run_step_or_fail:它已經自己分級 0/75/其他,
# 每一種結果都有自己的通知。以下各步才是原本裸呼叫、失敗完全沒聲音的部分
# (`radar` 是 shell 函式,ERR trap 不繼承進函式)。
run_step_or_fail "import-insti" radar import-daily --datasets insti
# 權證主檔偶發 timeout 不得擋法人/日K 上線。無論成功與否都在
# 其後彙總：成功時採新主檔；失敗時沿用既有主檔。
if ! radar import-warrant-master; then
  notify_warn "權證主檔暫時抓不到，已略過；請在後續輪重試"
fi
# 庫藏股(MOPS t35sc09,近一年;docs/37 E1)。2026-10-02 使用者決定每日更新——
# 原本只在 09-03 手動跑過一次,之後新公告的計畫網站上都沒有。抓不到就 warn
# 並沿用既有資料,不得擋法人上線;匯入是 atomic,失敗零寫入。
if ! radar import-buybacks --days 365; then
  notify_warn "庫藏股公告暫時抓不到，已略過，沿用既有資料"
fi
# 個股期貨當日(docs/38 §7.18;2026-10-02 起接上)。資料不齊時 import-futures-day 回 75 且一列都不寫;
# 16:10 常常還沒公布,所以 75 只記 log 不通知;17:40／22:00 會重試。其他失敗只 warn,不擋法人上線。
fd_rc=0
if radar import-futures-day; then :; else fd_rc=$?; fi
if [ "$fd_rc" -eq 75 ]; then
  echo "個股期貨當日尚未公布齊全(exit 75),17:40／22:00 重試"
elif [ "$fd_rc" -ne 0 ]; then
  notify_warn "個股期貨當日匯入失敗（exit ${fd_rc}），本輪續跑；17:40／22:00 會重試"
fi
if [ "$quotes_rc" -eq 75 ]; then
  notify_warn "部分已入庫，因TPEx行情未完整，本輪不發布（不做aggregate/compute/export/deploy），待17:40"
  exit 75
fi
run_step_or_fail "aggregate-warrants" radar aggregate-warrants --date "$(taipei_date +%Y%m%d)"
run_step_or_fail "compute-indicators" radar compute-indicators --all --days 5
run_step_or_fail "compute-scores" radar compute-scores
run_step_or_fail "export-json" radar export-json
run_step_or_fail "deploy" deploy_data
notify_ok "三大法人資料已更新並上線"
