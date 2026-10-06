# 45 — 技術分頁「價格位置」:多空事實並陳(規劃)

> 2026-10-03 Fable Planner 唯讀規劃。使用者:「個股的技術資訊都講正面的,能否也講負面的——壓力線、均線、前方大量套牢賣壓、低點多少」;範圍 = 個股頁「技術」分頁。
> 狀態:✅ **P0-a / P0-b / P1 已實作(2026-10-04,未上線;JSON 要等 VPS 下一輪 export-json)**;✅ **P2 已實作(2026-10-06,見 §8;`price_levels` version 2,JSON 同樣要等下一輪 export)**。§6 使用者已決定。多空句子後來改由 `docs/46` 多空摘要呈現(卡內不再畫「多方 N | 空方 N」兩列,句型見 `web/lib/priceLevels.ts priceLevelFacts()`)。**2026-10-04 docs/46 v2(§6)**:價格位置不再單獨成卡,階梯/上下成交/怎麼算搬進多空分頁「壓力分析」段的兩欄清單之下;F1 句改附最接近的均線價位與距離;F3 與 F4 同側合併成一句;F6/F7(現價之上成交、密集區)與前高前低、缺口、週/月均線改由 `web/lib/facts/levelFacts.ts` 逐列產句。
>
> 實作:`pipeline/radar/compute/price_levels.py`(純函式,F1–F7)→ `json_export.py` 每檔迴圈用已讀進的 K 棒算(`export timing:` 多一段 `levels=`;無新查詢)→ `stocks/{id}.json` 頂層 `price_levels`(K 棒 <20 根 → `{"status":"insufficient"}`;完全沒有 K 棒 → `null`)。成交量也依 af 反向還原(`v × af_today / af`),所以分割前後逐值相等;剛好落在現價的量(如一價到底的漲跌停)兩邊都不算,另給 `at`。密集區格線以現價為起點、寬 1%,同量取近者。前端 `web/lib/priceLevels.ts`(階梯 ≤5 列/側:前高前低與密集區必列、剩下給最近的均線;同價同日合併標最長視窗;今日即 N 日高低不進階梯而成為事實句)、`web/components/PriceLevelsCard.tsx`(技術→多空分頁)、K 線「壓力/支撐」chip 預設關(前高前低用該日 af 換回原始價、密集區取中點)。測試:`pipeline/tests/test_price_levels.py`、`web/lib/priceLevels.test.ts`;合成 DB 匯出 parity:除新鍵外其餘鍵逐位元相同。

## 1. 現況

- 技術分頁(`web/app/stock/page.tsx` `TechnicalPanel`)只畫 `technical.reasons`——全部來自 `indicators.py score_technical()` T1–T5 與 S1–S10,**只在多方條件成立時才產生句子**(站上 20/60 日線、多頭排列、創 20 日新高、量增價漲、RSI 健康區、MACD 翻正、KD 低檔黃金交叉…)。
- MA20/MA60 只給數字,沒說在現價之上還是之下。
- 唯一的技術面風險 `R_RSI_OVERHEAT`(RSI>80)存在 `technical.risks`,**但技術分頁沒有畫出來**(現成缺口)。
- `docs/04` §8 的「壓力區扣分」從未實作。
- **新事實不可放進 `technical.reasons/risks`**:`json_export.py derive_radar_state()` 用 `technical.risks` 非空判定 Armed/Extended,塞進去會悄悄改狀態。

## 2. 原則

- **只加顯示用事實,不動任何分數**(tech_score、final、risk_deductions、Armed 狀態都不變)。
- 數字由 export 算(新純函式 `pipeline/radar/compute/price_levels.py`,用 export 本來就讀進記憶體的 K 棒,每輪全市場 +1–2 秒,無新查詢、無 DB 欄位、無 schema 變更);句子由前端模板產生(`web/lib/priceLevels.ts`),改措辭不必等下一輪 export。
- 價格一律還原到今日基準:`p_adj(t) = raw(t) × af(t) / af(today)`(只讀 `adj_factor`,不碰其產生邏輯)。
- 只寫價位、距離、比例、日期;不寫目標價、不寫「支撐有效／壓力沉重」等形容或預測。

