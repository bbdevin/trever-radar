/**
 * 只給 node --test 用的合成資料(docs/46 v2 §4):每一個 FACT_CATALOGUE code 至少要有一個情境產生它。
 * 技術/壓力情境直接組 Series(不經指標計算),好精準觸發每一個分支。
 */
import type { Tf } from "../bullBear.ts";
import type { BranchPnlRow, Candle, PriceLevels, StockJson } from "../types.ts";
import type { AllSeries, Series } from "./series.ts";

export const LAST = "2026-10-01";

function isoDay(i: number, start = "2025-01-06"): string {
  const d = new Date(start + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + i);
  return d.toISOString().slice(0, 10);
}

/** 平盤序列:什麼事實都不會產生(RSI 為 null) */
export function flatSeries(tf: Tf, n = 60, base = 100): Series {
  const a = (v: number) => Array.from({ length: n }, () => v);
  return {
    tf,
    t: Array.from({ length: n }, (_, i) => isoDay(i)),
    o: a(base), h: a(base + 1), l: a(base - 1), c: a(base), v: a(1000), days: a(1),
    ma: { 5: a(base), 10: a(base), 20: a(base), 60: a(base), 120: a(base), 240: a(base) },
    dif: a(0), hist: a(0), rsi: Array.from({ length: n }, () => null), k: a(50), d: a(50),
  };
}

/** 從尾端數第 k 根(-1 = 最後一根)設值 */
export function at<T>(arr: T[], fromEnd: number, v: T): void {
  arr[arr.length + fromEnd] = v;
}

const all = (D: Series, W: Series, M: Series): AllSeries => ({ adjusted: [], D, W, M });

/** 多方事件集中的日K + 多頭週K + 月K 站回均線 */
export function techBullSeries(): AllSeries {
  const D = flatSeries("D");
  at(D.ma[20], -1, 110); at(D.ma[20], -6, 100); at(D.ma[20], -2, 105);
  at(D.ma[60], -1, 105); at(D.ma[60], -6, 100);
  // 連 4 日收漲、今日 +7.7%、5 日 +12%、跳空向上
  at(D.c, -6, 100); at(D.c, -5, 100.5); at(D.c, -4, 101); at(D.c, -3, 102); at(D.c, -2, 104); at(D.c, -1, 112);
  at(D.h, -2, 105); at(D.l, -1, 110); at(D.h, -1, 113); at(D.o, -1, 110.5);
  at(D.hist, -2, -1); at(D.hist, -1, 1); at(D.dif, -1, 1);
  at(D.k, -2, 30); at(D.d, -2, 35); at(D.k, -1, 40); at(D.d, -1, 36);

  const W = flatSeries("W", 30);
  at(W.ma[5], -1, 110); at(W.ma[10], -1, 105); at(W.ma[20], -1, 100);
  at(W.rsi, -1, 60);
  at(W.v, -3, 1000); at(W.v, -2, 1100); at(W.v, -1, 1300);
  at(W.c, -3, 101); at(W.c, -2, 102); at(W.c, -1, 120);

  const M = flatSeries("M", 40);
  at(M.ma[20], -2, 105); at(M.c, -2, 104); at(M.ma[20], -1, 106); at(M.c, -1, 108);
  // 月K 柱狀體與 K 值:零軸上狀態、K>80
  at(M.dif, -1, 2); at(M.hist, -2, 0.5); at(M.hist, -1, 0.6); at(M.k, -1, 85); at(M.d, -1, 80); at(M.k, -2, 84); at(M.d, -2, 79);
  return all(D, W, M);
}

