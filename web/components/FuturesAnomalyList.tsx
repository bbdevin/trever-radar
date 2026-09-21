"use client";

import Link from "next/link";
import { Layers } from "lucide-react";
import ReasonPill from "@/components/ReasonPill";
import { anomalyEmptyStateText, futuresAnomalyMarketState } from "@/lib/futures";
import type { FuturesVolumeAnomalyEntry, FuturesVolumeAnomalyMeta } from "@/lib/types";

/**
 * 首頁「期貨異常」分頁的名單(docs/38 §7.5)。
 *
 * 這個元件本身**不做任何判斷**:三態、事實列、順序、去重與否全部在
 * `lib/futures.ts` 的純函式裡,由 `lib/futures.test.ts` 鎖住。這裡只負責排版。
 * 兩件事寫在這裡是因為它們是排版決定:
 *   - 名單**不編號**。加一個序號等於在畫面上造出一個 §5 不做的跨契約名次,
 *     即使 payload 沒有 rank 鍵也一樣。
 *   - 單位是**契約**,所以同一檔股票可能連著出現兩列(1565 的 MYF/OMF),
 *     那是正確的,不要看到重複的股名就想合併。
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
  const state = futuresAnomalyMarketState(entries, dataDate, nameById, meta);

  // 缺鍵 = 今天沒有算過。不可以說成「今天沒有異常」——那是一個沒人做過的主張。
  if (state.kind === "not-computed") {
    return (
      <div className="mx-auto max-w-md py-[46px] text-center text-sm leading-relaxed text-muted-foreground">
        {"今日尚未計算期貨成交量異常。"}
        <br />
        {"期貨資料每日 21:20 匯入,這一版的期貨還停在前一個交易日;這不代表今天沒有異常。"}
      </div>
    );
  }

  // 空陣列 = 算過了,而且今天真的沒有契約舉旗。這是一個帶日期的正面主張,要說出日期。
  // 比較窗口的長度從 payload 的 `_meta` 讀(§7.11);讀不到就少講那一段,**不寫死 60**
  // (§7.10)——一個寫死的 60 會在 v2 改數字的那天變成第二個真相。
  if (state.kind === "computed-empty") {
    return (
      <div className="mx-auto max-w-md py-[46px] text-center text-sm leading-relaxed text-muted-foreground">
        {anomalyEmptyStateText(state)}
      </div>
    );
  }

  return (
    <div className="mb-4">
      <p className="mb-2 text-[12px] text-muted-foreground">
        {`${state.dataDate} 共 ${state.rows.length} 個契約舉旗。單位是契約不是股票——同一檔股票的兩個契約(例如 2,000 股標準型與 100 股小型)可以同一天都在名單上。`}
      </p>
      <div className="grid grid-cols-1 gap-2.5 pb-4 md:grid-cols-2 xl:grid-cols-3">
        {state.rows.map((row) => (
          <div
            key={`${row.stockId}-${row.code}`}
            className="min-w-0 rounded-[var(--r-lg)] border border-border bg-card p-3.5 shadow-[var(--shadow-card)]"
          >
            <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
              <Link
                href={`/stock?id=${row.stockId}`}
                className="min-w-0 text-[15px] font-bold text-foreground hover:text-[color:var(--accent-2)]"
              >
                <span className="num">{row.stockId}</span>
                {row.name && <span className="ml-1.5">{row.name}</span>}
              </Link>
              <span className="inline-flex shrink-0 items-center gap-1 rounded-full border border-[color:var(--accent-2)]/35 bg-[color:var(--accent-2)]/8 px-1.5 py-0.5 text-[11px] font-semibold text-[color:var(--accent-2)]">
                <Layers size={11} aria-hidden="true" />
                <span className="num">{row.code}</span>
              </span>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-1.5">
              {row.facts.map((f) => (
                <span
                  key={f.key}
                  className="flex items-baseline justify-between gap-2 rounded-[var(--r-sm)] border border-border bg-secondary px-2.5 py-1.5 text-[11.5px] text-muted-foreground"
                >
                  {f.label}
                  <b className="num shrink-0 font-bold text-[color:var(--ink-2)]">
                    {f.value}
                    <span className="ml-0.5 font-normal">{f.unit}</span>
                  </b>
                </span>
              ))}
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {row.reasons.map((r, i) => (
                <ReasonPill key={`reason-${i}`} code={r.code} text={r.text} />
              ))}
              {row.risks.map((r, i) => (
                <ReasonPill key={`risk-${i}`} code={r.code} text={r.text} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
