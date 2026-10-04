/**
 * bull_board_log/*.jsonl 的重複判定(docs/48 §1.1 紀錄行、§2 紀錄版 r(t))。
 *
 * 建置器每輪發布後都會跑;名單沒變的重建不再追加(只差時間戳的行對 §2 毫無資訊,每行約 73 KB)。
 * 「沒變」= 去掉 generated_at / radar_generated_at 之後 JSON 相同,且比的是**同一 data_date 的最後一行**
 * (A → B → A 會留三行,名單在當日的演變不丟)。保留的是一段相同行中的**第一行**:
 * 它的 generated_at 最早,§2「e(t) 09:00 前最後一行」選到的內容因此不變(評估中立)。
 *
 * 壞行(無法解析):無法判斷它屬於哪一天,一律當作「之後可能有變」——壞行之後的第一行必定保留。
 * 不得 import 任何 "@/" 模組:VPS 上由 Node 直接跑。
 */

/** 只差這些鍵 = 同一版名單。 */
export const VOLATILE_LOG_KEYS = ["generated_at", "radar_generated_at"] as const;

type LogRec = { data_date?: unknown } & Record<string, unknown>;

/** 去掉時間戳後的內容字串(同一個產生器的鍵順序固定,直接 stringify)。 */
export function logContentKey(rec: LogRec): string {
  const rest: Record<string, unknown> = { ...rec };
  for (const k of VOLATILE_LOG_KEYS) delete rest[k];
  return JSON.stringify(rest);
}

function parseLine(raw: string): LogRec | null {
  try {
    const v = JSON.parse(raw);
    return v && typeof v === "object" && !Array.isArray(v) ? (v as LogRec) : null;
  } catch {
    return null;
  }
}

/** 既有紀錄(可為多個月檔依時間順序串接)之後,這一行該不該追加。 */
export function shouldAppendLogLine(existing: string, line: LogRec): boolean {
  let last: string | null = null;
  for (const raw of existing.split("\n")) {
    if (!raw.trim()) continue;
    const rec = parseLine(raw);
    if (!rec) last = null;
    else if (rec.data_date === line.data_date) last = logContentKey(rec);
  }
  return last !== logContentKey(line);
}

export type DedupeResult = { text: string; total: number; kept: number; dropped: number; corrupt: number };

/**
 * 壓縮單一月檔:與同一 data_date 上一個保留行內容相同(忽略時間戳)的行刪掉,留第一行。
 * 檔內的結果與「建置器一開始就跳過相同重建」相同;但它逐檔處理,建置器會跳過的跨月重複
 * (例:11/01 重建 10/31,重複行在 11 月檔、前一行在 10 月檔)它看不到、不會刪。壞行原樣保留,空白行去掉。
 */
export function dedupeLogText(text: string): DedupeResult {
  const lastByDate = new Map<unknown, string>();
  const out: string[] = [];
  let total = 0;
  let corrupt = 0;
  for (const raw of text.split("\n")) {
    if (!raw.trim()) continue;
    total += 1;
    const rec = parseLine(raw);
    if (!rec) {
      corrupt += 1;
      lastByDate.clear();
      out.push(raw);
      continue;
    }
    const key = logContentKey(rec);
    if (lastByDate.get(rec.data_date) === key) continue;
    lastByDate.set(rec.data_date, key);
    out.push(raw);
  }
  return {
    text: out.length ? `${out.join("\n")}\n` : "",
    total,
    kept: out.length,
    dropped: total - out.length,
    corrupt,
  };
}
