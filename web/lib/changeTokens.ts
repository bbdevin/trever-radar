/**
 * 把一句含漲跌與價格的文字切成可上色的片段(2026-10-03 使用者:「只要有漲跌幾 % 的文字
 * 都要用顏色區分,股價也要用不同顏色或 span 區分」)。
 *
 * 規則(台股紅漲綠跌,docs/19 §1;顏色不是唯一訊號——符號與文字照留):
 *   - 有號百分比 `+5.3%` / `−2.8%` / `-2.8%` → up / down;`0.0%` → flat。
 *   - 「漲 ≥3%」「跌 ≥3%」這類以動詞表方向的 → up / down。
 *   - 「高於…N 檔」「低於…N 檔」→ up / down。
 *   - 帶小數的價格(`123.5`、`1,085.00`)→ price(粗體、前景色)。整數計數不動。
 * 純函式,`ChangeText` 元件只負責把 kind 對到 class。
 */
export type ChangeTokenKind = "text" | "up" | "down" | "flat" | "price";
export type ChangeToken = { kind: ChangeTokenKind; text: string };

const PATTERN = new RegExp(
  [
    "(?<signed>[+\\-−]\\d+(?:\\.\\d+)?%)",
    "(?<zero>(?<![\\d.])0(?:\\.0+)?%)",
    "(?<upverb>漲\\s*≥?\\s*\\d+(?:\\.\\d+)?%)",
    "(?<downverb>跌\\s*≥?\\s*\\d+(?:\\.\\d+)?%)",
    "(?<above>高於[^、，；。]*?\\d+\\s*檔)",
    "(?<below>低於[^、，；。]*?\\d+\\s*檔)",
    "(?<price>(?<![\\d.,])\\d{1,3}(?:,\\d{3})*\\.\\d+(?![\\d%]))",
  ].join("|"),
  "g",
);

export function changeTokens(text: string): ChangeToken[] {
  const out: ChangeToken[] = [];
  let last = 0;
  for (const m of text.matchAll(PATTERN)) {
    const g = m.groups ?? {};
    const start = m.index ?? 0;
    if (start > last) out.push({ kind: "text", text: text.slice(last, start) });
    let kind: ChangeTokenKind = "text";
    if (g.signed) kind = g.signed.startsWith("+") ? "up" : "down";
    else if (g.zero) kind = "flat";
    else if (g.upverb || g.above) kind = "up";
    else if (g.downverb || g.below) kind = "down";
    else if (g.price) kind = "price";
    out.push({ kind, text: m[0] });
    last = start + m[0].length;
  }
  if (last < text.length) out.push({ kind: "text", text: text.slice(last) });
  return out;
}
