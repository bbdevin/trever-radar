"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Layers } from "lucide-react";
import { dataFetch } from "@/lib/dataFetch";
import { cn } from "@/lib/utils";
import {
  anomalyEmptyStateText,
  anomalyLagText,
  anomalyMeaningText,
  futuresAnomalyMarketState,
  groupBySpotFollow,
  spotFollowLabel,
} from "@/lib/futures";
import type { FuturesVolumeAnomalyEntry, FuturesVolumeAnomalyMeta } from "@/lib/types";

/**
 * 首頁「期貨異常」分頁的名單(docs/38 §7.5;2026-10-02 依使用者要求改版,§7.17)。
 *
 * 改版重點:先講讀這個旗標時最重要的一件事——**現貨有沒有跟上**。檢定只對
 * 「期貨創高、現貨還沒跟上」成立,所以那一種排前面、貼醒目標籤;現貨已同步爆量
 * 的排後面(分組,不是名次——組內維持 payload 的順序,§5)。數字壓成一列,不再
 * 用一句話把同樣的數字重講一遍;風險提醒改成一行小字,不用紅色警示框。
 *
 * 判斷全部在 `lib/futures.ts` 的純函式裡(三態、事實列、分組、標籤),由
 * `lib/futures.test.ts` 鎖住;這裡只負責排版。名單**不編號**(§5)。
 */
