import type {
  FuturesAnomaly,
  FuturesContract,
  FuturesInfo,
  FuturesVolumeAnomalyEntry,
  FuturesVolumeAnomalyMeta,
  ReasonItem,
} from "@/lib/types";

/**
 * 個股期貨存在狀態的三態判定(這個功能的重點)。
 *
 * - "unknown"：payload 完全沒有 `futures` 鍵——我們還沒 import-futures 過,
 *   不知道答案,不可以顯示成「沒有期貨」。
 * - "none"：`futures.contracts` 是空陣列——TAIFEX 完整官方清單截至
 *   `asOf` 這天確實不含這檔,是一個帶日期的正面主張。
 * - "has"：`futures.contracts` 非空——這檔股票有對應的個股期貨/選擇權契約。
 *
 * 把這個判斷抽成純函式(同 ReasonPill.tsx 的 isChipStrategyCode),因為
 * unknown 和 none 一旦被同一段 JSX 條件式不小心揉在一起,使用者會被告知
 * 一件假的事——「還沒匯入」被讀成「已確認沒有」。
 */
export type FuturesState =
  | { kind: "unknown" }
  | { kind: "none"; asOf: string }
  | { kind: "has"; asOf: string; contracts: FuturesContract[] };

export function futuresState(futures: FuturesInfo | null | undefined): FuturesState {
  if (!futures) return { kind: "unknown" };
  if (futures.contracts.length === 0) return { kind: "none", asOf: futures.list_as_of };
  return { kind: "has", asOf: futures.list_as_of, contracts: futures.contracts };
}

/* ------------------------------------------------------------------ *
 * 成交量異常(docs/38 §7)的呈現判斷。
 *
 * 全部抽成純函式的理由同上:這一節的每一條規則都是「不可以顯示什麼」,
 * 而「不可以」沒辦法靠讀 JSX 驗證。以下四條被測試鎖住:
 *   §7.5  市場層級鍵的三態不得塌成兩態。
 *   §7.1 / §7.4  `oi_change` 缺鍵 → 整列不顯示(不是 0、不是破折號)。
 *   §5 / §7.5  不排名:不算比率、不給名次,順序原封不動照 payload。
 *   §0 / §7.10  單位是契約不是股票,同一檔的兩個契約都要活下來。
 * ------------------------------------------------------------------ */

/** 口數的千分位;單位字(口)由呼叫端排版,不混進數字。 */
export function fmtLotsAbs(n: number): string {
  return n.toLocaleString("zh-TW");
}

/** 未平倉變化是有號的量,`0` 顯示為 `0`(它是一個真的觀測,不是缺值)。 */
export function fmtLotsSigned(n: number): string {
  const s = Math.abs(n).toLocaleString("zh-TW");
  return n > 0 ? `+${s}` : n < 0 ? `-${s}` : "0";
}

/**
 * 異常區塊要顯示的事實列。**只是把 payload 裡的整數換成字串**——
 * 沒有除法、沒有差值、沒有名次。`window_days` 從區塊讀進標籤(§7.10),
 * `oi_change` 缺鍵時這裡就少一列(§7.1),呼叫端不需要知道它可能缺。
 */
export interface FuturesAnomalyFact {
  key: "today" | "window_max" | "window_median" | "oi_change";
  label: string;
  value: string;
  unit: string;
}

export function anomalyFacts(a: FuturesAnomaly): FuturesAnomalyFact[] {
  const days = fmtLotsAbs(a.window_days);
  const facts: FuturesAnomalyFact[] = [
    { key: "today", label: "今日一般時段", value: fmtLotsAbs(a.today), unit: "口" },
    { key: "window_max", label: `前 ${days} 個比較日最高`, value: fmtLotsAbs(a.window_max), unit: "口" },
    { key: "window_median", label: `前 ${days} 個比較日中位數`, value: fmtLotsAbs(a.window_median), unit: "口" },
  ];
  // 缺鍵就是缺鍵:不補 0、不補破折號、不加一句「未公布」(§7.1)。
  if (a.oi_change !== undefined) {
    facts.push({ key: "oi_change", label: "未平倉較前日", value: fmtLotsSigned(a.oi_change), unit: "口" });
  }
  return facts;
}

