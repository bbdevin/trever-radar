// 權證分點持有估算 `wpos-avgcost-v1`(docs/51)的顯示邏輯。計算全在 pipeline
// (`radar/compute/warrant_position_est.py`);這裡只負責型別、格式、篩選與鎖定文案。
// 執行測試: node --test web/lib/warrantPositions.test.ts
//
// 文案是鎖定的(warrantPositions.test.ts 逐字比對 + 禁用詞):這是估算,不是帳戶損益;
// 券商分點不是單一個人;不寫勝率、不寫方向性字眼。
import { fmtMoney, fmtMoneyAbs } from "./branchPnl.ts";

export const WPOS_VERSION = "wpos-avgcost-v1";

export type WarrantLegEst = {
  warrant_id: string;
  lots: number;
  cost: number;
  buy_lots: number;
  sell_lots_attributed: number;
  sell_lots_unattributed: number;
  realized: number;
  status: "valued" | "expired" | "no_price" | "cost_unknown" | "closed" | string;
  avg_cost?: number;
  avg_under?: number;
  last_price?: number;
  value?: number;
  unrealized?: number;
  last_buy_date?: string;
  self?: boolean;
};

/** 一家券商在一檔標的、一種權證(認購或認售)上的加總。金額為元。 */
export type PositionAgg = {
  lots: number;
  cost: number;
  buy_lots: number;
  sell_lots_attributed: number;
  sell_lots_unattributed: number;
  realized: number;
  n_warrants: number;
  n_held: number;
  n_expired: number;
  n_no_price: number;
  n_cost_unknown: number;
  self_cost: number;
  warrants: WarrantLegEst[];
  avg_under?: number;
  cost_valued?: number;
  value?: number;
  unrealized?: number;
  unrealized_pct?: number;
  last_buy_date?: string;
  first_date?: string;
  /** 進場日拆解(仍持有的部分):[日期, 張數, 成本(元), 當日標的收盤|null],日期遞增;舊 payload 沒有。 */
  buy_days?: BuyDay[];
};

export type BuyDay = [string, number, number, number | null];

export type BranchPositions = { call?: PositionAgg; put?: PositionAgg };

/** 「2026-09-15」→「09/15」。 */
export function fmtMD(date: string): string {
  const m = /^\d{4}-(\d{2})-(\d{2})$/.exec(date);
  return m ? `${m[1]}/${m[2]}` : date;
}

/** 進場日少於等於這個數就逐日列出,否則只列起訖與天數、點開才展開。 */
export const ENTRY_INLINE_MAX = 3;

/**
 * 進場日一行字:≤ 3 天「進場 09/15 120 張 · 09/16 80 張」;更多「09/02 起 共 8 天，最近 10/07」。
 * 沒有資料(舊 payload)或沒有仍持有 → null。張數是平均成本法等比例扣減後**仍持有**的部分。
 */
export function entryLine(days: BuyDay[] | undefined): string | null {
  if (!days || days.length === 0) return null;
  if (days.length <= ENTRY_INLINE_MAX) {
    return `進場 ${days.map(([d, lots]) => `${fmtMD(d)} ${lots.toLocaleString("zh-TW")} 張`).join(" · ")}`;
  }
  return `${fmtMD(days[0][0])} 起 共 ${days.length} 天，最近 ${fmtMD(days[days.length - 1][0])}`;
}

export const ENTRY_NOTE = "進場日列的是仍持有的部分：平均成本法沒有先進先出，每次賣超把每個買超日的剩餘張數等比例縮小。";

export type WarrantPositions = {
  version: string;
  as_of: string | null;
  window_from: string | null;
  under_last?: number;
  under_last_date?: string;
  branches: Record<string, BranchPositions>;
};

export type WarrantKindKey = "call" | "put";
export const KIND_LABEL: Record<WarrantKindKey, string> = { call: "認購", put: "認售" };

const MINUS = "−";

