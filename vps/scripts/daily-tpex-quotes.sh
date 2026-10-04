#!/usr/bin/env bash
# 14:45 台北(週一–五)— 上櫃日K。14:10 時 dailyQuotes 從未出表(12/12),15:00 時 12/12 都有。
# docs/47:14:45 起每 3 分鐘輪詢上櫃日K(要求 ≥ 前一交易日 80% 列數)直到 15:30,
# 到了就重算指標/分數並上線;舊 crontab 的 15:00 一樣適用(截止仍是 15:30)。
# 上市已由 14:05 那輪進庫(upsert 冪等)。
source "$(dirname "$0")/lib.sh"

# 本輪失敗的後果(接在 run_step_or_fail 的「本輪中止、未上線」之後)。
# 依據:16:00 的 daily-insti.sh 會再抓一次 `import-daily --datasets quotes`
# (它自己分級 0/75 的那一步),然後同樣跑 aggregate-warrants → compute-indicators
# → compute-scores → export-json → deploy_data(docs/47 新排程 16:00;舊 crontab 16:10)。
# 所以本輪掛掉是「上櫃日K晚一個多小時」,不是「今天沒有上櫃日K」。
set_round_consequence "網站停在上一輪（通常是 14:05，只有上市日K），上櫃日K 尚未補上；16:00（舊排程 16:10）三大法人輪會再抓一次上櫃日K並重算上線"

# docs/38 §7.18 期貨發布時間量測(唯讀、≤70 秒、永不失敗,見 lib.sh futures_probe)。
# 放在拿鎖之前:等鎖的日子也要量到。
futures_probe

# 等鎖不略過:週一舊排程的題材步驟曾讓本輪 `flock -n` 失敗、整輪上櫃日K消失。
acquire_db_lock_wait 2700
sync_code

# 上市日K今天沒進來(休市,或 14:05 那輪到 14:40 都沒等到)→ 不輪詢,只試一次。
# 休市日沒有理由在這裡等 45 分鐘;真的是上市晚到,下一輪(16:00)還會再抓日K。
TPEX_DEADLINE=1530
if ! price_date_is_today; then
  echo "今天的上市日K不在庫裡：上櫃日K只試一次，不輪詢"
  TPEX_DEADLINE=0000
fi

if poll_until "tpex-quotes" "$TPEX_DEADLINE" 180 run_step "import-daily" radar import-daily --datasets quotes --require tpex:quotes:0.8; then
  :
else
  quotes_rc=$?
  if [ "$quotes_rc" -eq 75 ]; then
    if [ "$TPEX_DEADLINE" = "0000" ]; then
      echo "publish skipped: no change"
      exit 0
    fi
    notify_warn "上櫃日K至 15:30 仍未公布齊全，本輪不發布；16:00 三大法人輪會再抓一次"
    exit 0
  fi
  notify "import-daily 失敗（碼 ${quotes_rc}），本輪中止、未上線；${ROUND_FAIL_CONSEQUENCE}" high "失敗"
  exit "$quotes_rc"
fi
if ! round_has_changes; then
  echo "publish skipped: no change"
  exit 0
fi
run_step_or_fail "aggregate-warrants" radar aggregate-warrants --date "$(taipei_date +%Y%m%d)"
run_step_or_fail "compute-indicators" radar compute-indicators --all --days 5
run_step_or_fail "compute-scores" radar compute-scores
run_step_or_fail "export-json" radar export-json
run_step_or_fail "deploy" deploy_data
notify_ok "上櫃日K已補齊並上線"
