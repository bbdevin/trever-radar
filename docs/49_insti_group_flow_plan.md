# 49 法人族群買賣超(外資／投信／自營 × 產業／題材)規劃

> **狀態**:✅ **MVP 程式完成(2026-10-08,分支、未合 main、未上線;v3.5)**;✅ **「個股」模式(§9,2026-10-09,分支;v3.6)**;✅ **首頁「市場資金流向」面板併入本分頁(§10,2026-10-09,分支;v3.6)**;✅ **「個股」排序＋首頁「市場概況」卡＋大盤指數匯入(§11,2026-10-09,分支;v3.6;排程接線待做)**;✅ **市場概況 A 版:台指期近月＋迷你走勢＋走勢圖 bottom sheet(§12,2026-10-09,分支;v3.6)**;P1/P2 📝 未做。原規劃 2026-10-08 Fable Planner;使用者已核准,分頁名稱沿用「法人族群」。
>
> **MVP 實作備註**(與本檔的差異或補充):
> - 張數取「逐檔 `淨股數 ÷ 1000` **向零截斷**再相加」(`trunc_lots`),兩條恆等式(族群 = Σ 成員、產業各組 + 其他 = 全市場)因此逐張成立;`buy_n`/`sell_n` 與成員前 5/前 3 只計截斷後 ≠ 0 張的檔(零股不算買也不算賣)。**與個股卡片 `foreign_net_lots` 的 `//`(向下取整)刻意不同**:`//` 把 −500 股算成 −1 張、+500 股算成 0 張,買賣超檔數會系統性偏向賣方,並出現「−1張 · 0萬」的假賣超;卡片值逐檔顯示、不計檔數,所以不動(兩者在負數有零股尾數時差 1 張)。
> - Export 隔離:`write_insti_flow` 與 `_export_margin_usage` 各自 try/except,失敗只記 warning,不中斷 stocks_index/個股檔。法人族群失敗時**刪除**上一份檔(舊檔的 `stale` 是當時算的,留著會把舊法人日講成今天;分頁顯示「尚無法人族群資料」,下一輪恢復);資券失敗保留舊檔(檔內 `as_of`,畫面標資料日)。預算最後一階仍超標時記 warning 照寫。
> - 排序看金額(估),族群張數方向可能與金額相反(低價股大量買超、高價股少量賣超),此時族群列加小字「張數方向與金額不同」。
> - 分頁位置:使用者要求放在「期貨異常」右邊(233011e),不是 §4.1 原寫的「資券」之後。
> - 產業「其他」放在 `groups.other.{身分}`(單一族群物件,不排名),畫面在清單底下一行小字。題材分類過期時族群帶 `cls_date`(membership `status == "stale"` 的最早 `data_date`)。`amt_missing_n` 頂層必有、族群層 > 0 才有。
> - 預算保險(§3.2):序列化 > 250 KB raw 時自動降為成員 3+2,仍超過再降題材前 10;畫面「買超前 N」讀陣列長度。全市場規模種子資料實測 239,690 B raw / 25.6 KB br,未觸發降級。
> - 「集中於 X」對稱處理:買超組看 `buy_top[0]`、賣超組看 `sell_top[0]`,≥ 70%。
> - MVP 每邊最多列 10 組,其餘以「顯示前 10 組,共 N 組」小字交代;「更多」展開仍屬 P1。
> - 個股頁原本不認 `#insti`,本次補一條 hash → 三大法人分頁。
> - §7.1「抽 3 檔與 T86/TPEx 人工核對」需正式資料,合 main 上線後做。
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
| MoneyFlow(成交金額 vs20) | 回答「錢多不多」;本功能回答「法人往哪放」。同一套族群名稱與列版型,使用者心智一致。 | ~~不改。P2 可在 MoneyFlow 族群下鑽多一行「外資 +N 張」(讀同一檔)。~~ **2026-10-09 作廢:首頁面板移除,`vs20` 量能徽章併入本分頁族群列(§10)。** |
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
| **P2** | 個股頁三大法人分頁的族群脈絡一行(§5);~~MoneyFlow 下鑽加法人一行~~(2026-10-09 面板已移除,改為本分頁族群列帶量能徽章,§10,已做);族群連續 N 日同向(`streak`,從 20 日檔算) | `web/components/InstiPanel.tsx` | 0.5 天 |

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
| 擺放 | 首頁分頁「法人族群」,放在「期貨異常」右邊(使用者 2026-10-08 指定;原規劃緊接「資券」) |
| 個股頁脈絡 | P2,只顯示、非事實 code |
| 多方榜 | 不動 |

