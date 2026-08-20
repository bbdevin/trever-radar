import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** 膠囊分頁按鈕樣式(K線/範圍/分點期間等共用) */
export function pillTabClass(active: boolean) {
  return cn(
    "rounded-full bg-transparent px-3.5 py-1.5 text-[12.5px] font-semibold text-[color:var(--ink-2)]",
    active && "bg-muted text-foreground shadow-[inset_0_0_0_1px_var(--border-strong)]",
  )
}

/** 買超/賣超左右對半切(全寬 1:1,比照籌碼日報常見分段) */
export function halfSegClass(active: boolean, side: "buy" | "sell") {
  return cn(
    "min-h-11 w-full rounded-md px-2 text-[13px] font-semibold transition-colors",
    side === "buy" && active && "bg-up/15 text-up shadow-[inset_0_0_0_1px_rgba(230,103,103,0.4)]",
    side === "sell" && active && "bg-down/15 text-down shadow-[inset_0_0_0_1px_rgba(12,163,12,0.4)]",
    !active && "text-muted-foreground hover:text-foreground",
  )
}
