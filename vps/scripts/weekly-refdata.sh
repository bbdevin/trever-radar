#!/usr/bin/env bash
# 週一 11:00 台北 — 每週參考資料:題材分類、分點地緣、產業別(docs/47)。
#
# 為什麼從 14:10 收盤輪搬出來:這三步合計 45–55 分鐘,排在收盤輪 export 之前,
# 每個週一都把上市行情上線拖到 15:00 以後,而且 15:00 上櫃輪 `flock -n` 搶不到鎖
# 整輪靜默消失(上櫃日K要等到 16:10)。三者都不依賴當天行情,11:00 盤中空檔跑完正好。
#
# 只寫 DB、不匯出不上線:下一輪(14:05 收盤輪)的 export 會把新題材/地緣/產業別一起帶上。
# 失敗一律 warn-and-continue(lib.sh weekly_step):用上週的題材配今天的行情,遠好過
# 為了一次爬蟲逾時中止。跑完寫本 ISO 週的標記;daily-market.sh 在 crontab 改好之前
# 看不到標記就會在上線之後自己補跑(過渡期)。
source "$(dirname "$0")/lib.sh"

echo "=== weekly-refdata start $(taipei_date -Is) ==="

acquire_db_lock_wait 1800
sync_code

weekly_step "題材更新" radar import-themes
weekly_step "分點地緣" radar import-geo
# 產業別:新上市個股永遠不會補上——FinMind TaiwanStockInfo 一次請求取全清單。
weekly_step "產業別更新" radar import-stock-info

date -Is > "$(refdata_marker)"
notify_ok "每週題材／地緣／產業別已更新（14:05 收盤輪一起上線）"
echo "=== weekly-refdata done $(taipei_date -Is) ==="