**唯一留給使用者的問題**:分頁名稱「法人族群」是否符合你習慣的叫法(常見站台叫「法人買賣超族群」「法人動向—族群」);不回覆即用「法人族群」。

## 9. 「個股」模式:法人買賣超個股排行(2026-10-09,程式完成於分支、未合 main;v3.6)

使用者要求「可以再增加 法人買賣超的股票嗎」。動工前查過:站上沒有全市場逐檔法人排行(首頁卡片的 `foreign_net_lots`/`trust_net_lots` 只在評分候選股上顯示;MoneyFlow 是成交金額),所以新做,不重用。

### 9.1 擺放

- **不開新分頁**:在「法人族群」分頁的 產業/題材 pill 加第三個「個股」,身分 segmented(外資/投信/自營/合計)三個檢視共用。
- 版面:買超 ↑(`--up` 紅)在上、賣超 ↓(`--down` 綠)在下,md 以上左右兩欄;每邊先列 10 檔,「顯示全部 30 檔」展開(390px 下 60 列一次攤開,賣超要捲很遠才看得到);換身分時收回。
- 每列兩行:第一行 名稱｜張數｜金額(估)｜漲跌｜›;第二行橫跨數字欄:代號、市場徽章、官方產業別、「連 N 日買超/賣超」(N ≥ 2 才顯示)。整列連 `/stock?id=…#insti`。欄頭「買超前 30 檔 · 張數/金額(估)/漲跌」,上方一行「外資 買超 812 檔 · 賣超 835 檔」。
- 標頭、身分與檢視切換在載入中與缺檔時都照常顯示(MVP 原本整塊換成骨架);缺檔時「尚無法人個股資料(下一輪法人更新後出現)」,`partial`/`stale` 沿用族群的琥珀一行。
- 標籤用產業別、不用「最熱題材」:產業一檔恰一個、永遠有值;題材要再選一個代表,口徑會和 §2.1「不採 hottestListedTheme」打架。

### 9.2 資料:`rankings/insti_stocks_1d.json`(另一檔,切到「個股」才抓)

- 族群檔正式約 228 KB、接近 250 KB 預算,所以**不加進去**;個股檔由 `pipeline/radar/export/insti_stocks.py` 的 `write_insti_stocks` 寫,json_export 內**自己一個 try/except**(緊接 `write_insti_flow`),失敗只記 warning 並**刪除舊檔**(理由同族群檔);兩檔互不影響。
- 口徑完全沿用族群檔:`load_rows`(type='stock'、active、ETF 排除、上市＋上櫃、停牌回退收盤)、`trunc_lots` 向零截斷、`stale`/`coverage.partial`/`amt_missing_n`。
- 買超 = 截斷後 > 0 張、賣超 = < 0 張(零股兩邊都不算,`buy_n`/`sell_n` 同口徑);排名鍵 = 金額(估)。同分:買超 金額降冪 → 張數降冪 → 代號升冪;賣超 金額升冪 → 張數升冪 → 代號升冪;無收盤(`amt_missing`,金額 0,畫面「—」)排在該邊最後。
- `streak`(P1-lite,已做):同一身分、截至法人日連續同方向的法人日數。只看 `daily_institutional` 最近 20 個不同法人日(`streak_days` 為實際天數),只查排行上出現的 ≤ 240 檔(PK 前綴查詢,成本可忽略);某日缺列、零張或方向改變即停;到上限時畫面寫「連 20 日以上」。
- 形狀:`{version,window,as_of,data_date,generated_at,stale,coverage,amt_missing_n,streak_days,top_n,ranks:{foreign|trust|dealer|total:{buy_n,sell_n,buy:[…],sell:[…]}}}`,列 `{id,name,market,ind,net_lots,amt_est,chg_pct,streak,amt_missing?}`;緊湊序列化、tmp+rename、`i_date` 為 None 不寫。
- 大小:全市場規模種子(約 1,700 檔、31 產業、20 法人日)**32,684 B raw / 5,986 B gzip / 4,714 B br**;遠低於預算,不需降級階梯。
- `radar.json`、`home/*.json`、`insti_flow_1d.json` 逐位元不變(pytest 以固定時鐘、有無個股檔各匯出一次比對);多方榜不動。

