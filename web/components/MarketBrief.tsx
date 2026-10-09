"use client";

import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import type { MarketIndex, RadarJson } from "@/lib/types";
import IndexTrendSheet from "@/components/IndexTrendSheet";
import {
  BRIEF_INSTI_HINT,
  BRIEF_STALE_BADGE,
  BRIEF_TITLE,
  BRIEF_UPDOWN_HINT,
  TILE_SLOTS,
  dateTag,
  fmtE8,
  fmtIndex,
  indexChangeText,
  indexDecimals,
  indexPctText,
  instiBriefItems,
  isNightNewer,
  mmdd,
  nightTileText,
  nightTileTitle,
  orderedIndices,
  sparkPath,
  turnoverCell,
} from "@/lib/marketBrief";

function tone(n: number | null | undefined): string {
  if (n == null || n === 0) return "text-foreground";
  return n > 0 ? "text-up" : "text-down";
}

const SPARK_H = 16;

/**
 * 迷你走勢圖:inline SVG、滿格寬、16px 高(40 個收盤,不另載圖表庫);少於 2 點不畫。
 * 描邊一律中性(`--ink-2`):旁邊的數字是「今日」漲跌,40 日方向常與今日相反,兩個紅綠擺一起會打架;
 * 顏色留給數字,走勢只給形狀(docs/49 §12.3)。
 */
