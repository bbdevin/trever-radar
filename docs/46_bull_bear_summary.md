# 46 — 個股頁「多空摘要」(Fable 規劃 2026-10-04,已核定)

> 狀態:✅ **v2(§6)P0/P1/P2 已實作(2026-10-04,未上線)**——三段分析、左右對開、全列、日/週/月、大戶比;§1.3 的「每側 6 列 + 還有 N 項」與單欄版面已被 §6 取代。v1:✅ P0/P1 已實作(2026-10-04)。實作偏差一則:§3.2 的 `raw_risks` 沒有放進 `all_stocks` 列(那些列會原樣進 radar.json,違反 §5「不改 radar.json」),改放旁表 `raw_risks_by_id`,只寫進個股 payload。

承 docs/45(價格位置)與使用者「這紅框資訊可以整合至技術」「可以列出做多理由 做空理由」。純呈現/IA,不改分數、不加策略、不動 derive_radar_state。

## 0. 三個裁定
1. 用詞「多方／空方」,不用做多/做空(建倉動作,同 docs/10 買進/賣出類);固定可見定義句:「多方＝對股價有利的已發生事實;空方＝不利或需留意的事實。只整理資料,不下判斷。」第三類「背景」收方向未定(壓縮蓄勢、庫藏股期間、期貨量異常)。
2. 分頁 `技術` 改名 `多空`,移到 K線 右邊第二格;內部 key 仍 `tech`(?tab=tech、stock-tab-tech 不變)。技術分/RSI/量比/觀察失效/T 訊號變成分頁內最下段「技術指標」。
3. 標頭瘦身不清空:綜合分 + 來源徽章 + 一列「多方 N · 空方 N ›」按鈕(切到多空分頁)+ 最強一條多方、一條空方(各一行 truncate、title 全文)。口袋徽章手機移到分頁、≥sm 留標頭。

## 1. IA
### 1.1 標頭(390px 左欄約 215px)
```
┌ 17  綜合評分 [分點]                     ┐
│ [多方 5] [空方 2]  ›                   │ 紅/綠 chip(bg-up/15、bg-down/15),整列 min-h-11 button
│ ● 分點【美林】連4日買超215張,佔期間…   │ 第一條多方
│ ▲ 分點【統一】昨日大買後今日反手賣出…   │ 第一條空方
└────────────────────────────────────────┘
```
testid:stock-decision(不變)、stock-bullbear-link、stock-decision-top-bull、stock-decision-top-bear。無 scores 但有多空項 → 不畫大數字其餘照畫;兩邊空且無分數 → 整卡不畫。
### 1.2 分頁順序:K線 | 多空 | 籌碼日報 | 權證 | (期貨) | 三大法人 | 大戶 | 基本資料 | 資券。預設仍 K線。
### 1.3 多空分頁(390px)
```
┌ ◆ 多空              資料日 10/03     ┐ SectionHeader family="price"
│ [多方 5]  [空方 2]  + 定義句 + 「計數是事實數量,不是分數」
├─▌多方(左 2px 紅條 border-up)──────────┤
│ 分點 美林 連4日買超215張,佔期間成交量6.3% │ 來源標籤=家族色小字(分點/法人/資券=accent-2 青、技術/價格/策略=primary 藍、權證/題材=warn 琥珀、公司=ink-2)
│ 價格 站上 5/10/20 日線                 │ price_levels F1 群組句(取代 T1_MA20)
├─▌空方(左 2px 綠條 border-down)────────┤ 風險列前綴 AlertTriangle(text-down)
│ 分點 統一 昨日大買後今日反手賣出,疑似倒貨 │
│ 價格 RSI14 38,低於 50                 │
├─ 背景(有項目才出現)───────────────────┤
└──────────────────────────────────────┘
┌ 價格位置(docs/45 卡;卡內拿掉「多方 N | 空方 N」兩列)┐
┌ 技術指標:StatTile 技術分 / RSI14 / 量比;觀察價/失效價;<details> 預設收合「技術訊號原文 加分 N 項・風險 M 項」內 t.reasons + t.risks ReasonPill 原樣 ┐
```
每側預設最多 6 列,超過「還有 N 項」展開;一側空寫「目前沒有符合的多方事實」/「…空方事實」。≥768px 多空左右兩欄。多空摘要列不是 ReasonPill(docs/19 §4 新增例外:家族色來源標籤 + 前景色句子 + 側別色邊框;不得灰字 span)。計數不相減、不比大小、不排名。

