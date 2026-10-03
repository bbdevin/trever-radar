import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** 摘要數字格:11px 標籤 + num 粗體數值。tone 只上色,數值本身仍帶正負號／單位(色非唯一訊號)。 */
export type StatTone = "up" | "down" | "neutral" | "warn";

const TONE: Record<StatTone, string> = {
  up: "text-up",
  down: "text-down",
  neutral: "text-foreground",
  warn: "text-warn",
};

/** 依正負號選 tone(0 為中性)。 */
export function toneOf(n: number): StatTone {
  return n > 0 ? "up" : n < 0 ? "down" : "neutral";
}

export default function StatTile({
  label,
  value,
  tone = "neutral",
  className,
  valueClassName,
}: {
  label: ReactNode;
  value: ReactNode;
  tone?: StatTone;
  className?: string;
  valueClassName?: string;
}) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-0.5 rounded-[var(--r-sm)] border border-border bg-secondary p-2.5", className)}>
      <span className="truncate text-[11px] text-muted-foreground">{label}</span>
      <span className={cn("num truncate text-base font-bold", TONE[tone], valueClassName)}>{value}</span>
    </div>
  );
}
