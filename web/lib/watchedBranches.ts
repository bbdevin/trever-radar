// 自選「特定分點」(docs/52):使用者挑幾個分點(一個為「主」),看它們今天在哪些股票同步買超／賣超,
// 以及近 60 交易日估計仍持有。純函式,資料來自 branches/watch/{index,sNN}.json。
// 執行測試: node --test web/lib/watchedBranches.test.ts

/** [代號, 當日買張, 當日賣張, 當日淨張, 估計仍持有, 進場日, 視窗內出現天數, 視窗內淨張合計, 最後出現日]
 *  當日三欄 null = 當天不在該股前 15 大買超／賣超(未知,不是 0)。 */
export type WatchRow = [string, number | null, number | null, number | null, number, string | null, number, number, string];

/** [名稱, 收盤, 漲跌%(還原價), 近 20 日均量(張)] */
export type WatchStockMeta = [string, number | null, number | null, number | null];

/** [名稱, 分片, 當日買超檔數, 當日賣超檔數, 當日沒出現但估計仍持有的檔數] */
export type WatchIndexEntry = [string, number, number, number, number];

export interface WatchIndex {
  version: number;
  as_of: string | null;
  window_days: number;
  window_from: string | null;
  shards: number;
  hold_min: number;
  hold_top: number;
  branches: WatchIndexEntry[];
}

export interface WatchShard {
  version: number;
  as_of: string | null;
  window_days: number;
  window_from: string | null;
  shard: number;
  branches: Record<string, WatchRow[]>;
  stocks: Record<string, WatchStockMeta>;
}

export interface BranchSet {
  branches: string[];
  anchor: string;
}

export const DEFAULT_BRANCH_SET: BranchSet = {
  branches: ["富邦-新店", "永豐金-內湖", "元大-松江"],
  anchor: "富邦-新店",
};

export const MAX_BRANCHES = 6;
/** 「估計仍持有很多」:≥ 1,000 張,或 ≥ 該股近 20 日均量(一整天的量)。 */
export const BIG_HOLD_LOTS = 1000;

export type Side = "buy" | "sell" | "hold";
export type ComboMode = "anchor" | "anchor_plus" | "all" | "any";
export type SortKey = "combo" | "lots" | "amount" | "hold";

export const SIDE_LABEL: Record<Side, string> = { buy: "買超", sell: "賣超", hold: "估計仍持有" };

export function modeLabel(mode: ComboMode, side: "buy" | "sell"): string {
  const w = SIDE_LABEL[side];
  switch (mode) {
    case "anchor": return `主分點${w}`;
    case "anchor_plus": return `主＋任一同${w.slice(0, 1)}`;
    case "all": return `全部同${w.slice(0, 1)}`;
    case "any": return `任一分點${w}`;
  }
}

/** 篩選選中後的可見定義句(docs/19 §2.13)。 */
export function modeDefinition(mode: ComboMode, side: "buy" | "sell", anchor: string, n: number): string {
  const w = SIDE_LABEL[side];
  switch (mode) {
    case "anchor": return `${anchor} 今天${w}的股票;其他分點同步${w}的排前面。`;
    case "anchor_plus": return `${anchor} 今天${w},且至少再一個分點也${w}。`;
    case "all": return `選的 ${n} 個分點今天全部${w}。`;
    case "any": return `任一個選的分點今天${w}(不要求主分點)。`;
  }
}

export const SORT_OPTIONS: { key: SortKey; label: string }[] = [
  { key: "combo", label: "同步家數" },
  { key: "lots", label: "今日張數" },
  { key: "amount", label: "金額(估)" },
  { key: "hold", label: "估計仍持有" },
];

export const HONESTY_NOTE =
  "分點資料只有當天進入該股前 15 大買超或賣超才看得到;沒出現的日子是未知,不是 0。估計仍持有＝近 60 個交易日看得到的淨買超累計(賣超大於已知買超時歸 0),看不到的賣超扣不到,實際可能較少。金額＝張數 × 收盤 × 1,000,同屬估算。";

export const PUSH_NOTE = "每天資料更新後自動換成最新一日;這裡不發手機通知。";

export interface Cell {
  buy: number | null;
  sell: number | null;
  net: number | null;
  hold: number;
  entry: string | null;
  obs: number;
  sum: number;
  last: string;
}

