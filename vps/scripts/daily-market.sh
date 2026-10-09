#!/usr/bin/env bash
# 14:05 台北(週一–五)— 收盤閃電更新。鏡像 .github/workflows/daily-market.yml。
# 日K/權證成交 14:00 後公布;法人/融資券/分點由後續輪分批補,前端 freshness 標示。
# docs/47:14:05 起每 3 分鐘輪詢上市日K直到 14:40(實測 14:10 已 12/12 到齊),
# 到了就立刻算、匯出、上線;舊 crontab 的 14:10 一樣適用(截止仍是 14:40)。
source "$(dirname "$0")/lib.sh"

# 本輪失敗的後果(接在 run_step_or_fail 的「本輪中止、未上線」之後)。
# 依據:14:45 的 daily-tpex-quotes.sh 是本輪這幾步的**逐步同款**——同樣
# import-daily --datasets quotes → aggregate-warrants → compute-indicators →
# compute-scores → export-json → deploy_data(docs/47 新排程 14:45;舊 crontab 15:00)。
# 所以本輪整輪掛掉並不需要人工介入,上櫃日K輪會把整套重跑一次。
# 週一的題材/地緣/產業別已搬到週一 11:00 weekly-refdata.sh;crontab 還沒改的過渡期
# 本輪在 deploy 之後補跑,死在那之前就要等那支或下週一。
set_round_consequence "網站仍是前一交易日的內容；同樣這幾步 14:45（舊排程 15:00）上櫃日K輪會整套再跑一次並補上"

acquire_db_lock_wait 1800
sync_code

# 每週一的補充資料(題材/地緣/產業別)已搬到週一 11:00 的 weekly-refdata.sh
# (docs/47:以前排在 export 之前跑 45–55 分鐘,15:00 上櫃輪因此搶不到鎖整輪消失)。
# 過渡:正式機 crontab 還沒加那一行時,本 ISO 週沒有完成標記 → 本輪補跑,而且排在
# 上線之後,行情不再被它擋住。**本輪不上線的出口(截止仍沒日K、沒有變動)也要補跑**:
# 週一休市時本輪一定走那些出口,不補就整週沒有題材更新。呼叫時一律握著 DB 鎖
# (poll_until 截止回 75 時仍握著鎖)。失敗一律 warn-and-continue(lib.sh weekly_step)。
refdata_catchup() {
  if [ "$(taipei_date +%u)" = "1" ] && [ ! -e "$(refdata_marker)" ]; then
    weekly_step "題材更新" radar import-themes
    weekly_step "分點地緣" radar import-geo
    # 產業別:新上市個股永遠不會補上——FinMind TaiwanStockInfo 一次請求取全清單。
    weekly_step "產業別更新" radar import-stock-info
    date -Is > "$(refdata_marker)"
  fi
}

# 輪詢上市日K(lib.sh poll_until):沒到(import-daily 回 75)就放鎖、3 分鐘後再試,
# 到 14:40 仍沒有 → 不算不上線,只 warn。其他錯誤(1 等)= 原碼,照舊 high + 中止。
if poll_until "twse-quotes" 1440 180 run_step "import-daily" radar import-daily --datasets quotes --require twse:quotes; then
  :
else
  quotes_rc=$?
  if [ "$quotes_rc" -eq 75 ]; then
    notify_warn "上市日K至 14:40 仍未公布，本輪不發布（若今天休市可忽略）；14:45 上櫃日K輪會再抓"
    refdata_catchup
    exit 0
  fi
  notify "import-daily 失敗（碼 ${quotes_rc}），本輪中止、未上線；${ROUND_FAIL_CONSEQUENCE}" high "失敗"
  exit "$quotes_rc"
fi
if ! round_has_changes; then
  echo "publish skipped: no change"
  refdata_catchup
  exit 0
fi
run_step_or_fail "aggregate-warrants" radar aggregate-warrants --date "$(taipei_date +%Y%m%d)"
run_step_or_fail "compute-indicators" radar compute-indicators --all --days 5
run_step_or_fail "compute-scores" radar compute-scores
# 加權/櫃買指數與台指期近月(docs/49 §11.3/§12):冪等 upsert;尚未公布回 75 只 warn,不擋上線。
run_step_or_warn "import-index" radar import-index
run_step_or_fail "export-json" radar export-json
build_bull_board
run_step_or_fail "deploy" deploy_data
notify_ok "收盤行情已更新並上線（上市日K／指標／分數）"
refdata_catchup
