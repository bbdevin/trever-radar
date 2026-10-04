# 46 — 個股頁「多空摘要」(Fable 規劃 2026-10-04,已核定)

> 狀態:✅ **P0/P1 已實作(2026-10-04,未上線)**;P2(期貨背景列、F9–F11)未做。實作偏差一則:§3.2 的 `raw_risks` 沒有放進 `all_stocks` 列(那些列會原樣進 radar.json,違反 §5「不改 radar.json」),改放旁表 `raw_risks_by_id`,只寫進個股 payload。

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

## 5. 不做
不改 tech_score/final/risk_deductions/Armed;不加 S14/R_RESIST;不把 F 事實放 technical.*;不改 reasons/risks 字串陣列與 radar.json;不顯示 points、不相減計數;UI 不出現 做多/做空/看多/看空/買進/賣出/建議;不改預設分頁與其他分頁順序;不新增色票;不改伺服器原文;不碰 adj_factor。