### 9.3 驗證

- pytest `tests/test_insti_stocks.py`(10):排名與同分、零股不算、前 30 與缺收盤排最後、streak(缺列/零股/反向)、partial/stale、種子 DB 匯出值與獨立重算(不經模組)逐檔相同、ETF 排除、失敗刪舊檔且其他檔照寫、族群檔失敗不擋個股檔、其他輸出逐位元相同。
- node `web/lib/instiGroupFlow.test.ts`:個股句子、連續日數文案、金額「—」、禁詞。`tsc`、`next build` 通過。
- 390px 深/淺色截圖:**已做(2026-10-09 驗證者)**。未改門禁:Playwright 以路由攔截回應 Supabase `/auth/v1/*`、`/rest/v1/*`(app_profiles=approved)後對靜態 build 截圖;收合/展開、缺收盤「—」、載入中、缺檔、離線各狀態皆無橫向溢出(scrollWidth=390)。
- 正式資料抽 3 檔與 T86/TPEx 核對(同 §7.1),合 main 上線後做。

## 10. 首頁「市場資金流向」面板併入本分頁(2026-10-09,程式完成於分支;v3.6)

使用者:「因為做了法人族群 感覺下面市場資金流向重複到了 可以整併或移除」,決定權交給 Planner。本節是盤點、決定與理由;§5 那一列「MoneyFlow 不改」自本節起作廢。

### 10.1 盤點:MoneyFlow 到底顯示什麼

| 項目 | MoneyFlow(`web/components/MoneyFlow.tsx`,首頁最底、預設收合) | 法人族群分頁 | 判定 |
|---|---|---|---|
| 族群切換 產業／題材 | 有(`radar.sectors` 前 16／`radar.themes` 前 20,`home/head.json`) | 有(全部產業／題材買賣各前 20) | **重複**(同一套族群名稱、同一種對向條列版型) |
| 排序鍵 | 資金量能(`vs20`=今日成交金額÷近 20 日均)或 平均漲跌(`avg_chg`) | 法人淨額金額(估) | 不同維度:MoneyFlow 問「錢多不多」,本分頁問「法人往哪放」 |
| 族群列數字 | 成交金額(億)、vs20 偏離 %、平均漲跌 % | 淨額(估)、淨張數、買／賣檔數 | `vs20` 是**唯一**本分頁沒有的族群層訊號;成交金額絕對值、平均漲跌為次要 |
| 下鑽 | 產業 → 子題材(`sectors[].subs`,金額/量能/平均漲跌)→ 成分股 chips(漲跌、金額);題材 → 成分股 chips | 族群 → 買超前 5／賣超前 3 成員(張數/金額/漲跌)→ 個股頁 | 重複(都是「點族群看成員」);子題材層是 MoneyFlow 獨有 |
| 展開標頭 | 金額 · 量能 × · ↑漲家數/↓跌家數(族群層 `up`/`down`) | 買超 N 檔/賣超 N 檔/有資料 N 檔 | 族群層漲跌家數為 MoneyFlow 獨有;**市場層**漲跌家數在首頁 Compact Brief(`summary[].up/down`),不受影響 |
| `share`(成交金額佔比) | export 有,**畫面從未顯示** | — | 無損失 |

`sectors`/`themes` 的其他讀者(與本節無關、全部不動):多方榜族群檢視(`groupBoardEntries` 用 `vs20` 挑最熱題材)、`build-bull-board.mjs`(`hottestListedTheme`)、市場掃描／口袋的「題材」排序(`ThemeGroupedList` 分組標頭的量能徽章 `Vs20Badge`)。

### 10.2 決定:移除首頁面板,把「量能」併進法人族群的族群列(選項 b 的最小版)

