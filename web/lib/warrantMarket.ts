/**
 * /branch「權證分點異動」全市場資料的載入(docs/51 §3.5,2026-10-25)。
 *
 * 以前分頁一進站就抓整份 branches/warrant_branches.json(2026-10-22 正式檔 21.6 MB,九成是逐檔
 * breakdown),抓完之前與抓失敗時都顯示「此區間內無淨買賣超 500 萬以上之權證大戶」——使用者
 * 回報「近 1、2 日都沒有資訊」就是手機上還沒下載完。現在:
 *   - 只抓目前區間的 warrant_branches_{tf}.json(列不含 breakdown,1d 約 6 KB);
 *   - 點列展開時才抓該股 warrant-stock-details/{id}.breakdown.json 取逐檔明細;
 *   - 新檔 404(程式碼先於下一次 VPS 匯出上線)才退回舊的全市場檔,一次填滿五個區間;
 *   - 載入中／失敗／真的沒有資料是三種不同狀態,失敗不再假裝成「無資料」。
 */

export const MARKET_TIMEFRAMES = ["1d", "2d", "5d", "30d", "120d"] as const;
export type MarketTimeframe = (typeof MARKET_TIMEFRAMES)[number];

export type MarketBreakdown = {
  warrant_id: string;
  warrant_name: string;
  kind: "call" | "put" | string;
  net_lots: number;
  net_amount: number;
};

export type MarketRow = {
  branch_name: string;
  underlying_id: string;
  underlying_name: string;
  net_amount: number;
  /** 只有舊的全市場檔內嵌;新的區間檔沒有,展開時另抓。 */
  breakdown?: MarketBreakdown[];
};

export type MarketTfState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; data_date: string | null; rows: MarketRow[] };

/** 最小的 fetch 介面(測試可注入假的)。 */
export type FetchLike = (path: string) => Promise<{ ok: boolean; status: number; json(): Promise<unknown> }>;

export const marketTfPath = (tf: MarketTimeframe) => `/data/branches/warrant_branches_${tf}.json`;
export const MARKET_LEGACY_PATH = "/data/branches/warrant_branches.json";
export const breakdownPath = (stockId: string) =>
  `/data/branches/warrant-stock-details/${encodeURIComponent(stockId)}.breakdown.json`;

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const dateOrNull = (v: unknown) => (typeof v === "string" && ISO_DATE.test(v) ? v : null);

/** 區間檔 {version:1, threshold, data_date, timeframe, rows};格式不對回 null(當成載入失敗,不是「無資料」)。 */
export function parseMarketTimeframe(payload: unknown, tf: MarketTimeframe): { data_date: string | null; rows: MarketRow[] } | null {
  if (!isObj(payload) || payload.version !== 1 || payload.timeframe !== tf || !Array.isArray(payload.rows)) return null;
  return { data_date: dateOrNull(payload.data_date), rows: payload.rows as MarketRow[] };
}

/**
 * 舊全市場檔:v1 wrapper {version:1, data_date, timeframes} 或更舊的裸 mapping(不替它捏造資料日)。
 * 不是物件 → null(載入失敗)。
 */
export function parseLegacyMarket(payload: unknown): { data_date: string | null; timeframes: Record<MarketTimeframe, MarketRow[]> } | null {
  if (!isObj(payload)) return null;
  const wrapped = payload.version === 1 && "timeframes" in payload;
  const src = wrapped ? payload.timeframes : payload;
  if (!isObj(src)) return null;
  const timeframes = Object.fromEntries(
    MARKET_TIMEFRAMES.map((tf) => [tf, Array.isArray(src[tf]) ? (src[tf] as MarketRow[]) : []]),
  ) as Record<MarketTimeframe, MarketRow[]>;
  return { data_date: wrapped ? dateOrNull(payload.data_date) : null, timeframes };
}

export type MarketLoadResult =
  | { kind: "tf"; tf: MarketTimeframe; data_date: string | null; rows: MarketRow[] }
  | { kind: "legacy"; data_date: string | null; timeframes: Record<MarketTimeframe, MarketRow[]> };

/**
 * 載入器:load(tf) 抓該區間檔;只有 404 才退回舊全市場檔(同一個 promise 共用,失敗後可重試)。
 * 其他錯誤(500、斷線、格式錯)一律 reject,畫面顯示錯誤＋重試。
 */
