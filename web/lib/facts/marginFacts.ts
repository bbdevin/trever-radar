/**
 * 資券(docs/46 v2 §2.4):margin_history(張,新→舊)。使用率門檻與後端 I_MARGIN_OK / R_MARGIN_HOT 相同(60%)。
 * 股價 5 日變化用還原收盤。
 */
import type { DerivedFact } from "../bullBear.ts";
import type { Candle, MarginHistoryPoint } from "../types.ts";
import { LOTS, PCT, mk, mmdd, share } from "./text.ts";

export function marginFacts(mh: MarginHistoryPoint[] | undefined, adjusted: readonly Candle[], lastT: string): DerivedFact[] {
  if (!mh?.length) return [];
  const r0 = mh[0];
  const date = r0.t !== lastT ? mmdd(r0.t) : undefined;
  const out: DerivedFact[] = [];
  if (r0.usage != null) {
    if (r0.usage >= 0.6) out.push(mk("C_MARGIN_HOT", [`融資使用率 ${share(r0.usage)},高於 60%`], { rank: 3, magnitude: r0.usage, mirrors: ["R_MARGIN_HOT"], date }));
    else out.push(mk("C_MARGIN_OK", [`融資使用率 ${share(r0.usage)},低於 60%`], { rank: 1, mirrors: ["I_MARGIN_OK"], date }));
  }
  const r5 = mh[5];
  if (!r5) return out;
  const closeBy = new Map(adjusted.map((c) => [c.t, c.c]));
  const c0 = closeBy.get(r0.t);
  const c5 = closeBy.get(r5.t);
  const pchg = c0 != null && c5 ? (c0 / c5 - 1) * 100 : null;
  if (r0.balance != null && r5.balance != null && r5.balance > 0 && pchg != null) {
    const chg = r0.balance - r5.balance;
    const rel = chg / r5.balance;
    const segs = [`融資 5 日${chg > 0 ? "增加" : "減少"} `, LOTS(chg), "(", PCT(rel * 100), "),股價 5 日 ", PCT(pchg)];
    if (rel >= 0.1 && chg >= 100 && pchg <= 0) out.push(mk("C_MARGIN_UP_PRICE_DOWN", segs, { rank: 4, magnitude: rel * 100, date }));
    else if (rel <= -0.1 && chg <= -100 && pchg >= 0) out.push(mk("C_MARGIN_DOWN_PRICE_UP", segs, { rank: 4, magnitude: -rel * 100, date }));
  }
  if (r0.short_balance != null && r5.short_balance != null && r5.short_balance > 0) {
    const chg = r0.short_balance - r5.short_balance;
    if (Math.abs(chg) >= 50 && Math.abs(chg) >= r5.short_balance * 0.2)
      out.push(mk("C_SHORT_CHANGE", [`融券 5 日${chg > 0 ? "增加" : "減少"} `, LOTS(chg), "(", PCT((chg / r5.short_balance) * 100), ")"], { rank: 1, date }));
  }
  if (r0.short_balance != null && r0.balance != null && r0.balance > 0) {
    const ratio = r0.short_balance / r0.balance;
    if (ratio >= 0.3) out.push(mk("C_SHORT_MARGIN_RATIO", [`券資比 ${share(ratio)}`], { rank: 1, date }));
  }
  return out;
}
