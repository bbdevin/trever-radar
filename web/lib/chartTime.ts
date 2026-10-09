/**
 * lightweight-charts 的時間標籤(十字線 + 時間軸刻度),K 線圖與首頁走勢圖共用。純函式,node --test 直接跑。
 *
 * 圖表收到的 time 有兩種(見 resample.ts `chartTimeOf`):
 * - 日K以上:"YYYY-MM-DD" 字串;
 * - 分K:台北牆上時間「當成 UTC」的秒數(epoch + 8h)。所以一律讀 UTC 欄位,
 *   不經瀏覽器時區 —— 不論使用者在哪個時區,09:00 開盤都顯示 09:00。
 * 另外容忍 BusinessDay 物件 { year, month, day }(本專案不傳,但 lightweight-charts 的 Time 型別允許)。
 */

interface TimeParts {
  y: number;
  m: number;
  d: number;
  /** 只有分K(秒數)才有時刻 */
  hh?: number;
  mm?: number;
}

const pad2 = (n: number) => String(n).padStart(2, "0");

export function chartTimeParts(t: unknown): TimeParts | null {
  if (typeof t === "string") {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(t);
    return m ? { y: Number(m[1]), m: Number(m[2]), d: Number(m[3]) } : null;
  }
  if (typeof t === "number" && Number.isFinite(t)) {
    const dt = new Date(t * 1000);
    return { y: dt.getUTCFullYear(), m: dt.getUTCMonth() + 1, d: dt.getUTCDate(), hh: dt.getUTCHours(), mm: dt.getUTCMinutes() };
  }
  if (t && typeof t === "object") {
    const b = t as { year?: unknown; month?: unknown; day?: unknown };
    if (typeof b.year === "number" && typeof b.month === "number" && typeof b.day === "number") {
      return { y: b.year, m: b.month, d: b.day };
    }
  }
  return null;
}

/**
 * 十字線上的時間標籤(`localization.timeFormatter`):
 * 日K「10/07」;週K/月K(`withYear`)「2026/10/07」—— 一根跨一週/一月、圖常跨好幾年,不帶年讀不出是哪年;
 * 分K「10/06 11:55」(台北時間)。
 */
export function crosshairTimeLabel(t: unknown, withYear = false): string {
  const p = chartTimeParts(t);
  if (!p) return String(t);
  const md = `${pad2(p.m)}/${pad2(p.d)}`;
  if (p.hh != null && p.mm != null) return `${md} ${pad2(p.hh)}:${pad2(p.mm)}`;
  return withYear ? `${p.y}/${md}` : md;
}

/**
 * 時間軸刻度(`timeScale.tickMarkFormatter`);tickType = lightweight-charts TickMarkType:
 * 0 年 →「2026年」、1 月 →「9月」、2 日 →「10/07」、3/4 時刻 →「11:55」(分K一天之內;換日那根是 2 → MM/DD)。
 */
export function tickMarkLabel(t: unknown, tickType: number): string {
  const p = chartTimeParts(t);
  if (!p) return String(t);
  if (tickType === 0) return `${p.y}年`;
  if (tickType === 1) return `${p.m}月`;
  if ((tickType === 3 || tickType === 4) && p.hh != null && p.mm != null) return `${pad2(p.hh)}:${pad2(p.mm)}`;
  return `${pad2(p.m)}/${pad2(p.d)}`;
}
