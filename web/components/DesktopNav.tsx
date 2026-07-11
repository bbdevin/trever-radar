"use client";

import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const NAV = [
  { label: "\u4eca\u65e5\u96f7\u9054", href: "/" },
  { label: "\u5206\u9ede\u7814\u7a76", href: "/branch" },
  { label: "\u81ea\u9078\u8ffd\u8e64", href: "/watchlist" },
];

/** \u684c\u6a5f\u9802\u90e8\u5c0e\u89bd\uff08\u624b\u6a5f\u96b1\u85cf\uff09\u2014\u2014\u4f7f\u7528 usePathname \u5448\u73fe active state */
export default function DesktopNav() {
  const path = usePathname();
  return (
    <nav className="hidden gap-0.5 md:flex" aria-label="\u4e3b\u5c0e\u89bd">
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
