# 30 WP-B6：全市場股票兩年＋上市／上櫃活躍權證合併半年回補

> **狀態（2026-07-19）：範圍已確認，本次只完成規劃；程式與 VPS 腳本尚未依本版改完。**
> 現有 `vps/scripts/wp-b6-backfill.sh` 仍只檢查／抓取上市權證，**在完成本文件 §8 的實作與驗收前不得正式開跑**。
> 正式執行仍須由使用者親自在 VPS 啟動；agent 不得自行部署、改 cron 或寫入正式 DB。

## 1. Confirmed Scope

### 1.1 股票分點

- 全市場普通股，上市＋上櫃，排除 ETF／ETN／其他商品。
- 最近 490 個交易日（約兩年）。
- 規劃指令：`backfill-branches --top 2500 --days 490 --sleep 1.2`。
- `2500` 是防止市場檔數成長的安全上限；正式開跑前必須確認實際普通股目標數沒有被上限截斷。

### 1.2 權證分點：上市＋上櫃同一池

- 每個歷史交易日當天全部有成交的上市＋上櫃認購／認售權證。
- 最近 120 個交易日（約半年）。
- **不拆上市／上櫃 phase、不設兩份 marker、不做兩條排程、不分兩套前端結果。**
- 規劃中的單一指令（CLI 尚待實作 `--market all`）：

```bash
backfill-warrant-branches --market all --top 30000 --days 120 --sleep 1.2
```

- 單一目標查詢口徑：

```sql
WHERE w.market IN ('twse', 'tpex')
  AND w.kind IN ('call', 'put')
  AND COALESCE(d.turnover, 0) > 0
```

- 「活躍」定義為該交易日有成交金額；零成交權證不可能產生分點買超事件，不浪費請求。
- `30000` 只是單日安全上限，不是固定抓滿 30,000 檔；前置檢查若發現單日峰值超過上限，必須停止而非靜默截斷。
- 2026-07-18 已修正「拿最新權證清單倒查歷史」的 bug（commit `a87df0d`）；仍須逐日使用該日 `warrant_daily` 目標，不能退回最新清單模式。

### 1.3 權證分點統計口徑

- 上市與上櫃權證進入**同一份** `branch_trades` 資料流與 `warrant_branches.json`。
- 同一分點、同一標的股票旗下的所有上市／上櫃權證合併，不按市場拆開。
- **NT$2,000,000 是權證分點進入觀察池的淨買超門檻；單日大買與連續多日累積都能觸發。**
- 事件粒度固定為「交易日＋分點＋標的股票」；同日同分點對該標的旗下全部上市／上櫃權證先分別換算買進與賣出金額，再計算買超：

```text
gross_buy_amount  = Σ(buy_lots  × 1000 × 該權證當日收盤價)
gross_sell_amount = Σ(sell_lots × 1000 × 該權證當日收盤價)
net_amount        = gross_buy_amount - gross_sell_amount
```

- **單日型觸發**：`net_amount ≥ NT$2,000,000`，當日直接進入觀察池。
- 例：買進 250 萬、賣出 240 萬，買超只有 10 萬，單日不觸發；買進 250 萬、賣出 40 萬，買超 210 萬，單日觸發。
- **連買型觸發**：同一分點＋同一標的股票，連續至少 2 個可觀察交易日 `net_amount > 0`，把每天跨不同權證的 `net_amount` 累加；當 `streak_net_amount ≥ NT$2,000,000` 時進入觀察池，即使沒有任何單日達 200 萬也要列出。
- 例：第一日買超 80 萬（權證 A）、第二日買超 70 萬（權證 B）、第三日買超 60 萬（權證 C），三日同分點、同標的累計 210 萬，第三日觸發連買型觀察。
- 連買必須是逐交易日可觀察到的正買超；`net_amount ≤ 0` 或該交易日完全沒有該分點資料時中斷 streak。由於來源只提供前 15 大分點，資料中斷不等於真實停止買進，UI 必須誠實標示「觀察到的連買」。
- 同一筆可以同時符合單日型與連買型，輸出時合併為一個 episode，`trigger_types` 同時記錄兩者，不重複顯示。
- `1D / 2D / 5D / 30D / 120D` 用來查看期間內的觸發事件及追蹤 episode；不可把中間含賣超或資料空缺的整段 120 日任意累加成「連續買進」。
- 每筆事件須保留構成權證明細：代號、上市／上櫃、認購／認售、買進張數、賣出張數、估算買進／賣出／淨額與淨買超貢獻占比。
- ETF／指數等非普通股標的權證仍可被回補，但只有能對應 `stocks.type = 'stock'` 的權證會進入「按股票」聚合結果；前置報告必須列出未映射數量。

