import { AlertTriangle } from "lucide-react";

import ChangeText, { CHANGE_CLASS } from "@/components/ChangeText";
import { HowTo, PriceLadder, VolumeSplit } from "@/components/PriceLevelsCard";
import SectionHeader from "@/components/SectionHeader";
import {
  COLUMN_LABEL,
  CONTEXT_LABEL,
  COUNT_NOTE,
  EMPTY_SIDE,
  PANEL_TITLE,
  SECTION_LABEL,
  SECTION_ORDER,
  SECTION_SHORT,
  SIDE_DEFINITION,
  SIDE_LABEL,
  TF_CHIP,
  groupColumn,
  type BullBearItem,
  type BullBearSummary,
  type Section,
  type Source,
} from "@/lib/bullBear";
import { PL_LABELS, insufficientText, type PriceLevelsView } from "@/lib/priceLevels";
import { cn } from "@/lib/utils";

/** 群組頭的家族色(docs/19 §4 的同一組 token;零新色票)。 */
const SOURCE_TONE: Record<Source, string> = {
  chips: "text-[color:var(--accent-2)]",
  inst: "text-[color:var(--accent-2)]",
  margin: "text-[color:var(--accent-2)]",
  holders: "text-[color:var(--accent-2)]",
  futures: "text-[color:var(--accent-2)]",
  tech: "text-primary",
  price: "text-primary",
  levels: "text-primary",
  strategy: "text-primary",
  warrant: "text-warn",
  theme: "text-warn",
  company: "text-[color:var(--ink-2)]",
  other: "text-[color:var(--ink-2)]",
};

const CARD = "grid min-w-0 gap-3 rounded-[var(--r-lg)] border border-border bg-card p-3.5 shadow-[var(--shadow-card)]";

/**
 * 多空分頁(docs/46 v2 §1):總覽列 → 技術分析 / 籌碼分析 / 壓力分析三段。每段左多方(紅)、右空方(綠),
 * 中間 1px 分隔線貫穿較高的那一欄;全部列出,不收合。計數是事實數量,不相減、不比大小。
 * 壓力段兩欄之下接價格階梯、現價上下成交與「怎麼算」(docs/45)。
 */
export default function BullBearPanel({ summary, levels, className }: { summary: BullBearSummary; levels: PriceLevelsView; className?: string }) {
  return (
    <div data-testid="bullbear-panel" className={cn("grid min-w-0 gap-3", className)}>
      <section data-testid="bullbear-overview" aria-labelledby="bullbear-heading" className={CARD}>
        <SectionHeader
          family="price"
          as="h3"
          id="bullbear-heading"
          title={PANEL_TITLE}
          meta={<>資料日 <span className="num">{summary.asOf.slice(5).replace("-", "/")}</span></>}
          right={
            <>
              <CountChip side="bull" n={summary.bull.length} />
              <CountChip side="bear" n={summary.bear.length} />
            </>
          }
        />
        <p className="text-[12px] leading-relaxed text-[color:var(--ink-2)]">
          {SIDE_DEFINITION}
          <span className="text-muted-foreground">{COUNT_NOTE}</span>
        </p>
        <p className="num flex flex-wrap gap-x-2 gap-y-0.5 text-[12.5px] font-semibold text-foreground">
          {SECTION_ORDER.map((sec, i) => {
            const b = summary.sections[sec];
            return (
              <span key={sec} className="whitespace-nowrap">
                {i > 0 && <span aria-hidden className="mr-2 text-muted-foreground">・</span>}
                {SECTION_SHORT[sec]} <span className="text-up">▲{b.bull.length}</span> <span className="text-down">▼{b.bear.length}</span>
              </span>
            );
          })}
        </p>
      </section>
      {SECTION_ORDER.map((sec) => (
        <AnalysisSection key={sec} section={sec} summary={summary} levels={sec === "levels" ? levels : undefined} />
      ))}
    </div>
  );
}

