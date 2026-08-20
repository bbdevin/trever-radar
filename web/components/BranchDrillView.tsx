"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft } from "lucide-react";
import KChart from "@/components/KChart";
import type { Candle, StockJson } from "@/lib/types";
import { fmtLots } from "@/lib/format";
import { cn, pillTabClass } from "@/lib/utils";

const RANGES = [
  { key: "1m", label: "1月", days: 22 },
  { key: "3m", label: "3月", days: 66 },
  { key: "1y", label: "1年", days: 240 },
  { key: "all", label: "全部", days: Infinity },
] as const;

type BranchHistory = NonNullable<StockJson["branch_history"]>;

/** 單一分點在此股的每日進出 + 對應 K 線。全螢幕覆層,呼叫端須套 `.safe-overlay`。 */
export default function BranchDrillView({
  stockName,
  stockId,
  branchName,
  candles,
  branchHistory,
  onBack,
}: {
  stockName: string;
  stockId: string;
  branchName: string;
  candles: Candle[];
  branchHistory?: BranchHistory;
  onBack: () => void;
}) {
  const [range, setRange] = useState<(typeof RANGES)[number]["key"]>("1y");
  const onBackRef = useRef(onBack);
  onBackRef.current = onBack;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onBackRef.current();
    };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, []);

  const visibleDays = useMemo(() => {
    const days = RANGES.find((r) => r.key === range)?.days ?? Infinity;
    return days === Infinity ? Number.MAX_SAFE_INTEGER : days;
  }, [range]);

  const daily = useMemo(() => {
    if (!branchHistory?.length) return [];
    const rows: { t: string; buy: number; sell: number; net: number }[] = [];
    for (const d of branchHistory) {
      const b = d.branches.find((x) => x.n === branchName);
      if (!b) continue;
      rows.push({ t: d.t, buy: b.b, sell: b.s, net: b.net });
    }
    return rows;
  }, [branchHistory, branchName]);

  const branchFlow = useMemo(() => {
    if (!daily.length) return undefined;
    return [...daily]
      .map((r) => ({ t: r.t, net: r.net }))
      .sort((a, b) => (a.t < b.t ? -1 : 1));
  }, [daily]);

  const totals = useMemo(() => {
    let buy = 0;
    let sell = 0;
    let net = 0;
    for (const r of daily) {
      buy += r.buy;
      sell += r.sell;
      net += r.net;
    }
    return { buy, sell, net, days: daily.length };
  }, [daily]);

  return (
    <div className="flex min-h-0 flex-col gap-3">
      <div className="flex min-w-0 items-center gap-2">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-full border border-border bg-card px-3 text-[13.5px] font-semibold text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="返回籌碼日報"
        >
          <ArrowLeft size={16} />
          返回
        </button>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[16px] font-extrabold" title={branchName}>
            {branchName}
          </div>
          <div className="truncate text-[12px] text-muted-foreground">
            {stockName} {stockId} · 進出明細
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <div className="flex flex-col gap-0.5 rounded-[var(--r-sm)] border border-border bg-card p-2.5">
          <span className="text-[11px] text-muted-foreground">累計淨張</span>
          <span className={cn("num text-base font-bold", totals.net > 0 ? "text-up" : totals.net < 0 ? "text-down" : "text-foreground")}>
            {fmtLots(totals.net)}
          </span>
        </div>
        <div className="flex flex-col gap-0.5 rounded-[var(--r-sm)] border border-border bg-card p-2.5">
          <span className="text-[11px] text-muted-foreground">買張合計</span>
          <span className="num text-base font-bold text-up">{fmtLots(totals.buy)}</span>
        </div>
        <div className="flex flex-col gap-0.5 rounded-[var(--r-sm)] border border-border bg-card p-2.5">
          <span className="text-[11px] text-muted-foreground">賣張合計</span>
          <span className="num text-base font-bold text-down">{fmtLots(-totals.sell)}</span>
        </div>
        <div className="flex flex-col gap-0.5 rounded-[var(--r-sm)] border border-border bg-card p-2.5">
          <span className="text-[11px] text-muted-foreground">上榜日數</span>
          <span className="num text-base font-bold text-foreground">{totals.days}</span>
        </div>
      </div>

      <div
        role="tablist"
        className="flex max-w-full gap-0.5 overflow-x-auto rounded-full border border-border bg-card p-[3px] scrollbar-hide [scrollbar-width:none] max-md:flex-nowrap max-md:[&>*]:shrink-0 [&::-webkit-scrollbar]:hidden"
      >
        {RANGES.map((r) => (
          <button
            key={r.key}
            type="button"
            role="tab"
            aria-selected={range === r.key}
            className={pillTabClass(range === r.key)}
            onClick={() => setRange(r.key)}
          >
            {r.label}
          </button>
        ))}
      </div>

      {candles.length > 0 ? (
        <KChart
          candles={candles}
          visibleDays={visibleDays}
          branchFlow={branchFlow}
          branchFlowLabel={`分點進出(${branchName})`}
        />
      ) : (
        <p className="py-8 text-center text-sm text-muted-foreground">尚無 K 線資料。</p>
      )}

      <div className="overflow-x-auto rounded-[var(--r-lg)] border border-border bg-card shadow-[var(--shadow-card)]">
        {daily.length === 0 ? (
          <p className="px-3.5 py-[46px] text-center text-sm text-muted-foreground">
            此分點在已抓到的前 15 大買賣超裡沒有進出紀錄。免費資料為裁剪版,冷門進出不可見。
          </p>
        ) : (
          <table className="w-full border-collapse text-[13px]">
            <caption className="sr-only">{branchName} 在 {stockName} 的每日進出</caption>
            <thead>
              <tr>
                <th className="px-3.5 py-2.5 text-left font-semibold text-muted-foreground">日期</th>
                <th className="px-3.5 py-2.5 text-right font-semibold text-muted-foreground whitespace-nowrap">買張</th>
                <th className="px-3.5 py-2.5 text-right font-semibold text-muted-foreground whitespace-nowrap">賣張</th>
                <th className="px-3.5 py-2.5 text-right font-semibold text-muted-foreground whitespace-nowrap">淨張</th>
              </tr>
            </thead>
            <tbody>
              {daily.map((r) => (
                <tr key={r.t} className="num border-t border-[color:var(--line)]">
                  <td className="px-3.5 py-2.5 text-left font-sans text-foreground">{r.t}</td>
                  <td className="px-3.5 py-2.5 text-right text-up">{r.buy ? fmtLots(r.buy) : "—"}</td>
                  <td className="px-3.5 py-2.5 text-right text-down">{r.sell ? fmtLots(-r.sell) : "—"}</td>
                  <td className={cn("px-3.5 py-2.5 text-right font-bold", r.net > 0 ? "text-up" : r.net < 0 ? "text-down" : "text-[color:var(--ink-2)]")}>
                    {fmtLots(r.net)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <p className="text-[11.5px] leading-relaxed text-muted-foreground">
        僅列出該分點有進入當日前 15 大買/賣超的交易日,不是全量委託明細。盤後 T+1,僅供籌碼觀察。
      </p>
    </div>
  );
}
