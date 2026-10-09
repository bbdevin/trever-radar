/**
 * 首頁「市場概況」(docs/49 §11,2026-10-09)的句子與格式。純函式,node --test 直接跑。
 *
 * 取代原本三張「資料日／上櫃成交／上市成交」卡:同一張卡裡放 加權指數、櫃買指數、
 * 全市場成交額＋漲跌家數、三大法人全市場淨額(估)。只整理交易所公布的數字,不下判斷。
 * 舊 payload 沒有 `indices` / `insti_market` 時,對應的格不畫,其餘照常。
 */
import type { InstiMarket, MarketIndex, RadarJson } from "./types.ts";
import { fmtAmt } from "./instiGroupFlow.ts";

export const BRIEF_TITLE = "市場概況";
export const BRIEF_STALE_BADGE = "部分待更新";
export const BRIEF_TURNOVER_LABEL = "成交額";
export const BRIEF_INSTI_LABEL = "三大法人(估)";
export const BRIEF_INSTI_HINT = "外資、投信、自營商全市場買賣超,金額＝張數×當日收盤(估),不含 ETF";
export const BRIEF_UPDOWN_HINT = "上市＋上櫃普通股今日收盤高於／低於前一日的家數";

/** "2026-10-07" → "10/07" */
export function mmdd(d: string | null | undefined): string {
  if (!d) return "—";
  const m = /^\d{4}-(\d{2})-(\d{2})$/.exec(d);
  return m ? `${m[1]}/${m[2]}` : d;
}

