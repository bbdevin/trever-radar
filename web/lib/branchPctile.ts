// 個股頁「買點偏低、賣點偏高的分點」面板的純邏輯(BranchPctilePanel 用)。
//
// 放在這裡而不是元件裡,是為了用 node --test 驗:payload 正規化(v1/v2、張數缺值)、
// 每一列的文字、紀錄不足的判斷、搜尋,以及預設只展開前幾個。
//
// 原則(沿用面板一貫的立場):
//   * 這裡全部是進出場時點的價格分位計次與張數,不是損益,不輸出任何分數。
//   * 分母不足就明講「紀錄不足」,絕不把 1/2 畫成 50%,也不把缺值畫成 0%。
//   * 定義的數字(20/120 日、40%/60%)一律從 payload 讀;只有 v1 payload 沒帶,
//     才用 v1 當時固定的定義(V1_DEFINITION)。
import type {
  BranchPctileCamp,
  BranchPctileCounts,
  BranchPctileCountsV1,
  BranchPctileRow,
} from "@/lib/types";

export type CampKey = "short" | "long";
export const CAMP_KEYS: CampKey[] = ["short", "long"];
export const CAMP_NAMES: Record<CampKey, string> = { short: "短線派", long: "長線派" };

/** 預設展開的分點數。 */
export const DEFAULT_VISIBLE = 5;
/** 搜尋結果最多顯示幾張卡。 */
export const SEARCH_LIMIT = 20;

/** v1 payload 沒有帶定義數字;v1 的定義是固定的 20 日、≤40%/≥60%。 */
const V1_DEFINITION = { shortWindow: 20, lowMax: 0.4, highMin: 0.6, minKnown: 5 };

export interface SideNumbers {
  /** 分位可知的 episode 次數(分母)。 */
  known: number;
  /** 其中落在低檔(買)/高檔(賣)的次數。 */
  hit: number;
  /** 同一分類的張數;舊資料為 null。 */
  lotsKnown: number | null;
  lotsHit: number | null;
}

export interface CampStat {
  name: string;
  buy: SideNumbers;
  sell: SideNumbers;
  buyUnknown: number | null;
  sellUnknown: number | null;
  daytrade: { obs: number; paybacks: number } | null;
}

export interface CampModel {
  key: CampKey;
  available: boolean;
  windowDays: number | null;
  /** 已排序的清單(第 1 位在前)。 */
  rows: CampStat[];
  base: { buy: SideNumbers | null; sell: SideNumbers | null };
  shrinkK: { buy: number | null; sell: number | null };
}

export interface PctileModel {
  version: 1 | 2;
  /** true = 張數加權＋收縮排序;false = 次數排序(v1 或舊快照)。 */
  lotsRanked: boolean;
  minKnown: number;
  maxBranches: number | null;
  lowMax: number;
  highMin: number;
  minDaytradeObs: number | null;
  stockDaytrade: { obs: number; paybacks: number } | null;
  windowFrom: string | null;
  asOf: string | null;
  marketDays: number | null;
  /** v1 沒有長線派:camps.long 為 null。 */
  camps: { short: CampModel; long: CampModel | null };
  /** 不在清單裡的分點,兩派的數字(名稱 → 派 → 數字)。 */
  lookup: Map<string, Partial<Record<CampKey, CampStat>>>;
}

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function countOrNull(value: unknown): number | null {
  return isCount(value) ? value : null;
}

function side(known: unknown, hit: unknown, lotsKnown: unknown, lotsHit: unknown): SideNumbers | null {
  if (!isCount(known) || !isCount(hit) || hit > known) return null;
  let lk = countOrNull(lotsKnown);
  let lh = countOrNull(lotsHit);
  if (lk == null || lh == null || lh > lk) {
    lk = null;
    lh = null;
  }
  return { known, hit, lotsKnown: lk, lotsHit: lh };
}