## 2. 分類
來源排序:分點 → 法人 → 資券 → 權證 → 題材 → 技術 → 價格 → 策略 → 公司;同來源依 points 遞減(只排序,不顯示)。
### 2.1 reasons(raw_reasons ∪ technical.reasons,以 code 去重)
- 多方/分點:B1_BRANCH_STREAK、B2_MULTI_BRANCH、B3_BUY_CONCENTRATION、B6_BIG_MONEY_FLOW
- 多方/策略:S12_BRANCH_ACCUMULATION、S11_INSTI_BREAKOUT、S13_SHORT_SQUEEZE(套 legacyReasonText)、S1_REBOUND、S1_REBOUND_RELAXED、S2_BREAKOUT20、S3_MA_CONVERGE_BREAKOUT、S4_COMPRESSION_BREAKOUT_V2、S5_PULLBACK_SUPPORT、S6_HIGH_BASE_BREAKOUT、S7_MACD_ZERO_CROSS、S8_GAP_BREAKOUT、S9_MA5_TREND、S10_BOTTOM_MACD
- 多方/權證:W1_TURNOVER_X3/X2/X1_5、W2_VOLUME_X3/X2、W3_STOCK_QUIET、W4_STREAK3/2、W5_CALL_DOMINANT
- 多方/法人:I_TRUST_BUY、I_TRUST_STREAK、I_FOREIGN_BUY、I_FOREIGN_STREAK、I_BOTH_BUY、I_NET_SHARE;多方/資券:I_MARGIN_OK;多方/題材:T_THEME_HOT
- 多方/技術:T1_MA20、T1_MA60(鏡像 F1)、T1_BULL_MA(鏡像 F2)、T2_20D_HIGH(鏡像 F4)、T4_PRICE_VOLUME_UP(鏡像 F5)、T5_RSI(鏡像 F8)、T2_VOLUME_BREAKOUT、T3_BOX_TOP、T5_MACD_HIST_POS、T5_KD_GOLDEN_LOW
- 背景/策略:S4_COMPRESSION_SETUP_V2、S4_VOLATILITY_CONTRACTION
- 無 code 字串 → 多方/其他
### 2.2 risks(raw_risks 新鍵 ∪ technical.risks,以 code 去重;舊 JSON 用 risks 字串比對)
B_RISK_REVERSAL 空方/分點「昨日大買後今日反手賣出」;R_HOT5、R_HOT10 空方/價格「日累漲」;R_SHOOTING 空方/技術「爆量長上影」;R_GAP_FADE 空方/技術「開高走低」;R_RSI_OVERHEAT 空方/技術「RSI14超過80」(兩來源去重);R_FOREIGN_SELL5 空方/法人「外資連5日賣超」;R_MARGIN_HOT 空方/資券「融資使用率」;比對不到 → 空方/其他。
### 2.3 pocket_tags:G1_GEO_BUY 多方/分點;G2_GEO_SELL 空方/分點;T1_TRACKED_BUY、K1_KEY_BUY 多方/分點(PocketBadges.displayText 轉換);H1_HOT_THEME 多方/題材;KB1_BUYBACK_WINDOW 背景/公司。
### 2.4 期貨:F1_FUTURES_VOLUME_60D_HIGH + R_FUTURES_VOLUME_NO_DIRECTION → 背景/期貨(P2)。
### 2.5 price_levels 事實(priceLevels.ts 產句)
F1 均線:多「站上 5/10/20 日線」、空「60/120/240 日線在上方」(每側合成一句;ma ≥ 現價歸上方);F2:「5/10/20日均線多頭排列」/「…空頭排列」(交錯不列);F3:只在今日即極值時「今日即 N 日最高/最低」(取最長視窗);F4「收盤創20日新高/新低」;F5「連2日量增價漲/價跌」;F6/F7 不進清單;F8「RSI14 58,位於 50–70」/「RSI14 38,低於 50」(70–80 不列;>80 由 R_RSI_OVERHEAT)。
去重:只有 price_levels 可用且 as_of === candles[last].t,且對應 F 事實同方向存在時,才隱藏 T1_MA20/T1_MA60/T1_BULL_MA/T2_20D_HIGH/T4_PRICE_VOLUME_UP/T5_RSI;記入 suppressed[];測試保證每個輸入 code 在 bull ∪ bear ∪ context ∪ suppressed 恰出現一次。不顯示 points、不預測;F 句 as_of ≠ 資料日時帶日期。

## 3. 資料契約
### 3.1 web/lib/bullBear.ts
```ts
export type Side = "bull" | "bear" | "context";
export type Source = "chips"|"inst"|"margin"|"warrant"|"theme"|"tech"|"price"|"strategy"|"company"|"futures"|"other";
export interface BullBearItem { key: string; code: string|null; side: Side; source: Source; text: string; risk: boolean; date?: string }
export interface BullBearSummary { asOf: string; bull: BullBearItem[]; bear: BullBearItem[]; context: BullBearItem[]; suppressed: string[] }
export const SIDE_BY_CODE: Record<string,{side:Side;source:Source}>;  // §2 全表含 K1/S4 舊 code
export const RISK_TEXT_KEYS: Array<[string,string]>;
export const SIDE_LABEL = { bull:"多方", bear:"空方", context:"背景" };
export const SOURCE_LABEL: Record<Source,string>; // 分點/法人/資券/權證/題材/技術/價格/策略/公司/期貨/其他
export const SIDE_DEFINITION: string; export const COUNT_NOTE: string; export const EMPTY_SIDE: Record<"bull"|"bear",string>;
export function buildBullBear(input: { rawReasons?: ReasonItem[]; reasons: string[]; rawRisks?: ReasonItem[]; risks: string[]; technical: TechnicalSummary|null; pocketTags?: PocketTag[]; priceFacts?: PriceLevelFact[]; asOf: string }): BullBearSummary;
export function topOfSide(s: BullBearSummary, side:"bull"|"bear"): BullBearItem|null;
```
priceLevels.ts 匯出 priceLevelFacts(pl, lastCandleDate): PriceLevelFact[] = { code: "F1_MA_BELOW"|"F1_MA_ABOVE"|"F2_BULL"|"F2_BEAR"|"F3_HIGH_TODAY"|"F3_LOW_TODAY"|"F4_NEW_HIGH"|"F4_NEW_LOW"|"F5_UP"|"F5_DOWN"|"F8_RSI_OK"|"F8_RSI_LOW"; side; text; mirrors?: string[]; date?: string }(鏡像由 F 事實宣告)。
### 3.2 後端:json_export.py 加 "raw_risks"(全部 risk 項含 code/points/text/value,≤7)到 all_stocks 與個股 payload(無評分殘件 []);與 price_levels 同 commit;derive_radar_state 不讀。types.ts:raw_risks?: ReasonItem[]、price_levels?。鍵缺席時走 §2.2 字串 fallback。
### 3.4 鎖測
web/lib/bullBear.test.ts(charCode 組禁詞避免自掃):禁詞 勝率|獲利|報酬|關鍵分點|大漲|噴|極品|機率|目標價|買進|賣出|看多|看空|將會|有效支撐|壓力沉重|做多|做空|建議|喊單 不得出現在前端模板/標籤/F 句;分類表覆蓋全部 code;去重案例;R_RSI_OVERHEAT 只一次;舊 JSON 可用;7 條風險字串回推 code、未知歸空方/其他;每 code 恰一次;S4 setup 落背景、G2 落空方。pipeline/tests/test_bull_bear_codes.py:regex 抽 scores.py/indicators.py/pocket.py 所有 code,斷言都在 SIDE_BY_CODE(未分類擋 CI)。parity harness:除 /stock 標頭與 stock-tab-tech 外逐字相等。
### 3.5 例外:伺服器原文含「大漲」四處(W3_STOCK_QUIET、S12、S13、S1_REBOUND_RELAXED)本案不改,照顯示;另案改字。

