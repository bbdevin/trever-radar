import { AlertTriangle } from "lucide-react";
import type { ReactNode } from "react";

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
import type { MetricTone, TechMetric } from "@/lib/techMetrics";
import { cn } from "@/lib/utils";

/** 群組頭小膠囊的家族色(docs/19 §4 的同一組 token + /12 淡底;零新色票)。 */
const ACCENT2_PILL = "bg-[color:var(--accent-2)]/12 text-[color:var(--accent-2)]";
const PRIMARY_PILL = "bg-primary/12 text-primary";
const WARN_PILL = "bg-warn/12 text-warn";
const INK_PILL = "bg-[color:var(--ink-2)]/12 text-[color:var(--ink-2)]";
const SOURCE_TONE: Record<Source, string> = {
  chips: ACCENT2_PILL,
  inst: ACCENT2_PILL,
  margin: ACCENT2_PILL,
  holders: ACCENT2_PILL,
  futures: ACCENT2_PILL,
  tech: PRIMARY_PILL,
  price: PRIMARY_PILL,
  levels: PRIMARY_PILL,
  strategy: PRIMARY_PILL,
  warrant: WARN_PILL,
  theme: WARN_PILL,
  company: INK_PILL,
  other: INK_PILL,
};

/** 兩欄的側別淡底、重點列的較深底與左側色條(--up 紅 / --down 綠)。 */
const SIDE_TINT: Record<"bull" | "bear", { col: string; key: string }> = {
  bull: { col: "bg-up/[0.06]", key: "border-up bg-up/12" },
  bear: { col: "bg-down/[0.06]", key: "border-down bg-down/12" },
};

const CARD = "grid min-w-0 gap-3 rounded-[var(--r-lg)] border border-border bg-card p-3.5 shadow-[var(--shadow-card)]";

/**
 * 多空分頁(docs/46 v2 §1):總覽列 → 技術分析 / 籌碼分析 / 壓力分析三段。每段左多方(紅)、右空方(綠),
 * 中間 1px 分隔線貫穿較高的那一欄;全部列出,不收合。計數是事實數量,不相減、不比大小。
 * 技術段頭下接指標列(技術分/RSI14/量比/觀察價/失效價,docs/46 §6.7);壓力段兩欄之下接價格階梯、
 * 現價上下成交與「怎麼算」(docs/45)。
 */
export default function BullBearPanel({
  summary,
  levels,
  metrics,
  className,
}: {
  summary: BullBearSummary;
  levels: PriceLevelsView;
  /** 技術分析段頂的指標列;null = 尚未產出技術指標 */
  metrics: TechMetric[] | null;
  className?: string;
}) {
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
        <AnalysisSection key={sec} section={sec} summary={summary} levels={sec === "levels" ? levels : undefined}>
          {sec === "tech" && <TechMetricsRow metrics={metrics} />}
        </AnalysisSection>
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

function AnalysisSection({
  section,
  summary,
  levels,
  children,
}: {
  section: Section;
  summary: BullBearSummary;
  levels?: PriceLevelsView;
  /** 段頭與兩欄之間(技術段的指標列) */
  children?: ReactNode;
}) {
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
      {children}
      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-x-2">
        <Column side="bull" section={section} items={b.bull} />
        <Column side="bear" section={section} items={b.bear} />
      </div>
      {b.context.length > 0 && <ContextStrip items={b.context} section={section} />}
      {levels && <LevelsExtra view={levels} />}
    </section>
  );
}

/** 指標格的淡底與數值色(同一組 token + /12 淡底;價格格用技術家族色的更淡底)。 */
const METRIC_TONE: Record<MetricTone, { tile: string; value: string }> = {
  brand: { tile: "bg-primary/12", value: "text-primary" },
  up: { tile: "bg-up/12", value: "text-up" },
  down: { tile: "bg-down/12", value: "text-down" },
  warn: { tile: "bg-warn/12", value: "text-warn" },
  neutral: { tile: "bg-secondary", value: "text-foreground" },
};
const DIST_CLASS = { up: "text-up", down: "text-down", flat: "text-foreground" } as const;