function rowToStat(row: unknown): CampStat | null {
  if (!row || typeof row !== "object") return null;
  const r = row as Record<string, unknown>;
  if (typeof r.branch_name !== "string" || r.branch_name.length === 0) return null;
  const buy = side(r.buy_pctile_known, r.low_buy_count, r.buy_lots_known, r.low_buy_lots);
  const sell = side(r.sell_pctile_known, r.high_sell_count, r.sell_lots_known, r.high_sell_lots);
  if (!buy || !sell) return null;
  const obs = r.daytrade_obs;
  const paybacks = r.daytrade_paybacks;
  return {
    name: r.branch_name,
    buy,
    sell,
    buyUnknown: countOrNull(r.buy_pctile_unknown),
    sellUnknown: countOrNull(r.sell_pctile_unknown),
    daytrade: isCount(obs) && isCount(paybacks) && paybacks <= obs ? { obs, paybacks } : null,
  };
}

function stockBase(source: Record<string, unknown>) {
  return {
    buy: side(source.stock_buy_pctile_known, source.stock_low_buy_count,
      source.stock_buy_lots_known, source.stock_low_buy_lots),
    sell: side(source.stock_sell_pctile_known, source.stock_high_sell_count,
      source.stock_sell_lots_known, source.stock_high_sell_lots),
  };
}

function campFrom(key: CampKey, camp: unknown, windowDays: number | null): CampModel {
  const c = (camp && typeof camp === "object" ? camp : {}) as Partial<BranchPctileCamp>;
  const rows = Array.isArray(c.branches)
    ? c.branches.map(rowToStat).filter((s): s is CampStat => s !== null)
    : [];
  return {
    key,
    available: c.available === true,
    windowDays,
    rows,
    base: stockBase(c as Record<string, unknown>),
    shrinkK: {
      buy: typeof c.shrink_k_buy_lots === "number" ? c.shrink_k_buy_lots : null,
      sell: typeof c.shrink_k_sell_lots === "number" ? c.shrink_k_sell_lots : null,
    },
  };
}

function lookupFrom(fields: unknown, entries: unknown): PctileModel["lookup"] {
  const out: PctileModel["lookup"] = new Map();
  if (!Array.isArray(fields) || !Array.isArray(entries)) return out;
  const at = new Map<string, number>();
  fields.forEach((field, index) => {
    if (typeof field === "string") at.set(field, index);
  });
  const nameAt = at.get("branch_name");
  if (nameAt == null) return out;
  for (const entry of entries) {
    if (!Array.isArray(entry)) continue;
    const name = entry[nameAt];
    if (typeof name !== "string" || !name) continue;
    const camps: Partial<Record<CampKey, CampStat>> = {};
    for (const key of CAMP_KEYS) {
      const get = (field: string) => {
        const index = at.get(`${key}.${field}`);
        return index == null ? undefined : entry[index];
      };
      const stat = rowToStat({
        branch_name: name,
        buy_pctile_known: get("buy_pctile_known"),
        low_buy_count: get("low_buy_count"),
        sell_pctile_known: get("sell_pctile_known"),
        high_sell_count: get("high_sell_count"),
        buy_lots_known: get("buy_lots_known"),
        low_buy_lots: get("low_buy_lots"),
        sell_lots_known: get("sell_lots_known"),
        high_sell_lots: get("high_sell_lots"),
      });
      if (stat) camps[key] = stat;
    }
    out.set(name, camps);
  }
  return out;
}

/**
 * payload → 畫面用的模型。v1(舊 JSON)照樣可讀,只是沒有張數、沒有長線派;
 * 其他版本或缺鍵回 null,整節不渲染。
 */
