/**
 * 前端事實目錄(docs/46 v2 §2)。每一個 code 的側別、來源、所屬段、可出現的週期與優先級(P0/P1/P2)。
 * 產生器一律透過 text.ts 的 mk() 取這裡的分類,不在各檔另寫一份,避免漂移。
 * mirrors = 同方向、同一天成立時取代的後端 code(只有不帶滯後日期的事實才取代)。
 */
import type { Section, Side, Source, Tf } from "../bullBear.ts";

export interface CatalogueEntry {
  side: Side;
  source: Source;
  section: Section;
  tfs: readonly Tf[];
  prio: 0 | 1 | 2;
  /** 事件型空方:畫面前綴警示圖示 */
  risk?: boolean;
  mirrors?: readonly string[];
}

const D = ["D"] as const;
const DW = ["D", "W"] as const;
const DWM = ["D", "W", "M"] as const;
const WM = ["W", "M"] as const;

const tech = (side: Side, tfs: readonly Tf[], prio: 0 | 1 | 2, extra: Partial<CatalogueEntry> = {}): CatalogueEntry =>
  ({ side, source: "tech", section: "tech", tfs, prio, ...extra });
const lvl = (side: Side, tfs: readonly Tf[], prio: 0 | 1 | 2, extra: Partial<CatalogueEntry> = {}): CatalogueEntry =>
  ({ side, source: "levels", section: "levels", tfs, prio, ...extra });
const chip = (source: Source, side: Side, prio: 0 | 1 | 2, extra: Partial<CatalogueEntry> = {}): CatalogueEntry =>
  ({ side, source, section: "chips", tfs: D, prio, ...extra });