- **移除** 首頁底部「市場資金流向」收合按鈕與 `MoneyFlow.tsx`。理由:docs/20「停止擴張、合併重複」、docs/25 §4「首頁先回答該檢查誰」;面板已經是預設收合、放在免責聲明之上,等於第三屏的隱藏功能;它與本分頁同族群、同版型,使用者看到的就是「同一張表排兩次」。
- **併入**:本分頁 產業／題材 檢視的族群列第二行加 `量能+N%` 徽章(沿用 `Vs20Badge`,搬到 `web/components/Vs20Badge.tsx`),來源是首頁**已經載入**的 `head.json` `sectors`/`themes`,**不多抓任何檔、head.json 不變**(docs/44 §3.3 預設分頁下載量不變)。定義句後面多一句「量能＝今日成交金額相對近 20 日平均(+80% 即比平時多八成);只列有資料的族群」,只在有族群對得上時出現。一列同時看到「法人往哪放」與「錢多不多」,這正是 §5 原本列為 P2 的「兩個訊號放一起」,只是方向反過來(把量能放進法人表,而不是把法人放進量能表)。
- **不做** 成交金額／平均漲跌排序、子題材下鑽、族群層漲跌家數、「成交」第五個身分 segmented。理由:再加一種排序鍵或第五格 segmented 會把本分頁變回兩張表;390px 下 segmented 四格已是上限;族群層「平均漲跌」與「漲跌家數」在個股層都有更直接的入口(市場掃描 強勢／弱勢、個股頁)。使用者若日後要「哪個產業今天錢最多」,再評估是否以 `turnover` 當第二排序鍵,不在本次範圍。
- **不動**:多方榜、`radar.json`/`home/*.json` 逐位元不變、export 不改、`個股` 檢視不加徽章(全市場個股的 vs20 不在 head.json,只有候選股才有)。

### 10.3 Export 清理候選(本次不動;另案、需人類核准)

移除面板後,下列欄位**已無任何前端讀者**,但 `radar.json`/`home/head.json` 逐位元穩定對其他讀者有意義(docs/44 §3.3),本次不從 export 拿掉,只記為清理候選:

- `sectors[].subs`(子題材下鑽,含每 sub 的 `top`)、`sectors[].top`、`themes[].top`(成分股 chips):docs/44 §3.3 估約 33 KB raw。
- `sectors[].share`、`sectors[].avg_chg`、`sectors[].up`、`sectors[].down`、`themes[].share/avg_chg/up/down`、`sectors[].turnover`、`themes[].turnover`(只剩測試 fixture 與型別引用)。
- 仍有讀者、**不能動**:`sectors[].name`、`sectors[].vs20`、`themes[].name`、`themes[].vs20`、`themes[]` lifecycle 欄位(`cls_date` 等)。

### 10.4 驗證

- node `web/lib/instiGroupFlow.test.ts` 加 `vs20Deviation`/`vs20ByName`/`VS20_LEGEND` 禁詞;web node 全套、`tsc`、`next build` 通過。
- 390px 深／淺色截圖(靜態 build + 種子資料;Playwright 攔截 Supabase `/auth/v1/*`、`/rest/v1/*`,假 session,未動 AuthGate):首頁多方榜(面板已不在)、法人族群 產業／題材(族群列帶量能徽章)。

## 11. 首頁「市場概況」卡 + 大盤指數匯入;「個股」檢視排序與手機版面(2026-10-09,程式完成於分支;v3.6)

使用者:「法人連續買賣超顯示功能很棒 但這邊ui是否能以手機畫面為優化 並且增加排序 / 還有首頁上方的 資料日 上櫃成交 上市成交 這些資訊 跟ui是否可以優化好看點 像是背景顏色 還有這資訊沒什麼太大幫助 或是可以增加指數之類的 或是對使用者有用的資訊」。

### 11.1 「個股」檢視(§9)排序與 390px 版面