## 4. 實作
P0(docs/45 批次追加):json_export raw_risks;priceLevelFacts();PriceLevelsCard 不畫多空兩列。
P1:bullBear.ts+test;BullBearPanel.tsx;page.tsx:TechnicalPanel 重組(BullBearPanel → PriceLevelsCard → 技術指標卡),technical null 仍畫多空卡;分頁 {key:"tech",label:"多空"} 移到第二格;StockDecisionHeader 改 §1.1(StockView useMemo buildBullBear 一次,按鈕 setView("tech"),PocketBadges hidden sm:flex);verify-mobile-stock.mjs 斷言更新;文件 docs/46、45、25、19 §4、07 §4、STATUS。
P2:期貨背景列;F9–F11。
驗收:node tests、pytest(含 test_bull_bear_codes、test_label_honesty)、build、tsc;截圖 390 深淺 + 1280:高分多理由多風險股、非評分池有 price_levels、舊 JSON、只有風險無理由;標頭高度不超過右欄行情摘要。

## 6. v2(2026-10-04 Fable 規劃、使用者核定;已實作)
使用者:三段(技術/籌碼/壓力)、每段左多右空中間分隔線、全部列出不收合、空方要完整(6488 的 240 日高、上方密集區、上方成交、外資賣超、前大分點淨賣都要出現)、日/週/月、大戶比(集保週資料帶資料日)。純呈現:不改分數、radar.json、DB;全部事實由現有個股 JSON 鍵算出。

### 6.1 版面(`web/components/BullBearPanel.tsx`)
總覽卡(`bullbear-overview`:定義句、計數、「技術 ▲n ▼n ・ 籌碼 … ・ 壓力 …」)→ 三張段卡(`bullbear-section-tech|chips|levels`)→ 技術指標卡。段卡 = SectionHeader + 兩顆計數 chip → `grid-cols-[minmax(0,1fr)_1px_minmax(0,1fr)] items-start`(中間格 `self-stretch` 分隔線貫穿較高欄;**§6.6 起改為兩欄側別淡底,不再有分隔線**)→ 背景列(有才出現)。欄頭 `▲ 多方`/`▼ 空方`(壓力段 `▲ 下方支撐`/`▼ 上方壓力`),欄 testid 仍 `bullbear-bull|bear` 加 `data-section`。群組頭取代每列來源標籤:技術段 日K/週K/月K;籌碼段依來源(大戶顯示「大戶(集保 MM/DD)」);壓力段不分組、依距離由近到遠,兩欄之下接價格階梯、現價上下成交、「怎麼算」(`PriceLevelsCard.tsx` 只剩這三個小元件)。**§6.7 起技術指標卡併入技術分析段頂,不再有獨立卡。**週/月列前綴描邊小 chip「週」「月」;事件型空方(R*、B_RISK_REVERSAL、空方口袋、出貨、跌破 20 線、MACD 翻負、KD 高檔死叉、跳空下跌、長黑)前綴 ⚠。前端事實帶 `segments`(價格藍、+ 紅、− 綠),後端原文仍走 ChangeText。

