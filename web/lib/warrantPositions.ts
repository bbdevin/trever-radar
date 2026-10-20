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
  /** 進場日超過 20 天時,張數較小的其餘日子併成這一段(n 天、合計張數／成本、起訖)。 */
  buy_days_rest?: BuyDaysRest;
};

export type BuyDay = [string, number, number, number | null];
export type BuyDaysRest = { n: number; lots: number; cost: number; first: string; last: string };

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
export function entryLine(days: BuyDay[] | undefined, rest?: BuyDaysRest): string | null {
  if (!days || days.length === 0) return null;
  if (days.length <= ENTRY_INLINE_MAX && !rest) {
    return `進場 ${days.map(([d, lots]) => `${fmtMD(d)} ${lots.toLocaleString("zh-TW")} 張`).join(" · ")}`;
  }
  const n = days.length + (rest?.n ?? 0);
  const first = rest && rest.first < days[0][0] ? rest.first : days[0][0];
  const lastDay = days[days.length - 1][0];
  const last = rest && rest.last > lastDay ? rest.last : lastDay;
  return `${fmtMD(first)} 起 共 ${n} 天，最近 ${fmtMD(last)}`;
}

/** 展開清單最後一列:「其餘 8 天合計 120 張 · 成本 36 萬（05/02–07/13）」 */
export function entryRestLine(rest: BuyDaysRest | undefined): string | null {
  if (!rest || rest.n <= 0) return null;
  return `其餘 ${rest.n} 天合計 ${rest.lots.toLocaleString("zh-TW")} 張 · 成本 ${fmtMoneyAbs(rest.cost)}（${fmtMD(rest.first)}–${fmtMD(rest.last)}）`;
}

export const ENTRY_NOTE = "進場日列的是仍持有的部分：平均成本法沒有先進先出，每次賣超把每個買超日的剩餘張數等比例縮小。";
export const ENTRY_CAP_NOTE = "超過 20 個進場日時只逐日列張數最大的 20 天，其餘併成一列合計。";

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
  // 百分比的分母是估得出值的成本;只估到一部分時標「(部分)」,不讓它看起來像整筆成本的帳面。
  const partial = pct && agg.cost_valued != null && agg.cost_valued < agg.cost ? "(部分)" : "";
  return `持有(估) ${fmtMoneyAbs(agg.cost).replace(" ", "")} · ${pct ? `${pct}${partial}` : "未估值"}`;
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
  buy_days_rest?: BuyDaysRest;
};

/**
 * 一種(認購或認售)的一邊:帳面為負(down,最差在前,估不出值的接在最後)或帳面為正
 * (up,最好在前,不含估不出值的)。rows 最多 max_rows_per_side 列,total 是這一邊門檻內全部筆數。
 * excluded_self(2026-10-20 起匯出端才有):這一邊被排除的自家發行筆數;缺鍵 = 舊檔,只有整種合計。
 */
export type ScreenSide = { rows: ScreenRow[]; total: number; excluded_self?: number };
export type ScreenDir = "down" | "up";
export type ScreenBucket = { excluded_self: number; down: ScreenSide; up: ScreenSide };

export type ScreenPayload = {
  data_date: string | null;
  window_from: string | null;
  min_cost: number;
  max_rows_per_side: number;
  kinds: Record<WarrantKindKey, ScreenBucket>;
};

export const SCREEN_FILE_VERSION = 3;

function sideOf(raw: unknown): ScreenSide {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return { rows: [], total: 0 };
  const s = raw as Partial<ScreenSide>;
  const rows = Array.isArray(s.rows) ? (s.rows as ScreenRow[]) : [];
  const out: ScreenSide = { rows, total: typeof s.total === "number" ? s.total : rows.length };
  if (typeof s.excluded_self === "number") out.excluded_self = s.excluded_self;
  return out;
}

function bucketOf(raw: unknown): ScreenBucket {
  const b = raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {};
  return {
    excluded_self: typeof b.excluded_self === "number" ? b.excluded_self : 0,
    down: sideOf(b.down),
    up: sideOf(b.up),
  };
}

/**
 * 只收 v3(認購／認售各一份、每份再分帳面為負／為正);v2(只有帳面最差的前 400,為正的大多被截掉)
 * 與 v1 混排的舊檔視同沒有,畫面顯示「等下一次匯出」。
 */