- **排序**:計數行下方一排 chip「金額(估)｜張數｜連續日數｜漲跌」(`filterChipClass`,選中主色),買超、賣超**兩邊各自**排,換身分不重置。偏好存 `localStorage["trever.insti.stockSort.v1"]`(讀寫 try/catch,讀不到就是預設「金額(估)」)。規則在 `web/lib/instiGroupFlow.ts` `sortStockRows`,**確定性**:金額 = 檔內順序原樣;張數 = 買超降冪／賣超升冪 → |金額| 降冪 → 代號;連續日數 = streak 降冪 → |金額| 降冪 → 代號;漲跌 = chg_pct 降冪、缺值最後 → |金額| → 代號。欄頭跟著寫「依張數」等;預設不寫。
- **列版面**:第一行 名稱｜張數(粗、側別色)｜金額(估)｜漲跌,數字欄固定寬;第二行 **連續日數膠囊放最前**(`bg-up/15 text-up` / `bg-down/15 text-down`,使用者最常看的訊號,不再是行尾小字)+ 代號 · 市場 · 產業。拿掉每列的 ›(390px 省 12px 給數字;整列本來就可點)。欄頭右側一行小字「張數 / 金額(估) / 漲跌」交代三個數字欄。
- 不改資料檔(`insti_stocks_1d.json` 逐位元不變)。

### 11.2 首頁頂部:三張「資料日／上櫃成交／上市成交」卡 → 一張「市場概況」卡

- **為什麼換**:原三張卡只有兩市成交額與漲跌家數,橫滑才看得到第三張;使用者說「沒什麼太大幫助」。決策有用的市場脈絡是:大盤今天漲跌(加權／櫃買)、錢多不多(成交額)、廣度(漲跌家數)、法人整體進出(三大法人全市場淨額)。四格剛好 390px 兩欄兩列,不用橫滑。
- **版面**(`web/components/MarketBrief.tsx`,句子 `web/lib/marketBrief.ts`):標題「市場概況 · 資料日 YYYY-MM-DD [部分待更新]」;格 1 加權指數、格 2 櫃買指數(收盤 19px 粗體、下一行「▼492.93 · -0.99%」,紅漲綠跌、箭頭與正負號都在字裡);格 3 成交額(兩市合計,下一行 上市/上櫃 各自與 ↑漲家數/↓跌家數);格 4 三大法人(估)(外資大字,投信、自營小字;金額＝張數×當日收盤(估),與法人族群分頁 marketLine **同一組數字**)。md 以上四格一列。底色 `linear-gradient(135deg, color-mix(primary 9%, card), card)`,零新色票(docs/19 §1)。
- **資料日**:指數日或法人日與頁面資料日不同時,格標籤旁標 `(10/06)` / `(法人 10/06)`;「部分待更新」徽章沿用 freshness。
- **舊 payload**:缺 `indices` → 兩個指數格不畫;缺 `insti_market` → 法人格不畫;`summary` 永遠有 → 至少成交額格。首頁預設分頁多下載 **452 B raw**(兩個鍵,種子資料實測),其餘 head.json 不變。
- **不做**:期貨指數、外資期貨未平倉(資料不在站上)、任何預測或強弱判讀字眼。

### 11.3 大盤指數匯入(新資料,原始值逐筆照來源)

| 項目 | 內容 |
|---|---|
| 表 | `market_indices(market, date, close, change, chg_pct)`(`schema.py`;`init_db` 的 `create_all` 會在 VPS 下一次任何 `radar` 指令時建表,不需 migration) |
| 來源 | 上市:TWSE `rwd/zh/afterTrading/MI_INDEX?type=IND`,第一張表「價格指數」列「發行量加權股價指數」(收盤指數、漲跌(+/-)、漲跌點數、漲跌百分比)。上櫃:TPEx `www/zh-tw/afterTrading/tradingIndex?date=YYY/MM/DD`(整月逐日「成交量值及櫃買指數」,取日期相符的列;只有櫃買指數與漲/跌點數,**沒有百分比** → DB 存 NULL,export 以 change ÷ (close − change) 推,四捨五入兩位)。兩者公開、無驗證碼,與既有 quotes 同站。 |
| 程式 | `pipeline/radar/providers/market_index.py`(`parse_twse_index`/`parse_tpex_index` 純函式 + fetch)、`pipeline/radar/market_index.py`(`import_market_index` 走 `importer._run`,`import_logs` dataset=`index`;`latest_indices` 供 export)、`cli.py` 末尾新增 `import-index [--date YYYYMMDD] [--days N]`(獨立區塊,方便與其他分支合併) |
| 離開碼 | 單日:0 兩市都到、**75 任一市還沒公布**(已到的照樣留著,與 `import-daily`/`import-futures-day` 的 75 同義)、1 任一市錯誤。`--days N` 回補:休市日 empty 不算失敗,只有 error 回 1 |
| Export | `radar.json` / `home/head.json` 新鍵 `indices`(每市 ≤ data_date 的最新一列,固定 twse、tpex;一列都沒有 → 鍵不出)與 `insti_market`(`{date: i_date, foreign/trust/dealer/total: {net_lots, amt_est}}`,呼叫 `insti_group_flow.aggregate` 的 `market`,與分頁同函式;i_date 為 None 或算失敗 → 鍵不出、記 warning)。其餘鍵與順序不變。 |
| 測試 | `pipeline/tests/test_market_index.py`(12):fixture `tests/fixtures/twse_mi_index_ind_20261008.json`、`tpex_trading_index_20261008.json` 是 2026-10-09 抓回來的**原始回應**,解析值逐字對來源(49,313.44 / −492.93 / −0.99;426.71 / −3.75);方向欄為 + 時正號;stat 不是 OK / 當日列不在 → NoDataError;版面變 → RuntimeError;匯入兩市與 import_logs、upsert 不重複;CLI 0/75/1 與 `--days`;export 的 `indices`(含 TPEx 推算百分比)與 `insti_market` == `insti_flow_1d.json` 的 `market`;無資料時兩鍵不出;head.json 帶鍵。 |

