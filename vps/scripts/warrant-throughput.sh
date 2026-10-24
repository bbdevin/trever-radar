# 權證分點回補吞吐地板的判決(純函式,無副作用;warrant-backfill.sh source 它,
# pipeline/tests/test_warrant_throughput_floor.py 直接 source 它測)。
#
# warrant_throughput_verdict ROWS ELAPSED EMPTY_EXPIRED REQUESTS SLEEP MIN_ELAPSED MIN_RPS
#   印一行 "<verdict> <rows_per_live_sec> <live_elapsed> <sec_per_request>",verdict 是:
#     collapse  未到期部分的列數/秒低於地板 → 呼叫端建暫停檔並告警
#     ok        高於地板
#     skip      扣掉已到期空的時間後剩下的秒數不到 MIN_ELAPSED,樣本太小不判
#
# 為什麼扣掉已到期的空(2026-10-22 事故,docs/30 §5.3):舊日期剩下的待抓目標大多是
# **今天已到期**的權證,鏡像多半已不供它們的頁(probe:三站全零列,不是錯誤頁),
# 每一檔都兩站確認 = 恰好 2 次請求、0 列。不扣的話,地板在舊日期必然誤觸。
# 未到期權證的空不扣——它們才是中毒的訊號,而且 CLI 的空爆量斷路器另外看著。
#
# 每次請求花多久(2026-10-23 誤報,docs/30 §5.3):第一版只扣 2 × SLEEP,但一次請求
# 實際是 sleep + 延遲 + 寫庫,10-23 那塊扣不夠就又誤觸了。現在用本塊自己量的
# ELAPSED / REQUESTS(CLI 摘要行的 `requests=`,實際發出的請求數;skipped_expired
# 不花請求、不在裡面)當每次請求的成本,扣 EMPTY_EXPIRED × 2 × 該成本。等同於
# 「只在未到期那部分請求所佔的時間上判 rows/s」,非請求的開銷(開容器、算目標)按
# 比例攤。
#
# 解析不到時的退路(失敗方向一律是「可能誤報」,不是「漏報」):
#   REQUESTS 解析不到(0)或與 EMPTY_EXPIRED 對不上(< 2 × EMPTY_EXPIRED)
#     → 每次請求當 SLEEP 秒(下界,扣得比實際少)
#   EMPTY_EXPIRED 解析不到(0) → 一分都不扣 = 舊判決
warrant_throughput_verdict() {
  local rows="$1" elapsed="$2" empty_expired="$3" requests="$4" sleep_s="$5" min_elapsed="$6" min_rps="$7"
  awk -v r="$rows" -v e="$elapsed" -v x="$empty_expired" -v q="$requests" -v s="$sleep_s" \
      -v me="$min_elapsed" -v mr="$min_rps" 'BEGIN {
    cost = (q > 0 && q >= 2 * x) ? e / q : s
    live = e - x * 2 * cost
    if (live < 0) live = 0
    if (live <= me) { printf "skip %.2f %d %.3f\n", (live > 0 ? r / live : 0), live, cost; exit }
    rps = r / live
    printf "%s %.2f %d %.3f\n", (rps < mr ? "collapse" : "ok"), rps, live, cost
  }'
}
