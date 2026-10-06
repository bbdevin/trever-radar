import { Info } from "lucide-react";

import {
  HOWTO_LINES,
  PL_LABELS,
  distSeg,
  fmtLevelPrice,
  fmtShare,
  type LadderRow,
} from "@/lib/priceLevels";
import { cn } from "@/lib/utils";

/**
 * 價格位置的小元件(docs/45 §4):價格階梯(上方紅 +%、現價藍帶、下方綠 −%)、現價上下成交量雙色條、
 * 「怎麼算」精簡說明(常駐)。docs/46 起由多空分頁「技術分析」卡內的壓力分析小節組裝(BullBearPanel),不再單獨成卡。
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
  // 距離字與色調同一個 distSeg:四捨五入為 0 的寫「貼近現價」、中性色,不會一邊紅字一邊說貼近
  const dist = distSeg(row.dist);
  const tone = dist.kind === "up" ? "text-up" : dist.kind === "down" ? "text-down" : "text-foreground";
  return (
    <li className="grid min-h-8 grid-cols-[minmax(0,1fr)_auto_4.25rem] items-center gap-2 px-2.5 text-[12.5px]" data-kind={row.kind}>
      <span className="min-w-0 truncate text-[color:var(--ink-2)]" title={row.label}>
        {row.label}
        {row.date && <span className="num ml-1.5 text-[11px] text-muted-foreground">{row.date}</span>}
      </span>
      <span className="num font-bold text-primary">
        {fmtLevelPrice(row.price, close)}
        {/* 密集區與缺口是一段區間:下緣–上緣 */}
        {row.priceHi != null && <>–{fmtLevelPrice(row.priceHi, close)}</>}
      </span>
      {isZone && row.share != null ? (
        <span className="num text-right font-semibold text-[color:var(--ink-2)]">{PL_LABELS.share} {fmtShare(row.share)}</span>
      ) : (
        <span className={cn("num text-right font-semibold", tone)}>{dist.t}</span>
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

/** 「怎麼算」精簡說明:常駐顯示的幾行小字(使用者不喜歡收合,docs/46 §6.8)。 */
export function HowTo({ lines = HOWTO_LINES, testId = "price-levels-howto" }: { lines?: readonly string[]; testId?: string }) {
  return (
    <div data-testid={testId} className="grid min-w-0 gap-0.5 border-l-2 border-[color:var(--line)] pl-2.5">
      <p className="flex items-center gap-1 text-[11.5px] font-bold text-[color:var(--ink-2)]">
        <Info size={12} aria-hidden />
        {PL_LABELS.howto}
      </p>
      <ul className="grid gap-0.5 text-[11.5px] leading-snug text-[color:var(--ink-2)]">
        {lines.map((l) => <li key={l}>{l}</li>)}
      </ul>
    </div>
  );
}
