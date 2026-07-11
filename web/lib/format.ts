/** 金額(元)→ 億,1 位小數 */
export function fmtE8(n: number | null | undefined): string {
  if (n == null) return "—";
  return (n / 1e8).toFixed(1) + "億";
}

/** 金額(元)→ 億(≥1億)或萬,含正負號;沿用專案 億/萬 慣例 */
export function fmtAmount(n: number | null | undefined): string {
  if (n == null) return "—";
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (abs >= 1e8) return `${sign}${(abs / 1e8).toFixed(1)}億`;
  return `${sign}${(abs / 1e4).toLocaleString("zh-TW", { maximumFractionDigits: 0 })}萬`;
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

export function fmtX(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${n.toFixed(1)}x`;
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
