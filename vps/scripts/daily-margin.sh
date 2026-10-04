#!/usr/bin/env bash
# 20:45 台北(週一–五)— 融資融券主輪。
# TWSE 官方約 21:00 產製 MI_MARGN。docs/47:20:45 起每 5 分鐘輪詢(上市＋上櫃資券都要到)
# 直到 22:15,到了就立刻上線(舊排程固定 21:20 才抓,實測落後 ≥35 分);
# 舊 crontab 的 21:20 一樣適用(截止仍是 22:15)。
# 分點輪若跑到 21:00 以後,收尾時會順手匯入資券——那天本輪看到資券已是今天就直接收工。
# 若價格日 > 資券日 → 再對齊價格日補抓一次 + 繁中 warn。
source "$(dirname "$0")/lib.sh"

# 本輪失敗的後果(接在 run_step_or_fail 的「本輪中止、未上線」之後)。
# 依據:**沒有任何後續排程會再匯入資券**。grep `--datasets` 全 vps/scripts:
# 只有本檔、daily-branches.sh(收尾已過 21:00 才順手匯入;第一輪通常早於本輪收工,
# 22:30 第二輪只在第一輪覆蓋率不到 100% 而要重爬時才走到那一步)、backfill-margin.sh
# (週日一次性,有 DONE flag)與 manual-catchup.sh / repair-window.sh(手動)碰得到 margin;
# 00:05 的 safe-branch-stats.sh 只重算分點統計。
# 而且本檔的落後補抓分支只會對齊**當下最新的**價格日,不會回頭撿昨天漏掉的那天。
# 所以這一輪失敗是四輪裡唯一「多半不會自己好」的:那一天的資券要人工補。
set_round_consequence "網站仍是分點輪的內容，融資融券未上線；只有 22:30 分點第二輪需要重爬時才會順手補資券，其餘情況沒有任何排程會再匯入（00:05 夜間作業只重算分點），缺的那一天要人工補抓"

# 分點全量輪跑過 21:00 時會在收尾順手匯入資券並上線;那天本輪不必再跑一次。
# 「已帶入」要求**上市與上櫃兩個市場**今天都有 ok 且 rows>0 的資券紀錄——只看
# MAX(date) 的話,只到一邊的那天會讓另一邊被靜默跳過(2026-10-04 驗證者抓到)。
margin_is_today() {
  local n=""
  n="$(radar_ro_sql "SELECT COUNT(DISTINCT source) FROM import_logs WHERE dataset = 'margin' AND status = 'ok' AND rows > 0 AND source IN ('twse','tpex') AND date = ?" "$(taipei_date +%F)" 2>/dev/null || true)"
  [ "${n:-0}" -ge 2 ] 2>/dev/null
}
if margin_is_today; then
  echo "融資融券已由分點輪帶入（上市＋上櫃今天都已匯入），本輪略過"
  exit 0
fi

# 等鎖不略過:分點全量爬可能還握著鎖(最長到約 22:15)。
acquire_db_lock_wait 5400
# 等鎖期間分點輪可能已經帶入了。
if margin_is_today; then
  echo "融資融券已由分點輪帶入（上市＋上櫃今天都已匯入），本輪略過"
  exit 0
fi
sync_code

# 非交易日(docs/47):**先自己補一次日K、再判斷**。前面幾輪若壞掉,本輪的日K匯入
# 是當天的補救之一,不能在匯入之前就認定休市。日K匯入只是保底:empty/TPEx 520(75)
# 都照常往下判斷,其他錯誤只 warn(下面輪詢那一步還會再匯一次日K)。
if radar import-daily --datasets quotes; then
  :
else
  q_rc=$?
  if [ "$q_rc" -ne 75 ]; then
    notify_warn "資券輪保底日K匯入失敗（exit ${q_rc}），續跑"
  fi
fi
if ! price_date_is_today; then
  notify_warn "匯入後仍沒有今天的日K（休市或交易所未出表），融資融券輪不輪詢、不上線"
  exit 0
fi
# 順便再補日K(上櫃若稍早仍空)。輪詢資券(lib.sh poll_until):沒到(75)就放鎖、
# 5 分鐘後再試,到 22:15 仍沒有 → warn、不上線。其他錯誤照舊 high + 原碼中止。
if poll_until "margin" 2215 300 run_step "import-daily" radar import-daily --datasets quotes,margin --require twse:margin,tpex:margin; then
  :
else
  margin_rc=$?
  if [ "$margin_rc" -eq 75 ]; then
    notify_warn "融資融券至 22:15 仍未公布齊全，本輪不發布；缺的那一天要人工補抓"
    exit 0
  fi
  notify "import-daily 失敗（碼 ${margin_rc}），本輪中止、未上線；${ROUND_FAIL_CONSEQUENCE}" high "失敗"
  exit "$margin_rc"
fi

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
# OpenAPI 日報只給最新一份,沒有日期參數,而且**刷新得晚**:2026-10-02 17:07
# 它仍供應 10/01,所以 21:20 跑到這裡拿到的常態是**前一個交易日**,期貨資料日
# 因此落後現貨一天。這是這個餵源的限制,不是「當天資料要等隔天 05:00 才完整」——
# 標 t 的盤後是 t−1 夜盤(TAIFEX 次一營業日慣例),futDataDown 當天約 17:00 就給得出
# t 的完整一般時段(docs/38 §7.18)。2026-10-02 起 `import-futures-day` 已接進 16:10／17:40／22:00,
# 所以本步驟不再是主要來源,而是「官方日報覆核」:覆核餵源當下服務的那一天(常態 t−1,
# 該日早已由當日匯入寫過),不同就以官方為準覆寫並 warn。
# production 的 2026-09-18 是一般 1,763 列 + 盤後 39 列。
# exit 75 = 這一份少了一個時段,是例外不是常態,但仍然 warn-and-continue:
# 統計量只讀一般時段(docs/38 R3),少了盤後不影響任何旗標。其餘非 0 照本檔慣例中止。
#
# 修訂偵測:import-futures 覆寫前會印 `futures revision check: date=… changed=N`,
# 也就是這一天若已由 futDataDown 寫過,官方日報與它有幾列在量/未平倉/結算價上不同。
# 照樣覆寫(官方為準),changed>0 只發 warn——那代表 futDataDown 當天那份不是定稿。
futures_rc=0
FUTURES_OUT="$(mktemp "${TMPDIR:-/tmp}/radar-futures.XXXXXXXX")"
if radar import-futures | tee "$FUTURES_OUT"; then
  :
else
  futures_rc=$?
fi
futures_changed="$(sed -n 's/^futures revision check: .* changed=\([0-9][0-9]*\).*$/\1/p' "$FUTURES_OUT" | tail -n 1 || true)"
rm -f "$FUTURES_OUT"
if [ -n "$futures_changed" ] && [ "$futures_changed" -gt 0 ]; then
  notify_warn "個股期貨官方日報與先前寫入的同日資料有 ${futures_changed} 列不同（已以官方日報覆寫）"
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
