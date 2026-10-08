# 49 法人族群買賣超(外資／投信／自營 × 產業／題材)規劃

> **狀態**:📝 規劃(2026-10-08,Fable Planner;使用者提出「投信、外資當日買超或賣超的族群」,附圖未送達,依常見站台版型推定需求)。**程式未動**;MVP 範圍與預設值由本檔定案,Executor 依 §6 單一 Phase 開工。
> 治理:不新增策略、不新增分數、不碰 `final`/Armed/多方榜(`docs/48` 凍結)。資料只來自既有 `daily_institutional`,不新增爬蟲。
> 相關:`docs/20`(功能治理)、`docs/25`(IA)、`docs/19`(UI)、`docs/37` §4(題材)、`docs/44` §3.3(首頁拆檔)、`docs/48`(多方榜凍結)。

## 1. 目標與價值

- **一句話**:每個交易日把「外資／投信／自營 分別淨買超、淨賣超最多的族群」排出來,點族群看是哪幾檔貢獻的,再連到個股頁。
- **回答的問題**:法人今天把籌碼放進哪一群股票、從哪一群抽走;是一兩檔撐起來的,還是整群同向。
- **為什麼符合 `docs/20`**:現站已有逐檔法人(個股頁「三大法人」、首頁卡片 `foreign_net_lots`/`trust_net_lots`)與族群成交金額資金流(MoneyFlow),**缺的是族群層級的法人淨額**——這是既有資料的另一個切面,不是新資料源、不是第 14 個策略、不進任何分數。它補上 docs/25 §2「掃描」任務裡「該先檢查哪一群」的脈絡。
- **誠實邊界**:只整理交易所公布的買賣超,不下判斷;金額是估算(§2.2);題材成分重疊(§2.1);法人資料常比行情晚到(§2.6)。

## 2. 資料定義

### 2.1 族群

| 模式 | 來源 | 一檔歸幾組 | 合計怎麼算 |
|---|---|---|---|
| **產業**(預設) | `stocks.industry`(官方產業別;字面「其他」併為「其他」組、不排名) | 恰一組 | 各組相加 = 全市場,**不重複計算** |
| **題材** | `stock_themes`×`themes`,口徑同 `radar.themes`(排除 `data_date` 晚於報價日的 membership;同名題材以 `(name, stock_id)` 去重) | 每個所屬題材各算一次 | **不跨組相加**;畫面不顯示題材合計,定義句明寫「題材成分重疊,只供組間相對比較」 |

- 母體:`stocks.type = 'stock'` 且 `is_active = 1`;**ETF 不算**(無產業/題材,外資買 0050 不是族群訊號),這與 `radar.json` 的 `all_stocks` 口徑一致。
- 「全市場合計」一行**直接**由 `daily_institutional` 對母體加總,不由族群回加(題材模式才不會算兩次)。
- 不採多方榜的「一檔只歸最熱題材」(`hottestListedTheme`)——那是顯示用的分組法;法人淨額歸到單一題材會把 AI 伺服器股的買超全記給某一個題材,其他題材憑空歸零。

### 2.2 單位

- **張**:`daily_institutional.foreign_net / trust_net / dealer_net / total_net` 為股數,÷1000 取整為張(同 `foreign_net_lots` 既有轉法)。這是原始資料,逐筆可對 T86 / TPEx `insti/dailyTrade`。
- **金額(估)**:交易所只公布股數,不公布金額。估算 = Σ 成分股(淨股數 × **該日**收盤 `daily_prices.close`);多日視窗逐日估再相加(point-in-time,不用今日收盤乘累計張數)。該日無收盤(停牌)→ 取 ≤ 該日最近一筆收盤;仍無 → 該檔金額計 0、張數照算,並記 `amt_missing_n`。
- **排序鍵 = 金額(估)**:張數排名會被低價股與零股型大量交易主導,族群比較用金額較有意義。畫面兩個都列,金額永遠帶「估」字。