### 1.4 「還在不在」追蹤口徑

觸發與持續追蹤分開計算：

1. 依「分點＋標的股票」按日期排序。
2. 單日型觸發時，episode 從該日開始；連買型觸發時，episode 要回溯到該段 streak 的第一個正買超日，不能只從跨過 200 萬當天開始算。
3. episode 開啟後，把後續**可觀察到**的每日 `net_amount` 累加為 `estimated_remaining_flow`；未達 200 萬的正負淨流也要計入，不能只計觸發事件日。
4. 再次符合單日型或連買型時保留新事件，並加進同一未結束 episode；若前一 episode 已退出，則開新 episode。
5. 每檔權證另按「分點＋權證代號」維護估算張數，才能回答買了哪些權證、是否換券：

```text
estimated_lots[d,warrant] =
  max(0, estimated_lots[d-1,warrant] + observed_net_lots[d,warrant])

estimated_market_value  = estimated_lots × 1000 × latest_warrant_close
```

   - 正 `net_lots` 視為估算加碼；負 `net_lots` 依序扣減該權證估算張數。
   - 賣超大於已觀察買超時歸零並標記 `coverage_warning`，不得產生負持倉。
   - 權證 A 減碼／歸零、同標的權證 B 增加時，episode 不結束，另標示 `疑似換券`。
   - 權證到期或終止交易時標示 `已到期`，不可繼續算成仍持有。
6. 建議輸出狀態以每檔權證估算張數為主、金額淨流為輔：
   - `仍在（估）`：至少一檔權證 `estimated_lots > 0`，且未觀察到明顯減碼。
   - `減碼中（估）`：至少一檔仍有估算張數，但已觀察到部分權證賣出或估算總張數／成本基礎下降。
   - `疑似換券`：同標的舊權證減碼，同期另一檔權證增加，標的層 episode 仍為正。
   - `已退出（估）`：episode 內所有權證估算張數都歸零；`estimated_remaining_flow ≤ 0` 作輔助證據。
   - `資料不足`：歷史缺日、標的映射不足或來源覆蓋不足，不能下狀態。
7. MoneyDJ 只提供前 15 大買／賣分點；某分點某日沒出現在榜內，不代表零交易。因此所有狀態必須帶「估」或「資料不足」，不得宣稱實際持倉。

這是觀察窗內分點淨流推估，不是庫存成本、集保部位或券商客戶實際持倉證明；單日或連買累計 200 萬只負責觸發列入，不能當成剩餘部位門檻。

### 1.5 標的股票進場均價與權證成本粗估

使用者要觀察的是「分點買權證時，對應標的股票大約在哪個價位」。核心欄位定義為 `estimated_underlying_entry_avg`：

```text
added_capital[d,w] = max(net_lots[d,w], 0) × 1000 × warrant_close[d,w]

per_warrant_underlying_ref_avg[w] =
  Σ(underlying_close[d] × added_capital[d,w])
  ÷ Σ added_capital[d,w]

remaining_cost_basis[w] =
  estimated_lots[w] × 1000 × warrant_avg_cost[w]

estimated_underlying_entry_avg =
  Σ(per_warrant_underlying_ref_avg[w] × remaining_cost_basis[w])
  ÷ Σ remaining_cost_basis[w]
```