### 6.2 契約(`web/lib/bullBear.ts`)
`BullBearItem` 加 `section`、`segments?`、`tf?`、`dataDate?`、`rank`(1–5)、`magnitude?`、`dist?`;`BullBearSummary.sections`。`buildBullBear({..., derivedFacts})`;`SECTION_BY_SOURCE`(tech/strategy→技術、price/levels→壓力、其餘→籌碼);Source 加 `holders`、`levels`。分類調整:R_HOT5/R_HOT10 來源 price→tech(技術段日K)、S11→inst、S12→chips、S13→margin;F1_FUTURES_VOLUME_60D_HIGH、R_FUTURES_VOLUME_NO_DIRECTION 進表(背景/期貨)。去重:①後端 code 只一次 ②前端事實(無 date/dataDate)的 mirrors 取代同方向後端 code,含風險與口袋 ③`YIELD_TO_BACKEND`:R_HOT5/10→X_CHG5_UP、R_GAP_FADE→X_GAP_UP_TODAY、R_SHOOTING→X_BIG_BLACK ④事實鍵 code+tf+variant 只一次。排序:段內先分組,再 rank↓ → magnitude↓ → points↓ → 原順序;壓力段距離↑。`topOfSide`:rank → magnitude → 段序(壓力距離 ≤3% → 籌碼 → 技術 → 其餘壓力)→ 來源序。

### 6.3 事實目錄(`web/lib/facts/catalogue.ts`,104 個 code;產生器 `techFacts`/`levelFacts`/`instFacts`/`marginFacts`/`marginFlowFacts`(§7)/`branchFacts`/`holdersFacts`/`otherFacts`,彙整 `facts/index.ts deriveAllFacts`)
| 段/來源 | P0 | P1 | P2 |
|---|---|---|---|
| 技術(日K F2/F3/F4/F5/F8 由 `priceLevelFacts`) | F2_BULL/BEAR、X_ALIGN_BULL/BEAR(W/M)、X_MA_CROSS_UP/DOWN、X_MACD_CROSS_UP/DOWN、X_KD_GOLDEN_LOW/X_KD_DEATH_HIGH、F8_RSI_OK/LOW、X_VOL_SURGE_UP/DOWN、F5_UP/DOWN、F4_NEW_HIGH/LOW、F3_HIGH/LOW_TODAY、X_UP/DOWN_STREAK、X_CHG1_UP/DOWN、X_CHG5_UP/DOWN | X_MA20_SLOPE_UP/DOWN、X_MA60_SLOPE_UP/DOWN、X_MACD_STATE_POS/NEG、X_KD_OVER80、X_GAP_UP/DOWN_TODAY、X_BIG_BLACK(週/月版 F4/F5/F8 亦屬 P1) | X_VOL_DRY |
| 壓力 | F1_MA_BELOW/ABOVE(日/週/月,附最接近均線價位與距離)、L_HIGH_ABOVE、L_LOW_BELOW、L_DENSE_ABOVE/BELOW、L_SUPPLY_ABOVE/BELOW | L_ALLTIME_HIGH/LOW、L_GAP_ABOVE/BELOW、L_RANGE_POS_TOP/BOTTOM | — |
| 法人 | C_FOREIGN_BUY/SELL、C_TRUST_BUY/SELL、C_BOTH_BUY/SELL、C_NET_SHARE_BUY/SELL | C_FOREIGN_20D_BUY/SELL、C_TRUST_20D_BUY/SELL | — |
| 資券 | C_MARGIN_HOT/OK、C_MARGIN_UP_PRICE_DOWN、C_MARGIN_DOWN_PRICE_UP | C_SHORT_CHANGE、C_MARGIN_UP_CONC(背景)、C_MARGIN_UP_DISPERSED(空方 ⚠)、C_MARGIN_BUILDUP_CONC(背景)(§7) | C_SHORT_MARGIN_RATIO |
| 分點 | C_TOP15_FLOW_BUY/SELL、C_ACC_1M、C_DIST_1M、C_DAYTRADE_BUY、C_TRACKED_SELL、C_SMART_BUY、C_SMART_SELL(⚠)(§6.8) | C_ACC_1W、C_DIST_1W、C_GEO_BUY/SELL、C_PNL_GAINERS/LOSERS_HOLDING、C_SMART_HOLDING、C_SMART_HOLDING_NEG(背景)(§6.8) | — |
| 大戶 | H_MAJOR400_UP/DOWN、H_MAJOR1000_UP/DOWN、H_RETAIL_DOWN/UP | H_MAJOR_COUNT、H_INSIDER_UP/DOWN | H_PLEDGE_HIGH |
| 權證/期貨/題材/公司 | C_PUT_DOMINANT | C_PUT_SURGE、C_FUT_VOLUME_HIGH、C_THEME_HOT/COLD、C_BUYBACK | (C_WARRANT_QUIET、C_FUT_OI_CHANGE 未做) |

### 6.4 與規劃稿的偏差(實作時決定)
- **L_SUPPLY_ABOVE/BELOW 兩側都列**(≥5% 才列;之上 ≥30%、之下 ≥70% 的 rank 較高),不是只在門檻以上才列——6488 現價之上只有 18%,照門檻就不會出現,而使用者點名要看到「上方成交」。
- **成交最密集區佔量 <0.5% 不列**(K 棒很少的股票會出現「佔 0%」的空殼區)。
- **C_TOP15_FLOW 句子寫「前12大分點」**:個股 payload 每天只留淨額前 12 大,寫 15 會不誠實;code 名照規劃稿。
- **法人單日沒有連續時**,若近 10 日有 ≥5 日同方向,句尾加「近10日有 N 日賣超,10日合計 …」(6488 外資 10/01 賣、09/30 買,連續天數只有 1)。
- 外資/投信 20 日累計拆成 `_BUY/_SELL` 兩個 code(目錄每個 code 側別固定)。
- 期貨用新 code `C_FUT_VOLUME_HIGH`(背景,帶「行情 MM/DD」);後端兩個期貨 code 只進分類表。權證/期貨/題材/公司合在 `facts/otherFacts.ts`。
- `web/tsconfig.json` 加 `allowImportingTsExtensions`:facts 模組彼此要用 `.ts` 副檔名 import,`node --test` 才跑得動,next build 的型別檢查原本會擋。
- 週/月的量比用「日均量」比(進行中的那根才不會被少算);週/月事實 rank 比日K 低一級。