/** 指數收盤:千分位、兩位小數(來源就是兩位) */
export function fmtIndex(close: number): string {
  return close.toLocaleString("zh-TW", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** 「▼492.93 · -0.99%」;顏色不是唯一訊號,箭頭與正負號都在字裡。缺值 → "—" */
export function indexChangeText(change: number | null, chgPct: number | null): string {
  if (change == null && chgPct == null) return "—";
  const ref = change ?? chgPct ?? 0;
  const arrow = ref > 0 ? "▲" : ref < 0 ? "▼" : "";
  const parts: string[] = [];
  if (change != null) parts.push(`${arrow}${Math.abs(change).toLocaleString("zh-TW", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
  if (chgPct != null) parts.push(`${chgPct > 0 ? "+" : chgPct < 0 ? "-" : ""}${Math.abs(chgPct).toFixed(2)}%`);
  return parts.join(" · ");
}

/** 該格的資料日與頁面資料日不同時,回 "10/06" 標在旁邊;相同 → null */
export function dateTag(date: string | null | undefined, dataDate: string): string | null {
  return date && date !== dataDate ? mmdd(date) : null;
}

export interface TurnoverCell {
  total: number;
  up: number;
  down: number;
  /** 各市場一行:「上市 314.0億 · 上櫃 158.0億」 */
  byMarket: { market: string; turnover: number }[];
}

export function turnoverCell(summary: RadarJson["summary"] | undefined): TurnoverCell | null {
  if (!summary?.length) return null;
  return {
    total: summary.reduce((s, m) => s + (m.turnover || 0), 0),
    up: summary.reduce((s, m) => s + (m.up || 0), 0),
    down: summary.reduce((s, m) => s + (m.down || 0), 0),
    // 固定 上市 → 上櫃(summary 來自 GROUP BY market,字母序會把 tpex 排前面)
    byMarket: [...summary]
      .sort((a, b) => (MARKET_ORDER[a.market] ?? 9) - (MARKET_ORDER[b.market] ?? 9))
      .map((m) => ({ market: m.market, turnover: m.turnover })),
  };
}

const MARKET_ORDER: Record<string, number> = { twse: 0, tpex: 1 };

/** 億,一位小數、千分位;不帶正負號(成交額沒有方向) */
export function fmtE8(n: number): string {
  return `${(n / 1e8).toLocaleString("zh-TW", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}億`;
}

export const INSTI_BRIEF_IDENTS = ["foreign", "trust", "dealer"] as const;
export const INSTI_BRIEF_LABEL: Record<(typeof INSTI_BRIEF_IDENTS)[number], string> = {
  foreign: "外資",
  trust: "投信",
  dealer: "自營",
};

/** 三格:[{label:"外資", text:"+99.4億", value}] */
export function instiBriefItems(m: InstiMarket | undefined): { key: string; label: string; text: string; value: number }[] {
  if (!m) return [];
  return INSTI_BRIEF_IDENTS.map((k) => ({
    key: k,
    label: INSTI_BRIEF_LABEL[k],
    text: fmtAmt(m[k].amt_est),
    value: m[k].amt_est,
  }));
}

/** 卡片第一列固定三格(A 版):沒有該序列資料時顯示中性「—」格 */
export const TILE_SLOTS: { market: string; label: string }[] = [
  { market: "twse", label: "加權" },
  { market: "tpex", label: "櫃買" },
  { market: "tx", label: "台指期 近月" },
];

/** 指數格固定順序 twse → tpex → tx;payload 順序本來就是,這裡只是防呆 */
export function orderedIndices(indices: MarketIndex[] | undefined): MarketIndex[] {
  const order: Record<string, number> = { twse: 0, tpex: 1, tx: 2 };
  return [...(indices ?? [])].sort((a, b) => (order[a.market] ?? 9) - (order[b.market] ?? 9));
}

// ── 走勢(docs/49 §12):迷你走勢圖 + 點開的走勢圖 bottom sheet ──

export const INDEX_HIST_URL = "/data/market/indices_hist.json";
export const TREND_AFFORDANCE = "走勢";
export const TREND_SHEET_TITLE = "大盤走勢";
export const TREND_EMPTY = "尚無走勢資料(指數回補後出現)";
export const TREND_HINT = "點圖上任一點看那天的收盤與漲跌;只整理交易所公布的收盤,不下判斷。";

/** 台指期副標:「近月 2026/10 · 結算 49,240」(沒有月份 → null) */
export function txSubtitle(ix: Pick<MarketIndex, "contract_month" | "settlement">): string | null {
  const m = ix.contract_month;
  if (!m || !/^\d{6}$/.test(m)) return null;
  const parts = [`近月 ${m.slice(0, 4)}/${m.slice(4)}`];
  if (ix.settlement != null) parts.push(`結算 ${fmtIndex(ix.settlement)}`);
  return parts.join(" · ");
}

/**
 * 迷你走勢圖的 SVG path(polyline):values 舊→新,畫在 w×h 內、上下留 1px。
 * 少於 2 點 → null(不畫)。所有點同值 → 水平線在中間。
 */
export function sparkPath(values: number[] | undefined, w: number, h: number): string | null {
  if (!values || values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min;
  const pad = 1;
  const stepX = w / (values.length - 1);
  return values
    .map((v, i) => {
      const x = i * stepX;
      const y = span === 0 ? h / 2 : pad + (1 - (v - min) / span) * (h - pad * 2);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
}

/** 迷你走勢的顏色依「最後一個收盤 vs 第一個」:紅漲綠跌,持平用中性 */
export function sparkTone(values: number[] | undefined): "up" | "down" | "flat" {
  if (!values || values.length < 2) return "flat";
  const d = values[values.length - 1] - values[0];
  return d > 0 ? "up" : d < 0 ? "down" : "flat";
}

export type TrendRange = "1m" | "3m" | "6m" | "1y";
/** 以交易日數切範圍(來源每個序列最多 260 列,1 年取 250) */
export const TREND_RANGES: { key: TrendRange; label: string; days: number }[] = [
  { key: "1m", label: "1月", days: 21 },
  { key: "3m", label: "3月", days: 63 },
  { key: "6m", label: "6月", days: 126 },
  { key: "1y", label: "1年", days: 250 },
];
export const TREND_RANGE_DEFAULT: TrendRange = "3m";

export type TrendPoint = [string, number, number | null, number | null];

export function sliceRange(points: TrendPoint[] | undefined, key: TrendRange): TrendPoint[] {
  const days = TREND_RANGES.find((r) => r.key === key)?.days ?? 63;
  const src = points ?? [];
  return src.slice(Math.max(0, src.length - days));
}

/** 區間統計:高、低、區間漲跌(點與 %,首尾收盤相比);少於 1 點 → null */
export function rangeStats(points: TrendPoint[]): { high: number; low: number; change: number; chgPct: number | null; from: string; to: string } | null {
  if (!points.length) return null;
  let high = -Infinity;
  let low = Infinity;
  for (const p of points) {
    if (p[1] > high) high = p[1];
    if (p[1] < low) low = p[1];
  }
  const first = points[0][1];
  const last = points[points.length - 1][1];
  const change = Math.round((last - first) * 100) / 100;
  return {
    high, low, change,
    chgPct: first ? Math.round((change / first) * 10000) / 100 : null,
    from: points[0][0], to: points[points.length - 1][0],
  };
}

/** 走勢線顏色:區間首尾相比紅漲綠跌(與迷你圖同一規則) */
export function rangeTone(points: TrendPoint[]): "up" | "down" | "flat" {
  if (points.length < 2) return "flat";
  const d = points[points.length - 1][1] - points[0][1];
  return d > 0 ? "up" : d < 0 ? "down" : "flat";
}
