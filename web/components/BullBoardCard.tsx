import Link from "next/link";
import { AlertTriangle, Ban, ShieldCheck, Zap } from "lucide-react";

import FactLine, { SOURCE_TONE } from "@/components/FactLine";
import WatchlistButton from "@/components/WatchlistButton";
import { SECTION_SHORT, SOURCE_LABEL, type Source } from "@/lib/bullBear";
import { BOARD_NO_BEAR, COUNT_SECTIONS } from "@/lib/bullBoard";
import { CHANGE_CLASS } from "@/components/ChangeText";
import { MARKET_LABEL, chgClass, fmtPct } from "@/lib/format";
import type { BullBoardEntry, BullBoardFact } from "@/lib/types";
import { cn } from "@/lib/utils";

const CHG_BADGE: Record<string, string> = {
  up: "text-up bg-up/15",
  down: "text-down bg-down/15",
  flat: "text-foreground bg-secondary",
};

/** 狀態徽章:沿用 StockCard 的 Armed/Triggered/Extended/Faded 樣式。 */
function StateBadge({ state }: { state: BullBoardEntry["state"] }) {
  if (state === "armed")
    return (
      <span className="inline-flex shrink-0 items-center gap-0.5 rounded bg-up/10 px-1.5 py-0.5 text-[10px] font-bold text-up">
        <ShieldCheck className="h-3 w-3" /> Armed
      </span>
    );
  if (state === "triggered")
    return (
      <span className="inline-flex shrink-0 items-center gap-0.5 rounded bg-down/10 px-1.5 py-0.5 text-[10px] font-bold text-down">
        <Zap className="h-3 w-3 fill-current" /> Triggered
      </span>
    );
  if (state === "extended")
    return (
      <span className="inline-flex shrink-0 items-center gap-0.5 rounded bg-warn/15 px-1.5 py-0.5 text-[10px] font-bold text-warn">
        <AlertTriangle className="h-3 w-3" /> Extended
      </span>
    );
  if (state === "faded")
    return (
      <span className="inline-flex shrink-0 items-center gap-0.5 rounded bg-muted px-1.5 py-0.5 text-[10px] font-bold text-muted-foreground">
        <Ban className="h-3 w-3" /> Faded
      </span>
    );
  return null;
}

function SourcePill({ source }: { source: string }) {
  const s = (source in SOURCE_LABEL ? source : "other") as Source;
  return (
    <span className={cn("mr-1 inline-flex -translate-y-px rounded-full px-1.5 text-[10.5px] font-bold leading-[1.45]", SOURCE_TONE[s])}>
      {SOURCE_LABEL[s]}
    </span>
  );
}

function KeyChip({ side, n }: { side: "bull" | "bear"; n: number }) {
  return (
    <span
      className={cn(
        "num inline-flex items-center gap-1 rounded-full px-2 py-px text-[11.5px] font-bold",
        side === "bull" ? "bg-up/15 text-up" : "bg-down/15 text-down",
      )}
    >
      <span aria-hidden>{side === "bull" ? "▲" : "▼"}</span>
      {side === "bull" ? "多方重點" : "空方重點"} {n}
    </span>
  );
}

const lineText = (f: BullBoardFact) => f.text;

/**
 * 首頁「多方榜」一張卡(docs/48):點整張進個股頁「多空」分頁。左側紅色條;第一列名稱/狀態/價格/漲跌/自選;
 * 第二列多方/空方重點條數;三條多方重點(來源膠囊 + 逐段上色);一條空方;底列三段計數與綜合分。
 * 不顯示名次。
 */
export default function BullBoardCard({ e, index = 99 }: { e: BullBoardEntry; index?: number }) {
  const cls = chgClass(e.chg_pct);
  return (
    <Link
      href={`/stock?id=${e.id}&tab=tech`}
      prefetch
      data-testid="bull-board-card"
      style={index < 6 ? { animationDelay: `${0.02 + index * 0.03}s` } : undefined}
      className="nav-card group relative flex cursor-pointer flex-col gap-1.5 overflow-hidden rounded-[var(--r-lg)] border border-border bg-card p-3 pl-3.5shadow-[var(--shadow-card)] transition-[transform,border-color,box-shadow] duration-150 animate-[fadeUp_0.35s_ease_backwards] hover:-translate-y-0.5 hover:border-[color:var(--border-strong)] hover:shadow-[var(--shadow-lift)] active:scale-[0.985]"
    >
      <span aria-hidden className="pointer-events-none absolute inset-y-1.5 left-0 w-[3px] rounded-full bg-up" />
      <div className="flex items-start gap-2">
        <div className="flex min-w-0 flex-col">
          <div className="flex min-w-0 items-center gap-1.5">
            <span className="truncate text-[15.5px] font-bold text-foreground">{e.name}</span>
            <StateBadge state={e.state} />
          </div>
          <span className="truncate text-xs text-muted-foreground">
            {e.id} · {MARKET_LABEL[e.market] ?? e.market}
            {e.industry ? ` · ${e.industry}` : ""}
          </span>
        </div>
        <div className="ml-auto flex shrink-0 items-baseline gap-1.5 pt-0.5">
          <span className={cn("text-[18px] tracking-[-0.3px]", CHANGE_CLASS.price, "font-extrabold")}>
            {e.close != null ? e.close.toLocaleString("zh-TW") : "—"}
          </span>
          <span className={cn("num inline-block rounded-full px-1.5 py-px text-[12px] font-bold", CHG_BADGE[cls])}>
            {fmtPct(e.chg_pct)}
          </span>
        </div>
        <WatchlistButton stockId={e.id} />
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <KeyChip side="bull" n={e.bull_key_n} />
        <KeyChip side="bear" n={e.bear_key_n} />
      </div>

      <ul className="grid min-w-0 gap-0.5" aria-label="多方重點">
        {e.bull.map((f, i) => (
          <li
            key={`${f.code ?? lineText(f)}-${i}`}
            className="min-w-0 break-words rounded-[6px] border-l-2 border-up bg-up/12 py-0.5 pl-1.5 pr-1 text-[12.5px] leading-snug text-foreground"
          >
            <SourcePill source={f.source} />
            <FactLine text={f.text} segments={f.segments} tf={f.tf} />
          </li>
        ))}
      </ul>

      <p className="flex min-w-0 items-baseline gap-1 text-[12.5px] leading-snug text-foreground">
        <span aria-hidden className="shrink-0 font-bold text-down">▼</span>
        {e.bear ? (
          <span className="min-w-0 break-words">
            <SourcePill source={e.bear.source} />
            <FactLine text={e.bear.text} segments={e.bear.segments} tf={e.bear.tf} riskIcon={e.bear.risk} date={e.bear.date} />
          </span>
        ) : (
          <span className="text-muted-foreground">{BOARD_NO_BEAR}</span>
        )}
      </p>

      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-0.5 border-t border-dashed border-[color:var(--line)] pt-1.5 text-[11.5px] text-muted-foreground">
        <span className="num flex flex-wrap gap-x-2.5">
          {COUNT_SECTIONS.map((sec) => (
            <span key={sec} className="whitespace-nowrap">
              {SECTION_SHORT[sec]} <span className="text-up">▲{e.counts[sec].bull}</span> <span className="text-down">▼{e.counts[sec].bear}</span>
            </span>
          ))}
        </span>
        {e.final != null && (
          <span className="whitespace-nowrap">
            綜合 <b className={cn("num text-[13px] font-extrabold text-[color:var(--ink-2)]", e.final >= 65 && "text-warn")}>{e.final}</b>
          </span>
        )}
      </div>
    </Link>
  );
}
