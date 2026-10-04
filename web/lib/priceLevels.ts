/**
 * 個股「價格位置」(docs/45):把 export 的 `price_levels` 數字變成階梯列、多空事實句、K 線價位線。
 * 純函式(node --test 可直接跑);句子都在這裡,改措辭不必等下一輪 export。
 *
 * 原則:只寫價位、距離、比例、日期——不寫目標價、不寫預測或「有效／沉重」之類形容(docs/45 §2、§7)。
 * 這些事實只供顯示,**不進任何分數**,也不混進 technical.reasons/risks。
 */
import type { Candle, PriceLevelPoint, PriceLevels, PriceLevelZone } from "@/lib/types";
import type { DerivedFact, Section, Seg, Source } from "@/lib/bullBear";

export type OkLevels = Extract<PriceLevels, { status: "ok" }>;

/** 價格小數位依台股升降單位:≥500 元 0 位、50–500 元 1 位、<50 元 2 位(K 線價格軸同一規則)。 */
export function pricePrecision(close: number): number {
  return close >= 500 ? 0 : close >= 50 ? 1 : 2;
}

export function fmtLevelPrice(price: number, close: number): string {
  const d = pricePrecision(close);
  return price.toLocaleString("zh-TW", { minimumFractionDigits: d, maximumFractionDigits: d });
}

/** 與現價的距離(%):上方為 +、下方為 −(U+2212,ChangeText 會上紅/綠)。純數字版(觀察價/失效價用)。 */
export function fmtDist(pct: number): string {
  // 對稱四捨五入(Math.round(-62.5) 會得 -62)
  const r = (Math.sign(pct) * Math.round(Math.abs(pct) * 10)) / 10;
  if (r === 0) return "0.0%";
  return `${r > 0 ? "+" : "−"}${Math.abs(r).toFixed(1)}%`;
}

/**
 * 價位距離四捨五入到畫面一位小數後為 0(|d| < 0.05%):均線、前高前低、缺口等單一價位與現價幾乎相等。
 * 畫面不寫「在上方 0.0%」,寫 AT_PRICE;與 fmtDist 同一個四捨五入,字和判斷不會打架。
 */
export function isAtPrice(distPct: number): boolean {
  return Math.round(Math.abs(distPct) * 10) === 0;
}
export const AT_PRICE = "貼近現價";

