import { ChevronDown } from "lucide-react";

import {
  HOWTO_LINES,
  PL_LABELS,
  fmtDist,
  fmtLevelPrice,
  fmtShare,
  type LadderRow,
} from "@/lib/priceLevels";
import { cn } from "@/lib/utils";

/**
 * 價格位置的小元件(docs/45 §4):價格階梯(上方紅 +%、現價藍帶、下方綠 −%)、現價上下成交量雙色條、
 * 「怎麼算」收合。docs/46 v2 起由多空分頁「壓力分析」段組裝(BullBearPanel),不再單獨成卡。
 * 只顯示事實,不影響任何分數。
 */
export function PriceLadder({ above, below, close }: { above: LadderRow[]; below: LadderRow[]; close: number }) {
  return (
    <ol className="grid min-w-0 gap-0.5" aria-label="價格階梯(由高到低)">
      {above.map((r) => <LadderLine key={r.key} row={r} close={close} />)}
      <li
        data-testid="price-levels-current"
        className="my-0.5 grid min-h-9 grid-cols-[minmax(0,1fr)_auto] items-center gap-2 rounded-[var(--r-sm)] bg-primary/12 px-2.5 text-[13px] font-bold text-primary"
      >
        <span>{PL_LABELS.current}</span>
        <span className="num text-[15px]">{fmtLevelPrice(close, close)}</span>
      </li>
      {below.map((r) => <LadderLine key={r.key} row={r} close={close} />)}
    </ol>
  );
}

function LadderLine({ row, close }: { row: LadderRow; close: number }) {
  const isZone = row.kind === "zone";
  const tone = row.dist > 0 ? "text-up" : row.dist < 0 ? "text-down" : "text-foreground";
  return (
    <li className="grid min-h-8 grid-cols-[minmax(0,1fr)_auto_4.25rem] items-center gap-2 px-2.5 text-[12.5px]">
      <span className="min-w-0 truncate text-[color:var(--ink-2)]" title={row.label}>
        {row.label}
        {row.date && <span className="num ml-1.5 text-[11px] text-muted-foreground">{row.date}</span>}
      </span>
      <span className="num font-bold text-primary">
        {fmtLevelPrice(row.price, close)}
        {isZone && row.priceHi != null && <>–{fmtLevelPrice(row.priceHi, close)}</>}
      </span>
      {isZone && row.share != null ? (
        <span className="num text-right font-semibold text-[color:var(--ink-2)]">{PL_LABELS.share} {fmtShare(row.share)}</span>
      ) : (
        <span className={cn("num text-right font-semibold", tone)}>{fmtDist(row.dist)}</span>
      )}
    </li>
  );
}

export function VolumeSplit({ volume }: { volume: { window: number; above: number; below: number; at: number } }) {
  const sum = volume.above + volume.below || 1;
  return (
    <div className="grid min-w-0 gap-1.5" data-testid="price-levels-volume">
      <div className="flex min-w-0 items-baseline justify-between gap-2 text-[12px]">
        <span className="text-muted-foreground">近{volume.window}日成交</span>
        <span className="num">
          <span className="font-semibold text-up">現價之上 {fmtShare(volume.above)}</span>
          <span className="mx-1.5 text-muted-foreground">|</span>
          <span className="font-semibold text-down">之下 {fmtShare(volume.below)}</span>
        </span>
      </div>
      {/* 條軌獨立一列,文字不會被條蓋到(docs/19 §2-4) */}
      <div className="flex h-2.5 min-w-0 overflow-hidden rounded-full bg-secondary" aria-hidden>
        <span className="h-full bg-up/80" style={{ width: `${(volume.above / sum) * 100}%` }} />
        <span className="h-full bg-down/80" style={{ width: `${(volume.below / sum) * 100}%` }} />
      </div>
      {volume.at >= 0.005 && (
        <p className="text-[11px] text-muted-foreground">另有 {fmtShare(volume.at)} 成交剛好在現價</p>
      )}
    </div>
  );
}

export function HowTo() {
  return (
    <details className="group min-w-0 rounded-[var(--r-sm)] border border-[color:var(--line)]">
      <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-2 px-3 text-[12.5px] font-semibold text-[color:var(--ink-2)] [&::-webkit-details-marker]:hidden">
        {PL_LABELS.howto}
        <ChevronDown size={16} aria-hidden className="transition-transform duration-200 group-open:rotate-180" />
      </summary>
      <ul className="grid gap-1.5 px-3 pb-3 text-[12px] leading-relaxed text-[color:var(--ink-2)]">
        {HOWTO_LINES.map((l) => <li key={l}>{l}</li>)}
      </ul>
    </details>
  );
}
