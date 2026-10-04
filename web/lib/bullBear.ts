/**
 * 個股頁「多空摘要」(docs/46):把既有理由、風險、口袋標籤與價格位置事實分成多方/空方/背景三欄。
 * 純函式(node --test 可直接跑)。只整理已發生的事實:不加減分數、不比大小、不排名、不顯示 points。
 *
 * 分類表 SIDE_BY_CODE 必須涵蓋後端所有 code——pipeline/tests/test_bull_bear_codes.py 會從
 * scores.py / indicators.py / pocket.py 抽出全部 code 對這個檔案比對,漏一個就擋 CI。
 */
import type { PocketTag, ReasonItem, TechnicalSummary } from "@/lib/types";
import type { PriceLevelFact } from "@/lib/priceLevels";

export type Side = "bull" | "bear" | "context";
export type Source =
  | "chips" | "inst" | "margin" | "warrant" | "theme" | "tech" | "price" | "strategy" | "company" | "futures" | "other";

export interface BullBearItem {
  key: string;
  code: string | null;
  side: Side;
  source: Source;
  text: string;
  /** 來自風險列(R 開頭、B_RISK_REVERSAL)或空方口袋標籤;畫面前綴警示圖示 */
  risk: boolean;
  /** 只有 as_of 不是資料日的價格事實才帶 */
  date?: string;
}

export interface BullBearSummary {
  asOf: string;
  bull: BullBearItem[];
  bear: BullBearItem[];
  context: BullBearItem[];
  /** 被價格位置事實取代(同方向、同一天)的技術理由 code */
  suppressed: string[];
}

const B = (source: Source) => ({ side: "bull" as Side, source });
const R = (source: Source) => ({ side: "bear" as Side, source });
const C = (source: Source) => ({ side: "context" as Side, source });

/** docs/46 §2 全表(含舊 code K1_KEY_BUY、S4_VOLATILITY_CONTRACTION)。 */
export const SIDE_BY_CODE: Record<string, { side: Side; source: Source }> = {
  // 分點
  B1_BRANCH_STREAK: B("chips"), B2_MULTI_BRANCH: B("chips"), B3_BUY_CONCENTRATION: B("chips"), B6_BIG_MONEY_FLOW: B("chips"),
  B_RISK_REVERSAL: R("chips"),
  G1_GEO_BUY: B("chips"), G2_GEO_SELL: R("chips"), T1_TRACKED_BUY: B("chips"), K1_KEY_BUY: B("chips"),
  // 法人 / 資券
  I_TRUST_BUY: B("inst"), I_TRUST_STREAK: B("inst"), I_FOREIGN_BUY: B("inst"), I_FOREIGN_STREAK: B("inst"),
  I_BOTH_BUY: B("inst"), I_NET_SHARE: B("inst"), R_FOREIGN_SELL5: R("inst"),
  I_MARGIN_OK: B("margin"), R_MARGIN_HOT: R("margin"),
  // 權證
  W1_TURNOVER_X3: B("warrant"), W1_TURNOVER_X2: B("warrant"), W1_TURNOVER_X1_5: B("warrant"),
  W2_VOLUME_X3: B("warrant"), W2_VOLUME_X2: B("warrant"), W3_STOCK_QUIET: B("warrant"),
  W4_STREAK3: B("warrant"), W4_STREAK2: B("warrant"), W5_CALL_DOMINANT: B("warrant"),
  // 題材
  T_THEME_HOT: B("theme"), H1_HOT_THEME: B("theme"),
  // 技術
  T1_MA20: B("tech"), T1_MA60: B("tech"), T1_BULL_MA: B("tech"), T2_20D_HIGH: B("tech"), T2_VOLUME_BREAKOUT: B("tech"),
  T3_BOX_TOP: B("tech"), T4_PRICE_VOLUME_UP: B("tech"), T5_RSI: B("tech"), T5_MACD_HIST_POS: B("tech"), T5_KD_GOLDEN_LOW: B("tech"),
  R_SHOOTING: R("tech"), R_GAP_FADE: R("tech"), R_RSI_OVERHEAT: R("tech"),
  // 價格
  R_HOT5: R("price"), R_HOT10: R("price"),
  // 策略
  S12_BRANCH_ACCUMULATION: B("strategy"), S11_INSTI_BREAKOUT: B("strategy"), S13_SHORT_SQUEEZE: B("strategy"),
  S1_REBOUND: B("strategy"), S1_REBOUND_RELAXED: B("strategy"), S2_BREAKOUT20: B("strategy"),
  S3_MA_CONVERGE_BREAKOUT: B("strategy"), S4_COMPRESSION_BREAKOUT_V2: B("strategy"), S5_PULLBACK_SUPPORT: B("strategy"),
  S6_HIGH_BASE_BREAKOUT: B("strategy"), S7_MACD_ZERO_CROSS: B("strategy"), S8_GAP_BREAKOUT: B("strategy"),
  S9_MA5_TREND: B("strategy"), S10_BOTTOM_MACD: B("strategy"),
  S4_COMPRESSION_SETUP_V2: C("strategy"), S4_VOLATILITY_CONTRACTION: C("strategy"),
  // 公司
  KB1_BUYBACK_WINDOW: C("company"),
};

