"use client";

import IntradayPanel from "@/components/IntradayPanel";
import { Activity } from "lucide-react";

/** 盤中監控專頁 */
export default function IntradayPage() {
  return (
    <div className="animate-[fadeUp_0.35s_ease_backwards] py-5 md:py-7">
      <header className="mb-5">
        <div className="mb-1.5 flex items-center gap-2 text-primary">
          <Activity className="h-5 w-5" aria-hidden />
          <span className="text-[12px] font-semibold tracking-wide">MONITOR</span>
        </div>
        <h1 className="text-xl font-extrabold tracking-tight text-foreground md:text-2xl">
          盤中監控
        </h1>
        <p className="mt-1.5 max-w-2xl text-[13.5px] leading-relaxed text-muted-foreground">
          盤後選好要盯的池（未發動籌碼 + 自選，不含 ETF），盤中有異動才推播。此頁即時更新，無需手動重整。
        </p>
      </header>

      <IntradayPanel />

      <p className="mt-4 text-[11.5px] leading-relaxed text-muted-foreground">
        想調整監控對象：到「自選追蹤」加 ★。額度見頁頂「監控 n/上限」；未發動優先，ETF（如 0050）不納入。
      </p>
    </div>
  );
}