export interface ComboRow {
  stock_id: string;
  name: string;
  close: number | null;
  chg: number | null;
  avgVol: number | null;
  cells: Record<string, Cell>;
  /** 今天淨買超的分點(依使用者選的順序) */
  buyers: string[];
  sellers: string[];
  holdTotal: number;
}

/** 從儲存值還原分點組合;壞值退回預設。anchor 一定在 branches 裡。 */
export function normalizeSet(raw: unknown): BranchSet {
  if (!raw || typeof raw !== "object") return { ...DEFAULT_BRANCH_SET, branches: [...DEFAULT_BRANCH_SET.branches] };
  const r = raw as { branches?: unknown; anchor?: unknown };
  const seen = new Set<string>();
  const branches: string[] = [];
  if (Array.isArray(r.branches)) {
    for (const b of r.branches) {
      if (typeof b !== "string") continue;
      const t = b.trim();
      if (!t || t.length > 64 || seen.has(t)) continue;
      seen.add(t);
      branches.push(t);
      if (branches.length >= MAX_BRANCHES) break;
    }
  }
  if (!branches.length) return { ...DEFAULT_BRANCH_SET, branches: [...DEFAULT_BRANCH_SET.branches] };
  const anchor = typeof r.anchor === "string" && branches.includes(r.anchor) ? r.anchor : branches[0];
  return { branches, anchor };
}

export function addBranch(set: BranchSet, name: string): BranchSet {
  const t = name.trim();
  if (!t || set.branches.includes(t) || set.branches.length >= MAX_BRANCHES) return set;
  return { ...set, branches: [...set.branches, t] };
}

export function removeBranch(set: BranchSet, name: string): BranchSet {
  if (set.branches.length <= 1 || !set.branches.includes(name)) return set;
  const branches = set.branches.filter((b) => b !== name);
  return { branches, anchor: set.anchor === name ? branches[0] : set.anchor };
}

export function setAnchor(set: BranchSet, name: string): BranchSet {
  return set.branches.includes(name) ? { ...set, anchor: name } : set;
}

/** 選的分點要抓哪些分片(去重、排序);index 裡沒有的分點略過。 */
export function shardsFor(index: WatchIndex, names: string[]): number[] {
  const byName = new Map(index.branches.map((b) => [b[0], b[1]]));
  const out = new Set<number>();
  for (const n of names) {
    const s = byName.get(n);
    if (s != null) out.add(s);
  }
  return [...out].sort((a, b) => a - b);
}

/** 依名稱片段搜尋分點(排除已選),今天有進出的排前面。 */
export function searchBranches(index: WatchIndex, q: string, exclude: string[], limit = 8): WatchIndexEntry[] {
  const t = q.trim();
  if (!t) return [];
  const ex = new Set(exclude);
  return index.branches
    .filter((b) => b[0].includes(t) && !ex.has(b[0]))
    .sort((a, b) => (b[2] + b[3]) - (a[2] + a[3]) || a[0].localeCompare(b[0], "zh-Hant"))
    .slice(0, limit);
}

/** 把選的分點在各分片的列合成「一檔一列」。 */
export function buildRows(set: BranchSet, shards: WatchShard[]): ComboRow[] {
  const byStock = new Map<string, ComboRow>();
  const meta: Record<string, WatchStockMeta> = {};
  for (const sh of shards) Object.assign(meta, sh.stocks);
  for (const b of set.branches) {
    const rows = shards.find((sh) => sh.branches[b])?.branches[b] ?? [];
    for (const [sid, buy, sell, net, hold, entry, obs, sum, last] of rows) {
      let row = byStock.get(sid);
      if (!row) {
        const m = meta[sid];
        row = {
          stock_id: sid, name: m?.[0] ?? sid, close: m?.[1] ?? null, chg: m?.[2] ?? null, avgVol: m?.[3] ?? null,
          cells: {}, buyers: [], sellers: [], holdTotal: 0,
        };
        byStock.set(sid, row);
      }
      row.cells[b] = { buy, sell, net, hold, entry, obs, sum, last };
      row.holdTotal += hold;
    }
  }
  for (const row of byStock.values()) {
    for (const b of set.branches) {
      const net = row.cells[b]?.net;
      if (net == null) continue;
      if (net > 0) row.buyers.push(b);
      else if (net < 0) row.sellers.push(b);
    }
  }
  return [...byStock.values()];
}

