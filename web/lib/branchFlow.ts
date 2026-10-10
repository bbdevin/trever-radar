/**
 * 籌碼日報(BranchFlowSection)的聚合純邏輯:N 日買超／賣超名單。
 *
 * 來源每天只公布買超前 15 大與賣超前 15 大(`SIDE_MAX`),所以:
 * - 1日 = 當天那最多 30 列,每側最多 15 家。
 * - N 日 = **各日前 15 大的合計**(同一分點在 N 天內的列相加),不是全市場完整合計:某天沒進
 *   名單的分點那天視為 0。畫面要寫清楚(`RANGE_NOTE`)。
 * - 同名同日多列(多個 branch_key 共用名稱)一律加總,每個名字一列。
 *
 * 1日 且當日 `branches`(個股 JSON 的當日完整列)非空時用它:2026-10-10 之前的 chips 每天只留
 * |淨額| 前 12 列,一邊倒的日子另一側會整個不見(2464 盟立 10/08 買超空白);`branches` 非空代表
 * raw 當日有列,它與 branchHistory[0] 必是同一天。新 chips(branch_days v2)兩者是同一批列。
 */
import type { BranchRow, StockJson } from "./types.ts";

/** 每側最多列幾家 = 來源每日每側公布的上限(前 15 大買超、前 15 大賣超)。 */
export const SIDE_MAX = 15;

/** 多日區間的說明(畫面常駐)。 */
export const RANGE_NOTE = `各日前 ${SIDE_MAX} 大買賣超合計(來源每日只公布買超、賣超各前 ${SIDE_MAX} 大;某天不在名單的分點那天算 0),不是全市場完整合計。`;

export interface FlowRow {
  name: string;
  buy: number;
  sell: number;
  net: number;
}

export interface FlowRowWithHistory extends FlowRow {
  /** 區間內每一天(舊→新)這個分點的淨張;1日 時就是那一天 */
  history: { t: string; net: number }[];
}

export interface FlowAggregate {
  /** 區間淨買超 > 0 的全部分點(淨張大→小) */
  buyers: FlowRow[];
  /** 區間淨賣超 < 0 的全部分點(淨張小→大) */
  sellers: FlowRow[];
  topBuy: FlowRowWithHistory[];
  topSell: FlowRowWithHistory[];
  /** 這次聚合實際用的來源:當日完整列(`branches`)或日史切片 */
  source: "branches" | "history";
}

export function aggregateBranchFlow(
  branches: BranchRow[],
  branchHistory: StockJson["branch_history"],
  activeDays: number,
): FlowAggregate {
  const latestFull = activeDays === 1 && branches.length > 0;
  const map = new Map<string, FlowRow>();
  const add = (name: string, b: number, s: number, net: number) => {
    let r = map.get(name);
    if (!r) map.set(name, (r = { name, buy: 0, sell: 0, net: 0 }));
    r.buy += b;
    r.sell += s;
    r.net += net;
  };
  const sliced = !branchHistory?.length || latestFull ? [] : branchHistory.slice(0, Math.max(1, activeDays));
  if (sliced.length) {
    for (const day of sliced) for (const b of day.branches) add(b.n, b.b, b.s, b.net);
  } else {
    for (const b of branches) add(b.name, b.buy, b.sell, b.net);
  }
  const allDates = sliced.length ? sliced.map((s) => s.t).reverse() : branchHistory?.[0]?.t ? [branchHistory[0].t] : [];

  const arr = [...map.values()];
  const buyers = arr.filter((x) => x.net > 0).sort((a, b) => b.net - a.net);
  const sellers = arr.filter((x) => x.net < 0).sort((a, b) => a.net - b.net);

  const withHistory = (b: FlowRow): FlowRowWithHistory => ({
    ...b,
    history: allDates.map((dt) => {
      if (!sliced.length) return { t: dt, net: b.net }; // 1日:整列就是當天
      const dObj = sliced.find((s) => s.t === dt);
      return { t: dt, net: dObj ? dObj.branches.reduce((s, x) => s + (x.n === b.name ? x.net : 0), 0) : 0 };
    }),
  });
  // 1日:同名加總後整天的列全列(來源每側最多 15 列,合併後只會更少;但同名兩個 branch_key 或
  // 來源 net 與買賣差不同的列,理論上可讓一側超過 15 家,不為了湊 15 偷砍一家)。
  // N 日:各日前 15 大合計後每側只列前 15(名單是「前 15 大」的設計,其餘在 buyers/sellers)。
  const cap = sliced.length > 1 ? SIDE_MAX : Infinity;
  return {
    buyers,
    sellers,
    topBuy: buyers.slice(0, cap).map(withHistory),
    topSell: sellers.slice(0, cap).map(withHistory),
    source: sliced.length ? "history" : "branches",
  };
}
