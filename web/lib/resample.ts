import type { Candle } from "@/lib/types";

/** 分K(docs/50)= "5" | "30" | "60";日/週/月K = "D" | "W" | "M"。 */
export type MinuteTf = "5" | "30" | "60";
/** 只由日K重取樣得到的週期(多空事實 lib/facts 只用這三種)。 */
export type DailyTf = "D" | "W" | "M";
export type Timeframe = MinuteTf | DailyTf;

export function isMinuteTf(tf: Timeframe): tf is MinuteTf {
  return tf === "5" || tf === "30" || tf === "60";
}

/** `stocks/intraday/{id}.json`(docs/50):5 分 K,原始價(未還原),量為張。
 *  bars = [epoch 秒(該根開始時間), 開, 高, 低, 收, 量]。 */
export interface IntradayFile {
  id: string;
  tf: "5";
  from: string;
  to: string;
  adjusted: false;
  bars: [number, number, number, number, number, number][];
}

/** 一個交易日(09:00–13:30)各分K週期的根數:5 分 54 根、30 分 9 根、60 分 5 根(13:00 那根半小時)。 */
export const BARS_PER_DAY: Record<MinuteTf, number> = { "5": 54, "30": 9, "60": 5 };
/** 分K預設可視交易日數:5 分看 5 天、30 分看 20 天、60 分看 60 天(檔案全部)。 */
export const MINUTE_VISIBLE_DAYS: Record<MinuteTf, number> = { "5": 5, "30": 20, "60": 60 };

const TW_OFFSET_S = 8 * 3600;
const SESSION_OPEN_MIN = 9 * 60;

/** epoch 秒 → 台北牆上時間鍵 "YYYY-MM-DDTHH:MM"(分K的 Candle.t)。 */
export function twWallKey(epochS: number): string {
  return new Date((epochS + TW_OFFSET_S) * 1000).toISOString().slice(0, 16);
}

/**
 * Candle.t → lightweight-charts 的 time。日K照舊傳 "YYYY-MM-DD"(business day);
 * 分K傳 UTCTimestamp,但用「台北牆上時間當成 UTC」(= epoch + 8h):圖表一律以 UTC 顯示,
 * 這樣軸與十字線才會是 09:00 而不是 01:00。
 */
export function chartTimeOf(t: string): string | number {
  return t.length > 10 ? Date.parse(`${t}:00Z`) / 1000 : t;
}

/** 5 分 K 檔 → 指定分K週期的 Candle(t = 台北牆上時間鍵、amt 無資料記 0、af = 1)。
 *  30/60 分以交易時段切桶:從 09:00 起每 30/60 分一桶,13:25 那根(含 13:30 收盤)落在 13:00 桶。 */
export function intradayCandles(file: IntradayFile, tf: MinuteTf): Candle[] {
  const size = Number(tf);
  const out: Candle[] = [];
  let key = "";
  let cur: Candle | null = null;
  for (const [ts, o, h, l, c, v] of file.bars) {
    const wall = twWallKey(ts);
    const mins = Number(wall.slice(11, 13)) * 60 + Number(wall.slice(14, 16)) - SESSION_OPEN_MIN;
    const bucketStart = SESSION_OPEN_MIN + Math.floor(Math.max(0, mins) / size) * size;
    const t = `${wall.slice(0, 11)}${String(Math.floor(bucketStart / 60)).padStart(2, "0")}:${String(bucketStart % 60).padStart(2, "0")}`;
    if (t !== key || !cur) {
      if (cur) out.push(cur);
      key = t;
      cur = { t, o, h, l, c, v, amt: 0, af: 1 };
    } else {
      cur.h = Math.max(cur.h, h);
      cur.l = Math.min(cur.l, l);
      cur.c = c;
      cur.v += v;
    }
  }
  if (cur) out.push(cur);
  return out;
}

/** 分K檔的載入狀態:idle 還沒抓、loading 抓取中、ok 有檔、none 這檔沒有分K(404 或抓取失敗)。 */
export type IntradayStatus = "idle" | "loading" | "ok" | "none";

/**
 * 實際畫的週期。選了分K但這張圖不提供分K(`offered` = false,例:權證分頁)、或這檔還沒/沒有
 * 分K檔 → 日K。選擇本身(localStorage)不改:換到有分K的股票時照樣是分K。
 */
export function effectiveTf(requested: Timeframe, offered: boolean, status: IntradayStatus): Timeframe {
  if (!isMinuteTf(requested)) return requested;
  return offered && status === "ok" ? requested : "D";
}

export const MINUTE_NONE_NOTICE = "此股未提供分K,改看日K";
export const MINUTE_LOADING_NOTICE = "分K載入中…";

/** 選了分K而畫的是日K時,圖上方那一行說明;其餘 null。 */
export function minuteNotice(requested: Timeframe, offered: boolean, status: IntradayStatus): string | null {
  if (!isMinuteTf(requested) || !offered) return null;
  if (status === "none") return MINUTE_NONE_NOTICE;
  if (status === "idle" || status === "loading") return MINUTE_LOADING_NOTICE;
  return null;
}

/** 分K圖的說明列:「分K · 原始價(未還原) · 盤後更新至 MM-DD」。 */
export function minuteCaption(file: Pick<IntradayFile, "to">): string {
  return `分K · 原始價(未還原) · 盤後更新至 ${file.to.slice(5)}`;
}

/** 十字線 legend 的時間:分K「MM-DD HH:MM」;日K桌機完整日期、手機 MM-DD。 */
export function barTimeLabel(t: string, mobile: boolean): string {
  if (t.length > 10) return `${t.slice(5, 10)} ${t.slice(11, 16)}`;
  return mobile ? t.slice(5) : t;
}

/** 週鍵:該日所屬週的週一日期(台股週一~週五) */
function weekKey(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00Z");
  const dow = (d.getUTCDay() + 6) % 7; // Mon=0
  d.setUTCDate(d.getUTCDate() - dow);
  return d.toISOString().slice(0, 10);
}

/** 該日所屬的重取樣桶鍵(D=當日、W=週一、M=YYYY-MM);供非K棒日序列與 K 棒桶對齊。分K不用(日頻序列不畫)。 */
export function periodKey(dateStr: string, tf: Timeframe): string {
  if (tf === "W") return weekKey(dateStr);
  if (tf === "M") return dateStr.slice(0, 7);
  return dateStr;
}

/** 日K → 週K/月K:開=首日開、高=max、低=min、收=末日收、量/額=加總,t=末日。分K不經這裡(見 intradayCandles)。 */
export function resample(candles: Candle[], tf: Timeframe): Candle[] {
  if (tf !== "W" && tf !== "M") return candles;
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
  if (isMinuteTf(tf)) return days * BARS_PER_DAY[tf];
  return tf === "D" ? days : tf === "W" ? Math.ceil(days / 5) : Math.ceil(days / 21);
}
