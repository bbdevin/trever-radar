# 權證分點回補吞吐地板的判決(純函式,無副作用;warrant-backfill.sh source 它,
# pipeline/tests/test_warrant_throughput_floor.py 直接 source 它測)。
#
# warrant_throughput_verdict ROWS ELAPSED EMPTY_EXPIRED SLEEP MIN_ELAPSED MIN_RPS
#   印一行 "<verdict> <rows_per_live_sec> <live_elapsed>",verdict 是:
#     collapse  未到期部分的列數/秒低於地板 → 呼叫端建暫停檔並告警
#     ok        高於地板
#     skip      扣掉已到期空的時間後剩下的秒數不到 MIN_ELAPSED,樣本太小不判
#
# 為什麼扣掉已到期的空(2026-10-22 事故,docs/30 §5.3):舊日期剩下的待抓目標大多是
# **今天已到期**的權證,鏡像多半已不供它們的頁(probe:三站全零列,不是錯誤頁),
# 每一檔都兩站確認 = 至少 2 × SLEEP 秒、0 列。不扣的話,地板在舊日期必然誤觸
# (10-22 12:46 那則就是誤報)。未到期權證的空不扣——它們才是中毒的訊號,而且
# CLI 的空爆量斷路器另外看著。
#
# EMPTY_EXPIRED 解析不到(欄位改名、舊 CLI)時呼叫端傳 0 → 一分都不扣,退回舊判決:
# 失敗方向是「可能誤報」,不是「漏報」。
warrant_throughput_verdict() {
  local rows="$1" elapsed="$2" empty_expired="$3" sleep_s="$4" min_elapsed="$5" min_rps="$6"
  awk -v r="$rows" -v e="$elapsed" -v x="$empty_expired" -v s="$sleep_s" \
      -v me="$min_elapsed" -v mr="$min_rps" 'BEGIN {
    live = e - x * 2 * s
    if (live < 0) live = 0
    if (live <= me) { printf "skip %.2f %d\n", (live > 0 ? r / live : 0), live; exit }
    rps = r / live
    printf "%s %.2f %d\n", (rps < mr ? "collapse" : "ok"), rps, live
  }'
}
