/**
 * 個股「價格位置」(docs/45):把 export 的 `price_levels` 數字變成階梯列、多空事實句、K 線價位線。
 * 純函式(node --test 可直接跑);句子都在這裡,改措辭不必等下一輪 export。
 *
 * 原則:只寫價位、距離、比例、日期——不寫目標價、不寫預測或「有效／沉重」之類形容(docs/45 §2、§7)。
 * 這些事實只供顯示,**不進任何分數**,也不混進 technical.reasons/risks。
 */
import type { Candle, PriceLevelPoint, PriceLevels, PriceLevelZone } from "@/lib/types";

type OkLevels = Extract<PriceLevels, { status: "ok" }>;

/** 價格小數位依台股升降單位:≥500 元 0 位、50–500 元 1 位、<50 元 2 位(K 線價格軸同一規則)。 */
export function pricePrecision(close: number): number {
  return close >= 500 ? 0 : close >= 50 ? 1 : 2;
}

export function fmtLevelPrice(price: number, close: number): string {
  const d = pricePrecision(close);
  return price.toLocaleString("zh-TW", { minimumFractionDigits: d, maximumFractionDigits: d });
}

/** 與現價的距離(%):上方為 +、下方為 −(U+2212,ChangeText 會上紅/綠)。 */
export function fmtDist(pct: number): string {
  // 對稱四捨五入(Math.round(-62.5) 會得 -62)
  const r = (Math.sign(pct) * Math.round(Math.abs(pct) * 10)) / 10;
  if (r === 0) return "0.0%";
  return `${r > 0 ? "+" : "−"}${Math.abs(r).toFixed(1)}%`;
}

export function fmtShare(share: number): string {
  return `${Math.round(share * 100)}%`;
}

const MA_KEYS = ["5", "10", "20", "60", "120", "240"] as const;
const HL_KEYS = ["20", "60", "120", "240"] as const;
const MA_LABEL: Record<(typeof MA_KEYS)[number], string> = {
  "5": "5日均線", "10": "10日均線", "20": "20日均線", "60": "60日均線", "120": "120日均線", "240": "240日均線",
};
export const MAX_ROWS_PER_SIDE = 5;

export type LadderRow = {
  key: string;
  kind: "ma" | "high" | "low" | "zone";
  side: "above" | "below";
  label: string;
  /** MM/DD;只有前高/前低有 */
  date?: string;
  /** zone 為下緣 */
  price: number;
  /** zone 的上緣 */
  priceHi?: number;
  /** 與現價的距離(%);zone 取靠近現價那一側的邊 */
  dist: number;
  /** zone:該格成交量佔視窗總量 */
  share?: number;
};

export type PriceFactCode =
  | "F1_MA_BELOW" | "F1_MA_ABOVE" | "F2_BULL" | "F2_BEAR" | "F3_HIGH_TODAY" | "F3_LOW_TODAY"
  | "F4_NEW_HIGH" | "F4_NEW_LOW" | "F5_UP" | "F5_DOWN" | "F8_RSI_OK" | "F8_RSI_LOW";

/** 價格位置的多空事實句(進 docs/46 多空摘要)。mirrors = 同方向、同一天時可取代的技術理由 code。 */
export interface PriceLevelFact {
  code: PriceFactCode;
  side: "bull" | "bear";
  text: string;
  mirrors?: string[];
  /** MM/DD;只在 price_levels 的 as_of 不是最新 K 棒日時帶(此時不取代任何技術理由) */
  date?: string;
}

export type PriceLevelsView =
  | { state: "missing" }
  | { state: "insufficient"; asOf: string; bars: number }
  | {
      state: "ok";
      asOf: string;
      close: number;
      above: LadderRow[];
      below: LadderRow[];
      volume: { window: number; above: number; below: number; at: number } | null;
    };

const mmdd = (t: string) => `${t.slice(5, 7)}/${t.slice(8, 10)}`;
const pct = (price: number, close: number) => ((price - close) / close) * 100;

/** 同價同日的 N 日高/低合併成一列,標最長視窗;今日即高/低的那些不進階梯(改成事實句)。 */
function extremes(map: OkLevels["highs"], asOf: string) {
  const merged = new Map<string, { n: string; pt: PriceLevelPoint }>();
  let todayN: string | null = null;
  for (const n of HL_KEYS) {
    const pt = map[n];
    if (!pt) continue;
    if (pt.t === asOf) {
      todayN = n; // 由短到長走,留下最長視窗
      continue;
    }
    merged.set(`${pt.p}@${pt.t}`, { n, pt }); // 後寫的視窗較長 → 覆蓋
  }
  return { rows: [...merged.values()], todayN };
}

function zoneRow(z: PriceLevelZone, side: "above" | "below", close: number): LadderRow {
  return {
    key: `zone-${side}`,
    kind: "zone",
    side,
    label: "成交最密集區",
    price: z.lo,
    priceHi: z.hi,
    dist: pct(side === "above" ? z.lo : z.hi, close),
    share: z.share,
  };
}

