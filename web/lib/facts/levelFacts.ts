/**
 * 壓力分析段(docs/46 v2 §2.2):上方壓力 / 下方支撐。price_levels(日K,還原價)是權威;
 * 週/月均線價位、歷史最高最低、未回補缺口由還原後的 K 棒自算。每列都帶價位與距離 %。
 * 日K 的 F1(均線在上/下)由 priceLevelFacts 產。
 */
import type { DerivedFact, Seg, Tf } from "../bullBear.ts";
import type { PriceLevels } from "../types.ts";
import { AT_PRICE, GAP_LABEL, NEAR_PCT, denseZone, distSeg, extremes, isAtPrice, isNear, levelGaps, maLevelSegs, maSideSegs, maSplit, type OkLevels } from "../priceLevels.ts";
import type { AllSeries } from "./series.ts";
import { MA_BY_TF } from "./series.ts";
import { P, mk, mmdd, share } from "./text.ts";

const pct = (price: number, close: number) => ((price - close) / close) * 100;
/** ≤3% 視為「接近」:句尾加註,rank 升級(標頭優先);與技術段 nearLevelFacts 同一門檻 */
const NEAR = NEAR_PCT;
/**
 * 單一價位的「在上方 +1.2%」/「在下方 −1.2%」;距離四捨五入為 0 時改寫「貼近現價」(不寫「在上方 0.0%」)。
 * d 帶號(上方 +、下方 −)。
 */
const sideDist = (side: "above" | "below", d: number): (Seg | string)[] => (isAtPrice(d) ? [AT_PRICE] : [side === "above" ? "在上方 " : "在下方 ", distSeg(d)]);
/**
 * 成交最密集區的位置:格子以現價為錨(現價 1% 一格),最近的一格就從現價起算,邊緣等於現價是常態、現價不會落在格子裡面。
 * 那時寫「自現價向上/向下」——這一格的量全在現價之上/之下,仍是該側最近的價位,不寫「現價位於區內」也不寫 0.0%。
 */
const zoneDist = (side: "above" | "below", d: number): (Seg | string)[] =>
  isAtPrice(d) ? [side === "above" ? " 自現價向上" : " 自現價向下"] : [side === "above" ? " 在上方 " : " 在下方 ", distSeg(d)];
/** 句尾「,接近」:≤3% 才加;已寫「貼近現價」的不再重複 */
const nearTag = (d: number) => (isNear(d) && !isAtPrice(d) ? ",接近" : "");
/** 缺口(舊 JSON 回退算法,與 pipeline price_levels.py F9 同一條定義):近 120 根、寬度 ≥ 現價 0.5% 才列,每側最多 2 個 */
const GAP_WINDOW = 120;
const GAP_MIN = 0.005;
const GAP_PER_SIDE = 2;
/** 現價之上/之下成交比例低於 5% 不列(幾乎沒有成交在那一側) */
const SUPPLY_MIN = 0.05;
const ymd = (t: string) => `${t.slice(0, 4)}/${t.slice(5, 7)}/${t.slice(8, 10)}`;
/** 區間價位的短標(DerivedFact.level):「成交最密集區 1,100–1,111」 */
const rangeLevel = (label: string, z: { lo: number; hi: number }, close: number): Seg[] => [{ t: label }, P(z.lo, close), { t: "–" }, P(z.hi, close)];
const gapLevel = (g: { lo: number; hi: number }, close: number) => rangeLevel(`${GAP_LABEL} `, g, close);

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
    out.push(mk("F1_MA_BELOW", maSideSegs("below", sp.below, sp.nearBelow, close, unit), { tf, rank: isNear(d) ? 3 : 1, dist: d, level: maLevelSegs(sp.nearBelow, close, unit) }));
  }
  if (sp.nearAbove) {
    const d = Math.abs(pct(sp.nearAbove.v, close));
    out.push(mk("F1_MA_ABOVE", maSideSegs("above", sp.above, sp.nearAbove, close, unit), { tf, rank: isNear(d) ? 3 : 1, dist: d, level: maLevelSegs(sp.nearAbove, close, unit) }));
  }
  return out;
}

