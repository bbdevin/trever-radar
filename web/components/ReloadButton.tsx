"use client";

import { RefreshCw } from "lucide-react";

/** Header：重新整理目前頁面（硬重整，重新抓資料）。*/
export default function ReloadButton() {
  return (
    <button
      type="button"
      onClick={() => window.location.reload()}
      aria-label="重新整理頁面"
      title="重新整理"
      className="ml-1 grid size-11 shrink-0 cursor-pointer place-items-center rounded-full border border-border bg-card text-muted-foreground transition-colors duration-200 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <RefreshCw size={16} strokeWidth={2} aria-hidden />
    </button>
  );
}