/** 空方事件集中的日K + 空頭週K */
export function techBearSeries(): AllSeries {
  const D = flatSeries("D");
  at(D.ma[20], -1, 90); at(D.ma[20], -6, 100); at(D.ma[20], -2, 95);
  at(D.ma[60], -1, 95); at(D.ma[60], -6, 100);
  // 連 4 日收跌、今日 −9.3%、5 日 −12%、跳空向下 + 長黑
  at(D.c, -6, 100); at(D.c, -5, 99.5); at(D.c, -4, 99); at(D.c, -3, 98); at(D.c, -2, 97); at(D.c, -1, 88);
  at(D.l, -2, 96); at(D.h, -1, 94); at(D.o, -1, 93.5); at(D.l, -1, 87.5);
  at(D.hist, -2, 1); at(D.hist, -1, -1); at(D.dif, -1, -1);
  at(D.k, -2, 70); at(D.d, -2, 65); at(D.k, -1, 60); at(D.d, -1, 64);

  const W = flatSeries("W", 40);
  at(W.ma[5], -1, 90); at(W.ma[10], -1, 95); at(W.ma[20], -1, 100);
  at(W.rsi, -1, 40);
  at(W.v, -3, 1000); at(W.v, -2, 1100); at(W.v, -1, 1300);
  at(W.c, -3, 99); at(W.c, -2, 98); at(W.c, -1, 80);
  at(W.dif, -1, -2); at(W.hist, -2, -0.5); at(W.hist, -1, -0.6);

  const M = flatSeries("M", 40);
  return all(D, W, M);
}

/** 日K 量縮(背景) */
export function techQuietSeries(): AllSeries {
  const D = flatSeries("D");
  at(D.v, -1, 300);
  return all(D, flatSeries("W", 30), flatSeries("M", 40));
}

export function okLevels(over: Partial<Extract<PriceLevels, { status: "ok" }>> = {}): Extract<PriceLevels, { status: "ok" }> {
  return {
    version: 1, status: "ok", as_of: LAST, bars: 240, close: 1085,
    ma: { "5": 1060, "10": 1040, "20": 1000, "60": 1019, "120": 1100, "240": 1200 },
    ma_align: "bull",
    highs: {
      "20": { p: 1135, t: LAST },
      "60": { p: 1594, t: "2026-03-12" },
      "120": { p: 1594, t: "2026-03-12" },
      "240": { p: 1594, t: "2026-03-12" },
    },
    lows: {
      "20": { p: 1060, t: "2026-09-25" },
      "60": { p: 778, t: "2026-07-30" },
      "120": { p: 456, t: "2026-04-10" },
      "240": { p: 330, t: "2025-11-21" },
    },
    new_high_20: true, new_low_20: false, vol_price_2d: "up",
    vol_profile: { window: 120, above: 0.38, below: 0.62, at: 0 },
    dense_above: { lo: 1100, hi: 1111, share: 0.06 },
    dense_below: { lo: 944, hi: 955, share: 0.04 },
    ...over,
  };
}

/**
 * 壓力段用的日K:300 根(>240 才有資料內最高/最低),近 120 根內有一個向上缺口(支撐)
 * 與一個向下缺口(壓力),最後一根收 1085。
 */
export function levelSeries(): AllSeries {
  const n = 300;
  const D = flatSeries("D", n, 1000);
  for (let i = 0; i < n; i++) {
    D.c[i] = 1000; D.h[i] = 1005; D.l[i] = 995; D.o[i] = 1000;
  }
  // 資料內最高(遠在 240 根之前)與最低
  D.h[10] = 2050; D.l[20] = 43;
  // 向上缺口(第 n-60 根):之前高 1005,當根低 1030,之後都在 1030 之上
  for (let i = n - 60; i < n; i++) {
    D.c[i] = 1050; D.h[i] = 1060; D.l[i] = 1030; D.o[i] = 1050;
  }
  // 向下缺口(第 n-30 根):之前低 1030 … 改成先上去再跳空下來
  for (let i = n - 45; i < n - 30; i++) {
    D.c[i] = 1250; D.h[i] = 1260; D.l[i] = 1240; D.o[i] = 1250;
  }
  for (let i = n - 30; i < n; i++) {
    D.c[i] = 1085; D.h[i] = 1095; D.l[i] = 1075; D.o[i] = 1085;
  }
  const W = flatSeries("W", 70, 1085);
  W.ma[5] = W.ma[5].map(() => 1070); W.ma[10] = W.ma[10].map(() => 1050); W.ma[20] = W.ma[20].map(() => 1120); W.ma[60] = W.ma[60].map(() => 990);
  const M = flatSeries("M", 70, 1085);
  M.ma[5] = M.ma[5].map(() => 1150); M.ma[10] = M.ma[10].map(() => 980);
  return all(D, W, M);
}