### 2.3 法人身分

`外資`(`foreign_net`,含外資自營)、`投信`(`trust_net`)、`自營`(`dealer_net`,自行＋避險合計,與 DB 欄位一致)、`合計`(`total_net`)。四個都算、都匯出;預設顯示外資。

### 2.4 視窗

| 視窗 | 定義 | Phase |
|---|---|---|
| 今日 | `as_of` = `daily_institutional` 最新日 `i_date`(與 `freshness.insti.date` 同一個變數) | MVP |
| 5 日 / 20 日 | `daily_institutional` 中 ≤ `i_date` 的最近 5 / 20 個**不同日期**,逐日淨額(張、估算金額)相加;不足 N 日 → 有幾日算幾日並輸出 `days_actual` | P1 |

### 2.5 市場範圍

上市＋上櫃都在 `daily_institutional`(`twse.fetch_institutional` + `tpex.fetch_institutional`,`daily-insti.sh` 要兩市都到才發布)。族群不分市場合併;成員列帶 `market` 徽章。

### 2.6 滯後與不完整

- `i_date != data_date` → 檔案 `stale: true`;畫面資料日寫「法人 MM/DD」,與首頁 freshness 文案一致(「16:00 起輪詢」)。
- 匯出時數 `i_date` 當日兩市各有幾列 `coverage: {twse, tpex}`;任一市為 0 → `partial: true`,畫面一行「上櫃法人尚未到齊,目前只有上市」。不得把半套講成全市場。

### 2.7 最小族群

- 產業:該日有法人列的成分 ≥ **3** 檔才排名(多數官方產業都過);不足者併入「其他」組。
- 題材:同 `radar.themes` 的 ≥ 3 檔門檻;不設成交金額門檻(法人淨額自己就是門檻——`amt_est` 絕對值 < 1,000 萬的題材不輸出)。
- 每個 (身分, 視窗) 題材只留買超、賣超各前 **20** 組;產業全列。

## 3. 匯出設計

### 3.1 計算(`pipeline/radar/export/insti_group_flow.py`,純函式 + 一個寫檔入口)

1. 一次 SQL 取 `(stock_id, date, 四個淨額, close)`:`daily_institutional` JOIN `stocks`(type/active/industry)LEFT JOIN `daily_prices` 同日收盤,`date IN (最近 20 個法人日)`;約 2,000 檔 × 20 日 = 4 萬列,記憶體與時間可忽略(估 < 3 s)。
2. 題材 membership 沿用 `json_export.py` 既有的 `stock_themes` 查詢結果(同一個 `company_themes_by_stock`,避免兩套口徑)。
3. 純函式 `aggregate(rows, memberships, window) -> payload`:逐檔算 `net_lots`、`amt_est`,再按產業/題材分組;輸出每組 `n`(有法人列的成分數)、`buy_n`/`sell_n`(淨額 >0 / <0 的檔數)、`net_lots`、`amt_est`、`buy_top`(淨額最大前 5)、`sell_top`(淨額最小前 3),成員帶 `id/name/market/net_lots/amt_est/chg_pct`。
4. `json_export.export_json` 尾段(與 `_export_margin_usage` 同位置、同 `conn`)呼叫,`i_date` 為 None 時不寫檔。

### 3.2 落點與形狀

```
web/public/data/rankings/insti_flow_1d.json      (MVP)
web/public/data/rankings/insti_flow_5d.json      (P1)
web/public/data/rankings/insti_flow_20d.json     (P1)
```

```json
{"version":1,"window":1,"days_actual":1,"as_of":"2026-10-07","data_date":"2026-10-07",
 "generated_at":"…","stale":false,"coverage":{"twse":980,"tpex":790,"partial":false},
 "market":{"foreign":{"net_lots":45210,"amt_est":12030000000},"trust":{…},"dealer":{…},"total":{…}},
 "groups":{"industry":{"foreign":[{"name":"半導體","n":42,"buy_n":18,"sell_n":6,"net_lots":12480,"amt_est":3820000000,
                                   "buy_top":[{"id":"2330","name":"台積電","market":"twse","net_lots":8210,"amt_est":3100000000,"chg_pct":1.2}],
                                   "sell_top":[…]}],"trust":[…],"dealer":[…],"total":[…]},
           "theme":{…同形,每身分買超前20+賣超前20…}}}
```

