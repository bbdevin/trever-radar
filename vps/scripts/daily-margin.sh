#!/usr/bin/env bash
# 22:40 台北(週一–五)— 融資融券主輪。
# TWSE 官方約 21:00 產製 MI_MARGN;17:40/21:00 過早或不穩,故獨立晚槽。
# 若價格日 > 資券日 → 繁中 warn(腳本仍 exit 0,隔日再補或手動)。
source "$(dirname "$0")/lib.sh"

acquire_db_lock
sync_code

# 順便再補日K(上櫃若稍早仍空)。
radar import-daily --datasets quotes,margin
radar compute-scores
radar compute-performance
radar export-json
deploy_data

# 比對價格最新日 vs 資券最新日(不經 radar CLI,避免 -m radar 參數衝突)。
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
if [ -n "$PRICE_D" ] && [ -n "$MARGIN_D" ] && [ "$PRICE_D" != "$MARGIN_D" ]; then
  notify_warn "融資融券仍落後價格日（價格 ${PRICE_D}／資券 ${MARGIN_D}），來源可能尚未完整公布"
else
  notify_ok "融資融券資料已更新並上線（${MARGIN_D:-今日}）"
fi
