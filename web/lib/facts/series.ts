/**
 * 多空事實用的 K 線序列(docs/46 v2 §2.8):先還原(價 × af/af_last、量 × af_last/af),再合併成週K/月K,
 * 然後算均線、MACD、RSI、KD。K 線分頁畫的是原始價,這裡一律是還原價。
 * 最後一根週K/月K視為進行中(事件型句子標「本週」「本月」)。
 */
import type { Candle } from "../types.ts";
import { kd, macd, rsi, sma } from "../indicators.ts";
import { resample, type Timeframe } from "../resample.ts";

/** 還原到最後一根的基準;收盤缺值的 K 棒略過,高低開缺值以收盤代替。 */
export function adjustCandles(candles: readonly Candle[] | null | undefined): Candle[] {
  const rows = (candles ?? []).filter((c) => c && typeof c.c === "number" && Number.isFinite(c.c));
  if (!rows.length) return [];
  const last = rows[rows.length - 1].af || 1;
  return rows.map((c) => {
    const f = (c.af || 1) / last;
    const h = c.h ?? c.c;
    const l = c.l ?? c.c;
    const o = c.o ?? c.c;
    return { ...c, o: o * f, h: h * f, l: l * f, c: c.c * f, v: (c.v || 0) / f };
  });
}

export const MA_BY_TF: Record<Timeframe, readonly number[]> = {
  D: [5, 10, 20, 60, 120, 240],
  W: [5, 10, 20, 60],
  M: [5, 10, 20, 60],
};

export interface Series {
  tf: Timeframe;
  t: string[];
  o: number[];
  h: number[];
  l: number[];
  c: number[];
  v: number[];
  /** 每根含幾個交易日(日K 為 1);週/月的量比用「日均量」比,進行中的那根才不會被少算 */
  days: number[];
  ma: Record<number, (number | null)[]>;
  dif: (number | null)[];
  hist: (number | null)[];
  rsi: (number | null)[];
  k: (number | null)[];
  d: (number | null)[];
}

export function buildSeries(adjusted: readonly Candle[], tf: Timeframe): Series {
  const bars = resample(adjusted as Candle[], tf);
  const days: number[] = [];
  if (tf === "D") for (let i = 0; i < bars.length; i++) days.push(1);
  else {
    // resample 的桶 t = 該桶最後一天;依序數每桶有幾根日K
    let j = 0;
    for (const b of bars) {
      let n = 0;
      while (j < adjusted.length && adjusted[j].t <= b.t) {
        n++;
        j++;
      }
      days.push(Math.max(1, n));
    }
  }
  const c = bars.map((b) => b.c);
  const h = bars.map((b) => b.h);
  const l = bars.map((b) => b.l);
  const ma: Record<number, (number | null)[]> = {};
  for (const n of MA_BY_TF[tf]) ma[n] = sma(c, n);
  const m = macd(c);
  const kdv = kd(h, l, c);
  return {
    tf,
    t: bars.map((b) => b.t),
    o: bars.map((b) => b.o),
    h,
    l,
    c,
    v: bars.map((b) => b.v),
    days,
    ma,
    dif: m.dif,
    hist: m.hist,
    rsi: rsi(c),
    k: kdv.k,
    d: kdv.d,
  };
}

export interface AllSeries {
  adjusted: Candle[];
  D: Series;
  W: Series;
  M: Series;
}

export function allSeries(candles: readonly Candle[] | null | undefined): AllSeries {
  const adjusted = adjustCandles(candles);
  return { adjusted, D: buildSeries(adjusted, "D"), W: buildSeries(adjusted, "W"), M: buildSeries(adjusted, "M") };
}