- **不放進 `home/head.json`**:首頁預設分頁不需要它,放進去會讓每次開首頁多 ~100 KB raw(`docs/44` §3.3 的目的就是讓預設分頁只抓表頭)。切到分頁才抓,與「資券」分頁(`rankings/margin_usage.json`)同一模式。
- **大小估**(每檔):產業 ~30 組 + 題材 ≤40 組,× 4 身分 = 280 組,每組約 150 B + 8 成員 × 70 B ≈ 700 B → **~200 KB raw、~30 KB brotli**。預算上限:單檔 ≤ 250 KB raw / ≤ 40 KB br;超過先砍成員數(5+3 → 3+2),再砍題材組數。三個視窗各自一檔,預設只抓 1d。
- `radar.json` / `home/*.json` **逐位元不變**。

### 3.3 確定性與同分

- 族群排序:`amt_est` 降冪 → `net_lots` 降冪 → `name` 字串(codepoint)升冪。
- 成員排序:買超 `net_lots` 降冪 → `id` 升冪;賣超 `net_lots` 升冪 → `id` 升冪。
- 題材同名去重規則、`ORDER BY` 明寫(`docs/43` §1.1 教訓:不依賴實體排列)。
- 緊湊序列化、tmp + rename。

## 4. UI(手機優先 390px)

### 4.1 擺放:首頁新分頁「法人族群」(key `insti`,`?tab=insti`)

- 放在「資券」之後:兩者都是「全市場籌碼排行、自己的 JSON、不是股票卡片清單」,共用 `MarginUsageRank` 的嵌入模式(`embedded`、自己 `dataFetch`、骨架/離線/缺檔三態)。
- 不塞進 MoneyFlow 收合面板:那是成交金額脈絡、預設收合、在頁面最底;使用者明確要這個功能,應該一點就到。也不新開路由(docs/25 硬約束 3)。
- 分頁數 11 → 12;`ScrollHint` 既有,不另改。BottomNav 不動(docs/19 規則 14)。
- 新元件 `web/components/InstiGroupFlow.tsx`;句子集中 `web/lib/instiGroupFlow.ts`(純函式,禁用詞由測試把關,同 `bullBoard.ts` 作法)。

### 4.2 版面:清單,不做熱力圖

熱力圖在 390px 塞 30 組只剩顏色,違反 docs/19 規則 6(色彩非唯一訊號);改用 MoneyFlow 同款**對向條清單**:名稱 | 條軌 | 數值三欄,條只在軌內 `scaleX`,數值永不被條侵入(規則 4)。買超在上(紅,`--up`)、賣超在下(綠,`--down`),md 以上左右兩欄。數字一律 `.num`,帶 +/−。

```text
┌ 390px ──────────────────────────────────────────┐
│ 法人族群                    法人 10/07 · 收盤 10/07 │
│ [ 外資 ][ 投信 ][ 自營 ][ 合計 ]   ← 4 格 segmented(primary)
│ ( 產業 | 題材 )               ( 今日 | 5日 | 20日 )  ← P1 才有右邊
│ 族群內成分股的外資買賣超張數相加;金額＝張數×當日收盤(估)。│
│ 題材成分重疊,只供組間比較。只整理資料,不下判斷。          │
│ 外資全市場 +45,210 張 · +120.3 億(估)                   │
│                                                      │
│ 買超 ↑                                               │
│ 半導體      ▮▮▮▮▮▮▮▮▮▮   +38.2億(估)                 │
│                            +12,480張 · 18買/6賣      │
│ 電腦週邊    ▮▮▮▮▮         +15.1億(估)                 │
│                             +4,920張 · 9買/4賣       │
│ …(最多 10 列,「更多」展開其餘)                        │
│ 賣超 ↓                                               │
│ 金融保險    ▮▮▮▮▮▮▮       −22.4億(估)                 │
│                            −8,310張 · 3買/12賣       │
└──────────────────────────────────────────────────┘
```

