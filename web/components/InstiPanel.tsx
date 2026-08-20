"use client";

import { useMemo, useState } from "react";
import type { Candle, StockJson } from "@/lib/types";
import { fmtLots } from "@/lib/format";
import { cn } from "@/lib/utils";
import ReasonPill from "@/components/ReasonPill";

type SeriesKey = "foreign" | "trust" | "dealer" | "total";

/** 比照券商 App「法人」：外資 / 投信 / 自營商 / 三大法人 */
const SERIES: { key: SeriesKey; label: string; short: string }[] = [
  { key: "foreign", label: "外資", short: "外資" },
  { key: "trust", label: "投信", short: "投信" },
  { key: "dealer", label: "自營商", short: "自營" },
  { key: "total", label: "三大法人", short: "合計" },
];

const CHART_DAYS = 60;
const TABLE_PREVIEW = 20;

function fmtMD(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return iso;
  return `${m[2]}/${m[3]}`;
}

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
    return 10 + (1 - (c - minC) / (maxC - minC)) * 80;
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
  const seriesLabel = SERIES.find((s) => s.key === series)?.label ?? "";

  // 圖表左右軸刻度（顯示用）
  const leftTicks = [maxAbs, Math.round(maxAbs / 2), 0, -Math.round(maxAbs / 2), -maxAbs];
  const rightTicks =
    closes.length > 0
      ? [maxC, (maxC + minC) / 2, minC].map((n) => Math.round(n * 100) / 100)
      : [];

  return (
    <div className="grid min-w-0 gap-3">
      {/* 一行摘要：法人分 + 當日四欄淨張，不搶圖表注意力 */}
      <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1 rounded-[var(--r-md)] border border-border bg-card px-3 py-2.5 text-[12px]">
        <span className="text-muted-foreground">
          法人分{" "}
          <b className="num text-[18px] font-extrabold text-[color:var(--accent-2)]">{instScore ?? "—"}</b>
        </span>
        {SERIES.map((s) => (
          <span key={s.key} className="text-muted-foreground">
            {s.short}{" "}
            <b
              className={cn(
                "num font-bold",
                latest && latest[s.key] > 0 ? "text-up" : latest && latest[s.key] < 0 ? "text-down" : "text-foreground",
              )}
            >
              {latest ? fmtLots(latest[s.key]) : "—"}
            </b>
          </span>
        ))}
      </div>

      {instiReasons.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {instiReasons.map((r) => (
            <ReasonPill key={r.code} code={r.code} text={r.text} />
          ))}
        </div>
      )}

      {!history.length ? (
        <p className="rounded-[var(--r-md)] border border-border bg-card px-3.5 py-8 text-center text-sm text-muted-foreground">
          近 240 日三大法人買賣超會在下次資料匯出後出現。法人分仍可先看。
        </p>
      ) : (
        <>
          {/* 次切：外資 | 投信 | 自營商 | 三大法人（全寬分段） */}
          <div
            role="tablist"
            aria-label="法人類型"
            className="grid w-full grid-cols-4 overflow-hidden rounded-[var(--r-md)] border border-border bg-card"
          >
            {SERIES.map((s, i) => (
              <button
                key={s.key}
                type="button"
                role="tab"
                aria-selected={series === s.key}
                className={cn(
                  "min-h-11 px-1 text-[12.5px] font-bold transition-colors",
                  i > 0 && "border-l border-border",
                  series === s.key
                    ? "bg-secondary text-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
                onClick={() => setSeries(s.key)}
              >
                {s.label}
              </button>
            ))}
          </div>

          {/* 柱狀買賣超 + 股價線（左張右元） */}
          <div className="overflow-hidden rounded-[var(--r-lg)] border border-border bg-card shadow-[var(--shadow-card)]">
            <div className="flex items-center justify-between gap-2 border-b border-[color:var(--line)] px-3 py-2">
              <span className="text-[12.5px] font-semibold text-foreground">
                {seriesLabel}買賣超
              </span>
              <span className="text-[11px] text-muted-foreground">
                近 {chartRows.length} 日 · 白線收盤價
              </span>
            </div>
            <div className="relative grid grid-cols-[40px_1fr_40px] gap-0 px-1 pt-2 pb-1" style={{ height: 200 }}>
              <div className="flex flex-col justify-between py-1 text-right text-[9px] leading-none text-muted-foreground">
                {leftTicks.map((t, i) => (
                  <span key={i} className="num">
                    {t === 0 ? "0" : fmtLots(t).replace("+", "")}
                  </span>
                ))}
              </div>
              <div className="relative min-w-0">
                <div className="pointer-events-none absolute inset-x-0 top-1/2 h-px bg-[color:var(--line)]" />
                <div className="flex h-full items-stretch gap-px">
                  {chartRows.map((r) => {
                    const v = r[series];
                    const h = Math.max(v !== 0 ? 3 : 0, Math.round((Math.abs(v) / maxAbs) * 78));
                    return (
                      <div
                        key={r.t}
                        className="flex min-w-0 flex-1 flex-col"
                        title={`${r.t} ${seriesLabel} ${fmtLots(v)}張`}
                      >
                        <div className="flex h-1/2 flex-col justify-end">
                          {v > 0 ? <div className="w-full rounded-sm bg-up/85" style={{ height: h }} /> : null}
                        </div>
                        <div className="flex h-1/2 flex-col justify-start">
                          {v < 0 ? <div className="w-full rounded-sm bg-down/85" style={{ height: h }} /> : null}
                        </div>
                      </div>
                    );
                  })}
                </div>
                {pricePath && (
                  <svg
                    className="pointer-events-none absolute inset-0 h-full w-full"
                    viewBox="0 0 100 100"
                    preserveAspectRatio="none"
                    aria-hidden
                  >
                    <polyline
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.4"
                      className="text-foreground/80"
                      points={pricePath}
                      vectorEffect="non-scaling-stroke"
                    />
                  </svg>
                )}
              </div>
              <div className="flex flex-col justify-between py-1 text-left text-[9px] leading-none text-muted-foreground">
                {rightTicks.length
                  ? rightTicks.map((t, i) => (
                      <span key={i} className="num">
                        {t}
                      </span>
                    ))
                  : null}
              </div>
            </div>
            <div className="flex justify-between border-t border-[color:var(--line)] px-3 py-1.5 text-[10px] text-muted-foreground">
              <span>張</span>
              {chartRows.length >= 2 && (
                <span className="num">
                  {fmtMD(chartRows[0].t)} – {fmtMD(chartRows[chartRows.length - 1].t)}
                </span>
              )}
              <span>元</span>
            </div>
          </div>

          {/* 日表：日期 | 外資 | 投信 | 自營商 | 三大法人 */}
          <div className="overflow-x-auto rounded-[var(--r-lg)] border border-border bg-card shadow-[var(--shadow-card)]">
            <table className="w-full border-collapse text-[13px]">
              <thead>
                <tr>
                  <th className="px-3 py-2.5 text-left font-semibold text-muted-foreground">日期</th>
                  <th className="px-2.5 py-2.5 text-right font-semibold text-muted-foreground whitespace-nowrap">外資</th>
                  <th className="px-2.5 py-2.5 text-right font-semibold text-muted-foreground whitespace-nowrap">投信</th>
                  <th className="px-2.5 py-2.5 text-right font-semibold text-muted-foreground whitespace-nowrap">自營商</th>
                  <th className="px-2.5 py-2.5 text-right font-semibold text-muted-foreground whitespace-nowrap">三大法人</th>
                </tr>
              </thead>
              <tbody>
                {tableRows.map((r) => (
                  <tr
                    key={r.t}
                    className={cn(
                      "num border-t border-[color:var(--line)]",
                      // 高亮當前次切欄，方便對照圖
                    )}
                  >
                    <td className="px-3 py-2 font-sans text-foreground">{fmtMD(r.t)}</td>
                    <Cell n={r.foreign} emphasize={series === "foreign"} />
                    <Cell n={r.trust} emphasize={series === "trust"} />
                    <Cell n={r.dealer} emphasize={series === "dealer"} />
                    <Cell n={r.total} emphasize={series === "total"} bold />
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
            單位張。T+1 盤後官方三大法人（TWSE T86 / TPEx），與分點裁剪資料不同源。白線僅對齊收盤價方便對照，不是建議。
          </p>
        </>
      )}
    </div>
  );
}

function Cell({ n, bold, emphasize }: { n: number; bold?: boolean; emphasize?: boolean }) {
  return (
    <td
      className={cn(
        "px-2.5 py-2 text-right whitespace-nowrap",
        bold && "font-bold",
        emphasize && "bg-secondary/60",
        n > 0 ? "text-up" : n < 0 ? "text-down" : "text-[color:var(--ink-2)]",
      )}
    >
      {n === 0 ? "0" : fmtLots(n)}
    </td>
  );
}
