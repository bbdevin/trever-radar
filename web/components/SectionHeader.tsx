import type { ReactNode } from "react";
import { CandlestickChart, Layers, Ticket, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * 卡片區塊標頭:28px 家族色 icon chip + 標題 + 選用 meta(標題下一行)/ right(右側)。
 * 家族色沿用 ReasonPill 的語意家族(docs/19 §4):籌碼＝accent-2 青、權證＝warn 琥珀、
 * K 線/價格＝primary 藍。只用既有 token 的 /12 淡底,不引入新色票;icon 與標題文字
 * 一起出現,顏色不是唯一訊號。
 */
export type SectionFamily = "chips" | "warrant" | "price";

const FAMILY: Record<SectionFamily, { icon: LucideIcon; chip: string }> = {
  chips: { icon: Layers, chip: "bg-[color:var(--accent-2)]/12 text-[color:var(--accent-2)]" },
  warrant: { icon: Ticket, chip: "bg-warn/12 text-warn" },
  price: { icon: CandlestickChart, chip: "bg-primary/12 text-primary" },
};

export default function SectionHeader({
  family,
  title,
  id,
  as: Heading = "h2",
  meta,
  right,
  className,
}: {
  family: SectionFamily;
  title: ReactNode;
  /** 給外層 section 的 aria-labelledby */
  id?: string;
  as?: "h2" | "h3";
  /** 標題下方的輔助行(日期、窗口、計數) */
  meta?: ReactNode;
  /** 右側槽(chip、按鈕) */
  right?: ReactNode;
  className?: string;
}) {
  const { icon: Icon, chip } = FAMILY[family];
  return (
    <div className={cn("flex min-w-0 items-start justify-between gap-x-3 gap-y-1.5", className)}>
      <div className="flex min-w-0 items-start gap-2.5">
        <span
          aria-hidden
          className={cn("grid h-7 w-7 shrink-0 place-items-center rounded-[var(--r-sm)]", chip)}
        >
          <Icon size={16} strokeWidth={1.8} />
        </span>
        <div className="grid min-w-0 gap-0.5">
          <Heading id={id} className="text-[15px] font-bold leading-7 text-foreground">
            {title}
          </Heading>
          {meta != null && <div className="text-[11.5px] leading-snug text-muted-foreground">{meta}</div>}
        </div>
      </div>
      {right != null && <div className="flex shrink-0 flex-wrap items-center justify-end gap-1.5">{right}</div>}
    </div>
  );
}
