import type { RadarJson } from "@/lib/types";

/**
 * 首頁「尚未更新」徽章的句子,逐筆生成。
 *
 * 為什麼不是所有資料集共用一句:期貨**結構上永遠沒有「今日」的資料**。
 * TAIFEX 的端點只供應最新一天,而當日盤後要跑到隔天 05:00 才收完,所以 21:20
 * 那輪拿到的必然是前一個交易日(docs/38 §7.12)。對它說「今日尚未公布」在任何
 * 狀態下都是錯的——它的 `stale` 意思是「連前一個交易日都沒跟上」,不是「今天還沒到」。
 *
 * 這個缺陷是把 `futures` 加進 `FRESH_LABEL` 時漏掉的另一半:`json_export.py`
 * 的摘要句有排除期貨,前端徽章沒有,於是期貨一旦真的落後就會印出一句與
 * §7.12 自己的規則衝突的話。抽成純函式是為了讓它可以被測——這個專案沒有
 * React test runner,能變成純函式的判斷就不該留在元件裡。
 */
export type StaleLine = { key: string; text: string };

export const FRESH_LABEL: Record<string, string> = {
  insti: "法人",
  margin: "融資券",
  warrant: "權證",
  branch: "分點",
  futures: "個股期貨",
};

/** `quotes` 一律不進徽章(它是其他資料集的前提,自己有別的呈現)。 */
export function staleFreshnessLines(
  freshness: RadarJson["freshness"] | undefined,
): StaleLine[] {
  return Object.entries(freshness ?? {})
    .filter(([key, value]) => key !== "quotes" && value?.stale && value?.date)
    .map(([key, value]) => ({
      key,
      text:
        key === "futures"
          ? `個股期貨最新行情日 ${value!.date}，已落後於前一交易日`
          : `${FRESH_LABEL[key] ?? key}今日尚未公布，暫用 ${value!.date}`,
    }));
}

/**
 * 「依交易所公布時間分批自動更新」這句話對期貨是**做不到的承諾**:來源只供應
 * 最新一天,漏掉的日子不會自己回來,要靠 `backfill-futures` 補。所以只有在還有
 * 別的資料集時才保留它;期貨自己落後時不講這句。
 */
export function staleAutoFills(lines: StaleLine[]): boolean {
  return lines.some((line) => line.key !== "futures");
}
