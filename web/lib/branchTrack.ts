// 追蹤分點近 N 日明細(docs/24 §3 B1/B2)。純函式:客戶端對 branches/track/*.json
// 的緊湊列做任意區間加總,便於單元驗證(web 端無測試框架,以 node 腳本驗證)。

/** [date, stock_id, net_lots(帶正負), pct(可 null)] */
export type TrackRow = [string, string, number, number | null];

export interface TrackStockMeta {
  name: string;
  close: number | null;
}

export interface BranchTrackFile {
  branch_name: string;
  source: string;
  as_of: string;
  days: number;
  rows: TrackRow[];
  stocks: Record<string, TrackStockMeta>;
  truncated?: boolean;
}

export interface TrackIndexEntry {
  branch_name: string;
  source: string;
  file: string;
  rows_count: number;
  first_date: string | null;
}

export interface AggregatedStock {
  stock_id: string;
  net_lots: number;        // 期間淨買超張(加總,含賣出負值)
  pct_avg: number | null;  // 平均佔比(僅計 pct 非 null 的列)
  days_active: number;     // 期間內該股出現的天數
}

/** rows 中 distinct date 由新到舊(交易日,ISO 字串可字典序比較)。 */
export function tradingDaysDesc(rows: TrackRow[]): string[] {
  const set = new Set<string>();
  for (const r of rows) set.add(r[0]);
  return Array.from(set).sort((a, b) => (a < b ? 1 : a > b ? -1 : 0));
}

/**
 * 期間聚合:取 rows 中最新的 N 個交易日,對每檔股票加總 net_lots、平均 pct(非 null)。
 * N 大於可用交易日數時等同全取(呼叫端負責 clamp 與提示)。依 net_lots 降冪。
 */
export function aggregateBranchRows(rows: TrackRow[], n: number): AggregatedStock[] {
  const days = tradingDaysDesc(rows);
  const windowDays = new Set(days.slice(0, Math.max(0, n)));
  const acc = new Map<string, { net: number; pctSum: number; pctCnt: number; active: number }>();
  for (const [date, sid, net, pct] of rows) {
    if (!windowDays.has(date)) continue;
    let a = acc.get(sid);
    if (!a) {
      a = { net: 0, pctSum: 0, pctCnt: 0, active: 0 };
      acc.set(sid, a);
    }
    a.net += net;
    a.active += 1;
    if (pct != null) {
      a.pctSum += pct;
      a.pctCnt += 1;
    }
  }
  const out: AggregatedStock[] = [];
  for (const [sid, a] of acc) {
    out.push({
      stock_id: sid,
      net_lots: a.net,
      pct_avg: a.pctCnt > 0 ? a.pctSum / a.pctCnt : null,
      days_active: a.active,
    });
  }
  out.sort((x, y) => y.net_lots - x.net_lots || x.stock_id.localeCompare(y.stock_id));
  return out;
}