/** 技術分析段頂:技術分 / RSI14 / 量比 / 觀察價 / 失效價(docs/46 §6.7);手機一列 3 格、自動換行。 */
function TechMetricsRow({ metrics }: { metrics: TechMetric[] | null }) {
  if (!metrics) {
    return (
      <p data-testid="tech-metrics-missing" className="text-[12.5px] text-muted-foreground">
        尚未產出技術指標;請先跑 compute-indicators。
      </p>
    );
  }
  return (
    <dl data-testid="tech-metrics" className="grid min-w-0 grid-cols-3 gap-1.5">
      {metrics.map((m) => {
        const tone = METRIC_TONE[m.tone];
        return (
          <div
            key={m.key}
            data-metric={m.key}
            className={cn("flex min-w-0 flex-col gap-0.5 rounded-[var(--r-sm)] px-2 py-1.5", m.price ? "bg-primary/[0.06]" : tone.tile)}
          >
            <dt className="truncate text-[11px] font-semibold text-[color:var(--ink-2)]">{m.label}</dt>
            <dd className="num flex min-w-0 flex-wrap items-baseline gap-x-1 leading-tight">
              <span className={cn("text-[15px] font-bold", m.price ? "text-primary" : tone.value)}>{m.value}</span>
              {m.dist && <span className={cn("text-[11.5px] font-semibold", DIST_CLASS[m.dist.dir])}>{m.dist.text}</span>}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

function Column({ side, section, items }: { side: "bull" | "bear"; section: Section; items: BullBearItem[] }) {
  const groups = groupColumn(items, section);
  const tint = SIDE_TINT[side];
  return (
    <div
      data-testid={`bullbear-${side}`}
      data-section={section}
      className={cn("grid min-w-0 content-start gap-2 rounded-[var(--r-sm)] p-1.5", tint.col)}
    >
      <h4 className={cn("text-[13px] font-bold", side === "bull" ? "text-up" : "text-down")}>
        <span aria-hidden>{side === "bull" ? "▲" : "▼"} </span>
        {COLUMN_LABEL[section][side]}
      </h4>
      {items.length === 0 ? (
        <p className="text-[12.5px] leading-snug text-muted-foreground">{EMPTY_SIDE[side]}</p>
      ) : (
        groups.map((g) => (
          <div key={g.key} data-group={g.keyGroup ? "key" : undefined} className="grid min-w-0 gap-1">
            {g.label && (
              <p
                className={cn(
                  "w-fit rounded-full px-1.5 py-px text-[11px] font-bold leading-[1.45]",
                  g.keyGroup ? "bg-primary text-primary-foreground" : section === "chips" && g.source ? SOURCE_TONE[g.source] : PRIMARY_PILL,
                )}
              >
                {g.label}
              </p>
            )}
            {g.keyGroup ? (
              <ul className="grid min-w-0 gap-1">
                {g.items.map((it) => (
                  <FactRow key={it.key} it={it} lagDate className={cn("rounded-[6px] border-l-2 py-1 pl-1.5 pr-1", tint.key)} />
                ))}
              </ul>
            ) : (
              <ul className="grid min-w-0 divide-y divide-border">
                {g.items.map((it) => (
                  <FactRow key={it.key} it={it} className="py-1 first:pt-0 last:pb-0" />
                ))}
              </ul>
            )}
          </div>
        ))
      )}
    </div>
  );
}

/** lagDate:重點群組沒有「大戶(集保 MM/DD)」群組頭,滯後資料日改放在列尾。 */
function FactRow({ it, className, lagDate }: { it: BullBearItem; className?: string; lagDate?: boolean }) {
  const date = it.date ?? (lagDate ? it.dataDate : undefined);
  return (
    <li className={cn("min-w-0 break-words text-[12.5px] leading-snug text-foreground", className)}>
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
      {date && <span className="num ml-1.5 whitespace-nowrap text-[11px] text-muted-foreground">{date}</span>}
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