/** 價位距離的畫面字(階梯、壓力段句、技術段「3% 內」句共用):貼近現價 / +1.2% / −1.2%。 */
export function fmtLevelDist(pct: number): string {
  return isAtPrice(pct) ? AT_PRICE : fmtDist(pct);
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
/**
 * 距現價 ≤3% 視為「接近」(壓力段句尾加註、rank 升級;技術段另成「3% 內壓力/支撐價位」句)。
 * 壓力段與技術段共用這一個門檻。
 */
export const NEAR_PCT = 3;
/** 距離(%,正負皆可)是否「接近」:先依畫面的一位小數四捨五入再比,畫面寫 +3.0% 的就算接近,不會一邊寫 3.0% 一邊說 3% 內沒有。 */
export function isNear(distPct: number): boolean {
  return Math.round(Math.abs(distPct) * 10) / 10 <= NEAR_PCT;
}
/** 成交最密集區佔量低於 0.5% 不列(那一側幾乎沒有成交,「最密集」沒有意義);階梯、K 線虛線、事實句共用 */
export const DENSE_MIN_SHARE = 0.005;

/** 有意義的成交最密集區(佔量 ≥ DENSE_MIN_SHARE);階梯、K 線虛線、事實句都從這裡取,不各自判斷。 */
export function denseZone(pl: OkLevels, side: "above" | "below"): PriceLevelZone | null {
  const z = side === "above" ? pl.dense_above : pl.dense_below;
  return z && z.share >= DENSE_MIN_SHARE ? z : null;
}

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

/**
 * 價格位置的多空事實句(進 docs/46 多空)。mirrors = 同方向、同一天時可取代的技術理由 code;
 * date(MM/DD)只在 price_levels 的 as_of 不是最新 K 棒日時帶(此時不取代任何技術理由)。
 * F1 歸壓力段,其餘(F2–F5、F8)歸技術段日K。
 */
export interface PriceLevelFact extends DerivedFact {
  code: PriceFactCode;
  side: "bull" | "bear";
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
export function extremes(map: OkLevels["highs"], asOf: string) {
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

/** 價位距離片段(+ 紅、− 綠;貼近現價中性)。 */
export function distSeg(d: number): Seg {
  if (isAtPrice(d)) return { t: AT_PRICE, kind: "flat" };
  const t = fmtDist(d);
  return { t, kind: t.startsWith("+") ? "up" : "down" };
}

export type MaNear = { n: string; v: number };

/** 均線分上下(均線等於現價歸上方,docs/45 F1),並找出各側最接近現價的一條。 */
export function maSplit(ma: Partial<Record<string, number | null>>, keys: readonly string[], close: number) {
  const above: string[] = [];
  const below: string[] = [];
  let nearAbove: MaNear | null = null;
  let nearBelow: MaNear | null = null;
  for (const n of keys) {
    const v = ma[n];
    if (v == null) continue;
    if (v >= close) {
      above.push(n);
      if (!nearAbove || v < nearAbove.v) nearAbove = { n, v };
    } else {
      below.push(n);
      if (!nearBelow || v > nearBelow.v) nearBelow = { n, v };
    }
  }
  return { above, below, nearAbove, nearBelow };
}

/** 均線價位的短標(DerivedFact.level):「20日線 952」 */
export function maLevelSegs(near: MaNear, close: number, unit: string): Seg[] {
  return [{ t: `${near.n}${unit}線 ` }, { t: fmtLevelPrice(near.v, close), kind: "price" }];
}

/** F1 句:「站上 5/10/20 日線,最接近 20日線 952(−12.2%)」/「60/120 日線在上方,最接近 60日線 1,150(+6.0%)」 */
export function maSideSegs(side: "above" | "below", keys: readonly string[], near: MaNear, close: number, unit: string): Seg[] {
  const head = side === "below" ? `站上 ${keys.join("/")} ${unit}線` : `${keys.join("/")} ${unit}線在上方`;
  return [
    { t: `${head},最接近 ${near.n}${unit}線 ` },
    { t: fmtLevelPrice(near.v, close), kind: "price" },
    { t: "(" },
    distSeg(pct(near.v, close)),
    { t: ")" },
  ];
}

const F_SECTION: Record<PriceFactCode, { section: Section; source: Source }> = {
  F1_MA_BELOW: { section: "levels", source: "levels" },
  F1_MA_ABOVE: { section: "levels", source: "levels" },
  F2_BULL: { section: "tech", source: "tech" }, F2_BEAR: { section: "tech", source: "tech" },
  F3_HIGH_TODAY: { section: "tech", source: "tech" }, F3_LOW_TODAY: { section: "tech", source: "tech" },
  F4_NEW_HIGH: { section: "tech", source: "tech" }, F4_NEW_LOW: { section: "tech", source: "tech" },
  F5_UP: { section: "tech", source: "tech" }, F5_DOWN: { section: "tech", source: "tech" },
  F8_RSI_OK: { section: "tech", source: "tech" }, F8_RSI_LOW: { section: "tech", source: "tech" },
};

/**
 * 價格位置的多空事實(docs/46 §2.5、v2 §2.1–2.2)。lastCandleDate = 個股 K 棒最後一天;as_of 不同時每句帶日期、
 * 不宣告 mirrors(不取代技術理由)。rsi14 來自 technical(F8:50–70 多方、<50 空方、70–80 不列)。
 * F3(今日即 N 日高/低)與 F4(收盤創 20 日新高/低)同側成立時合併成一句。
 */
export function priceLevelFacts(
  pl: PriceLevels | null | undefined,
  lastCandleDate?: string | null,
  rsi14?: number | null,
): PriceLevelFact[] {
  if (!pl || pl.status !== "ok") return [];
  const date = lastCandleDate && pl.as_of !== lastCandleDate ? mmdd(pl.as_of) : undefined;
  const close = pl.close;
  const out: PriceLevelFact[] = [];
  const add = (code: PriceFactCode, side: "bull" | "bear", segs: Seg[], rank: number, extra: { mirrors?: string[]; dist?: number; level?: Seg[] } = {}) => {
    const f: PriceLevelFact = { code, side, ...F_SECTION[code], text: segs.map((s) => s.t).join(""), segments: segs, tf: "D", rank };
    if (extra.dist != null) f.dist = extra.dist;
    if (extra.level) f.level = extra.level;
    if (date) f.date = date;
    else if (extra.mirrors?.length) f.mirrors = extra.mirrors;
    out.push(f);
  };
  const ma = maSplit(pl.ma, MA_KEYS, close);
  if (ma.nearBelow) {
    const mirrors = [...(ma.below.includes("20") ? ["T1_MA20"] : []), ...(ma.below.includes("60") ? ["T1_MA60"] : [])];
    const d = Math.abs(pct(ma.nearBelow.v, close));
    // 下方最接近均線 ≤3% 與上方同級(支撐/壓力對稱)
    add("F1_MA_BELOW", "bull", maSideSegs("below", ma.below, ma.nearBelow, close, "日"), isNear(d) ? 4 : 2,
      { mirrors, dist: d, level: maLevelSegs(ma.nearBelow, close, "日") });
  }
  if (ma.nearAbove) {
    const d = Math.abs(pct(ma.nearAbove.v, close));
    add("F1_MA_ABOVE", "bear", maSideSegs("above", ma.above, ma.nearAbove, close, "日"), isNear(d) ? 4 : 2,
      { dist: d, level: maLevelSegs(ma.nearAbove, close, "日") });
  }
  if (pl.ma_align === "bull") add("F2_BULL", "bull", [{ t: "5/10/20日均線多頭排列" }], 3, { mirrors: ["T1_BULL_MA"] });
  if (pl.ma_align === "bear") add("F2_BEAR", "bear", [{ t: "5/10/20日均線空頭排列" }], 3);
  const hiN = extremes(pl.highs, pl.as_of).todayN;
  const loN = extremes(pl.lows, pl.as_of).todayN;
  const also = (n: string | null, word: string) => (n && n !== "20" ? `,今日${word}亦為 ${n} 日${word === "高點" ? "最高" : "最低"}` : "");
  if (pl.new_high_20) add("F4_NEW_HIGH", "bull", [{ t: `收盤創20日新高${also(hiN, "高點")}` }], 4, { mirrors: ["T2_20D_HIGH"] });
  else if (hiN) add("F3_HIGH_TODAY", "bull", [{ t: `今日即${hiN}日最高` }], 4);
  if (pl.new_low_20) add("F4_NEW_LOW", "bear", [{ t: `收盤創20日新低${also(loN, "低點")}` }], 4);
  else if (loN) add("F3_LOW_TODAY", "bear", [{ t: `今日即${loN}日最低` }], 4);
  if (pl.vol_price_2d === "up") add("F5_UP", "bull", [{ t: "連2日量增價漲" }], 3, { mirrors: ["T4_PRICE_VOLUME_UP"] });
  if (pl.vol_price_2d === "down") add("F5_DOWN", "bear", [{ t: "連2日量增價跌" }], 3);
  if (rsi14 != null) {
    const r = Math.round(rsi14);
    if (rsi14 >= 50 && rsi14 <= 70) add("F8_RSI_OK", "bull", [{ t: `RSI14 ${r},位於 50–70` }], 2, { mirrors: ["T5_RSI"] });
    else if (rsi14 < 50) add("F8_RSI_LOW", "bear", [{ t: `RSI14 ${r},低於 50` }], 2);
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
  const za = denseZone(pl, "above");
  const zb = denseZone(pl, "below");
  if (za) above.push(zoneRow(za, "above", close));
  if (zb) below.push(zoneRow(zb, "below", close));

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

/**
 * 「怎麼算」精簡說明(常駐顯示,不收合;docs/46 §6.8):壓力分析段底,4 短行只放關鍵定義。
 * 只列事實、不加減分數。
 */
export const HOWTO_LINES: readonly string[] = [
  "價位用還原價(除權息、分割已調整),可能和 K 線原始價不同。",
  "均線 5–240 日;N 日高低含今日;缺口=近 120 根未回補、寬 ≥0.5%;距現價 3% 內標「接近」。",
  "現價上/下成交:近 120 根 K 棒的量攤在當日高低之間;密集區以現價 1% 為一格。",
  "週K、月K由還原日K合併,最後一根是進行中的本週/本月。",
];

/** 融資×分點集中度事實的定義句(docs/46 §7):只並列、不歸因。 */
export const MARGIN_FLOW_DEFINITION =
  "融資增量只有全市場餘額,無分點或帳戶層級;此處只列同一期間的分點囤貨與集保變化,是否相關由讀者判斷。";

/** 籌碼分析段底的精簡門檻說明(常駐顯示;原「怎麼算」裡的籌碼條目)。 */
export const CHIPS_HOWTO_LINES: readonly string[] = [
  "法人:外資達當日量 1% 或 1,000 張、投信 1% 或 500 張才列;自營商不列。",
  "分點:每天只存淨額前 12 大,合計與天數是下限。大戶:集保 400 張以上週變化 ≥0.3 個百分點。",
  MARGIN_FLOW_DEFINITION,
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
  const dza = denseZone(pl, "above");
  const dzb = denseZone(pl, "below");
  const za = dza ? [{ price: (dza.lo + dza.hi) / 2, adj: dza.lo, label: "密集區", side: "above" as const }] : [];
  const zb = dzb ? [{ price: (dzb.lo + dzb.hi) / 2, adj: dzb.hi, label: "密集區", side: "below" as const }] : [];
  const near = (xs: { price: number; adj: number; label: string; side: "above" | "below" }[]) =>
    xs.sort((a, b) => Math.abs(a.adj - close) - Math.abs(b.adj - close) || a.label.localeCompare(b.label)).slice(0, perSide);
  return [...near([...hi, ...za]), ...near([...lo, ...zb])].map(({ price, label, side }) => ({ price, label, side }));
}
