import type { Candle } from "@/lib/types";

export type Timeframe = "D" | "W" | "M";

/** 週鍵:該日所屬週的週一日期(台股週一~週五) */
function weekKey(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00Z");
  const dow = (d.getUTCDay() + 6) % 7; // Mon=0
  d.setUTCDate(d.getUTCDate() - dow);
  return d.toISOString().slice(0, 10);
}

/** 日K → 週K/月K:開=首日開、高=max、低=min、收=末日收、量/額=加總,t=末日 */
export function resample(candles: Candle[], tf: Timeframe): Candle[] {
  if (tf === "D") return candles;
  const out: Candle[] = [];
  let key = "";
  let cur: Candle | null = null;
  for (const c of candles) {
    const k = tf === "M" ? c.t.slice(0, 7) : weekKey(c.t);
    if (k !== key || !cur) {
      if (cur) out.push(cur);
      key = k;
      cur = { ...c };
    } else {
      cur.h = Math.max(cur.h, c.h);
      cur.l = Math.min(cur.l, c.l);
      cur.c = c.c;
      cur.v += c.v;
      cur.amt += c.amt;
      cur.t = c.t;
    }
  }
  if (cur) out.push(cur);
  return out;
}

/** 把「交易日數」換算成該週期的 bar 數 */
export function barsForDays(days: number, tf: Timeframe): number {
  if (!Number.isFinite(days)) return Number.MAX_SAFE_INTEGER;
  return tf === "D" ? days : tf === "W" ? Math.ceil(days / 5) : Math.ceil(days / 21);
}