/** 一側的階梯:前高/前低與密集區一定留,剩下的位子給離現價最近的均線;最後由高到低排。 */
function pickSide(fixed: LadderRow[], mas: LadderRow[]): LadderRow[] {
  const keep = fixed.slice(0, MAX_ROWS_PER_SIDE);
  const room = MAX_ROWS_PER_SIDE - keep.length;
  const nearest = [...mas].sort((a, b) => Math.abs(a.dist) - Math.abs(b.dist) || a.key.localeCompare(b.key)).slice(0, Math.max(0, room));
  return [...keep, ...nearest].sort((a, b) => (b.priceHi ?? b.price) - (a.priceHi ?? a.price) || a.key.localeCompare(b.key));
}

/** 均線在現價之上/之下的視窗(均線等於現價歸上方,docs/45 F1)。 */
function maSides(pl: OkLevels) {
  const above: (typeof MA_KEYS)[number][] = [];
  const below: (typeof MA_KEYS)[number][] = [];
  for (const n of MA_KEYS) {
    const v = pl.ma[n];
    if (v == null) continue;
    (v >= pl.close ? above : below).push(n);
  }
  return { above, below };
}

/**
 * 價格位置的多空事實(docs/46 §2.5)。lastCandleDate = 個股 K 棒最後一天;as_of 不同時每句帶日期、
 * 不宣告 mirrors(不取代技術理由)。rsi14 來自 technical(F8:50–70 多方、<50 空方、70–80 不列)。
 */
export function priceLevelFacts(
  pl: PriceLevels | null | undefined,
  lastCandleDate?: string | null,
  rsi14?: number | null,
): PriceLevelFact[] {
  if (!pl || pl.status !== "ok") return [];
  const date = lastCandleDate && pl.as_of !== lastCandleDate ? mmdd(pl.as_of) : undefined;
  const out: PriceLevelFact[] = [];
  const add = (code: PriceFactCode, side: "bull" | "bear", text: string, mirrors?: string[]) =>
    out.push(date ? { code, side, text, date } : mirrors?.length ? { code, side, text, mirrors } : { code, side, text });
  const ma = maSides(pl);
  if (ma.below.length) {
    const mirrors = [...(ma.below.includes("20") ? ["T1_MA20"] : []), ...(ma.below.includes("60") ? ["T1_MA60"] : [])];
    add("F1_MA_BELOW", "bull", `站上 ${ma.below.join("/")} 日線`, mirrors);
  }
  if (ma.above.length) add("F1_MA_ABOVE", "bear", `${ma.above.join("/")} 日線在上方`);
  if (pl.ma_align === "bull") add("F2_BULL", "bull", "5/10/20日均線多頭排列", ["T1_BULL_MA"]);
  if (pl.ma_align === "bear") add("F2_BEAR", "bear", "5/10/20日均線空頭排列");
  const hiN = extremes(pl.highs, pl.as_of).todayN;
  const loN = extremes(pl.lows, pl.as_of).todayN;
  if (hiN) add("F3_HIGH_TODAY", "bull", `今日即${hiN}日最高`);
  if (loN) add("F3_LOW_TODAY", "bear", `今日即${loN}日最低`);
  if (pl.new_high_20) add("F4_NEW_HIGH", "bull", "收盤創20日新高", ["T2_20D_HIGH"]);
  if (pl.new_low_20) add("F4_NEW_LOW", "bear", "收盤創20日新低");
  if (pl.vol_price_2d === "up") add("F5_UP", "bull", "連2日量增價漲", ["T4_PRICE_VOLUME_UP"]);
  if (pl.vol_price_2d === "down") add("F5_DOWN", "bear", "連2日量增價跌");
  if (rsi14 != null) {
    const r = Math.round(rsi14);
    if (rsi14 >= 50 && rsi14 <= 70) add("F8_RSI_OK", "bull", `RSI14 ${r},位於 50–70`, ["T5_RSI"]);
    else if (rsi14 < 50) add("F8_RSI_LOW", "bear", `RSI14 ${r},低於 50`);
  }
  return out;
}

/** 舊 JSON 沒有 `price_levels` → missing;不足 20 根 → insufficient。 */
export function priceLevelsView(pl: PriceLevels | null | undefined): PriceLevelsView {
  if (!pl) return { state: "missing" };
  if (pl.status !== "ok") return { state: "insufficient", asOf: pl.as_of, bars: pl.bars };
  const close = pl.close;
  const above: LadderRow[] = [];
  const below: LadderRow[] = [];
  const maRowsAbove: LadderRow[] = [];
  const maRowsBelow: LadderRow[] = [];
  for (const n of MA_KEYS) {
    const v = pl.ma[n];
    if (v == null) continue;
    // 均線與現價相等歸上方(docs/45 F1)
    const side = v >= close ? "above" : "below";
    (side === "above" ? maRowsAbove : maRowsBelow).push({ key: `ma-${n}`, kind: "ma", side, label: MA_LABEL[n], price: v, dist: pct(v, close) });
  }
  const hi = extremes(pl.highs, pl.as_of);
  const lo = extremes(pl.lows, pl.as_of);
  for (const { n, pt } of hi.rows) above.push({ key: `high-${n}`, kind: "high", side: "above", label: `${n}日最高`, date: mmdd(pt.t), price: pt.p, dist: pct(pt.p, close) });
  for (const { n, pt } of lo.rows) below.push({ key: `low-${n}`, kind: "low", side: "below", label: `${n}日最低`, date: mmdd(pt.t), price: pt.p, dist: pct(pt.p, close) });
  if (pl.dense_above) above.push(zoneRow(pl.dense_above, "above", close));
  if (pl.dense_below) below.push(zoneRow(pl.dense_below, "below", close));

  return {
    state: "ok",
    asOf: pl.as_of,
    close,
    above: pickSide(above, maRowsAbove),
    below: pickSide(below, maRowsBelow),
    volume: pl.vol_profile,
  };
}

