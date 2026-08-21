"use client";

import IntradayPanel from "@/components/IntradayPanel";
import { Activity } from "lucide-react";

/** 盤中監控專頁：即時訊號流 + I-1～I-4 說明（docs/24 + docs/19） */
export default function IntradayPage() {
  return (
    <div className="animate-[fadeUp_0.35s_ease_backwards] py-5 md:py-7">
      <header className="mb-5">
        <div className="mb-1.5 flex items-center gap-2 text-primary">
          <Activity className="h-5 w-5" aria-hidden />
          <span className="text-[12px] font-semibold tracking-wide">INTRA-DAY</span>
        </div>
        <h1 className="text-xl font-extrabold tracking-tight text-foreground md:text-2xl">
          盤中監控
        </h1>
        <p className="mt-1.5 max-w-2xl text-[13.5px] leading-relaxed text-muted-foreground">
          盤後選好要盯的池（未發動籌碼 + 你的自選），盤中有異動才推播。此頁透過 Supabase 即時訂閱更新，無需手動重整。
        </p>
      </header>

      <IntradayPanel variant="full" />

      <p className="mt-4 text-[11.5px] leading-relaxed text-muted-foreground">
        想調整監控對象：到「自選追蹤」加 ★。Fugle 免費方案最多同時監控 5 檔（未發動優先，其餘自選排隊）；worker 約每 5 分鐘重整。
      </p>
    </div>
  );
}
