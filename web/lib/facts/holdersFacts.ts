/**
 * 大戶比(docs/46 v2 §2.6):TDCC 集保股權分散週資料(holders_history,新→舊)與董監月資料。
 * 每一條都帶集保資料日(群組頭「大戶(集保 MM/DD)」);週資料天生落後,不取代任何後端 code。
 * 級距是集保分級彙總,不等於分點主力。
 */
import type { DerivedFact } from "../bullBear.ts";
import type { DirectorsLatest, HoldersHistoryPoint, HoldersMeta } from "../types.ts";
import { PCT, PP, fmtInt, mk, mmdd, share } from "./text.ts";

const MAJOR_STEP = 0.3;
const MAJOR_BIG = 0.5;
/** 「近 N 週最高/最低」至少要有這麼多週才判 */
const EXTREME_MIN_WEEKS = 12;

const pctOf = (p: HoldersHistoryPoint, lv: string) => p.thresholds?.[lv]?.shares_pct ?? null;
const ym = (s: string | null | undefined) => (s && /^\d{4}-\d{2}/.test(s) ? `${s.slice(5, 7)} 月` : null);

export function holdersFacts(hh: HoldersHistoryPoint[] | undefined, meta: HoldersMeta | undefined, directors: DirectorsLatest | null | undefined): DerivedFact[] {
  const out: DerivedFact[] = [];
  const insiderMonth = ym(meta?.insider_as_of_ym ?? directors?.as_of_ym);
  if (hh && hh.length >= 2) {
    const [h0, h1] = hh;
    const dataDate = mmdd(h0.t);
    const majorFact = (lv: "400" | "1000", only?: (d: number) => boolean) => {
      const a = pctOf(h0, lv);
      const b = pctOf(h1, lv);
      if (a == null || b == null) return null;
      const d = a - b;
      if (Math.abs(d) < MAJOR_STEP || (only && !only(d))) return null;
      const up = d > 0;
      let weeks = 0;
      for (let j = 0; j + 1 < hh.length; j++) {
        const x = pctOf(hh[j], lv);
        const y = pctOf(hh[j + 1], lv);
        if (x == null || y == null || Math.sign(x - y) !== Math.sign(d)) break;
        weeks++;
      }
      const series = hh.map((p) => pctOf(p, lv)).filter((x): x is number => x != null);
      let ext = "";
      if (series.length >= EXTREME_MIN_WEEKS) {
        if (up && a >= Math.max(...series)) ext = `,為近 ${series.length} 週最高`;
        if (!up && a <= Math.min(...series)) ext = `,為近 ${series.length} 週最低`;
      }
      const code = `H_MAJOR${lv}_${up ? "UP" : "DOWN"}`;
      return mk(code, [`${lv}張以上大戶持股 ${a.toFixed(2)}%,週${up ? "增" : "減"} `, PP(d), weeks >= 2 ? `,連 ${weeks} 週${up ? "增加" : "減少"}` : "", ext],
        { rank: Math.abs(d) >= MAJOR_BIG ? 5 : 3, magnitude: Math.abs(d), dataDate });
    };
    const m400 = majorFact("400");
    if (m400) out.push(m400);
    const d400 = (() => {
      const a = pctOf(h0, "400");
      const b = pctOf(h1, "400");
      return a != null && b != null ? a - b : 0;
    })();
    // 1000 張:方向與 400 張相反,或變化 ≥0.5 個百分點才另列
    const m1000 = majorFact("1000", (d) => Math.sign(d) !== Math.sign(d400) || Math.abs(d) >= MAJOR_BIG);
    if (m1000) out.push(m1000);

    // 未滿 400 張股東:人數週變化 ±2% 或持股 ±0.3 個百分點
    const n0 = h0.retail_holders;
    const n1 = h1.retail_holders;
    const p0 = h0.retail_pct;
    const p1 = h1.retail_pct;
    const nChg = n0 != null && n1 ? (n0 / n1 - 1) * 100 : null;
    const pChg = p0 != null && p1 != null ? p0 - p1 : null;
    const up = (nChg != null && nChg >= 2) || (pChg != null && pChg >= 0.3);
    const down = (nChg != null && nChg <= -2) || (pChg != null && pChg <= -0.3);
    if (up !== down) {
      const segs = [
        ...(nChg != null && n0 != null && n1 != null ? [`未滿400張股東 ${fmtInt(n1)}→${fmtInt(n0)} 人(`, PCT(nChg), ")"] : []),
        ...(pChg != null && p0 != null && p1 != null ? [`${nChg != null ? "," : "未滿400張"}持股 ${p1.toFixed(2)}%→${p0.toFixed(2)}%`] : []),
      ];
      out.push(mk(up ? "H_RETAIL_UP" : "H_RETAIL_DOWN", segs, { rank: 3, magnitude: Math.abs(nChg ?? 0), dataDate }));
    }

    // 1000 張以上人數
    const c0 = h0.thresholds?.["1000"]?.holders;
    const c1 = h1.thresholds?.["1000"]?.holders;
    if (c0 != null && c1 != null && Math.abs(c0 - c1) >= 3)
      out.push(mk("H_MAJOR_COUNT", [`1000張以上股東 ${c1}→${c0} 人(${c0 > c1 ? "+" : "−"}${Math.abs(c0 - c1)})`], { rank: 1, dataDate }));

    // 董監持股:與上一個不同的申報值比(月更、週序列 ffill)
    const i0 = h0.insider_pct;
    if (i0 != null) {
      const prev = hh.slice(1).map((p) => p.insider_pct).find((x) => x != null && Math.abs(x - i0) > 1e-9);
      if (prev != null) {
        const d = i0 - prev;
        if (Math.abs(d) >= 0.1)
          out.push(mk(d > 0 ? "H_INSIDER_UP" : "H_INSIDER_DOWN", [`董監持股 ${i0.toFixed(2)}%,較前次申報 `, PP(d), insiderMonth ? `(${insiderMonth}資料)` : ""], { rank: 2, magnitude: Math.abs(d), dataDate }));
      }
    }
  }

  // 董監質押比
  const rows = directors?.rows ?? [];
  const shares = rows.reduce((s, r) => s + (r.shares || 0), 0);
  const pledged = rows.reduce((s, r) => s + (r.pledged_shares || 0), 0);
  if (shares > 0 && pledged / shares >= 0.3)
    out.push(mk("H_PLEDGE_HIGH", [`董監質押比 ${share(pledged / shares)}`, insiderMonth ? `(${insiderMonth}資料)` : ""], { rank: 1, dataDate: hh?.[0] ? mmdd(hh[0].t) : undefined }));
  return out;
}