export function normalizeBranchPctile(data: BranchPctileCounts | unknown): PctileModel | null {
  if (!data || typeof data !== "object") return null;
  const d = data as Record<string, unknown>;
  const common = {
    minDaytradeObs: countOrNull(d.min_daytrade_obs),
    stockDaytrade: isCount(d.stock_daytrade_obs) && isCount(d.stock_daytrade_paybacks)
      ? { obs: d.stock_daytrade_obs, paybacks: d.stock_daytrade_paybacks }
      : null,
    windowFrom: typeof d.window_from === "string" ? d.window_from : null,
    asOf: typeof d.as_of === "string" ? d.as_of : null,
    marketDays: countOrNull(d.window_market_days),
  };

  if (d.version === 1) {
    const v1 = data as BranchPctileCountsV1;
    if (!Array.isArray(v1.branches)) return null;
    const short: CampModel = {
      key: "short",
      available: true,
      windowDays: V1_DEFINITION.shortWindow,
      rows: v1.branches.map(rowToStat).filter((s): s is CampStat => s !== null),
      base: stockBase(d),
      shrinkK: { buy: null, sell: null },
    };
    return {
      version: 1,
      lotsRanked: false,
      minKnown: countOrNull(d.min_known_episodes_per_side) ?? V1_DEFINITION.minKnown,
      maxBranches: countOrNull(d.max_branches),
      lowMax: V1_DEFINITION.lowMax,
      highMin: V1_DEFINITION.highMin,
      ...common,
      camps: { short, long: null },
      lookup: new Map(),
    };
  }

  if (d.version === 2) {
    const windows = (d.windows && typeof d.windows === "object" ? d.windows : {}) as Record<string, unknown>;
    if (!d.short || typeof d.short !== "object") return null;
    return {
      version: 2,
      lotsRanked: typeof d.ranking === "string" && d.ranking.startsWith("lots_shrunk"),
      minKnown: countOrNull(d.min_known_episodes_per_side) ?? V1_DEFINITION.minKnown,
      maxBranches: countOrNull(d.max_branches),
      lowMax: typeof d.low_buy_max_pctile === "number" ? d.low_buy_max_pctile : V1_DEFINITION.lowMax,
      highMin: typeof d.high_sell_min_pctile === "number" ? d.high_sell_min_pctile : V1_DEFINITION.highMin,
      ...common,
      camps: {
        short: campFrom("short", d.short, countOrNull(windows.short)),
        long: campFrom("long", d.long, countOrNull(windows.long)),
      },
      lookup: lookupFrom(d.lookup_fields, d.lookup),
    };
  }
  return null;
}

export function fmtInt(value: number): string {
  return Math.round(value).toLocaleString("en-US");
}

function pct(hit: number, known: number): number | null {
  return known > 0 ? (hit / known) * 100 : null;
}

export function fmtPct(value: number | null): string {
  return value == null ? "—" : `${Math.round(value)}%`;
}

export interface SideView {
  /** 已知分位次數不足門檻:不畫比率,只講「紀錄不足」。 */
  insufficient: boolean;
  /** 主要那一行,例如「買在低檔 1,318 / 2,350 張 · 56%」。 */
  label: string;
  /** 次要的小字,例如「次數 7/11」。 */
  detail: string;
  /** 長條長度(0–100);null 不畫。 */
  pct: number | null;
  /** 此股全體分點同一項的比率(刻線位置);null 不畫。 */
  basePct: number | null;
}

/**
 * 一側(買或賣)的文字與長條。有張數就以張數比率為主、次數為輔;沒有張數(舊資料)
 * 才退回次數比率。刻線永遠用同一種單位的該股比率——張數對張數、次數對次數。
 */
export function sideView(
  kind: "buy" | "sell",
  stat: SideNumbers,
  base: SideNumbers | null,
  minKnown: number,
): SideView {
  const word = kind === "buy" ? "買在低檔" : "賣在高檔";
  if (stat.known < minKnown) {
    return {
      insufficient: true,
      label: kind === "buy" ? "買進紀錄不足" : "賣出紀錄不足",
      detail: `分位可知 ${stat.known} 次，未達 ${minKnown} 次`,
      pct: null,
      basePct: null,
    };
  }
  const counts = `次數 ${stat.hit}/${stat.known}`;
  if (stat.lotsKnown != null && stat.lotsHit != null) {
    const share = pct(stat.lotsHit, stat.lotsKnown);
    const baseShare = base && base.lotsKnown != null && base.lotsHit != null
      ? pct(base.lotsHit, base.lotsKnown)
      : null;
    return {
      insufficient: false,
      label: `${word} ${fmtInt(stat.lotsHit)} / ${fmtInt(stat.lotsKnown)} 張 · ${fmtPct(share)}`,
      detail: counts,
      pct: share,
      basePct: baseShare,
    };
  }
  const share = pct(stat.hit, stat.known);
  return {
    insufficient: false,
    label: `${word} ${stat.hit} / ${stat.known} 次 · ${fmtPct(share)}`,
    detail: "",
    pct: share,
    basePct: base ? pct(base.hit, base.known) : null,
  };
}

