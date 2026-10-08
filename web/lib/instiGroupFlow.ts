/**
 * 首頁「法人族群」分頁(docs/49 MVP)的句子與小工具。
 *
 * 純函式,不 import 任何執行期的 "@/" 模組,node --test 直接跑;禁用詞由 instiGroupFlow.test.ts 把關。
 * 資料是 rankings/insti_flow_1d.json:族群內成分股的法人淨張數相加,金額是張數 × 當日收盤的估算。
 */
import type { InstiFlowGroup, InstiFlowJson, InstiIdentity } from "./types.ts";

export const INSTI_TAB_LABEL = "法人族群";
export const INSTI_TAB_HINT =
  "外資、投信、自營商今天在哪些產業或題材買超、賣超最多;點族群看是哪幾檔。只整理交易所公布的買賣超,不下判斷。";
export const INSTI_FLOW_URL = "/data/rankings/insti_flow_1d.json";
export const INSTI_EMPTY = "尚無法人族群資料(下一輪法人更新後出現)";
export const INSTI_NO_GROUPS = "今日沒有可排名的族群";
export const INSTI_OTHER_LABEL = "其他(未排名,含成分不足 3 檔的產業)";

export const IDENTITIES: readonly InstiIdentity[] = ["foreign", "trust", "dealer", "total"];
export const IDENTITY_LABEL: Record<InstiIdentity, string> = {
  foreign: "外資",
  trust: "投信",
  dealer: "自營",
  total: "合計",
};

export type InstiMode = "industry" | "theme";
export const MODE_LABEL: Record<InstiMode, string> = { industry: "產業", theme: "題材" };

/** 每邊最多列幾組(全部族群為 P1) */
export const SIDE_LIMIT = 10;
/** 第一檔金額佔族群 ≥ 70% → 「集中於 X」 */
export const CONCENTRATION_RATIO = 0.7;

/** 定義句:身分、金額估算、題材重疊、自營口徑。 */
export function definitionText(ident: InstiIdentity, mode: InstiMode): string {
  const who = ident === "total" ? "三大法人合計" : IDENTITY_LABEL[ident];
  const parts = [`族群內成分股的${who}買賣超張數相加;金額＝張數×當日收盤(估)。`];
  if (mode === "theme") parts.push("題材成分重疊,只供組間比較。");
  if (ident === "dealer") parts.push("自營＝自行買賣＋避險合計。");
  parts.push("只整理資料,不下判斷。");
  return parts.join("");
}

/** "2026-10-07" → "10/07" */
export function mmdd(d: string | null | undefined): string {
  if (!d) return "—";
  const m = /^\d{4}-(\d{2})-(\d{2})$/.exec(d);
  return m ? `${m[1]}/${m[2]}` : d;
}

function signed(n: number, body: string): string {
  return n > 0 ? `+${body}` : n < 0 ? `-${body}` : body;
}

/** 金額(元)→ "+38.2億" / "-3,200萬";不含「估」字(呼叫端決定放哪) */
export function fmtAmt(n: number): string {
  const abs = Math.abs(n);
  const body = abs >= 1e8
    ? `${(abs / 1e8).toFixed(1)}億`
    : `${Math.round(abs / 1e4).toLocaleString("zh-TW")}萬`;
  return signed(Math.round(abs / 1e4) === 0 ? 0 : n, body);
}

/** 金額一律帶「估」 */
export function fmtAmtEst(n: number): string {
  return `${fmtAmt(n)}(估)`;
}

export function fmtNetLots(n: number): string {
  return signed(n, Math.abs(n).toLocaleString("zh-TW")) + "張";
}

/** 右上資料日:「法人 10/07 · 收盤 10/07」 */
export function dateLine(p: Pick<InstiFlowJson, "as_of" | "data_date">): string {
  return `法人 ${mmdd(p.as_of)} · 收盤 ${mmdd(p.data_date)}`;
}

/** 法人比收盤晚到(stale)時的一行 */
export function staleText(p: Pick<InstiFlowJson, "as_of" | "data_date" | "stale">): string | null {
  if (!p.stale) return null;
  return `法人資料為 ${mmdd(p.as_of)},今日法人 16:00 起輪詢,到齊後更新。`;
}

