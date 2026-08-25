"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, Info } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { dataFetch } from "@/lib/dataFetch";
import { OFFLINE_DATA_COPY, isBrowserOffline } from "@/lib/pwa";
import type { MarginUsageJson } from "@/lib/types";
import { chgClass, fmtLots, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";

/** 融資使用率定義（首頁 tab／/margin 共用） */
export function MarginUsageDefinition({ asOf }: { asOf?: string | null }) {
  return (
    <div className="mb-3 space-y-2 rounded-[var(--r-md)] border border-border bg-card/80 px-3.5 py-3 text-[12.5px] leading-relaxed text-muted-foreground">
      <p className="flex items-start gap-2 text-foreground">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
        <span>
          <span className="font-semibold">融資使用率</span>
          {" = 融資餘額 ÷ 融資限額。資料日 "}
          <span className="num font-medium">{asOf ?? "—"}</span>
          {" · 僅供觀察，不進綜合分。"}
        </span>
      </p>
      <ul className="list-disc space-y-1 pl-6">
        <li>
          <span className="text-foreground/90">融資餘額</span>
          {"：市場上尚未了結的融資張數（投資人向券商借錢買進、尚未賣出償還）。"}
        </li>
        <li>
          <span className="text-foreground/90">融資限額</span>
          {"：交易所／櫃買公布該股「最多可融資幾張」的上限（各股不同，非固定發行股數％；官報直接給限額欄）。"}
        </li>
        <li>
          {"使用率越高＝可用額度越緊。本站 "}
          <span className="font-semibold text-[color:var(--warn)]">≥ 60%</span>
          {" 標為融資過熱風險（對齊 R_MARGIN_HOT 語意）。"}
        </li>
      </ul>
    </div>
  );
}

type Props = {
  /** 精簡標題列（嵌在首頁 tab 時） */
  embedded?: boolean;
};

export default function MarginUsageRank({ embedded = false }: Props) {
  const [data, setData] = useState<MarginUsageJson | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    dataFetch("/data/rankings/margin_usage.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setData)
      .catch(() => setError(true));
  }, []);

  if (error) {
    return (
      <div className="py-12 text-center text-sm text-muted-foreground">
        {isBrowserOffline() ? OFFLINE_DATA_COPY : "尚無融資使用率排行（下次 export-json 後更新）"}
      </div>
    );
  }

  if (!data) {
    return (
      <div className="space-y-2 py-2">
        <Skeleton className="h-24 w-full rounded-[var(--r-md)]" />
        {[0, 1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-12 w-full rounded-[var(--r-md)]" />
        ))}
      </div>
    );
  }

  return (
    <div className={cn("min-w-0", !embedded && "max-w-4xl py-4")}>
      {!embedded && (
        <div className="mb-4">
          <h1 className="text-xl font-extrabold tracking-tight">融資使用率排行</h1>
          <p className="mt-1 text-[13px] text-muted-foreground">
            依融資餘額 ÷ 融資限額由高到低 · 資料日 {data.as_of ?? "—"}
          </p>
        </div>
      )}

      <MarginUsageDefinition asOf={data.as_of} />

      <div className="mb-3 flex items-start gap-2 rounded-[var(--r-md)] border border-[color:var(--warn)]/30 bg-[color:var(--warn)]/10 px-3 py-2 text-[12px] text-muted-foreground">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[color:var(--warn)]" aria-hidden />
        <span>使用率 ≥ 60% 的列以琥珀色標示，提醒融資過熱風險；漲跌另以紅／綠與箭頭表示，色彩非唯一訊號。</span>
      </div>

      <div className="overflow-x-auto rounded-[var(--r-lg)] border border-border bg-card shadow-[var(--shadow-card)]">
        <table className="w-full min-w-[640px] text-left text-[13px]">
          <thead className="border-b border-border bg-secondary/40 text-[12px] text-muted-foreground">
            <tr>
              <th className="px-3 py-2.5 font-semibold">#</th>
              <th className="px-3 py-2.5 font-semibold">代號</th>
              <th className="px-3 py-2.5 font-semibold">名稱</th>
              <th className="px-3 py-2.5 font-semibold">使用率</th>
              <th className="px-3 py-2.5 font-semibold">餘額</th>
              <th className="px-3 py-2.5 font-semibold">增減</th>
              <th className="px-3 py-2.5 font-semibold">收盤</th>
              <th className="px-3 py-2.5 font-semibold">漲跌</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((row, idx) => {
              const hot = row.usage >= 0.6;
              const cls = chgClass(row.chg_pct);
              return (
                <tr
                  key={row.id}
                  className="border-b border-border/60 transition-colors duration-200 last:border-0 hover:bg-secondary/30"
                >
                  <td className="num px-3 py-2.5 text-muted-foreground">{idx + 1}</td>
                  <td className="px-3 py-2.5">
                    <a
                      href={`/stock?id=${row.id}&tab=margin`}
                      className="num cursor-pointer font-bold text-primary hover:underline"
                    >
                      {row.id}
                    </a>
                  </td>
                  <td className="max-w-[140px] truncate px-3 py-2.5" title={row.name}>
                    {row.name}
                  </td>
                  <td className={cn("num px-3 py-2.5 font-bold", hot && "text-[color:var(--warn)]")}>
                    {(row.usage * 100).toFixed(1)}%
                  </td>
                  <td className="num px-3 py-2.5">{fmtLots(row.balance)}</td>
                  <td
                    className={cn(
                      "num px-3 py-2.5",
                      (row.chg ?? 0) >= 0 ? "text-up" : "text-down",
                    )}
                  >
                    {row.chg == null ? "—" : `${row.chg >= 0 ? "+" : ""}${fmtLots(row.chg)}`}
                  </td>
                  <td className="num px-3 py-2.5">{row.close?.toLocaleString("zh-TW") ?? "—"}</td>
                  <td
                    className={cn(
                      "num px-3 py-2.5 font-semibold",
                      cls === "up" && "text-up",
                      cls === "down" && "text-down",
                    )}
                  >
                    {fmtPct(row.chg_pct)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
