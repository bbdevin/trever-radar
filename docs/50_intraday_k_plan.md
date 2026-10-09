# 50 個股分K(5/30/60 分)MVP

> 狀態:**程式完成於分支(2026-10-09),未合 main、未上線**。規劃 = Fable MVP 計畫,使用者已核准。
> 動 `pipeline/radar/export/intraday_bars.py`、`providers/fugle.py`、`web/lib/resample.ts`、`web/components/KChart.tsx` 的分K部分前先讀本檔。

## 1. 範圍

- 個股頁 K 線分頁的週期列多三格:**5分 / 30分 / 60分 / 日 / 週 / 月**(手機自成一列,放不下時橫滑,沿用 ScrollHint)。
- 只有**榜單聯集**(與 hist 同一個聯集,`json_export` 的 `union`,約 275 檔)有分K;其餘股票選分K時顯示「此股未提供分K,改看日K」並畫日K。
- 近 **60 個交易日**的 5 分 K;30/60 分由前端從 5 分 K 依交易時段切桶。
- 原始價(未還原),量為張;**盤後**更新(與 spark_day 同一輪),不是盤中即時。
- 不進任何分數、不改多方榜、不改日K/週K/月K 的任何行為;權證分頁等其他 K 線圖不出現分K。

## 2. 資料來源與前提

- **Fugle MarketData 免費方案**,與既有 spark_day(WP-H3 首頁當日分時)**同一個前提**:同一把 `FUGLE_API_KEY`(VPS 容器已帶),同一個 provider 模組與節流;不新增任何 secret、不綁卡。
- 免費方案:historical REST 60 次/分;`historical/candles` timeframe 1/3/5/10/15/30/60;分 K 自 2023-05-23 起;單次區間 < 1 年;量為張。
- 當日:spark_day 每天第一輪 export 本來就逐檔抓 `intraday/candles` 1 分 K(只留收盤做小圖)。現在 `fetch_intraday_candles` 回完整列(`rows`),分K在同一輪聚成 5 分 K——**當日零額外請求**。
- 缺的日子(新進聯集、前幾天沒抓到、第一次上線):`historical/candles` timeframe=5,每檔**一次請求**涵蓋最早到最晚的缺日。每輪上限 **120 次**,共用 fugle 模組節流(1.05 s/次 ≈ 57 次/分)與 429 Retry-After 退避。

## 3. 後端(`pipeline/radar/export/intraday_bars.py`)

| 項目 | 定案 |
|---|---|
| 呼叫點 | `json_export` 在 `attach_spark_day(union, d)` 下一行 `export_intraday_safe(out, union, d)`;同一個「台北今天 = 價格日」閘門才打 Fugle,其餘輪只用快取重寫/到期刪檔 |
| 隔離 | `export_intraday_safe` 任何例外只記 warning(`intraday bars export failed; previous files kept`),不中斷 export;舊檔保留 |
| 快取 | `DATA_DIR/intraday5/{id}.json` = `{id, days:{日期: bars}}`;`[]` = 問過、那天真的沒有(停牌/未上市),不再重問;**最新交易日例外**,沒拿到下輪再問 |
| 保留 | 交易日取 `daily_prices` 最近 60 個日期;視窗外的日子從快取與輸出一起裁掉 |
| 切桶 | 以**開始時間**標記 09:00…13:25 共 54 根;13:30 收盤集合競價那筆併進 13:25;09:00 前、13:30 後的列丟掉;缺分鐘不補(整個 5 分鐘沒成交就沒有那根) |
| 輸出 | `stocks/intraday/{id}.json` = `{id, tf:"5", from, to, adjusted:false, bars:[[epoch_s,o,h,l,c,v],…]}`;epoch 為真實 UTC 秒(該根開始時間);整數價寫成 int;緊湊序列化、tmp+rename;內容沒變不重寫(wrangler 不重傳) |
| 刪檔 | 離開聯集滿 **10 個交易日**(第 11 個缺席交易日)才刪輸出檔與快取;回到聯集即清零。缺席起日記在 `DATA_DIR/intraday5/_state.json` |
| 每輪 log | `intraday: union= requests= fetched_days= today= written= files= deleted= cap= fetch=`;第一次抓到歷史時另印 `intraday label check …` 一行(§4) |

CLI:`radar export-intraday [--out DIR] [--backfill]` —— 讀 `--out`(預設 `web/public/data`)底下 `radar.json` 的聯集與資料日,補抓並重寫;`--backfill` 不設每輪上限。歷史端點任何日子都能抓,所以 CLI 不套「今天 = 價格日」閘門。

## 4. 第一次正式跑要核對的事(Fugle 實際回應)

1. **歷史 5 分 K 的時間標記語意**:程式按「開始時間」處理(`FUGLE_HIST_LABEL = "open"`)。看 log 的 `intraday label check {id} {日}: first=HH:MM last=HH:MM`:
   - `first=09:00` → 開始時間,維持 `"open"`(13:30 那根若存在會併進 13:25)。
   - `first=09:05` 且 `last=13:30` → 結束時間,把 `FUGLE_HIST_LABEL` 改成 `"close"`(整批往前平移 5 分鐘),並清掉 `DATA_DIR/intraday5/` 重補。
   - 結果寫回本節。