/** 日K 的成交量(張)序列;日期與 insti/margin/branch fixture 對齊,新的在後 */
export function volCandles(dates: string[], v = 10000): Candle[] {
  return [...dates].sort().map((t, i) => ({ t, o: 100, h: 101, l: 99, c: 100 + i * 0.1, v, amt: 0, af: 1 }));
}

/** 近 N 個交易日(新→舊) */
export function recentDates(n: number, last = LAST): string[] {
  const out: string[] = [];
  const d = new Date(last + "T00:00:00Z");
  while (out.length < n) {
    const dow = d.getUTCDay();
    if (dow !== 0 && dow !== 6) out.push(d.toISOString().slice(0, 10));
    d.setUTCDate(d.getUTCDate() - 1);
  }
  return out;
}

type InstiRow = NonNullable<StockJson["insti_history"]>[number];

/** 外資連 5 日賣超(今日 −2,245)、投信今日買超 983;量 24,330 */
export function instiSellStreak(): { ih: InstiRow[]; candles: Candle[] } {
  const ds = recentDates(25);
  const ih = ds.map((t, i): InstiRow => {
    const foreign = i === 0 ? -2245 : i < 5 ? -2000 - i * 100 : i % 2 ? 300 : -100;
    const trust = i === 0 ? 983 : 10;
    return { t, foreign, trust, dealer: 0, total: foreign + trust };
  });
  return { ih, candles: volCandles(ds, 24330) };
}

/** 外資、投信同步買超且合計 ≥3% 量 */
export function instiBothBuy(): { ih: InstiRow[]; candles: Candle[] } {
  const ds = recentDates(25);
  const ih = ds.map((t, i): InstiRow => {
    const foreign = i < 3 ? 1500 : 50;
    const trust = i < 3 ? 800 : 5;
    return { t, foreign, trust, dealer: 0, total: foreign + trust };
  });
  return { ih, candles: volCandles(ds, 20000) };
}

/** 外資、投信同步賣超;合計賣超 ≥3% */
export function instiBothSell(): { ih: InstiRow[]; candles: Candle[] } {
  const ds = recentDates(25);
  const ih = ds.map((t, i): InstiRow => {
    const foreign = i === 0 ? -1500 : 40;
    const trust = i === 0 ? -700 : -3;
    return { t, foreign, trust, dealer: 0, total: foreign + trust };
  });
  return { ih, candles: volCandles(ds, 20000) };
}

/** 單日不顯著,近 20 日累計顯著(外資買、投信賣;flip = 反過來) */
export function insti20d(flip = false): { ih: InstiRow[]; candles: Candle[] } {
  const ds = recentDates(25);
  const s = flip ? -1 : 1;
  const ih = ds.map((t, i): InstiRow => {
    const foreign = s * (i === 0 ? 50 : 400);
    const trust = s * (i === 0 ? -20 : -250);
    return { t, foreign, trust, dealer: 0, total: foreign + trust };
  });
  return { ih, candles: volCandles(ds, 10000) };
}

type MarginRow = NonNullable<StockJson["margin_history"]>[number];

function marginRows(balances: number[], shorts: number[], usage: number): MarginRow[] {
  const ds = recentDates(balances.length);
  return ds.map((t, i) => ({
    t, balance: balances[i], prev: null, limit: 10000, usage, chg: null, buy: null, sell: null, repay: null,
    short_balance: shorts[i], short_prev: null, cost_est: null,
  }));
}

/** 融資使用率過熱 + 融資 5 日增 18% 而股價跌;融券 5 日 +50% */
export function marginHotUp(): { mh: MarginRow[]; adjusted: Candle[] } {
  const mh = marginRows([1300, 1250, 1200, 1150, 1120, 1100, 1090], [150, 140, 130, 120, 110, 100, 100], 0.7);
  // volCandles 由舊到新排;收盤逐日下跌
  const adjusted = volCandles(mh.map((r) => r.t)).map((c, i) => ({ ...c, c: 100 - i * 0.5 }));
  return { mh, adjusted };
}

/** 使用率健康 + 融資 5 日減 18% 而股價漲;券資比 44% */
export function marginOkDown(): { mh: MarginRow[]; adjusted: Candle[] } {
  const mh = marginRows([900, 950, 1000, 1050, 1080, 1100, 1110], [400, 400, 400, 400, 400, 400, 400], 0.2);
  return { mh, adjusted: volCandles(mh.map((r) => r.t)) };
}

