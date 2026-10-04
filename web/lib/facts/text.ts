/**
 * 事實句的片段工具:產句同時產 text 與 segments(價格藍、+ 紅、− 綠),畫面逐段上色,
 * 不靠 changeTokens 的正則猜(≥500 元的股價沒有小數,正則認不出來)。
 */
import type { DerivedFact, Seg, Tf } from "../bullBear.ts";
import { fmtDist, fmtLevelPrice } from "../priceLevels.ts";
import { FACT_CATALOGUE } from "./catalogue.ts";

export const T = (t: string): Seg => ({ t });

/** 價格(台股升降單位小數位,以現價決定) */
export const P = (p: number, close: number): Seg => ({ t: fmtLevelPrice(p, close), kind: "price" });

const signKind = (x: number): Seg["kind"] => (x > 0 ? "up" : x < 0 ? "down" : "flat");

/** 有號百分比(+1.2% / −1.2% / 0.0%) */
export const PCT = (pct: number): Seg => {
  const t = fmtDist(pct);
  return { t, kind: t === "0.0%" ? "flat" : t.startsWith("+") ? "up" : "down" };
};

export const fmtInt = (n: number): string => Math.round(n).toLocaleString("zh-TW");

/** 有號張數(+1,900 張 / −2,245 張) */
export const LOTS = (n: number): Seg => {
  const r = Math.round(n);
  return { t: `${r > 0 ? "+" : r < 0 ? "−" : ""}${fmtInt(Math.abs(r))} 張`, kind: signKind(r) };
};

/** 有號百分點(+0.40 個百分點) */
export const PP = (x: number, digits = 2): Seg => {
  const r = Number(x.toFixed(digits));
  return { t: `${r > 0 ? "+" : r < 0 ? "−" : ""}${Math.abs(r).toFixed(digits)} 個百分點`, kind: signKind(r) };
};

/** 金額(元 → 萬/億),不帶號 */
export function fmtMoney(yuan: number): string {
  if (yuan >= 1e8) return `${(yuan / 1e8).toFixed(1)} 億`;
  return `${fmtInt(yuan / 1e4)} 萬`;
}

/** 無號比例(0.38 → 38%) */
export const share = (x: number, digits = 0): string => `${(x * 100).toFixed(digits)}%`;

export const mmdd = (t: string): string => `${t.slice(5, 7)}/${t.slice(8, 10)}`;

export const joinSegs = (segs: readonly Seg[]): string => segs.map((s) => s.t).join("");

export interface MkOpts {
  tf?: Tf;
  rank?: number;
  magnitude?: number;
  dist?: number;
  mirrors?: string[];
  date?: string;
  dataDate?: string;
  variant?: string;
  /** 壓力段價位的短標(見 DerivedFact.level) */
  level?: Seg[];
}

/** 建一條事實:側別/來源/段/警示都取自 FACT_CATALOGUE;相鄰純文字段合併。 */
export function mk(code: string, segs: readonly (Seg | string | false | null | undefined)[], o: MkOpts = {}): DerivedFact {
  const cat = FACT_CATALOGUE[code];
  if (!cat) throw new Error(`unknown fact code ${code}`);
  const merged: Seg[] = [];
  for (const raw of segs) {
    if (raw == null || raw === false || raw === "") continue;
    const s = typeof raw === "string" ? { t: raw } : raw;
    const last = merged[merged.length - 1];
    if (!s.kind && last && !last.kind) last.t += s.t;
    else merged.push({ ...s });
  }
  const f: DerivedFact = {
    code,
    side: cat.side,
    source: cat.source,
    section: cat.section,
    text: joinSegs(merged),
    segments: merged,
  };
  if (cat.risk) f.risk = true;
  if (o.tf) f.tf = o.tf;
  if (o.rank != null) f.rank = o.rank;
  if (o.magnitude != null && Number.isFinite(o.magnitude)) f.magnitude = o.magnitude;
  if (o.dist != null && Number.isFinite(o.dist)) f.dist = o.dist;
  if (o.date) f.date = o.date;
  if (o.dataDate) f.dataDate = o.dataDate;
  if (o.variant) f.variant = o.variant;
  if (o.level?.length) f.level = o.level;
  if (o.mirrors?.length && !o.date && !o.dataDate) f.mirrors = o.mirrors;
  return f;
}