export default function FuturesAnomalyList({
  entries,
  dataDate,
  nameById,
  meta,
}: {
  entries: FuturesVolumeAnomalyEntry[] | undefined;
  dataDate: string;
  nameById: ReadonlyMap<string, string>;
  /** 與 `entries` 同生共死(§7.11);缺鍵時空名單那句話就少講比較窗口。 */
  meta?: FuturesVolumeAnomalyMeta;
}) {
  // 首頁的 radar.stocks 只是評分池,舉旗的股票常常不在裡面(2371、3045 曾只顯示代號)。
  // 缺名稱時才去讀全市場索引(搜尋框用的同一份),讀不到就照舊只顯示代號。
  const [indexNames, setIndexNames] = useState<ReadonlyMap<string, string> | null>(null);
  const needsIndex = !!entries?.some((e) => !nameById.get(e.stock_id));
  useEffect(() => {
    if (!needsIndex || indexNames) return;
    let cancelled = false;
    dataFetch("/data/stocks_index.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((rows: unknown) => {
        if (cancelled || !Array.isArray(rows)) return;
        const m = new Map<string, string>();
        for (const row of rows) {
          if (Array.isArray(row) && typeof row[0] === "string" && typeof row[1] === "string") m.set(row[0], row[1]);
        }
        setIndexNames(m);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [needsIndex, indexNames]);
  const names = useMemo(() => {
    if (!indexNames) return nameById;
    const merged = new Map(indexNames);
    nameById.forEach((v, k) => merged.set(k, v));
    return merged;
  }, [nameById, indexNames]);

  const state = futuresAnomalyMarketState(entries, dataDate, names, meta);

  // 缺鍵 = 這一版沒有算過。不可以說成「今天沒有異常」——那是一個沒人做過的主張。
  if (state.kind === "not-computed") {
    return (
      <div className="mx-auto max-w-md py-[46px] text-center text-sm leading-relaxed text-muted-foreground">
        {"尚未計算期貨成交量異常:這一版沒有可用的期貨行情日。這不代表沒有異常。"}
      </div>
    );
  }

  // 日期是**期貨行情日**(§7.12),與本頁資料日不同時另起一句講清楚。
  const lag = anomalyLagText(state.asOf, state.dataDate);
  if (state.kind === "computed-empty") {
    return (
      <div className="mx-auto max-w-md py-[46px] text-center text-sm leading-relaxed text-muted-foreground">
        {anomalyEmptyStateText(state)}
        {lag && (
          <>
            <br />
            {lag}
          </>
        )}
      </div>
    );
  }

  const rows = groupBySpotFollow(state.rows);
  const lagging = rows.filter((r) => r.spot === "lagging").length;

  return (
    <div className="mb-4 grid gap-3">
      {/* 摘要:日期一顆、兩個大數字;回測依據收進可展開(2026-10-02 使用者:重複資訊整併、
          文字能用視覺就用視覺、以手機為主)。頁首說明已經講過「預告的是量」,這裡不再重講。 */}
      <div className="rounded-[var(--r-lg)] border border-[color:var(--accent-2)]/30 bg-[color:var(--accent-2)]/6 px-3 py-2.5">
        <div className="flex min-w-0 items-center gap-2">
          <div className="grid flex-1 grid-cols-2 gap-2">
            <div className="min-w-0">
              <p className="text-[11px] text-muted-foreground">成交量創新高</p>
              <p className="num text-[22px] font-extrabold leading-tight text-foreground">
                {rows.length}
                <span className="ml-1 text-[11px] font-normal text-muted-foreground">個契約</span>
              </p>
            </div>
            <div className="min-w-0">
              <p className="flex items-center gap-1 text-[11px] text-muted-foreground">
                <span className="inline-block size-2 rounded-full bg-[color:var(--accent-2)]" aria-hidden="true" />
                現貨尚未跟上
              </p>
              <p className="num text-[22px] font-extrabold leading-tight text-[color:var(--accent-2)]">
                {lagging}
                <span className="ml-1 text-[11px] font-normal text-muted-foreground">個</span>
              </p>
            </div>
          </div>
          {state.asOf && (
            <span
              className="num shrink-0 self-start rounded-full border border-border bg-card px-2 py-0.5 text-[11px] text-muted-foreground"
              title={lag ?? undefined}
            >
              期貨 {state.asOf.slice(5)}
            </span>
          )}
        </div>
        <details className="group mt-1.5 text-[11.5px] leading-relaxed text-[color:var(--ink-2)]">
          <summary className="flex min-h-8 cursor-pointer list-none items-center gap-1 text-muted-foreground [&::-webkit-details-marker]:hidden">
            <span className="transition-transform group-open:rotate-90" aria-hidden="true">▸</span>
            回測依據
          </summary>
          <p className="pb-1">{anomalyMeaningText()}</p>
          {lag && <p className="text-muted-foreground">{lag}</p>}
        </details>
      </div>

      <div className="grid grid-cols-1 gap-2 pb-4 md:grid-cols-2 xl:grid-cols-3">
        {rows.map((row) => {
          const label = spotFollowLabel(row.spot);
          return (
            <Link
              key={`${row.stockId}-${row.code}`}
              href={`/stock?id=${row.stockId}&tab=futures`}
              className={cn(
                "block min-w-0 rounded-[var(--r-lg)] border border-l-4 bg-card px-3 py-2.5 shadow-[var(--shadow-card)] transition-colors hover:bg-secondary/40",
                // 左邊色條取代一段文字:亮色 = 現貨尚未跟上(檢定成立的那一種)
                row.spot === "lagging"
                  ? "border-[color:var(--accent-2)]/45 border-l-[color:var(--accent-2)]"
                  : "border-border border-l-border",
              )}
            >
              <div className="flex min-w-0 items-center gap-x-2">
                <span className="min-w-0 truncate text-[15px] font-bold text-foreground">
                  <span className="num">{row.stockId}</span>
                  {row.name && <span className="ml-1.5">{row.name}</span>}
                </span>
                <span className="inline-flex shrink-0 items-center gap-0.5 text-[11px] text-muted-foreground">
                  <Layers size={11} aria-hidden="true" />
                  <span className="num">{row.code}</span>
                </span>
                {label && (
                  <span
                    className={cn(
                      "ml-auto shrink-0 rounded-full px-1.5 py-0.5 text-[10.5px] font-bold",
                      row.spot === "lagging"
                        ? "bg-[color:var(--accent-2)] text-white"
                        : "bg-secondary text-muted-foreground",
                    )}
                  >
                    {label}
                  </span>
                )}
              </div>
              {/* 單位一律是口,寫在第一格就好,不每格重複 */}
              <dl className="mt-2 grid grid-cols-4 gap-x-2">
                {row.facts.map((f, i) => (
                  <div key={f.key} className="min-w-0">
                    <dt className="truncate text-[10.5px] text-muted-foreground" title={f.label}>{f.short ?? f.label}</dt>
                    <dd className={cn("num truncate font-bold text-foreground", i === 0 ? "text-[15px]" : "text-[13px]")}>
                      {f.value}
                      {i === 0 && <span className="ml-0.5 text-[10.5px] font-normal text-muted-foreground">{f.unit}</span>}
                    </dd>
                  </div>
                ))}
              </dl>
              {row.risks.length > 0 && (
                <p className="mt-1.5 text-[11px] leading-snug text-muted-foreground">
                  {row.risks.map((r) => r.text).join(" ")}
                </p>
              )}
            </Link>
          );
        })}
      </div>
    </div>
  );
}