## 3. 事實清單(多 ↔ 空成對)

| # | 多方 ↔ 空方 | 定義 | 期 |
|---|---|---|---|
| F1 | 均線在價下 ↔ 均線在價上 | MA 5/10/20/60/120/240(還原收盤);相等歸上方 | P0 |
| F2 | 5/10/20 多頭排列 ↔ 空頭排列 | 交錯 = 中性,不列兩邊 | P0 |
| F3 | N 日最低(下方)↔ N 日最高(上方) | N=20/60/120/240,還原高低點+日期;今日即最高 → 改列多方「今日即 N 日最高」;同價同日合併標最長視窗 | P0 |
| F4 | 收盤創 20 日新高 ↔ 創 20 日新低 | 與 T2 同口徑鏡像 | P0 |
| F5 | 連 2 日量增價漲 ↔ 量增價跌 | T4 鏡像 | P0 |
| F6 | 現價之下成交量 ↔ 現價之上成交量 | 近 120 日,每根量在 [low,high] 均勻分布,算落在現價之上的比例(說明文:「常被稱為套牢賣壓;只算區間內成交,無法知道是否已換手」) | P0 |
| F7 | 下方成交最密集區 ↔ 上方成交最密集區 | 同視窗分價量,bin 寬 = 現價 1% | P0 |
| F8 | RSI14 50–70 ↔ RSI14 < 50 | 既有數值,純前端 | P0 |
| F9 | 下方 ↔ 上方未回補缺口 | 近 120 根,每側 ≤2;✅ P2 由 export 算(`gaps_above/below`),階梯、K 線虛線、壓力段句、技術段 3% 內句同一份(§8) | P2 |
| F10 | MACD 翻正/KD 黃金交叉 ↔ MACD 翻負/KD 死亡交叉 | T5 鏡像;✅ 已由 `docs/46` 技術段 `X_MACD_CROSS_DOWN`/`X_KD_DEATH_HIGH`(前端還原 K 棒自算)涵蓋,不另加 | P2 |
| F11 | 站上 20 日線第 N 日 ↔ 跌破第 N 日 | 連續天數;✅ P2 `ma20_streak` → `F11_MA20_ABOVE_N/BELOW_N`(§8) | P2 |

邊界:K 棒 <20 根 → 不計算並說明;視窗不足 → 該視窗為空(不縮短、不補值);漲跌停鎖死、除權息、停牌、零成交量各有定義與測試。

JSON:個股頂層新鍵 `price_levels`(與 `technical` 平行,約 600–900 B raw),屬 `docs/44` §3 核心檔。

## 4. 畫面(390px)

技術分頁頂端新卡「價格位置」:
- **價格階梯**:由高到低,上方列(紅色距離 +%)、現價列(藍底)、下方列(綠色距離 −%);上下各最多 5 列,價格藍色粗體。
- **現價上下成交量雙色條**(紅=之上、綠=之下)。
- **多方 N / 空方 N** 兩列事實 chip;一側為空時寫「目前沒有符合的多方事實」。
- 「怎麼算」收合說明。
- 其下保留技術分、RSI、量比、觀察/失效價、reasons,並**補畫 `t.risks`**。

```
┌ 價格位置            資料日 10/03 · 還原價 ┐
│ 120日最高 09/12      135.00   +12.5% │ 紅
│ 60日均線             128.40    +7.0% │
│ 成交最密集區     124.0–125.2   佔 8% │
│ ━━━━━━━ 現價 120.00 ━━━━━━━━━━━━ │ 藍
│ 10日均線             118.90    −0.9% │ 綠
│ 20日最低 09/28       112.50    −6.3% │
│ 近120日成交 上方 38% ███░░░ 62% 下方   │
│ 多方 2 | 站上10日線 · 今日即5日最高     │
│ 空方 3 | 20日線之下 · 空頭排列 · RSI 38 │
└──────────────────────────────────┘
```