點一列(`aria-expanded`,再點收合,右上 X):

```text
│ ▾ 半導體   +38.2億(估) · +12,480張 · 買超 18 檔/賣超 6 檔/有資料 42 檔   [X] │
│   買超前 5                                                              │
│   台積電 2330 上市    +8,210張   +31.0億   +1.2%   ›                      │
│   聯發科 2454 上市    +1,120張   +14.9億   −0.4%   ›                      │
│   …                                                                     │
│   賣超前 3                                                              │
│   聯電   2303 上市    −2,050張    −0.9億   −1.1%   ›                      │
│   (成員列整列可點 → /stock?id=2330#insti,開「三大法人」分頁)             │
```

- 成員列 `min-h-11`、`next/link`;名稱 `truncate + title`。
- 「買超 18 檔/賣超 6 檔」讓使用者一眼分辨「整群同向」與「一檔撐場」;`buy_top` 第一檔金額佔族群 ≥ 70% 時在族群列尾加小字「集中於 台積電」(純顯示、前端算)。
- 空／錯誤狀態:檔不存在 →「尚無法人族群資料(下一輪法人更新後出現)」;`partial` → 琥珀一行;離線 → `OFFLINE_DATA_COPY`。

### 4.3 選中態與色

- 身分 segmented:`bg-primary`(同期貨「當日｜近 N 日」);產業/題材 pill:`pillTabClass(…, "accent")`(同 MoneyFlow);視窗 pill:`"warn"`。禁止灰底 inset ring(docs/19 規則 10)。
- 條:買超 `--up` 漸層、賣超 `--down` 漸層,**沿用 MoneyFlow 的兩組漸層,零新色票**。

## 5. 與既有功能的關係

| 既有 | 關係 | 動不動 |
|---|---|---|
| MoneyFlow(成交金額 vs20) | 回答「錢多不多」;本功能回答「法人往哪放」。同一套族群名稱與列版型,使用者心智一致。 | 不改。P2 可在 MoneyFlow 族群下鑽多一行「外資 +N 張」(讀同一檔)。 |
| 多方榜族群檢視(`groupBoardEntries`) | 顯示用分組,一檔只歸最熱題材;本功能全成員計入。兩者問的問題不同。 | **不改**(`docs/48` 凍結;`theme` 不參與入榜本來就鎖住)。 |
| 題材分組(`themeGroups.ts`) | 不重用 `hottestListedTheme`(理由 §2.1);重用 `radar.themes` 的 membership 口徑。 | 不改。 |
| 個股頁「三大法人」分頁 `InstiPanel` | P2 在面板頂加一行「所屬產業 半導體 今日外資合計 +12,480 張,本檔為族群內第 2 大買超」。 | **只顯示,不是事實 code**:`docs/48` §1 寫明「新增事實 code = v2」,所以不進 `facts/*`、不進多空摘要、不碰 rank 表;多方榜 `counts` 也不會動。 |
| 首頁卡片 `foreign_net_lots`/`trust_net_lots` | 逐檔值不變。 | 不改。 |
| `R_FOREIGN_SELL5`、`I_*` 分數 | 無關;族群層不進任何分數。 | 不改。 |

## 6. 分期

