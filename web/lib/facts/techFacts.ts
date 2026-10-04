/**
 * 技術分析段(docs/46 v2 §2.1):日/週/月 K 的均線排列與斜率、交叉、MACD、KD、RSI、量價、創高低、
 * 連漲連跌、單日/5 日幅度、跳空、長黑。日K 的 F2/F3/F4/F5/F8 由 priceLevelFacts 產(price_levels 權威),
 * 這裡只產週/月版。每個週期每個指標最多一列(事件優先於狀態)。
 */
import type { DerivedFact, Tf } from "../bullBear.ts";
import type { TechnicalSummary } from "../types.ts";
import type { AllSeries, Series } from "./series.ts";
import { P, PCT, T, mk } from "./text.ts";

const UNIT: Record<Tf, string> = { D: "日", W: "週", M: "月" };
/** 事件型句尾:週/月最後一根是進行中的那根 */
const EV: Record<Tf, string> = { D: "", W: "(本週)", M: "(本月)" };
const NOW: Record<Tf, string> = { D: "今日", W: "", M: "" };
/** 數量單位:連 3 日、5 週前、5 個月前 */
const CNT: Record<Tf, string> = { D: "日", W: "週", M: "個月" };

const pctChg = (a: number, b: number) => (b ? (a / b - 1) * 100 : 0);
/** 週/月事實的 rank 比日K低一級,標頭優先挑當天的事 */
const rk = (tf: Tf, r: number) => (tf === "D" ? r : Math.max(1, r - 1));

function avg(xs: number[]): number {
  return xs.length ? xs.reduce((s, x) => s + x, 0) / xs.length : 0;
}

