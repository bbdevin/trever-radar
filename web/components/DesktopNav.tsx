"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { cn, navPillClass } from "@/lib/utils";

const NAV = [
  { label: "首頁", href: "/", match: (path: string, tab: string | null) => path === "/" && tab !== "margin" },
  { label: "監控", href: "/intraday", match: (path: string) => path.startsWith("/intraday") },
  { label: "分點研究", href: "/branch", match: (path: string) => path.startsWith("/branch") },
  { label: "自選追蹤", href: "/watchlist", match: (path: string) => path.startsWith("/watchlist") },
];

function DesktopNavInner() {
  const path = usePathname();
  const tab = useSearchParams().get("tab");
  return (
    <nav className="hidden gap-0.5 md:flex" aria-label="主導覽">
      {NAV.map((n) => {
        const isActive = n.match(path, tab);
        // 跨頁走 client 導覽;已在同一頁時維持原本整頁重載(回到該頁預設狀態)。
        const Item = path === n.href ? "a" : Link;
        return (
          <Item
            key={n.label}
            href={n.href}
            aria-current={isActive ? "page" : undefined}
            className={cn(navPillClass(isActive))}
          >
            {n.label}
          </Item>
        );
      })}
    </nav>
  );
}

/** 桌機頂部導覽（手機隱藏）——資券已在首頁 tab／個股頁，不重複掛導覽；BottomNav 維持 ≤4 項 */
export default function DesktopNav() {
  return (
    <Suspense fallback={<nav className="hidden gap-0.5 md:flex" aria-label="主導覽" />}>
      <DesktopNavInner />
    </Suspense>
  );
}
