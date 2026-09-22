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
