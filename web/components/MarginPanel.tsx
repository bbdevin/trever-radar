"use client";

import { useMemo, useState } from "react";
import type { Candle, MarginHistoryPoint, MarginMeta, StockJson } from "@/lib/types";
import { fmtLots, fmtLotsPlain } from "@/lib/format";
import { cn, pillTabClass } from "@/lib/utils";

const TABLE_PREVIEW = 20;

function fmtMD(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return iso;
  return `${m[2]}/${m[3]}`;
}

function fmtYMD(iso: string | undefined): string {
  if (!iso) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return iso;
  return `${m[1]}/${m[2]}/${m[3]}`;
}

function fmtUsage(u: number | null | undefined): string {
  if (u == null) return "—";
  return `${(u * 100).toFixed(1)}%`;
}

export default function MarginPanel({ data, candles }: { data: StockJson; candles: Candle[] }) {
  const [mode, setMode] = useState<"margin" | "short">("margin");
  const [view, setView] = useState<"balance" | "usage">("balance");
  const [showCost, setShowCost] = useState(true);
  const [showAll, setShowAll] = useState(false);

  const history = data.margin_history ?? [];
  const meta: MarginMeta | undefined = data.margin_meta;
  const latest = history[0];

  const chartRows = useMemo(() => {
    const slice = history.slice().reverse();
    const closeByT = new Map(candles.map((c) => [c.t, c.c]));
    return slice.map((r) => ({ ...r, close: closeByT.get(r.t) ?? null }));
  }, [history, candles]);

  const maxAbsChg = Math.max(1, ...chartRows.map((r) => Math.abs(r.chg ?? 0)));
  const maxBal = Math.max(
    1,
    ...chartRows.map((r) => (mode === "margin" ? r.balance ?? 0 : r.short_balance ?? 0)),
  );
  const usages = chartRows.map((r) => r.usage).filter((u): u is number => u != null);
  const maxUsage = Math.max(0.01, ...usages, 0.01);
  const minUsage = usages.length ? Math.min(...usages) : 0;

  const tableRows = showAll ? history : history.slice(0, TABLE_PREVIEW);

  const usage = latest?.usage ?? null;
  const hot = usage != null && usage >= 0.6;

  const windowNote =
    meta?.display_from && meta?.display_to
      ? `顯示 ${fmtYMD(meta.display_from)}–${fmtYMD(meta.display_to)}（${meta.window_label ?? "當年度"}）`
      : history.length > 0
        ? `近 ${history.length} 日`
        : null;

  return (
    <div className="grid min-w-0 gap-3">
      {windowNote && (
        <p className="text-[12px] text-muted-foreground">{windowNote}</p>
      )}

      <div className="flex min-w-0 flex-wrap items-center gap-2 rounded-[var(--r-md)] border border-border bg-card px-3 py-2.5 text-[12px]">
        <span className="text-muted-foreground">資券</span>
        {latest && (
          <>
            <span>
              融資餘額{" "}
              <span className="num font-semibold text-foreground">{fmtLotsPlain(latest.balance)}</span> 張
            </span>
            <span>
              增減{" "}
              <span className={cn("num font-semibold", (latest.chg ?? 0) >= 0 ? "text-up" : "text-down")}>
                {fmtLots(latest.chg)}
              </span>
            </span>
            <span>
              使用率{" "}
              <span className={cn("num font-semibold", hot && "text-[color:var(--warn)]")}>
                {fmtUsage(usage)}
              </span>
            </span>
            {latest.cost_est != null && (
              <span>
                融資成本{" "}
                <span className="num font-semibold text-foreground">
                  {latest.cost_est.toLocaleString("zh-TW")}
                </span>
                <span className="text-muted-foreground">（估算）</span>
              </span>
            )}
          </>
        )}
        <a
          href="/?tab=margin"
          className="ml-auto text-[12px] font-semibold text-primary hover:underline"
        >
          使用率排行 →
        </a>
      </div>

      <p className="text-[11px] leading-relaxed text-muted-foreground">
        <span className="font-medium text-foreground/90">融資使用率</span>
        {" = 融資餘額 ÷ 融資限額（限額為交易所公布該股最多可融資張數，各股不同）。"}
        {" ≥60% 視為過熱風險觀察。"}
        {" 融資成本為系統依官方買進與收盤價遞推之估算值，非證交所公布、亦非個人實際成本。"}
      </p>

      <div className="flex flex-wrap gap-2">
        <div
          role="tablist"
          aria-label="資券類型"
          className="flex gap-0.5 rounded-full border border-border bg-card p-[3px]"
        >
          {(
            [
              { key: "margin" as const, label: "融資" },
              { key: "short" as const, label: "融券" },
            ] as const
          ).map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={mode === t.key}
              className={cn("min-h-11 cursor-pointer", pillTabClass(mode === t.key))}
              onClick={() => setMode(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>
        {mode === "margin" && (
          <>
            <div
              role="tablist"
              aria-label="圖表檢視"
              className="flex gap-0.5 rounded-full border border-border bg-card p-[3px]"
            >
              {(
                [
                  { key: "balance" as const, label: "餘額" },
                  { key: "usage" as const, label: "使用率" },
                ] as const
              ).map((t) => (
                <button
                  key={t.key}
                  type="button"
                  role="tab"
                  aria-selected={view === t.key}
                  className={cn("min-h-11 cursor-pointer", pillTabClass(view === t.key))}
                  onClick={() => setView(t.key)}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <button
              type="button"
              className={cn(
                "min-h-11 cursor-pointer rounded-full border px-3 py-1 text-[12px] font-semibold transition-colors duration-200",
                showCost
                  ? "border-primary/40 bg-primary/10 text-primary"
                  : "border-border text-muted-foreground hover:bg-secondary",
              )}
              onClick={() => setShowCost((v) => !v)}
            >
              融資成本線
            </button>
          </>
        )}
      </div>

      {chartRows.length === 0 ? (
        <div className="rounded-[var(--r-md)] border border-border bg-card px-4 py-8 text-center text-sm text-muted-foreground">
          窗內尚無資券歷史
          {meta?.db_earliest ? `（資料自 ${fmtYMD(meta.db_earliest)} 起）` : ""}
        </div>
      ) : (
        <div className="rounded-[var(--r-lg)] border border-border bg-card p-3 shadow-[var(--shadow-card)]">
          <div className="mb-2 text-[12px] font-semibold text-muted-foreground">
            {chartRows.length} 日 · 柱=增減 · 線=
            {mode === "margin" ? (view === "usage" ? "使用率" : "餘額") : "融券餘額"}
            {mode === "margin" && showCost ? " · 灰=成本(估)" : ""}
          </div>
          <div className="relative h-[200px] w-full">
            <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="h-full w-full">
              {chartRows.map((r, i) => {
                const chg = r.chg ?? 0;
                const h = (Math.abs(chg) / maxAbsChg) * 35;
                const x = (i / Math.max(chartRows.length, 1)) * 100;
                const w = (100 / Math.max(chartRows.length, 1)) * 0.7;
                const y = chg >= 0 ? 50 - h : 50;
                return (
                  <rect
                    key={r.t}
                    x={x}
                    y={y}
                    width={w}
                    height={h || 0.5}
                    fill={chg >= 0 ? "var(--up)" : "var(--down)"}
                    opacity={0.55}
                  />
                );
              })}
              {mode === "margin" && showCost && view === "balance" && (
                <polyline
                  fill="none"
                  stroke="var(--ink-2)"
                  strokeWidth="0.6"
                  strokeDasharray="2 1"
                  points={chartRows
                    .map((r, i) => {
                      if (r.cost_est == null) return null;
                      const costs = chartRows.map((x) => x.cost_est).filter((c): c is number => c != null);
                      const minC = Math.min(...costs);
                      const maxC = Math.max(...costs);
                      const x = ((i + 0.5) / Math.max(chartRows.length, 1)) * 100;
                      const y = maxC === minC ? 20 : 10 + (1 - (r.cost_est - minC) / (maxC - minC)) * 25;
                      return `${x},${y}`;
                    })
                    .filter(Boolean)
                    .join(" ")}
                />
              )}
              <polyline
                fill="none"
                stroke="var(--primary)"
                strokeWidth="0.8"
                points={chartRows
                  .map((r, i) => {
                    const x = ((i + 0.5) / Math.max(chartRows.length, 1)) * 100;
                    let y: number;
                    if (mode === "margin" && view === "usage") {
                      const u = r.usage ?? minUsage;
                      y = 88 - ((u - minUsage) / (maxUsage - minUsage || 1)) * 38;
                    } else {
                      const bal = mode === "margin" ? r.balance ?? 0 : r.short_balance ?? 0;
                      y = 88 - (bal / maxBal) * 38;
                    }
                    return `${x},${y}`;
                  })
                  .join(" ")}
              />
            </svg>
          </div>
        </div>
      )}

      <div className="overflow-x-auto rounded-[var(--r-md)] border border-border">
        <table className="w-full min-w-[520px] text-left text-[12px]">
          <thead className="border-b border-border bg-secondary/40 text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-semibold">日期</th>
              <th className="px-3 py-2 font-semibold">餘額</th>
              <th className="px-3 py-2 font-semibold">增減</th>
              {mode === "margin" && (
                <>
                  <th className="px-3 py-2 font-semibold">限額</th>
                  <th className="px-3 py-2 font-semibold">使用率</th>
                  <th className="px-3 py-2 font-semibold">成本(估)</th>
                </>
              )}
            </tr>
          </thead>
          <tbody>
            {tableRows.map((r: MarginHistoryPoint) => {
              const bal = mode === "margin" ? r.balance : r.short_balance;
              const chg =
                mode === "margin"
                  ? r.chg
                  : r.short_balance != null && r.short_prev != null
                    ? r.short_balance - r.short_prev
                    : null;
              return (
                <tr key={r.t} className="border-b border-border/60 last:border-0">
                  <td className="num px-3 py-2">{fmtMD(r.t)}</td>
                  <td className="num px-3 py-2">{fmtLotsPlain(bal)}</td>
                  <td className={cn("num px-3 py-2", (chg ?? 0) > 0 ? "text-up" : (chg ?? 0) < 0 ? "text-down" : "")}>
                    {chg == null ? "—" : fmtLots(chg)}
                  </td>
                  {mode === "margin" && (
                    <>
                      <td className="num px-3 py-2 text-muted-foreground">{fmtLotsPlain(r.limit)}</td>
                      <td className="num px-3 py-2">{fmtUsage(r.usage)}</td>
                      <td className="num px-3 py-2">{r.cost_est?.toLocaleString("zh-TW") ?? "—"}</td>
                    </>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {history.length > TABLE_PREVIEW && (
        <button
          type="button"
          className="cursor-pointer text-[12px] font-semibold text-primary hover:underline"
          onClick={() => setShowAll((v) => !v)}
        >
          {showAll ? "收合" : `顯示窗內全部 ${history.length} 日`}
        </button>
      )}
    </div>
  );
}