### 6.6 重點與影響力排序(2026-10-04 使用者:「多空理由排序 重要幾項資訊擺在前面」「重要會影響多空的擺在前面」)
**重點群組**(`bullBear.ts keyItems/groupColumn`):每段每欄最上方一個「重點」小群組(群組頭 = 實心 primary 膠囊),放 rank ≥4 的事實,依「當日先於滯後(無 date/dataDate 優先)→ rank↓ →(壓力段:距離↑)→ magnitude↓ → 欄內原順序」取前 **3** 條;沒有 rank ≥4 時,取最高一條但須 rank ≥3;否則不出現。重點是**移出**原群組(不重複),每個事實全欄仍恰一次。滯後事實在重點列尾補資料日(原本由「大戶(集保 MM/DD)」群組頭提供)。
**其餘群組**:依群組內最高 rank↓ 排,同 rank 維持固定序(技術 日K→週K→月K;籌碼 SOURCE_ORDER);群組內 rank↓ → magnitude↓。壓力段其餘列不分組、維持由近到遠。
**標頭** `topOfSide` 規則與重點一致(滯後後置 → rank → magnitude → 段序),單段時 = 該欄重點第一條。
**影響力 rank 表**(magnitude 為同 rank 內主排序:佔量 %、漲跌幅 |%|、量比、合計張數佔量;週/月 = 日K 減一級;滯後的集保/董監封頂 4):
| rank | 事實 |
|---|---|
| 5 | 外資/投信單日買賣超佔量 ≥3%;三大法人合計佔量 ≥5%;前12大分點淨買賣佔量 ≥5%;低買高賣/區間損益前段分點買賣超佔量 ≥2%(§6.8);近1月出貨分點;分點反手賣出(B_RISK_REVERSAL);日K 跌破 20 日線、MACD 柱翻正/翻負;壓力/支撐 ≤3%(前高前低、成交密集區) |
| 4 | 融資 20 日增加且同期分點集中(背景)/分散且股價跌(空方 ⚠)(§7);外資/投信單日佔量 1–3%(或張數門檻);外資投信同步;三大法人 3–5%;前12大分點 2–5%;低買高賣/區間損益前段分點買賣超(其餘);囤貨分點(1 月/1 週)、近1週出貨分點;當沖分點買超、追蹤分點賣超、地緣分點;融資 5 日增加股價跌(20 日已列「分散且股價跌」時不列)/ 融資減少股價漲;認售成交暴增;日K 站回 20 日線、KD 低檔金叉/高檔死叉、爆量收紅/收黑(量比 ≥1.5)、創 20 日新高/新低、今日 N 日高低、單日 ±3%、跳空、長黑;最接近均線 ≤3%(上下對稱)、未回補缺口 ≤3%;集保大戶週變化 ≥0.5 個百分點(封頂);後端事件型 R_*、分點/法人/T2 類理由 |
| 3 | 強分點仍有持股且帳面為正(C_SMART_HOLDING)、融資堆積且同期分點集中(背景,§7)、均線多空排列(日)、連漲連跌、2 日量增價漲/跌、近 5 日 ±8%、法人 20 日累計、融資使用率 ≥60%(含 R_MARGIN_HOT、R_RSI_OVERHEAT 狀態型風險;有融資堆積且同期分點集中時 C_MARGIN_HOT 降為 2,§7)、認售為認購倍數、散戶人數、週/月最接近均線 ≤3%、後端其餘技術/策略理由 |
| 2 | 強分點仍有持股但帳面為負(C_SMART_HOLDING_NEG,背景);融資使用率 ≥60% 但同期有堆積集中(C_MARGIN_HOT,仍空方,§7);RSI 區間、KD >80、均線斜率、MACD 在零軸上/下(原 3,屬例行狀態)、遠距壓力支撐(>3%)、區間上下緣、題材熱度、分點帳面損益家數、董監持股 |
| 1 | 量縮、融資使用率 <60%、券增減、券資比、期貨量、庫藏股、董監質押、資料內最高最低、遠距週/月均線 |
本次調整(其餘不動):外資/投信單日 ≥3% 由「僅外資賣超」改為多空、外資投信一致;三大法人合計與前12大分點 ≥5% 升 5;囤貨分點 3→4;融資增減股價反向 3→4;日K 最接近下方均線 ≤3% 2→4、週/月 1→3(與上方對稱);MACD 零軸狀態 3→2;集保大戶 5→4;後端 R_RSI_OVERHEAT、R_MARGIN_HOT 4→3。
**視覺**:多方欄 `bg-up/[0.06]`、空方欄 `bg-down/[0.06]` 圓角淡底(取代中間 1px 分隔線);重點列 `bg-up/12`/`bg-down/12` + 左 2px 側別色條;群組頭改家族色 /12 淡底小膠囊;一般列之間 `divide-border` 細線。不新增色票。

