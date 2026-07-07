/** 前端技術指標計算(對完整 candles 序列計算,再依可視區間切片,避免視窗邊緣均線斷裂) */

export function sma(values: (number | null)[], n: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  let sum = 0;
  let cnt = 0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (v == null) {
      // 缺值:重置視窗(日線資料極少缺,簡化處理)
      sum = 0;
      cnt = 0;
      continue;
    }
    sum += v;
    cnt++;
    if (cnt > n) {
      sum -= values[i - n] as number;
      cnt = n;
    }
    if (cnt === n) out[i] = sum / n;
  }
  return out;
}

function emaSeries(values: (number | null)[], n: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  const alpha = 2 / (n + 1);
  let prev: number | null = null;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (v == null) continue;
    prev = prev == null ? v : v * alpha + prev * (1 - alpha);
    out[i] = prev;
  }
  return out;
}

export function bollinger(closes: (number | null)[], n = 20, k = 2) {
  const mid = sma(closes, n);
  const upper: (number | null)[] = new Array(closes.length).fill(null);
  const lower: (number | null)[] = new Array(closes.length).fill(null);
  for (let i = 0; i < closes.length; i++) {
    if (mid[i] == null) continue;
    let s = 0;
    let ok = true;
    for (let j = i - n + 1; j <= i; j++) {
      const v = closes[j];
      if (v == null) {
        ok = false;
        break;
      }
      s += (v - (mid[i] as number)) ** 2;
    }
    if (!ok) continue;
    const sd = Math.sqrt(s / n);
    upper[i] = (mid[i] as number) + k * sd;
    lower[i] = (mid[i] as number) - k * sd;
  }
  return { mid, upper, lower };
}

export function macd(closes: (number | null)[], fast = 12, slow = 26, signal = 9) {
  const ef = emaSeries(closes, fast);
  const es = emaSeries(closes, slow);
  const dif: (number | null)[] = closes.map((_, i) =>
    ef[i] == null || es[i] == null ? null : (ef[i] as number) - (es[i] as number),
  );
  const dea = emaSeries(dif, signal);
  const hist = dif.map((v, i) => (v == null || dea[i] == null ? null : v - (dea[i] as number)));
  return { dif, dea, hist };
}

export function rsi(closes: (number | null)[], n = 14): (number | null)[] {
  const out: (number | null)[] = new Array(closes.length).fill(null);
  let avgGain: number | null = null;
  let avgLoss: number | null = null;
  let seenChanges = 0;
  let gainSum = 0;
  let lossSum = 0;
  for (let i = 1; i < closes.length; i++) {
    const a = closes[i - 1];
    const b = closes[i];
    if (a == null || b == null) continue;
    const chg = b - a;
    const gain = Math.max(chg, 0);
    const loss = Math.max(-chg, 0);
    seenChanges++;
    if (seenChanges <= n) {
      gainSum += gain;
      lossSum += loss;
      if (seenChanges === n) {
        avgGain = gainSum / n;
        avgLoss = lossSum / n;
      }
    } else {
      avgGain = ((avgGain as number) * (n - 1) + gain) / n;
      avgLoss = ((avgLoss as number) * (n - 1) + loss) / n;
    }
    if (avgGain != null && avgLoss != null) {
      out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
    }
  }
  return out;
}

export function kd(
  highs: (number | null)[],
  lows: (number | null)[],
  closes: (number | null)[],
  n = 9,
) {
  const k: (number | null)[] = new Array(closes.length).fill(null);
  const d: (number | null)[] = new Array(closes.length).fill(null);
  let kPrev = 50;
  let dPrev = 50;
  for (let i = 0; i < closes.length; i++) {
    if (i + 1 >= n && closes[i] != null) {
      let hi = -Infinity;
      let lo = Infinity;
      let ok = true;
      for (let j = i - n + 1; j <= i; j++) {
        if (highs[j] == null || lows[j] == null) {
          ok = false;
          break;
        }
        hi = Math.max(hi, highs[j] as number);
        lo = Math.min(lo, lows[j] as number);
      }
      if (ok && hi > lo) {
        const rsv = (((closes[i] as number) - lo) / (hi - lo)) * 100;
        kPrev = (kPrev * 2) / 3 + rsv / 3;
        dPrev = (dPrev * 2) / 3 + kPrev / 3;
      }
    }
    k[i] = kPrev;
    d[i] = dPrev;
  }
  return { k, d };
}
