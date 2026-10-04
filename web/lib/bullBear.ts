/**
 * 個股頁「多空」(docs/46 v2):把既有理由、風險、口袋標籤與前端事實(web/lib/facts/*)分成
 * 技術分析/籌碼分析/壓力分析三段,每段左多方、右空方,另列背景。
 * 純函式(node --test 可直接跑)。只整理已發生的事實:不加減分數、不比大小、不顯示 points/rank。
 *
 * 分類表 SIDE_BY_CODE 必須涵蓋後端所有 code——pipeline/tests/test_bull_bear_codes.py 會從
 * scores.py / indicators.py / pocket.py / futures_volume_anomaly.py 抽出全部 code 對這個檔案比對,
 * 漏一個就擋 CI。前端自己產生的事實 code 在 web/lib/facts/catalogue.ts。
 *
 * 這個檔案不 import 任何執行期模組(只有型別):node --test 認不得 "@/" 別名。
 */
import type { PocketTag, ReasonItem, TechnicalSummary } from "@/lib/types";

export type Side = "bull" | "bear" | "context";
export type Source =
  | "chips" | "inst" | "margin" | "holders" | "warrant" | "theme" | "tech" | "price" | "levels"
  | "strategy" | "company" | "futures" | "other";
export type Section = "tech" | "chips" | "levels";
export type Tf = "D" | "W" | "M";

/** 句子的一段;kind 決定顏色(價格藍、+ 紅、− 綠)。join 起來必須等於 text。 */
export type SegKind = "price" | "up" | "down" | "flat";
export interface Seg {
  t: string;
  kind?: SegKind;
}

export interface BullBearItem {
  key: string;
  code: string | null;
  side: Side;
  source: Source;
  section: Section;
  text: string;
  /** 有就逐段上色;沒有(後端原文)就交給 ChangeText 的 ±% 規則 */
  segments?: Seg[];
  /** 後端風險(R*、B_RISK_REVERSAL)、空方口袋標籤、事件型空方;畫面前綴警示圖示 */
  risk: boolean;
  /** 滯後資料的日期(MM/DD);列尾小字 */
  date?: string;
  /** 週更/月更資料的資料日(MM/DD),群組頭用(大戶「集保 MM/DD」) */
  dataDate?: string;
  /** 技術段的週期;後端技術/策略理由一律 D */
  tf?: Tf;
  /** 1–5,只用來排序與挑標頭那一條,不顯示 */
  rank: number;
  /** 同 rank 時的比較量(佔量 %、距離 %、百分點);不顯示 */
  magnitude?: number;
  /** 壓力段:與現價距離 %(絕對值),段內由近到遠 */
  dist?: number;
}

/** 前端事實產生器(web/lib/facts/*、priceLevelFacts)的輸出。 */
export interface DerivedFact {
  code: string;
  side: Side;
  source: Source;
  section: Section;
  text: string;
  segments?: Seg[];
  tf?: Tf;
  risk?: boolean;
  rank?: number;
  magnitude?: number;
  dist?: number;
  /** 同方向、同一天時可取代的後端 code;帶 date/dataDate 的事實不取代任何東西 */
  mirrors?: string[];
  date?: string;
  dataDate?: string;
  /** 同 code 同週期可有多列時的區分(N 日高、缺口序號…) */
  variant?: string;
}

export interface SectionBuckets {
  bull: BullBearItem[];
  bear: BullBearItem[];
  context: BullBearItem[];
}

