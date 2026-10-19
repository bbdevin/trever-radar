// 自選「特定分點」(docs/52):使用者挑幾個分點(一個為「主」),看它們今天在哪些股票同步買超／賣超,
// 以及近 60 交易日估計仍持有。純函式,資料來自 branches/watch/{index,sNN}.json。
// 執行測試: node --test web/lib/watchedBranches.test.ts

/** [代號, 當日買張, 當日賣張, 當日淨張, 估計仍持有, 進場日, 視窗內出現天數, 視窗內淨張合計, 最後出現日, 均價(估)]
 *  當日三欄 null = 當天不在該股前 15 大買超／賣超(未知,不是 0)。
 *  均價(估):這段持有的平均成本(買超日收盤加權,還原到資料日尺度);null = 沒有持有或有買超日缺收盤;舊檔沒有這欄。 */
export type WatchRow = [string, number | null, number | null, number | null, number, string | null, number, number, string, (number | null)?];

/** [標的, 認購淨額, 認售淨額, 認購仍持有成本, 認購換算現股均價, 認售仍持有成本, 認售換算現股均價](元)
 *  當天淨額 null = 沒有列或 |金額| 未達門檻;持有欄來自 docs/51(仍持有成本 ≥ 500 萬才有)。哪一天見 WatchIndex.warrant。 */
export type WatchWarrantRow = [string, number | null, number | null, number | null, number | null, number | null, number | null];

/** 權證欄的資料日。counted = 權證那天就是現股分點資料日,才算進今天的同買／同賣;
 *  false = 權證分點比較舊(晚一步匯入),只列出、標日期。 */
export interface WatchWarrantMeta {
  data_date: string;
  day: string;
  counted: boolean;
  /** 那天權證分點匯入完整(import_logs branch_warrant_pool 最後一輪 ok;沒有紀錄也算);舊檔沒有 */
  complete?: boolean;
  min_amount: number;
  /** 夜間權證池的成交金額門檻;舊檔沒有 */
  pool_turnover_min?: number;
}

/** [名稱, 收盤, 漲跌%(還原價), 近 20 日均量(張), 今天狀態]
 *  今天狀態:1 = 這檔今天有分點列(選的分點沒列 = 未進前 15 大);0 = 匯入池的股票、今天的匯入還沒完成
 *  (晚上第二輪才補齊)→ 尚未匯入;2 = 今天沒有列也不會再補(匯入已完成的確認空,或 ETF 等不在匯入池)
 *  → 無分點資料。舊檔沒有這欄 → 當作 1。 */
export type WatchStockMeta = [string, number | null, number | null, number | null, (0 | 1 | 2)?, (0 | 1)?];

export type TodayState = "rows" | "pending" | "nodata";

/** [名稱, 分片, 當日買超檔數, 當日賣超檔數, 當日沒出現但估計仍持有(已輸出)檔數, 同上(截斷前)] */
export type WatchIndexEntry = [string, number, number, number, number, number?];

export interface WatchIndex {
  version: number;
  as_of: string | null;
  window_days: number;
  window_from: string | null;
  shards: number;
  hold_min: number;
  /** 小型股相對門檻的地板(≥ 20 日均量且 ≥ 這個張數);舊檔沒有 → 20 */
  hold_floor?: number;
  hold_top: number;
  /** 今日分點匯入覆蓋,照匯入端:池(普通股、不含 ETF)裡已有分點列的檔數;complete = 匯入端記為完成。 */
  coverage?: { covered: number; expected: number; complete: boolean } | null;
  /** 權證欄的資料日;null／舊檔沒有 = 沒有權證資料 */
  warrant?: WatchWarrantMeta | null;
  branches: WatchIndexEntry[];
}

export interface WatchShard {
  version: number;
  as_of: string | null;
  window_days: number;
  window_from: string | null;
  shard: number;
  branches: Record<string, WatchRow[]>;
  /** 舊檔沒有 */
  warrants?: Record<string, WatchWarrantRow[]>;
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
/** 「≥ 20 日均量」那條的地板,避免 3 張 vs 均量 2 張也被標(與匯出端 HOLD_FLOOR_LOTS 同值)。 */
export const HOLD_FLOOR_LOTS = 20;

export type Side = "buy" | "sell" | "hold";
export type ComboMode = "anchor" | "anchor_plus" | "all" | "any";
export type SortKey = "combo" | "lots" | "amount" | "hold" | "gap";

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
  { key: "gap", label: "現價對均價(低→高)" },
];

