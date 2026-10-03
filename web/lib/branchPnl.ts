/**
 * 區間損益(估算)`pnl-avgcost-v1` 的顯示邏輯(docs/42)。計算全在 pipeline
 * (`radar/compute/branch_interval_pnl.py`);這裡只負責格式、摘要句與誠實文案。
 *
 * 文案是鎖定的(branchPnl.test.ts 逐字比對):這是估算,不是帳戶損益;
 * 不寫勝率、不寫「常低買高賣」這種身分宣稱。
 */
import type { BranchPnlEst, BranchPnlRow, BranchPnlWindow } from "@/lib/types";

export const PNL_HEADING = "區間損益（估算）";
export const PNL_LEAD =
  "只用這檔每日前 15 大進出看得見的買賣，以當日收盤價當成交價、平均成本法估算；"
  + "看不見的日子視為沒交易，區間起點視為零持股。不含手續費與交易稅；股利只在調整因子有更新的期間才反映。";
export const PNL_POS_NOTE = "以未實現為主：若已在榜外出清，實際結果會不同。";
export const PNL_AF_NOTE = "區間內有調整因子變動，成本已換算到今日股本。";
export const PNL_FOOTER =
  "估算不是帳戶真實損益，也不代表之後會重複；本站 2026-09-08 回測顯示分點×個股買賣傾向跨期可重現性低。";

export function unattributedNote(lots: number): string {
  return `另有 ${lots.toLocaleString("zh-TW")} 張賣出找不到對應買進（區間前已持有或榜外買進），未計入。`;
}

export type PnlWindowKey = "60" | "240" | "all";
export const PNL_WINDOWS: { key: PnlWindowKey; label: string }[] = [
  { key: "60", label: "3月" },
  { key: "240", label: "1年" },
  { key: "all", label: "2年" },
];
export type PnlSide = "gain" | "loss";
export const DEFAULT_VISIBLE = 5;

const MINUS = "−";

function trimNum(n: number, digits: number): string {
  return n.toLocaleString("zh-TW", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

/** NT$ → 「2.7 億」「850 萬」「3,200 元」(不帶號)。 */
export function fmtMoneyAbs(n: number): string {
  const a = Math.abs(n);
  if (a >= 1e8 - 5e3) return `${trimNum(a / 1e8, a >= 1e10 ? 0 : 1)} 億`;
  if (a >= 1e4) return `${trimNum(a / 1e4, a >= 1e5 ? 0 : 1)} 萬`;
  return `${trimNum(a, 0)} 元`;
}

/** 帶號金額:「+2.7 億」「−850 萬」「0 元」。正負號與文字一起出現,顏色不是唯一訊號。 */
export function fmtMoney(n: number): string {
  const body = fmtMoneyAbs(n);
  if (body.startsWith("0 ")) return body;
  return `${n > 0 ? "+" : n < 0 ? MINUS : ""}${body}`;
}

/** ret_pct(已是百分比)→「+12.3%」;null → null。 */
export function fmtRetPct(p: number | null | undefined): string | null {
  if (p == null || !Number.isFinite(p)) return null;
  const a = Math.abs(p).toFixed(1);
  return `${p > 0 ? "+" : p < 0 ? MINUS : ""}${a}%`;
}

export function fmtPrice(p: number): string {
  return p.toLocaleString("zh-TW", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** 缺鍵、版本不認得或沒有任何窗口 → null(分段不出現)。 */
export function normalizePnl(est: BranchPnlEst | null | undefined): BranchPnlEst | null {
  if (!est || typeof est !== "object" || est.definitions_version !== "pnl-avgcost-v1") return null;
  const ws = est.windows ?? {};
  if (!PNL_WINDOWS.some((w) => ws[w.key])) return null;
  return est;
}

export function availableWindows(est: BranchPnlEst): PnlWindowKey[] {
  return PNL_WINDOWS.filter((w) => est.windows[w.key]).map((w) => w.key);
}

export function sideRows(win: BranchPnlWindow, side: PnlSide): BranchPnlRow[] {
  return side === "gain" ? win.gainers : win.losers;
}

export function sideCount(win: BranchPnlWindow, side: PnlSide): number {
  return side === "gain" ? (win.n_gainers ?? win.gainers.length) : (win.n_losers ?? win.losers.length);
}

/** 「符合門檻的 N 個分點：估算賺 X 個、賠 Y 個」——個數,不是金額,不是比率。 */
export function summaryText(win: BranchPnlWindow): string {
  return `符合門檻的 ${win.pairs_considered} 個分點：估算賺 ${sideCount(win, "gain")} 個、賠 ${sideCount(win, "loss")} 個`;
}

export function captionText(row: BranchPnlRow): string {
  return `${row.first_date}–${row.last_date} · ${row.visible_days} 個可見日`;
}

/** 一列底下的條件註記(依序:持股、找不到對應的賣出、調整因子)。 */
export function rowNotes(row: BranchPnlRow): string[] {
  const out: string[] = [];
  if (row.pos_lots > 0) out.push(PNL_POS_NOTE);
  if (row.sell_lots_unattributed > 0) out.push(unattributedNote(row.sell_lots_unattributed));
  if (row.af_adjusted) out.push(PNL_AF_NOTE);
  return out;
}

/** 已實現／未實現兩段條的寬度(依絕對值,合計 100);兩者皆 0 → null。 */
export function splitBar(row: BranchPnlRow): { realized: number; unrealized: number } | null {
  const r = Math.abs(row.realized);
  const u = Math.abs(row.unrealized);
  if (r + u === 0) return null;
  const rp = Math.round((r / (r + u)) * 100);
  return { realized: rp, unrealized: 100 - rp };
}

/** 「怎麼算」的公式文字。 */
export const PNL_FORMULA: string[] = [
  "價格＝當日收盤 × 當日調整因子 ÷ 最新調整因子（換算到今日股本）。",
  "淨買 N 張：均價＝（持股 × 均價 ＋ N × 價格）÷（持股 ＋ N），持股加 N。",
  "淨賣 N 張：先賣掉手上的持股（最多賣到 0，不放空），已實現 ＋＝ 賣出張數 ×（價格 − 均價）× 1000；超過持股的張數記為「找不到對應買進」，不計入。",
  "未實現＝持股 ×（最新收盤 − 均價）× 1000；估算合計＝已實現 ＋ 未實現。",
  "百分比＝估算合計 ÷ 區間內最大持有成本；排序只看金額，不看百分比。",
  "入選門檻：區間內看得見的買進至少 50 張，且最大持有成本至少 100 萬元；任何一個交易日缺收盤價的分點不列。",
];