function forTf(S: Series, tf: Tf, technical: TechnicalSummary | null): DerivedFact[] {
  const out: DerivedFact[] = [];
  const n = S.c.length;
  if (n < 2) return out;
  const i = n - 1;
  const p = i - 1;
  const u = UNIT[tf];
  const ev = EV[tf];
  const now = NOW[tf];
  const cnt = CNT[tf];
  const close = S.c[i];
  const add = (code: string, segs: Parameters<typeof mk>[1], o: Parameters<typeof mk>[2] = {}) => out.push(mk(code, segs, { tf, ...o }));

  // 均線排列(日K 由 F2)
  if (tf !== "D") {
    const [m5, m10, m20] = [S.ma[5]?.[i], S.ma[10]?.[i], S.ma[20]?.[i]];
    if (m5 != null && m10 != null && m20 != null) {
      if (m5 > m10 && m10 > m20) add("X_ALIGN_BULL", [`5/10/20${u}線多頭排列`], { rank: rk(tf, 3) });
      else if (m5 < m10 && m10 < m20) add("X_ALIGN_BEAR", [`5/10/20${u}線空頭排列`], { rank: rk(tf, 3) });
    }
  }

  // 均線斜率:較 5 根前 ≥ +0.5% / ≤ −0.5%
  const slopes: Array<[number, string, string]> = [[20, "X_MA20_SLOPE_UP", "X_MA20_SLOPE_DOWN"]];
  if (tf !== "M") slopes.push([60, "X_MA60_SLOPE_UP", "X_MA60_SLOPE_DOWN"]);
  for (const [w, up, dn] of slopes) {
    const a = S.ma[w]?.[i];
    const b = S.ma[w]?.[i - 5];
    if (a == null || b == null) continue;
    const s = pctChg(a, b);
    const segs = [`${w}${u}均線較5${cnt}前 `, PCT(s)];
    if (s >= 0.5) add(up, segs, { rank: rk(tf, 2), magnitude: Math.abs(s) });
    else if (s <= -0.5) add(dn, segs, { rank: rk(tf, 2), magnitude: Math.abs(s) });
  }

  // 收盤站回 / 跌破 20 均線
  {
    const a = S.ma[20]?.[i];
    const b = S.ma[20]?.[p];
    if (a != null && b != null) {
      if (S.c[p] < b && close >= a) add("X_MA_CROSS_UP", [`收盤${now}站回20${u}線 `, P(a, close), ev], { rank: rk(tf, 4) });
      else if (S.c[p] >= b && close < a) add("X_MA_CROSS_DOWN", [`收盤${now}跌破20${u}線 `, P(a, close), ev], { rank: rk(tf, 5) });
    }
  }

  // MACD:交叉優先,否則零軸上下 + 柱狀體連續根數
  if (n >= 35) {
    const h0 = S.hist[i];
    const h1 = S.hist[p];
    const dif = S.dif[i];
    if (h0 != null && h1 != null && dif != null) {
      if (h1 <= 0 && h0 > 0) add("X_MACD_CROSS_UP", [`MACD柱狀體${now}翻正${ev}`], { rank: rk(tf, 5), mirrors: tf === "D" ? ["T5_MACD_HIST_POS"] : undefined });
      else if (h1 >= 0 && h0 < 0) add("X_MACD_CROSS_DOWN", [`MACD柱狀體${now}翻負${ev}`], { rank: rk(tf, 5) });
      else {
        let k = 0;
        for (let j = i; j >= 0 && S.hist[j] != null && Math.sign(S.hist[j] as number) === Math.sign(h0) && h0 !== 0; j--) k++;
        if (dif > 0 && h0 > 0) add("X_MACD_STATE_POS", [`MACD 位於零軸之上,柱狀體連 ${k} ${cnt}為正`], { rank: rk(tf, 2) });
        else if (dif < 0 && h0 < 0) add("X_MACD_STATE_NEG", [`MACD 位於零軸之下,柱狀體連 ${k} ${cnt}為負`], { rank: rk(tf, 2) });
      }
    }
  }

  // KD:50 以下黃金交叉 / 50 以上死亡交叉;非交叉日 K > 80
  if (n >= 20) {
    const [k0, d0, k1, d1] = [S.k[i], S.d[i], S.k[p], S.d[p]];
    if (k0 != null && d0 != null && k1 != null && d1 != null) {
      const kTxt = `(K ${Math.round(k0)})`;
      if (k0 > d0 && k1 <= d1 && k0 < 50 && d0 < 50)
        add("X_KD_GOLDEN_LOW", [`KD於50以下黃金交叉${kTxt}${ev}`], { rank: rk(tf, 4), mirrors: tf === "D" ? ["T5_KD_GOLDEN_LOW"] : undefined });
      else if (k0 < d0 && k1 >= d1 && k0 > 50 && d0 > 50) add("X_KD_DEATH_HIGH", [`KD於50以上死亡交叉${kTxt}${ev}`], { rank: rk(tf, 4) });
      else if (k0 > 80) add("X_KD_OVER80", [`K值 ${Math.round(k0)},高於 80`], { rank: rk(tf, 2) });
    }
  }

  // RSI14(日K 由 F8;週/月 >80 不列——週/月不產 R_*)
  if (tf !== "D") {
    const r = S.rsi[i];
    if (r != null) {
      if (r >= 50 && r <= 70) add("F8_RSI_OK", [`RSI14 ${Math.round(r)},位於 50–70`], { rank: rk(tf, 2) });
      else if (r < 50) add("F8_RSI_LOW", [`RSI14 ${Math.round(r)},低於 50`], { rank: rk(tf, 2) });
    }
  }

  // 量:日均量對前 20 根日均量(日K 優先用 technical.volume_ratio)
  const perDay = S.v.map((v, j) => v / S.days[j]);
  let ratio: number | null = null;
  if (tf === "D" && technical?.volume_ratio != null) ratio = technical.volume_ratio;
  else if (n >= 21) {
    const base = avg(perDay.slice(i - 20, i));
    if (base > 0) ratio = perDay[i] / base;
  }
  const chg = pctChg(close, S.c[p]);
  if (ratio != null) {
    const r = ratio.toFixed(1);
    if (ratio >= 1.5 && chg > 0) add("X_VOL_SURGE_UP", [`成交量為20${u}均量 ${r} 倍,收漲 `, PCT(chg), ev], { rank: rk(tf, 4), magnitude: ratio, mirrors: tf === "D" ? ["T2_VOLUME_BREAKOUT"] : undefined });
    else if (ratio >= 1.5 && chg < 0) add("X_VOL_SURGE_DOWN", [`成交量為20${u}均量 ${r} 倍,收跌 `, PCT(chg), ev], { rank: rk(tf, 4), magnitude: ratio });
    else if (ratio <= 0.5 && tf !== "M") add("X_VOL_DRY", [`成交量為20${u}均量 ${r} 倍`], { rank: 1 });
  }

  // 週/月:連 2 根量增價漲/跌、創 20 根新高/低(日K 由 F4/F5)
  if (tf !== "D" && n >= 3) {
    const [v0, v1, v2] = [perDay[i - 2], perDay[p], perDay[i]];
    const [c0, c1, c2] = [S.c[i - 2], S.c[p], close];
    if (v2 > v1 && v1 > v0) {
      if (c2 > c1 && c1 > c0) add("F5_UP", [`連2${cnt}量增價漲${ev}`], { rank: rk(tf, 3) });
      else if (c2 < c1 && c1 < c0) add("F5_DOWN", [`連2${cnt}量增價跌${ev}`], { rank: rk(tf, 3) });
    }
  }
  if (tf !== "D" && n >= 21) {
    const prior = S.c.slice(i - 20, i);
    if (close > Math.max(...prior)) add("F4_NEW_HIGH", [`收盤創20${cnt}新高${ev}`], { rank: rk(tf, 4) });
    else if (close < Math.min(...prior)) add("F4_NEW_LOW", [`收盤創20${cnt}新低${ev}`], { rank: rk(tf, 4) });
  }

  // 連漲 / 連跌(日、週)
  if (tf !== "M") {
    let k = 0;
    const dir = Math.sign(close - S.c[p]);
    if (dir !== 0) for (let j = i; j >= 1 && Math.sign(S.c[j] - S.c[j - 1]) === dir; j--) k++;
    if (k >= 3) {
      const cum = pctChg(close, S.c[i - k]);
      const unitWord = tf === "D" ? "日" : "週";
      if (dir > 0) add("X_UP_STREAK", [`連 ${k} ${unitWord}收漲,累計 `, PCT(cum)], { rank: rk(tf, 3), magnitude: Math.abs(cum) });
      else add("X_DOWN_STREAK", [`連 ${k} ${unitWord}收跌,累計 `, PCT(cum)], { rank: rk(tf, 3), magnitude: Math.abs(cum) });
    }
  }

  if (tf === "D") {
    if (chg >= 3) add("X_CHG1_UP", ["今日上漲 ", PCT(chg)], { rank: 4, magnitude: Math.abs(chg) });
    else if (chg <= -3) add("X_CHG1_DOWN", ["今日下跌 ", PCT(chg)], { rank: 4, magnitude: Math.abs(chg) });
    if (n >= 6) {
      const c5 = pctChg(close, S.c[i - 5]);
      if (c5 >= 8) add("X_CHG5_UP", ["近 5 日上漲 ", PCT(c5)], { rank: 3, magnitude: c5 });
      else if (c5 <= -8) add("X_CHG5_DOWN", ["近 5 日下跌 ", PCT(c5)], { rank: 3, magnitude: -c5 });
    }
    // 今日跳空(缺口 ≥ 前一日收盤 1%)
    if (S.l[i] > S.h[p] && (S.l[i] - S.h[p]) / S.c[p] >= 0.01)
      add("X_GAP_UP_TODAY", ["今日跳空上漲 ", PCT(chg), ",缺口 ", P(S.h[p], close), "–", P(S.l[i], close), " 未回補"], { rank: 4 });
    else if (S.h[i] < S.l[p] && (S.l[p] - S.h[i]) / S.c[p] >= 0.01)
      add("X_GAP_DOWN_TODAY", ["今日跳空下跌 ", PCT(chg), ",缺口 ", P(S.h[i], close), "–", P(S.l[p], close), " 未回補"], { rank: 4 });
    // 長黑:收黑實體 ≥ 3%、上影線短於實體
    const o = S.o[i];
    if (o > close && (o - close) / o >= 0.03 && S.h[i] - o < o - close)
      add("X_BIG_BLACK", ["今日收長黑 K,實體 ", PCT(pctChg(close, o))], { rank: 4, magnitude: pctChg(o, close) });
  }
  return out;
}

export function techFacts(series: AllSeries, technical: TechnicalSummary | null): DerivedFact[] {
  return [...forTf(series.D, "D", technical), ...forTf(series.W, "W", technical), ...forTf(series.M, "M", technical)];
}