export function CountChip({ side, n, className, testId }: { side: "bull" | "bear"; n: number; className?: string; testId?: string | null }) {
  return (
    <span
      data-testid={testId === undefined ? `bullbear-count-${side}` : testId ?? undefined}
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

function AnalysisSection({ section, summary, levels }: { section: Section; summary: BullBearSummary; levels?: PriceLevelsView }) {
  const b = summary.sections[section];
  const id = `bullbear-${section}-heading`;
  return (
    <section data-testid={`bullbear-section-${section}`} aria-labelledby={id} className={CARD}>
      <SectionHeader
        family={section === "chips" ? "chips" : "price"}
        as="h3"
        id={id}
        title={SECTION_LABEL[section]}
        right={
          <>
            <CountChip side="bull" n={b.bull.length} testId={null} />
            <CountChip side="bear" n={b.bear.length} testId={null} />
          </>
        }
      />
      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_1px_minmax(0,1fr)] items-start gap-x-2.5">
        <Column side="bull" section={section} items={b.bull} />
        <div aria-hidden className="self-stretch bg-[color:var(--line)]" />
        <Column side="bear" section={section} items={b.bear} />
      </div>
      {b.context.length > 0 && <ContextStrip items={b.context} section={section} />}
      {levels && <LevelsExtra view={levels} />}
    </section>
  );
}

function Column({ side, section, items }: { side: "bull" | "bear"; section: Section; items: BullBearItem[] }) {
  const groups = groupColumn(items, section);
  return (
    <div data-testid={`bullbear-${side}`} data-section={section} className="grid min-w-0 content-start gap-1.5">
      <h4 className={cn("text-[13px] font-bold", side === "bull" ? "text-up" : "text-down")}>
        <span aria-hidden>{side === "bull" ? "▲" : "▼"} </span>
        {COLUMN_LABEL[section][side]}
      </h4>
      {items.length === 0 ? (
        <p className="text-[12.5px] leading-snug text-muted-foreground">{EMPTY_SIDE[side]}</p>
      ) : (
        groups.map((g) => (
          <div key={g.key} className="grid min-w-0 gap-1">
            {g.label && (
              <p className={cn("text-[11px] font-bold", section === "chips" && g.source ? SOURCE_TONE[g.source] : "text-primary")}>{g.label}</p>
            )}
            <ul className="grid min-w-0 gap-1.5">
              {g.items.map((it) => (
                <FactRow key={it.key} it={it} />
              ))}
            </ul>
          </div>
        ))
      )}
    </div>
  );
}

function FactRow({ it }: { it: BullBearItem }) {
  return (
    <li className="min-w-0 break-words text-[12.5px] leading-snug text-foreground">
      {it.risk && it.side === "bear" && <AlertTriangle aria-hidden className="mr-1 inline h-3 w-3 -translate-y-px text-down" />}
      {it.tf && it.tf !== "D" && (
        <span className="mr-1 inline-flex -translate-y-px items-center rounded-[4px] border border-[color:var(--line)] px-1 text-[10.5px] font-semibold leading-[1.35] text-[color:var(--ink-2)]">
          {TF_CHIP[it.tf]}
        </span>
      )}
      {it.segments ? (
        it.segments.map((s, i) => (
          <span key={i} className={s.kind ? CHANGE_CLASS[s.kind] : undefined}>
            {s.t}
          </span>
        ))
      ) : (
        <ChangeText text={it.text} prices={false} />
      )}
      {it.date && <span className="num ml-1.5 whitespace-nowrap text-[11px] text-muted-foreground">{it.date}</span>}
    </li>
  );
}

function ContextStrip({ items, section }: { items: BullBearItem[]; section: Section }) {
  return (
    <div data-testid="bullbear-context" data-section={section} className="grid min-w-0 gap-1 border-l-2 border-[color:var(--line)] pl-2.5">
      <h4 className="text-[12px] font-bold text-[color:var(--ink-2)]">{CONTEXT_LABEL}</h4>
      <ul className="grid min-w-0 gap-1">
        {items.map((it) => (
          <FactRow key={it.key} it={it} />
        ))}
      </ul>
    </div>
  );
}

function LevelsExtra({ view }: { view: PriceLevelsView }) {
  if (view.state !== "ok") {
    return (
      <div data-testid="price-levels" className="grid min-w-0 gap-2">
        <p className="text-[12.5px] text-muted-foreground">
          <span className="font-bold text-foreground">{PL_LABELS.title}</span>{" "}
          {view.state === "missing" ? PL_LABELS.missing : insufficientText(view.bars)}
        </p>
        <HowTo />
      </div>
    );
  }
  return (
    <div data-testid="price-levels" className="grid min-w-0 gap-3 border-t border-[color:var(--line)] pt-3">
      <p className="text-[11.5px] text-muted-foreground">
        {PL_LABELS.title} · 資料日 <span className="num">{view.asOf.slice(5).replace("-", "/")}</span> · {PL_LABELS.adjusted}
      </p>
      <PriceLadder above={view.above} below={view.below} close={view.close} />
      {view.volume && <VolumeSplit volume={view.volume} />}
      <HowTo />
    </div>
  );
}