K 線分頁(P1):最近上方 2 條＋下方 2 條水平虛線(前高前低、密集區),右軸短標籤,均線列加「壓力/支撐」開關。分價量直方圖畫在 K 線上列 P3(桌機、預設關)。

## 5. 驗證

- pytest `test_price_levels.py`:單調漲/跌、手算三根 K 棒、還原不變性(分割前後逐值相等)、資料不足、漲停鎖死、同日合併、零成交、密集區同量取近者、停牌 as_of、輸出決定性。
- Parity:匯出後刪掉 `price_levels`,其餘鍵與改動前快照逐鍵相等;`derive_radar_state` 輸入不含新鍵;既有 pytest 全綠。
- node:句型、排序、上下各 ≤5、**禁用詞鎖**(勝率/獲利/報酬/關鍵分點/大漲/噴/極品/機率/目標價/買進/賣出/看多/看空/將會/有效支撐/壓力沉重)、舊 JSON 無此鍵不報錯。
- 畫面:390×844 與 1280、深淺主題、無橫向捲動;樣本含貼近 60 日高、深陷均線下、新上市、視窗內除權息。

## 6. 分期與待決

| 期 | 內容 | 工時 |
|---|---|---|
| P0-a | 技術分頁補畫 `t.risks`、RSI<50 鏡像(純前端) | 1 h |
| P0-b | `price_levels` 計算+測試、export 接入、價格位置卡 | 1–1.5 天 |
| P1 | K 線壓力/支撐虛線 2+2 | 0.5 天 |
| P2 | 缺口、MACD/KD 鏡像、連續天數、Header 一行摘要 — ✅ 2026-10-06 完成(§8;MACD/KD 鏡像與 Header 摘要已由 `docs/46` 涵蓋) | 1 天 |
| P3 | K 線分價量直方圖(桌機) | 1 天 |

**使用者決定(2026-10-03)**:①✅ 只顯示事實、不改任何分數 ②K 線壓力/支撐虛線**預設關**(使用者想看再開)③✅ 技術分頁 MA20/MA60 兩格由階梯取代。
已由 Executor 預設:上方成交量主標用「現價之上成交量」、說明文才提「套牢賣壓」;成交量分布視窗 120 日;文件編號 45;排在 `docs/43` 那批 `json_export.py` 修改之後。

## 8. P2 實作(2026-10-06 Fable Planner+Executor;使用者「按照 Fable 建議進行」)

只加顯示用事實,分數、`technical`、`radar.json`、DB 都不動;`price_levels` 仍在拆檔的核心檔(`docs/44` §3.2),新鍵隨核心一起拆、接回。

