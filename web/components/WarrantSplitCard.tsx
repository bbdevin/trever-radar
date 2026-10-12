"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export type SplitBreakdownRow = {
  warrant_id: string;
  warrant_name: string;
  kind: "call" | "put" | string;
  net_lots: number;
  net_amount: number;
};

export type SplitItem = {
  key: string;
  /** 列的主文字(券商名或標的名;可含連結)。 */
  label: ReactNode;
  /** 文字版(aria-label 用)。 */
  text: string;
  /** 淨額(元),>0 進左欄「買超」、<0 進右欄「賣超」;0 不列。 */
  amount: number;
  breakdown?: SplitBreakdownRow[];
  /** 列的第二行(例「仍持有(估) …」),可選。 */
  line2?: string | null;
  /** 可選:個股權證分頁深連結(選中這家券商);列右側多一顆「›」連結,列本身仍是展開明細。 */
  href?: string;
};

/** 元 → 帶號萬(「+1,234」「-56.7」):淨額欄只有紅綠時補上正負號,顏色不是唯一訊號。 */
export function signedWan(amt: number, digits: number): string {
  const s = (Math.abs(amt) / 10000).toLocaleString("zh-TW", { maximumFractionDigits: digits });
  return `${amt > 0 ? "+" : amt < 0 ? "-" : ""}${s}`;
}

/** 元 → 「1,234 萬」(不帶號)。 */
export function absWan(amt: number, digits = 0): string {
  return `${(Math.abs(amt) / 10000).toLocaleString("zh-TW", { maximumFractionDigits: digits })} 萬`;
}

/**
 * /branch 權證分點異動的卡片(依標的／依分點共用;docs/51 §3.2):標題列 + 左「買超」右「賣超」
 * 兩欄,每欄自己的合計;點一列在兩欄下方展開它的逐檔權證明細(全寬,手機兩欄太窄放不下)。
 * 兩欄在 390px 手機也並排(使用者 2026-10-12 要求左買右賣),名稱截斷、金額整數萬。
 */
