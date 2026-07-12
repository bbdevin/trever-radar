"use client";

import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const NAV = [
  { label: "今日雷達", href: "/" },
  { label: "分點研究", href: "/branch" },
  { label: "自選追蹤", href: "/watchlist" },
];

/** 桌機頂部導覽（手機隱藏）——使用 usePathname 呈現 active state */
export default function DesktopNav() {
  const path = usePathname();
  return (
    <nav className="hidden gap-0.5 md:flex" aria-label="主導覽">
      {NAV.map((n) => {
        const isActive = path === n.href || (n.href !== "/" && path.startsWith(n.href));
        return (
          <a
            key={n.href}
            href={n.href}
            aria-current={isActive ? "page" : undefined}
            className={cn(
              "rounded-full px-3.5 py-1.5 text-[13.5px] font-semibold transition-colors",
              isActive
                ? "bg-muted text-foreground shadow-[inset_0_0_0_1px_var(--border-strong)]"
                : "text-muted-foreground hover:bg-secondary hover:text-foreground",
            )}
          >
            {n.label}
          </a>
        );
      })}
    </nav>
  );
}