type BranchDay = NonNullable<StockJson["branch_history"]>[number];

// ── 融資 × 分點集中度(docs/46 §7) ──
// i = 交易日索引(0 = LAST,新→舊);集保每 5 個交易日一筆(週索引 w,對應 i = 5w);量 10,000 張/日。

export interface FlowCase {
  data: Pick<StockJson, "margin_history" | "branch_history" | "insti_history" | "holders_history">;
  candles: Candle[];
}

interface FlowSpec {
  n: number;
  usage: number;
  bal: (i: number) => number;
  branches: (i: number) => { n: string; net: number }[];
  inst: (i: number) => { foreign: number; trust: number };
  close: (i: number) => number;
  p400: (w: number) => number;
  rh: (w: number) => number;
}

function flowCase(s: FlowSpec): FlowCase {
  const ds = recentDates(s.n);
  const candles = ds.map((t, i) => ({ t, o: s.close(i), h: s.close(i), l: s.close(i), c: s.close(i), v: 10000, amt: 0, af: 1 })).reverse();
  return {
    candles,
    data: {
      margin_history: ds.map((t, i) => ({
        t, balance: s.bal(i), prev: null, limit: 40000, usage: s.usage, chg: null, buy: null, sell: null, repay: null,
        short_balance: null, short_prev: null, cost_est: null,
      })),
      branch_history: ds.map((t, i) => ({ t, branches: s.branches(i).map((b) => ({ n: b.n, b: Math.max(b.net, 0), s: Math.max(-b.net, 0), net: b.net })) })),
      insti_history: ds.map((t, i) => {
        const x = s.inst(i);
        return { t, ...x, dealer: 0, total: x.foreign + x.trust };
      }),
      holders_history: ds.filter((_, i) => i % 5 === 0).map((t, w) => ({
        t, thresholds: { "400": { holders: 90, shares_pct: s.p400(w) } }, retail_pct: null, retail_holders: s.rh(w),
      })),
    },
  };
}

/**
 * 2476 型:融資自 i=100(10,000 張,近 130 日最低)線性增至 20,000 張(使用率 75%);
 * 統一-敦南每天買 150、康和每天買 60(囤貨),美林每天買 100(外資席位,不計);
 * 股價緩漲、400 張以上大戶每週 +0.1 個百分點;法人每天各買 10。
 * → 20 日集中(C_MARGIN_UP_CONC)+ 堆積集中(C_MARGIN_BUILDUP_CONC,近6月)→ C_MARGIN_HOT rank 2
 */
const concSpec = (): FlowSpec => ({
  n: 130, usage: 0.75,
  bal: (i) => (i <= 100 ? 20000 - 100 * i : 12000),
  branches: () => [{ n: "統一-敦南", net: 150 }, { n: "康和", net: 60 }, { n: "美林", net: 100 }],
  inst: () => ({ foreign: 10, trust: 10 }),
  close: (i) => 120 - i * 0.1,
  p400: (w) => 50 - w * 0.1,
  rh: (w) => 100000 + w * 500,
});
export const marginConcBuildup = (): FlowCase => flowCase(concSpec());

/** 2236 型:同上但集保 400 張以上大戶每週 −0.5 個百分點 → 無法判斷,不產事實;C_MARGIN_HOT 維持 rank 3 */
export const marginConcTdccDown = (): FlowCase => flowCase({ ...concSpec(), p400: (w) => 50 + w * 0.5 });

/** 唯一的大買方是外資席位(美林、(港商)麥格理)→ 囤貨分點合計 0,股價沒跌 → 不產事實 */
export const marginConcForeignOnly = (): FlowCase =>
  flowCase({ ...concSpec(), branches: () => [{ n: "美林", net: 150 }, { n: "(港商)麥格理", net: 100 }] });

/** 分點缺日:20 日視窗內少一天 branch_history → computeWindow 不可用 → 不產事實 */
export function marginConcGap(): FlowCase {
  const f = marginConcBuildup();
  f.data.branch_history = f.data.branch_history!.filter((_, i) => i !== 7);
  return f;
}