/** 分片的 positions 鍵:缺鍵、版本不認得或結構不對 → null(畫面不出現持有估算)。 */
export function normalizePositions(raw: unknown): WarrantPositions | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const p = raw as Partial<WarrantPositions>;
  if (p.version !== WPOS_VERSION || !p.branches || typeof p.branches !== "object" || Array.isArray(p.branches)) return null;
  return {
    version: p.version,
    as_of: typeof p.as_of === "string" ? p.as_of : null,
    window_from: typeof p.window_from === "string" ? p.window_from : null,
    ...(typeof p.under_last === "number" ? { under_last: p.under_last } : {}),
    ...(typeof p.under_last_date === "string" ? { under_last_date: p.under_last_date } : {}),
    branches: p.branches as Record<string, BranchPositions>,
  };
}

export function branchPosition(pos: WarrantPositions | null, branch: string | null, kind: WarrantKindKey): PositionAgg | null {
  if (!pos || !branch) return null;
  return pos.branches[branch]?.[kind] ?? null;
}

/** 這家券商有沒有任何一邊仍持有(估)。 */
export function hasHolding(bp: BranchPositions | undefined): boolean {
  return !!bp && ((bp.call?.lots ?? 0) > 0 || (bp.put?.lots ?? 0) > 0);
}

/** 「+12.3%」「−40.0%」;null → null。 */
export function fmtPct(p: number | null | undefined): string | null {
  if (p == null || !Number.isFinite(p)) return null;
  return `${p > 0 ? "+" : p < 0 ? MINUS : ""}${Math.abs(p).toFixed(1)}%`;
}

export function fmtLots(n: number): string {
  return `${n.toLocaleString("zh-TW")} 張`;
}

