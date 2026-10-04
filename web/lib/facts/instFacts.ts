/**
 * 法人(docs/46 v2 §2.3):insti_history(張,新→舊)。外資、投信每身分一天一列;自營商不列。
 * 顯著門檻與後端 I_* 相同:外資 ≥ 當日量 1% 或 ≥1,000 張、投信 ≥1% 或 ≥500 張。
 */
import type { DerivedFact } from "../bullBear.ts";
import type { Candle, StockJson } from "../types.ts";
import { LOTS, fmtInt, mk, mmdd } from "./text.ts";

type Row = NonNullable<StockJson["insti_history"]>[number];

const IDS = [
  { key: "foreign" as const, label: "外資", thr: 1000, buy: "C_FOREIGN_BUY", sell: "C_FOREIGN_SELL", d20: ["C_FOREIGN_20D_BUY", "C_FOREIGN_20D_SELL"] },
  { key: "trust" as const, label: "投信", thr: 500, buy: "C_TRUST_BUY", sell: "C_TRUST_SELL", d20: ["C_TRUST_20D_BUY", "C_TRUST_20D_SELL"] },
];

export function instFacts(ih: Row[] | undefined, candles: readonly Candle[], lastT: string): DerivedFact[] {
  if (!ih?.length) return [];
  const volBy = new Map(candles.map((c) => [c.t, c.v || 0]));
  const r0 = ih[0];
  const vol = volBy.get(r0.t) ?? 0;
  const date = r0.t !== lastT ? mmdd(r0.t) : undefined;
  const out: DerivedFact[] = [];
  const sig: Record<string, number> = {};
  for (const id of IDS) {
    const x = r0[id.key] ?? 0;
    const ok = x !== 0 && vol > 0 && (Math.abs(x) >= vol * 0.01 || Math.abs(x) >= id.thr);
    if (ok) {
      sig[id.key] = Math.sign(x);
      let k = 0;
      let cum = 0;
      for (const r of ih) {
        const y = r[id.key] ?? 0;
        if (Math.sign(y) !== Math.sign(x) || y === 0) break;
        k++;
        cum += y;
      }
      const sh = (Math.abs(x) / vol) * 100;
      const verb = x > 0 ? "買超" : "賣超";
      // 沒有連續時,改講近 10 日有幾天同方向(≥5 天才講)
      const last10 = ih.slice(0, 10);
      const same10 = last10.filter((r) => Math.sign(r[id.key] ?? 0) === Math.sign(x)).length;
      const tail = k >= 2
        ? [`,連 ${k} 日累計 `, LOTS(cum)]
        : last10.length === 10 && same10 >= 5 ? [`,近10日有 ${same10} 日${verb},10日合計 `, LOTS(last10.reduce((s, r) => s + (r[id.key] ?? 0), 0))] : [];
      const segs = [`${id.label}${verb} ${fmtInt(Math.abs(x))} 張(佔量 ${sh.toFixed(1)}%)`, ...tail];
      const mirrors =
        x > 0
          ? [id.key === "foreign" ? "I_FOREIGN_BUY" : "I_TRUST_BUY", ...(k >= 3 ? [id.key === "foreign" ? "I_FOREIGN_STREAK" : "I_TRUST_STREAK"] : [])]
          : id.key === "foreign" && k >= 5 ? ["R_FOREIGN_SELL5"] : [];
      const rank = x < 0 && id.key === "foreign" && sh >= 3 ? 5 : 4;
      out.push(mk(x > 0 ? id.buy : id.sell, segs, { rank, magnitude: sh, mirrors, date }));
      continue;
    }
    // 單日不顯著 → 看近 20 日累計(≥ 期間成交量 2%)
    if (ih.length >= 20) {
      const rows = ih.slice(0, 20);
      const sum = rows.reduce((s, r) => s + (r[id.key] ?? 0), 0);
      const v20 = rows.reduce((s, r) => s + (volBy.get(r.t) ?? 0), 0);
      if (v20 > 0 && Math.abs(sum) >= v20 * 0.02) {
        const sh = (Math.abs(sum) / v20) * 100;
        out.push(mk(sum > 0 ? id.d20[0] : id.d20[1], [`${id.label}近20日累計${sum > 0 ? "買超" : "賣超"} `, LOTS(sum), `(佔期間量 ${sh.toFixed(1)}%)`], { rank: 3, magnitude: sh, date }));
      }
    }
  }
  if (sig.foreign && sig.foreign === sig.trust) {
    const buy = sig.foreign > 0;
    out.push(mk(buy ? "C_BOTH_BUY" : "C_BOTH_SELL", [`外資、投信同步${buy ? "買超" : "賣超"}`], { rank: 4, mirrors: buy ? ["I_BOTH_BUY"] : [], date }));
  }
  if (vol > 0 && r0.total != null) {
    const sh = (r0.total / vol) * 100;
    if (Math.abs(sh) >= 3) {
      const buy = sh > 0;
      out.push(mk(buy ? "C_NET_SHARE_BUY" : "C_NET_SHARE_SELL", [`三大法人合計${buy ? "買超" : "賣超"} ${fmtInt(Math.abs(r0.total))} 張(佔量 ${Math.abs(sh).toFixed(1)}%)`],
        { rank: 4, magnitude: Math.abs(sh), mirrors: buy ? ["I_NET_SHARE"] : [], date }));
    }
  }
  return out;
}
