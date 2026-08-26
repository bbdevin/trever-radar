"use client";

import { useEffect, useState } from "react";
import { ALargeSmall } from "lucide-react";
import { FONT_SCALE_LABEL, useUserPrefs, type FontScale } from "@/lib/userPrefs";

/** Header 文字縮放：循環 標準 → 較大 → 最大；登入後寫入帳號。*/
export default function FontScaleToggle() {
  const { fontScale, cycleFontScale } = useUserPrefs();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const label = mounted ? FONT_SCALE_LABEL[fontScale as FontScale] : FONT_SCALE_LABEL.md;

  return (
    <button
      type="button"
      onClick={() => void cycleFontScale()}
      aria-label={`文字大小：${label}，點擊切換`}
      title={`文字：${label}`}
      className="ml-1 grid size-11 shrink-0 cursor-pointer place-items-center rounded-full border border-border bg-card text-muted-foreground transition-colors duration-200 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <ALargeSmall size={16} strokeWidth={2} aria-hidden />
    </button>
  );
}