/** 只有一個市場的法人到齊時的一行(不得把半套講成全市場) */
export function partialText(p: Pick<InstiFlowJson, "coverage">): string | null {
  const { twse, tpex } = p.coverage;
  if (twse > 0 && tpex === 0) return "上櫃法人尚未到齊,目前只有上市。";
  if (tpex > 0 && twse === 0) return "上市法人尚未到齊,目前只有上櫃。";
  if (twse === 0 && tpex === 0) return "上市、上櫃法人都尚未到齊。";
  return null;
}

/** 「外資全市場 +45,210張 · +120.3億(估)」;partial 時改稱「目前已到齊市場」 */
export function marketLine(p: InstiFlowJson, ident: InstiIdentity): string {
  const m = p.market[ident];
  const scope = p.coverage.partial ? "已到齊市場" : "全市場";
  return `${IDENTITY_LABEL[ident]}${scope} ${fmtNetLots(m.net_lots)} · ${fmtAmtEst(m.amt_est)}`;
}

/** 族群列第二行的短計數:「18買/6賣」 */
export function countShort(g: Pick<InstiFlowGroup, "buy_n" | "sell_n">): string {
  return `${g.buy_n}買/${g.sell_n}賣`;
}

/** 展開後的完整計數 */
export function countFull(g: Pick<InstiFlowGroup, "buy_n" | "sell_n" | "n">): string {
  return `買超 ${g.buy_n} 檔/賣超 ${g.sell_n} 檔/有資料 ${g.n} 檔`;
}

export function missingText(n: number | null | undefined): string | null {
  return n && n > 0 ? `${n} 檔無當日收盤,金額未計` : null;
}

export function clsStaleText(clsDate: string | null | undefined): string | null {
  return clsDate ? `分類 ${mmdd(clsDate)}` : null;
}

/**
 * 「一檔撐場」:族群同方向的第一檔(買超組看 buy_top[0]、賣超組看 sell_top[0])
 * 金額佔族群 ≥ 70% 時回傳該檔名稱。純顯示。
 */
export function concentratedIn(g: InstiFlowGroup): string | null {
  if (g.amt_est === 0) return null;
  const top = g.amt_est > 0 ? g.buy_top[0] : g.sell_top[0];
  if (!top) return null;
  return top.amt_est / g.amt_est >= CONCENTRATION_RATIO ? top.name : null;
}

export function concentrationText(g: InstiFlowGroup): string | null {
  const name = concentratedIn(g);
  return name ? `集中於 ${name}` : null;
}

export const LOTS_AMT_MISMATCH = "張數方向與金額不同";

/**
 * 排名看金額(估),張數與金額可能反向(低價股大量買超、高價股少量賣超):賣超欄出現
 * 「+N張」時加一句小字,免得讀成資料錯誤。
 */
export function lotsAmtMismatchText(g: Pick<InstiFlowGroup, "net_lots" | "amt_est">): string | null {
  return Math.sign(g.net_lots) * Math.sign(g.amt_est) < 0 ? LOTS_AMT_MISMATCH : null;
}

function bySellOrder(a: InstiFlowGroup, b: InstiFlowGroup): number {
  if (a.amt_est !== b.amt_est) return a.amt_est - b.amt_est;
  if (a.net_lots !== b.net_lots) return a.net_lots - b.net_lots;
  return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
}

/** 依金額(估)拆買超/賣超兩邊;買超照檔內順序(金額降冪),賣超金額最負的在前。 */
export function splitSides(groups: InstiFlowGroup[]): { buy: InstiFlowGroup[]; sell: InstiFlowGroup[] } {
  return {
    buy: groups.filter((g) => g.amt_est > 0),
    sell: groups.filter((g) => g.amt_est < 0).sort(bySellOrder),
  };
}

/** 超過 SIDE_LIMIT 時的小字 */
export function moreText(total: number, shown: number): string | null {
  return total > shown ? `顯示前 ${shown} 組,共 ${total} 組` : null;
}

/** 條長(0–1);最小 6% 讓小值也看得到 */
export function barRatio(amt: number, maxAbs: number): number {
  if (maxAbs <= 0) return 0.06;
  return Math.max(Math.abs(amt) / maxAbs, 0.06);
}

/** 個股連結:開三大法人分頁 */
export function memberHref(id: string): string {
  return `/stock?id=${encodeURIComponent(id)}#insti`;
}
