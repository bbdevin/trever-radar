#!/usr/bin/env bash
# 08:00 台北(週一–五)— 早上夜盤上線(docs/49 §12.6.5)。
#
# 期交所把「前一交易日 15:00 → 今天 05:00」那一夜的台指期盤後收盤標在今天,而且今天早上就公布
# (2026-10-13 11:25 VPS 實測 futDataDown 一般 0 列、盤後 6 列;最早幾點公布尚未量到——本腳本每次
# 嘗試都印一行 `morning-index tx_night date=… present=yes|no … at=HH:MM`,就是量測紀錄)。
# 以前要等 14:05 收盤輪才上線;這一輪只做三件事,總共約 1–2 分鐘:
#   1. `radar import-index`(加權/櫃買/台指期一般時段早上一定還沒有 → 75,正常;盤後列有就寫 tx_night)
#   2. `radar export-index`:只重寫 radar.json 的 indices、home/{head,stocks}.json、market/indices_hist.json
#      (不跑 ~15 分鐘的全量 export-json;資料日讀現有 radar.json,generated_at 不動,見 export/index_export.py)
#   3. deploy_data
# 沒公布就每 10 分鐘再試,到 08:40 為止(放鎖再睡;08:50 盤中 worker、09:00 mid-backfill-publish 之前收工——
# mid-backfill-publish 以 `fuser /tmp/radar-db.lock` 判斷,我們握著 fd 9 時它會略過)。
# 截止仍沒有 = 休市或期交所還沒出,**只寫 log、不通知**(14:05 收盤輪照常帶上);匯入/匯出/上線失敗只 warn。
source "$(dirname "$0")/lib.sh"

set_round_consequence "網站維持前一版（台指期夜盤那一行停在上一夜）；14:05 收盤輪的全量匯出會帶上這一夜"

MORNING_DEADLINE="${MORNING_DEADLINE:-0840}"   # HHMM,poll_until 截止
MORNING_INTERVAL="${MORNING_INTERVAL:-600}"    # 秒
# 輪與輪之間重新拿鎖最多等這麼久(預設 3600 太長:09:00 之前一定要收工)
POLL_LOCK_WAIT_SECS="${MORNING_LOCK_WAIT_SECS:-300}"

# 交易日守衛:crontab 已限 1-5;手動在週末跑也直接收工(期交所不會標週末)。
if [ "$(taipei_date +%u)" -gt 5 ]; then
  echo "morning-index: weekend — nothing to do"
  exit 0
fi
TODAY="$(taipei_date +%F)"
TODAY8="$(taipei_date +%Y%m%d)"

acquire_db_lock_wait "${MORNING_LOCK_WAIT_SECS:-300}"
sync_code

# 今天(期交所標示)的夜盤收盤;沒有 → 空字串。唯讀,不搶寫鎖。
night_close_today() {
  radar_ro_sql "SELECT close FROM market_indices WHERE market = 'tx_night' AND date = ?" "$TODAY" 2>/dev/null || true
}

# 一次嘗試:匯入後看今天的 tx_night 在不在。在 → 0;不在 → 75(poll_until 放鎖再試);
# 匯入錯誤且 tx_night 不在 → 原碼。0/75 都是 import-index 的正常碼(早上一般時段一定還沒有,
# 所以多半是 75)。
# 2026-10-20:import-index 只要任一來源錯誤就回 1(加權/櫃買/期交所都跑完才判),所以加權或櫃買
# 掛掉時夜盤其實已經寫進去了。這一輪只需要 tx_night:錯誤碼之後照樣查,有就照常匯出上線,
# 另外 warn 一次其他來源的錯誤(IMPORT_ERR_RC)。
IMPORT_ERR_RC=""
import_night() {
  local rc=0 close=""
  if run_step "import-index" radar import-index --date "$TODAY8"; then
    rc=0
  else
    rc=$?
  fi
  close="$(night_close_today)"
  if [ "$rc" -ne 0 ] && [ "$rc" -ne 75 ]; then
    if [ -z "$close" ]; then
      echo "morning-index tx_night date=${TODAY} present=no import_rc=${rc} at=$(taipei_date +%H:%M)"
      return "$rc"
    fi
    IMPORT_ERR_RC="$rc"
  fi
  if [ -n "$close" ]; then
    echo "morning-index tx_night date=${TODAY} present=yes close=${close} at=$(taipei_date +%H:%M)"
    return 0
  fi
  echo "morning-index tx_night date=${TODAY} present=no at=$(taipei_date +%H:%M)"
  return 75
}

if poll_until "tx-night" "$MORNING_DEADLINE" "$MORNING_INTERVAL" import_night; then
  :
else
  rc=$?
  if [ "$rc" -eq 75 ]; then
    echo "morning-index: no tx_night for ${TODAY} by ${MORNING_DEADLINE} (holiday or not yet published) — not published"
    exit 0
  fi
  notify_warn "夜盤早上匯入失敗（碼 ${rc}），本輪不上線；${ROUND_FAIL_CONSEQUENCE}"
  exit 0
fi

if [ -n "$IMPORT_ERR_RC" ]; then
  notify_warn "早上指數匯入有其他來源錯誤（碼 ${IMPORT_ERR_RC}，加權／櫃買），台指期夜盤已寫入、本輪照常上線；加權／櫃買由 14:05 收盤輪補"
fi

if run_step "export-index" radar export-index; then
  :
else
  rc=$?
  notify_warn "夜盤早上匯出失敗（碼 ${rc}），本輪不上線；${ROUND_FAIL_CONSEQUENCE}"
  exit 0
fi

if run_step "deploy" deploy_data; then
  :
else
  rc=$?
  notify_warn "夜盤早上上線失敗（碼 ${rc}）；${ROUND_FAIL_CONSEQUENCE}"
  exit 0
fi

notify_ok "台指期夜盤（${TODAY} 05:00 收）已上線：$(night_close_today)"
