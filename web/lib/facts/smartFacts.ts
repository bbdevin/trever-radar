/**
 * 低買高賣/區間損益估算前段分點「現在在這檔做什麼」(docs/46 §6.8;2026-10-04 使用者:
 * 「籌碼分析 要把低買高賣的強分點 或是區間獲利多的分點考量進去」)。純呈現,不進任何分數。
 *
 * 「強分點」不另立定義,沿用既有兩份名單:
 *  - 低買高賣:branch_pctile_counts 排行(normalizeBranchPctile)每一派的前 DEFAULT_VISIBLE(5)名
 *    ——即面板預設展開的那幾家;買側紀錄未達 minKnown(compactSide 判「不足」)的不算,與分點標籤同規則。
 *  - 區間損益估算前段:branch_pnl_est 3月/1年窗口 gainers 依估算合計前 3 名且 > 0;
 *    進榜本身已過 pipeline 門檻(可見買進 ≥50 張、最大持有成本 ≥100 萬)。
 */
import type { DerivedFact } from "../bullBear.ts";
import { CAMP_KEYS, CAMP_NAMES, DEFAULT_VISIBLE as PCTILE_TOP, compactSide, normalizeBranchPctile, type CampKey, type SideNumbers } from "../branchPctile.ts";
import { PNL_WINDOWS, fmtMoney as fmtPnl } from "../branchPnl.ts";
import type { BranchPnlRow, Candle, StockJson } from "../types.ts";
import { LOTS, fmtInt, mk, mmdd } from "./text.ts";

/** 區間損益估算取前幾名 */
export const SMART_PNL_TOP = 3;
/** 看哪些區間損益窗口(3月、1年);2年太舊,不代表現在 */
export const SMART_PNL_WINDOWS = ["60", "240"] as const;
/** 期間買賣超要「有份量」:佔期間成交量 ≥0.5%,或 ≥500 張(大型股 0.5% 太難達到;同 C_TRACKED_SELL 的張數門檻) */
export const SMART_MIN_SHARE = 0.005;
export const SMART_MIN_LOTS_ALT = 500;
/** 不論佔量多高,至少 50 張(小量股 0.5% 只有幾張,不算) */
export const SMART_FLOOR_LOTS = 50;
/** 區間損益前段分點近 5 日賣掉估算持股的 ≥30% → 也算減碼(即使佔量未達門檻) */
export const SMART_CUT_RATIO = 0.3;
/** 佔量 ≥2% → rank 5 */
export const SMART_RANK5_SHARE = 0.02;
export const SMART_DAYS = 5;

type PnlKey = (typeof SMART_PNL_WINDOWS)[number];
interface Cred {
  pctile?: { camp: CampKey; buy: string; sell: string };
  pnl?: { window: PnlKey; row: BranchPnlRow };
}

const winLabel = (w: string) => PNL_WINDOWS.find((x) => x.key === w)?.label ?? `${w}日`;

/** 張數加權比例(舊資料退回次數);已知不足回 null。 */
function sideShare(s: SideNumbers | null | undefined, minKnown: number): number | null {
  if (!s || s.known < minKnown) return null;
  if (s.lotsKnown != null && s.lotsHit != null && s.lotsKnown > 0) return s.lotsHit / s.lotsKnown;
  return s.known > 0 ? s.hit / s.known : null;
}

/** 明顯勝過基準的幅度:至少高 10 個百分點,且為基準的 1.5 倍(19% vs 18% 不算強)。 */
export const SMART_BASE_MARGIN_PP = 0.1;
export const SMART_BASE_MULT = 1.5;

/** 分點這一側的比例是否明顯勝過股票自身基準;基準缺時要求 ≥ 50%。 */
function beatsBase(side: SideNumbers, base: SideNumbers | null, minKnown: number): boolean {
  const s = sideShare(side, minKnown);
  if (s == null) return false;
  const b = sideShare(base, 1);
  const eps = 1e-9; // 0.4×1.5 = 0.6000000000000001
  return b == null ? s >= 0.5 : s + eps >= b + SMART_BASE_MARGIN_PP && s + eps >= b * SMART_BASE_MULT;
}

