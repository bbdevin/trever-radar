import type { RadarJson } from "@/lib/types";

/**
 * 首頁「尚未更新」徽章的句子,逐筆生成。
 *
 * 為什麼不是所有資料集共用一句:在**現行排程**下期貨沒有「今日」的資料。
 * 21:20 那輪用的 TAIFEX OpenAPI 日報只供應最新一天,而且刷新得晚(2026-10-02
 * 17:07 仍是 10/01),所以它拿到的是前一個交易日(docs/38 §7.12)。這是餵源與
 * 排程的限制,不是資料本身:futDataDown 當天約 17:00 就有當天完整的一般時段,
 * 標 t 的盤後是 t−1 夜盤、早已收完(「要等隔天 05:00」是舊的錯誤說法;docs/38 §7.18)。
 * 當日匯入在發布時間量測完成前不排程,所以下面的排程字串與 stale 規則暫時不動。
 * 在那之前,對它說「今日尚未公布」仍是錯的——它的 `stale` 意思是「連前一個交易日
 * 都沒跟上」,不是「今天還沒到」。
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
 * (docs/08 §0、docs/35):14:10 daily-market、15:00 daily-tpex-quotes、16:10
 * daily-insti、17:40 / 22:00 daily-branches、21:20 daily-margin。改排程時這裡要一起改。
 *
 * 期貨照實寫:21:20 只拿得到前一個交易日,漏掉的日子不會自己補回來。
 */
// `short` 是手機版一行放得下的寫法(使用者 2026-10-02:要考量手機畫面)。
export const UPDATE_SCHEDULE: { key: string; label: string; when: string; short: string }[] = [
  { key: "quotes", label: "股價", when: "上市 14:10、上櫃 15:00", short: "上市 14:10、上櫃 15:00" },
  { key: "insti", label: "法人", when: "16:10(17:40 補抓)", short: "16:10、17:40 補抓" },
  { key: "warrant", label: "權證", when: "16:10", short: "16:10" },
  { key: "branch", label: "分點", when: "17:40 第一輪(常未到齊)、22:00 補齊", short: "17:40、22:00 補齊" },
  { key: "margin", label: "融資券", when: "21:20", short: "21:20" },
  { key: "futures", label: "個股期貨", when: "21:20(只抓得到前一交易日;漏掉的日子要人工補)", short: "21:20 只抓前一交易日" },
  { key: "themes", label: "題材分類", when: "每週一 14:10", short: "週一 14:10" },
  { key: "scores", label: "評分與榜單", when: "每一輪都重算;資料齊全的版本約 23:10", short: "每輪重算,完整約 23:10" },
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
          // 白天停在前天是常態(14:10 現貨已到今天、21:20 期貨才抓昨天),stale 的
          // 意思是比那更舊(json_export 的規則,2026-10-02)。
          ? `個股期貨最新行情日 ${value!.date}，已落後超過兩個交易日`
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