### 6.7 技術指標併入技術分析段(2026-10-04 使用者:「技術指標是否能整合技術分析」)
- 技術分析段卡的段頭之下、兩欄之上加指標列(`BullBearPanel.tsx TechMetricsRow`,testid `tech-metrics`;純函式 `web/lib/techMetrics.ts`):技術分(`bg-primary/12` 藍)、RSI14(50–70 紅、<50 綠、>80 琥珀、70–80 中性,同 F8)、量比(`1.8×`;≥1.5 且收漲紅、收跌綠,否則中性)、觀察價/失效價(有才列;藍字價格、精度同價格階梯,附與收盤距離 +紅/−綠,`bg-primary/[0.06]`)。390px 一列 3 格自動換行。§1.3/§6.1 的獨立「技術指標」卡**取消**。
- `technical` 為 null 時,指標列位置改顯示「尚未產出技術指標;請先跑 compute-indicators。」(`tech-metrics-missing`),三段照畫。
- 「技術訊號原文」`<details>` **移除**(`techDetailsSummary` 一併刪):`bullBear.test.ts` 鎖定 technical.reasons/risks 的每個 code 不是在多空列(bull/bear/context),就是被 suppressed 且取代它的鏡像事實列仍在畫面上,故不需要補列。

### 6.8 壓力分析併入技術分析卡、「怎麼算」常駐(2026-10-04 使用者:「壓力分析也能整併至技術分析 只是會變成有一個小標題是壓力分析」;不喜歡收合)
- 卡片改兩張:**技術分析**(指標列 → 技術兩欄 → `border-t` 分隔的「壓力分析」小節 → 價格階梯 → 現價上下成交 → 怎麼算)、**籌碼分析**(第二張)。小節標題 13px 粗體 + 20px 價格家族 icon + 自己的 ▲多方/▼空方 小計數膠囊,比卡片段頭小一級(`h4`,其下欄頭降為 `h5`)。testid 不變:`bullbear-section-levels` 現在巢狀在 `bullbear-section-tech` 內。
- 總覽列計數仍三組,順序跟畫面一致:技術 · 壓力 · 籌碼(`PANEL_ORDER`;資料排序用的 `SECTION_ORDER` 與標頭最強一條的段序都不變)。
- 「怎麼算」不再用 `<details>`:常駐 11.5px `--ink-2` 小字、左 2px 線,`HOWTO_LINES` 由 13 條精簡為 4 條關鍵定義(還原價、均線/N 日高低/缺口/接近、現價上下成交與密集區、週月K合併)。原本混在裡面的法人/分點/大戶門檻改為籌碼分析卡底 2 行(`CHIPS_HOWTO_LINES`,testid `bullbear-chips-howto`)。被刪掉的細節(N 日視窗不縮短、同價同日只列最長、60 日區間上下緣、1000 張級距另列條件等)只留在本檔與程式註解,不再上畫面。
- 驗收:`verify-mobile-stock.mjs` 鎖 levels 巢狀於 tech、卡片序 總覽→技術→籌碼、多空分頁無 `details`。
### 6.8 低買高賣/區間損益估算前段分點的動向(2026-10-04 使用者:「籌碼分析 要把低買高賣的強分點 或是區間獲利多的分點考量進去」)
產生器 `web/lib/facts/smartFacts.ts`(由 `branchFacts` 呼叫);純呈現,不進任何分數。「強分點」不另立定義,沿用既有兩份名單:
- **低買高賣**:`branch_pctile_counts` 經 `normalizeBranchPctile`,短線派/長線派各取排行前 `DEFAULT_VISIBLE`(5)名——即面板預設展開的那幾家(整份排行 30 家太寬,第 30 名不能稱「強」);買側紀錄未達 `minKnown` 的(`compactSide` 判「不足」)不算,與分點標籤同一規則。短線派優先。v1 舊 JSON 只有短線派,照樣可用。**品質門檻(2026-10-04 正式資料抽查後補)**:排行前段不等於低買高賣——買低(與有紀錄時的賣高)比例必須**明顯勝過這檔股票自身基準**(`camp.base`):至少高 10 個百分點且為基準 1.5 倍;基準缺時買低 ≥50%。正式資料上「買低 11%/19%/21%」這類只排在前段、未明顯勝過基準的分點因此不再被稱為低買高賣。句中附基準,例「(短線派 買低 70%,本股 40%)」。
- **區間損益估算前段**:`branch_pnl_est` 3月(60)、1年(240)窗口 `gainers` 依估算合計前 3 名且 >0(進榜已過 pipeline 門檻:可見買進 ≥50 張、最大持有成本 ≥100 萬)。2年窗口太舊,不用。
- **份量**:分點近 5 日(`branch_history` 前 5 天,每天只留前 12 大,看不到的日子算 0)或今日淨買賣超,須 ≥50 張,且佔同期間成交量 ≥0.5% 或 ≥500 張(500 張同 `C_TRACKED_SELL`,大型股 0.5% 太難達到;50 張下限擋小量股的幾張雜訊)。近 5 日的量全在今日 → 寫「今日」;否則先看近 5 日,不成立才看今日。一家分點只寫一句。
- **減碼**:區間損益前段分點近 5 日淨賣 ≥50 張且 ≥ 估算持股的 30%(賣出 ÷(估算持股 + 賣出);估算日不早於分點資料日才算)→ 也列入 `C_SMART_SELL`,句尾「估算持股減少 N%」。
- **句子**:`C_SMART_BUY`(多方)/`C_SMART_SELL`(空方 ⚠)點名前 2 家(依佔量排),其餘「等 N 家」;資格寫在名字前後,例「低買高賣分點【群益金鼎-板橋】(短線派 買低 70%)近5日買超 +1,500 張(佔量 3.0%)」「區間損益估算前段分點【凱基-台北】(3月 +500 萬)今日買超 +600 張(佔量 6.0%)」。賣超句的分位標示用「賣高 N%」(賣側紀錄不足時用買低)。rank:最大佔量 ≥2% → 5,否則 4;magnitude = 佔量 %。分點資料日落後 → 帶日期、「今日」字樣拿掉。
- **持股**:沒被買賣句點名的強分點,在區間損益估算有持股 ≥50 張 → 帳面為正:`C_SMART_HOLDING`(多方,rank 3)「…仍有持股 800 張,帳面為正(估算)」;帳面為負:`C_SMART_HOLDING_NEG`(背景,rank 2,2026-10-04 使用者:套牢中仍持股不是多方證據),同句型。各自一家一句、最多 2 家。這些分點不再算進 `C_PNL_GAINERS/LOSERS_HOLDING` 家數,有排除時家數句首加「另有」。
- **去重**:`C_TRACKED_SELL` 已點名的今日賣超分點不再出現在 `C_SMART_SELL`。
- `branch_pctile_counts` 由 `STOCK_KEYS_NOT_FACTS` 移到 `STOCK_KEYS_USED`(原註記「只呈現次數,不得做成判定」:這裡只點名排行前段分點的買賣超事實並附分位佔比,不做評分與判定)。

