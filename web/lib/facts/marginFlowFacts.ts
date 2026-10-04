/**
 * 融資增量 × 同期分點囤貨/集保變化(docs/46 §7;Fable 2026-10-04 規格,使用者核定)。純前端、無新後端鍵。
 *
 * 只是「同一期間並列」的觀察,不是歸因:官方只公布每檔融資餘額,沒有分點或帳戶層級,分點也不分現股/融資。
 * 所以文案只寫「融資增量」與「同期囤貨分點」「同期集保大戶變化」並列,不寫誰用融資。
 * 畫面定義句 = priceLevels.MARGIN_FLOW_DEFINITION(籌碼分析段底常駐)。
 *
 * 20 日(每交易日):視窗 = computeWindow 的 20 日視窗(以分點最新日為終點,且不晚於融資最新日);
 * 融資/股價/法人都從視窗前一交易日算到視窗末日(= 20 個交易日的變化)。
 *  1. 顯著:ΔM ≥ max(200 張, 起點餘額 5%),否則不判讀
 *  2. 外資+投信同期淨買 ≥ 0.5×ΔM → 法人主導,不判讀
 *  3. 囤貨分點(排除外資席位)合計 ≥ 0.5×ΔM 且 ≥200 張、股價 ≥ −5%、集保 400 張以上未減 0.3 個百分點以上 → C_MARGIN_UP_CONC(背景)
 *  4. 囤貨合計 < 0.5×ΔM 且股價 ≤ −5% → C_MARGIN_UP_DISPERSED(空方)
 *  5. 其他不判讀
 * 堆積(使用率 ≥60% 才算):起點 = 近 240 筆融資餘額最低日;末/低 ≥1.5 且增 ≥500 張;
 * 分點視窗取與起點距今交易日數最接近的 20/60/120/240;同 2–4 分類,只有集中才列 C_MARGIN_BUILDUP_CONC(背景)。
 */
import type { DerivedFact } from "../bullBear.ts";
import { WINDOWS, computeWindow } from "../accumulation.ts";
import type { Candle, StockJson } from "../types.ts";
import { isForeignBroker } from "./seat.ts";
import { LOTS, PCT, PP, fmtInt, mk, mmdd, share } from "./text.ts";

export const FLOW_DAYS = 20;
export const FLOW_MIN_LOTS = 200;
export const FLOW_MIN_REL = 0.05;
/** 外資+投信同期淨買 ≥ 融資增量的此比例 → 法人主導 */
export const INST_DOMINANT = 0.5;
/** 囤貨分點合計 ÷ 融資增量 ≥ 此值 → 集中 */
export const COV_MIN = 0.5;
export const CONC_MIN_LOTS = 200;
/** 股價變化(%):集中要 ≥ 此值;分散要 ≤ 此值 */
export const PX_DOWN = -5;
/** 集保 400 張以上持股比減少 ≥ 此值(百分點)→ 不算集中 */
export const MAJOR_DOWN = -0.3;
export const BUILDUP_USAGE = 0.6;
export const BUILDUP_RATIO = 1.5;
export const BUILDUP_MIN_LOTS = 500;
export const BUILDUP_LOOKBACK = 240;
const STD_WINDOWS = [20, 60, 120, 240] as const;

type Data = Pick<StockJson, "margin_history" | "branch_history" | "insti_history" | "holders_history">;

export interface MarginFlowResult {
  facts: DerivedFact[];
  /** 有 C_MARGIN_BUILDUP_CONC → C_MARGIN_HOT 降為 rank 2 */
  buildupConc: boolean;
  /** 有 C_MARGIN_UP_DISPERSED → 不再列 5 日 C_MARGIN_UP_PRICE_DOWN */
  dispersed20: boolean;
}

interface Conc { lots: number; count: number; start: string; end: string; days: number }
interface Period { dM: number; inst: number; px: number | null; d400: number | null; dRetail: number | null; hDate: string | null }

/** 囤貨分點(computeWindow 同一套判準),排除外資席位;總公司保留。分點缺日 → null */
function concentration(data: Data, candles: readonly Candle[], days: number, endMax: string): Conc | null {
  const bh = (data.branch_history ?? []).filter((d) => d.t <= endMax);
  const w = computeWindow(bh, candles.map((c) => ({ t: c.t, v: c.v || 0 })), days);
  if (!w.available) return null;
  const foreign = w.acc.filter((r) => isForeignBroker(r.name));
  return {
    lots: w.accTotal - foreign.reduce((s, r) => s + r.net, 0),
    count: w.accCount - foreign.length,
    start: w.start,
    end: w.end,
    days,
  };
}

/** (base, end] 期間的法人、股價、集保變化 */
function period(data: Data, adjusted: readonly Candle[], base: string, end: string, dM: number): Period {
  const inst = (data.insti_history ?? []).filter((r) => r.t > base && r.t <= end).reduce((s, r) => s + (r.foreign ?? 0) + (r.trust ?? 0), 0);
  const closeBy = new Map(adjusted.map((c) => [c.t, c.c]));
  const c0 = closeBy.get(base);
  const c1 = closeBy.get(end);
  const px = c0 && c1 != null ? (c1 / c0 - 1) * 100 : null;
  const hh = (data.holders_history ?? []).filter((p) => p.t > base && p.t <= end).sort((a, b) => a.t.localeCompare(b.t));
  let d400: number | null = null;
  let dRetail: number | null = null;
  let hDate: string | null = null;
  if (hh.length >= 2) {
    const first = hh[0];
    const last = hh[hh.length - 1];
    const a = first.thresholds?.["400"]?.shares_pct;
    const b = last.thresholds?.["400"]?.shares_pct;
    if (a != null && b != null) d400 = b - a;
    if (first.retail_holders && last.retail_holders != null) dRetail = (last.retail_holders / first.retail_holders - 1) * 100;
    hDate = last.t;
  }
  return { dM, inst, px, d400, dRetail, hDate };
}

