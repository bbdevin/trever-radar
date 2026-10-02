#!/usr/bin/env bash
# ⚠️ GATED — 尚未啟用。本檔**不在 crontab、也不被任何其他腳本呼叫**,
# 直到 docs/38 §7.18 的發布時間量測做完(lib.sh futures_probe 在 14:10 / 15:00 /
# 16:10 三輪開頭各量一次,寫 ~/futures-probe.log,至少 3 個交易日)。
# 量測確認 futDataDown 在哪一輪之前穩定完整之後,才由人類決定:
#   (a) 把下面的匯入段搬進那一輪(預期是 daily-insti.sh 16:10,放在 export-json 之前),或
#   (b) 為本檔新增一條 cron。
# 兩者都要同步改 crontab.example、docs/08 §0、docs/35、web/lib/freshness.ts 的
# UPDATE_SCHEDULE 與 json_export.py 的期貨 stale 規則。
# pipeline/tests/test_futures_day_wiring.py 鎖住「目前沒有被接上」這件事;接上時要一起改。
#
# 做的事:用 futDataDown 在當天匯入當天(t)的個股期貨(radar import-futures-day),
# 成功就 export-json + deploy。21:20 daily-margin.sh 的 import-futures(OpenAPI)
# 仍照跑,它覆寫前會做修訂偵測(changed>0 → warn)。
source "$(dirname "$0")/lib.sh"

set_round_consequence "網站的個股期貨仍停在前一個交易日；21:20 融資融券輪的 import-futures 會照常補上前一交易日（當日要等明晚）"

acquire_db_lock
sync_code

# 0 = 寫入當天;75 = 現貨還沒到今天/futDataDown 還沒有今天/完整性閘門沒過,
# 什麼都沒寫,不是失敗(下一輪或 21:20 會補);其餘非 0 = 真的壞了。
fd_rc=0
if radar import-futures-day; then
  :
else
  fd_rc=$?
fi
if [ "$fd_rc" -eq 75 ]; then
  notify_skip "個股期貨當日資料尚未完整公布，本輪未寫入（21:20 照常匯入前一交易日）"
  exit 0
fi
if [ "$fd_rc" -ne 0 ]; then
  notify "個股期貨當日匯入失敗（exit ${fd_rc}），請查看 ~/radar-cron.log" high "失敗"
  exit "$fd_rc"
fi

run_step_or_fail "export-json" radar export-json
run_step_or_fail "deploy" deploy_data
notify_ok "個股期貨當日行情已更新並上線"