export function fmtUnderPrice(p: number): string {
  return p.toLocaleString("zh-TW", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function fmtWarrantPrice(p: number): string {
  return p.toLocaleString("zh-TW", { minimumFractionDigits: 2, maximumFractionDigits: 3 });
}

/**
 * 排行列第二行(手機兩欄各約 165px,所以很短):「持有(估) 850萬 · −12.0%」;沒有持有 → null
 * (不佔一行);有持有但沒有任何一檔估得出值 → 「持有(估) 850萬 · 未估值」。
 */
export function holdingLine(agg: PositionAgg | null | undefined): string | null {
  if (!agg || agg.lots <= 0 || agg.cost <= 0) return null;
  const pct = fmtPct(agg.unrealized_pct);
  return `持有(估) ${fmtMoneyAbs(agg.cost).replace(" ", "")} · ${pct ?? "未估值"}`;
}

/** 現股相對換算均價的差距(%):(現股 ÷ 換算均價 − 1) × 100;缺一邊 → null。 */
export function underDiffPct(avgUnder: number | undefined, underLast: number | undefined): number | null {
  if (!avgUnder || !underLast || avgUnder <= 0) return null;
  return (underLast / avgUnder - 1) * 100;
}

/** 「現股 580.00，較換算均價低 8.3%」—— 只陳述位置,不給方向。 */
export function underDiffText(avgUnder: number | undefined, underLast: number | undefined): string | null {
  const d = underDiffPct(avgUnder, underLast);
  if (d == null || underLast == null) return null;
  const a = Math.abs(d).toFixed(1);
  const rel = d < -0.05 ? `較換算均價低 ${a}%` : d > 0.05 ? `較換算均價高 ${a}%` : "與換算均價相當";
  return `現股 ${fmtUnderPrice(underLast)}，${rel}`;
}

/** 帳面估算文字:「帳面估算 −480 萬（−40.0%）」;估不出 → null。 */
export function unrealizedText(agg: PositionAgg | null | undefined): string | null {
  if (!agg || agg.unrealized == null) return null;
  const pct = fmtPct(agg.unrealized_pct);
  return `帳面估算 ${fmtMoney(agg.unrealized)}${pct ? `（${pct}）` : ""}`;
}

/** 卡片底下的條件註記(依序:未估值的檔數、部分估值、找不到對應的賣超、自家發行)。 */
export function positionNotes(agg: PositionAgg): string[] {
  const out: string[] = [];
  if (agg.n_expired > 0) out.push(`${agg.n_expired} 檔已到期，仍持有的張數列入成本、不估值。`);
  if (agg.n_no_price > 0) out.push(`${agg.n_no_price} 檔近 5 個交易日沒有收盤價，不估值。`);
  if (agg.n_cost_unknown > 0) out.push(`${agg.n_cost_unknown} 檔有交易日缺權證收盤價，整檔不列入估算。`);
  if (agg.unrealized != null && agg.cost_valued != null && agg.cost_valued < agg.cost) {
    out.push(`帳面估算只涵蓋估得出值的 ${fmtMoneyAbs(agg.cost_valued)} 成本（共 ${fmtMoneyAbs(agg.cost)}）。`);
  }
  if (agg.sell_lots_unattributed > 0) {
    out.push(`另有 ${agg.sell_lots_unattributed.toLocaleString("zh-TW")} 張賣超找不到對應的買超（窗口前已持有或榜外買超），未計入。`);
  }
  if (agg.cost > 0 && agg.self_cost > 0) {
    out.push(`其中 ${Math.floor((agg.self_cost / agg.cost) * 100)}% 的成本在同券商發行的權證上，多為發行商造市／避險。`);
  }
  return out;
}

export const WPOS_HEADING = "權證持有（估算）";
export const WPOS_LEAD =
  "只用每檔權證每日前 15 大進出看得見的張數，以當日權證收盤價當成交價、平均成本法估算；"
  + "近 120 個交易日的起點視為零持股，看不見的日子視為沒交易。認購與認售分開計。";
export const WPOS_UNDER_NOTE =
  "換算現股均價＝這家券商各筆買超當天的現股收盤，以該筆買超金額加權；只是「買的那幾天現股在哪」，"
  + "不是以履約價算出的損益兩平點。";
export const WPOS_FOOTER =
  "估算不是帳戶損益；券商分點不等於單一個人；權證有時間價值，放著不動帳面也會縮水；"
  + "發行商在自家權證上的進出多為造市／避險，請看「發行商」「同券商」標籤。";
export const WPOS_FORMULA: string[] = [
  "每檔權證一腿：淨買超 N 張 → 成本 ＋＝ N × 當日權證收盤 × 1000，持有加 N；同時記下當天現股收盤。",
  "淨賣超 N 張 → 先扣手上的持有（最多扣到 0，不放空），成本與換算均價等比例扣減；超過持有的張數記為「找不到對應的買超」。",
  "帳面估算＝仍持有張數 × 最新權證收盤 × 1000 − 仍持有成本；最新收盤只取資料日當天或之前 5 個交易日內。",
  "已到期、近 5 日無收盤的權證仍列入持有與成本，但不估值；百分比只用估得出值的那部分成本當分母。",
  "換算現股均價＝Σ（每筆買超金額 × 當天現股收盤）÷ Σ 買超金額；賣超後維持不變。",
];

// ---------- 全市場「仍持有(估)」篩選清單(/branch 權證分點異動) ----------

export type ScreenRow = {
  branch_name: string;
  underlying_id: string;
  underlying_name: string;
  kind: WarrantKindKey | string;
  lots: number;
  cost: number;
  n_held: number;
  n_unvalued: number;
  self_pct: number;
  value?: number;
  unrealized?: number;
  unrealized_pct?: number;
  avg_under?: number;
  last_buy_date?: string;
  first_date?: string;
  under_last?: number;
  under_last_date?: string;
  buy_days?: BuyDay[];
};

export type ScreenPayload = {
  data_date: string | null;
  window_from: string | null;
  rows_total: number;
  excluded_self: number;
  min_cost: number;
  rows: ScreenRow[];
};

export function normalizeScreening(raw: unknown): ScreenPayload | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const p = raw as Partial<ScreenPayload> & { version?: unknown; definitions_version?: unknown };
  if (p.version !== 1 || p.definitions_version !== WPOS_VERSION || !Array.isArray(p.rows)) return null;
  return {
    data_date: typeof p.data_date === "string" ? p.data_date : null,
    window_from: typeof p.window_from === "string" ? p.window_from : null,
    rows_total: typeof p.rows_total === "number" ? p.rows_total : p.rows.length,
    excluded_self: typeof p.excluded_self === "number" ? p.excluded_self : 0,
    min_cost: typeof p.min_cost === "number" ? p.min_cost : 0,
    rows: p.rows as ScreenRow[],
  };
}

export type ScreenSort = "pct" | "unrealized" | "cost" | "recent";
export const SCREEN_SORTS: { key: ScreenSort; label: string }[] = [
  { key: "pct", label: "帳面 %" },
  { key: "unrealized", label: "帳面金額" },
  { key: "cost", label: "持有成本" },
  { key: "recent", label: "最近買超" },
];

/** 帳面門檻(%):0 = 不限;−20 = 帳面 −20% 或更差。 */
export const SCREEN_LOSS_STEPS: { key: number; label: string }[] = [
  { key: 0, label: "不限" },
  { key: -10, label: "帳面 −10% 以下" },
  { key: -20, label: "帳面 −20% 以下" },
  { key: -40, label: "帳面 −40% 以下" },
];

export type ScreenFilter = { kind: WarrantKindKey; maxPct: number; minCost: number; sort: ScreenSort };
export const DEFAULT_SCREEN_FILTER: ScreenFilter = { kind: "call", maxPct: -20, minCost: 5_000_000, sort: "pct" };

/**
 * 篩選＋排序。帳面門檻只對估得出值的列生效:估不出的列(全部到期／無價)在門檻 0
 * 時保留並排最後,門檻 < 0 時不列(不能宣稱它帳面多差)。
 */
export function filterScreenRows(rows: ScreenRow[], f: ScreenFilter): ScreenRow[] {
  const picked = rows.filter((r) => {
    if (r.kind !== f.kind || r.lots <= 0 || r.cost < f.minCost) return false;
    if (f.maxPct < 0) return r.unrealized_pct != null && r.unrealized_pct <= f.maxPct;
    return true;
  });
  const valued = (r: ScreenRow) => (r.unrealized_pct == null ? 1 : 0);
  const cmp: Record<ScreenSort, (a: ScreenRow, b: ScreenRow) => number> = {
    pct: (a, b) => valued(a) - valued(b) || (a.unrealized_pct ?? 0) - (b.unrealized_pct ?? 0) || b.cost - a.cost,
    unrealized: (a, b) => valued(a) - valued(b) || (a.unrealized ?? 0) - (b.unrealized ?? 0) || b.cost - a.cost,
    cost: (a, b) => b.cost - a.cost || (a.unrealized_pct ?? 0) - (b.unrealized_pct ?? 0),
    recent: (a, b) => (b.last_buy_date ?? "").localeCompare(a.last_buy_date ?? "") || b.cost - a.cost,
  };
  return [...picked].sort((a, b) => cmp[f.sort](a, b) || a.branch_name.localeCompare(b.branch_name, "zh-TW") || a.underlying_id.localeCompare(b.underlying_id));
}

/** 「N 筆符合；另有 M 筆發行商／同券商自家權證過半未列」 */
export function screenSummary(shown: number, payload: ScreenPayload): string {
  const self = payload.excluded_self > 0 ? `；另有 ${payload.excluded_self} 筆自家發行占過半（發行商造市／避險）未列` : "";
  return `${shown} 筆符合${self}`;
}

export const SCREEN_LEAD =
  "近 120 個交易日內，權證仍持有成本（估）達 500 萬以上的券商 × 標的，依帳面估算由差到好排。"
  + "同一家券商可能是很多客戶的合計；帳面差不代表之後會怎樣。";