/**
 * 8039/3450 型:融資 20 日 +2,000 張(+20%,全在近 5 日),每天換不同分點買 100(無囤貨),
 * 外資每天賣 700;股價自 120 跌到 100;400 張以上大戶每週 −0.5、散戶人數每週 +2%;使用率 50%。
 * → C_MARGIN_UP_DISPERSED,且不再列 5 日 C_MARGIN_UP_PRICE_DOWN
 */
const dispersedSpec = (): FlowSpec => ({
  n: 30, usage: 0.5,
  bal: (i) => (i < 5 ? 10000 + (5 - i) * 400 : 10000),
  branches: (i) => [{ n: `散戶分點${i}`, net: 100 }],
  inst: () => ({ foreign: -700, trust: 0 }),
  close: (i) => 100 + i,
  p400: (w) => 50 + w * 0.5,
  rh: (w) => 100000 / 1.02 ** w,
});
export const marginDispersedDown = (): FlowCase => flowCase(dispersedSpec());

/** 6538 型(20 日):同上但外資每天買 100(20 日 +2,000 ≥ 融資增量一半)→ 法人主導,不判讀;5 日融資增價跌照列 */
export const marginInstDominant = (): FlowCase => flowCase({ ...dispersedSpec(), inst: () => ({ foreign: 100, trust: 0 }) });

/** 近 25 日:A 天天買 300(囤貨、地緣)、B 天天賣 300(出貨);今日 G 買 1,000(有隔日沖紀錄) */
export function branchMonth(): Pick<StockJson, "branch_history" | "branch_tags" | "branch_pnl_est"> & { candles: Candle[] } {
  const ds = recentDates(25);
  const bh: BranchDay[] = ds.map((t, i) => ({
    t,
    branches: [
      { n: "A分點", b: 300, s: 0, net: 300 },
      { n: "B分點", b: 0, s: 300, net: -300 },
      ...(i === 0 ? [{ n: "G分點", b: 1000, s: 0, net: 1000 }] : []),
    ],
  }));
  const row = (name: string, pos: number, un: number) => ({
    name, est_total: un, realized: 0, unrealized: un, pos_lots: pos, avg_cost: 100, last_close: 100, buy_lots: pos,
    sell_lots_attributed: 0, sell_lots_unattributed: 0, visible_days: 60, max_cost: 0, ret_pct: null, af_adjusted: false,
    first_date: ds[24], last_date: ds[0],
  });
  return {
    candles: volCandles(ds, 10000),
    branch_history: bh,
    branch_tags: { as_of: LAST, geo: { rule: "city", names: ["A分點"] }, daytrade: { min_obs: 5, rate: 0.6, rows: { G分點: [10, 8] } }, tracked: [] },
    branch_pnl_est: {
      as_of: LAST, definitions_version: "1",
      windows: {
        "60": {
          window_days: 60, first_date: ds[24], pairs_considered: 4, pairs_skipped_missing_price: 0,
          // 前 3 名(甲乙戊)由 C_SMART_HOLDING 逐家寫;己、庚留給 C_PNL_GAINERS_HOLDING(「另有」)
          gainers: [row("甲", 500, 2_000_000), row("乙", 300, 1_000_000), row("戊", 0, 800_000), row("己", 120, 50_000), row("庚", 80, 20_000)],
          losers: [row("丙", 400, -1_500_000), row("丁", 200, -300_000)],
        },
      },
    },
  };
}

function pnlRow(name: string, est: number, pos: number, un: number, ds: string[]): BranchPnlRow {
  return {
    name, est_total: est, realized: est - un, unrealized: un, pos_lots: pos, avg_cost: 100, last_close: 100, buy_lots: pos + 500,
    sell_lots_attributed: 0, sell_lots_unattributed: 0, visible_days: 40, max_cost: 5_000_000, ret_pct: null, af_adjusted: false,
    first_date: ds[ds.length - 1], last_date: ds[0],
  };
}

function pctileRow(name: string, lowBuy: number, highSell: number, known = 10) {
  return {
    branch_name: name, buy_pctile_known: known, buy_pctile_unknown: 0, low_buy_count: lowBuy,
    sell_pctile_known: known, sell_pctile_unknown: 0, high_sell_count: highSell,
    buy_lots_known: known * 100, low_buy_lots: lowBuy * 100, sell_lots_known: known * 100, high_sell_lots: highSell * 100,
  };
}