**排程接線(✅ 2026-10-09 已接:三支腳本 export-json 前 `run_step_or_warn "import-index"`;VPS 已跑 `--days 370` 回補。以下為原規劃文字;本次不動 `vps/scripts`,另一個 agent 正在改;2026-10-09 §12 後 `import-index` 同一支指令連台指期一起抓,接線行不變)**:在 `daily-market.sh`(14:05 上市日K輪)`import-daily` 成功之後、`export-json` 之前加一行 `run_step_or_warn "import-index" radar import-index`(上市指數與 MI_INDEX 同一刻公布;上櫃 tradingIndex 通常 14:45 前後才有、台指期 futDataDown 約 15:00 後有一般時段;這一步回 75 只 warn 不擋);`daily-tpex-quotes.sh`(14:45)與 `daily-insti.sh`(16:00)各加同一行當保底(冪等 upsert;16:00 那輪通常三個都到齊)。**第一次上線前在 VPS 跑一次回補**:`radar import-index --days 370`(≈250 個交易日;TWSE 每天一請求、間隔 3 秒 ≈ 19 分鐘,TPEx 每月一請求 ≈ 13 次,TAIFEX 每 28 天一請求 ≈ 14 次;休市日 empty 無害,只有 error 回 1)。三個來源都回得到 250 個交易日以上(TWSE MI_INDEX 逐日可回多年;TPEx tradingIndex 逐月可回多年;TAIFEX futDataDown 的 `backfill-futures` 已實測可回數年)。不加也不會壞:缺鍵時首頁三格顯示「—」。

### 11.4 驗證

- pytest `tests/test_market_index.py` + `test_insti_group_flow.py` + `test_insti_stocks.py` + `test_home_split.py` + `test_json_export.py`;node `marketBrief.test.ts`(新)、`instiGroupFlow.test.ts`(排序三項);`tsc`、`next build`。
- 390px 深／淺色截圖(同 §10.4 方法):首頁市場概況卡、法人族群「個股」預設與「連續日數」排序(重新整理後排序仍在)、舊 payload(拿掉兩鍵)只畫成交額格。

> §11.2 的四格版面已於同日被 §12 的 A 版(三格可點＋一行)取代;§11.3 的匯入與 export 仍適用,§12 只加台指期、走勢與歷史檔。

## 12. 市場概況 A 版:台指期近月、迷你走勢、走勢圖 bottom sheet(2026-10-09,程式完成於分支;v3.6)

使用者:「上市上櫃 希望增加台指 然後可以可以看到走勢圖 點擊的時候放大展開跳出一個類似modal 要以手機優化為主 然後要表示可以點擊」+「上方還是要有緊湊感喔」;三個版面選項中選 **A**。

### 12.1 台指期近月(新序列 `market='tx'`)

