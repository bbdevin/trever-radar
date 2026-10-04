/**
 * 分點(docs/46 v2 §2.5):branch_history(每天只留淨額前 12 大,新→舊)、branch_tags(地緣/隔日沖/追蹤)、
 * branch_pnl_est(區間損益估算)。囤貨/出貨沿用籌碼日報 accumulation.computeWindow 的同一套判準。
 */
import type { DerivedFact } from "../bullBear.ts";
import type { Candle, StockJson } from "../types.ts";
import { TOP_N_PER_DAY, computeWindow, type AccRow } from "../accumulation.ts";
import { LOTS, fmtInt, mk, mmdd } from "./text.ts";

const dayNet = (d: { branches: { n: string; net: number }[] }) => {
  const m = new Map<string, number>();
  for (const b of d.branches) m.set(b.n, (m.get(b.n) ?? 0) + b.net);
  return m;
};

function nameList(rows: { name: string; net: number }[], max = 2) {
  const segs: (string | ReturnType<typeof LOTS>)[] = [];
  rows.slice(0, max).forEach((r, k) => {
    if (k) segs.push("、");
    segs.push(`${r.name} `, LOTS(r.net));
  });
  if (rows.length > max) segs.push(" 等");
  return segs;
}

export function branchFacts(data: Pick<StockJson, "branch_history" | "branch_tags" | "branch_pnl_est">, candles: readonly Candle[], lastT: string, muted: ReadonlySet<string>): DerivedFact[] {
  const bh = data.branch_history;
  const out: DerivedFact[] = [];
  const volBy = new Map(candles.map((c) => [c.t, c.v || 0]));
  if (bh?.length) {
    const d0 = bh[0];
    const vol = volBy.get(d0.t) ?? 0;
    const lag = d0.t !== lastT;
    const date = lag ? mmdd(d0.t) : undefined;
    const today = lag ? "" : "今日";
    const nets = dayNet(d0);

    // 前 N 大分點淨流
    const flow = (d: (typeof bh)[number]) => d.branches.reduce((s, b) => s + b.net, 0);
    const f0 = flow(d0);
    if (vol > 0 && Math.abs(f0) >= vol * 0.02) {
      let k = 0;
      for (const d of bh) {
        if (Math.sign(flow(d)) !== Math.sign(f0)) break;
        k++;
      }
      const sh = (Math.abs(f0) / vol) * 100;
      const buy = f0 > 0;
      out.push(mk(buy ? "C_TOP15_FLOW_BUY" : "C_TOP15_FLOW_SELL",
        [`前${TOP_N_PER_DAY}大分點${today}淨${buy ? "買超" : "賣超"} ${fmtInt(Math.abs(f0))} 張(佔量 ${sh.toFixed(1)}%)`, k >= 2 ? `,連 ${k} 日為${buy ? "正" : "負"}` : ""],
        { rank: 4, magnitude: sh, mirrors: buy && k >= 3 ? ["B6_BIG_MONEY_FLOW"] : [], date }));
    }

    // 囤貨 / 出貨(1 月、1 週;1 週名單與 1 月重疊過半就不另列)
    const vd = candles.map((c) => ({ t: c.t, v: c.v || 0 }));
    const m1 = computeWindow(bh, vd, 20);
    const w1 = computeWindow(bh, vd, 5);
    const accFact = (code: string, label: string, rows: AccRow[], count: number, total: number, end: string, rank: number) =>
      mk(code, [`${label}${code.includes("ACC") ? "囤貨" : "出貨"}分點 ${count} 家:`, ...nameList(rows), ",合計 ", LOTS(total)],
        { rank, magnitude: vol > 0 ? (Math.abs(total) / vol) * 100 : undefined, date: end !== lastT ? mmdd(end) : undefined });
    const overlap = (a: AccRow[], b: AccRow[]) => {
      if (!a.length) return 1;
      const s = new Set(b.map((r) => r.name));
      return a.filter((r) => s.has(r.name)).length / a.length;
    };
    if (m1.available) {
      if (m1.accCount) out.push(accFact("C_ACC_1M", "近1月", m1.acc, m1.accCount, m1.accTotal, m1.end, 3));
      if (m1.distCount) out.push(accFact("C_DIST_1M", "近1月", m1.dist, m1.distCount, m1.distTotal, m1.end, 5));
    }
    if (w1.available) {
      if (w1.accCount && (!m1.available || overlap(w1.acc, m1.acc) < 0.5)) out.push(accFact("C_ACC_1W", "近1週", w1.acc, w1.accCount, w1.accTotal, w1.end, 3));
      if (w1.distCount && (!m1.available || overlap(w1.dist, m1.dist) < 0.5)) out.push(accFact("C_DIST_1W", "近1週", w1.dist, w1.distCount, w1.distTotal, w1.end, 4));
    }

    const tags = data.branch_tags;
    if (tags && vol > 0) {
      // 今日買超中有隔日沖紀錄的分點
      const rows = tags.daytrade?.rows ?? {};
      const dt = [...nets].filter(([n, v]) => v > 0 && rows[n]).map(([name, net]) => ({ name, net })).sort((a, b) => b.net - a.net);
      const dtSum = dt.reduce((s, r) => s + r.net, 0);
      if (dt.length && dtSum >= vol * 0.01)
        out.push(mk("C_DAYTRADE_BUY", [`${today}買超分點中有隔日沖紀錄者 ${dt.length} 家,合計 `, LOTS(dtSum), `(佔量 ${((dtSum / vol) * 100).toFixed(1)}%)`],
          { rank: 4, magnitude: (dtSum / vol) * 100, date }));

      // 追蹤分點淨賣超(使用者關掉的不算)
      const tracked = new Set((tags.tracked ?? []).filter((n) => !muted.has(n)));
      const ts = [...nets].filter(([n, v]) => v < 0 && tracked.has(n)).map(([name, net]) => ({ name, net })).sort((a, b) => a.net - b.net);
      const tsSum = ts.reduce((s, r) => s + r.net, 0);
      if (ts.length && (-tsSum >= vol * 0.003 || -tsSum >= 500))
        out.push(mk("C_TRACKED_SELL", [`追蹤分點${today}淨賣超 ${ts.length} 家:`, ...nameList(ts), ...(ts.length > 1 ? [",合計 ", LOTS(tsSum)] : [])],
          { rank: 4, magnitude: (-tsSum / vol) * 100, date }));

      // 地緣分點
      const geo = new Set(tags.geo?.names ?? []);
      const g = [...nets].filter(([n]) => geo.has(n));
      const gSum = g.reduce((s, [, v]) => s + v, 0);
      if (g.length && Math.abs(gSum) >= vol * 0.01) {
        const buy = gSum > 0;
        out.push(mk(buy ? "C_GEO_BUY" : "C_GEO_SELL", [`地緣分點 ${g.length} 家${today}淨${buy ? "買超" : "賣超"},合計 `, LOTS(gSum), `(佔量 ${((Math.abs(gSum) / vol) * 100).toFixed(1)}%)`],
          { rank: 4, magnitude: (Math.abs(gSum) / vol) * 100, mirrors: [buy ? "G1_GEO_BUY" : "G2_GEO_SELL"], date }));
      }
    }
  }

  // 區間損益(估算):近 60 日仍有持股的分點,帳面為正/為負的家數
  const pnl = data.branch_pnl_est;
  const w = pnl?.windows?.["60"];
  if (w) {
    const byName = new Map<string, { pos: number; un: number }>();
    for (const r of [...(w.gainers ?? []), ...(w.losers ?? [])]) if (!byName.has(r.name)) byName.set(r.name, { pos: r.pos_lots, un: r.unrealized });
    const holding = [...byName.values()].filter((r) => r.pos > 0);
    const neg = holding.filter((r) => r.un < 0);
    const pos = holding.filter((r) => r.un > 0);
    const date = pnl.as_of && pnl.as_of !== lastT ? mmdd(pnl.as_of) : undefined;
    const lots = (xs: { pos: number }[]) => fmtInt(xs.reduce((s, r) => s + r.pos, 0));
    if (neg.length >= 2) out.push(mk("C_PNL_LOSERS_HOLDING", [`近60日仍有持股且帳面為負的分點 ${neg.length} 家,合計持股 ${lots(neg)} 張(估算)`], { rank: 2, date }));
    if (pos.length >= 2) out.push(mk("C_PNL_GAINERS_HOLDING", [`近60日仍有持股且帳面為正的分點 ${pos.length} 家,合計持股 ${lots(pos)} 張(估算)`], { rank: 2, date }));
  }
  return out;
}