/**
 * 低買高賣/區間損益前段分點(docs/46 §6.8),量 10,000 張/日:
 *  - 群益金鼎-板橋:短線派第 1(買低 70%、賣高 80%),近 5 日每天買 300 → 近5日 +1,500(佔量 3.0%)
 *  - 凱基-台北:區間損益估算 3月第 1(+500 萬),只有今日買 600 → 寫「今日」(佔量 6.0%)
 *  - B1:長線派第 1(賣高 60%),今日賣 600 → 空方
 *  - 元大-士林:長線派第 2,今日賣 40(未達 50 張下限)→ 份量不足,不列
 *  - 富邦-建國:區間損益估算 3月第 2,估算持股 100 張;前 3 日各賣 60(近5日 −180,佔量 0.36% 未達門檻),
 *    但估算持股減少 180/(100+180)=64% ≥30% → 空方
 *  - 永豐-竹北:短線派第 6(超出前 5 名)今日買 2,000 → 不是強分點,不列
 *  - 國泰-敦南:區間損益估算 1年第 1,沒有買賣、仍持股 800 張帳面為正 → C_SMART_HOLDING
 *  - 紀錄不足:短線派第 2 但買側只 3 次可知(compactSide 判不足)今日買 3,000 → 不列
 */
export function branchSmart(): Pick<StockJson, "branch_history" | "branch_pctile_counts" | "branch_pnl_est" | "branch_tags"> & { candles: Candle[] } {
  const ds = recentDates(25);
  const bh: BranchDay[] = ds.map((t, i) => ({
    t,
    branches: [
      ...(i < 5 ? [{ n: "群益金鼎-板橋", b: 300, s: 0, net: 300 }] : []),
      ...(i === 0 ? [
        { n: "凱基-台北", b: 600, s: 0, net: 600 },
        { n: "B1", b: 0, s: 600, net: -600 },
        { n: "元大-士林", b: 0, s: 40, net: -40 },
        { n: "永豐-竹北", b: 2000, s: 0, net: 2000 },
        { n: "紀錄不足", b: 3000, s: 0, net: 3000 },
      ] : []),
      ...(i >= 1 && i <= 3 ? [{ n: "富邦-建國", b: 0, s: 60, net: -60 }] : []),
    ],
  }));
  const camp = (rows: ReturnType<typeof pctileRow>[]) => ({
    available: true, stock_buy_pctile_known: 2000, stock_low_buy_count: 800, stock_sell_pctile_known: 2000, stock_high_sell_count: 800,
    stock_buy_lots_known: 200000, stock_low_buy_lots: 80000, stock_sell_lots_known: 200000, stock_high_sell_lots: 80000,
    shrink_k_buy_lots: 100, shrink_k_sell_lots: 100, branches: rows,
  });
  return {
    candles: volCandles(ds, 10000),
    branch_history: bh,
    branch_tags: { as_of: LAST, geo: { rule: "city", names: [] }, daytrade: { min_obs: 5, rate: 0.6, rows: {} }, tracked: [] },
    branch_pctile_counts: {
      version: 2, ranking: "lots_shrunk_v2", min_known_episodes_per_side: 5, max_branches: 30, windows: { short: 20, long: 120 },
      low_buy_max_pctile: 0.4, high_sell_min_pctile: 0.6, min_daytrade_obs: 5, as_of: LAST, window_market_days: 120, window_from: ds[24],
      computed_at: null, definitions_version: null, stock_daytrade_obs: null, stock_daytrade_paybacks: null,
      short: camp([
        pctileRow("群益金鼎-板橋", 7, 8), { ...pctileRow("紀錄不足", 3, 3), buy_pctile_known: 3, buy_lots_known: 300 },
        pctileRow("A1", 7, 7), pctileRow("A2", 7, 7), pctileRow("A3", 7, 7), pctileRow("永豐-竹北", 9, 9),
      ]),
      long: camp([pctileRow("B1", 6, 6), pctileRow("元大-士林", 6, 6)]),
      lookup_fields: ["branch_name"], lookup: [],
    },
    branch_pnl_est: {
      as_of: LAST, definitions_version: "pnl-avgcost-v1",
      windows: {
        "60": {
          window_days: 60, first_date: ds[24], pairs_considered: 4, pairs_skipped_missing_price: 0,
          gainers: [pnlRow("凱基-台北", 5_000_000, 900, 3_000_000, ds), pnlRow("富邦-建國", 3_000_000, 100, 200_000, ds)],
          // A2:短線派前 5,沒有買賣、仍持股 300 張但帳面為負 → C_SMART_HOLDING_NEG(背景)
          losers: [pnlRow("A2", -1_000_000, 300, -800_000, ds)],
        },
        "240": {
          window_days: 240, first_date: ds[24], pairs_considered: 4, pairs_skipped_missing_price: 0,
          gainers: [pnlRow("國泰-敦南", 9_000_000, 800, 4_000_000, ds)],
          losers: [],
        },
      },
    },
  };
}