2. **1 分 K(intraday)的標記**:假設也是開始時間(第一根 09:00,收盤另一根 13:30)。若第一根是 09:01,所有 5 分邊界會差 1 分鐘,需同樣處理。
3. **量的單位**:計畫寫歷史端點為張;當日 intraday 端點假設同為張。抽一檔比對當日 5 分 K 量加總 ≈ 當日 `daily_prices.volume // 1000`。
4. **歷史端點是否含當天**:不影響正確性(當天由 1 分 K 來);若含,當天 1 分 K 失敗的股票會在同日下一輪由歷史補上。
5. 單次區間 60 個交易日(~3 個月)的回應是否完整(有無筆數上限/分頁)。若被截斷,`from`/`to` 會看到缺日,改成分段請求。

**2026-10-09 VPS 實測結果(2330,Fugle 免費金鑰)**:
- 第 1 點:`historical/candles` timeframe=5,10/07–10/08 共 108 列 = 每日 54 根;第一根 `09:00:00+08:00`、最後一根 `13:30:00`。即**開始時間**標記:09:00…13:20 共 53 根連續交易 + 13:30 收盤集合競價 1 根,**沒有 13:25 根**(13:25–13:30 為集合競價時段)。`FUGLE_HIST_LABEL="open"` 正確;13:30 併入 13:25 桶後每日 54 根。
- 第 2 點:`intraday/candles` timeframe=1,10/08 共 266 列,第一根 09:00、最後一根 13:30,同為開始時間。
- 第 3 點:單位是**張**。1 分 K 量加總 20,154 = 歷史 5 分 K 量加總 20,154(完全相等)。但分 K 量加總比 `daily_prices.volume//1000` 少約 15%(10/07:14,381 vs 16,941;10/08:20,154 vs 23,145),推測日量含盤後定價/鉅額交易,**不可拿兩者互比**,UI 也沒有比較。
- 第 5 點:一次查 07/01–10/08(約 3 個月)回 3,726 列,無分頁或筆數上限跡象。
- 回應鍵:`symbol, type, exchange, market, timeframe, data, sort`。

## 5. 前端

- `web/lib/resample.ts`:`Timeframe` 擴成 `"5"|"30"|"60"|"D"|"W"|"M"`(`DailyTf` 給 `lib/facts` 用,多空事實不變)。`intradayCandles(file, tf)` 依交易時段切桶:30 分每天 9 根(13:00 那根到 13:30)、60 分每天 5 根(13:00 那根半小時);不跨日併桶。
- `web/lib/stockLoad.ts`:`fetchStockIntraday(id)`,404 → `null`(空檔也當沒有)。
- 個股頁:第一次**真的要畫分K**才抓(選了分K;或上次選分K而記在 localStorage)。換股不沿用上一檔。
- KChart(分K時):
  - 時間用 UTCTimestamp,以「台北牆上時間當 UTC」(epoch + 8h)傳入,軸與十字線顯示 09:00;`timeVisible`。
  - legend 時間「MM-DD HH:MM」;均線名 **MA5/MA10/MA20/MA60/MA120/MA240**(不寫「5日」「季線」)。
  - 預設可視:5 分 5 天、30 分 20 天、60 分 60 天;頁面的日K區間列(1月…全部)此時藏起來。
  - 主力買賣超/分點進出 pane 與壓力/支撐虛線是日頻資料,分K不畫(手機的「主力」「分點」鈕也藏)。
  - 說明列「分K · 原始價(未還原) · 盤後更新至 MM-DD」。
  - 沒有分K檔(404/失敗):說明列「此股未提供分K,改看日K」,畫日K;選擇照樣記著,換到有分K的股票時就是分K。

## 6. 體積

- 每檔 60 日 × 54 根 = 3,240 根;以 1245/87.3/23.45 三種價位模擬:**~120–128 KB raw、~27 KB gzip**。
- 聯集 ~275 檔 → 輸出約 **34 MB raw**(VPS 磁碟同量的快取);每次開個股分K下載一檔 ~27 KB(壓縮後)。
- Workers 靜態資產檔數:現況清理後 ~9,100 檔(`docs/44` §P1)+ ~275(寬限期內最多再多幾十)≈ 9,400,上限 20,000。單檔遠小於 25 MB。
- 日常:每天第一輪只多「聚合 + 寫檔」;內容沒變的檔不重寫。新進聯集的股票每檔 1 次請求。

## 7. VPS 上線步驟(待人類)

1. 合 main(Pages 先上前端;沒有資料時選分K一律顯示「此股未提供分K」,不壞)。
2. VPS `git pull` 後,第一次回補(可選;不跑的話交易日的 export 每輪自動補 120 檔,當天幾輪就補完):
   ```bash
   docker run … radar-pipeline python -m radar export-intraday --backfill   # ~275 次請求 ≈ 5 分鐘
   ```
   (與 export 同一個容器呼叫方式、同一個 `vps/.env` 的 `FUGLE_API_KEY`;跑完下一輪 `deploy_data` 上線,或手動 `wrangler deploy`。)
3. 看 log 的 `intraday label check` 一行,依 §4 核對並回寫本檔。
4. 不改 crontab、Worker、secrets。

## 8. 不做 / 之後

- 盤中即時分K(要 WebSocket 或盤中輪詢,另案)。
- 還原分K(除權息日的分K斷層:MVP 標「原始價(未還原)」)。
- 1/15 分、非聯集股(全市場 ~2,400 檔 × 1 次 = 42 分鐘/輪,超過免費方案合理用量)。
