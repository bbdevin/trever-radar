// 個股權證分頁:券商排行 + 對齊 K 線的逐日買賣超(2026-10-02)。
// 執行測試: node --test web/lib/warrantBranches.test.ts
//
// 認購與認售方向相反——買認售是看空。把兩者混成一個「淨買超」,一個大買認售的
// 券商會被排進「買超最多」、看起來在做多。所以排行與圖都依種類計算,不混。

/** "all" = 認購＋認售合計(使用者 2026-10-02 選擇的預設顯示)。 */
export type WarrantKind = "call" | "put" | "all";

export type BreakdownLite = { kind: string; net_amount: number };
export type BranchRowLite = { branch_name: string; net_amount: number; breakdown?: BreakdownLite[] };

/** shard.daily 的一列:[日期, 認購金額, 認售金額](元)。 */
export type DailyEntry = [string, number, number];

/** 某券商在某種權證上的淨額:由逐檔明細依種類加總。 */
export function kindNet(row: BranchRowLite, kind: WarrantKind): number {
  if (kind === "all") return row.net_amount;
  return (row.breakdown ?? []).reduce((s, b) => (b.kind === kind ? s + b.net_amount : s), 0);
}

export type RankedBranch = { branch_name: string; amount: number };

/**
 * 買超或賣超前 N 名(依該種權證的淨額)。0 元的券商不進任一邊。
 *
 * 已知邊界:shard 只收「總淨額 ≥ 100 萬」的券商;一個認購 +500 萬、認售 −500 萬
 * 的券商總額為 0 不會出現在這裡。那是匯出端的門檻,這裡不假裝看得到它。
 */
export function rankBranches(
  rows: BranchRowLite[], kind: WarrantKind, side: "buy" | "sell", n = 10,
): RankedBranch[] {
  const scored = rows.map((r) => ({ branch_name: r.branch_name, amount: kindNet(r, kind) }));
  const picked = side === "buy" ? scored.filter((r) => r.amount > 0) : scored.filter((r) => r.amount < 0);
  picked.sort((a, b) => (side === "buy" ? b.amount - a.amount : a.amount - b.amount));
  return picked.slice(0, n);
}

/** K 線副圖用的序列(t 對齊 candles)。沒有逐日資料 → undefined(不是空陣列)。 */
export function branchSeries(
  daily: Record<string, DailyEntry[]> | undefined,
  branch: string | null,
  kind: WarrantKind,
): { t: string; net: number }[] | undefined {
  if (!daily || !branch) return undefined;
  const rows = daily[branch];
  if (!rows?.length) return undefined;
  // 缺的日子不補 0:那天該券商不在任何一檔權證的前 15 大,不是確定沒交易。
  return rows.map(([t, call, put]) => ({ t, net: kind === "call" ? call : kind === "put" ? put : call + put }));
}

/**
 * 副圖用的序列換成「萬」為單位:圖表座標軸直接印序列的數值,以元餵進去軸上會是
 * 「8M」(= 800 萬),而台股讀者看的是萬(參考圖的軸是 0–800)。
 */
export function toWanSeries(series: { t: string; net: number }[] | undefined) {
  return series?.map((p) => ({ t: p.t, net: Math.round(p.net / 1000) / 10 }));
}

/** 已經是「萬」的數值 →「+1,234萬」(副圖標題用)。 */
export function fmtWanValueSigned(wan: number): string {
  const s = Math.round(Math.abs(wan)).toLocaleString("zh-TW");
  return wan > 0 ? `+${s}萬` : wan < 0 ? `-${s}萬` : "0萬";
}

/** 金額(元)→「+1,234萬」。副圖標題與排行共用,單位一致。 */
export function fmtWanSigned(n: number): string {
  const wan = Math.round(Math.abs(n) / 10000).toLocaleString("zh-TW");
  return n > 0 ? `+${wan}萬` : n < 0 ? `-${wan}萬` : "0萬";
}

export type BranchHit = { branch_name: string; code: string | null; amount: number };

/**
 * 「搜尋券商」:依名稱或代號找這段期間任何一家券商(不只排行前 10)。
 * 依該種權證淨額的絕對值排序;0 元的也列出(它在另一種權證可能有動作,
 * 選了之後切種類就看得到)。空查詢回空陣列。
 */
export function searchBranches(
  rows: BranchRowLite[], query: string, kind: WarrantKind,
  codes: Record<string, string> = {}, limit = 20,
): BranchHit[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  return rows
    .map((r) => ({ branch_name: r.branch_name, code: codes[r.branch_name] ?? null, amount: kindNet(r, kind) }))
    .filter((r) => r.branch_name.toLowerCase().includes(q) || (r.code ?? "").toLowerCase().includes(q))
    .sort((a, b) => Math.abs(b.amount) - Math.abs(a.amount))
    .slice(0, limit);
}

/** 預設選中的券商:目前排行的買超第一名,沒有就賣超第一名。 */
export function defaultBranch(buys: RankedBranch[], sells: RankedBranch[]): string | null {
  return buys[0]?.branch_name ?? sells[0]?.branch_name ?? null;
}
