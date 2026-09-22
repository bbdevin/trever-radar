#!/usr/bin/env bash
# 15:00 台北(週一–五)— 上櫃日K 補抓。14:10 dailyQuotes 常尚未出表;約 14:57 起才有完整表。
# 上市 14:10 已進庫(upsert 冪等);此輪讓上櫃追上並重算指標/分數後上線。
source "$(dirname "$0")/lib.sh"

# 本輪失敗的後果(接在 run_step_or_fail 的「本輪中止、未上線」之後)。
# 依據:16:10 的 daily-insti.sh 會再抓一次 `import-daily --datasets quotes`
# (它自己分級 0/75 的那一步),然後同樣跑 aggregate-warrants → compute-indicators
# → compute-scores → export-json → deploy_data(crontab `10 16 * * 1-5`)。
# 所以本輪掛掉是「上櫃日K晚 70 分鐘」,不是「今天沒有上櫃日K」。
set_round_consequence "網站停在上一輪（通常是 14:10，只有上市日K），上櫃日K 尚未補上；16:10 三大法人輪會再抓一次上櫃日K並重算上線"

acquire_db_lock
sync_code

# 每一步都走 run_step_or_fail(lib.sh)。裸呼叫時失敗發生在 `radar` 這個 shell
# **函式**內部,ERR trap 不繼承進函式,整輪會靜默帶著離開碼死掉——本輪在此之前
# 一則失敗通知都沒有。順帶得到與其他輪同格式的每步耗時。
run_step_or_fail "import-daily" radar import-daily --datasets quotes
run_step_or_fail "aggregate-warrants" radar aggregate-warrants --date "$(taipei_date +%Y%m%d)"
run_step_or_fail "compute-indicators" radar compute-indicators --all --days 5
run_step_or_fail "compute-scores" radar compute-scores
run_step_or_fail "export-json" radar export-json
run_step_or_fail "deploy" deploy_data
notify_ok "上櫃日K已補齊並上線"