export const HONESTY_NOTE =
  "分點資料只有當天進入該股前 15 大買超或賣超才看得到;沒出現的日子是未知,不是 0。估計仍持有＝近 60 個交易日看得到的淨買超累計(賣超大於已知買超時歸 0),看不到的賣超扣不到,實際可能較少。金額＝張數 × 收盤 × 1,000,同屬估算。均價(估)＝這段持有裡每個看得到的買超日以當天收盤計價的平均成本(賣超不改均價,歸 0 後重算),不是成交均價。";

/** 「含權證」開著時的規則句(docs/52 §8)。 */
export const WARRANT_RULE =
  "含權證:分點今天淨買某檔的認購權證(≥ 100 萬)也算同買;淨賣認購、或淨買認售算同賣;認售淨賣方向不明確,只列出不計。牛熊證不算。只算收集得到的權證:當天成交 ≥ 100 萬的認購／認售(上市＋上櫃),且分點進入該權證當天前 15 大;收集不到的標「權證:未收集」。";

export const WARRANT_OFF = "不含權證:只看現股分點;權證進出仍列在卡片裡,但不算同買／同賣。";

export const WARRANT_NOTE =
  "權證分點只收集當天成交 ≥ 100 萬的認購／認售權證(上市＋上櫃),而且同樣只有當天進入該權證前 15 大才看得到;成交較小的權證、或沒進前 15 大的分點,這裡看不到,不代表沒有進出。金額＝權證淨張數 × 當日權證收盤 × 1,000,同一檔標的的所有認購(或認售)權證合計。權證仍持有與換算均價沿用權證分點頁的估算(仍持有成本 ≥ 500 萬才列)。";

/** 權證那一格;金額單位元,null = 沒有或未達門檻。 */
export interface WarrantCell {
  call: number | null;
  put: number | null;
  callHeld: number | null;
  callAvg: number | null;
  putHeld: number | null;
  putAvg: number | null;
}

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
  /** 均價(估);null = 沒有持有或有買超日缺收盤 */
  avg: number | null;
}