function credentials(data: Pick<StockJson, "branch_pctile_counts" | "branch_pnl_est">): Map<string, Cred> {
  const out = new Map<string, Cred>();
  const get = (n: string) => out.get(n) ?? (out.set(n, {}), out.get(n)!);
  const model = normalizeBranchPctile(data.branch_pctile_counts);
  if (model) {
    for (const key of CAMP_KEYS) {
      const camp = model.camps[key];
      if (!camp || !camp.available) continue;
      for (const row of camp.rows.slice(0, PCTILE_TOP)) {
        const buy = compactSide("buy", row.buy, model.minKnown);
        if (buy.insufficient) continue;
        // 排行前段不等於「低買高賣」:買低、賣高兩側都要勝過這檔股票自己的基準
        // (同 docs/43 的判讀口徑);股票基準缺時,買低比例至少一半才算。
        if (!beatsBase(row.buy, camp.base.buy, model.minKnown)) continue;
        if (row.sell.known >= model.minKnown && !beatsBase(row.sell, camp.base.sell, model.minKnown)) continue;
        const c = get(row.name);
        if (c.pctile) continue;
        const sell = compactSide("sell", row.sell, model.minKnown);
        // 附上本股基準,讓「買低 19%」這種數字有參照(長線派基準常只有一成上下)
        const withBase = (text: string, base: SideNumbers | null) => {
          const b = sideShare(base, 1);
          return b == null ? text : `${text},本股 ${Math.round(b * 100)}%`;
        };
        c.pctile = {
          camp: key,
          buy: withBase(buy.text, camp.base.buy),
          sell: sell.insufficient ? withBase(buy.text, camp.base.buy) : withBase(sell.text, camp.base.sell),
        };
      }
    }
  }
  const pnl = data.branch_pnl_est;
  for (const w of SMART_PNL_WINDOWS) {
    const win = pnl?.windows?.[w];
    if (!win?.gainers) continue;
    const top = [...win.gainers].filter((r) => r.est_total > 0).sort((a, b) => b.est_total - a.est_total).slice(0, SMART_PNL_TOP);
    for (const row of top) {
      const c = get(row.name);
      if (!c.pnl) c.pnl = { window: w, row };
    }
  }
  return out;
}

/** 分點在區間損益估算窗口裡的那一列(持股、帳面用);先 3月 再 1年 */
function pnlRow(data: Pick<StockJson, "branch_pnl_est">, name: string): { window: PnlKey; row: BranchPnlRow } | null {
  for (const w of SMART_PNL_WINDOWS) {
    const win = data.branch_pnl_est?.windows?.[w];
    const row = [...(win?.gainers ?? []), ...(win?.losers ?? [])].find((r) => r.name === name);
    if (row) return { window: w, row };
  }
  return null;
}

/** 「低買高賣分點【A】(短線派 買低 56%)」/「區間損益估算前段分點【B】(3月 +200 萬)」 */
function credSegs(name: string, c: Cred, side: "buy" | "sell"): string {
  const kinds: string[] = [];
  const notes: string[] = [];
  if (c.pctile) {
    kinds.push("低買高賣");
    notes.push(`${CAMP_NAMES[c.pctile.camp]} ${side === "buy" ? c.pctile.buy : c.pctile.sell}`);
  }
  if (c.pnl) {
    kinds.push("區間損益估算前段");
    notes.push(`${winLabel(c.pnl.window)} ${fmtPnl(c.pnl.row.est_total)}`);
  }
  return `${kinds.join("、")}分點【${name}】(${notes.join(";")})`;
}

interface Move {
  name: string;
  cred: Cred;
  net: number;
  share: number;
  period: string;
  cut?: number;
}

export interface SmartResult {
  facts: DerivedFact[];
  /** C_SMART_HOLDING / C_SMART_HOLDING_NEG 涵蓋的分點(C_PNL_*_HOLDING 家數排除用,避免同一家寫兩次) */
  holdingNamed: Set<string>;
}

/**
 * excluded = 其他分點事實已點名、同方向的分點(目前是 C_TRACKED_SELL 的今日賣超名單),不重複列。
 */