### 6.5 測試
`web/lib/bullBear.test.ts`(完整性 fixture:240 日高 +46.9%、上方密集區、現價之上成交、外資連 5 日賣超取代 R_FOREIGN_SELL5;讓位;鏡像含口袋;標頭 rank;分組;每 code 恰一次)、`web/lib/facts/{series,techFacts,levelFacts,holdersFacts,chipsFacts,catalogue}.test.ts`(重取樣:部分週/週中與週一假日/跨年週/月桶/分割前後還原相等/零量;目錄覆蓋率=每個 code 都有 fixture 產生;segments 接起來等於 text;mirrors ⊆ 目錄;禁用詞)。`pipeline/tests/test_bull_bear_codes.py`:SOURCES 加 `futures_volume_anomaly.py`;json_export 個股 payload 頂層鍵 ⊆ `STOCK_KEYS_USED ∪ STOCK_KEYS_NOT_FACTS`(且不得列 payload 沒有的鍵)。

## 7. 融資增量 × 同期分點囤貨/集保(Fable 2026-10-04 規格,使用者核定;已實作)
使用者問「融資使用率高但分點集中,是不是主力用融資」。結論:**只能是同向共動的觀察,不是歸因**——官方只公布每檔融資餘額,沒有分點或帳戶層級;分點也不分現股/融資。所以事實句只把「融資增量」與「同期囤貨分點」「同期集保大戶變化」並列,不寫誰用融資。使用者採 Fable 建議:`C_MARGIN_HOT` 維持空方,只在有堆積集中證據時 rank 3→2;**不採**選項 B(把 C_MARGIN_HOT 改背景);不改任何分數。

**定義句**(籌碼分析卡底常駐,`priceLevels.ts MARGIN_FLOW_DEFINITION` ∈ `CHIPS_HOWTO_LINES`):「融資增量只有全市場餘額,無分點或帳戶層級;此處只列同一期間的分點囤貨與集保變化,是否相關由讀者判斷。」

**產生器** `web/lib/facts/marginFlowFacts.ts`(純前端;資料 margin_history、branch_history、insti_history、holders_history、candles;無新後端鍵,`STOCK_KEYS_USED` 不變)。`deriveAllFacts` 先算它,結果 `{buildupConc, dispersed20}` 傳給 `marginFacts()` 第 4 參數。外資席位判斷 `web/lib/facts/seat.ts isForeignBroker`(去掉「(…)」前綴後比對 X商 前綴或美林/摩根/花旗/高盛/瑞銀/野村/麥格理/瑞士信貸/德意志/大和/巴黎/匯豐/法銀/星展/法國興業);`branchPctile.seatKind()` 不動。

**名詞**:W=20 交易日,視窗同 `computeWindow`(以分點最新日為終點,且分點先截到融資最新日以前);ΔM、股價、法人都從**視窗前一交易日**算到視窗末日(=20 個交易日的變化)。囤貨分點 = `computeWindow(...).acc` 扣外資席位(總公司保留);cov = 囤貨分點合計淨買 ÷ ΔM;inst = 期間外資+投信淨買合計;px = 還原收盤變化;集保:期間內 holders_history ≥2 週點時 Δ400 = 末週−首週 400 張以上持股比(百分點)、Δretail = 未滿 400 張股東人數變化 %。

