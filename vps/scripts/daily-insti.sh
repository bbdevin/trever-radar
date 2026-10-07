#!/usr/bin/env bash
# 16:00 台北(週一–五)— 法人買賣超 + 權證主檔;上櫃日K 保底再抓(主輪在 14:45)。
# docs/47:16:00 起每 5 分鐘輪詢三大法人(上市＋上櫃都要到)直到 17:10;每次嘗試順手試
# 個股期貨當日。實測上市法人 16:10 只有 5/12 天到、17:40 12/12,舊排程 7/12 天要等到
# 分點輪(約 20:30 以後)才上線。舊 crontab 的 16:10 一樣適用(截止仍是 17:10)。
# 權證主檔偶發 timeout 不得擋正常發布；TPEx 520 部分行情則本輪不發布。
source "$(dirname "$0")/lib.sh"

# 本輪失敗的後果(接在 run_step_or_fail 的「本輪中止、未上線」之後)。
# 依據:17:30(舊排程 17:40)的 daily-branches.sh 第一步就是
# `radar import-daily --datasets quotes,insti`,而且那一輪會跑完 compute → export
# → deploy_data。所以本輪掛掉 = 法人晚幾個小時上線,不需要人工介入。注意
# aggregate-warrants 不在分點輪裡,但上櫃日K輪已經用同一個 --date 跑過同一天的彙總
# (冪等),本輪那一次是刷新而非唯一機會。
set_round_consequence "網站停在上櫃日K那輪的內容，三大法人未上線；17:30（舊排程 17:40）分點輪會再匯入一次三大法人並重算上線"

acquire_db_lock_wait 2700
sync_code

# 14:45 主抓上櫃日K;此處再抓一次當保底(empty 無害)。只有「TWSE 成功、
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

# 個股期貨當日(docs/38 §7.18;2026-10-02 起接上)。資料不齊時 import-futures-day 回 75 且一列都不寫;
# 本輪輪詢法人的每一次嘗試都順手試一次,75 只記 log 不通知,拿到 0 就不再試;
# 其他失敗只 warn,不擋法人上線。本輪結束仍未齊 → 17:30 分點輪重試。
FD_DONE=0
try_futures_day() {
  local fd_rc=0
  if radar import-futures-day; then :; else fd_rc=$?; fi
  if [ "$fd_rc" -eq 75 ]; then
    echo "個股期貨當日尚未公布齊全(exit 75),下次嘗試再試;本輪結束仍未齊則 17:30 分點輪重試"
  elif [ "$fd_rc" -ne 0 ]; then
    notify_warn "個股期貨當日匯入失敗（exit ${fd_rc}），本輪續跑；17:30 分點輪會重試"
    FD_DONE=1
  fi
  if [ "$fd_rc" -eq 0 ]; then
    FD_DONE=1
  fi
}

# poll_until 的一次嘗試:三大法人(上市＋上櫃都要 rows>0)+ 期貨當日(還沒拿到才試)。
# 回傳法人那一步的碼:0 到齊、75 還沒、其他 = 錯誤(由下面分級)。
insti_attempt() {
  local rc=0
  if run_step "import-insti" radar import-daily --datasets insti --require twse:insti,tpex:insti; then
    rc=0
  else
    rc=$?
  fi
  if [ "$FD_DONE" = "0" ]; then
    try_futures_day
  fi
  return "$rc"
}

# 今天的日K不在庫裡(休市)→ 只試一次,不輪詢 70 分鐘。
INSTI_DEADLINE=1710
if ! price_date_is_today; then
  echo "今天的日K不在庫裡：三大法人只試一次，不輪詢"
  INSTI_DEADLINE=0000
fi
insti_rc=0
if poll_until "insti" "$INSTI_DEADLINE" 300 insti_attempt; then
  :
else
  insti_rc=$?
fi
# 上面那一步(法人輪詢)刻意**不**走 run_step_or_fail:75 是「還沒到」不是失敗。
# 其他非 0 才是錯誤:與舊版 run_step_or_fail 同一句話、同一個原碼。
if [ "$insti_rc" -ne 0 ] && [ "$insti_rc" -ne 75 ]; then
  notify "import-insti 失敗（碼 ${insti_rc}），本輪中止、未上線；${ROUND_FAIL_CONSEQUENCE}" high "失敗"
  exit "$insti_rc"
fi

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
if [ "$quotes_rc" -eq 75 ]; then
  notify_warn "部分已入庫，因TPEx行情未完整，本輪不發布（不做aggregate/compute/export/deploy），待17:30"
  exit 75
fi
if [ "$insti_rc" -eq 75 ]; then
  if [ "$INSTI_DEADLINE" = "0000" ] || ! round_has_changes; then
    echo "publish skipped: no change"
    exit 0
  fi
  # 截止仍缺上市(或上櫃)法人:已到的(通常是上櫃法人、期貨、權證主檔)照舊上線,
  # 不讓它們陪著等到分點輪 20:30 以後——舊 16:10 輪也是這樣先上線上櫃法人。
  notify_warn "三大法人至 17:10 仍未公布齊全，先上線已到的部分；17:30 分點輪會再抓"
fi
run_step_or_fail "aggregate-warrants" radar aggregate-warrants --date "$(taipei_date +%Y%m%d)"
run_step_or_fail "compute-indicators" radar compute-indicators --all --days 5
run_step_or_fail "compute-scores" radar compute-scores
run_step_or_fail "export-json" radar export-json
build_bull_board
run_step_or_fail "deploy" deploy_data
# 期貨量異常摘要(docs/38 §7.19):上線之後才送;永不失敗,同一個期貨行情日只送一次。
futures_digest
notify_ok "三大法人資料已更新並上線"
