import type { FuturesContract, FuturesInfo } from "@/lib/types";

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