**20 日分類**(每交易日):
1. 顯著:ΔM ≥ max(200 張, 起點餘額 5%),否則不判讀(不算 cov)。
2. inst ≥ 0.5×ΔM → 法人主導,不判讀。
3. cov ≥0.5 且囤貨合計 ≥200 張且 px ≥ −5% 且非(Δ400 ≤ −0.3)→ `C_MARGIN_UP_CONC`(背景,rank 4)。
4. cov <0.5 且 px ≤ −5% → `C_MARGIN_UP_DISPERSED`(空方 ⚠,rank 4);此時不再列 5 日 `C_MARGIN_UP_PRICE_DOWN`。
5. 其他不判讀。分點缺日(`computeWindow` 不可用)→ 不判讀。

**堆積視窗**(只在融資使用率 ≥60% 時算):起點 = 近 240 筆 margin_history 餘額最低日;需 末日/最低 ≥1.5 且 ΔM ≥500 張;分點視窗取與起點距今交易日數最接近的 20/60/120/240(>20 日用持倉保有率判準);同第 2–4 條分類(期間 = 起點到最新融資日),**只有集中才列** `C_MARGIN_BUILDUP_CONC`(背景,rank 3),並讓 `C_MARGIN_HOT` rank 3→2(文案不變、仍空方、仍取代 R_MARGIN_HOT;rank 2 不進重點、不當標頭)。

**句型**(新事實不設 mirrors):
- `C_MARGIN_UP_CONC`:「融資 20 日增加 +9,111 張(+31.3%),同期囤貨分點 4 家合計淨買超 +9,863 張(為融資增量的 108%),股價 20 日 +3.3%;400張以上大戶 +2.50 個百分點(集保 06/26)」(集保 ≥2 週才有分號後段)。
- `C_MARGIN_UP_DISPERSED`:「融資 20 日增加 +2,058 張(+15.5%),同期無囤貨分點,外資投信合計賣超 14,442 張,股價 20 日 −9.8%;400張以上大戶 −7.33 個百分點、未滿400張股東 +14.6%(集保 10/02)」;有囤貨但 cov<0.5 改寫「同期囤貨分點合計僅為融資增量的 31%」;inst ≥0 省略法人子句。
- `C_MARGIN_BUILDUP_CONC`:「融資餘額自 03/24 的 12,911 張增至 41,400 張(+28,489 張,使用率 75%);近6月囤貨分點 9 家合計淨買超 +33,223 張、400張以上大戶 +7.86 個百分點、股價 +21.2%」。
- 禁詞:主力/鎖碼/大戶融資/散戶融資/買進/賣出/看多/看空/建議/將會(加專案既有禁詞),`chipsFacts.test.ts` 鎖。

**驗證案例**(Fable 正式庫唯讀實查,10-02):
| 股票 | 20 日 | 堆積 | 畫面 |
|---|---|---|---|
| 2476 鉅祥 | 04-17~07-09 七個評估點皆集中;之後融資停增 → 消失 | 起點 03-24 12,911 張;06-26/07-31/10-02 皆集中(統一-敦南 +8,901、康和 +5,722、兆豐-民生 +5,503、永豐金證券 +3,815;集保 ≥400 +7.86pp、散戶人數 −12.7%) | 背景兩條(20 日視窗期間)+ C_MARGIN_HOT rank 2 非重點 |
| 8039 台虹、3450 聯鈞 | 分散且股價跌 | — | 空方 ⚠ C_MARGIN_UP_DISPERSED |
| 2236 百達-KY | 無法判斷 | 大戶 −4.03pp → 無法判斷 | 只有 C_MARGIN_HOT(rank 3) |
| 8932 智通 | 無法判斷(股價 −55.8%) | — | 無新事實 |
| 6538 倉和 | 法人主導 | 集中(股價 +382%:說明為何 C_MARGIN_HOT 不改背景) | 堆積背景 + C_MARGIN_HOT rank 2 |
| 1586 和勤 | 集中 | — | C_MARGIN_UP_CONC |
母體(10-02,ΔM20 顯著 315/1,718 檔):集中 48、集中但跌/大戶減 26、法人主導 97、分散未跌 118、分散且跌 26。

**測試**:`web/lib/facts/fixtures.ts` 的 `marginConcBuildup`(2476 型)、`marginDispersedDown`(8039/3450 型)、`marginInstDominant`、`marginConcForeignOnly`(唯一大買方是外資席位 → 不計)、`marginConcTdccDown`(2236 型 → 無事實)、`marginConcGap`(分點缺日 → 無事實);`chipsFacts.test.ts` 鎖文案/rank/禁詞,`catalogue.test.ts` 覆蓋率,`bullBear.test.ts` 鎖「有堆積集中時 C_MARGIN_HOT rank 2、不在重點、不當標頭;每 code 恰一次」。
**後續(P2)**:`pipeline/tools/margin_flow_audit.py` 唯讀稽核母體分布。
**不做**:不寫主力/鎖碼/歸因;不新增 DB 表或後端匯出;不把融資+集中放多方;不改 R_MARGIN_HOT/I_MARGIN_OK 分數與 60% 門檻;不改 accumulation.ts、seatKind();不用 5 日視窗判集中。
## 5. 不做
不改 tech_score/final/risk_deductions/Armed;不加 S14/R_RESIST;不把 F 事實放 technical.*;不改 reasons/risks 字串陣列與 radar.json;不顯示 points、不相減計數;UI 不出現 做多/做空/看多/看空/買進/賣出/建議;不改預設分頁與其他分頁順序;不新增色票;不改伺服器原文;不碰 adj_factor。
