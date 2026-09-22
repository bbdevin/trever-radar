#!/usr/bin/env bash
# 21:20 台北(週一–五)— 融資融券主輪。
# TWSE 官方約 21:00 產製 MI_MARGN;留約 20 分緩衝。勿塞 17:40(必空)。
# 分點第二輪在 22:00,避免與本輪搶 db lock。
# 若價格日 > 資券日 → 再對齊價格日補抓一次 + 繁中 warn。
source "$(dirname "$0")/lib.sh"

# 本輪失敗的後果(接在 run_step_or_fail 的「本輪中止、未上線」之後)。
# 依據:**沒有任何後續排程會再匯入資券**。grep `--datasets` 全 vps/scripts:
# 只有本檔、backfill-margin.sh(週日一次性,有 DONE flag)與 manual-catchup.sh
# (手動)碰得到 margin;22:00 的 daily-branches.sh 匯的是 quotes,insti,00:05 的
# safe-branch-stats.sh 只重算分點統計(它的 deploy 送的是磁碟上既有的 JSON)。
# 而且本檔的落後補抓分支只會對齊**當下最新的**價格日,不會回頭撿昨天漏掉的那天。
# 所以這一輪失敗是四輪裡唯一「不會自己好」的:那一天的資券要人工補。
set_round_consequence "網站仍是 17:40 那輪的內容，融資融券未上線；之後沒有任何排程會再匯入資券（22:00 只匯分點與法人、00:05 夜間作業只重算分點），缺的那一天要人工補抓"

acquire_db_lock
sync_code

# 順便再補日K(上櫃若稍早仍空)。
# run_step_or_fail(lib.sh):裸呼叫時失敗發生在 `radar` 這個 shell **函式**內部,
# ERR trap 不繼承進函式,整輪會靜默帶著離開碼死掉。
run_step_or_fail "import-daily" radar import-daily --datasets quotes,margin

# 若資券仍落後價格最新日(常見:前一晚腳本 Permission denied / 來源晚公布),對齊價格日再抓。
MARGIN_META="$(docker run --rm \
  -v "$REPO/pipeline":/app/pipeline \
  -v "$REPO/data":/app/data \
  -w /app/pipeline \
  radar-pipeline python -c "
from radar.db import get_engine
from sqlalchemy import text
c = get_engine().connect()
p = c.execute(text('select max(date) from daily_prices')).scalar()
m = c.execute(text('select max(date) from daily_margins')).scalar()
print(f'{p}|{m}')
" 2>/dev/null || true)"
PRICE_D="${MARGIN_META%%|*}"
MARGIN_D="${MARGIN_META##*|}"
if [ -n "$PRICE_D" ] && { [ -z "$MARGIN_D" ] || [ "$PRICE_D" != "$MARGIN_D" ]; }; then
  PRICE_YMD="${PRICE_D//-/}"
  echo "margin lag: price=$PRICE_D margin=${MARGIN_D:-none}; retry --date $PRICE_YMD"
  run_step_or_fail "import-margin-retry" radar import-daily --datasets margin --date "$PRICE_YMD"
  MARGIN_D="$PRICE_D"
fi

# 個股期貨(TAIFEX)。刻意掛在本輪、不新增 cron、不新增第二個寫入者:
# 這一輪已經握著 db lock 且做完 import → compute → export → deploy。
# 餵源只給最新一份**完整**的日報,沒有日期參數:21:20 跑到這裡,最新的完整日報
# 是**前一個交易日**的(當天的盤後時段要到隔天 05:00 才收盤)。所以期貨資料日
# 常態落後現貨一天,而且那一份兩個時段都在裡面——production 的 2026-09-18 是
# 一般 1,763 列 + 盤後 39 列。(先前這裡寫著「21:20 只看得到一般時段」,是錯的。)
# exit 75 = 這一份少了一個時段,是例外不是常態,但仍然 warn-and-continue:
# 統計量只讀一般時段(docs/38 R3),少了盤後不影響任何旗標。其餘非 0 照本檔慣例中止。
futures_rc=0
if radar import-futures; then
  :
else
  futures_rc=$?
fi
if [ "$futures_rc" -ne 0 ] && [ "$futures_rc" -ne 75 ]; then
  notify "個股期貨匯入失敗（exit ${futures_rc}），請查看 ~/radar-cron.log" high "失敗"
  exit "$futures_rc"
fi
if [ "$futures_rc" -eq 75 ]; then
  notify_warn "個股期貨僅一般時段已公布（盤後約 05:00），本輪照常續跑"
fi

# 上面的 import-futures 刻意**不**走 run_step_or_fail:它的 75 是 warn-and-continue,
# 其餘非 0 已經自己發 high 並帶原碼中止。以下各步才是原本裸呼叫、失敗沒聲音的部分。
run_step_or_fail "compute-scores" radar compute-scores
run_step_or_fail "compute-performance" radar compute-performance
run_step_or_fail "export-json" radar export-json
run_step_or_fail "deploy" deploy_data

MARGIN_META2="$(docker run --rm \
  -v "$REPO/pipeline":/app/pipeline \
  -v "$REPO/data":/app/data \
  -w /app/pipeline \
  radar-pipeline python -c "
from radar.db import get_engine
from sqlalchemy import text
c = get_engine().connect()
p = c.execute(text('select max(date) from daily_prices')).scalar()
m = c.execute(text('select max(date) from daily_margins')).scalar()
print(f'{p}|{m}')
" 2>/dev/null || true)"
PRICE_D="${MARGIN_META2%%|*}"
MARGIN_D="${MARGIN_META2##*|}"
if [ -n "$PRICE_D" ] && [ -n "$MARGIN_D" ] && [ "$PRICE_D" != "$MARGIN_D" ]; then
  notify_warn "融資融券仍落後價格日（價格 ${PRICE_D}／資券 ${MARGIN_D}），來源可能尚未完整公布"
else
  notify_ok "融資融券資料已更新並上線（${MARGIN_D:-今日}）"
fi