export function smartBranchFacts(
  data: Pick<StockJson, "branch_history" | "branch_pctile_counts" | "branch_pnl_est">,
  candles: readonly Candle[],
  lastT: string,
  excludedSell: ReadonlySet<string> = new Set(),
): SmartResult {
  const facts: DerivedFact[] = [];
  const holdingNamed = new Set<string>();
  const creds = credentials(data);
  if (!creds.size) return { facts, holdingNamed };

  const volBy = new Map(candles.map((c) => [c.t, c.v || 0]));
  const bh = data.branch_history ?? [];
  const named = new Set<string>();
  const buys: Move[] = [];
  const sells: Move[] = [];
  let date: string | undefined;
  if (bh.length) {
    const lag = bh[0].t !== lastT;
    date = lag ? mmdd(bh[0].t) : undefined;
    const days = bh.slice(0, SMART_DAYS);
    const netOf = (d: (typeof bh)[number], n: string) => d.branches.reduce((s, b) => s + (b.n === n ? b.net : 0), 0);
    const vol0 = volBy.get(bh[0].t) ?? 0;
    const volN = days.reduce((s, d) => s + (volBy.get(d.t) ?? 0), 0);
    const big = (net: number, vol: number) =>
      Math.abs(net) >= SMART_FLOOR_LOTS && ((vol > 0 && Math.abs(net) >= vol * SMART_MIN_SHARE) || Math.abs(net) >= SMART_MIN_LOTS_ALT);
    const pnlFresh = data.branch_pnl_est?.as_of != null && data.branch_pnl_est.as_of >= bh[0].t;
    for (const [name, cred] of creds) {
      const net0 = netOf(bh[0], name);
      const netN = days.reduce((s, d) => s + netOf(d, name), 0);
      let m: Move | null = null;
      // 近 5 日的量全在今日 → 寫今日;否則先看近 5 日(較穩),不成立才看今日。一家分點只寫一句
      const today = { name, cred, net: net0, share: vol0 > 0 ? Math.abs(net0) / vol0 : 0, period: lag ? "" : "今日" };
      if (big(net0, vol0) && Math.abs(net0) >= Math.abs(netN)) m = today;
      else if (days.length > 1 && big(netN, volN)) m = { name, cred, net: netN, share: volN > 0 ? Math.abs(netN) / volN : 0, period: `近${days.length}日` };
      else if (big(net0, vol0)) m = today;
      // 區間損益前段分點:近 5 日賣掉估算持股 ≥30%(持股是估算日的,要估算日不早於分點資料日)
      if (cred.pnl && pnlFresh && netN < 0 && -netN >= SMART_FLOOR_LOTS) {
        const cut = -netN / (cred.pnl.row.pos_lots + -netN);
        if (cut >= SMART_CUT_RATIO) {
          if (!m || m.net > 0) m = { name, cred, net: netN, share: volN > 0 ? -netN / volN : 0, period: `近${days.length}日` };
          if (m.net < 0) m.cut = cut;
        }
      }
      if (!m) continue;
      if (m.net > 0) buys.push(m);
      else if (!excludedSell.has(name)) sells.push(m);
    }
  }

  const sentence = (code: string, rows: Move[], side: "buy" | "sell") => {
    rows.sort((a, b) => b.share - a.share || Math.abs(b.net) - Math.abs(a.net));
    const segs: (string | ReturnType<typeof LOTS>)[] = [];
    rows.slice(0, 2).forEach((r, k) => {
      if (k) segs.push(";");
      named.add(r.name);
      segs.push(`${credSegs(r.name, r.cred, side)}${r.period}${side === "buy" ? "買超" : "賣超"} `, LOTS(r.net));
      if (r.share > 0) segs.push(`(佔量 ${(r.share * 100).toFixed(1)}%)`);
      if (r.cut != null) segs.push(`,估算持股減少 ${Math.round(r.cut * 100)}%`);
    });
    if (rows.length > 2) segs.push(` 等 ${rows.length} 家`);
    const top = rows[0].share;
    facts.push(mk(code, segs, { rank: top >= SMART_RANK5_SHARE ? 5 : 4, magnitude: top * 100, date }));
  };
  if (buys.length) sentence("C_SMART_BUY", buys, "buy");
  if (sells.length) sentence("C_SMART_SELL", sells, "sell");

  // 仍有持股(估算):沒被買賣句點名的強分點;一家一句,最多 2 家
  const pnl = data.branch_pnl_est;
  const holds: { name: string; cred: Cred; pos: number; un: number; window: PnlKey }[] = [];
  for (const [name, cred] of creds) {
    if (named.has(name)) continue;
    const pr = cred.pnl ?? pnlRow(data, name);
    if (!pr || pr.row.pos_lots < SMART_FLOOR_LOTS || !pr.row.unrealized) continue;
    holds.push({ name, cred, pos: pr.row.pos_lots, un: pr.row.unrealized, window: pr.window });
  }
  // 帳面為正 → 多方(C_SMART_HOLDING,rank 3);帳面為負 → 背景(C_SMART_HOLDING_NEG,rank 2):
  // 強分點套牢中仍持股,不是多方證據(2026-10-04 使用者)
  const hDate = pnl?.as_of && pnl.as_of !== lastT ? mmdd(pnl.as_of) : undefined;
  const holdSentence = (code: string, rows: typeof holds, rank: number) => {
    if (!rows.length) return;
    rows.sort((a, b) => b.pos - a.pos);
    const segs: string[] = [];
    rows.slice(0, 2).forEach((h, k) => {
      if (k) segs.push(";");
      segs.push(`${credSegs(h.name, h.cred, "buy")}仍有持股 ${fmtInt(h.pos)} 張,帳面為${h.un > 0 ? "正" : "負"}(${h.cred.pnl ? "" : winLabel(h.window)}估算)`);
    });
    if (rows.length > 2) segs.push(` 等 ${rows.length} 家`);
    facts.push(mk(code, segs, { rank, date: hDate }));
  };
  for (const h of holds) holdingNamed.add(h.name);
  holdSentence("C_SMART_HOLDING", holds.filter((h) => h.un > 0), 3);
  holdSentence("C_SMART_HOLDING_NEG", holds.filter((h) => h.un < 0), 2);
  return { facts, holdingNamed };
}