type Verdict = "conc" | "dispersed" | null;

function classify(p: Period, c: Conc): Verdict {
  if (p.inst >= INST_DOMINANT * p.dM) return null;
  if (p.px == null) return null;
  const cov = c.lots / p.dM;
  if (cov >= COV_MIN && c.lots >= CONC_MIN_LOTS && p.px >= PX_DOWN && !(p.d400 != null && p.d400 <= MAJOR_DOWN)) return "conc";
  if (cov < COV_MIN && p.px <= PX_DOWN) return "dispersed";
  return null;
}

export function marginFlowFacts(data: Data, candles: readonly Candle[], adjusted: readonly Candle[], lastT: string): MarginFlowResult {
  const res: MarginFlowResult = { facts: [], buildupConc: false, dispersed20: false };
  const mh = data.margin_history;
  if (!mh?.length) return res;
  const balBy = new Map(mh.map((r) => [r.t, r.balance]));
  const calendar = candles.map((c) => c.t);

  // ── 20 日 ──
  const c20 = concentration(data, candles, FLOW_DAYS, mh[0].t);
  if (c20) {
    const i = calendar.indexOf(c20.start) - 1;
    const base = i >= 0 ? calendar[i] : null;
    const b0 = base ? balBy.get(base) : null;
    const b1 = balBy.get(c20.end);
    if (base && b0 != null && b0 > 0 && b1 != null) {
      const dM = b1 - b0;
      if (dM >= Math.max(FLOW_MIN_LOTS, FLOW_MIN_REL * b0)) {
        const p = period(data, adjusted, base, c20.end, dM);
        const v = classify(p, c20);
        const date = c20.end !== lastT ? mmdd(c20.end) : undefined;
        const head = ["融資 20 日增加 ", LOTS(dM), "(", PCT((dM / b0) * 100), ")"];
        const hd = p.hDate ? `(集保 ${mmdd(p.hDate)})` : "";
        if (v === "conc") {
          const tail = p.d400 != null ? [";400張以上大戶 ", PP(p.d400), hd] : [];
          res.facts.push(mk("C_MARGIN_UP_CONC", [
            ...head, `,同期囤貨分點 ${c20.count} 家合計淨買超 `, LOTS(c20.lots), `(為融資增量的 ${share(c20.lots / dM)}),股價 20 日 `, PCT(p.px!), ...tail,
          ], { rank: 4, magnitude: (c20.lots / dM) * 100, date }));
        } else if (v === "dispersed") {
          const conc = c20.count > 0 && c20.lots > 0 ? `,同期囤貨分點合計僅為融資增量的 ${share(c20.lots / dM)}` : ",同期無囤貨分點";
          const inst = p.inst < 0 ? `,外資投信合計賣超 ${fmtInt(-p.inst)} 張` : "";
          const hs: (string | ReturnType<typeof PP>)[] = [];
          if (p.d400 != null) hs.push("400張以上大戶 ", PP(p.d400));
          if (p.dRetail != null) hs.push(hs.length ? "、" : "", "未滿400張股東 ", PCT(p.dRetail));
          res.facts.push(mk("C_MARGIN_UP_DISPERSED", [
            ...head, conc, inst, ",股價 20 日 ", PCT(p.px!), ...(hs.length ? [";", ...hs, hd] : []),
          ], { rank: 4, magnitude: (dM / b0) * 100, date }));
          res.dispersed20 = true;
        }
      }
    }
  }

  // ── 堆積視窗(使用率 ≥60% 才算) ──
  const r0 = mh[0];
  if (r0.usage != null && r0.usage >= BUILDUP_USAGE && r0.balance != null) {
    const rows = mh.slice(0, BUILDUP_LOOKBACK);
    let k = -1;
    for (let j = 0; j < rows.length; j++) {
      const b = rows[j].balance;
      if (b != null && b > 0 && (k < 0 || b < rows[k].balance!)) k = j;
    }
    const low = k > 0 ? rows[k] : null;
    if (low && low.balance! > 0) {
      const dM = r0.balance - low.balance!;
      if (r0.balance / low.balance! >= BUILDUP_RATIO && dM >= BUILDUP_MIN_LOTS) {
        const days = STD_WINDOWS.reduce((best, w) => (Math.abs(w - k) < Math.abs(best - k) ? w : best), STD_WINDOWS[0]);
        const c = concentration(data, candles, days, r0.t);
        if (c) {
          const p = period(data, adjusted, low.t, r0.t, dM);
          if (classify(p, c) === "conc") {
            const label = WINDOWS.find((w) => w.days === days)?.label ?? `${days}日`;
            res.facts.push(mk("C_MARGIN_BUILDUP_CONC", [
              `融資餘額自 ${mmdd(low.t)} 的 ${fmtInt(low.balance!)} 張增至 ${fmtInt(r0.balance)} 張(`, LOTS(dM), `,使用率 ${share(r0.usage)});`,
              `近${label}囤貨分點 ${c.count} 家合計淨買超 `, LOTS(c.lots),
              ...(p.d400 != null ? ["、400張以上大戶 ", PP(p.d400)] : []),
              "、股價 ", PCT(p.px!),
            ], { rank: 3, magnitude: (c.lots / dM) * 100, date: r0.t !== lastT ? mmdd(r0.t) : undefined }));
            res.buildupConc = true;
          }
        }
      }
    }
  }
  return res;
}
