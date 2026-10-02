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
      <div className="rounded-[var(--r-lg)] border border-[color:var(--accent-2)]/30 bg-[color:var(--accent-2)]/6 px-3.5 py-3 text-[12.5px] leading-relaxed text-[color:var(--ink-2)]">
        <p className="font-semibold text-foreground">
          {state.asOf ? `期貨 ${state.asOf}:` : ""}
          {`${rows.length} 個契約成交量創新高,其中 ${lagging} 個現貨尚未跟上。`}
        </p>
        <p className="mt-1">{anomalyMeaningText()}</p>
        {lag && <p className="mt-1 text-[11.5px] text-muted-foreground">{lag}</p>}
      </div>

      <div className="grid grid-cols-1 gap-2.5 pb-4 md:grid-cols-2 xl:grid-cols-3">
        {rows.map((row) => {
          const label = spotFollowLabel(row.spot);
          return (
            <div
              key={`${row.stockId}-${row.code}`}
              className={cn(
                "min-w-0 rounded-[var(--r-lg)] border bg-card p-3.5 shadow-[var(--shadow-card)]",
                row.spot === "lagging" ? "border-[color:var(--accent-2)]/55" : "border-border",
              )}
            >
              <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                <Link
                  href={`/stock?id=${row.stockId}&tab=futures`}
                  className="min-w-0 text-[15px] font-bold text-foreground hover:text-[color:var(--accent-2)]"
                >
                  <span className="num">{row.stockId}</span>
                  {row.name && <span className="ml-1.5">{row.name}</span>}
                </Link>
                <span className="inline-flex shrink-0 items-center gap-1 rounded-full border border-border px-1.5 py-0.5 text-[11px] text-muted-foreground">
                  <Layers size={11} aria-hidden="true" />
                  <span className="num">{row.code}</span>
                </span>
                {label && (
                  <span
                    className={cn(
                      "ml-auto shrink-0 rounded-full px-2 py-0.5 text-[11px] font-bold",
                      row.spot === "lagging"
                        ? "bg-[color:var(--accent-2)] text-white"
                        : "bg-secondary text-muted-foreground",
                    )}
                  >
                    {label}
                  </span>
                )}
              </div>
              <dl className="mt-2.5 grid grid-cols-2 gap-x-3 gap-y-1.5 sm:grid-cols-4">
                {row.facts.map((f) => (
                  <div key={f.key} className="min-w-0">
                    <dt className="truncate text-[10.5px] text-muted-foreground" title={f.label}>{f.short ?? f.label}</dt>
                    <dd className="num text-[13.5px] font-bold text-foreground">
                      {f.value}
                      <span className="ml-0.5 text-[11px] font-normal text-muted-foreground">{f.unit}</span>
                    </dd>
                  </div>
                ))}
              </dl>
              {row.risks.length > 0 && (
                <p className="mt-2 text-[11px] leading-snug text-muted-foreground">
                  {row.risks.map((r) => r.text).join(" ")}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