/** 舊 JSON 只有風險字串(無 code)時,用句中關鍵字回推 code(docs/46 §2.2)。先比長的。 */
export const RISK_TEXT_KEYS: Array<[string, string]> = [
  ["反手賣出", "B_RISK_REVERSAL"],
  ["10日累漲", "R_HOT10"],
  ["5日累漲", "R_HOT5"],
  ["爆量長上影", "R_SHOOTING"],
  ["開高走低", "R_GAP_FADE"],
  ["RSI14超過80", "R_RSI_OVERHEAT"],
  ["外資連5日賣超", "R_FOREIGN_SELL5"],
  ["融資使用率", "R_MARGIN_HOT"],
];

export const SIDE_LABEL: Record<Side, string> = { bull: "多方", bear: "空方", context: "背景" };
export const SOURCE_LABEL: Record<Source, string> = {
  chips: "分點", inst: "法人", margin: "資券", warrant: "權證", theme: "題材",
  tech: "技術", price: "價格", strategy: "策略", company: "公司", futures: "期貨", other: "其他",
};
export const SOURCE_ORDER: readonly Source[] = [
  "chips", "inst", "margin", "warrant", "theme", "tech", "price", "strategy", "company", "futures", "other",
];
export const PANEL_TITLE = "多空";
export const SIDE_DEFINITION = "多方＝對股價有利的已發生事實;空方＝不利或需留意的事實。只整理資料,不下判斷。";
export const COUNT_NOTE = "計數是事實數量,不是分數。";
export const EMPTY_SIDE: Record<"bull" | "bear", string> = {
  bull: "目前沒有符合的多方事實",
  bear: "目前沒有符合的空方事實",
};
/** 每側預設顯示列數,超過收「還有 N 項」 */
export const SIDE_PREVIEW = 6;
export function moreText(n: number): string {
  return `還有 ${n} 項`;
}
export function techDetailsSummary(nReasons: number, nRisks: number): string {
  return `技術訊號原文 加分 ${nReasons} 項・風險 ${nRisks} 項`;
}

export function riskCodeFromText(text: string): string | null {
  for (const [needle, code] of RISK_TEXT_KEYS) if (text.includes(needle)) return code;
  return null;
}

export interface BuildInput {
  rawReasons?: ReasonItem[];
  /** 舊 JSON 的理由字串(只在 rawReasons 缺席時用) */
  reasons: string[];
  rawRisks?: ReasonItem[];
  /** 舊 JSON 的風險字串(只在 rawRisks 缺席時用) */
  risks: string[];
  technical: TechnicalSummary | null;
  pocketTags?: PocketTag[];
  priceFacts?: PriceLevelFact[];
  asOf: string;
  /** 顯示前的文字轉換(舊字樣轉場,如 legacyReasonText);預設原樣 */
  reasonText?: (code: string | null, text: string) => string;
  /** 口袋標籤顯示文字(如 K1→T1 改名轉場);預設 t.text */
  pocketText?: (t: PocketTag) => string;
}

