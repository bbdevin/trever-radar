"use client";

import { useState } from "react";
import { AlertTriangle } from "lucide-react";

import ChangeText from "@/components/ChangeText";
import SectionHeader from "@/components/SectionHeader";
import {
  COUNT_NOTE,
  EMPTY_SIDE,
  PANEL_TITLE,
  SIDE_DEFINITION,
  SIDE_LABEL,
  SIDE_PREVIEW,
  SOURCE_LABEL,
  moreText,
  type BullBearItem,
  type BullBearSummary,
  type Source,
} from "@/lib/bullBear";
import { cn } from "@/lib/utils";

/** 來源標籤的家族色(docs/19 §4 的同一組 token;零新色票)。 */
const SOURCE_TONE: Record<Source, string> = {
  chips: "text-[color:var(--accent-2)]",
  inst: "text-[color:var(--accent-2)]",
  margin: "text-[color:var(--accent-2)]",
  futures: "text-[color:var(--accent-2)]",
  tech: "text-primary",
  price: "text-primary",
  strategy: "text-primary",
  warrant: "text-warn",
  theme: "text-warn",
  company: "text-[color:var(--ink-2)]",
  other: "text-[color:var(--ink-2)]",
};

/**
 * 多空分頁頂端(docs/46 §1.3):多方/空方/背景三欄事實。不是 ReasonPill——docs/19 §4 例外:
 * 家族色來源標籤 + 前景色句子 + 側別色邊框。計數不相減、不比大小、不排名。
 */
export default function BullBearPanel({ summary, className }: { summary: BullBearSummary; className?: string }) {
  return (
    <section
      data-testid="bullbear-panel"
      aria-labelledby="bullbear-heading"
      className={cn("grid min-w-0 gap-3 rounded-[var(--r-lg)] border border-border bg-card p-3.5 shadow-[var(--shadow-card)]", className)}
    >
      <SectionHeader
        family="price"
        as="h3"
        id="bullbear-heading"
        title={PANEL_TITLE}
        meta={<>資料日 <span className="num">{summary.asOf.slice(5).replace("-", "/")}</span></>}
      />
      <div className="grid min-w-0 gap-1.5">
        <div className="flex flex-wrap items-center gap-1.5">
          <CountChip side="bull" n={summary.bull.length} />
          <CountChip side="bear" n={summary.bear.length} />
        </div>
        <p className="text-[12px] leading-relaxed text-[color:var(--ink-2)]">
          {SIDE_DEFINITION}
          <span className="text-muted-foreground">{COUNT_NOTE}</span>
        </p>
      </div>
      <div className="grid min-w-0 grid-cols-1 gap-3 md:grid-cols-2">
        <SideList side="bull" items={summary.bull} />
        <SideList side="bear" items={summary.bear} />
      </div>
      {summary.context.length > 0 && <SideList side="context" items={summary.context} />}
    </section>
  );
}

export function CountChip({ side, n, className }: { side: "bull" | "bear"; n: number; className?: string }) {
  return (
    <span
      data-testid={`bullbear-count-${side}`}
      className={cn(
        "num inline-flex items-center gap-1 rounded-full px-2 py-[3px] text-[12px] font-bold",
        side === "bull" ? "bg-up/15 text-up" : "bg-down/15 text-down",
        className,
      )}
    >
      <span aria-hidden>{side === "bull" ? "▲" : "▼"}</span>
      {SIDE_LABEL[side]} {n}
    </span>
  );
}

function SideList({ side, items }: { side: "bull" | "bear" | "context"; items: BullBearItem[] }) {
  const [open, setOpen] = useState(false);
  const shown = open ? items : items.slice(0, SIDE_PREVIEW);
  const rest = items.length - shown.length;
  const edge = side === "bull" ? "border-up" : side === "bear" ? "border-down" : "border-[color:var(--line)]";
  const head = side === "bull" ? "text-up" : side === "bear" ? "text-down" : "text-[color:var(--ink-2)]";
  return (
    <div data-testid={`bullbear-${side}`} className={cn("grid min-w-0 content-start gap-1 border-l-2 pl-2.5", edge)}>
      <h4 className={cn("text-[13px] font-bold", head)}>
        {SIDE_LABEL[side]}
      </h4>
      {items.length === 0 ? (
        <p className="py-0.5 text-[12.5px] text-muted-foreground">{side === "context" ? "" : EMPTY_SIDE[side]}</p>
      ) : (
        <ul className="grid min-w-0 gap-1">
          {shown.map((it) => (
            <li key={it.key} className="grid min-w-0 grid-cols-[2.25rem_minmax(0,1fr)] items-baseline gap-1.5 text-[13px] leading-snug">
              <span className={cn("text-[11.5px] font-bold", SOURCE_TONE[it.source])}>{SOURCE_LABEL[it.source]}</span>
              <span className="min-w-0 break-words text-foreground">
                {it.risk && <AlertTriangle aria-hidden className="mr-1 inline h-3.5 w-3.5 -translate-y-px text-down" />}
                <ChangeText text={it.text} prices={false} />
                {it.date && <span className="num ml-1.5 text-[11px] text-muted-foreground">{it.date}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
      {(rest > 0 || open) && items.length > SIDE_PREVIEW && (
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          className="inline-flex min-h-11 w-fit cursor-pointer items-center text-[12.5px] font-semibold text-primary transition-colors duration-200 hover:underline"
        >
          {open ? "收合" : moreText(rest)}
        </button>
      )}
    </div>
  );
}