/** 卡片上的固定字(集中在這裡,禁用詞測試一併掃)。 */
export const PL_LABELS = {
  title: "價格位置",
  adjusted: "還原價",
  current: "現價",
  howto: "怎麼算",
  missing: "這份資料還沒有價格位置(下一輪資料更新後出現)。",
  chartToggle: "壓力/支撐",
  share: "佔",
} as const;

export function insufficientText(bars: number): string {
  return `K 棒只有 ${bars} 根(少於 20 根),暫不計算價格位置。`;
}

export function volumeSplitText(v: { window: number; above: number; below: number }): string {
  return `近${v.window}日成交:現價之上 ${fmtShare(v.above)}、之下 ${fmtShare(v.below)}`;
}

/** 「怎麼算」說明(收合)。 */
export const HOWTO_LINES: readonly string[] = [
  "價格一律還原到資料日的基準(除權息、分割前的價格乘上調整係數),所以前高、前低可能和 K 線上看到的原始價不同;K 線分頁的均線是用原始價畫的。",
  "均線:最近 5/10/20/60/120/240 根收盤的平均;均線等於現價時算在上方。",
  "N 日最高／最低:最近 20/60/120/240 根 K 棒(含今日)的最高價、最低價與日期;K 棒不足 N 根的視窗不列,不縮短。同價同日只列最長的視窗。",
  "現價之上／之下成交:最近 120 根 K 棒,把每根的成交量平均攤在當日最低到最高之間,算有多少落在現價之上、之下。常被稱為套牢賣壓;這裡只算區間內的成交,無法知道是否已經換手。",
  "成交最密集區:同樣 120 根,以現價的 1% 為一格,現價之上、之下各取成交量最多的一格,「佔」是佔 120 日總量的比例。",
  "均線、前高前低等句子另外整理在上方的多方／空方清單;這裡只把現況並列出來,不加減任何分數,也不代表之後的走勢。",
];

export type ChartLevel = { price: number; label: string; side: "above" | "below" };

/**
 * K 線上的壓力/支撐虛線(docs/45 P1):前高/前低與成交最密集區,現價之上、之下各取最近 2 條。
 * K 線畫的是原始價:有日期的前高/前低用該日 af 換回原始價,讓線貼著那根 K 棒;
 * 密集區(跨多日)維持還原價,取一格的中點。
 */
export function chartLevels(pl: PriceLevels | null | undefined, candles: readonly Candle[] = [], perSide = 2): ChartLevel[] {
  if (!pl || pl.status !== "ok") return [];
  const close = pl.close;
  const lastAf = candles.length ? candles[candles.length - 1].af : undefined;
  const afByDate = new Map(candles.map((c) => [c.t, c.af]));
  const toRaw = (p: number, t: string) => {
    const af = afByDate.get(t);
    return lastAf && af ? (p * lastAf) / af : p;
  };
  const hi = extremes(pl.highs, pl.as_of).rows.map(({ n, pt }) => ({ price: toRaw(pt.p, pt.t), adj: pt.p, label: `${n}日高`, side: "above" as const }));
  const lo = extremes(pl.lows, pl.as_of).rows.map(({ n, pt }) => ({ price: toRaw(pt.p, pt.t), adj: pt.p, label: `${n}日低`, side: "below" as const }));
  const za = pl.dense_above ? [{ price: (pl.dense_above.lo + pl.dense_above.hi) / 2, adj: pl.dense_above.lo, label: "密集區", side: "above" as const }] : [];
  const zb = pl.dense_below ? [{ price: (pl.dense_below.lo + pl.dense_below.hi) / 2, adj: pl.dense_below.hi, label: "密集區", side: "below" as const }] : [];
  const near = (xs: { price: number; adj: number; label: string; side: "above" | "below" }[]) =>
    xs.sort((a, b) => Math.abs(a.adj - close) - Math.abs(b.adj - close) || a.label.localeCompare(b.label)).slice(0, perSide);
  return [...near([...hi, ...za]), ...near([...lo, ...zb])].map(({ price, label, side }) => ({ price, label, side }));
}
