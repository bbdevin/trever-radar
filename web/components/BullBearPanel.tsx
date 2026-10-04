import { CandlestickChart } from "lucide-react";
import type { ReactNode } from "react";

import FactLine, { PRIMARY_PILL, SOURCE_TONE } from "@/components/FactLine";
import { HowTo, PriceLadder, VolumeSplit } from "@/components/PriceLevelsCard";
import SectionHeader from "@/components/SectionHeader";
import {
  COLUMN_LABEL,
  CONTEXT_LABEL,
  COUNT_NOTE,
  EMPTY_SIDE,
  PANEL_ORDER,
  PANEL_TITLE,
  SECTION_LABEL,
  SECTION_SHORT,
  SIDE_DEFINITION,
  SIDE_LABEL,
  groupColumn,
  type BullBearItem,
  type BullBearSummary,
  type Section,
  type SectionBuckets,
} from "@/lib/bullBear";
import { CHIPS_HOWTO_LINES, PL_LABELS, insufficientText, type PriceLevelsView } from "@/lib/priceLevels";
import type { MetricTone, TechMetric } from "@/lib/techMetrics";
import { cn } from "@/lib/utils";

/** 兩欄的側別淡底、重點列的較深底與左側色條(--up 紅 / --down 綠)。 */
const SIDE_TINT: Record<"bull" | "bear", { col: string; key: string }> = {
  bull: { col: "bg-up/[0.06]", key: "border-up bg-up/12" },
  bear: { col: "bg-down/[0.06]", key: "border-down bg-down/12" },
};

const CARD = "grid min-w-0 gap-3 rounded-[var(--r-lg)] border border-border bg-card p-3.5 shadow-[var(--shadow-card)]";

/**
 * 多空分頁(docs/46 v2 §1、§6.8):總覽列 → 技術分析卡 → 籌碼分析卡。每段左多方(紅)、右空方(綠);
 * 全部列出,不收合。計數是事實數量,不相減、不比大小。
 * 技術卡:指標列(docs/46 §6.7)→ 技術兩欄 → 「壓力分析」小節(小標+自己的計數、下方支撐/上方壓力兩欄、
 * 價格階梯、現價上下成交、常駐「怎麼算」,docs/45)。籌碼卡底附常駐門檻說明。
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
          {PANEL_ORDER.map((sec, i) => {
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
      <AnalysisSection
        section="tech"
        summary={summary}
        top={<TechMetricsRow metrics={metrics} />}
        bottom={<LevelsSubsection summary={summary} levels={levels} />}
      />
      <AnalysisSection section="chips" summary={summary} bottom={<HowTo lines={CHIPS_HOWTO_LINES} testId="bullbear-chips-howto" />} />
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

/** 一張分析卡:段頭 → top(技術卡的指標列)→ 兩欄 → 背景 → bottom(技術卡的壓力分析小節、籌碼卡的門檻說明)。 */
function AnalysisSection({
  section,
  summary,
  top,
  bottom,
}: {
  section: Section;
  summary: BullBearSummary;
  top?: ReactNode;
  bottom?: ReactNode;
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
        right={<SideCounts b={b} />}
      />
      {top}
      <SideColumns section={section} b={b} />
      {bottom}
    </section>
  );
}

function SideCounts({ b, size }: { b: SectionBuckets; size?: "sm" }) {
  const cls = size === "sm" ? "px-1.5 py-px text-[11px]" : undefined;
  return (
    <>
      <CountChip side="bull" n={b.bull.length} testId={null} className={cls} />
      <CountChip side="bear" n={b.bear.length} testId={null} className={cls} />
    </>
  );
}

function SideColumns({ section, b, sub }: { section: Section; b: SectionBuckets; sub?: boolean }) {
  return (
    <>
      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-x-2">
        <Column side="bull" section={section} items={b.bull} sub={sub} />
        <Column side="bear" section={section} items={b.bear} sub={sub} />
      </div>
      {b.context.length > 0 && <ContextStrip items={b.context} section={section} sub={sub} />}
    </>
  );
}

/**
 * 技術分析卡內的「壓力分析」小節(docs/46 §6.8):比卡片段頭小一級的小標(價格家族 icon + 自己的計數),
 * 兩欄下方支撐/上方壓力,再接價格階梯、現價上下成交與常駐「怎麼算」。
 */
function LevelsSubsection({ summary, levels }: { summary: BullBearSummary; levels: PriceLevelsView }) {
  const b = summary.sections.levels;
  const id = "bullbear-levels-heading";
  return (
    <section
      data-testid="bullbear-section-levels"
      aria-labelledby={id}
      className="grid min-w-0 gap-3 border-t border-[color:var(--line)] pt-3"
    >
      <div className="flex min-w-0 items-center justify-between gap-x-3 gap-y-1">
        <h4 id={id} className="flex min-w-0 items-center gap-1.5 text-[13px] font-bold text-foreground">
          <span aria-hidden className="grid h-5 w-5 shrink-0 place-items-center rounded-[6px] bg-primary/12 text-primary">
            <CandlestickChart size={13} strokeWidth={1.8} />
          </span>
          {SECTION_LABEL.levels}
        </h4>
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-1">
          <SideCounts b={b} size="sm" />
        </div>
      </div>
      <SideColumns section="levels" b={b} sub />
      <LevelsExtra view={levels} />
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

/** sub:位於小節(h4)之下,欄頭降一級為 h5。 */
function Column({ side, section, items, sub }: { side: "bull" | "bear"; section: Section; items: BullBearItem[]; sub?: boolean }) {
  const groups = groupColumn(items, section);
  const tint = SIDE_TINT[side];
  const H = sub ? "h5" : "h4";
  return (
    <div
      data-testid={`bullbear-${side}`}
      data-section={section}
      className={cn("grid min-w-0 content-start gap-2 rounded-[var(--r-sm)] p-1.5", tint.col)}
    >
      <H className={cn("text-[13px] font-bold", side === "bull" ? "text-up" : "text-down")}>
        <span aria-hidden>{side === "bull" ? "▲" : "▼"} </span>
        {COLUMN_LABEL[section][side]}
      </H>
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
      <FactLine text={it.text} segments={it.segments} tf={it.tf} riskIcon={it.risk && it.side === "bear"} date={date} />
    </li>
  );
}

function ContextStrip({ items, section, sub }: { items: BullBearItem[]; section: Section; sub?: boolean }) {
  const H = sub ? "h5" : "h4";
  return (
    <div data-testid="bullbear-context" data-section={section} className="grid min-w-0 gap-1 border-l-2 border-[color:var(--line)] pl-2.5">
      <H className="text-[12px] font-bold text-[color:var(--ink-2)]">{CONTEXT_LABEL}</H>
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
    <div data-testid="price-levels" className="grid min-w-0 gap-3">
      <p className="text-[11.5px] text-muted-foreground">
        {PL_LABELS.title} · 資料日 <span className="num">{view.asOf.slice(5).replace("-", "/")}</span> · {PL_LABELS.adjusted}
      </p>
      <PriceLadder above={view.above} below={view.below} close={view.close} />
      {view.volume && <VolumeSplit volume={view.volume} />}
      <HowTo />
    </div>
  );
}