export interface ComboRow {
  stock_id: string;
  name: string;
  close: number | null;
  chg: number | null;
  avgVol: number | null;
  cells: Record<string, Cell>;
  /** 這檔今天的分點狀態(見 WatchStockMeta) */
  today: TodayState;
  /** 今天現股淨買超的分點(依使用者選的順序) */
  buyers: string[];
  sellers: string[];
  /** 今天權證算進買方／賣方的分點(認購淨買 → 買方;認購淨賣、認售淨買 → 賣方)。
   *  權證資料日不是今天(counted=false)時一律空:舊的權證進出只列出、不算。 */
  wBuyers: string[];
  wSellers: string[];
  /** 現股或(算進今天的)權證任一邊參與,依選的順序 */
  allBuyers: string[];
  allSellers: string[];
  warrants: Record<string, WarrantCell>;
  /** 這檔那天有沒有權證進夜間權證池(個股摘要第 6 欄);null = 不知道(舊檔/沒有權證資料) */
  warrantPooled: boolean | null;
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

/** 搜尋用的寬鬆名稱:全形→半形(NFKC)、去空白與各種連字號、臺→台、英文小寫。
 *  「富邦新店」「富邦 新店」「富邦－新店」都對得到「富邦-新店」。 */
export function looseName(s: string): string {
  return s.normalize("NFKC").replace(/[\s\-‐‑‒–—―−_·・.]/g, "").replace(/臺/g, "台").toLowerCase();
}

/** 依名稱片段搜尋分點(寬鬆比對,排除已選),今天有進出的排前面。 */
export function searchBranches(index: WatchIndex, q: string, exclude: string[], limit = 8): WatchIndexEntry[] {
  const t = looseName(q);
  if (!t) return [];
  const ex = new Set(exclude);
  return index.branches
    .filter((b) => looseName(b[0]).includes(t) && !ex.has(b[0]))
    .sort((a, b) => (b[2] + b[3]) - (a[2] + a[3]) || a[0].localeCompare(b[0], "zh-Hant"))
    .slice(0, limit);
}

/** 把選的分點在各分片的列合成「一檔一列」。warrantCounted = index.warrant?.counted(權證那天是今天)。 */
export function buildRows(set: BranchSet, shards: WatchShard[], warrantCounted = false): ComboRow[] {
  const byStock = new Map<string, ComboRow>();
  const meta: Record<string, WatchStockMeta> = {};
  for (const sh of shards) Object.assign(meta, sh.stocks);
  const rowFor = (sid: string): ComboRow => {
    let row = byStock.get(sid);
    if (!row) {
      const m = meta[sid];
      row = {
        stock_id: sid, name: m?.[0] ?? sid, close: m?.[1] ?? null, chg: m?.[2] ?? null, avgVol: m?.[3] ?? null,
        today: m?.[4] === 0 ? "pending" : m?.[4] === 2 ? "nodata" : "rows",
        cells: {}, buyers: [], sellers: [], wBuyers: [], wSellers: [], allBuyers: [], allSellers: [], warrants: {},
        warrantPooled: m?.[5] === 1 ? true : m?.[5] === 0 ? false : null, holdTotal: 0,
      };
      byStock.set(sid, row);
    }
    return row;
  };
  for (const b of set.branches) {
    const rows = shards.find((sh) => sh.branches[b])?.branches[b] ?? [];
    for (const [sid, buy, sell, net, hold, entry, obs, sum, last, avg] of rows) {
      const row = rowFor(sid);
      row.cells[b] = { buy, sell, net, hold, entry, obs, sum, last, avg: avg ?? null };
      row.holdTotal += hold;
    }
    const wrows = shards.find((sh) => sh.warrants?.[b])?.warrants?.[b] ?? [];
    for (const [sid, call, put, callHeld, callAvg, putHeld, putAvg] of wrows) {
      rowFor(sid).warrants[b] = { call, put, callHeld, callAvg, putHeld, putAvg };
    }
  }
  for (const row of byStock.values()) {
    for (const b of set.branches) {
      const net = row.cells[b]?.net;
      if (net != null) {
        if (net > 0) row.buyers.push(b);
        else if (net < 0) row.sellers.push(b);
      }
      const w = row.warrants[b];
      if (w && warrantCounted) {
        if (w.call != null && w.call > 0) row.wBuyers.push(b);
        if ((w.call != null && w.call < 0) || (w.put != null && w.put > 0)) row.wSellers.push(b);
      }
      if ((net != null && net > 0) || row.wBuyers.includes(b)) row.allBuyers.push(b);
      if ((net != null && net < 0) || row.wSellers.includes(b)) row.allSellers.push(b);
    }
  }
  return [...byStock.values()];
}

/** 今天這一邊參與的分點(依選的順序);withWarrants = 「含權證」開關。 */
export function participants(row: ComboRow, side: "buy" | "sell", withWarrants = true): string[] {
  if (side === "buy") return withWarrants ? row.allBuyers : row.buyers;
  return withWarrants ? row.allSellers : row.sellers;
}

/** 只靠權證參與(現股那邊沒有)的分點數。 */
export function warrantOnlyCount(row: ComboRow, side: "buy" | "sell"): number {
  const stock = side === "buy" ? row.buyers : row.sellers;
  const w = side === "buy" ? row.wBuyers : row.wSellers;
  return w.filter((b) => !stock.includes(b)).length;
}

function sideList(row: ComboRow, side: "buy" | "sell", withWarrants = true): string[] {
  return participants(row, side, withWarrants);
}

export function isBigHold(hold: number, avgVol: number | null): boolean {
  if (hold <= 0) return false;
  return hold >= BIG_HOLD_LOTS || (avgVol != null && avgVol > 0 && hold >= HOLD_FLOOR_LOTS && hold >= avgVol);
}

/** 「估計仍持有」檢視的門檻,與匯出端相同:≥ holdMin 張,或 ≥ 20 日均量(且 ≥ 20 張)。 */
export function holdQualifies(hold: number, avgVol: number | null, holdMin = 100): boolean {
  return hold >= holdMin || isBigHold(hold, avgVol);
}

/** withWarrants =「含權證」開關:開著時,分點今天的權證進出(只限算進今天的)也算參與,主分點只買認購也符合「主分點買超」。 */
export function filterRows(rows: ComboRow[], set: BranchSet, side: Side, mode: ComboMode, holdMin = 100, withWarrants = true): ComboRow[] {
  if (side === "hold") {
    return rows.filter((r) => set.branches.some((b) => holdQualifies(r.cells[b]?.hold ?? 0, r.avgVol, holdMin)));
  }
  return rows.filter((r) => {
    const list = sideList(r, side, withWarrants);
    switch (mode) {
      case "anchor": return list.includes(set.anchor);
      case "anchor_plus": return list.includes(set.anchor) && list.length >= 2;
      case "all": return set.branches.every((b) => list.includes(b));
      case "any": return list.length > 0;
    }
  });
}

/** 今天這一邊的現股張數合計(買超取正、賣超取絕對值;只算選的分點)。 */
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

/** 今天這一邊算進來的權證金額(元):買方 = 認購淨買;賣方 = 認購淨賣 + 認售淨買。
 *  只算 wBuyers／wSellers(權證那天是今天);認售淨賣不算。 */
export function sideWarrantAmount(row: ComboRow, side: Side): number {
  if (side === "hold") return 0;
  let s = 0;
  for (const b of side === "buy" ? row.wBuyers : row.wSellers) {
    const w = row.warrants[b];
    if (!w) continue;
    if (side === "buy") s += w.call != null && w.call > 0 ? w.call : 0;
    else s += (w.call != null && w.call < 0 ? -w.call : 0) + (w.put != null && w.put > 0 ? w.put : 0);
  }
  return s;
}

/** 張數 × 收盤 × 1,000(元);沒有收盤 → null。 */
export function amountEst(lots: number, close: number | null): number | null {
  return close == null ? null : lots * close * 1000;
}

/** (現價 ÷ 均價 − 1) × 100;任一缺 → null。 */
export function gapPct(close: number | null, avg: number | null): number | null {
  if (close == null || avg == null || avg <= 0) return null;
  return (close / avg - 1) * 100;
}

/** 選的分點合計的均價(估):有持有、均價已知的分點依張數加權;partial = 有持有的分點裡有均價未知的。 */
export function combinedAvg(row: ComboRow, branches: string[]): { avg: number | null; partial: boolean } {
  let lots = 0, cost = 0, partial = false;
  for (const b of branches) {
    const c = row.cells[b];
    if (!c || c.hold <= 0) continue;
    if (c.avg == null) { partial = true; continue; }
    lots += c.hold;
    cost += c.hold * c.avg;
  }
  return { avg: lots > 0 ? cost / lots : null, partial };
}

export function sortRows(rows: ComboRow[], side: Side, key: SortKey, withWarrants = true, branches?: string[]): ComboRow[] {
  const amt = (r: ComboRow) => {
    const a = amountEst(sideLots(r, side), r.close);
    const w = withWarrants ? sideWarrantAmount(r, side) : 0;
    return a == null && !w ? -1 : (a ?? 0) + w;
  };
  const co = (r: ComboRow) => (side === "hold"
    ? Object.values(r.cells).filter((c) => c.hold > 0).length
    : sideList(r, side, withWarrants).length);
  const gap = (r: ComboRow) => gapPct(r.close, combinedAvg(r, branches ?? Object.keys(r.cells)).avg);
  return [...rows].sort((a, b) => {
    let d = 0;
    switch (key) {
      case "combo": d = co(b) - co(a) || amt(b) - amt(a); break;
      case "lots": d = sideLots(b, side) - sideLots(a, side); break;
      case "amount": d = amt(b) - amt(a); break;
      case "hold": d = b.holdTotal - a.holdTotal; break;
      case "gap": {
        // 現價低於均價最多的在前;沒有均價的排最後
        const ga = gap(a), gb = gap(b);
        d = ga == null && gb == null ? 0 : ga == null ? 1 : gb == null ? -1 : ga - gb;
        break;
      }
    }
    return d || a.stock_id.localeCompare(b.stock_id);
  });
}

/** 分頁徽章:今天選的分點有任何一家出現(現股買超或賣超,含權證時也算權證)的檔數。 */
export function todayCount(rows: ComboRow[], withWarrants = true): number {
  return rows.filter((r) => participants(r, "buy", withWarrants).length + participants(r, "sell", withWarrants).length > 0).length;
}

/** 元 → 「320萬」「1.2億」,帶正負號(+/−)。 */
export function fmtWan(n: number, signed = true): string {
  const abs = Math.abs(n);
  const body = abs >= 1e8 ? `${(abs / 1e8).toFixed(1)}億` : `${Math.round(abs / 1e4).toLocaleString("zh-TW")}萬`;
  return signed ? `${n > 0 ? "+" : n < 0 ? "−" : ""}${body}` : body;
}

function fmtPrice(p: number): string {
  return p.toLocaleString("zh-TW", { minimumFractionDigits: 1, maximumFractionDigits: p >= 100 ? 1 : 2 });
}

/** 均價(估)與現價差的一句話;沒有均價 → null。 */
export function avgLine(avg: number | null, close: number | null): string | null {
  if (avg == null) return null;
  const g = gapPct(close, avg);
  const head = `均價(估) ${fmtPrice(avg)}`;
  if (g == null) return head;
  if (Math.abs(g) < 0.05) return `${head} · 現價約等於均價`;
  return `${head} · 現價${g > 0 ? "高於" : "低於"}均價 ${g > 0 ? "+" : "−"}${Math.abs(g).toFixed(1)}%`;
}

export interface WarrantChip {
  text: string;
  /** 算進今天的哪一邊;null = 只列出不計(舊日期、或認售淨賣) */
  side: "buy" | "sell" | null;
}

/** 一個分點在一檔標的上的權證進出膠囊。counted=false(權證資料日不是今天)時一律標日期、不計。 */
export function warrantChips(w: WarrantCell | undefined, meta: WatchWarrantMeta | null | undefined): WarrantChip[] {
  if (!w || !meta) return [];
  const pre = meta.counted ? "權證" : `權證分點 ${fmtMD(meta.day)}${meta.complete === false ? " 未完整" : ""}`;
  const out: WarrantChip[] = [];
  if (w.call != null) out.push({ text: `${pre} 認購 ${fmtWan(w.call)}`, side: meta.counted ? (w.call > 0 ? "buy" : "sell") : null });
  if (w.put != null) out.push({ text: `${pre} 認售 ${fmtWan(w.put)}`, side: meta.counted && w.put > 0 ? "sell" : null });
  return out;
}

/** 權證仍持有(估)的一句話(docs/51 的估算);沒有 → []。 */
export function warrantHeldLines(w: WarrantCell | undefined, meta: WatchWarrantMeta | null | undefined): string[] {
  if (!w || !meta) return [];
  const date = meta.counted && meta.data_date === meta.day ? "" : `(${fmtMD(meta.data_date)})`;
  const out: string[] = [];
  const one = (kind: string, cost: number | null, avg: number | null) => {
    if (cost == null || cost <= 0) return;
    out.push(`權證 ${kind} 仍持有(估)${date} ${fmtWan(cost, false)}${avg != null ? ` · 換算均價 ${fmtPrice(avg)}` : ""}`);
  };
  one("認購", w.callHeld, w.callAvg);
  one("認售", w.putHeld, w.putAvg);
  return out;
}

/** 權證分點比現股分點舊時的提示;沒有權證資料或同一天 → null。 */
export function warrantStaleText(index: WatchIndex): string | null {
  const w = index.warrant;
  if (!w || w.counted) return null;
  if (w.complete === false && w.day === index.as_of) {
    return `權證分點尚未完整:${fmtMD(w.day)} 權證分點有一部分還沒抓到,權證進出只列出(標「未完整」),不算進今天的同買／同賣,待下一輪更新。`;
  }
  return `權證分點資料日 ${fmtMD(w.day)},比現股分點 ${fmtMD(index.as_of)} 舊:權證進出只列出(標日期),不算進今天的同買／同賣,待下一輪更新。`;
}

/** 卡片上的權證覆蓋說明(取代沉默):這檔今天的權證沒收集到、或權證資料不是今天的完整資料 → 一句話;否則 null。 */
export function warrantCoverageLine(row: ComboRow, index: WatchIndex): string | null {
  const w = index.warrant;
  if (!w) return null;
  const asOf = fmtMD(index.as_of);
  if (w.day !== index.as_of) return `權證:${asOf} 未收集(權證分點只到 ${fmtMD(w.day)})`;
  if (w.complete === false) return `權證:${asOf} 分點尚未完整,只列出不計`;
  if (row.warrantPooled === false) return `權證:未收集(${asOf} 這檔沒有成交 ≥ 100 萬的認購／認售)`;
  return null;
}

export function fmtMD(d: string | null | undefined): string {
  if (!d) return "—";
  const m = /^\d{4}-(\d{2})-(\d{2})$/.exec(d);
  return m ? `${m[1]}/${m[2]}` : d;
}

export const PENDING_TODAY = "今天尚未匯入";
export const NO_DATA_TODAY = "今天無分點資料";
export const NOT_TOP15_TODAY = "今天未進前 15 大";

/** 當日 null 的說法:依這檔今天的狀態,不依分點。 */
export function nullTodayText(state: TodayState): string {
  return state === "pending" ? PENDING_TODAY : state === "nodata" ? NO_DATA_TODAY : NOT_TOP15_TODAY;
}

/** 單一分點在一檔上的一句話:今天 + 估計仍持有。 */
export function cellLine(c: Cell | undefined, state: TodayState = "rows"): { today: string; hold: string } {
  if (!c) return { today: state === "rows" ? "近 60 日未見" : nullTodayText(state), hold: "" };
  const today = c.net == null
    ? nullTodayText(state)
    : c.net > 0 ? `今天買超 ${c.net.toLocaleString("zh-TW")} 張`
    : c.net < 0 ? `今天賣超 ${(-c.net).toLocaleString("zh-TW")} 張`
    : "今天買賣相抵";
  const hold = c.hold > 0
    ? `估計仍持有 ${c.hold.toLocaleString("zh-TW")} 張 · 進場 ${fmtMD(c.entry)}`
    : "估計仍持有 0";
  return { today, hold };
}

/** 今日分點只匯入一部分時的提示;齊了(或舊檔沒有覆蓋資訊)→ null。 */
export function coverageText(index: WatchIndex): string | null {
  const c = index.coverage;
  if (!c || c.complete !== false || c.expected <= 0 || c.covered >= c.expected) return null;
  return `${fmtMD(index.as_of)} 分點已匯入 ${c.covered.toLocaleString("zh-TW")} / ${c.expected.toLocaleString("zh-TW")} 檔,其餘待下一輪更新;還沒匯入的股票今天的進出未知(標「尚未匯入」),不會出現在買超／賣超篩選裡。`;
}

/** 選的分點中,今天沒出現的估計仍持有列被每分點上限截掉的說明;沒截 → null。 */
export function holdCapText(index: WatchIndex, branches: string[]): string | null {
  const by = new Map(index.branches.map((b) => [b[0], b]));
  const parts: string[] = [];
  for (const name of branches) {
    const e = by.get(name);
    if (e && e[5] != null && e[5] > e[4]) parts.push(`${name} 共 ${e[5]} 檔,只列持有最多的 ${e[4]} 檔`);
  }
  return parts.length ? `今天沒進出的估計仍持有:${parts.join(";")}。` : null;
}

export const SEARCH_EMPTY = "沒有找到名稱相近的分點;清單只含近 60 個交易日出現過的分點,可換個寫法(例如只打「新店」)。";

export function emptyText(side: Side, mode: ComboMode, asOf: string | null): string {
  if (!asOf) return "還沒有分點資料。";
  if (side === "hold") return "選的分點近 60 個交易日沒有估計仍持有達門檻(≥ 100 張或 ≥ 20 日均量)的股票。";
  return `${fmtMD(asOf)} 沒有符合「${modeLabel(mode, side)}」的股票。可以換成「任一分點${SIDE_LABEL[side]}」或加入其他分點。`;
}