/** 近 25 日:E 先賣後買(只有 1 週囤貨)、F 先買後賣(只有 1 週出貨,地緣);今日追蹤分點 H 賣 1,500 */
export function branchWeek(): Pick<StockJson, "branch_history" | "branch_tags"> & { candles: Candle[] } {
  const ds = recentDates(25);
  const bh: BranchDay[] = ds.map((t, i) => ({
    t,
    branches: [
      { n: "E分點", b: i < 5 ? 600 : 0, s: i < 5 ? 0 : 500, net: i < 5 ? 600 : -500 },
      { n: "F分點", b: i < 5 ? 0 : 500, s: i < 5 ? 600 : 0, net: i < 5 ? -600 : 500 },
      ...(i === 0 ? [{ n: "H分點", b: 0, s: 1500, net: -1500 }] : []),
    ],
  }));
  return {
    candles: volCandles(ds, 10000),
    branch_history: bh,
    branch_tags: { as_of: LAST, geo: { rule: "city", names: ["F分點"] }, daytrade: { min_obs: 5, rate: 0.6, rows: {} }, tracked: ["H分點", "靜音分點"] },
  };
}

type HoldersRow = NonNullable<StockJson["holders_history"]>[number];

function holdersRows(n: number, f: (i: number) => { p400: number; p1000: number; c1000: number; rh: number; rp: number; ins: number }): HoldersRow[] {
  return recentDates(n * 5).filter((_, i) => i % 5 === 0).slice(0, n).map((t, i) => {
    const x = f(i);
    return {
      t,
      thresholds: { "400": { holders: 90, shares_pct: x.p400 }, "1000": { holders: x.c1000, shares_pct: x.p1000 } },
      retail_pct: x.rp, retail_holders: x.rh, insider_pct: x.ins,
    };
  });
}

/** 14 週:400 張連 3 週增(近 14 週最高)、1000 張反向減、散戶人數減 3%、1000 張人數 41→45、董監 +0.24 */
export function holdersBull(): HoldersRow[] {
  return holdersRows(14, (i) => ({
    p400: i < 3 ? 77 - i * 0.4 : 75.8,
    p1000: i === 0 ? 70 : 70.4,
    c1000: i === 0 ? 45 : 41,
    rh: i === 0 ? 97000 : 100000,
    rp: 23,
    ins: i < 4 ? 47.24 : 47,
  }));
}

/** 400 張減 0.6、1000 張反向增 0.6、散戶人數增 3%、董監 −0.3 */
export function holdersBear(): HoldersRow[] {
  return holdersRows(6, (i) => ({
    p400: i === 0 ? 76 : 76.6,
    p1000: i === 0 ? 71.2 : 70.6,
    c1000: 45,
    rh: i === 0 ? 103000 : 100000,
    rp: i === 0 ? 23.4 : 23,
    ins: i === 0 ? 46.9 : 47.2,
  }));
}

export const DIRECTORS_PLEDGED: NonNullable<StockJson["directors_latest"]> = {
  as_of_ym: "2026-08",
  rows: [
    { title: "董事長本人", name: "某甲", shares: 1_000_000, lots: 1000, pledged_shares: 500_000 },
    { title: "董事本人", name: "某乙", shares: 1_000_000, lots: 1000, pledged_shares: 300_000 },
  ],
};
