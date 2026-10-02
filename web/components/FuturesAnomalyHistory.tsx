"use client";

import Link from "next/link";
import {
  PRICE_AFTER_HEADING,
  anomalyHistoryHeaderText,
  futuresAnomalyHistoryState,
  nextDayEvidenceText,
  priceAfterCounts,
  priceAfterCountsText,
} from "@/lib/futures";
import { useStockNames } from "@/lib/useStockNames";
import WatchlistButton from "@/components/WatchlistButton";
import { ContractTag, SpotChip, flagCardClass } from "@/components/FuturesFlagParts";
import { cn } from "@/lib/utils";
import type { FuturesAnomalyHistoryDay, FuturesAnomalyHistoryMeta } from "@/lib/types";

/**
 * 首頁「期貨異常」分頁的「近 N 日」:舉旗紀錄(docs/38 §7.19)。
 *
 * 依舉旗日分組(新到舊),組內照 payload 順序;每一筆一張精簡卡:股名/代號、
 * 契約白話名稱、舉旗當天現貨有沒有同步爆量(與當日名單同一套顏色)、之後現貨量
 * 有沒有跟上、之後的現貨價格(中性色,事後紀錄)。**不依價格排序、不給命中徽章**:
 * 價格是波動,不是這個訊號驗證過的東西。判斷全部在 `lib/futures.ts`。
 */
export default function FuturesAnomalyHistory({
  history,
  meta,
  nameById,
}: {
  history: FuturesAnomalyHistoryDay[] | undefined;
  meta: FuturesAnomalyHistoryMeta | undefined;
  nameById: ReadonlyMap<string, string>;
}) {
  const ids = (history ?? []).flatMap((d) => (d.entries ?? []).map((e) => e.stock_id));
  const names = useStockNames(nameById, ids);
  const state = futuresAnomalyHistoryState(history, meta, names);

  if (state.kind === "not-computed") {
    return (
      <div className="mx-auto max-w-md py-[46px] text-center text-sm leading-relaxed text-muted-foreground">
        {"這一版沒有舉旗紀錄可看。這不代表之前沒有舉旗。"}
      </div>
    );
  }

  const total = state.days.reduce((n, d) => n + d.rows.length, 0);
  const counts = priceAfterCounts(history ?? []);

  return (
    <div className="mb-4 grid gap-3">
      <div className="rounded-[var(--r-lg)] border border-border bg-card px-3 py-2.5 shadow-[var(--shadow-card)]">
        <p className="text-[12.5px] font-semibold text-foreground">
          近 <span className="num">{state.days.length}</span> 個期貨交易日舉旗{" "}
          <span className="num">{total}</span> 次
        </p>
        <p className="mt-1.5 text-[11px] font-semibold text-muted-foreground">{PRICE_AFTER_HEADING}</p>
        <p className="mt-0.5 text-[11.5px] leading-relaxed text-[color:var(--ink-2)]">
          {priceAfterCountsText(counts)}
        </p>
        <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">{nextDayEvidenceText()}</p>
        <details className="group mt-1 text-[11.5px] leading-relaxed text-[color:var(--ink-2)]">
          <summary className="flex min-h-8 cursor-pointer list-none items-center gap-1 text-muted-foreground [&::-webkit-details-marker]:hidden">
            <span className="transition-transform group-open:rotate-90" aria-hidden="true">▸</span>
            怎麼看
          </summary>
          <p className="pb-1">{anomalyHistoryHeaderText(state.meta, history ?? [])}</p>
        </details>
      </div>

      {state.days.map((day) => (
        <section key={day.asOf} aria-label={`期貨 ${day.asOf} 的舉旗`} className="grid gap-1.5">
          <h3 className="flex items-baseline gap-2 px-0.5 text-[12.5px] font-bold text-foreground">
            <span className="num">{day.asOf}</span>
            <span className="text-[11px] font-normal text-muted-foreground">
              {!day.computed
                ? "這一天沒有算出結果"
                : day.rows.length === 0
                  ? "沒有契約舉旗"
                  : `${day.rows.length} 個契約`}
            </span>
          </h3>
          {day.rows.length > 0 && (
            <div className="grid grid-cols-1 gap-1.5 md:grid-cols-2 xl:grid-cols-3">
              {day.rows.map((row) => (
                <Link
                  key={`${day.asOf}-${row.code}`}
                  href={`/stock?id=${row.stockId}&tab=futures`}
                  className={cn(flagCardClass(row.spot), "py-2")}
                >
                  {/* flex-wrap:契約名稱長時換行,不擠掉股名(同當日名單)。 */}
                  <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="min-w-0 max-w-full truncate text-[14px] font-bold text-foreground">
                      <span className="num">{row.stockId}</span>
                      {row.name && <span className="ml-1.5">{row.name}</span>}
                    </span>
                    <ContractTag label={row.label} code={row.code} />
                    <span className="ml-auto flex shrink-0 items-center gap-1.5">
                      <SpotChip spot={row.spot} when="flag" />
                      <WatchlistButton stockId={row.stockId} size={15} />
                    </span>
                  </div>
                  <p className="mt-1 text-[12px] font-semibold text-foreground">{row.followLabel}</p>
                  <p className="num mt-0.5 text-[11.5px] leading-snug text-[color:var(--ink-2)]">{row.priceAfter}</p>
                </Link>
              ))}
            </div>
          )}
        </section>
      ))}
    </div>
  );
}