export function normalizeScreening(raw: unknown): ScreenPayload | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const p = raw as Partial<ScreenPayload> & { version?: unknown; definitions_version?: unknown; kinds?: Record<string, unknown> };
  if (p.version !== SCREEN_FILE_VERSION || p.definitions_version !== WPOS_VERSION || !p.kinds || typeof p.kinds !== "object") return null;
  return {
    data_date: typeof p.data_date === "string" ? p.data_date : null,
    window_from: typeof p.window_from === "string" ? p.window_from : null,
    min_cost: typeof p.min_cost === "number" ? p.min_cost : 0,
    max_rows_per_side: typeof p.max_rows_per_side === "number" ? p.max_rows_per_side : 0,
    kinds: { call: bucketOf(p.kinds.call), put: bucketOf(p.kinds.put) },
  };
}

export const SCREEN_DIR_LABEL: Record<ScreenDir, string> = { down: "帳面為負", up: "帳面為正" };

export type ScreenSort = "pct" | "unrealized" | "cost" | "recent";
/** 排序選項兩邊共用;帳面 % ／金額在「為負」由差到好、在「為正」由好到差。 */
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

/** 帳面為正的門檻(%,與為負那邊對稱):0 = 不限;20 = 帳面 +20% 或更高。 */
export const SCREEN_GAIN_STEPS: { key: number; label: string }[] = [
  { key: 0, label: "不限" },
  { key: 10, label: "帳面 +10% 以上" },
  { key: 20, label: "帳面 +20% 以上" },
  { key: 40, label: "帳面 +40% 以上" },
];

export const SCREEN_STEPS: Record<ScreenDir, { key: number; label: string }[]> = {
  down: SCREEN_LOSS_STEPS,
  up: SCREEN_GAIN_STEPS,
};

/** 切換方向時門檻回到該邊的預設(−20 / +20)。 */
export const SCREEN_DEFAULT_PCT: Record<ScreenDir, number> = { down: -20, up: 20 };

/** pct:帳面門檻,帶號;為負那邊 ≤ pct、為正那邊 ≥ pct;0 = 不限。 */
export type ScreenFilter = { kind: WarrantKindKey; dir: ScreenDir; pct: number; minCost: number; sort: ScreenSort };
export const DEFAULT_SCREEN_FILTER: ScreenFilter = { kind: "call", dir: "down", pct: -20, minCost: 5_000_000, sort: "pct" };

/** 換方向:門檻換成那一邊的預設,其餘(種類、排序)保留。 */
export function withScreenDir(f: ScreenFilter, dir: ScreenDir): ScreenFilter {
  return f.dir === dir ? f : { ...f, dir, pct: SCREEN_DEFAULT_PCT[dir] };
}

/**
 * 篩選＋排序(rows 是同一邊的清單)。帳面門檻只對估得出值的列生效:
 * - 為負:估不出的列(全部到期／無價)在門檻 0 時保留並排最後,門檻 < 0 時不列(不能宣稱它帳面多差);
 *   帳面 > 0 的列不列(防禦:v3 檔本來就分開)。
 * - 為正:只列帳面 > 0 的估得出值列;門檻 > 0 時 ≥ 門檻。
 */
export function filterScreenRows(rows: ScreenRow[], f: ScreenFilter): ScreenRow[] {
  const up = f.dir === "up";
  const picked = rows.filter((r) => {
    if (r.kind !== f.kind || r.lots <= 0 || r.cost < f.minCost) return false;
    const p = r.unrealized_pct;
    if (up) return p != null && p > 0 && p >= f.pct;
    if (p != null && p > 0) return false;
    if (f.pct < 0) return p != null && p <= f.pct;
    return true;
  });
  const valued = (r: ScreenRow) => (r.unrealized_pct == null ? 1 : 0);
  const s = up ? -1 : 1;   // 為正那邊:帳面 % ／金額由高到低
  const cmp: Record<ScreenSort, (a: ScreenRow, b: ScreenRow) => number> = {
    pct: (a, b) => valued(a) - valued(b) || s * ((a.unrealized_pct ?? 0) - (b.unrealized_pct ?? 0)) || b.cost - a.cost,
    unrealized: (a, b) => valued(a) - valued(b) || s * ((a.unrealized ?? 0) - (b.unrealized ?? 0)) || b.cost - a.cost,
    cost: (a, b) => b.cost - a.cost || s * ((a.unrealized_pct ?? 0) - (b.unrealized_pct ?? 0)),
    recent: (a, b) => (b.last_buy_date ?? "").localeCompare(a.last_buy_date ?? "") || b.cost - a.cost,
  };
  return [...picked].sort((a, b) => cmp[f.sort](a, b) || a.branch_name.localeCompare(b.branch_name, "zh-TW") || a.underlying_id.localeCompare(b.underlying_id));
}