export const FACT_CATALOGUE: Record<string, CatalogueEntry> = {
  // ── 技術(priceLevelFacts 的 D 版 + techFacts 的 W/M 版共用 F 代碼) ──
  F2_BULL: tech("bull", D, 0, { mirrors: ["T1_BULL_MA"] }),
  F2_BEAR: tech("bear", D, 0),
  X_ALIGN_BULL: tech("bull", WM, 0),
  X_ALIGN_BEAR: tech("bear", WM, 0),
  X_MA20_SLOPE_UP: tech("bull", DWM, 1),
  X_MA20_SLOPE_DOWN: tech("bear", DWM, 1),
  X_MA60_SLOPE_UP: tech("bull", DW, 1),
  X_MA60_SLOPE_DOWN: tech("bear", DW, 1),
  X_MA_CROSS_UP: tech("bull", DWM, 0),
  X_MA_CROSS_DOWN: tech("bear", DWM, 0, { risk: true }),
  X_MACD_CROSS_UP: tech("bull", DWM, 0, { mirrors: ["T5_MACD_HIST_POS"] }),
  X_MACD_CROSS_DOWN: tech("bear", DWM, 0, { risk: true }),
  X_MACD_STATE_POS: tech("bull", DWM, 1),
  X_MACD_STATE_NEG: tech("bear", DWM, 1),
  X_KD_GOLDEN_LOW: tech("bull", DWM, 0, { mirrors: ["T5_KD_GOLDEN_LOW"] }),
  X_KD_DEATH_HIGH: tech("bear", DWM, 0, { risk: true }),
  X_KD_OVER80: tech("bear", DWM, 1),
  F8_RSI_OK: tech("bull", DWM, 0, { mirrors: ["T5_RSI"] }),
  F8_RSI_LOW: tech("bear", DWM, 0),
  X_VOL_SURGE_UP: tech("bull", DWM, 0, { mirrors: ["T2_VOLUME_BREAKOUT"] }),
  X_VOL_SURGE_DOWN: tech("bear", DWM, 0),
  X_VOL_DRY: tech("context", DW, 2),
  F5_UP: tech("bull", DWM, 0, { mirrors: ["T4_PRICE_VOLUME_UP"] }),
  F5_DOWN: tech("bear", DWM, 0),
  F4_NEW_HIGH: tech("bull", DWM, 0, { mirrors: ["T2_20D_HIGH"] }),
  F4_NEW_LOW: tech("bear", DWM, 0),
  F3_HIGH_TODAY: tech("bull", D, 0),
  F3_LOW_TODAY: tech("bear", D, 0),
  X_UP_STREAK: tech("bull", DW, 0),
  X_DOWN_STREAK: tech("bear", DW, 0),
  X_CHG1_UP: tech("bull", D, 0),
  X_CHG1_DOWN: tech("bear", D, 0),
  X_CHG5_UP: tech("bull", D, 0),
  X_CHG5_DOWN: tech("bear", D, 0),
  X_GAP_UP_TODAY: tech("bull", D, 1),
  X_GAP_DOWN_TODAY: tech("bear", D, 1, { risk: true }),
  X_BIG_BLACK: tech("bear", D, 1, { risk: true }),
  // 壓力段 ≤3% 的價位在技術段的對應句(levelFacts.nearLevelFacts,docs/46 §6.9)
  X_LEVEL_ABOVE_NEAR: tech("bear", D, 0),
  X_LEVEL_BELOW_NEAR: tech("bull", D, 0),
  // 收盤相對 20 日線的連續天數(docs/45 F11,P2;狀態型 rank 2,不進多方榜 K 鍵)
  F11_MA20_ABOVE_N: tech("bull", D, 2),
  F11_MA20_BELOW_N: tech("bear", D, 2),

  // ── 壓力 ──
  F1_MA_BELOW: lvl("bull", DWM, 0, { mirrors: ["T1_MA20", "T1_MA60"] }),
  F1_MA_ABOVE: lvl("bear", DWM, 0),
  L_HIGH_ABOVE: lvl("bear", D, 0),
  L_LOW_BELOW: lvl("bull", D, 0),
  L_ALLTIME_HIGH: lvl("bear", D, 1),
  L_ALLTIME_LOW: lvl("bull", D, 1),
  L_DENSE_ABOVE: lvl("bear", D, 0),
  L_DENSE_BELOW: lvl("bull", D, 0),
  L_SUPPLY_ABOVE: lvl("bear", D, 0),
  L_SUPPLY_BELOW: lvl("bull", D, 0),
  L_GAP_ABOVE: lvl("bear", D, 1),
  L_GAP_BELOW: lvl("bull", D, 1),
  L_RANGE_POS_TOP: lvl("bull", D, 1, { mirrors: ["T3_BOX_TOP"] }),
  L_RANGE_POS_BOTTOM: lvl("bear", D, 1),

  // ── 法人 ──
  C_FOREIGN_BUY: chip("inst", "bull", 0, { mirrors: ["I_FOREIGN_BUY", "I_FOREIGN_STREAK"] }),
  C_FOREIGN_SELL: chip("inst", "bear", 0, { mirrors: ["R_FOREIGN_SELL5"] }),
  C_TRUST_BUY: chip("inst", "bull", 0, { mirrors: ["I_TRUST_BUY", "I_TRUST_STREAK"] }),
  C_TRUST_SELL: chip("inst", "bear", 0),
  C_BOTH_BUY: chip("inst", "bull", 0, { mirrors: ["I_BOTH_BUY"] }),
  C_BOTH_SELL: chip("inst", "bear", 0),
  C_NET_SHARE_BUY: chip("inst", "bull", 0, { mirrors: ["I_NET_SHARE"] }),
  C_NET_SHARE_SELL: chip("inst", "bear", 0),
  C_FOREIGN_20D_BUY: chip("inst", "bull", 1),
  C_FOREIGN_20D_SELL: chip("inst", "bear", 1),
  C_TRUST_20D_BUY: chip("inst", "bull", 1),
  C_TRUST_20D_SELL: chip("inst", "bear", 1),

  // ── 資券 ──
  C_MARGIN_HOT: chip("margin", "bear", 0, { mirrors: ["R_MARGIN_HOT"] }),
  C_MARGIN_OK: chip("margin", "bull", 0, { mirrors: ["I_MARGIN_OK"] }),
  C_MARGIN_UP_PRICE_DOWN: chip("margin", "bear", 0),
  C_MARGIN_DOWN_PRICE_UP: chip("margin", "bull", 0),
  C_SHORT_CHANGE: chip("margin", "context", 1),
  C_SHORT_MARGIN_RATIO: chip("margin", "context", 2),
  // 融資增量 × 同期分點囤貨/集保(docs/46 §7):只並列、不歸因;不取代任何後端 code
  C_MARGIN_UP_CONC: chip("margin", "context", 1),
  C_MARGIN_UP_DISPERSED: chip("margin", "bear", 1, { risk: true }),
  C_MARGIN_BUILDUP_CONC: chip("margin", "context", 1),

  // ── 分點 ──
  C_TOP15_FLOW_BUY: chip("chips", "bull", 0, { mirrors: ["B6_BIG_MONEY_FLOW"] }),
  C_TOP15_FLOW_SELL: chip("chips", "bear", 0),
  C_ACC_1M: chip("chips", "bull", 0),
  C_DIST_1M: chip("chips", "bear", 0, { risk: true }),
  C_ACC_1W: chip("chips", "bull", 1),
  C_DIST_1W: chip("chips", "bear", 1, { risk: true }),
  C_DAYTRADE_BUY: chip("chips", "bear", 0),
  C_TRACKED_SELL: chip("chips", "bear", 0),
  C_GEO_BUY: chip("chips", "bull", 1, { mirrors: ["G1_GEO_BUY"] }),
  C_GEO_SELL: chip("chips", "bear", 1, { mirrors: ["G2_GEO_SELL"] }),
  C_PNL_GAINERS_HOLDING: chip("chips", "bull", 1),
  C_PNL_LOSERS_HOLDING: chip("chips", "bear", 1),
  // 低買高賣排行前段/區間損益估算前段分點(docs/46 §6.8)
  C_SMART_BUY: chip("chips", "bull", 0),
  C_SMART_SELL: chip("chips", "bear", 0, { risk: true }),
  C_SMART_HOLDING: chip("chips", "bull", 1),
  // 強分點仍持股但帳面為負(估算):不是多方證據,列背景
  C_SMART_HOLDING_NEG: chip("chips", "context", 1),

  // ── 大戶(集保週資料)/ 董監 ──
  H_MAJOR400_UP: chip("holders", "bull", 0),
  H_MAJOR400_DOWN: chip("holders", "bear", 0),
  H_MAJOR1000_UP: chip("holders", "bull", 0),
  H_MAJOR1000_DOWN: chip("holders", "bear", 0),
  H_RETAIL_DOWN: chip("holders", "bull", 0),
  H_RETAIL_UP: chip("holders", "bear", 0),
  H_MAJOR_COUNT: chip("holders", "context", 1),
  H_INSIDER_UP: chip("holders", "bull", 1),
  H_INSIDER_DOWN: chip("holders", "bear", 1),
  H_PLEDGE_HIGH: chip("holders", "context", 2),

  // ── 權證 / 期貨 / 題材 / 公司 ──
  C_PUT_DOMINANT: chip("warrant", "bear", 0),
  C_PUT_SURGE: chip("warrant", "bear", 1),
  C_FUT_VOLUME_HIGH: chip("futures", "context", 1),
  C_THEME_HOT: chip("theme", "bull", 1, { mirrors: ["T_THEME_HOT", "H1_HOT_THEME"] }),
  C_THEME_COLD: chip("theme", "context", 1),
  C_BUYBACK: chip("company", "context", 1, { mirrors: ["KB1_BUYBACK_WINDOW"] }),
};