export default function WarrantSplitCard({
  title,
  totalAmt,
  items,
  subtitle,
}: {
  title: ReactNode;
  totalAmt: number;
  items: SplitItem[];
  subtitle?: ReactNode;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const buys = items.filter((i) => i.amount > 0).sort((a, b) => b.amount - a.amount);
  const sells = items.filter((i) => i.amount < 0).sort((a, b) => a.amount - b.amount);
  const buyTotal = buys.reduce((s, i) => s + i.amount, 0);
  const sellTotal = sells.reduce((s, i) => s + i.amount, 0);
  const open = items.find((i) => i.key === expanded && i.breakdown && i.breakdown.length > 0) ?? null;

  return (
    <div className="flex min-w-0 flex-col overflow-hidden rounded-[var(--r-lg)] border border-border bg-card shadow-sm transition-colors duration-300 hover:border-border-strong">
      <div className="flex items-center justify-between gap-2 border-b border-border bg-card px-3.5 py-3">
        <div className="min-w-0">
          {title}
          {subtitle && <div className="mt-0.5 text-[11px] text-muted-foreground">{subtitle}</div>}
        </div>
        <div className="flex shrink-0 flex-col items-end">
          <span className="mb-0.5 text-[10px] font-bold tracking-wider text-muted-foreground">淨額</span>
          <span className={cn("num text-lg font-bold tracking-tight", totalAmt > 0 ? "text-up" : totalAmt < 0 ? "text-down" : "text-foreground")}>
            {signedWan(totalAmt, 0)} 萬
          </span>
        </div>
      </div>

      <div className="grid min-w-0 grid-cols-2 gap-2 bg-background p-2.5" data-testid="warrant-split-columns">
        <SplitColumn tone="up" title="買超" total={buyTotal} items={buys} expanded={expanded} onToggle={setExpanded} />
        <SplitColumn tone="down" title="賣超" total={sellTotal} items={sells} expanded={expanded} onToggle={setExpanded} />
      </div>

      {open && open.breakdown && (
        <div className="border-t border-border/60 bg-secondary/20 px-2.5 py-2">
          <p className="mb-1 px-1 text-[11px] font-semibold text-foreground">{open.text} 的權證明細</p>
          <div className="mb-1 grid grid-cols-[1.5fr_1fr_0.7fr] px-1 text-[10px] font-semibold text-muted-foreground">
            <span>權證</span>
            <span className="text-right">估金額</span>
            <span className="text-right">占比</span>
          </div>
          <ul className="flex flex-col gap-1">
            {open.breakdown.map((brk) => (
              <li
                key={brk.warrant_id}
                className={cn(
                  "grid grid-cols-[1.5fr_1fr_0.7fr] items-center rounded-md border-l-2 px-1.5 py-1.5",
                  brk.net_amount > 0 ? "border-l-up/60" : "border-l-down/60",
                )}
              >
                <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                  <span className="truncate text-[12.5px] font-medium text-foreground" title={brk.warrant_name}>{brk.warrant_name}</span>
                  <span className={cn("rounded px-1 py-0.5 text-[9px] font-bold leading-none", brk.kind === "call" ? "bg-up/10 text-up" : "bg-down/10 text-down")}>
                    {brk.kind === "call" ? "購" : "售"}
                  </span>
                </div>
                <span className={cn("num text-right text-[13px] font-medium tracking-tight", brk.net_amount > 0 ? "text-up" : "text-down")}>
                  {signedWan(brk.net_amount, 1)} 萬
                </span>
                <span className="num text-right text-[11px] text-muted-foreground">
                  {open.amount ? `${Math.round((Math.abs(brk.net_amount) / Math.abs(open.amount)) * 100)}%` : "—"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function SplitColumn({
  tone,
  title,
  total,
  items,
  expanded,
  onToggle,
}: {
  tone: "up" | "down";
  title: string;
  total: number;
  items: SplitItem[];
  expanded: string | null;
  onToggle: (key: string | null) => void;
}) {
  return (
    <div className="min-w-0 overflow-hidden rounded-[var(--r-md)] border border-border">
      <div className={cn("flex items-baseline justify-between gap-1 px-2 py-1.5 text-[12px] font-bold", tone === "up" ? "bg-up/12 text-up" : "bg-down/12 text-down")}>
        <span>{title}</span>
        <span className="num text-[11px] font-semibold">{items.length ? absWan(total) : ""}</span>
      </div>
      {items.length === 0 ? (
        <p className="px-2 py-3 text-center text-[11px] text-muted-foreground">無</p>
      ) : (
        <ol className="divide-y divide-[color:var(--line)]">
          {items.map((i) => {
            const hasBreakdown = !!i.breakdown && i.breakdown.length > 0;
            const isOpen = expanded === i.key;
            return (
              <li key={i.key} className={cn("flex min-w-0 items-stretch", isOpen && "bg-secondary/70")}>
                <button
                  type="button"
                  onClick={() => onToggle(isOpen ? null : i.key)}
                  aria-expanded={hasBreakdown ? isOpen : undefined}
                  aria-label={`${i.text} 權證明細`}
                  className="grid min-h-10 min-w-0 flex-1 grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-1.5 gap-y-0.5 px-2 py-1.5 text-left text-[12.5px] transition-colors hover:bg-secondary"
                >
                  <span className="min-w-0 truncate font-medium text-foreground" title={i.text}>{i.label}</span>
                  <span className={cn("num shrink-0 text-[12.5px] font-bold tracking-tight", tone === "up" ? "text-up" : "text-down")}>
                    {absWan(i.amount)}
                  </span>
                  {i.line2 && (
                    <span className="col-span-2 truncate text-[10.5px] font-normal leading-tight text-muted-foreground" title={i.line2}>
                      {i.line2}
                    </span>
                  )}
                </button>
                {i.href && (
                  <Link
                    href={i.href}
                    aria-label={`${i.text}:個股權證分頁與走勢`}
                    className="flex w-7 shrink-0 items-center justify-center border-l border-[color:var(--line)] text-muted-foreground no-underline transition-colors hover:bg-secondary hover:text-foreground"
                  >
                    ›
                  </Link>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
