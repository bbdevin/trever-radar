import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** 選取態色調（對齊品牌 token；避免灰底 inset 看不清） */
export type SelectTone = "primary" | "accent" | "warn"

const SELECT_ACTIVE: Record<SelectTone, string> = {
  primary: "bg-primary text-primary-foreground shadow-sm",
  accent: "bg-[color:var(--accent-2)] text-white shadow-sm",
  warn: "bg-[color:var(--warn)] text-white shadow-sm dark:text-[#141412]",
}

const SELECT_IDLE =
  "bg-transparent text-muted-foreground hover:bg-secondary/80 hover:text-foreground"

/**
 * 膠囊分頁（個股 tab／K 線區間／大戶／籌碼日數等）。
 * 預設 primary 藍；次要分組可傳 accent／warn。
 */
export function pillTabClass(active: boolean, tone: SelectTone = "primary") {
  return cn(
    "cursor-pointer rounded-full px-3.5 py-1.5 text-[12.5px] font-semibold transition-colors duration-200",
    active ? SELECT_ACTIVE[tone] : SELECT_IDLE,
  )
}

/** 導覽／首頁／分點研究等較大 pill（可含 icon） */
export function navPillClass(active: boolean, tone: SelectTone = "primary") {
  return cn(
    "cursor-pointer rounded-full px-3.5 py-1.5 text-[13.5px] font-semibold transition-colors duration-200",
    active ? SELECT_ACTIVE[tone] : SELECT_IDLE,
  )
}

/** 緊湊分段鈕（日K／MACD 等 rounded-md 群組內） */
export function segBtnClass(active: boolean, tone: SelectTone = "accent") {
  return cn(
    "min-h-9 cursor-pointer rounded-md px-3 py-1 text-xs font-semibold transition-colors duration-200",
    active ? SELECT_ACTIVE[tone] : SELECT_IDLE,
  )
}

/** 篩選 toggle（可追蹤／樣本足夠等） */
export function filterChipClass(active: boolean, tone: SelectTone = "accent") {
  return cn(
    "cursor-pointer rounded-full px-3 py-1 text-[12px] font-semibold transition-colors duration-200",
    active
      ? SELECT_ACTIVE[tone]
      : "bg-muted text-muted-foreground hover:bg-secondary hover:text-foreground",
  )
}

/** 列表列／卡片選中：青綠淡底＋描邊（非填滿，避免整列搶戲） */
export function softSelectClass(active: boolean) {
  return active
    ? "bg-[color:var(--accent-2)]/12 shadow-[inset_0_0_0_1px_color-mix(in_oklab,var(--accent-2)_40%,transparent)]"
    : ""
}
