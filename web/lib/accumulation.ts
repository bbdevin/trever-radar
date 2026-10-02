// 個股頁「囤貨／出貨分點」的純邏輯。UI 只讀這裡的常數產生定義文字,避免文案與判準漂移。
//
// 資料限制:branch_history 每天只留淨買賣前 12 大分點(見 json_export),某天不在前 12
// 的分點當天記為 0——所以天數與張數都是下限。

export type BranchDay = { t: string; branches: { n: string; b: number; s: number; net: number }[] };
export type VolumeDay = { t: string; v: number };

/** 視窗:交易日數(以該股 K 線日曆為準) */
export const WINDOWS = [
  { key: "1w", label: "1週", days: 5 },
  { key: "1m", label: "1月", days: 20 },
  { key: "3m", label: "3月", days: 60 },
] as const;
export type WindowKey = (typeof WINDOWS)[number]["key"];
export const DEFAULT_WINDOW: WindowKey = "1m";

/** 期間內最少買超(或賣超)天數 */
export const MIN_DAYS: Record<number, number> = { 5: 3, 20: 5, 60: 10 };
/**
 * 留倉率門檻(以張數,不以天數):囤貨 = 期間淨買 ÷ 期間買超日淨買合計 ≥ 此值,
 * 也就是賣回的張數不到買進的四成。2026-10-02 使用者指出:舊版「買超天數 ≥ 賣超天數 2 倍」
 * 把一天賣 3 張與一天買 800 張看成一樣重,散戶在同一分點小賣幾天就會讓主力被判出局。
 * 出貨鏡像:期間淨賣 ÷ 賣超日淨賣合計 ≥ 此值(賣出後買回不到四成)。
 */
export const RETAIN_MIN = 0.6;
/**
 * 規模門檻:|期間淨額| 至少 MIN_LOTS 張,且至少佔期間總成交量的 MIN_SHARE(成交量為 0 時略過此項)。
 * 單一分點一天的大單常是鉅額交易或轉倉,不該被當成囤貨。買賣天數比只是資訊,不是門檻。
 */
export const MIN_LOTS = 50;
export const MIN_SHARE = 0.005;
/** 「近期」= 最後幾個交易日 */
export const RECENT_DAYS = 5;
/** 近期反向淨額不得超過期間淨額的此比例 */
export const RECENT_REVERSAL = 0.3;
/** 預設顯示列數與展開上限 */
export const DEFAULT_VISIBLE = 5;
export const MAX_ROWS = 20;
/** 每日分點資料只含前幾大(文案用) */
export const TOP_N_PER_DAY = 12;

export type Side = "acc" | "dist";

export interface AccRow {
  name: string;
  /** 期間累計淨張數(囤貨為正、出貨為負) */
  net: number;
  buyDays: number;
  sellDays: number;
  /** 期間買超日淨買合計(張)、賣超日淨賣合計(張,正數) */
  buyLots: number;
  sellLots: number;
  /** 囤貨:net ÷ buyLots;出貨:|net| ÷ sellLots(百分比,0–100) */
  retainPct: number;
  /** |net| / 期間總成交量,百分比;成交量為 0 時 null */
  volumeSharePct: number | null;
  /** 囤貨:最後一次買超日;出貨:最後一次賣超日 */
  lastDate: string;
  /** 最近 RECENT_DAYS 日淨張數 */
  recentNet: number;
}

export type WindowResult =
  | { available: false; days: number; covered: number; message: string }
  | {
      available: true;
      days: number;
      start: string;
      end: string;
      acc: AccRow[];
      dist: AccRow[];
      accTotal: number;
      distTotal: number;
      /** 未截斷前的名單數(標頭計數用) */
      accCount: number;
      distCount: number;
    };

/** 該視窗的一行定義(UI 直接顯示) */
export function definitionText(days: number, side: Side): string {
  const min = MIN_DAYS[days];
  const pct = Math.round(RECENT_REVERSAL * 10);
  const retain = Math.round(RETAIN_MIN * 100);
  const back = ZH_DIGIT[Math.round((1 - RETAIN_MIN) * 10)];
  const share = String(Number((MIN_SHARE * 100).toFixed(2)));
  if (side === "acc") {
    return `囤貨＝期間淨買 ≥${MIN_LOTS} 張且 ≥ 期間成交量 ${share}%、買超 ≥${min} 天、留倉率 ≥${retain}%（賣回不到買進的${back}成）、近 ${RECENT_DAYS} 日沒有倒貨（淨賣 ≤ 期間淨買 ${pct} 成）`;
  }
  return `出貨＝期間淨賣 ≥${MIN_LOTS} 張且 ≥ 期間成交量 ${share}%、賣超 ≥${min} 天、出清率 ≥${retain}%（買回不到賣出的${back}成）、近 ${RECENT_DAYS} 日沒有回補（淨買 ≤ 期間淨賣 ${pct} 成）`;
}