export function createMarketLoader(fetchJson: FetchLike) {
  let legacy: Promise<MarketLoadResult> | null = null;
  const loadLegacy = () => {
    if (!legacy) {
      const p = (async (): Promise<MarketLoadResult> => {
        const res = await fetchJson(MARKET_LEGACY_PATH);
        if (!res.ok) throw new Error(`warrant_branches.json ${res.status}`);
        const parsed = parseLegacyMarket(await res.json());
        if (!parsed) throw new Error("warrant_branches.json 格式錯誤");
        return { kind: "legacy", ...parsed };
      })();
      legacy = p;
      p.catch(() => { if (legacy === p) legacy = null; });
    }
    return legacy;
  };
  return async function load(tf: MarketTimeframe): Promise<MarketLoadResult> {
    const res = await fetchJson(marketTfPath(tf));
    if (res.status === 404) return loadLegacy();
    if (!res.ok) throw new Error(`warrant_branches_${tf}.json ${res.status}`);
    const parsed = parseMarketTimeframe(await res.json(), tf);
    if (!parsed) throw new Error(`warrant_branches_${tf}.json 格式錯誤`);
    return { kind: "tf", tf, ...parsed };
  };
}

/** 把一次載入結果併進各區間狀態。舊檔一次填滿五個區間;已經 ready 的區間不被舊檔蓋掉。 */
export function applyMarketResult(
  prev: Partial<Record<MarketTimeframe, MarketTfState>>,
  result: MarketLoadResult,
): Partial<Record<MarketTimeframe, MarketTfState>> {
  if (result.kind === "tf") {
    return { ...prev, [result.tf]: { status: "ready", data_date: result.data_date, rows: result.rows } };
  }
  const next = { ...prev };
  for (const tf of MARKET_TIMEFRAMES) {
    if (next[tf]?.status !== "ready") next[tf] = { status: "ready", data_date: result.data_date, rows: result.timeframes[tf] };
  }
  return next;
}

/** {id}.breakdown.json 的 timeframe → 券商 → 逐檔明細。 */
export type StockBreakdowns = Record<string, Record<string, MarketBreakdown[]>>;

/**
 * 抓回來的明細檔怎麼處理:
 *   ok    = 資料日與畫面上的區間檔相同,直接用;
 *   stale = 檔本身沒問題,但資料日不同(畫面載入後 VPS 又部署了一次)——頁面要重抓區間檔,
 *           並把這份明細存在**它自己的**資料日底下,區間檔換成同一天後就直接命中;
 *   bad   = 格式錯。
 * 不論哪種,畫面都不會把兩個資料日的列與明細拼在一起(快取鍵含資料日)。
 */
export type BreakdownFetchResult =
  | { kind: "ok"; timeframes: StockBreakdowns }
  | { kind: "stale"; data_date: string | null; timeframes: StockBreakdowns }
  | { kind: "bad" };

export function classifyStockBreakdowns(payload: unknown, stockId: string, dataDate: string | null): BreakdownFetchResult {
  if (!isObj(payload) || payload.version !== 1 || payload.stock_id !== stockId || !isObj(payload.timeframes)) return { kind: "bad" };
  const fileDate = (payload.data_date ?? null) as unknown;
  if (fileDate !== null && typeof fileDate !== "string") return { kind: "bad" };
  const timeframes = payload.timeframes as StockBreakdowns;
  return fileDate === dataDate ? { kind: "ok", timeframes } : { kind: "stale", data_date: fileDate, timeframes };
}

/** 明細快取鍵:資料日 + 股號(不同資料日的明細絕不互用)。 */
export const breakdownKey = (dataDate: string | null, stockId: string) => `${dataDate}|${stockId}`;

export type BreakdownEntry = "loading" | "error" | StockBreakdowns;

/**
 * 某一列此刻的明細:內嵌(舊檔)直接用;否則看該股的明細快取。
 * undefined = 還沒抓(點了才抓)。該股檔裡找不到這家 → [](不是載入中)。
 */
export function rowBreakdown(
  row: MarketRow,
  tf: MarketTimeframe,
  entry: BreakdownEntry | undefined,
): MarketBreakdown[] | "loading" | "error" | undefined {
  if (row.breakdown) return row.breakdown;
  if (entry === undefined || entry === "loading" || entry === "error") return entry;
  return entry[tf]?.[row.branch_name] ?? [];
}