| 項目 | 內容 |
|---|---|
| 來源 | TAIFEX `futDataDown`(與 `import-futures-day` 同一支、同一個 `providers/taifex.parse_history_csv`),契約代碼 `TX`。既有流程把 TX 當「對不到個股對照表的其他商品」丟掉,這裡另外取。 |
| 近月定義 | 當日**一般時段**、非價差(月份不含 `/`)、有收盤價的 TX 列中,**到期月份最小**的那一個(`pick_tx_near_month`)。到期月契約在最後交易日(第三個週三,遇假日由期交所順延)當天仍有一般時段列 → 當天仍是近月;次一交易日來源不再列它 → 自然換成下一月。不自己算第三個週三,假日順延也對。換月那天的 `change` 是新近月自己對前一日結算的漲跌(來源值),不跨契約相減。 |
| 時段 | 只取一般時段(08:45–13:45),與加權/櫃買 13:30 收盤同一個時間框;盤後(前一晚 15:00–05:00)不混。 |
| 存法 | `market_indices` 加兩欄 `contract_month`、`settlement`(指數列 NULL);`close`=收盤價、`change`=漲跌價(來源值)、`chg_pct` NULL(`FuturesDailyRow` 不帶漲跌%,export 以 change/(close−change) 推;fixture 2026/09/10 推得 −0.65% 與來源「漲跌%」相同)。 |
| 匯入 | `import-index` 第三個 `_run`(source=`taifex`, dataset=`index`);還沒產製 → empty/75。`--days N` 走 `backfill_market_index`:TWSE 每天一請求(自帶 3 秒間隔)、TPEx 同月一請求、TAIFEX 每 28 天一請求(塊間睡 3 秒)。 |
| 驗證 | `test_market_index.py`:fixture `taifex_fut_history.csv`(原始 Big5 CSV)2026/09/10 TX 202609 一般 → 46870 / −308 / 結算 46869,盤後列 46984 不取;近月規則(價差、盤後、小台、別天不算;最後交易日仍是近月;次日換月;近月無收盤退下一月);回補的請求次數(TPEx 1 次、TAIFEX 一塊涵蓋三天);今天 pending 時 `--days` 回 0。**2026-10-09 驗證者發現**:上市盤中 MI_INDEX 回 `stat=OK`、表頭齊、`data=[]`,原本當 RuntimeError(exit 1)→ 改為 NoDataError(75),fixture `twse_mi_index_ind_pending_20261009.json` 是實抓回應。 |

### 12.2 資料檔

- `home/head.json` `indices[]` 多 `spark`(每序列最近 40 個收盤,舊→新)與 tx 的 `contract_month`/`settlement`;三序列合計兩個鍵 **1,621 B raw**(種子實測;§11.2 時是 452 B)。
- 新檔 `market/indices_hist.json`(`write_indices_hist`,export 尾段 try/except、失敗保留舊檔、沒有任何序列時刪舊檔):`{version, as_of, generated_at, series: {twse|tpex|tx: {name, points: [[date, close, change, chg_pct]…≤260], contract_month?}}}`;種子 260×3 列 **27.7 KB raw**,只在點開走勢圖時抓、一個 session 抓一次。
- `radar.json` 其餘鍵不變;多方榜不動。

### 12.3 UI(A 版,`web/components/MarketBrief.tsx` + `IndexTrendSheet.tsx`,句子/純函式 `web/lib/marketBrief.ts`)

