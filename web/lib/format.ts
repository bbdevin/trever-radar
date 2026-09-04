/**
 * S13 reason text 改名(融券回補軋空 → 融券減＋帶量大漲)的顯示期轉場。
 *
 * 程式碼走 Pages 幾分鐘就上,但 `daily_scores.reasons`/`indicators_daily.reasons`
 * 的 `text` 是 VPS 匯出當下寫死的字串,要等下一輪 export 才會換成新字。這段時間
 * 舊 payload 仍會把「融券回補軋空」原樣送到畫面。只改顯示,不碰資料:只對含舊
 * 字樣的 S13 reason 生效,新 payload 走不到這裡。用法比照
 * `PocketBadges.tsx` 的 `displayText()`——新 export 上線、舊字樣不再出現後可刪除。
 */
const LEGACY_S13_TEXT = "融券回補軋空";

export function legacyReasonText(code: string | null | undefined, text: string): string {
  if (code === "S13_SHORT_SQUEEZE" && text.startsWith(LEGACY_S13_TEXT)) {
    return "融券減少＋帶量大漲";
  }
  return text;
}

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

/** 張數／股數（無正負號，用於餘額、限額） */
export function fmtLotsPlain(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString("zh-TW");
}

export function fmtPct(n: number | null | undefined): string {
  if (n == null) return "—";
  const arrow = n > 0 ? "▲" : n < 0 ? "▼" : "";
  return `${arrow}${Math.abs(n).toFixed(2)}%`;
}

/** 使用率變化（百分點，可正可負） */
export function fmtUsageChg(n: number | null | undefined): string {
  if (n == null) return "—";
  const arrow = n > 0 ? "▲" : n < 0 ? "▼" : "";
  return `${arrow}${Math.abs(n).toFixed(1)}%`;
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
