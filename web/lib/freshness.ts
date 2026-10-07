import type { RadarJson } from "@/lib/types";

/**
 * 首頁「尚未更新」徽章的句子,逐筆生成。
 *
 * 為什麼不是所有資料集共用一句:期貨的 `stale` 意思是「連前一個交易日
 * 都沒跟上」,不是「今天還沒到」。2026-10-02 起 `import-futures-day`(futDataDown)
 * 接進 16:10／17:40／22:00,當天完整的一般時段約 17:00 就有(標 t 的盤後是 t−1 夜盤,
 * 早已收完;docs/38 §7.18),所以正常是追上現貨日或落後一天;21:20 的 OpenAPI 日報
 * 退為官方覆核。對它說「今日尚未公布」仍是錯的——16:10 未到齊時 17:40、22:00 會重試。
 *
 * 這個缺陷是把 `futures` 加進 `FRESH_LABEL` 時漏掉的另一半:`json_export.py`
 * 的摘要句有排除期貨,前端徽章沒有,於是期貨一旦真的落後就會印出一句與
 * §7.12 自己的規則衝突的話。抽成純函式是為了讓它可以被測——這個專案沒有
 * React test runner,能變成純函式的判斷就不該留在元件裡。
 */
export type StaleLine = {
  key: string;
  /** 完整句子(無障礙／title 用;既有測試鎖住它)。 */
  text: string;
  /** 手機版精簡一行用:資料名稱、停在哪一天(MM-DD)、短排程。 */
  label?: string;
  shortDate?: string;
  /** 手機一行的狀態:「暫用 10-01」「停在 09-30」「部分未到(2 檔)」。 */
  shortState?: string;
  schedule?: string;
  shortSchedule?: string;
};

/**
 * 每日自動更新時間表(週一至週五,台北時間;2026-10-02 依使用者要求整合到首頁的
 * 「尚未更新」區塊)。**來源是正式機的 crontab 與 vps/scripts/ 各輪實際匯入的資料**
 * (docs/08 §0、docs/35、docs/47):14:05 daily-market、14:45 daily-tpex-quotes、16:00
 * daily-insti、16:30 / 22:30 daily-branches(docs/47 §8,2026-10-07 起;舊 17:30)、20:45
 * daily-margin、週一 11:00 weekly-refdata。
 * docs/47 起各輪是「起點」:腳本輪詢到來源公布就立刻上線,所以這裡寫「起」。
 * 改排程時這裡要一起改。
 *
 * 期貨照實寫:16:00 起隨法人輪詢抓當日,未到齊 16:30、22:30 重試;資券輪為官方日報覆核。
 */
// `short` 是手機版一行放得下的寫法(使用者 2026-10-02:要考量手機畫面)。
export const UPDATE_SCHEDULE: { key: string; label: string; when: string; short: string }[] = [
  { key: "quotes", label: "股價", when: "上市 14:05 起、上櫃 14:45 起", short: "上市14:05、上櫃14:45起" },
  { key: "insti", label: "法人", when: "16:00 起輪詢(到齊即上線)", short: "16:00 起輪詢" },
  { key: "warrant", label: "權證", when: "16:00 起(隨法人輪)", short: "16:00 起" },
  { key: "branch", label: "分點", when: "16:30 起偵測、齊全即抓", short: "16:30 起偵測、齊全即抓" },
  { key: "margin", label: "融資券", when: "20:45 起輪詢", short: "20:45 起輪詢" },
  { key: "futures", label: "個股期貨", when: "16:00 起（當日；未到齊則 16:30、22:30 重試）", short: "16:00 當日、16:30 補" },
  { key: "themes", label: "題材分類", when: "每週一 11:00", short: "週一 11:00" },
  { key: "scores", label: "評分與榜單", when: "每一輪都重算;資料齊全的版本約 22:00", short: "每輪重算,完整約 22:00" },
];

export function scheduleFor(key: string): string | undefined {
  return UPDATE_SCHEDULE.find((s) => s.key === key)?.when;
}

export function shortScheduleFor(key: string): string | undefined {
  return UPDATE_SCHEDULE.find((s) => s.key === key)?.short;
}

/** 2026-10-01 → 10-01(手機一行放得下;年份由頁首的資料日交代)。 */
export function mmdd(date: string): string {
  return /^\d{4}-\d{2}-\d{2}$/.test(date) ? date.slice(5) : date;
}

export const FRESH_LABEL: Record<string, string> = {
  insti: "法人",
  margin: "融資券",
  warrant: "權證",
  branch: "分點",
  futures: "個股期貨",
  themes: "題材分類",
};

/** `quotes` 一律不進徽章(它是其他資料集的前提,自己有別的呈現)。 */
export function staleFreshnessLines(
  freshness: RadarJson["freshness"] | undefined,
): StaleLine[] {
  return Object.entries(freshness ?? {})
    .filter(([key, value]) => key !== "quotes" && value?.stale && value?.date)
    .map(([key, value]) => {
      // 權證「今天的批次到了,但有幾檔標的昨天有、今天還沒有」——不是整批舊,
      // 說「暫用(今天)」很怪(2026-10-02 首頁出現「權證 暫用 10-02」)。
      const partial = key === "warrant" && (value as { partial_stale?: boolean }).partial_stale;
      const partialN = (value as { stale_stock_count?: number }).stale_stock_count;
      const shortDate = mmdd(value!.date as string);
      return {
      key,
      text:
        key === "futures"
          // stale 的意思是落後超過一個交易日(json_export 的規則 (d, prev),2026-10-02 收回)。
          ? `個股期貨最新行情日 ${value!.date}，已落後超過一個交易日`
          : partial
          ? `權證今日部分標的尚未公布${partialN ? `(${partialN} 檔)` : ""}`
          : `${FRESH_LABEL[key] ?? key}今日尚未公布，暫用 ${value!.date}`,
      label: FRESH_LABEL[key] ?? key,
      shortDate,
      shortState: key === "futures"
        ? `停在 ${shortDate}`
        : partial
        ? `部分未到${partialN ? `(${partialN} 檔)` : ""}`
        : `暫用 ${shortDate}`,
      schedule: scheduleFor(key),
      shortSchedule: shortScheduleFor(key),
      };
    });
}

/**
 * 「依交易所公布時間分批自動更新」這句話對期貨是**做不到的承諾**:來源只供應
 * 最新一天,漏掉的日子不會自己回來,要靠 `backfill-futures` 補。所以只有在還有
 * 別的資料集時才保留它;期貨自己落後時不講這句。
 */
export function staleAutoFills(lines: StaleLine[]): boolean {
  return lines.some((line) => line.key !== "futures");
}
