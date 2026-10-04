/**
 * 多空分頁「技術分析」段頂的指標列(docs/46 §6):技術分、RSI14、量比、觀察價、失效價。
 * 純函式(node --test 可直接跑);只決定文字與色調,元件只負責畫。
 * 色調沿用 docs/19 §4 既有 token:技術分=技術家族 --primary;RSI 50–70 紅、<50 綠、>80 琥珀(70–80 中性,
 * 同 F8 不列);量比 ≥1.5 依收盤漲跌上紅/綠;價格藍、與收盤距離 +紅 / −綠。
 */
import type { TechnicalSummary } from "./types.ts";
import { fmtDist, fmtLevelPrice } from "./priceLevels.ts";

export type MetricTone = "brand" | "up" | "down" | "warn" | "neutral";

export interface TechMetric {
  key: "score" | "rsi" | "vol" | "watch" | "stop";
  label: string;
  value: string;
  /** 整格的淡底與數值色 */
  tone: MetricTone;
  /** 數值是價格(藍字) */
  price?: boolean;
  /** 與收盤的距離(價格格才有) */
  dist?: { text: string; dir: "up" | "down" | "flat" };
}

export const VOL_SURGE = 1.5;

export function rsiTone(rsi: number | null): MetricTone {
  if (rsi == null) return "neutral";
  if (rsi > 80) return "warn";
  if (rsi < 50) return "down";
  if (rsi <= 70) return "up";
  return "neutral";
}

export function volTone(ratio: number | null, chg: number | null): MetricTone {
  if (ratio == null || ratio < VOL_SURGE || chg == null || chg === 0) return "neutral";
  return chg > 0 ? "up" : "down";
}

export function techMetrics(
  t: TechnicalSummary,
  prices: { watch?: number | null; stop?: number | null },
  close: number | null,
  chg: number | null,
): TechMetric[] {
  const out: TechMetric[] = [
    { key: "score", label: "技術分", value: String(t.score), tone: "brand" },
    { key: "rsi", label: "RSI14", value: t.rsi14 == null ? "—" : t.rsi14.toFixed(1), tone: rsiTone(t.rsi14) },
    { key: "vol", label: "量比", value: t.volume_ratio == null ? "—" : `${t.volume_ratio.toFixed(1)}×`, tone: volTone(t.volume_ratio, chg) },
  ];
  const price = (key: "watch" | "stop", label: string, p: number | null | undefined) => {
    if (p == null) return;
    const m: TechMetric = { key, label, value: close ? fmtLevelPrice(p, close) : p.toFixed(2), tone: "neutral", price: true };
    if (close) {
      const text = fmtDist((p / close - 1) * 100);
      m.dist = { text, dir: text.startsWith("+") ? "up" : text.startsWith("−") ? "down" : "flat" };
    }
    out.push(m);
  };
  price("watch", "觀察價", prices.watch);
  price("stop", "失效價", prices.stop);
  return out;
}