| Phase | 內容 | 檔案 | 估時 |
|---|---|---|---|
| **MVP** | 今日視窗;外資/投信/自營/合計;產業＋題材;族群列＋展開成員(5+3);`insti_flow_1d.json`;首頁新分頁;pytest/node 測試;390px 截圖 | `pipeline/radar/export/insti_group_flow.py`(新)、`json_export.py`(呼叫 + 把 `company_themes_by_stock` 傳入)、`pipeline/tests/test_insti_group_flow.py`(新)、`web/lib/instiGroupFlow.ts`(+test,新)、`web/components/InstiGroupFlow.tsx`(新)、`web/app/page.tsx`(TABS + 分支)、`web/lib/types.ts`、`web/lib/changelog.ts`、`docs/49`/`STATUS` | 1.5–2 天 |
| **P1** | 5 日 / 20 日視窗(兩個檔,切到才抓);「更多」展開全部族群;族群全部成分(第四個檔 `insti_flow_members_1d.json`,只在點「看全部」時抓) | 同上 + `vps/scripts` 不需改(export 內部寫) | 0.5–1 天 |
| **P2** | 個股頁三大法人分頁的族群脈絡一行(§5);MoneyFlow 下鑽加法人一行;族群連續 N 日同向(`streak`,從 20 日檔算) | `web/components/InstiPanel.tsx`、`MoneyFlow.tsx` | 0.5 天 |

每個 Phase 完成後:changelog 次版 +1、`docs/49` 狀態表、`STATUS`;MVP 合 `main` 後 VPS 下一輪 `daily-insti.sh` 的 export 自動產生檔案,**不需改 crontab、Worker、腳本**。

## 7. 風險與驗證

### 7.1 原始資料一致(使用者定義:原始張數逐筆一致)

- pytest 種子 DB:每組 `net_lots` == Σ 成員 `daily_institutional` 列 ÷1000;產業各組 + 其他 == 全市場 `market.*`;題材不做跨組恆等式(重疊)。
- 抽 3 檔與 T86 / TPEx 當日公布值人工核對一次(Executor 完成時附在 STATUS)。
- `amt_est` 永遠標「估」;`amt_missing_n` > 0 時畫面小字「N 檔無當日收盤,金額未計」。

### 7.2 測試

- pytest:聚合純函式(ETF 排除、同名題材去重、最小族群、題材前 20、同分順序、停牌回退收盤、`partial`/`stale`、`i_date` None 不寫檔、序列化穩定);`test_label_honesty`/禁用詞沿用專案既有模式。
- node:`instiGroupFlow.test.ts`(句子、禁用詞清單同 §1、集中於 X 的 70% 門檻、空/partial 文案);`tsc`、`next build`。
- Playwright 390px 深/淺色截圖;鍵盤可操作 segmented/展開/收合。

### 7.3 效能預算

- export 增加 ≤ 5 s(VPS);單檔 ≤ 250 KB raw / 40 KB br;首頁預設分頁**零**額外下載;切分頁一次抓一檔。
- VPS Workers 資產 +3 檔;`deploy_data` 無變動不上線的規則不受影響(檔案每輪重寫但內容未變時由既有機制處理)。

### 7.4 其他風險

- 題材分類每週一更新、可能 stale:族群列沿用 `radar.themes` 的 lifecycle 欄位,stale 題材列尾標「分類 MM/DD」。
- 自營商含避險部位,波動大、與方向判讀弱:分頁定義句點明「自營＝自行＋避險合計」。
- 分頁數變 12:若 390px 可見性退步,把「法人族群」放到「資券」之前並量 `ScrollHint` 是否仍可見。

## 8. 已決定的預設(不再問)

| 項目 | 決定 |
|---|---|
| 預設身分 | 外資 |
| 預設模式 | 產業 |
| 排序鍵 | 金額(估);張數並列 |
| 成員數 | 買超 5 + 賣超 3;全部成分為 P1 |
| 擺放 | 首頁分頁「法人族群」,緊接「資券」 |
| 個股頁脈絡 | P2,只顯示、非事實 code |
| 多方榜 | 不動 |

**唯一留給使用者的問題**:分頁名稱「法人族群」是否符合你習慣的叫法(常見站台叫「法人買賣超族群」「法人動向—族群」);不回覆即用「法人族群」。
