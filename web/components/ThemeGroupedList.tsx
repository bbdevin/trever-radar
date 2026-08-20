"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import StockCard from "@/components/StockCard";
import { Vs20Badge } from "@/components/MoneyFlow";
import type { RadarStock, SectorFlow } from "@/lib/types";
import { cn } from "@/lib/utils";
import { groupStocksByHottestTheme, OTHER_THEME } from "@/lib/themeGroups";

const OPEN_DEFAULT = 3;

export default function ThemeGroupedList({
  stocks,
  themes,
}: {
  stocks: RadarStock[];
  themes: SectorFlow[] | undefined;
}) {
  const groups = groupStocksByHottestTheme(stocks, themes);
  const groupKey = groups?.map((g) => g.name).join("\0") ?? "";
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const [seenKey, setSeenKey] = useState("");
  if (groupKey !== seenKey) {
    setSeenKey(groupKey);
    setOpen(new Set(groups?.slice(0, OPEN_DEFAULT).map((g) => g.name) ?? []));
  }

  if (!groups) {
    return (
      <div className="grid grid-cols-1 gap-2.5 pb-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {stocks.map((s, i) => (
          <StockCard key={s.id} s={s} index={i} />
        ))}
      </div>
    );
  }

  const toggle = (name: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });

  let cardIndex = 0;
  return (
    <div className="flex flex-col gap-3 pb-4">
      {groups.map((g) => {
        const isOpen = open.has(g.name);
        const startIndex = cardIndex;
        if (isOpen) cardIndex += g.stocks.length;
        return (
          <section key={g.name} className="min-w-0">
            <button
              type="button"
              onClick={() => toggle(g.name)}
              aria-expanded={isOpen}
              className="sticky top-[58px] z-20 flex min-h-11 w-full cursor-pointer items-center gap-2 rounded-[var(--r-md)] border border-border bg-background/92 px-3 py-2 text-left shadow-[var(--shadow-card)] backdrop-blur-md"
            >
              <ChevronDown
                size={15}
                aria-hidden
                className={cn(
                  "shrink-0 text-muted-foreground transition-transform duration-200",
                  !isOpen && "-rotate-90",
                )}
              />
              <span className="min-w-0 truncate text-[13.5px] font-semibold text-foreground" title={g.name}>
                {g.name}
              </span>
              {g.name !== OTHER_THEME && <Vs20Badge vs20={g.vs20} />}
              <span className="num ml-auto shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10.5px] text-muted-foreground">
                {g.stocks.length}
              </span>
            </button>
            {isOpen && (
              <div className="mt-2 grid grid-cols-1 gap-2.5 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {g.stocks.map((s, i) => (
                  <StockCard key={s.id} s={s} index={startIndex + i} />
                ))}
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
