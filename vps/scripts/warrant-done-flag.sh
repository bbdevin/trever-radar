# 權證分點回補的「今天已完成」判定(2026-10-29,docs/30 §6.2 每日增量)。
#
# 以前完成標記是空檔,存在就永久略過:10-25 回補到 70 日深度後就再也不跑,10-27 起新的
# 交易日只剩日更輪的成交 ≥ 100 萬權證池(~580 檔,全市場 ~1.6 萬檔),5/30/120 日累計
# 與仍持有(估)開始新舊混雜。現在標記內容 = 完成那天的台北日期:同一天內略過(cron 每
# 20 分呼叫,別每次都 pause/unpause),隔天重新問一次——CLI 已完成的日期零請求跳過,
# 只會抓到 min-age 剛放行的新交易日。舊的空標記(內容不是今天)= 未完成,下一次照跑。
#
# 由 warrant-backfill.sh source;獨立成檔是為了讓測試能在不碰 docker/SQLite 的情況下
# 用真的 bash 執行這個判定(同 warrant-throughput.sh)。

# warrant_done_for_today FLAG TODAY → 0 = 標記第一行恰為 TODAY(今天已完成,略過)。
warrant_done_for_today() {
  local flag="$1" today="$2" line=""
  [ -f "$flag" ] || return 1
  IFS= read -r line < "$flag" || true
  [ "$line" = "$today" ]
}