- 只使用 episode 內觀察到的正買超增加量；每檔權證先算買進當時的標的股價參考均價，再按目前估算剩餘成本基礎合併。
- 賣出時沿用平均成本法減少估算張數與剩餘成本基礎；已估算歸零的權證不再影響「目前仍持有部位」的標的進場均價。
- 這個數字表示「目前估算仍持有的權證資金，買進時標的股票市價的加權參考均價」，不是把權證價格直接換算成股票持股成本。
- 同一標的買了不同權證時可以合併，同時仍保留每檔權證自己的估算成本與標的參考均價。
- 顯示 `latest_underlying_close`、相對均價漲跌幅：

```text
underlying_return_from_entry =
  latest_underlying_close / estimated_underlying_entry_avg - 1
```

每檔權證另用觀察到的正 `net_lots` 與當日權證收盤價做移動平均成本；賣出時按平均成本法減少估算張數，平均成本本身不因賣出改變：

```text
new_warrant_avg_cost =
  (old_lots × old_avg_cost + added_lots × warrant_close)
  ÷ (old_lots + added_lots)
```

若該權證的履約價與行使比例完整，可加一個**每檔權證、不可跨檔合併**的到期損益兩平股價參考：

```text
認購權證 break_even ≈ strike + warrant_avg_cost / exercise_ratio
認售權證 break_even ≈ strike - warrant_avg_cost / exercise_ratio
```

- 履約價／行使比例缺漏、重設型、上下限型、到期前條款或歷史調整無法正確還原時，不顯示 break-even，改標 `資料不足`。
- 所有成本與持有張數都必須標「估」；MoneyDJ 沒有實際成交價、客戶別與完整分點流水，不能宣稱精準成本。

### 1.6 每日觀察頁最小功能

首頁或 `/branch` 的權證區至少提供：

- `今日權證大戶`：今日單日型買超 ≥200 萬事件。
- `連買剛達標`：今日首次由連買 streak 累計跨過 200 萬的 episode。
- `持續觀察`：仍在／減碼中／疑似換券／已退出／資料不足。
- 兩種主視角：按標的股票、按分點。
- 卡片摘要：分點、標的、觸發類型、今日買超、連買天數、episode 累計淨流、估算剩餘金額、標的進場均價、標的現價與報酬差。
- 展開明細：每天的買超時間軸與每檔權證代號、認購／認售、上市／上櫃、估算張數、成本、現值、狀態及 break-even（可算時）。
- `1D / 2D / 5D / 30D / 120D` 篩選觸發日／episode，不得隱藏已退出的原始事件。
- 同一 episode 同時買進認購與認售時標示 `多空混合／可能為波動策略`，不得只因總買超很大就解讀為看多標的股票。

建議 JSON 最少包含：`branch_name`、`underlying_id`、`episode_start`、`trigger_date`、`trigger_types`、`daily_net_amount`、`streak_days`、`streak_net_amount`、`estimated_remaining_flow`、`status`、`estimated_underlying_entry_avg`、`latest_underlying_close`、`positions[]`、`coverage_warning`。

### 1.7 完成後處理

```text
compute-branch-stats
→ compute-scores
→ compute-performance
→ export-json
→ prune
→ PRAGMA integrity_check
→ Workers 資料 deploy
```

`integrity_check` 必須在 deploy 前回 `ok`；不得先發布再驗 DB。權證分點維持實驗觀察，不納入綜合分（見 `docs/20` §2.4）。

## 2. 免費來源與 2026-07-19 實測結論

### 2.1 目標清單與行情

