"use client";

import { ArrowDown, ArrowUp, Equal, HelpCircle } from "lucide-react";
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
 * **為什麼它只有四個數字**:它是描述性的——只說今天有幾個契約的未平倉比前一個
 * 期貨交易日高,不說那代表什麼。§1 的旗標因為主張「它告訴你一些事」才需要
 * §3 那一整套 battery;這裡沒有那個主張,所以也沒有那個資格去下任何判語。
 *
 * 2026-10-02 手機版(使用者:「有些文字可以用視覺化替代」):一句長句改成四顆
 * 圖示計數。**刻意不用紅綠、不畫堆疊比例條**——紅綠會讀成多空,比例條就是
 * §7.15 禁止的比率與總數;四顆同色、只差圖示。完整句子留在 `aria-label`/`title`。
 */
export default function FuturesOpenInterestDirection({
  direction,
}: {
  direction?: DirectionCounts;
}) {
  const state = futuresOpenInterestDirectionState(direction);
  // 缺鍵 = 沒有算過。不畫任何東西——「今天 0 個契約增加」是一句我們沒有做過的主張。
  if (state.kind === "not-computed") return null;
  const c = state.counts;
  const items = [
    { key: "inc", icon: ArrowUp, label: "增加", n: c.increased },
    { key: "dec", icon: ArrowDown, label: "減少", n: c.decreased },
    { key: "flat", icon: Equal, label: "持平", n: c.unchanged },
    { key: "unk", icon: HelpCircle, label: "無法判定", n: c.undetermined },
  ];

  return (
    <div
      className="mb-3 rounded-[var(--r-lg)] border border-border bg-card px-3 py-2.5 shadow-[var(--shadow-card)]"
      role="group"
      aria-label={openInterestDirectionText(c)}
      title={openInterestDirectionText(c)}
    >
      <p className="mb-1.5 text-[11.5px] text-muted-foreground">
        未平倉 vs 前一期貨交易日
      </p>
      <dl className="grid grid-cols-4 gap-1.5">
        {items.map(({ key, icon: Icon, label, n }) => (
          <div key={key} className="min-w-0 rounded-md bg-muted/40 px-1.5 py-1.5 text-center">
            <dt className="flex items-center justify-center gap-0.5 text-[11px] text-muted-foreground">
              <Icon size={12} aria-hidden="true" />
              <span className="truncate">{label}</span>
            </dt>
            <dd className="num text-[16px] font-bold leading-tight text-foreground">{n}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