function sideList(row: ComboRow, side: "buy" | "sell"): string[] {
  return side === "buy" ? row.buyers : row.sellers;
}

export function isBigHold(hold: number, avgVol: number | null): boolean {
  if (hold <= 0) return false;
  return hold >= BIG_HOLD_LOTS || (avgVol != null && avgVol > 0 && hold >= avgVol);
}

/** 估計仍持有門檻:任一選的分點 ≥ holdMin 張。 */
export function filterRows(rows: ComboRow[], set: BranchSet, side: Side, mode: ComboMode, holdMin = 100): ComboRow[] {
  if (side === "hold") return rows.filter((r) => set.branches.some((b) => (r.cells[b]?.hold ?? 0) >= holdMin));
  return rows.filter((r) => {
    const list = sideList(r, side);
    switch (mode) {
      case "anchor": return list.includes(set.anchor);
      case "anchor_plus": return list.includes(set.anchor) && list.length >= 2;
      case "all": return set.branches.every((b) => list.includes(b));
      case "any": return list.length > 0;
    }
  });
}

/** 今天這一邊的張數合計(買超取正、賣超取絕對值;只算選的分點)。 */
export function sideLots(row: ComboRow, side: Side): number {
  if (side === "hold") return row.holdTotal;
  let s = 0;
  for (const c of Object.values(row.cells)) {
    if (c.net == null) continue;
    if (side === "buy" && c.net > 0) s += c.net;
    if (side === "sell" && c.net < 0) s -= c.net;
  }
  return s;
}

/** 張數 × 收盤 × 1,000(元);沒有收盤 → null。 */
export function amountEst(lots: number, close: number | null): number | null {
  return close == null ? null : lots * close * 1000;
}

export function sortRows(rows: ComboRow[], side: Side, key: SortKey): ComboRow[] {
  const amt = (r: ComboRow) => amountEst(sideLots(r, side), r.close) ?? -1;
  const co = (r: ComboRow) => (side === "hold"
    ? Object.values(r.cells).filter((c) => c.hold > 0).length
    : sideList(r, side).length);
  return [...rows].sort((a, b) => {
    let d = 0;
    switch (key) {
      case "combo": d = co(b) - co(a) || amt(b) - amt(a); break;
      case "lots": d = sideLots(b, side) - sideLots(a, side); break;
      case "amount": d = amt(b) - amt(a); break;
      case "hold": d = b.holdTotal - a.holdTotal; break;
    }
    return d || a.stock_id.localeCompare(b.stock_id);
  });
}

/** 分頁徽章:今天選的分點有任何一家出現(買超或賣超)的檔數。 */
export function todayCount(rows: ComboRow[]): number {
  return rows.filter((r) => r.buyers.length + r.sellers.length > 0).length;
}

export function fmtMD(d: string | null | undefined): string {
  if (!d) return "—";
  const m = /^\d{4}-(\d{2})-(\d{2})$/.exec(d);
  return m ? `${m[1]}/${m[2]}` : d;
}

/** 單一分點在一檔上的一句話:今天 + 估計仍持有。 */
export function cellLine(c: Cell | undefined): { today: string; hold: string } {
  if (!c) return { today: "近 60 日未見", hold: "" };
  const today = c.net == null
    ? "今天未進前 15 大"
    : c.net > 0 ? `今天買超 ${c.net.toLocaleString("zh-TW")} 張`
    : c.net < 0 ? `今天賣超 ${(-c.net).toLocaleString("zh-TW")} 張`
    : "今天買賣相抵";
  const hold = c.hold > 0
    ? `估計仍持有 ${c.hold.toLocaleString("zh-TW")} 張 · 進場 ${fmtMD(c.entry)}`
    : "估計仍持有 0";
  return { today, hold };
}

export function emptyText(side: Side, mode: ComboMode, asOf: string | null): string {
  if (!asOf) return "還沒有分點資料。";
  if (side === "hold") return "選的分點近 60 個交易日沒有估計仍持有達門檻的股票。";
  return `${fmtMD(asOf)} 沒有符合「${modeLabel(mode, side)}」的股票。可以換成「任一分點${SIDE_LABEL[side]}」或加入其他分點。`;
}
