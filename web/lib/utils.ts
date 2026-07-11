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
