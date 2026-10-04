/**
 * 權證、期貨、題材、公司(docs/46 v2 §2.7)。
 * - 權證:認售成交相對認購、相對前 20 日。
 * - 期貨:契約層級的成交量異常旗標 → 背景(方向未定;帶期貨行情日)。
 * - 題材:所屬題材今日成交相對 20 日均(與後端 T_THEME_HOT / H1_HOT_THEME 同源資料)。
 * - 公司:庫藏股買回期間 → 背景。
 */
import type { DerivedFact } from "../bullBear.ts";
import type { Buyback, FuturesInfo, RecentThemeHeat, WarrantHistoryPoint, WarrantSummary } from "../types.ts";
import { contractLabelsByCode, fmtLotsAbs } from "../futures.ts";
import { fmtMoney, mk, mmdd } from "./text.ts";

const MIN_TURNOVER = 5_000_000;

export function warrantFacts(w: WarrantSummary | null | undefined, wh: WarrantHistoryPoint[] | undefined, lastT: string): DerivedFact[] {
  const out: DerivedFact[] = [];
  if (w && w.put_call_ratio != null && w.put_call_ratio >= 1 && w.call_turnover + w.put_turnover >= MIN_TURNOVER) {
    out.push(mk("C_PUT_DOMINANT", [`認售權證成交 ${fmtMoney(w.put_turnover)},為認購的 ${w.put_call_ratio.toFixed(1)} 倍`], { rank: 3, magnitude: w.put_call_ratio }));
  }
  // warrant_history:舊→新
  if (wh && wh.length >= 21) {
    const last = wh[wh.length - 1];
    const prev = wh.slice(-21, -1);
    const avg = prev.reduce((s, p) => s + p.put_turnover, 0) / prev.length;
    if (avg > 0 && last.put_turnover >= MIN_TURNOVER && last.put_turnover >= avg * 2) {
      const x = last.put_turnover / avg;
      out.push(mk("C_PUT_SURGE", [`認售權證成交 ${fmtMoney(last.put_turnover)},為前20日均值 ${x.toFixed(1)} 倍`], { rank: 4, magnitude: x, date: last.t !== lastT ? mmdd(last.t) : undefined }));
    }
  }
  return out;
}

export function futuresFacts(f: FuturesInfo | undefined, stockId: string): DerivedFact[] {
  if (!f?.contracts?.length) return [];
  const flagged = f.contracts.filter((c) => c.anomaly);
  if (!flagged.length) return [];
  const labels = contractLabelsByCode(f.contracts, stockId);
  const day = f.daily_as_of ? mmdd(f.daily_as_of) : undefined;
  return flagged.map((c) =>
    mk("C_FUT_VOLUME_HIGH", [`${labels.get(c.code) ?? "期貨"}一般時段成交 ${fmtLotsAbs(c.anomaly!.today)} 口,為前 ${c.anomaly!.window_days} 個比較日最高(方向未定)`],
      { rank: 1, variant: c.code, date: day ? `行情 ${day}` : undefined }),
  );
}

export function themeFacts(heat: RecentThemeHeat[] | undefined, buyback: Buyback | null | undefined, lastT: string): DerivedFact[] {
  const out: DerivedFact[] = [];
  const ok = (heat ?? []).filter((h) => h.eligible && h.vs20 != null);
  const hot = ok.filter((h) => (h.vs20 as number) >= 1.15).sort((a, b) => (b.vs20 as number) - (a.vs20 as number));
  const cold = ok.filter((h) => (h.vs20 as number) <= 0.7).sort((a, b) => (a.vs20 as number) - (b.vs20 as number));
  const list = (xs: RecentThemeHeat[]) => xs.slice(0, 3).map((h) => `【${h.name}】${(h.vs20 as number).toFixed(2)} 倍`).join("、");
  const dateOf = (xs: RecentThemeHeat[]) => {
    const d = xs[0]?.heat_date;
    return d && d !== lastT ? mmdd(d) : undefined;
  };
  if (hot.length) out.push(mk("C_THEME_HOT", [`所屬題材成交為20日均:${list(hot)}`], { rank: 2, magnitude: hot[0].vs20 as number, mirrors: ["T_THEME_HOT", "H1_HOT_THEME"], date: dateOf(hot) }));
  if (cold.length) out.push(mk("C_THEME_COLD", [`所屬題材成交為20日均:${list(cold)}`], { rank: 1, date: dateOf(cold) }));
  if (buyback && buyback.status === "in_progress" && buyback.start_date && buyback.end_date) {
    const pctTxt = buyback.execution_pct != null ? `,已執行 ${buyback.execution_pct.toFixed(0)}%` : "";
    out.push(mk("C_BUYBACK", [`庫藏股買回期間 ${mmdd(buyback.start_date)}–${mmdd(buyback.end_date)}${pctTxt}`], { rank: 1, mirrors: ["KB1_BUYBACK_WINDOW"] }));
  }
  return out;
}
