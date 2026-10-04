/**
 * 壓力分析段(docs/46 v2 §2.2):上方壓力 / 下方支撐。price_levels(日K,還原價)是權威;
 * 週/月均線價位、歷史最高最低、未回補缺口由還原後的 K 棒自算。每列都帶價位與距離 %。
 * 日K 的 F1(均線在上/下)由 priceLevelFacts 產。
 */
import type { DerivedFact, Tf } from "../bullBear.ts";
import type { PriceLevels } from "../types.ts";
import { extremes, maSideSegs, maSplit } from "../priceLevels.ts";
import type { AllSeries } from "./series.ts";
import { MA_BY_TF } from "./series.ts";
import { P, PCT, mk, mmdd, share } from "./text.ts";

const pct = (price: number, close: number) => ((price - close) / close) * 100;
/** ≤3% 視為「接近」:句尾加註,rank 升到 5(標頭優先) */
const NEAR = 3;
/** 缺口:近 120 根、寬度 ≥ 現價 0.5% 才列,每側最多 2 個 */
const GAP_WINDOW = 120;
const GAP_MIN = 0.005;
const GAP_PER_SIDE = 2;
/** 現價之上/之下成交比例低於 5% 不列(幾乎沒有成交在那一側) */
const SUPPLY_MIN = 0.05;
/** 成交最密集區佔量低於 0.5% 不列(那一側幾乎沒有成交,「最密集」沒有意義) */
const DENSE_MIN = 0.005;

const ymd = (t: string) => `${t.slice(0, 4)}/${t.slice(5, 7)}/${t.slice(8, 10)}`;

function maFactsFor(series: AllSeries, tf: Exclude<Tf, "D">): DerivedFact[] {
  const S = series[tf];
  const i = S.c.length - 1;
  if (i < 0) return [];
  const close = S.c[i];
  const ma: Record<string, number | null> = {};
  for (const n of MA_BY_TF[tf]) ma[String(n)] = S.ma[n]?.[i] ?? null;
  const unit = tf === "W" ? "週" : "月";
  const sp = maSplit(ma, MA_BY_TF[tf].map(String), close);
  const out: DerivedFact[] = [];
  if (sp.nearBelow) {
    const d = Math.abs(pct(sp.nearBelow.v, close));
    out.push(mk("F1_MA_BELOW", maSideSegs("below", sp.below, sp.nearBelow, close, unit), { tf, rank: d <= NEAR ? 3 : 1, dist: d }));
  }
  if (sp.nearAbove) {
    const d = Math.abs(pct(sp.nearAbove.v, close));
    out.push(mk("F1_MA_ABOVE", maSideSegs("above", sp.above, sp.nearAbove, close, unit), { tf, rank: d <= NEAR ? 3 : 1, dist: d }));
  }
  return out;
}

function gapFacts(series: AllSeries, close: number, date?: string): DerivedFact[] {
  const S = series.D;
  const n = S.c.length;
  if (n < 3) return [];
  const i = n - 1;
  const above: { lo: number; hi: number; t: string }[] = [];
  const below: { lo: number; hi: number; t: string }[] = [];
  // 今日的缺口由技術段「今日跳空」講,這裡從昨天往前找
  for (let j = Math.max(1, n - GAP_WINDOW); j < i; j++) {
    if (S.l[j] > S.h[j - 1]) {
      // 向上缺口:之後的最低點把缺口吃掉多少
      const lo = S.h[j - 1];
      let hi = S.l[j];
      for (let k = j + 1; k <= i; k++) hi = Math.min(hi, S.l[k]);
      if (hi - lo >= close * GAP_MIN && hi < close) below.push({ lo, hi, t: S.t[j] });
    } else if (S.h[j] < S.l[j - 1]) {
      let lo = S.h[j];
      const hi = S.l[j - 1];
      for (let k = j + 1; k <= i; k++) lo = Math.max(lo, S.h[k]);
      if (hi - lo >= close * GAP_MIN && lo > close) above.push({ lo, hi, t: S.t[j] });
    }
  }
  const out: DerivedFact[] = [];
  const near = (a: { lo: number; hi: number }) => Math.abs(pct(a.lo > close ? a.lo : a.hi, close));
  above.sort((a, b) => near(a) - near(b)).slice(0, GAP_PER_SIDE).forEach((g, k) => {
    const d = near(g);
    out.push(mk("L_GAP_ABOVE", ["未回補缺口 ", P(g.lo, close), "–", P(g.hi, close), `(${mmdd(g.t)})在上方 `, PCT(d)], { rank: d <= NEAR ? 4 : 2, dist: d, variant: String(k), date }));
  });
  below.sort((a, b) => near(a) - near(b)).slice(0, GAP_PER_SIDE).forEach((g, k) => {
    const d = near(g);
    out.push(mk("L_GAP_BELOW", ["未回補缺口 ", P(g.lo, close), "–", P(g.hi, close), `(${mmdd(g.t)})在下方 `, PCT(-d)], { rank: d <= NEAR ? 4 : 2, dist: d, variant: String(k), date }));
  });
  return out;
}

