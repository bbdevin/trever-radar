"use client";

import { MARKET_LABEL } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { RadarJson } from "@/lib/types";
import {
  BRIEF_INSTI_HINT,
  BRIEF_INSTI_LABEL,
  BRIEF_STALE_BADGE,
  BRIEF_TITLE,
  BRIEF_TURNOVER_LABEL,
  BRIEF_UPDOWN_HINT,
  dateTag,
  fmtE8,
  fmtIndex,
  indexChangeText,
  instiBriefItems,
  orderedIndices,
  turnoverCell,
} from "@/lib/marketBrief";

function tone(n: number | null | undefined): string {
  if (n == null || n === 0) return "text-foreground";
  return n > 0 ? "text-up" : "text-down";
}

/**
 * 首頁「市場概況」(docs/49 §11):一張卡、最多四格(加權指數／櫃買指數／成交額＋漲跌家數／
 * 三大法人全市場淨額)。手機 2 欄,md 以上 4 欄。舊 payload 缺 `indices`/`insti_market`
 * 時對應的格不畫。底色用主色 9% 混 card(零新色票);數字 .num。
 */
export default function MarketBrief({
  radar,
  stale,
}: {
  radar: Pick<RadarJson, "data_date" | "summary" | "indices" | "insti_market">;
  stale: boolean;
}) {
  const indices = orderedIndices(radar.indices);
  const turnover = turnoverCell(radar.summary);
  const insti = instiBriefItems(radar.insti_market);
  const instiDate = dateTag(radar.insti_market?.date, radar.data_date);

  return (
    <section
      aria-label={BRIEF_TITLE}
      className="my-3.5 rounded-[var(--r-lg)] border border-border bg-[linear-gradient(135deg,color-mix(in_srgb,var(--primary)_9%,var(--card)),var(--card)_70%)] px-3 pb-2.5 pt-2 shadow-[var(--shadow-card)]"
    >
      <div className="mb-1.5 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <h2 className="text-[13px] font-bold text-foreground">{BRIEF_TITLE}</h2>
        <span className="num text-[11.5px] text-muted-foreground">
          {"資料日 "}
          <span className="text-[color:var(--ink-2)]">{radar.data_date}</span>
        </span>
        {stale && (
          <span className="rounded-md bg-warn/15 px-1.5 py-px text-[10.5px] font-bold text-warn">{BRIEF_STALE_BADGE}</span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-x-3 gap-y-2 md:grid-cols-4">
        {indices.map((ix) => {
          const tag = dateTag(ix.date, radar.data_date);
          return (
            <div key={ix.market} className="flex min-w-0 flex-col gap-0.5" data-testid={`brief-index-${ix.market}`}>
              <span className="truncate text-[10.5px] text-muted-foreground">
                {ix.name}
                {tag && <span className="num ml-1">{`(${tag})`}</span>}
              </span>
              <span className={cn("num text-[19px] font-bold leading-none tracking-tight", tone(ix.change ?? ix.chg_pct))}>
                {fmtIndex(ix.close)}
              </span>
              <span className={cn("num text-[11.5px] font-semibold", tone(ix.change ?? ix.chg_pct))}>
                {indexChangeText(ix.change, ix.chg_pct)}
              </span>
            </div>
          );
        })}

        {turnover && (
          <div className="flex min-w-0 flex-col gap-0.5" data-testid="brief-turnover" title={BRIEF_UPDOWN_HINT}>
            <span className="text-[10.5px] text-muted-foreground">{BRIEF_TURNOVER_LABEL}</span>
            <span className="num text-[19px] font-bold leading-none tracking-tight text-foreground">{fmtE8(turnover.total)}</span>
            <span className="num flex flex-wrap gap-x-1.5 text-[11px] leading-snug text-[color:var(--ink-2)]">
              {turnover.byMarket.map((m) => (
                <span key={m.market} className="whitespace-nowrap">
                  {(MARKET_LABEL[m.market] ?? m.market) + " "}
                  {fmtE8(m.turnover)}
                </span>
              ))}
              <span className="whitespace-nowrap">
                <span className="text-up">{"↑"}{turnover.up}</span>
                {"/"}
                <span className="text-down">{"↓"}{turnover.down}</span>
              </span>
            </span>
          </div>
        )}

        {insti.length > 0 && (
          <div className="flex min-w-0 flex-col gap-0.5" data-testid="brief-insti" title={BRIEF_INSTI_HINT}>
            <span className="truncate text-[10.5px] text-muted-foreground">
              {BRIEF_INSTI_LABEL}
              {instiDate && <span className="num ml-1">{`(法人 ${instiDate})`}</span>}
            </span>
            <span className={cn("num text-[19px] font-bold leading-none tracking-tight", tone(insti[0].value))}>
              <span className="mr-1 text-[11px] font-semibold text-muted-foreground">{insti[0].label}</span>
              {insti[0].text}
            </span>
            <span className="num flex flex-wrap gap-x-2 text-[11px] leading-snug">
              {insti.slice(1).map((i) => (
                <span key={i.key} className="whitespace-nowrap">
                  <span className="text-muted-foreground">{i.label + " "}</span>
                  <span className={cn("font-semibold", tone(i.value))}>{i.text}</span>
                </span>
              ))}
            </span>
          </div>
        )}
      </div>
    </section>
  );
}
