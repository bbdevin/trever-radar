"use client";

import { futuresOpenInterestDirectionState, openInterestDirectionText } from "@/lib/futures";
import type { FuturesOpenInterestDirection as DirectionCounts } from "@/lib/types";

/**
 * 首頁「期貨異常」分頁最上面那一行:市場層級的未平倉方向計數(docs/38 §7.15)。
 *
 * **為什麼它在名單上面**:名單講的是旗標,而旗標是少數——典型的一天個位數,
 * 空名單是常態。這四個計數則每一天、每一個契約都有,是這個分頁唯一一定講得出
 * 內容的東西;放在名單下面,它在最常見的那一天(空名單)會被一段置中的
 * 「今天沒有契約舉旗」擋在下面,而那正是讀者最需要它的時候。
 *
 * **為什麼它只有一句話**:它是描述性的——只說今天有幾個契約的未平倉比前一個
 * 期貨交易日高,不說那代表什麼。§1 的旗標因為主張「它告訴你一些事」才需要
 * §3 那一整套 battery;這裡沒有那個主張,所以也沒有那個資格去下任何判語。
 * 加一句「今天偏多」或一個門檻,就是在這個功能的信用底下放一個沒有被檢定過的
 * 訊號。判斷全部在 `lib/futures.ts` 的純函式裡,這裡只負責排版。
 */
export default function FuturesOpenInterestDirection({
  direction,
}: {
  direction?: DirectionCounts;
}) {
  const state = futuresOpenInterestDirectionState(direction);
  // 缺鍵 = 沒有算過。不畫任何東西——「今天 0 個契約增加」是一句我們沒有做過的主張。
  if (state.kind === "not-computed") return null;

  return (
    <p className="mb-3 rounded-[var(--r-lg)] border border-border bg-card px-3.5 py-2.5 text-[12px] leading-relaxed text-muted-foreground shadow-[var(--shadow-card)]">
      {openInterestDirectionText(state.counts)}
    </p>
  );
}
