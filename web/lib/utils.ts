import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** 膠囊分頁按鈕樣式(個股 tab／K線區間／大戶門檻等共用) */
export function pillTabClass(active: boolean) {
  return cn(
    "cursor-pointer rounded-full px-3.5 py-1.5 text-[12.5px] font-semibold transition-colors duration-200",
    active
      ? "bg-primary text-primary-foreground shadow-sm"
      : "bg-transparent text-muted-foreground hover:bg-secondary/80 hover:text-foreground",
  )
}