const ZH_DIGIT: Record<number, string> = { 1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九" };

type Acc = {
  net: number; buyDays: number; sellDays: number; buyLots: number; sellLots: number;
  recentNet: number; lastBuy: string; lastSell: string;
};

function bigEnough(absNet: number, totalVolume: number): boolean {
  return absNet >= MIN_LOTS && (totalVolume <= 0 || absNet >= MIN_SHARE * totalVolume);
}

function qualifies(side: Side, a: Acc, min: number, totalVolume: number): boolean {
  if (side === "acc") {
    return a.net > 0 && bigEnough(a.net, totalVolume) && a.buyDays >= min && a.net >= RETAIN_MIN * a.buyLots
      && a.recentNet >= -RECENT_REVERSAL * a.net;
  }
  return a.net < 0 && bigEnough(-a.net, totalVolume) && a.sellDays >= min && -a.net >= RETAIN_MIN * a.sellLots
    && a.recentNet <= RECENT_REVERSAL * -a.net;
}

/**
 * 計算單一視窗。視窗 = K 線日曆中,截至分點資料最新日(含)的最後 `days` 個交易日;
 * 分點資料可能比報價晚一天,以分點最新日為終點才不會把「還沒有資料」當成 0。
 * 視窗內任一交易日沒有分點資料(回補深度不足或缺日)→ 整個視窗不可用,不拿殘缺資料硬算。
 */
export function computeWindow(
  branchHistory: BranchDay[] | undefined,
  candles: VolumeDay[],
  days: number,
): WindowResult {
  const min = MIN_DAYS[days] ?? Math.ceil(days / 2);
  const byDate = new Map<string, BranchDay>();
  for (const d of branchHistory ?? []) byDate.set(d.t, d);
  const newest = (branchHistory ?? []).reduce<string | null>((m, d) => (m == null || d.t > m ? d.t : m), null);

  const calendar = newest == null ? [] : candles.filter((c) => c.t <= newest);
  const windowCandles = calendar.slice(-days);
  const covered = windowCandles.filter((c) => byDate.has(c.t)).length;
  if (windowCandles.length < days || covered < days) {
    return {
      available: false,
      days,
      covered,
      message: `分點資料只涵蓋 ${covered} 天，不足 ${days} 天`,
    };
  }

  const dates = windowCandles.map((c) => c.t); // 舊→新
  const recentFrom = dates[Math.max(0, dates.length - RECENT_DAYS)];
  const totalVolume = windowCandles.reduce((s, c) => s + (c.v || 0), 0);

  const map = new Map<string, Acc>();
  for (const t of dates) {
    // 同名分點同一天可能有兩列(多個 branch_key 共用名稱):先按名稱加總成一天一個淨額,
    // 否則買超天數會重複計算。
    const dayNet = new Map<string, number>();
    for (const b of byDate.get(t)!.branches) dayNet.set(b.n, (dayNet.get(b.n) ?? 0) + b.net);
    for (const [name, net] of dayNet) {
      let a = map.get(name);
      if (!a) {
        a = { net: 0, buyDays: 0, sellDays: 0, buyLots: 0, sellLots: 0, recentNet: 0, lastBuy: "", lastSell: "" };
        map.set(name, a);
      }
      a.net += net;
      if (t >= recentFrom) a.recentNet += net;
      if (net > 0) {
        a.buyDays += 1;
        a.buyLots += net;
        if (t > a.lastBuy) a.lastBuy = t;
      } else if (net < 0) {
        a.sellDays += 1;
        a.sellLots += -net;
        if (t > a.lastSell) a.lastSell = t;
      }
    }
  }

  const build = (side: Side): AccRow[] =>
    [...map.entries()]
      .filter(([, a]) => qualifies(side, a, min, totalVolume))
      .map(([name, a]) => ({
        name,
        net: a.net,
        buyDays: a.buyDays,
        sellDays: a.sellDays,
        buyLots: a.buyLots,
        sellLots: a.sellLots,
        retainPct: side === "acc"
          ? (a.buyLots > 0 ? (a.net / a.buyLots) * 100 : 0)
          : (a.sellLots > 0 ? (-a.net / a.sellLots) * 100 : 0),
        volumeSharePct: totalVolume > 0 ? (Math.abs(a.net) / totalVolume) * 100 : null,
        lastDate: side === "acc" ? a.lastBuy : a.lastSell,
        recentNet: a.recentNet,
      }))
      .sort((x, y) => Math.abs(y.net) - Math.abs(x.net) || x.name.localeCompare(y.name));

  const accAll = build("acc");
  const distAll = build("dist");
  return {
    available: true,
    days,
    start: dates[0],
    end: dates[dates.length - 1],
    acc: accAll.slice(0, MAX_ROWS),
    dist: distAll.slice(0, MAX_ROWS),
    accTotal: accAll.reduce((s, r) => s + r.net, 0),
    distTotal: distAll.reduce((s, r) => s + r.net, 0),
    accCount: accAll.length,
    distCount: distAll.length,
  };
}

/** 預設顯示前 DEFAULT_VISIBLE 列,展開後全部(已在 computeWindow 截在 MAX_ROWS) */
export function visibleRows<T>(rows: T[], expanded: boolean): T[] {
  return expanded ? rows : rows.slice(0, DEFAULT_VISIBLE);
}

/** YYYY-MM-DD → MM-DD */
export function fmtMonthDay(iso: string): string {
  const m = /^\d{4}-(\d{2}-\d{2})/.exec(iso);
  return m ? m[1] : iso;
}

/** 佔量百分比:< 0.1% 顯示「<0.1%」 */
export function fmtShare(pct: number | null): string {
  if (pct == null) return "—";
  if (pct > 0 && pct < 0.1) return "<0.1%";
  return `${pct.toFixed(1)}%`;
}