export interface CompactSide {
  /** 「買低 56%」「賣高 64%」;紀錄不足時為「買進不足」「賣出不足」。 */
  text: string;
  insufficient: boolean;
}

/**
 * 精簡列(一行一個分點)用的單側標籤。比率規則與 sideView 相同:有張數用張數比率,
 * 舊資料退回次數比率;已知次數未達門檻就講「不足」,絕不印成 0%。
 */
export function compactSide(kind: "buy" | "sell", stat: SideNumbers, minKnown: number): CompactSide {
  if (stat.known < minKnown) {
    return { text: kind === "buy" ? "買進不足" : "賣出不足", insufficient: true };
  }
  const share = stat.lotsKnown != null && stat.lotsHit != null
    ? pct(stat.lotsHit, stat.lotsKnown)
    : pct(stat.hit, stat.known);
  return { text: `${kind === "buy" ? "買低" : "賣高"} ${fmtPct(share)}`, insufficient: false };
}

/** 一行版定義(「買低」「賣高」兩個詞的意思);數字全部來自 payload。 */
export function campShortDefinition(model: PctileModel, key: CampKey): string {
  const days = model.camps[key]?.windowDays;
  const low = Math.round(model.lowMax * 100);
  const high = Math.round(model.highMin * 100);
  // 與 compactSide 同一個判斷:清單上有張數就是張數佔比,舊快照才是次數佔比。
  const lots = model.camps[key]?.rows.some((row) => row.buy.lotsKnown != null) ?? false;
  const unit = lots ? "張數佔比" : "次數佔比";
  return `買低＝買進日收盤在${days ? `近 ${days} 日` : ""}區間 ≤${low}%，賣高＝賣出日 ≥${high}%（${unit}）`;
}

/** 刻線圖例:此股全體分點兩側的比率(與長條同一種單位)。 */
export function baseLegend(camp: CampModel): string | null {
  const parts: string[] = [];
  for (const kind of ["buy", "sell"] as const) {
    const base = camp.base[kind];
    if (!base) continue;
    const share = base.lotsKnown != null && base.lotsHit != null
      ? pct(base.lotsHit, base.lotsKnown)
      : pct(base.hit, base.known);
    if (share == null) continue;
    parts.push(`${kind === "buy" ? "買在低檔" : "賣在高檔"} ${fmtPct(share)}`);
  }
  return parts.length ? `刻線＝此股全體分點：${parts.join("、")}` : null;
}

export function visibleRows<T>(rows: T[], expanded: boolean, top = DEFAULT_VISIBLE): T[] {
  return expanded ? rows : rows.slice(0, top);
}

/** 「≈ 1 個月」「≈ 半年」:20 個交易日約一個月。 */
export function approxSpan(days: number): string {
  const months = Math.max(1, Math.round(days / 20));
  if (months === 6) return "≈ 半年";
  if (months === 12) return "≈ 1 年";
  return `≈ ${months} 個月`;
}

/** 「近 20 個交易日 ≈ 1 個月」;沒有窗口數字時為空字串。 */
export function campWindowLabel(model: PctileModel, key: CampKey): string {
  const days = model.camps[key]?.windowDays;
  return days ? `近 ${days} 個交易日 ${approxSpan(days)}` : "";
}

export function campTabLabel(model: PctileModel, key: CampKey): string {
  const window = campWindowLabel(model, key);
  return window ? `${CAMP_NAMES[key]}（${window}）` : CAMP_NAMES[key];
}

/** 頁籤下方那一行定義;數字全部來自 payload。 */
export function campDefinition(model: PctileModel, key: CampKey): string {
  const days = model.camps[key]?.windowDays;
  const low = Math.round(model.lowMax * 100);
  const high = Math.round(model.highMin * 100);
  const range = days ? `近 ${days} 個交易日的收盤區間` : "收盤區間";
  return `以${range}為尺：買進日收盤落在 ≤${low}% 位置記為買在低檔，`
    + `賣出日收盤落在 ≥${high}% 位置記為賣在高檔。`;
}

export interface CampHit {
  stat: CampStat | null;
  /** 在該派清單裡的位置(1 起算);不在清單裡為 null。 */
  rank: number | null;
}

