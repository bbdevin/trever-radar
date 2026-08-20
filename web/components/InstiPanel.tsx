"use client";

import { useMemo, useState } from "react";
import type { Candle, StockJson } from "@/lib/types";
import { fmtLots } from "@/lib/format";
import { cn, pillTabClass } from "@/lib/utils";
import ReasonPill from "@/components/ReasonPill";

type SeriesKey = "foreign" | "trust" | "dealer" | "total";

const SERIES: { key: SeriesKey; label: string }[] = [
  { key: "foreign", label: "外資" },
  { key: "trust", label: "投信" },
  { key: "dealer", label: "自營" },
  { key: "total", label: "三大法人" },
];

const CHART_DAYS = 60;
const TABLE_PREVIEW = 20;

export default function InstiPanel({ data, candles }: { data: StockJson; candles: Candle[] }) {
  const [series, setSeries] = useState<SeriesKey>("foreign");
  const [showAll, setShowAll] = useState(false);

  const instiReasons = useMemo(
    () =>
      (data.raw_reasons ?? []).filter((r) => {
        const c = r.code ?? "";
        return c.startsWith("I") || c === "S11_INSTI_BREAKOUT";
      }),
    [data],
  );

  const history = data.insti_history ?? [];
  const latest = history[0];
  const chartRows = useMemo(() => {
    const slice = history.slice(0, CHART_DAYS).slice().reverse();
    const closeByT = new Map(candles.map((c) => [c.t, c.c]));
    return slice.map((r) => ({ ...r, close: closeByT.get(r.t) ?? null }));
  }, [history, candles]);

  const maxAbs = Math.max(1, ...chartRows.map((r) => Math.abs(r[series])));
  const closes = chartRows.map((r) => r.close).filter((c): c is number => c != null);
  const minC = closes.length ? Math.min(...closes) : 0;
  const maxC = closes.length ? Math.max(...closes) : 1;
  const priceY = (c: number) => {
    if (maxC === minC) return 50;
    return 8 + (1 - (c - minC) / (maxC - minC)) * 84;
  };
  const pricePath = chartRows
    .map((r, i) => {
      if (r.close == null) return null;
      const x = ((i + 0.5) / Math.max(chartRows.length, 1)) * 100;
      return `${x},${priceY(r.close)}`;
    })
    .filter(Boolean)
    .join(" ");

  const tableRows = showAll ? history : history.slice(0, TABLE_PREVIEW);
  const instScore = data.scores?.inst ?? null;

  return (
    <div className="grid min-w-0 gap-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <div className="flex flex-col gap-0.5 rounded-[var(--r-sm)] border border-border bg-card p-2.5">
          <span className="text-[11px] text-muted-foreground">法人分</span>
          <span className="num text-[28px] leading-none font-extrabold text-[color:var(--accent-2)]">
            {instScore ?? "—"}
          </span>
        </div>
        {SERIES.map((s) => (
          <div key={s.key} className="flex flex-col gap-0.5 rounded-[var(--r-sm)] border border-border bg-card p-2.5">
            <span className="text-[11px] text-muted-foreground">{s.label}淨張</span>
            <span
              className={cn(
                "num text-base font-bold",
                latest && latest[s.key] > 0 ? "text-up" : latest && latest[s.key] < 0 ? "text-down" : "text-foreground",
              )}
            >
              {latest ? fmtLots(latest[s.key]) : "—"}
            </span>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap gap-1.5">
        {instiReasons.length > 0 ? (
          instiReasons.map((r) => <ReasonPill key={r.code} code={r.code} text={r.text} />)
        ) : (
          <span className="rounded-full border border-[color:var(--line)] px-2 py-[3px] text-[11.5px] text-[color:var(--ink-2)]">
            今日未觸發法人加分條件
          </span>
        )}
      </div>

      {!history.length ? (
        <p className="rounded-[var(--r-md)] border border-border bg-card px-3.5 py-6 text-center text-sm text-muted-foreground">
          近 240 日外資/投信/自營明細會在下次資料匯出後出現。法人分與理由仍可先看。
        </p>
      ) : (
        <>
          <div
            role="tablist"
            className="flex max-w-full gap-0.5 overflow-x-auto rounded-full border border-border bg-card p-[3px] scrollbar-hide"
          >
            {SERIES.map((s) => (
              <button
                key={s.key}
                type="button"
                role="tab"
                aria-selected={series === s.key}
                className={pillTabClass(series === s.key)}
                onClick={() => setSeries(s.key)}
              >
                {s.label}
              </button>
            ))}
          </div>

          <div className="relative h-[140px] overflow-hidden rounded-[var(--r-lg)] border border-border bg-card px-1 pt-2 pb-1">
            <div className="flex h-full items-stretch gap-px">
              {chartRows.map((r) => {
                const v = r[series];
                const h = Math.max(v !== 0 ? 4 : 0, Math.round((Math.abs(v) / maxAbs) * 58));
                return (
                  <div key={r.t} className="flex min-w-0 flex-1 flex-col" title={`${r.t} ${SERIES.find((s) => s.key === series)?.label} ${fmtLots(v)}張`}>
                    <div className="flex h-1/2 flex-col justify-end">
                      {v > 0 ? <div className="w-full rounded-sm bg-up/80" style={{ height: h }} /> : null}
                    </div>
                    <div className="flex h-1/2 flex-col justify-start">
                      {v < 0 ? <div className="w-full rounded-sm bg-down/80" style={{ height: h }} /> : null}
                    </div>
                  </div>
                );
              })}
            </div>
            {pricePath && (
              <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden>
                <polyline fill="none" stroke="currentColor" strokeWidth="1.2" className="text-foreground/70" points={pricePath} vectorEffect="non-scaling-stroke" />
              </svg>
            )}
          </div>
          <p className="text-[11px] text-muted-foreground">近 {chartRows.length} 日{SERIES.find((s) => s.key === series)?.label}買賣超（張）· 白線為收盤價</p>

          <div className="overflow-x-auto rounded-[var(--r-lg)] border border-border bg-card shadow-[var(--shadow-card)]">
            <table className="w-full border-collapse text-[13px]">
              <thead>
                <tr>
                  <th className="px-3 py-2.5 text-left font-semibold text-muted-foreground">日期</th>
                  <th className="px-3 py-2.5 text-right font-semibold text-muted-foreground whitespace-nowrap">外資</th>
                  <th className="px-3 py-2.5 text-right font-semibold text-muted-foreground whitespace-nowrap">投信</th>
                  <th className="px-3 py-2.5 text-right font-semibold text-muted-foreground whitespace-nowrap">自營</th>
                  <th className="px-3 py-2.5 text-right font-semibold text-muted-foreground whitespace-nowrap">合計</th>
                </tr>
              </thead>
              <tbody>
                {tableRows.map((r) => (
                  <tr key={r.t} className="num border-t border-[color:var(--line)]">
                    <td className="px-3 py-2 font-sans text-foreground">{r.t.slice(5)}</td>
                    <Cell n={r.foreign} />
                    <Cell n={r.trust} />
                    <Cell n={r.dealer} />
                    <Cell n={r.total} bold />
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {history.length > TABLE_PREVIEW && (
            <button
              type="button"
              className="min-h-11 rounded-[var(--r-sm)] border border-[color:var(--line)] text-[12.5px] font-semibold text-[color:var(--ink-2)] hover:bg-card"
              onClick={() => setShowAll((v) => !v)}
              aria-expanded={showAll}
            >
              {showAll ? "收合" : `展開全部 ${history.length} 日`}
            </button>
          )}
          <p className="text-[11.5px] leading-relaxed text-muted-foreground">
            單位張。T+1 盤後官方三大法人，與分點裁剪資料不同源。白線僅對齊收盤價方便對照，不是建議。
          </p>
        </>
      )}
    </div>
  );
}

function Cell({ n, bold }: { n: number; bold?: boolean }) {
  return (
    <td
      className={cn(
        "px-3 py-2 text-right whitespace-nowrap",
        bold && "font-bold",
        n > 0 ? "text-up" : n < 0 ? "text-down" : "text-[color:var(--ink-2)]",
      )}
    >
      {fmtLots(n)}
    </td>
  );
}
