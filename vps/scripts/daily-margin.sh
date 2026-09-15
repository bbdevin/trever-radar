#!/usr/bin/env bash
# 21:20 台北(週一–五)— 融資融券主輪。
# TWSE 官方約 21:00 產製 MI_MARGN;留約 20 分緩衝。勿塞 17:40(必空)。
# 分點第二輪在 22:00,避免與本輪搶 db lock。
# 若價格日 > 資券日 → 再對齊價格日補抓一次 + 繁中 warn。
source "$(dirname "$0")/lib.sh"

acquire_db_lock
sync_code

# 順便再補日K(上櫃若稍早仍空)。
radar import-daily --datasets quotes,margin

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
  radar import-daily --datasets margin --date "$PRICE_YMD"
  MARGIN_D="$PRICE_D"
fi

# 個股期貨(TAIFEX)。刻意掛在本輪、不新增 cron、不新增第二個寫入者:
# 這一輪已經握著 db lock 且做完 import → compute → export → deploy。
# exit 75 = 只有一般時段落地;盤後約 05:00 才公布,21:20 跑到這裡看到一個時段
# 是正常的,所以 75 是 warn-and-continue,不是失敗。其餘非 0 照本檔慣例中止。
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

radar compute-scores
radar compute-performance
radar export-json
deploy_data

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