- **F9 未回補缺口改由 export 算**(`price_levels.py` `_gaps`,`version` 1→2,新鍵 `gaps_above`/`gaps_below`:`[{lo, hi, t}]`,每側 ≤2、近者在前,還原價)。定義與 `docs/46` 已上線的前端回退算法**逐字相同**:近 120 根、只看昨天以前(今日跳空由技術段 `X_GAP_UP/DOWN_TODAY` 講)、之後的 K 棒吃掉多少縮多少、剩餘寬度 ≥ 現價 0.5%、整段在現價之下才是下方支撐/之上才是上方壓力。前端 `priceLevels.levelGaps()` 是唯一取用點:**價格階梯**多一種列 `kind:"gap"`(「未回補缺口 MM/DD  lo–hi  ±x%」,距離看靠近現價那一側的邊)、**K 線壓力/支撐虛線**把缺口中點一起比距離(標籤「缺口」,用跳空那天的 af 換回原始價)、**壓力段句** `L_GAP_ABOVE/BELOW` 改讀這兩個鍵(句型、rank、variant 不變)、**技術段 3% 內句**經 `level` 短標自動點名。合成母體 150 檔:export 算的缺口與前端回退算的逐檔相同(多方榜卡片 `counts.levels` 無一差異)。
- **舊 JSON(version 1,沒有 `gaps_*`)**:壓力段照舊由 K 棒自算(`levelFacts.gapsFromSeries`),階梯與 K 線不畫缺口;`gaps_*: []` 是「有鍵、沒缺口」,不回退。
- **階梯上限**:前高前低、密集區、缺口都是固定列,超過 5 列時**留離現價最近的 5 列**(原本「前高前低與密集區必列」在多了缺口後可能超過 5),剩餘位子仍給最近的均線。
- **F11 連續天數**:新鍵 `ma20_streak: {n, side: "above"|"below", capped}`(收盤 ≥ MA20 歸 above,與 `T1_MA20`/`X_MA_CROSS_UP` 同口徑;`capped` = 可算 MA20 的 221 根全同向,真實天數只多不少)。前端 `priceLevelFacts` 產 `F11_MA20_ABOVE_N`(多方)「收盤連 N 日站上20日線」/ `F11_MA20_BELOW_N`(空方)「收盤連 N 日低於20日線」,capped 寫「N 日以上」;**n = 1 不列**(那就是今天站回/跌破,技術段事件句 `X_MA_CROSS_UP/DOWN` 已講)。技術段日K、狀態型 **rank 2**,不宣告鏡像。
- **F10 MACD/KD 鏡像、Header 一行摘要**:`docs/46` 已有(技術段 `X_MACD_CROSS_DOWN`、`X_KD_DEATH_HIGH`;標頭「多方 N/空方 N + 最強一條」),本期不再做第二份。
- **多方榜不變**(`docs/48` v1 凍結):新 code 都在 K 鍵之外——F11 rank 2(<4)、缺口在壓力段(不計入 K 也不排除)。證據:合成母體 150 檔(同一份 K 棒,`price_levels` 分別用 main 399e1ec 舊 compute 與新 compute 算)分別以 main 與本分支的 `build-bull-board.mjs` 建榜,`universe/qualified/entries/excluded`、入榜 22 檔的 id 順序、卡片三條多方 code 與一條空方 code、紀錄行**完全相同**;唯一差異是 20 張卡片的 `counts.tech` 多 1(F11 計入技術段計數,與 §6.9 的 X_LEVEL 句同一情形)。新程式讀舊 JSON(無新鍵)建出的 `bull_board.json` 與 main 逐位元相同。`bullBear.test.ts` 另鎖 `boardKeys` 有無新鍵相同。
- **測試**:`test_price_levels.py` +9(缺口部分回補/全回補/今日與視窗外排除/每側最近 2 個/分割還原不變;連續天數不封頂/封頂/相等歸上方);node `priceLevels.test.ts`(階梯缺口列、超過 5 列留最近、K 線中點、舊 JSON 不畫、F11 句型/rank/第 1 日不列/落後帶日期、禁用詞)、`levelFacts.test.ts`(有鍵用鍵不看 K 棒、空清單不回退、階梯/K 線/句/3% 內句一致)、`catalogue.test.ts` 覆蓋新 code、`bullBear.test.ts` 多方榜鍵不變。tsc、next build 綠。
- **畫面**:390px 深/淺色截圖(合成股 1206:上方缺口 1 個、下方缺口 2 個、站上 20 日線第 4 日),見 STATUS 當日條目。

## 7. 不做

- 不寫目標價、滿足點、「跌破就…」、支撐有效/壓力沉重等預測與形容。
- 不進 `technical.reasons/risks`、`daily_scores`、`radar.json`;不改 T1–T5、不加 S14、不做 R_RESIST 扣分、不改 final/tech_score。
- 不碰 `adj_factor` 計算、不加 `indicators_daily` 欄位、不做 schema migration、不觸發全市場重算。
- 不做 W 底/頸線等型態辨識(project-context 取捨 4);不換圖表庫、不新增色票。