export interface BullBearSummary {
  asOf: string;
  bull: BullBearItem[];
  bear: BullBearItem[];
  context: BullBearItem[];
  sections: Record<Section, SectionBuckets>;
  /** 被前端事實取代(同方向、同一天)或依 §3 規則讓位的 code */
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
  // 技術(含累漲:v2 歸技術段日K)
  T1_MA20: B("tech"), T1_MA60: B("tech"), T1_BULL_MA: B("tech"), T2_20D_HIGH: B("tech"), T2_VOLUME_BREAKOUT: B("tech"),
  T3_BOX_TOP: B("tech"), T4_PRICE_VOLUME_UP: B("tech"), T5_RSI: B("tech"), T5_MACD_HIST_POS: B("tech"), T5_KD_GOLDEN_LOW: B("tech"),
  R_SHOOTING: R("tech"), R_GAP_FADE: R("tech"), R_RSI_OVERHEAT: R("tech"),
  R_HOT5: R("tech"), R_HOT10: R("tech"),
  // 策略(S11–S13 是籌碼事件,v2 歸籌碼段對應來源)
  S12_BRANCH_ACCUMULATION: B("chips"), S11_INSTI_BREAKOUT: B("inst"), S13_SHORT_SQUEEZE: B("margin"),
  S1_REBOUND: B("strategy"), S1_REBOUND_RELAXED: B("strategy"), S2_BREAKOUT20: B("strategy"),
  S3_MA_CONVERGE_BREAKOUT: B("strategy"), S4_COMPRESSION_BREAKOUT_V2: B("strategy"), S5_PULLBACK_SUPPORT: B("strategy"),
  S6_HIGH_BASE_BREAKOUT: B("strategy"), S7_MACD_ZERO_CROSS: B("strategy"), S8_GAP_BREAKOUT: B("strategy"),
  S9_MA5_TREND: B("strategy"), S10_BOTTOM_MACD: B("strategy"),
  S4_COMPRESSION_SETUP_V2: C("strategy"), S4_VOLATILITY_CONTRACTION: C("strategy"),
  // 公司
  KB1_BUYBACK_WINDOW: C("company"),
  // 期貨成交量異常(契約層級旗標,方向未定 → 背景;個股頁由 facts/futuresFacts 產句)
  F1_FUTURES_VOLUME_60D_HIGH: C("futures"), R_FUTURES_VOLUME_NO_DIRECTION: C("futures"),
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

/** 後端 code 出現時,讓位的前端事實(docs/46 v2 §3 去重 5)。 */
export const YIELD_TO_BACKEND: Record<string, string[]> = {
  R_HOT5: ["X_CHG5_UP"],
  R_HOT10: ["X_CHG5_UP"],
  R_GAP_FADE: ["X_GAP_UP_TODAY"],
  R_SHOOTING: ["X_BIG_BLACK"],
};

export const SIDE_LABEL: Record<Side, string> = { bull: "多方", bear: "空方", context: "背景" };
export const SOURCE_LABEL: Record<Source, string> = {
  chips: "分點", inst: "法人", margin: "資券", holders: "大戶", warrant: "權證", theme: "題材",
  tech: "技術", price: "價格", levels: "壓力", strategy: "策略", company: "公司", futures: "期貨", other: "其他",
};
export const SOURCE_ORDER: readonly Source[] = [
  "chips", "inst", "margin", "holders", "warrant", "theme", "tech", "price", "levels", "strategy", "company", "futures", "other",
];
export const SECTION_ORDER: readonly Section[] = ["tech", "chips", "levels"];
export const SECTION_LABEL: Record<Section, string> = { tech: "技術分析", chips: "籌碼分析", levels: "壓力分析" };
export const SECTION_SHORT: Record<Section, string> = { tech: "技術", chips: "籌碼", levels: "壓力" };
/** 欄頭:壓力段左欄是下方支撐、右欄是上方壓力 */
export const COLUMN_LABEL: Record<Section, Record<"bull" | "bear", string>> = {
  tech: { bull: "多方", bear: "空方" },
  chips: { bull: "多方", bear: "空方" },
  levels: { bull: "下方支撐", bear: "上方壓力" },
};
export const SECTION_BY_SOURCE: Record<Source, Section> = {
  tech: "tech", strategy: "tech",
  price: "levels", levels: "levels",
  chips: "chips", inst: "chips", margin: "chips", holders: "chips", warrant: "chips", theme: "chips",
  company: "chips", futures: "chips", other: "chips",
};
export const TF_LABEL: Record<Tf, string> = { D: "日K", W: "週K", M: "月K" };
export const TF_CHIP: Record<Tf, string> = { D: "日", W: "週", M: "月" };
export const PANEL_TITLE = "多空";
export const SIDE_DEFINITION = "多方＝對股價有利的已發生事實;空方＝不利或需留意的事實。只整理資料,不下判斷。";
export const COUNT_NOTE = "計數是事實數量,不是分數。";
export const EMPTY_SIDE: Record<"bull" | "bear", string> = {
  bull: "目前沒有符合的多方事實",
  bear: "目前沒有符合的空方事實",
};
export const CONTEXT_LABEL = "背景";

export function techDetailsSummary(nReasons: number, nRisks: number): string {
  return `技術訊號原文 加分 ${nReasons} 項・風險 ${nRisks} 項`;
}

/** 總覽列一段:「技術 ▲5 ▼3」 */
export function overviewText(s: BullBearSummary, section: Section): string {
  const b = s.sections[section];
  return `${SECTION_SHORT[section]} ▲${b.bull.length} ▼${b.bear.length}`;
}

export function riskCodeFromText(text: string): string | null {
  for (const [needle, code] of RISK_TEXT_KEYS) if (text.includes(needle)) return code;
  return null;
}

/** 後端 code 的排序權重(1–5,docs/46 v2 §3):5 今日事件且有張數、4 今日顯著流向、3 多日狀態、2 位置、1 背景。 */
export function backendRank(code: string | null, side: Side): number {
  if (!code) return side === "context" ? 1 : 3;
  if (code === "B_RISK_REVERSAL") return 5;
  if (side === "context") return 1;
  if (code.startsWith("R_")) return 4;
  if (/^(B[1-6]_|G[12]_|T1_TRACKED|K1_|I_(TRUST|FOREIGN)_BUY|I_BOTH|I_NET|T2_)/.test(code)) return 4;
  if (code === "I_MARGIN_OK") return 1;
  if (code === "T_THEME_HOT" || code === "H1_HOT_THEME") return 2;
  return 3;
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
  /** priceLevelFacts() 的輸出(也是 DerivedFact) */
  priceFacts?: DerivedFact[];
  /** deriveAllFacts() 的輸出 */
  derivedFacts?: DerivedFact[];
  asOf: string;
  /** 顯示前的文字轉換(舊字樣轉場,如 legacyReasonText);預設原樣 */
  reasonText?: (code: string | null, text: string) => string;
  /** 口袋標籤顯示文字(如 K1→T1 改名轉場);預設 t.text */
  pocketText?: (t: PocketTag) => string;
}

type Draft = BullBearItem & { points: number; order: number };

const TF_ORDER: Record<Tf, number> = { D: 0, W: 1, M: 2 };

/** 欄內分組序:技術=日/週/月、籌碼=來源序、壓力=不分組(距離)。 */
function groupIndex(it: BullBearItem): number {
  if (it.section === "tech") return TF_ORDER[it.tf ?? "D"];
  if (it.section === "chips") return SOURCE_ORDER.indexOf(it.source);
  return 0;
}

function compareInSection(a: Draft, b: Draft): number {
  const g = groupIndex(a) - groupIndex(b);
  if (g) return g;
  if (a.section === "levels") {
    const d = (a.dist ?? Infinity) - (b.dist ?? Infinity);
    if (d) return d;
  }
  return b.rank - a.rank || (b.magnitude ?? 0) - (a.magnitude ?? 0) || b.points - a.points || a.order - b.order;
}

export function factKey(f: Pick<DerivedFact, "code" | "tf" | "variant">): string {
  return `d:${f.code}:${f.tf ?? ""}:${f.variant ?? ""}`;
}

export function buildBullBear(input: BuildInput): BullBearSummary {
  const rt = input.reasonText ?? ((_c, t) => t);
  const items: Draft[] = [];
  const seen = new Set<string>();
  let order = 0;
  const push = (it: Omit<Draft, "order">) => items.push({ ...it, order: order++ });
  const suppressed: string[] = [];

  // 理由/風險列(先收齊,讓位規則要知道後端有哪些 code)
  const reasonRows: ReasonItem[] = input.rawReasons
    ? [...input.rawReasons, ...(input.technical?.reasons ?? [])]
    : [...input.reasons.map((text) => ({ code: "", text })), ...(input.technical?.reasons ?? [])];
  const riskRows: ReasonItem[] = input.rawRisks
    ? [...input.rawRisks, ...(input.technical?.risks ?? [])]
    : [...input.risks.map((text) => ({ code: riskCodeFromText(text) ?? "", text })), ...(input.technical?.risks ?? [])];
  const backendCodes = new Set([...reasonRows, ...riskRows].map((r) => r.code).filter(Boolean));
  const yielded = new Set<string>();
  for (const c of backendCodes) for (const y of YIELD_TO_BACKEND[c] ?? []) yielded.add(y);

  // 前端事實:讓位、去重,並決定要取代哪些後端 code(同方向同一天才取代)
  const facts: DerivedFact[] = [];
  const factKeys = new Set<string>();
  for (const f of [...(input.priceFacts ?? []), ...(input.derivedFacts ?? [])]) {
    const k = factKey(f);
    if (factKeys.has(k)) continue;
    factKeys.add(k);
    if (yielded.has(f.code)) {
      if (!suppressed.includes(f.code)) suppressed.push(f.code);
      continue;
    }
    facts.push(f);
  }
  const mirrored = new Set<string>();
  for (const f of facts) if (!f.date && !f.dataDate) for (const m of f.mirrors ?? []) mirrored.add(m);

  const backend = (r: ReasonItem, kind: "r" | "k", defaultSide: Side) => {
    const code = r.code || null;
    if (code) {
      if (seen.has(code)) return;
      seen.add(code);
      if (mirrored.has(code)) {
        suppressed.push(code);
        return;
      }
    }
    const cls = code ? SIDE_BY_CODE[code] : undefined;
    const side = cls?.side ?? defaultSide;
    const source = cls?.source ?? "other";
    const section = SECTION_BY_SOURCE[source];
    push({
      key: `${kind}:${code ?? r.text}`,
      code,
      side,
      source,
      section,
      text: rt(code, r.text),
      risk: kind === "k",
      ...(section === "tech" ? { tf: "D" as Tf } : {}),
      rank: backendRank(code, side),
      points: typeof r.points === "number" ? r.points : 0,
    });
  };
  for (const r of reasonRows) backend(r, "r", "bull");
  for (const r of riskRows) backend(r, "k", "bear");

  for (const t of input.pocketTags ?? []) {
    if (seen.has(t.code)) continue;
    seen.add(t.code);
    if (mirrored.has(t.code)) {
      suppressed.push(t.code);
      continue;
    }
    const cls = SIDE_BY_CODE[t.code];
    const side = cls?.side ?? "bull";
    const source = cls?.source ?? "other";
    push({
      key: `p:${t.code}`,
      code: t.code,
      side,
      source,
      section: SECTION_BY_SOURCE[source],
      text: input.pocketText ? input.pocketText(t) : t.text,
      risk: side === "bear",
      rank: backendRank(t.code, side),
      points: 0,
    });
  }

  for (const f of facts) {
    push({
      key: factKey(f),
      code: f.code,
      side: f.side,
      source: f.source,
      section: f.section,
      text: f.text,
      ...(f.segments ? { segments: f.segments } : {}),
      risk: !!f.risk,
      ...(f.date ? { date: f.date } : {}),
      ...(f.dataDate ? { dataDate: f.dataDate } : {}),
      ...(f.tf ? { tf: f.tf } : f.section === "tech" ? { tf: "D" as Tf } : {}),
      rank: f.rank ?? 3,
      ...(f.magnitude != null ? { magnitude: f.magnitude } : {}),
      ...(f.dist != null ? { dist: f.dist } : {}),
      points: 0,
    });
  }

  const sectionIdx = (s: Section) => SECTION_ORDER.indexOf(s);
  const sorted = [...items].sort((a, b) => sectionIdx(a.section) - sectionIdx(b.section) || compareInSection(a, b));
  const strip = ({ points: _p, order: _o, ...it }: Draft): BullBearItem => it;
  const all = sorted.map((d) => ({ d, it: strip(d) }));
  const pick = (side: Side, section?: Section) =>
    all.filter(({ it }) => it.side === side && (!section || it.section === section)).map(({ it }) => it);
  const sections = Object.fromEntries(
    SECTION_ORDER.map((sec) => [sec, { bull: pick("bull", sec), bear: pick("bear", sec), context: pick("context", sec) }]),
  ) as Record<Section, SectionBuckets>;
  return {
    asOf: input.asOf,
    bull: pick("bull"),
    bear: pick("bear"),
    context: pick("context"),
    sections,
    suppressed,
  };
}

/** 標頭用的段序:壓力(距離 ≤3%)→ 籌碼 → 技術 → 其餘壓力。 */
function headerSectionIdx(it: BullBearItem): number {
  if (it.section === "levels") return it.dist != null && it.dist <= 3 ? 0 : 3;
  return it.section === "chips" ? 1 : 2;
}

/** 標頭用:該側 rank 最高的一條;同 rank 比 magnitude,再比段序、來源序,最後保留原順序。 */
export function topOfSide(s: BullBearSummary, side: "bull" | "bear"): BullBearItem | null {
  let best: BullBearItem | null = null;
  let bestIdx = -1;
  s[side].forEach((it, i) => {
    if (!best) {
      best = it;
      bestIdx = i;
      return;
    }
    const b: BullBearItem = best;
    const c =
      it.rank - b.rank ||
      (it.magnitude ?? 0) - (b.magnitude ?? 0) ||
      headerSectionIdx(b) - headerSectionIdx(it) ||
      SOURCE_ORDER.indexOf(b.source) - SOURCE_ORDER.indexOf(it.source) ||
      bestIdx - i;
    if (c > 0) {
      best = it;
      bestIdx = i;
    }
  });
  return best;
}

export interface FactGroup {
  key: string;
  /** null = 不畫群組頭(壓力段) */
  label: string | null;
  source?: Source;
  items: BullBearItem[];
}

/** 一欄依段落規則分組:技術=日K/週K/月K;籌碼=來源(大戶附集保資料日);壓力=不分組。 */
export function groupColumn(items: BullBearItem[], section: Section): FactGroup[] {
  if (section === "levels") return items.length ? [{ key: "all", label: null, items }] : [];
  const out: FactGroup[] = [];
  for (const it of items) {
    const key = section === "tech" ? (it.tf ?? "D") : it.source;
    let g = out.find((x) => x.key === key);
    if (!g) {
      let label = section === "tech" ? TF_LABEL[it.tf ?? "D"] : SOURCE_LABEL[it.source];
      if (section === "chips" && it.source === "holders") {
        const dd = items.find((x) => x.source === "holders" && x.dataDate)?.dataDate;
        if (dd) label = `大戶(集保 ${dd})`;
      }
      g = { key, label, ...(section === "chips" ? { source: it.source } : {}), items: [] };
      out.push(g);
    }
    g.items.push(it);
  }
  return out;
}