/**
 * 「N 筆符合（檔內只保留帳面最差的前 400 / 共 M 筆，門檻與排序只在這 400 筆內）；另有 X 筆自家發行占過半未列」
 * 截斷訊息只在匯出端那一邊真的截掉時出現(total > rows.length)。
 * 自家發行筆數:檔裡有這一邊自己的數(side.excluded_self)就只講這一邊;舊檔只有整種合計,
 * 照實說是兩邊合計(2026-10-20:以前兩邊都顯示同一個合計,讀起來像是這一邊被排除的)。
 */
export function screenSummary(shown: number, bucket: ScreenBucket, dir: ScreenDir): string {
  const side = bucket[dir];
  const cut = side.total > side.rows.length
    ? `（檔內只保留帳面${dir === "up" ? "最高" : "最差"}的前 ${side.rows.length} / 共 ${side.total} 筆，門檻與排序只在這 ${side.rows.length} 筆內）`
    : "";
  const perSide = typeof side.excluded_self === "number";
  const n = perSide ? side.excluded_self! : bucket.excluded_self;
  const self = n > 0
    ? `；另有 ${n} 筆自家發行占過半（發行商造市／避險）未列${perSide ? "" : "（帳面為負、為正兩邊合計）"}`
    : "";
  return `${shown} 筆符合${cut}${self}`;
}

/** 沒有符合的列時的說明(每邊各一句)。 */
export function screenEmptyText(dir: ScreenDir): string {
  const head = dir === "up" ? "沒有帳面估算為正、符合門檻的券商 × 標的。" : "沒有帳面估算為負、符合門檻的券商 × 標的。";
  return `${head}涵蓋已匯入權證池、每檔權證只有前 15 大分點；沒有資料不代表沒有持有。`;
}

/**
 * 篩選狀態 ↔ 網址參數(wk / wdir / wpct / wsort),返回鍵才不會丟掉;不認得的值回預設。
 * wpct 只收該方向的門檻(wdir=up&wpct=-20 → 回到為正的預設)。
 */
export function screenFilterFromParams(params: { get(name: string): string | null }): ScreenFilter {
  const kind = params.get("wk");
  const dir: ScreenDir = params.get("wdir") === "up" ? "up" : "down";
  const pctRaw = params.get("wpct");
  const pct = pctRaw == null || pctRaw === "" ? NaN : Number(pctRaw);
  const sort = params.get("wsort");
  return {
    ...DEFAULT_SCREEN_FILTER,
    kind: kind === "put" ? "put" : "call",
    dir,
    pct: SCREEN_STEPS[dir].some((s) => s.key === pct) ? pct : SCREEN_DEFAULT_PCT[dir],
    sort: SCREEN_SORTS.some((s) => s.key === sort) ? (sort as ScreenSort) : DEFAULT_SCREEN_FILTER.sort,
  };
}

/** 預設值不寫(為負、該方向的預設門檻、認購、帳面 %)。 */
export function screenFilterToParams(f: ScreenFilter): Record<string, string | null> {
  return {
    wk: f.kind === DEFAULT_SCREEN_FILTER.kind ? null : f.kind,
    wdir: f.dir === DEFAULT_SCREEN_FILTER.dir ? null : f.dir,
    wpct: f.pct === SCREEN_DEFAULT_PCT[f.dir] ? null : String(f.pct),
    wsort: f.sort === DEFAULT_SCREEN_FILTER.sort ? null : f.sort,
  };
}

/** /branch 離開「仍持有(估)」檢視時要清掉的網址參數。 */
export const SCREEN_PARAM_KEYS = ["wk", "wdir", "wpct", "wsort"] as const;

export const SCREEN_LEAD =
  "近 120 個交易日內，權證仍持有成本（估）達 500 萬以上的券商 × 標的，分帳面為負（由差到好）與帳面為正（由高到低）兩份清單。"
  + "同一家券商可能是很多客戶的合計；帳面正負不代表之後會怎樣。";