type Gap = { lo: number; hi: number; t: string };

/** 舊 JSON(price_levels version 1)沒有 gaps_* 鍵時,從還原日K 自算;定義與 pipeline 相同。 */
function gapsFromSeries(series: AllSeries, close: number): { above: Gap[]; below: Gap[] } {
  const S = series.D;
  const n = S.c.length;
  const above: Gap[] = [];
  const below: Gap[] = [];
  if (n < 3) return { above, below };
  const i = n - 1;
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
  const near = (a: Gap) => Math.abs(pct(a.lo > close ? a.lo : a.hi, close));
  return { above: above.sort((a, b) => near(a) - near(b)).slice(0, GAP_PER_SIDE), below: below.sort((a, b) => near(a) - near(b)).slice(0, GAP_PER_SIDE) };
}

/**
 * 未回補缺口:price_levels 有 gaps_*(version ≥2)就用它(與價格階梯、K 線虛線同一份 `levelGaps`),
 * 舊 JSON 回退為 K 棒自算。每側 ≤2、近者在前,句型相同。
 */
function gapFacts(pl: OkLevels, series: AllSeries, close: number, date?: string): DerivedFact[] {
  const fromPl = { above: levelGaps(pl, "above"), below: levelGaps(pl, "below") };
  const fb = fromPl.above && fromPl.below ? null : gapsFromSeries(series, close);
  const above = fromPl.above ?? fb!.above;
  const below = fromPl.below ?? fb!.below;
  const out: DerivedFact[] = [];
  above.forEach((g, k) => {
    const d = Math.abs(pct(g.lo, close));
    out.push(mk("L_GAP_ABOVE", [`${GAP_LABEL} `, P(g.lo, close), "–", P(g.hi, close), `(${mmdd(g.t)})`, ...sideDist("above", d)], { rank: isNear(d) ? 4 : 2, dist: d, variant: String(k), date, level: gapLevel(g, close) }));
  });
  below.forEach((g, k) => {
    const d = Math.abs(pct(g.hi, close));
    out.push(mk("L_GAP_BELOW", [`${GAP_LABEL} `, P(g.lo, close), "–", P(g.hi, close), `(${mmdd(g.t)})`, ...sideDist("below", -d)], { rank: isNear(d) ? 4 : 2, dist: d, variant: String(k), date, level: gapLevel(g, close) }));
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
    out.push(mk("L_HIGH_ABOVE", [`${n}日最高 `, P(pt.p, close), `(${mmdd(pt.t)})`, ...sideDist("above", d), nearTag(d)],
      { rank: isNear(d) ? 5 : 2, dist: Math.abs(d), magnitude: isNear(d) ? Math.max(0, NEAR - d) : undefined, variant: n, date, level: [{ t: `${n}日最高 ` }, P(pt.p, close)] }));
  }
  for (const { n, pt } of lo) {
    const d = pct(pt.p, close);
    out.push(mk("L_LOW_BELOW", [`${n}日最低 `, P(pt.p, close), `(${mmdd(pt.t)})`, ...sideDist("below", d), nearTag(d)],
      { rank: isNear(-d) ? 5 : 2, dist: Math.abs(d), variant: n, date, level: [{ t: `${n}日最低 ` }, P(pt.p, close)] }));
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
      out.push(mk("L_ALLTIME_HIGH", [`近 ${years} 年資料最高 `, P(A.h[hiI], close), `(${ymd(A.t[hiI])})`, ...sideDist("above", d)],
        { rank: 1, dist: Math.abs(d), date, level: [{ t: `近 ${years} 年資料最高 ` }, P(A.h[hiI], close)] }));
    }
    if (loI !== last && A.l[loI] < close && (l240 == null || Math.abs(A.l[loI] / l240 - 1) > 0.001)) {
      const d = pct(A.l[loI], close);
      out.push(mk("L_ALLTIME_LOW", [`近 ${years} 年資料最低 `, P(A.l[loI], close), `(${ymd(A.t[loI])})`, ...sideDist("below", d)],
        { rank: 1, dist: Math.abs(d), date, level: [{ t: `近 ${years} 年資料最低 ` }, P(A.l[loI], close)] }));
    }
  }

  // 成交最密集區(佔量門檻與價格階梯同一個 denseZone)
  const za = denseZone(pl, "above");
  if (za) {
    const d = pct(za.lo, close);
    out.push(mk("L_DENSE_ABOVE", ["成交最密集區 ", P(za.lo, close), "–", P(za.hi, close), ...zoneDist("above", d), `(佔近120日成交 ${share(za.share, za.share < 0.1 ? 1 : 0)})`, nearTag(d)],
      { rank: isNear(d) ? 5 : 2, dist: Math.abs(d), date, level: rangeLevel("成交最密集區 ", za, close) }));
  }
  const zb = denseZone(pl, "below");
  if (zb) {
    const d = pct(zb.hi, close);
    out.push(mk("L_DENSE_BELOW", ["成交最密集區 ", P(zb.lo, close), "–", P(zb.hi, close), ...zoneDist("below", d), `(佔近120日成交 ${share(zb.share, zb.share < 0.1 ? 1 : 0)})`, nearTag(d)],
      { rank: isNear(-d) ? 5 : 2, dist: Math.abs(d), date, level: rangeLevel("成交最密集區 ", zb, close) }));
  }

  // 現價之上/之下成交比例:兩側都列(使用者要「全列」);達門檻(之上 ≥30%、之下 ≥70%)者 rank 較高
  const vp = pl.vol_profile;
  if (vp) {
    if (vp.above >= SUPPLY_MIN) out.push(mk("L_SUPPLY_ABOVE", [`近${vp.window}日成交 ${share(vp.above)} 在現價之上`], { rank: vp.above >= 0.3 ? 2 : 1, magnitude: vp.above, date }));
    if (vp.below >= SUPPLY_MIN) out.push(mk("L_SUPPLY_BELOW", [`近${vp.window}日成交 ${share(vp.below)} 在現價之下`], { rank: vp.below >= 0.7 ? 2 : 1, magnitude: vp.below, date }));
  }

  out.push(...gapFacts(pl, series, close, date));

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

/** 技術段「3% 內壓力/支撐價位」句最多點名幾個價位,其餘寫「等 N 處」 */
const NEAR_NAMED = 2;
/**
 * 技術段的近距壓力/支撐(docs/46 §6.9):從壓力段**已產出的價位事實**(priceLevelFacts + levelFacts,帶 level 短標者)
 * 挑距現價 ≤ NEAR_PCT 的,上方併成一句空方、下方併成一句多方,放技術段日K。
 * 與壓力段同一份事實、同一個門檻:壓力分析標「接近」的價位,技術分析的多空欄一定也看得到。
 * rank 固定 3:不進多方榜的 K_bull/K_bear(rank ≥4)與排除條件(rank 5),也不搶標頭(同價位的壓力段事實 rank 更高或段序在前)。
 */
export function nearLevelFacts(facts: readonly DerivedFact[]): DerivedFact[] {
  const out: DerivedFact[] = [];
  for (const side of ["bear", "bull"] as const) {
    const near = facts
      .filter((f) => f.section === "levels" && f.side === side && f.level && f.dist != null && isNear(f.dist))
      .map((f, i) => ({ f, i }))
      .sort((a, b) => a.f.dist! - b.f.dist! || a.i - b.i)
      .map(({ f }) => f);
    if (!near.length) continue;
    const segs: (Seg | string)[] = [side === "bear" ? `上方 ${NEAR}% 內有壓力價位:` : `下方 ${NEAR}% 內有支撐價位:`];
    near.slice(0, NEAR_NAMED).forEach((f, k) => {
      if (k) segs.push("、");
      segs.push(...f.level!, "(", distSeg(side === "bear" ? f.dist! : -f.dist!), ")");
    });
    if (near.length > NEAR_NAMED) segs.push(`等 ${near.length} 處`);
    const date = near.find((f) => f.date)?.date;
    out.push(mk(side === "bear" ? "X_LEVEL_ABOVE_NEAR" : "X_LEVEL_BELOW_NEAR", segs, { tf: "D", rank: 3, date }));
  }
  return out;
}
