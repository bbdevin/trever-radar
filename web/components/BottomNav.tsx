"use client";

import { usePathname } from "next/navigation";
import { IconCompass, IconPulse, IconRadar, IconStar, IconTrend } from "@/components/Icons";

const ITEMS = [
  { label: "雷達", href: "/", icon: IconRadar },
  { label: "分點", href: "/branch", icon: IconCompass },
  { label: "探索", href: "/explore", icon: IconTrend },
  { label: "自選", href: "/watchlist", icon: IconStar },
  { label: "盤中", icon: IconPulse, badge: "V2" },
];

/** 手機底部導航列(桌機隱藏) */
export default function BottomNav() {
  const path = usePathname();
  return (
    <nav className="bottom-nav" aria-label="主導覽">
      {ITEMS.map((it) =>
        it.href ? (
          <a key={it.label} href={it.href} className={path === it.href ? "bn-item active" : "bn-item"}>
            <it.icon size={21} />
            <span>{it.label}</span>
          </a>
        ) : (
          <span key={it.label} className="bn-item disabled" title="開發中">
            <it.icon size={21} />
            <span>
              {it.label}
              <small>{it.badge}</small>
            </span>
          </span>
        ),
      )}
    </nav>
  );
}