- **卡**:第一行小字「市場概況 · 資料日 MM/DD [部分待更新]」;第二列 `grid-cols-3`、6px 間距三格可點(加權／櫃買／台指期 近月):標籤＋右上 ›(11px)、收盤 15px、漲跌 ▲▼ 點數 · %(11px,紅漲綠跌)、16px 滿寬迷你走勢(inline SVG,40 點,顏色看首尾);格底 `color-mix(foreground 5%, card)`、圓角 10、min-h 44、按下 `scale 0.97`;整格 `<button aria-label="<名稱> 走勢">`。第三行一行 12px:`成交 1,180.5億 ↑891 ↓875 · 外資 −9.9億 · 投信 −3,280萬 · 自營 +6,909萬`(金額依正負上色;法人日不同時尾端標 `(法人 MM/DD)`)。
- **高度(390px 實測,Playwright `boundingBox`)**:§11.2 四格版 **≈360px → A 版 144px**;舊 payload(三格「—」+ 成交一行)125px。
- **缺資料**:某序列沒有 → 該格中性「—／尚無資料」、不可點;三格永遠在。舊 payload 無 `indices` → 三格都是「—」,無 `insti_market` → 第三行只剩成交。
- **Bottom sheet**(base-ui Dialog:focus trap、ESC、點背景關閉;另明寫 `body.overflow=hidden` 鎖頁面捲動):把手、44px X;標題「大盤走勢 · YYYY-MM-DD 收盤」;指數切換 pill(加權指數／櫃買指數／台指期);名稱＋台指期副標「近月 2026/10 · 結算 49,695.00」;收盤 30px、漲跌點數 · %;300px `lightweight-charts` AreaSeries(線色＝區間首尾紅漲綠跌;加權/台指期價格軸整數、櫃買兩位;關掉縮放/平移,十字游標點或拖讀值,**標頭數字跟著游標變成那天的收盤與當日漲跌**);範圍 chip 1月/3月/6月/1年(21/63/126/250 個交易日,預設 3月);區間高／區間低／區間漲跌(首尾相比)。歷史檔抓不到 → 「尚無走勢資料」;離線 → 既有離線文案。
- **不做**:台指期盤後、小台/選擇權、下滑手勢關閉(X/ESC/背景三種已夠)、任何預測字眼。

### 12.3b 驗證者回報後的修正(2026-10-09 同日)

- **最後交易日結算 0**:futDataDown 在到期月最後交易日(2026 年 05/20、06/17、07/15、08/19、09/16 實測)把結算價寫成 `0`;`pick_tx_near_month` 改存 NULL,前端 `txSubtitle` 把 0/缺都當「沒有結算價」只寫「近月 YYYY/MM」。
- **舊形狀表**:`db._migrate_sqlite` 補 `market_indices` 的 `contract_month`/`settlement`(§11 時建的表沒有這兩欄,export 會直接擲例外);`latest_indices` 也包進 try/except,壞了只少 `indices` 鍵。正式機從未跑過 `import-index`,表還不存在,`create_all` 會直接建新形狀。
- **格式**:卡片格只放 %(「▼0.99%」,點數在 sheet 與 title);台指期整數到底(格、sheet 標頭、結算、區間統計、游標、價格軸);sheet 標題與游標日期 `MM/DD`、時間軸刻度 日 `MM/DD`／月 `M月`／年 `YYYY年`(`localization.timeFormatter` + `tickMarkFormatter`);區間漲跌只放 %(點數在 title),390px 不換行。
- **迷你走勢描邊改中性**(`--ink-2`):旁邊的數字是「今日」漲跌,40 日方向常與今日相反,兩個紅綠擺一起會互相打架;顏色留給數字、走勢只給形狀。sheet 的大圖仍以區間首尾上色(那裡的數字就是區間漲跌)。
- **游標吸附**(`CrosshairMode.Magnet`):價格標籤顯示那天的收盤。台指期副標跟著游標:歷史列第 5 個元素帶那天的近月月份(近月連續、未調整換月價差,提示行加這句);結算價只有最新一天,游標停在過去日不顯示。
- **TradingView 署名**:授權要求保留、與 KChart 一致(都顯示),補 `aria-label`/`title`;位置是圖表庫固定的左下角,不動。
- **缺資料**:完全沒有 `indices`(舊 payload / 還沒回補)→ 整列三格不畫,只剩成交/法人一行(125px → 約 60px);只缺一個序列才顯示那一格「—」。

### 12.4 驗證

- pytest `test_market_index.py`(18)+ 相關 export 測試;node `marketBrief.test.ts`(迷你走勢 path、範圍切片、區間統計、台指期副標、禁詞)、全套;`tsc`、`next build`。
- 390px 深／淺色 Playwright(攔截 Supabase、假 session):卡 144px、無水平溢出、開卡前**沒有**抓歷史檔;點台指期開 sheet(646px,焦點在 sheet 內,只抓一次歷史檔)、游標移動標頭數字跟著變、切 1年＋加權統計更新、ESC 與點背景都能關;缺台指期一格「—」、舊 payload 三格「—」。
