#!/usr/bin/env bash
# 14:10 台北(週一–五)— 收盤閃電更新。鏡像 .github/workflows/daily-market.yml。
# 日K/權證成交 14:00 後公布;法人/融資券/分點由後續輪分批補,前端 freshness 標示。
source "$(dirname "$0")/lib.sh"

# 本輪失敗的後果(接在 run_step_or_fail 的「本輪中止、未上線」之後)。
# 依據:15:00 的 daily-tpex-quotes.sh 是本輪這六步的**逐步同款**——同樣
# import-daily --datasets quotes → aggregate-warrants → compute-indicators →
# compute-scores → export-json → deploy_data(crontab `0 15 * * 1-5`)。
# 所以 14:10 整輪掛掉並不需要人工介入,50 分鐘後會被整套重跑一次。
# 唯一不被 15:00 涵蓋的是下面那三個週一補充(題材/地緣/產業別):它們排在
# compute-scores 之後,本輪若死在那之前就整週不會再跑——句尾那個條件子句
# 講的就是這件事,而且不論死在哪一步都成立。
set_round_consequence "網站仍是前一交易日的內容；同樣這六步 15:00 上櫃日K輪會整套再跑一次並補上（週一的題材／地緣／產業別補充若還沒跑到，要等下週一）"

acquire_db_lock
sync_code

# 每一步都走 run_step_or_fail(lib.sh):裸呼叫時 `radar` 是 shell **函式**,
# ERR trap 不繼承進函式,失敗會當場帶著原碼靜默結束——本輪在此之前**沒有任何
# 失敗通知**(weekly_step 只顧那三個週一補充)。順帶拿到與 17:40 / 00:05 同格式
# 的每步耗時,這是本輪(全日最大的一輪)第一次有耗時可看。
run_step_or_fail "import-daily" radar import-daily --datasets quotes
run_step_or_fail "aggregate-warrants" radar aggregate-warrants --date "$(taipei_date +%Y%m%d)"
run_step_or_fail "compute-indicators" radar compute-indicators --all --days 5
run_step_or_fail "compute-scores" radar compute-scores

# 每週一的補充資料更新(鏡像 daily-market.yml 的 Weekly concept-theme refresh)。
#
# 三者都是「每週一次的補充資料」,失敗一律不得中止本輪:這支腳本的主要職責是把
# 當天的日K/指標/分數 export 並上線,若因為一次題材爬蟲或 FinMind 逾時就 abort,
# 等於「每週一次的補充更新失敗 → 當天行情不上線」,代價完全不成比例。
# 用上週的題材配今天的行情,遠好過今天沒有行情。
weekly_step() {
  local label="$1"; shift
  set +e
  "$@"
  local rc=$?
  set -e
  if [ "$rc" -ne 0 ]; then
    echo "${label} failed rc=${rc} (continue: 本輪仍會 export 並上線)"
    notify_warn "每週${label}失敗（碼 ${rc}），沿用既有資料，當日行情照常上線"
  fi
}

if [ "$(taipei_date +%u)" = "1" ]; then
  weekly_step "題材更新" radar import-themes
  weekly_step "分點地緣" radar import-geo
  # 產業別:2,494 檔 active 中曾有 19 檔沒有產業別,且新上市個股永遠不會補上——
  # 這支指令在 2026-09-03 之前從未被任何排程呼叫過(最後一次成功是 2026-07-07)。
  # FinMind TaiwanStockInfo 是一次請求取全清單,成本與其他兩步同級。
  weekly_step "產業別更新" radar import-stock-info
fi

run_step_or_fail "export-json" radar export-json
run_step_or_fail "deploy" deploy_data
notify_ok "收盤行情已更新並上線（上市日K／指標／分數）"