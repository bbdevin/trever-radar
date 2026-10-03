"use client";

import { useEffect, useRef } from "react";
import { cn, pillTabClass } from "@/lib/utils";
import { fmtWanSigned, stepIndex, type StripItem } from "@/lib/warrantBranches";

/**
 * 手機版權證分頁的券商列(2026-10-03):排行表在手機上折進「排行與搜尋」,
 * 改用這一列在 K 線正上方換券商,選了圖就地重畫,不必上下捲。
 * 只在 <md 顯示;不做左右滑動手勢(會和 K 線的平移打架),只用 ‹ › 與點選。
 */
export default function BrokerStrip({
  items,
  selected,
  onSelect,
}: {
  items: StripItem[];
  selected: string | null;
  onSelect: (name: string) => void;
}) {
  const rowRef = useRef<HTMLDivElement>(null);
  const index = items.findIndex((i) => i.name === selected);
  const prev = stepIndex(items.length, index, -1);
  const next = stepIndex(items.length, index, 1);

  // 選中的那格捲到列中央。只動這一列的水平捲動,不用 scrollIntoView:
  // 從下方排行表選券商時,scrollIntoView 的垂直對齊會把整頁拉走。
  useEffect(() => {
    const row = rowRef.current;
    if (!row || !selected) return;
    const chip = row.querySelector<HTMLElement>(`[data-strip-index="${index}"]`);
    if (!chip) return;
    row.scrollTo({ left: chip.offsetLeft - (row.clientWidth - chip.offsetWidth) / 2, behavior: "smooth" });
  }, [selected, index]);

  if (items.length === 0) return null;

  const arrow = "flex min-h-11 w-9 shrink-0 items-center justify-center rounded-md text-lg text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:opacity-30 disabled:hover:bg-transparent";

  return (
    <div className="flex min-w-0 items-center gap-1 md:hidden">
      <button
        type="button"
        aria-label="上一家券商"
        disabled={prev === null}
        onClick={() => prev !== null && onSelect(items[prev].name)}
        className={arrow}
      >
        ‹
      </button>
      <div
        ref={rowRef}
        role="tablist"
        aria-label="選擇券商"
        className="relative flex min-w-0 flex-1 snap-x gap-1.5 overflow-x-auto scrollbar-hide [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        {items.map((item, i) => {
          const active = item.name === selected;
          return (
            <button
              key={item.name}
              type="button"
              role="tab"
              aria-selected={active}
              data-strip-index={i}
              onClick={() => onSelect(item.name)}
              title={item.code ? `${item.code} ${item.name}` : item.name}
              className={cn(
                pillTabClass(active),
                "flex max-w-[9.5rem] shrink-0 snap-center items-center gap-1.5 whitespace-nowrap px-3",
              )}
            >
              <span className={cn("size-1.5 shrink-0 rounded-full", item.tone === "up" ? "bg-up" : "bg-down")} aria-hidden />
              <span className="min-w-0 truncate">{item.name}</span>
              {item.tag && <span className="shrink-0 text-[9.5px] font-semibold opacity-75">{item.tag}</span>}
              <span className="num shrink-0 text-[10.5px] font-medium opacity-80">{fmtWanSigned(item.amount)}</span>
            </button>
          );
        })}
      </div>
      <button
        type="button"
        aria-label="下一家券商"
        disabled={next === null}
        onClick={() => next !== null && onSelect(items[next].name)}
        className={arrow}
      >
        ›
      </button>
    </div>
  );
}
