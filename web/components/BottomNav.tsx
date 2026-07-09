"use client";

import { usePathname } from "next/navigation";
import { IconCompass, IconPulse, IconRadar, IconStar, IconTrend } from "@/components/Icons";
import { cn } from "@/lib/utils";

const ITEMS = [
  { label: "雷達", href: "/", icon: IconRadar },
  { label: "分點", href: "/branch", icon: IconCompass },
  { label: "探索", href: "/explore", icon: IconTrend },
  { label: "自選", href: "/watchlist", icon: IconStar },
  { label: "盤中", icon: IconPulse, badge: "V2" },
];

const itemClass = "flex min-w-[62px] flex-col items-center gap-0.5 rounded-[10px] px-2.5 py-1 text-[10.5px] text-muted-foreground";

/** 手機底部導航列(桌機隱藏) */
export default function BottomNav() {
  const path = usePathname();
  return (
    <nav
      aria-label="主導覽"
      className="fixed inset-x-0 bottom-0 z-40 flex justify-around border-t border-border bg-popover/85 px-2 pt-1.5 backdrop-blur-md md:hidden"
      style={{ paddingBottom: "calc(6px + env(safe-area-inset-bottom))" }}
    >
      {ITEMS.map((it) =>
        it.href ? (
          <a key={it.label} href={it.href} className={cn(itemClass, path === it.href && "text-primary")}>
            <it.icon size={21} />
            <span>{it.label}</span>
          </a>
        ) : (
          <span key={it.label} className={cn(itemClass, "cursor-default opacity-55")} title="開發中">
            <it.icon size={21} />
            <span>
              {it.label}
              <small className="ml-0.5 text-[8.5px]">{it.badge}</small>
            </span>
          </span>
        ),
      )}
    </nav>
  );
}
