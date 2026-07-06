/** 金額(元)→ 億,1 位小數 */
export function fmtE8(n: number | null | undefined): string {
  if (n == null) return "—";
  return (n / 1e8).toFixed(1) + "億";
}

/** 張數,含正負號與千分位 */
export function fmtLots(n: number | null | undefined): string {
  if (n == null) return "—";
  const s = Math.abs(n).toLocaleString("zh-TW");
  return n > 0 ? `+${s}` : n < 0 ? `-${s}` : "0";
}

export function fmtPct(n: number | null | undefined): string {
  if (n == null) return "—";
  const arrow = n > 0 ? "▲" : n < 0 ? "▼" : "";
  return `${arrow}${Math.abs(n).toFixed(2)}%`;
}

/** 台股慣例:紅漲綠跌 */
export function chgClass(n: number | null | undefined): string {
  if (n == null || n === 0) return "flat";
  return n > 0 ? "up" : "down";
}

export const MARKET_LABEL: Record<string, string> = { twse: "上市", tpex: "上櫃" };
export const DATASET_LABEL: Record<string, string> = {
  quotes: "日K",
  insti: "法人",
  margin: "融資券",
};
export const SOURCE_LABEL: Record<string, string> = { twse: "上市", tpex: "上櫃" };
