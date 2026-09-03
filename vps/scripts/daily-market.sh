#!/usr/bin/env bash
# 14:10 台北(週一–五)— 收盤閃電更新。鏡像 .github/workflows/daily-market.yml。
# 日K/權證成交 14:00 後公布;法人/融資券/分點由後續輪分批補,前端 freshness 標示。
source "$(dirname "$0")/lib.sh"

acquire_db_lock
sync_code

radar import-daily --datasets quotes
radar aggregate-warrants --date "$(taipei_date +%Y%m%d)"
radar compute-indicators --all --days 5
radar compute-scores

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

radar export-json
deploy_data
notify_ok "收盤行情已更新並上線（上市日K／指標／分數）"