"use client";

import { cn } from "@/lib/utils";

/** 全寬對半切：買方 | 賣方（比照券商 App 籌碼日報 segmented control） */
export default function BuySellSplit({
  value,
  onChange,
  buyLabel,
  sellLabel,
}: {
  value: "buy" | "sell";
  onChange: (next: "buy" | "sell") => void;
  buyLabel: string;
  sellLabel: string;
}) {
  return (
    <div
      role="tablist"
      aria-label="買超或賣超"
      className="grid w-full grid-cols-2 overflow-hidden rounded-[var(--r-md)] border border-border bg-card"
    >
      <button
        type="button"
        role="tab"
        aria-selected={value === "buy"}
        className={cn(
          "min-h-11 cursor-pointer px-2 text-[13.5px] font-bold transition-colors duration-200",
          value === "buy" ? "bg-up/20 text-up shadow-sm" : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
        )}
        onClick={() => onChange("buy")}
      >
        {buyLabel}
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={value === "sell"}
        className={cn(
          "min-h-11 cursor-pointer border-l border-border px-2 text-[13.5px] font-bold transition-colors duration-200",
          value === "sell" ? "bg-down/20 text-down shadow-sm" : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
        )}
        onClick={() => onChange("sell")}
      >
        {sellLabel}
      </button>
    </div>
  );
}