type Draft = BullBearItem & { points: number; order: number };

export function buildBullBear(input: BuildInput): BullBearSummary {
  const rt = input.reasonText ?? ((_c, t) => t);
  const items: Draft[] = [];
  const seen = new Set<string>();
  let order = 0;
  const push = (it: Omit<Draft, "order">) => items.push({ ...it, order: order++ });

  // 價格位置事實先決定要取代哪些技術理由(同方向同一天才取代)
  const facts = input.priceFacts ?? [];
  const mirrored = new Set<string>();
  for (const f of facts) if (!f.date) for (const m of f.mirrors ?? []) mirrored.add(m);
  const suppressed: string[] = [];

  // 理由:raw_reasons ∪ technical.reasons,以 code 去重
  const reasonRows: ReasonItem[] = input.rawReasons
    ? [...input.rawReasons, ...(input.technical?.reasons ?? [])]
    : [...input.reasons.map((text) => ({ code: "", text })), ...(input.technical?.reasons ?? [])];
  for (const r of reasonRows) {
    const code = r.code || null;
    if (code) {
      if (seen.has(code)) continue;
      seen.add(code);
      if (mirrored.has(code)) {
        suppressed.push(code);
        continue;
      }
    }
    const cls = code ? SIDE_BY_CODE[code] : undefined;
    push({
      key: `r:${code ?? r.text}`,
      code,
      side: cls?.side ?? "bull",
      source: cls?.source ?? "other",
      text: rt(code, r.text),
      risk: false,
      points: typeof r.points === "number" ? r.points : 0,
    });
  }

  // 風險:raw_risks ∪ technical.risks,以 code 去重;舊 JSON 用字串回推 code
  const riskRows: ReasonItem[] = input.rawRisks
    ? [...input.rawRisks, ...(input.technical?.risks ?? [])]
    : [...input.risks.map((text) => ({ code: riskCodeFromText(text) ?? "", text })), ...(input.technical?.risks ?? [])];
  for (const r of riskRows) {
    const code = r.code || null;
    if (code) {
      if (seen.has(code)) continue;
      seen.add(code);
    }
    const cls = code ? SIDE_BY_CODE[code] : undefined;
    push({
      key: `k:${code ?? r.text}`,
      code,
      side: cls?.side ?? "bear",
      source: cls?.source ?? "other",
      text: rt(code, r.text),
      risk: true,
      points: typeof r.points === "number" ? r.points : 0,
    });
  }

  for (const t of input.pocketTags ?? []) {
    if (seen.has(t.code)) continue;
    seen.add(t.code);
    const cls = SIDE_BY_CODE[t.code];
    const side = cls?.side ?? "bull";
    push({
      key: `p:${t.code}`,
      code: t.code,
      side,
      source: cls?.source ?? "other",
      text: input.pocketText ? input.pocketText(t) : t.text,
      risk: side === "bear",
      points: 0,
    });
  }

  for (const f of facts) {
    push({ key: `f:${f.code}`, code: f.code, side: f.side, source: "price", text: f.text, risk: false, date: f.date, points: 0 });
  }

  const rank = (s: Source) => SOURCE_ORDER.indexOf(s);
  const sorted = [...items].sort((a, b) => rank(a.source) - rank(b.source) || b.points - a.points || a.order - b.order);
  const strip = ({ points: _p, order: _o, ...it }: Draft): BullBearItem => it;
  return {
    asOf: input.asOf,
    bull: sorted.filter((i) => i.side === "bull").map(strip),
    bear: sorted.filter((i) => i.side === "bear").map(strip),
    context: sorted.filter((i) => i.side === "context").map(strip),
    suppressed,
  };
}

/** 標頭用:該側排第一的事實(來源順序在前、同來源分數高者)。 */
export function topOfSide(s: BullBearSummary, side: "bull" | "bear"): BullBearItem | null {
  return s[side][0] ?? null;
}