/** 名單上的一列。刻意沒有 rank / position / score / ratio 這類鍵(§5、§7.5)。 */
export interface FuturesAnomalyRow {
  stockId: string;
  /** 解析不到股名時為 null——顯示 id 本身,不編一個標籤出來。 */
  name: string | null;
  code: string;
  facts: FuturesAnomalyFact[];
  reasons: ReasonItem[];
  risks: ReasonItem[];
}

/**
 * 市場層級名單的三態(§7.5)。缺鍵與空陣列**不同**:
 * 前者沒有主張,後者是一個帶日期的正面主張。
 *
 * `computed-empty` 帶著 `windowDays`(§7.11):空名單裡一個 `anomaly` 區塊都沒有,
 * 而 §7.10 不准在前端寫死 60,所以那個數字只能來自 payload 的 `_meta` 鍵。
 * 拿不到時是 `null`——那就少講比較窗口,**不是**退回一個寫死的 60,因為一個寫死
 * 的 60 會變成第二個不受 §3.5 管束的真相。
 */
export type FuturesAnomalyMarketState =
  | { kind: "not-computed" }
  | { kind: "computed-empty"; dataDate: string; windowDays: number | null }
  | { kind: "listed"; dataDate: string; rows: FuturesAnomalyRow[] };

export function futuresAnomalyMarketState(
  entries: FuturesVolumeAnomalyEntry[] | null | undefined,
  dataDate: string,
  nameById?: ReadonlyMap<string, string>,
  meta?: FuturesVolumeAnomalyMeta | null,
): FuturesAnomalyMarketState {
  if (!entries) return { kind: "not-computed" };
  if (entries.length === 0) {
    return { kind: "computed-empty", dataDate, windowDays: meta?.window_days ?? null };
  }
  // 順序原封不動(payload 已依 today − window_max 遞減排好);不排序、不去重。
  const rows = entries.map((e) => ({
    stockId: e.stock_id,
    name: nameById?.get(e.stock_id) ?? null,
    code: e.code,
    facts: anomalyFacts(e.anomaly),
    reasons: e.reasons,
    risks: e.risks,
  }));
  return { kind: "listed", dataDate, rows };
}

/**
 * 「算過了、今天沒有契約舉旗」那一句(§7.5 第二態)。
 *
 * 它**不在元件裡**的理由與這個檔案其他函式相同:句子裡有一個數字,而那個數字
 * 唯一合法的來源是 payload(§7.10)。寫在 JSX 裡沒有東西擋得住有人直接打一個 60;
 * 寫在這裡,`futures.test.ts` 餵 20 進來就會抓到。
 * `windowDays` 是 null(payload 沒給)時整段子句拿掉,句子照樣是一個帶日期的
 * 正面主張,只是少講比較基準——同 §7.1 的習慣:缺值就是缺值,不編一個數字上去。
 */
export function anomalyEmptyStateText(
  state: { dataDate: string; windowDays: number | null },
): string {
  const high = state.windowDays === null
    ? "創新高"
    : `創 ${state.windowDays} 個比較日新高`;
  return `${state.dataDate} 已完成計算:今日沒有契約的一般時段成交量${high}。`;
}

/**
 * 個股頁:契約裡帶旗標的那些。**不依股票去重**,1565 的 MYF 與 OMF
 * 同一天都舉旗時兩個都要出現(§7.10)。
 */
export type FlaggedContract = FuturesContract & { anomaly: FuturesAnomaly };

export function flaggedContracts(contracts: FuturesContract[]): FlaggedContract[] {
  return contracts.filter((c): c is FlaggedContract => c.anomaly !== undefined);
}
