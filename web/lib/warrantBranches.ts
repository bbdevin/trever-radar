// 個股權證分頁:券商排行 + 對齊 K 線的逐日買賣超(2026-10-02)。
// 執行測試: node --test web/lib/warrantBranches.test.ts
//
// 認購與認售方向相反——買認售是看空。把兩者混成一個「淨買超」,一個大買認售的
// 券商會被排進「買超最多」、看起來在做多。所以排行與圖都依種類計算,不混。

/** "all" = 認購＋認售合計(使用者 2026-10-02 選擇的預設顯示)。 */
export type WarrantKind = "call" | "put" | "all";

export type BreakdownLite = { kind: string; net_amount: number };

/**
 * 匯出端算好的「同券商發行」摘要(2026-10-02,可選鍵):該券商在自家集團發行的
 * 權證上的淨額(元)、占它總成交金額(絕對值)的百分比、是否為總公司席位。
 * 發行商依規定為自家權證造市,造市／避險單走發行券商總公司,所以 hq 且占比高的
 * 列多半是造市,不是主力買賣。舊分片沒有這個鍵。
 */
export type SelfIssued = { net: number; pct: number; hq: boolean };

export type BranchRowLite = {
  branch_name: string;
  net_amount: number;
  breakdown?: BreakdownLite[];
  self?: SelfIssued;
};

/** shard.daily 的一列:[日期, 認購金額, 認售金額](元)。 */
export type DailyEntry = [string, number, number];

/** 某券商在某種權證上的淨額:由逐檔明細依種類加總。 */
export function kindNet(row: BranchRowLite, kind: WarrantKind): number {
  if (kind === "all") return row.net_amount;
  return (row.breakdown ?? []).reduce((s, b) => (b.kind === kind ? s + b.net_amount : s), 0);
}

/** 排行選項:excludeSelf 扣掉同券商發行的金額;minAbs 是扣完後仍要達到的門檻(元)。 */
export type RankOptions = { excludeSelf?: boolean; minAbs?: number };

/** 過半金額在自家權證才標(低占比的分公司多半只是客戶剛好買到自家權證)。 */
export const SELF_TAG_MIN_PCT = 50;

/**
 * 排行用的金額。excludeSelf 只扣「有標籤」的列(selfIssuedTag 非 null:總公司或
 * 分公司、過半金額在自家權證);一般分公司客戶剛好買到自家權證不扣,保留全額。
 * 只對「合計」有效:匯出端的同券商摘要不分認購／認售,單一種類時原值回傳。
 */
export function branchAmount(row: BranchRowLite, kind: WarrantKind, excludeSelf = false): number {
  const net = kindNet(row, kind);
  return excludeSelf && kind === "all" && row.self && selfIssuedTag(row.self) ? net - row.self.net : net;
}

export type SelfTag = { label: "發行商" | "同券商"; pct: number; hq: boolean };

/**
 * 排行列上的標籤:總公司 →「發行商」(多為發行商造市／避險);分公司 →「同券商」
 * (只陳述事實:過半金額是同集團發行的權證)。占比未過半或沒有摘要 → null。
 */
export function selfIssuedTag(self: SelfIssued | undefined): SelfTag | null {
  if (!self || self.pct < SELF_TAG_MIN_PCT) return null;
  return { label: self.hq ? "發行商" : "同券商", pct: self.pct, hq: self.hq };
}

/** 有沒有任何一列帶同券商摘要(舊分片全無 → 不顯示「排除同券商發行」開關)。 */
export function hasSelfIssued(rows: BranchRowLite[]): boolean {
  return rows.some((r) => !!r.self);
}

/**
 * 某券商在某區間的逐檔明細:舊分片內嵌在列上;新分片拆到 {id}.breakdown.json。
 * 回 null = 拆檔還沒載入(或載入失敗),不是「沒有明細」。
 */
export function resolveBreakdown<T>(
  row: { branch_name: string; breakdown?: T[] } | null,
  split: Record<string, Record<string, T[]>> | null,
  tf: string,
): T[] | null {
  if (!row) return null;
  if (row.breakdown) return row.breakdown;
  if (!split) return null;
  return split[tf]?.[row.branch_name] ?? [];
}

export type RankedBranch = { branch_name: string; amount: number; self?: SelfIssued };

/**
 * 買超或賣超前 N 名(依該種權證的淨額)。0 元的券商不進任一邊。
 *
 * 已知邊界:shard 只收「總淨額 ≥ 100 萬」的券商;一個認購 +500 萬、認售 −500 萬
 * 的券商總額為 0 不會出現在這裡。那是匯出端的門檻,這裡不假裝看得到它。
 */
export function rankBranches(
  rows: BranchRowLite[], kind: WarrantKind, side: "buy" | "sell", n = 10,
  { excludeSelf = false, minAbs = 0 }: RankOptions = {},
): RankedBranch[] {
  const scored = rows.map((r) => ({
    branch_name: r.branch_name,
    amount: branchAmount(r, kind, excludeSelf),
    ...(r.self ? { self: r.self } : {}),
  })).filter((r) => Math.abs(r.amount) >= minAbs);
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
  codes: Record<string, string> = {}, limit = 20, excludeSelf = false,
): BranchHit[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  return rows
    .map((r) => ({ branch_name: r.branch_name, code: codes[r.branch_name] ?? null, amount: branchAmount(r, kind, excludeSelf) }))
    .filter((r) => r.branch_name.toLowerCase().includes(q) || (r.code ?? "").toLowerCase().includes(q))
    .sort((a, b) => Math.abs(b.amount) - Math.abs(a.amount))
    .slice(0, limit);
}

/** 手機券商列(BrokerStrip)的一格。tag = 「發行商」「同券商」標籤文字(可選)。 */
export type StripItem = { name: string; code?: string; amount: number; tone: "up" | "down"; tag?: string };

/**
 * 手機券商列:買超排行接賣超排行,順序與桌機左邊兩張表一致。buys/sells 已是
 * 目前區間、目前「排除同券商發行」狀態下的排行;排除模式下金額已扣自家權證,
 * 標籤會誤導,與排行表一樣不標(showTags = false)。
 */
export function buildStripItems(
  buys: RankedBranch[], sells: RankedBranch[], codes: Record<string, string> = {}, showTags = true,
): StripItem[] {
  const one = (r: RankedBranch, tone: "up" | "down"): StripItem => {
    const tag = showTags ? selfIssuedTag(r.self) : null;
    return {
      name: r.branch_name,
      amount: r.amount,
      tone,
      ...(codes[r.branch_name] ? { code: codes[r.branch_name] } : {}),
      ...(tag ? { tag: tag.label } : {}),
    };
  };
  return [...buys.map((r) => one(r, "up")), ...sells.map((r) => one(r, "down"))];
}

/**
 * 券商列的 ‹ › 前後切換,不繞回。current = -1(選中的券商不在列上,例如搜尋選的)
 * 時 › 從第一格開始、‹ 不動。回 null = 這個方向沒有下一格(按鈕停用)。
 */
export function stepIndex(length: number, current: number, delta: -1 | 1): number | null {
  if (length === 0) return null;
  if (current < 0) return delta > 0 ? 0 : null;
  const next = current + delta;
  return next < 0 || next >= length ? null : next;
}

/** 預設選中的券商:目前排行的買超第一名,沒有就賣超第一名。 */
export function defaultBranch(buys: RankedBranch[], sells: RankedBranch[]): string | null {
  return buys[0]?.branch_name ?? sells[0]?.branch_name ?? null;
}