export function Sparkline({ values }: { values: number[] | undefined }) {
  const w = 100;
  const d = sparkPath(values, w, SPARK_H);
  if (!d) return <span className="block h-4" aria-hidden />;
  return (
    <svg
      viewBox={`0 0 ${w} ${SPARK_H}`}
      className="block h-4 w-full overflow-visible"
      preserveAspectRatio="none"
      aria-hidden
    >
      <path d={d} fill="none" stroke="var(--ink-2)" strokeOpacity={0.85} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

const TILE_BASE =
  "flex min-h-11 min-w-0 flex-col gap-0.5 rounded-[10px] bg-[color:color-mix(in_srgb,var(--foreground)_5%,var(--card))] px-2 py-1 text-left";

/**
 * 指數格:整格是按鈕(開走勢圖),右上「›」提示可點,按下有壓感;格內只放 %(點數在 sheet)。
 * 台指期格多一行夜盤(docs/49 §12.6)「夜 49,593 ▼0.75%」:最新一夜的盤後收盤,與格內其他數字同寬;
 * 時間範圍在 title 與 sheet(夜盤跨午夜、連假前一夜標在假後,格裡放不下日期)。
 */
function IndexTile({ ix, label, dataDate, onOpen }: { ix: MarketIndex; label: string; dataDate: string; onOpen: (m: string) => void }) {
  const tag = dateTag(ix.date, dataDate);
  const t = tone(ix.change ?? ix.chg_pct);
  const dec = indexDecimals(ix.market);
  const night = ix.market === "tx" ? ix.night : undefined;
  const nightNewer = isNightNewer(night, ix.date);
  return (
    <button
      type="button"
      data-testid={`brief-index-${ix.market}`}
      onClick={() => onOpen(ix.market)}
      aria-label={`${ix.name} 走勢`}
      title={`${ix.name} ${fmtIndex(ix.close, dec)} ${indexChangeText(ix.change, ix.chg_pct, dec)}${night ? `;${nightTileTitle(night)}` : ""};點開走勢圖`}
      className={cn(
        TILE_BASE,
        "cursor-pointer transition-[background-color,transform] duration-150 hover:bg-secondary active:scale-[0.97] active:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
      )}
    >
      <span className="flex w-full items-center text-[11px] leading-none text-muted-foreground">
        <span className="truncate">
          {label}
          {tag && <span className="num ml-1">{`(${mmdd(ix.date)})`}</span>}
        </span>
        <ChevronRight size={12} strokeWidth={2.2} className="ml-auto shrink-0 text-[color:var(--ink-2)]" aria-hidden />
      </span>
      <span className={cn("num text-[15px] font-semibold leading-none tracking-tight", t)}>{fmtIndex(ix.close, dec)}</span>
      <span className={cn("num truncate text-[11px] font-semibold leading-none", t)}>{indexPctText(ix.change, ix.chg_pct, dec)}</span>
      {night && (
        <span
          className={cn("num truncate text-[10px] leading-none", nightNewer ? "font-semibold" : "font-medium", tone(night.change ?? night.chg_pct))}
          data-testid="brief-tx-night"
        >
          {nightTileText(night)}
        </span>
      )}
      <Sparkline values={ix.spark} />
    </button>
  );
}

/** 只有這一個序列還沒回補:中性「—」格,不可點(三格都沒有時整列不畫) */
function EmptyTile({ label }: { label: string }) {
  return (
    <div className={cn(TILE_BASE, "opacity-70")} data-testid="brief-index-empty" aria-label={`${label} 尚無資料`}>
      <span className="truncate text-[11px] leading-none text-muted-foreground">{label}</span>
      <span className="num text-[15px] font-semibold leading-none text-muted-foreground">—</span>
      <span className="text-[11px] leading-none text-muted-foreground">{"尚無資料"}</span>
      <span className="block h-4" aria-hidden />
    </div>
  );
}

/* 夜盤那一行讓台指期格多 ~12px;grid 列高取最高的格,三格一樣高,另外兩格多出的空間落在迷你走勢上方(flex 預設)。
   為了把卡壓回 ~150px(§12.6):格的上下 padding 6→4、標題列下緣 4→2(390px 實測 144 → 150)。 */

/**
 * 首頁「市場概況」(docs/49 §11–12,2026-10-09 使用者選 A 版):一張緊湊卡。
 * 第一列三格可點(加權 / 櫃買 / 台指期 近月):收盤、今日 %、16px 迷你走勢,點開 bottom sheet 看走勢圖;
 * 第二列一行:成交額 ↑↓家數 · 外資 · 投信 · 自營。資料日與「部分待更新」在最上面一行小字。
 * 舊 payload / 還沒回補:完全沒有 `indices` → 不畫指數列(只剩成交/法人一行);只缺一個序列 → 那格「—」。
 */
export default function MarketBrief({
  radar,
  stale,
}: {
  radar: Pick<RadarJson, "data_date" | "summary" | "indices" | "insti_market">;
  stale: boolean;
}) {
  const indices = orderedIndices(radar.indices);
  const byMarket = new Map(indices.map((i) => [i.market, i]));
  const turnover = turnoverCell(radar.summary);
  const insti = instiBriefItems(radar.insti_market);
  const instiDate = dateTag(radar.insti_market?.date, radar.data_date);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [sheetMarket, setSheetMarket] = useState<string>("twse");
  const openSheet = (m: string) => {
    setSheetMarket(m);
    setSheetOpen(true);
  };

  return (
    <>
      {indices.length > 0 && (
        <IndexTrendSheet
          open={sheetOpen}
          onOpenChange={setSheetOpen}
          market={sheetMarket}
          onMarketChange={setSheetMarket}
          indices={indices}
          dataDate={radar.data_date}
        />
      )}
      <section
        aria-label={BRIEF_TITLE}
        data-testid="market-brief"
        className="my-2.5 rounded-[var(--r-lg)] border border-border bg-[linear-gradient(135deg,color-mix(in_srgb,var(--primary)_9%,var(--card)),var(--card)_70%)] px-2.5 pb-2 pt-1.5 shadow-[var(--shadow-card)]"
      >
        <div className="mb-0.5 flex items-center gap-x-2 text-[11px] leading-none">
          <span className="font-bold text-foreground">{BRIEF_TITLE}</span>
          <span className="num text-muted-foreground">{`資料日 ${mmdd(radar.data_date)}`}</span>
          {stale && (
            <span className="rounded bg-warn/15 px-1 py-px text-[10px] font-bold text-warn">{BRIEF_STALE_BADGE}</span>
          )}
        </div>

        {indices.length > 0 && (
          <div className="grid grid-cols-3 gap-1.5" data-testid="brief-tiles">
            {TILE_SLOTS.map((slot) => {
              const ix = byMarket.get(slot.market);
              return ix
                ? <IndexTile key={slot.market} ix={ix} label={slot.label} dataDate={radar.data_date} onOpen={openSheet} />
                : <EmptyTile key={slot.market} label={slot.label} />;
            })}
          </div>
        )}

        {(turnover || insti.length > 0) && (
          <p className={cn("num flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5 text-[12px] leading-snug text-[color:var(--ink-2)]", indices.length > 0 && "mt-1.5")} data-testid="brief-line">
            {turnover && (
              <span className="whitespace-nowrap" title={BRIEF_UPDOWN_HINT}>
                <span className="text-muted-foreground">{"成交 "}</span>
                <span className="font-semibold text-foreground">{fmtE8(turnover.total)}</span>
                {" "}
                <span className="text-up">{"↑"}{turnover.up}</span>
                {" "}
                <span className="text-down">{"↓"}{turnover.down}</span>
              </span>
            )}
            {insti.map((i, k) => (
              <span key={i.key} className="whitespace-nowrap" title={BRIEF_INSTI_HINT}>
                {(turnover || k > 0) && <span className="text-muted-foreground">{"· "}</span>}
                <span className="text-muted-foreground">{i.label + " "}</span>
                <span className={cn("font-semibold", tone(i.value))}>{i.text}</span>
                {k === insti.length - 1 && instiDate && <span className="text-muted-foreground">{` (法人 ${instiDate})`}</span>}
              </span>
            ))}
          </p>
        )}
      </section>
    </>
  );
}