export function levelFacts(pl: PriceLevels | null | undefined, series: AllSeries, lastT: string): DerivedFact[] {
  const out: DerivedFact[] = [];
  out.push(...maFactsFor(series, "W"), ...maFactsFor(series, "M"));
  if (!pl || pl.status !== "ok") return out;
  const close = pl.close;
  const date = lastT && pl.as_of !== lastT ? mmdd(pl.as_of) : undefined;

  // N 日最高/最低(同價同日合併、標最長視窗;今日即高/低的那個由技術段 F3/F4 講)
  const hi = extremes(pl.highs, pl.as_of).rows;
  const lo = extremes(pl.lows, pl.as_of).rows;
  for (const { n, pt } of hi) {
    const d = pct(pt.p, close);
    out.push(mk("L_HIGH_ABOVE", [`${n}日最高 `, P(pt.p, close), `(${mmdd(pt.t)})在上方 `, PCT(d), d <= NEAR ? ",接近" : ""],
      { rank: d <= NEAR ? 5 : 2, dist: Math.abs(d), magnitude: d <= NEAR ? NEAR - d : undefined, variant: n, date }));
  }
  for (const { n, pt } of lo) {
    const d = pct(pt.p, close);
    out.push(mk("L_LOW_BELOW", [`${n}日最低 `, P(pt.p, close), `(${mmdd(pt.t)})在下方 `, PCT(d), -d <= NEAR ? ",接近" : ""],
      { rank: -d <= NEAR ? 5 : 2, dist: Math.abs(d), variant: n, date }));
  }

  // 資料內最高/最低(全部 K 棒;與 240 日同價則不另列)
  const A = series.D;
  if (A.c.length > 240) {
    let hiI = 0;
    let loI = 0;
    for (let j = 0; j < A.c.length; j++) {
      if (A.h[j] >= A.h[hiI]) hiI = j;
      if (A.l[j] <= A.l[loI]) loI = j;
    }
    const years = ((Date.parse(A.t[A.t.length - 1]) - Date.parse(A.t[0])) / 864e5 / 365.25).toFixed(1);
    const h240 = pl.highs["240"]?.p;
    const l240 = pl.lows["240"]?.p;
    const last = A.c.length - 1;
    if (hiI !== last && A.h[hiI] > close && (h240 == null || Math.abs(A.h[hiI] / h240 - 1) > 0.001)) {
      const d = pct(A.h[hiI], close);
      out.push(mk("L_ALLTIME_HIGH", [`近 ${years} 年資料最高 `, P(A.h[hiI], close), `(${ymd(A.t[hiI])})在上方 `, PCT(d)], { rank: 1, dist: Math.abs(d), date }));
    }
    if (loI !== last && A.l[loI] < close && (l240 == null || Math.abs(A.l[loI] / l240 - 1) > 0.001)) {
      const d = pct(A.l[loI], close);
      out.push(mk("L_ALLTIME_LOW", [`近 ${years} 年資料最低 `, P(A.l[loI], close), `(${ymd(A.t[loI])})在下方 `, PCT(d)], { rank: 1, dist: Math.abs(d), date }));
    }
  }

  // 成交最密集區
  if (pl.dense_above && pl.dense_above.share >= DENSE_MIN) {
    const z = pl.dense_above;
    const d = pct(z.lo, close);
    out.push(mk("L_DENSE_ABOVE", ["成交最密集區 ", P(z.lo, close), "–", P(z.hi, close), " 在上方 ", PCT(d), `(佔近120日成交 ${share(z.share, z.share < 0.1 ? 1 : 0)})`, d <= NEAR ? ",接近" : ""],
      { rank: d <= NEAR ? 5 : 2, dist: Math.abs(d), date }));
  }
  if (pl.dense_below && pl.dense_below.share >= DENSE_MIN) {
    const z = pl.dense_below;
    const d = pct(z.hi, close);
    out.push(mk("L_DENSE_BELOW", ["成交最密集區 ", P(z.lo, close), "–", P(z.hi, close), " 在下方 ", PCT(d), `(佔近120日成交 ${share(z.share, z.share < 0.1 ? 1 : 0)})`, -d <= NEAR ? ",接近" : ""],
      { rank: -d <= NEAR ? 5 : 2, dist: Math.abs(d), date }));
  }

  // 現價之上/之下成交比例:兩側都列(使用者要「全列」);達門檻(之上 ≥30%、之下 ≥70%)者 rank 較高
  const vp = pl.vol_profile;
  if (vp) {
    if (vp.above >= SUPPLY_MIN) out.push(mk("L_SUPPLY_ABOVE", [`近${vp.window}日成交 ${share(vp.above)} 在現價之上`], { rank: vp.above >= 0.3 ? 2 : 1, magnitude: vp.above, date }));
    if (vp.below >= SUPPLY_MIN) out.push(mk("L_SUPPLY_BELOW", [`近${vp.window}日成交 ${share(vp.below)} 在現價之下`], { rank: vp.below >= 0.7 ? 2 : 1, magnitude: vp.below, date }));
  }

  out.push(...gapFacts(series, close, date));

  // 60 日高低區間位置
  const h60 = pl.highs["60"]?.p;
  const l60 = pl.lows["60"]?.p;
  if (h60 != null && l60 != null && h60 > l60) {
    const pos = (close - l60) / (h60 - l60);
    const txt = `(區間 ${Math.round(pos * 100)}%)`;
    if (pos >= 0.9) out.push(mk("L_RANGE_POS_TOP", ["收盤位於近60日高低區間上緣", txt], { rank: 2, mirrors: ["T3_BOX_TOP"], date }));
    else if (pos <= 0.1) out.push(mk("L_RANGE_POS_BOTTOM", ["收盤位於近60日高低區間下緣", txt], { rank: 2, date }));
  }
  return out;
}
