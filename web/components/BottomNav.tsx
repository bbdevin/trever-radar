"use client";

import { usePathname } from "next/navigation";
import { IconCompass, IconPulse, IconRadar, IconStar } from "@/components/Icons";
import { cn } from "@/lib/utils";

type NavItem = { label: string; href: string; icon: typeof IconRadar };
const ITEMS: NavItem[] = [
  { label: "首頁", href: "/", icon: IconRadar },
  { label: "監控", href: "/intraday", icon: IconPulse },
  { label: "分點", href: "/branch", icon: IconCompass },
  { label: "自選", href: "/watchlist", icon: IconStar },
];

const itemClass =
  "flex min-h-11 min-w-[62px] cursor-pointer flex-col items-center justify-center gap-0.5 rounded-[10px] px-2.5 py-1 text-[10.5px] text-muted-foreground transition-colors duration-200";

/** 手機底部導航列(桌機隱藏)：首頁右側為監控 */
export default function BottomNav() {
  const path = usePathname();
  return (
    <nav
      aria-label="主導覽"
      className="fixed inset-x-0 bottom-0 z-40 flex justify-around border-t border-border bg-popover/85 px-2 pt-1.5 backdrop-blur-md md:hidden"
      style={{ paddingBottom: "calc(6px + env(safe-area-inset-bottom))" }}
    >
      {ITEMS.map((it) => {
        const active = path === it.href || (it.href !== "/" && path.startsWith(it.href));
        return (
          <a
            key={it.label}
            href={it.href}
            aria-current={active ? "page" : undefined}
            className={cn(itemClass, active && "text-primary")}
          >
            <it.icon size={21} />
            <span>{it.label}</span>
          </a>
        );
      })}
    </nav>
  );
}