export interface SearchHit {
  name: string;
  camps: Record<CampKey, CampHit | null>;
}

/**
 * 依分點名稱子字串搜尋(不分大小寫)。清單內與 lookup 一起找,所以沒進排序的
 * 分點也查得到。每個結果帶兩派的數字與位置;清單內的排前面。
 */
export function searchBranches(
  model: PctileModel,
  query: string,
  limit = SEARCH_LIMIT,
): { total: number; results: SearchHit[] } {
  const q = query.trim().toLowerCase();
  if (!q) return { total: 0, results: [] };
  const names = new Set<string>();
  for (const key of CAMP_KEYS) {
    for (const row of model.camps[key]?.rows ?? []) names.add(row.name);
  }
  for (const name of model.lookup.keys()) names.add(name);

  const hits: SearchHit[] = [];
  for (const name of names) {
    if (!name.toLowerCase().includes(q)) continue;
    const camps = {} as Record<CampKey, CampHit | null>;
    for (const key of CAMP_KEYS) {
      const camp = model.camps[key];
      if (!camp) {
        camps[key] = null;
        continue;
      }
      const index = camp.rows.findIndex((row) => row.name === name);
      camps[key] = index >= 0
        ? { stat: camp.rows[index], rank: index + 1 }
        : { stat: model.lookup.get(name)?.[key] ?? null, rank: null };
    }
    hits.push({ name, camps });
  }
  const bestRank = (hit: SearchHit) => Math.min(
    ...CAMP_KEYS.map((key) => hit.camps[key]?.rank ?? Number.POSITIVE_INFINITY),
  );
  hits.sort((a, b) => bestRank(a) - bestRank(b) || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  return { total: hits.length, results: hits.slice(0, limit) };
}

/** 搜尋結果裡某一派的狀態:在清單第幾位,或誠實的未入選理由。 */
export function campStatus(model: PctileModel, key: CampKey, hit: CampHit | null): string {
  const name = CAMP_NAMES[key];
  const camp = model.camps[key];
  if (!camp || !hit) return `${name}：無資料`;
  if (!camp.available) return `${name}：這份資料尚未計算`;
  if (hit.rank != null) return `${name}：排序第 ${hit.rank} 位`;
  const stat = hit.stat;
  // 沒有 stat = 資料裡沒收這一派的數字(lookup 有上限),不等於「沒有紀錄」。
  if (!stat) return `${name}：紀錄太少，未收錄這一派的數字`;
  if (stat.buy.known + stat.sell.known === 0) return `${name}：窗口內沒有分位可知的紀錄`;
  if (stat.buy.known < model.minKnown) {
    return `${name}：未進排行，買進紀錄 ${stat.buy.known} 次，未達 ${model.minKnown} 次`;
  }
  if (!model.lotsRanked && stat.sell.known < model.minKnown) {
    return `${name}：未進排行，賣出紀錄 ${stat.sell.known} 次，未達 ${model.minKnown} 次（舊版排序兩側都要求）`;
  }
  return model.maxBranches
    ? `${name}：未進排行，排在前 ${model.maxBranches} 位之後`
    : `${name}：未進排行`;
}

/** 次日回吐(只屬於短線派)的一行摘要;缺鍵回 null,不畫。 */
export function daytradeSummary(model: PctileModel, stat: CampStat): string | null {
  const dt = stat.daytrade;
  const minObs = model.minDaytradeObs;
  if (!dt || minObs == null) return null;
  if (dt.obs < minObs) {
    return `窗口內只有 ${dt.obs} 次可觀察的合格買超，未達 ${minObs} 次，無法判定；這是次數不足，不是「沒有回吐」。`;
  }
  const own = fmtPct(pct(dt.paybacks, dt.obs));
  const stock = model.stockDaytrade;
  const stockPart = stock && stock.obs > 0
    ? `；此股全體分點 ${stock.paybacks} / ${stock.obs} 次（${fmtPct(pct(stock.paybacks, stock.obs))}）`
    : "";
  return `${dt.paybacks} / ${dt.obs} 次合格買超在次日回吐（${own}）${stockPart}。`;
}