- 上市／上櫃權證主檔與每日行情沿用現有官方資料流。
- 上櫃權證可由 [TPEx OpenAPI](https://www.tpex.org.tw/openapi/) 的 `tpex_warrant_daily_quts`／`tpex_warrant_issue` 取得代號、標的、成交量值與主檔。
- 2026-07-17（民國 1150717）OpenAPI 實測：上櫃權證日資料 8,999 檔，其中有成交 3,985 檔，3,974 檔能直接對應四碼普通股標的，共 287 個標的。這只是單日容量樣本，正式值以 VPS DB 的 120 日逐日統計為準。

### 2.2 分點資料

- 沿用現有 MoneyDJ `zco` 五鏡像，仍限制私人、低頻盤後使用。
- 2026-07-19 以現有 `fetch_branch_trades()` 唯讀實測：
  - 上櫃權證 `72124U` 可取得「美好-基隆」「群益金鼎」等分點。
  - `710595`、`710828`、`706536`、`708948`、`710792` 均能取得分點買進／賣出張數。
  - `706536` 可取得較早歷史交易日資料。
  - 五個鏡像對相同代號／日期回傳一致。
- 可重現樣本：[MoneyDJ 710595，2026-07-17](https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco.djhtm?a=710595&e=2026-7-17&f=2026-7-17)。

因此，舊文件「免費分點來源不支援上櫃權證」的結論已被實測推翻；正式實作前仍要完成 §8.1 擴大 PoC，不能只靠五檔樣本直接上正式 DB。

### 2.3 不採用的來源

- [櫃買中心券商買賣日報表](https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html)：免費但只提供當日逐檔查詢，每檔可能要求 Cloudflare Turnstile；只作人工抽查，**不得破解或自動繞過驗證**。
- 官方 S40「買賣日報表－權證」：格式完整，但屬收市後交易資訊第九組，每月 NT$5,000，不符合本專案免付費原則（見[官方價格](https://www.tpex.org.tw/zh-tw/service/data/product/post.html)）。
- TPEx `tpex_active_broker_volume`：只有熱門上櫃股票與券商總公司彙總，不是逐權證分點，不能替代本需求。

## 3. 明確不做

- 不將上市／上櫃權證拆成兩套回補、排程、資料表、通知或 UI。
- 不破解 TPEx CAPTCHA／Turnstile。
- 不引入官方付費 S40、FinMind 付費分點或需綁卡服務。
- 不更動評分權重、S code、Armed 規則或前端資訊架構。
- 不回補兩年法人／融資券；WP-B6 只處理股票與權證分點歷史及既有衍生統計。
- 本規劃階段不改 cron、GitHub Actions、Cloudflare Access、secrets 或正式路由。
- 不上傳／下載整顆正式 DB；`data/radar.db` 始終是 VPS 唯一主本。

## 4. 單一權證 phase 設計

```text
Phase 1：股票全市場 490 日
  ↓ 完成 marker
Phase 2：上市＋上櫃活躍權證合併 120 日
  ↓ 單一完成 marker
Phase 3：統計／匯出／完整性檢查／發布
```

Phase 2 必須具備：

- 一個 worker container。
- 一個 `warrants-all-markets-120d.done` marker。
- 一組開始／避讓／恢復／重試／完成 ntfy。
- 逐日把 `twse + tpex` 目標合併後依成交金額排序，但不得因市場別先後導致任一市場被 `LIMIT` 截斷。
- 斷點續傳仍以「日期＋權證代號是否已有分點資料」判定；上市、上櫃使用同一規則。
- 同一時間只跑一個權證 worker，來源鏡像節流仍為全市場合計 1.2 秒／請求。

## 5. 時間、容量與 PoC 門檻

| 階段 | 粗估請求量 | 連續執行時間（未含避讓） |
|---|---:|---:|
| 普通股 490 日 | 約 1,200 × 490 = 58.8 萬 | 約 8 天 |
| 上市＋上櫃活躍權證 120 日 | 暫估 12,000 × 120 = 144 萬 | 約 20 天 |
| 合計 | 暫估約 203 萬 | 約 28 天；含排程避讓暫抓 5–6 週 |

以上權證數以「上市約 8,000＋上櫃單日實測約 4,000」估算，正式計畫不得把估算當成驗收值。開跑前由 VPS DB 產出：

- 120 日每一天的上市／上櫃／合計活躍權證數。
- 單日合計峰值及是否低於 `30000`。
- 半年 distinct 權證數、普通股映射數／比例。
- 已存在／缺漏的分點請求數，據此重算剩餘時間。

容量不再沿用舊版「只增加 0.7–1.0 GB」的低估。每次成功請求最多約 30 筆分點列，必須先做 1 日與 5 日 PoC，量測：

- 實際平均列數／權證。
- `radar.db`、WAL 與索引增量。
- 每 1,000 次請求耗時與錯誤率。
- 依實測外推 120 日最終容量。

開跑前仍要求可用空間 ≥20 GB，且外推完成後至少保留 10 GB；不滿足即停止並回報，不自行縮短範圍。

## 6. 與現行排程共存

### 6.1 歷史回補期間

控制腳本沿用以下避讓：

1. 平日 17:30–23:00 停止 worker，避開 17:40／21:00 分點輪與 22:10 收尾。
2. 週六 04:40–07:00 停止，確保 05:00 `weekly-backup.sh` 可 checkpoint、integrity check、gzip。
3. 恢復前確認 `/tmp/radar-db.lock` 未被正式輪持有。
4. 股票與「上市＋上櫃合併權證」順序執行，不並行。
5. 收到 `SIGINT`／`SIGTERM` 時停止當前 worker；已完成交易保留，重新執行即可續跑。

### 6.2 半年回補後的每日維護（需另次確認才改 cron）

只回補半年但不做每日增量，120D 名單會逐日失真，因此最終需要一條**上市＋上櫃合併**的每日權證分點輪；仍不得拆市場。設計原則：

- 每日只跑一次全市場權證，不再由 17:40／21:00 兩輪重複抓 Top 200 權證。
- 使用同一個 `--market all`；單日買超 ≥200 萬或連續正買超累計 ≥200 萬都能觸發，再用後續逐權證張數與金額淨流更新 episode 狀態。
- 與歷史 worker 共用 source lock，禁止兩者同時打 MoneyDJ。
- 加 hard timeout，不能侵入週六 05:00 備份窗口。
- 先完成 3 個交易日 runtime benchmark，再提出確切 cron 時間；本文件不預先拍板移動 01:10 深歷史輪。
- 修改 cron 屬高風險正式排程變更，必須另獲使用者確認。

## 7. ntfy 規格

沿用 `vps/.env` 的 `NTFY`。未設定時拒絕啟動。通知至少包含：

- preflight 與 Google Drive 開跑前快照完成。
- 股票 phase 開始／避讓／恢復／完成。
- **上市＋上櫃合併權證** phase 開始／避讓／恢復／完成。
- 每次通知附目前日期、已完成日期數、上市／上櫃／合計 fetched、failed、剩餘粗估。
- 來源錯誤與達最大重試次數（High）。
- 磁碟低水位、目標數超出上限、映射率異常（High）。
- 最終重算／integrity check／deploy 結果。
- 使用者中止或程序異常結束（High）。

## 8. 後續實作工作包（本次尚未執行）

### 8.1 WP-B6-P：擴大唯讀 PoC

- 從 TPEx 當日有成交權證按成交金額分位、認購／認售、純數字／尾碼代號抽至少 50 檔。
- 對五鏡像比較正規化後分點列。
- 以當日權證成交量檢查買進／賣出張數合理性。
- 抽已發行滿 30／60／120 日權證驗歷史可用深度。
- 通過條件：有效交易日樣本成功率、鏡像一致率與解析正確率均記錄落檔；失敗樣本須分類為未發行／零成交／來源缺資料／解析異常，不能籠統吞掉。

### 8.2 WP-B6-I：Importer／CLI

預計修改：

- `pipeline/radar/importer.py`
  - 權證目標改 `market IN ('twse','tpex')`。
  - 加活躍成交條件。
  - 確保 `LIMIT` 前先合併市場。
- `pipeline/radar/cli.py`
  - 增加 `--market twse|tpex|all`，WP-B6 固定用 `all`。
- `pipeline/tests/test_backfill_warrant_branches.py`
  - 同一天上市＋上櫃都被選入。
  - 零成交排除。
  - 歷史逐日清單、斷點續傳、上限防截斷回歸測試。
- `pipeline/radar/export/json_export.py` 與 `pipeline/tests/test_json_export.py`
  - 單日型使用當日正向 `net_amount ≥ 200 萬`；連買型使用連續正買超交易日 `streak_net_amount ≥ 200 萬`，不可改用買進總額或任意 120 日累計。
  - 測試同日買 250 萬／賣 240 萬（買超 10 萬）不列入。
  - 測試同日買 250 萬／賣 40 萬（買超 210 萬）須列出事件。
  - 測試同日買 190 萬／賣 0（買超 190 萬）不列入。
  - 測試同分點同標的跨三日、三檔權證買超 80＋70＋60 萬，第三日以連買型觸發；負淨額或資料空缺會中斷 streak。
  - 測試後續賣出會更新減碼／退出狀態，但不能刪掉原始買超事件。
  - 測試舊權證賣出、新權證買進會保留標的 episode 並標疑似換券。
  - 測試每檔權證平均成本、估算剩餘張數、標的股價資金加權均價，以及認購／認售 break-even 邊界。
  - 測試不同分點、不同標的股票不得互相湊滿 200 萬；同一分點同標的跨上市／上櫃權證可以合併。
- `web/app/branch/page.tsx`
  - 同一既有權證分點區新增「今日權證大戶／連買剛達標／持續觀察」，不另拆上市／上櫃頁。
  - 顯示觸發類型、連買天數、構成權證、估算剩餘張數、權證成本、標的進場均價、現價差與狀態警語。

### 8.3 WP-B6-S：VPS 控制腳本

預計修改 `vps/scripts/wp-b6-backfill.sh`：

- `WARRANT_TOP` 由 `20000` 提高為 `30000`。
- preflight 改查上市＋上櫃合計 120 日覆蓋與單日峰值。
- phase／marker／ntfy 全部改成 all-markets 單一版本。
- 加 PoC 外推容量、磁碟低水位與市場別計數。
- 最終仍先 `integrity_check` 再 deploy。

### 8.4 WP-B6-D：文件同步

- 修正 `docs/13_branch_tracking.md`、`docs/14_feature_wave2.md` 中「上櫃不支援」限制。
- 本文件狀態改為「腳本 ready」前，必須先完成 §8.1–§8.3 與測試。
- 每日全市場權證 cron 另立小工作包，經使用者確認後才更新 `docs/08_scheduler_jobs.md` 與 `vps/scripts/crontab.example`。

## 9. 開跑前驗收

1. 股票 490 日與權證 120 日日期覆蓋足夠。
2. 權證目標 SQL 同時選入上市＋上櫃，且零成交排除。
3. 單日合計峰值 < `30000`；否則停止調整上限後重驗。
4. 五鏡像上櫃 PoC 結果達標，解析測試有 fixture，不依 live 網路才會過。
5. 半年 distinct 權證的普通股標的映射率有報告；未映射清單可追查。
6. 1 日／5 日 PoC 容量外推後仍符合 20 GB 開跑、10 GB 完成餘量。
7. 開跑前 Google Drive 快照已執行 `wal_checkpoint(TRUNCATE)`、`integrity_check=ok` 且可列出檔案。
8. 股票 phase 與 all-markets 權證 phase 最終皆 `stopped=None`、`failed=0`。
9. exporter 的單日／連買雙觸發、逐權證持有估算、標的進場均價、episode 狀態測試，以及 pytest、Next.js build、Bash syntax 全過。
10. 使用者明確批准正式 VPS 開跑；每日 cron 仍需另次批准。

## 10. 失敗與回滾

- 一般來源失敗：等待後重開同一 all-markets phase，已完成資料不重抓；達最大重試後停止並發 High 通知。
- 使用者中止／VPS 重開：保留 state marker，重新執行續跑。
- 任何市場資料異常都停止整個權證 phase；不得把上市完成、上櫃失敗包裝成全市場完成。
- DB integrity 異常：不 deploy，依開跑前 Google Drive 快照走 WP-B4 還原流程。
- 不得以 `git reset`、GitHub release DB 或本機 DB 覆蓋正式主本。
- 本規劃不改現行 cron；因此即使 WP-B6 腳本未開跑或中止，既有日常排程仍維持原狀。
