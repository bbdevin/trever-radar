"use client";

import { useMemo, useState } from "react";
import type { HoldersHistoryPoint, HoldersMeta, StockJson } from "@/lib/types";
import { cn, pillTabClass } from "@/lib/utils";

const THRESHOLDS = [400, 600, 800, 1000] as const;
const TABLE_PREVIEW = 16;

function fmtYMD(iso: string | undefined): string {
  if (!iso) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return iso;
  return `${m[1]}/${m[2]}/${m[3]}`;
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${v.toFixed(2)}%`;
}

/** 個股「大戶」tab：TDCC 週更門檻＋張數比例｜持股人數（docs/34 B2）。 */
export default function HoldersPanel({ data }: { data: StockJson; candles?: Candle[] }) {
  const [threshold, setThreshold] = useState<(typeof THRESHOLDS)[number]>(400);
  const [mode, setMode] = useState<"pct" | "holders">("pct");
  const [showAll, setShowAll] = useState(false);

  const history = data.holders_history ?? [];
  const meta: HoldersMeta | undefined = data.holders_meta;
  const latest = history[0];
  const key = String(threshold);
  const latestCell = latest?.thresholds?.[key];

  const chartRows = useMemo(() => {
    const slice = history.slice().reverse();
    return slice.map((r) => {
      const cell = r.thresholds?.[key];
      return {
        t: r.t,
        value: mode === "pct" ? (cell?.shares_pct ?? null) : (cell?.holders ?? null),
      };
    });
  }, [history, key, mode]);

  const values = chartRows.map((r) => r.value).filter((v): v is number => v != null);
  const maxV = Math.max(0.01, ...values, 0.01);
  const minV = values.length ? Math.min(...values) : 0;
  const span = Math.max(maxV - minV, 0.01);

  const tableRows: HoldersHistoryPoint[] = showAll ? history : history.slice(0, TABLE_PREVIEW);

  const windowNote =
    meta?.display_from && meta?.display_to
      ? `顯示 ${fmtYMD(meta.display_from)}–${fmtYMD(meta.display_to)}（${meta.window_label ?? "當年度"}）`
      : null;

  if (!history.length) {
    return (
      <div className="rounded-[var(--r-md)] border border-border bg-card px-3 py-4 text-[13px] text-muted-foreground">
        尚無集保大戶週資料。週六 06:30 匯入後會出現（≠分點主力）。
      </div>
    );
  }

  return (
    <div className="grid min-w-0 gap-3">
      {windowNote && <p className="text-[12px] text-muted-foreground">{windowNote}</p>}
      <p className="text-[12px] text-muted-foreground">
        {meta?.note ?? "週資料、級距為集保分級彙總，≠分點主力"}
      </p>

      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <span className="text-[12px] text-muted-foreground">門檻</span>
        {THRESHOLDS.map((th) => (
          <button
            key={th}
            type="button"
            className={pillTabClass(threshold === th)}
            onClick={() => setThreshold(th)}
          >
            {th} 張
          </button>
        ))}
      </div>

      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <span className="text-[12px] text-muted-foreground">檢視</span>
        <button type="button" className={pillTabClass(mode === "pct")} onClick={() => setMode("pct")}>
          張數比例
        </button>
        <button
          type="button"
          className={pillTabClass(mode === "holders")}
          onClick={() => setMode("holders")}
        >
          持股人數
        </button>
      </div>

      <div className="flex min-w-0 flex-wrap items-center gap-3 rounded-[var(--r-md)] border border-border bg-card px-3 py-2.5 text-[12px]">
        <span className="text-muted-foreground">最新 {fmtYMD(latest?.t)}</span>
        <span>
          ≥{threshold} 張比例{" "}
          <span className="num font-semibold text-foreground">{fmtPct(latestCell?.shares_pct)}</span>
        </span>
        <span>
          人數{" "}
          <span className="num font-semibold text-foreground">
            {latestCell?.holders != null ? latestCell.holders.toLocaleString("zh-TW") : "—"}
          </span>
        </span>
      </div>

      <div className="relative h-24 overflow-hidden rounded-[var(--r-md)] border border-border bg-card px-2 py-2">
        <div className="flex h-full items-end gap-px">
          {chartRows.map((r) => {
            const h =
              r.value == null ? 0 : Math.max(4, ((r.value - minV) / span) * 100);
            return (
              <div
                key={r.t}
                title={`${fmtYMD(r.t)}: ${mode === "pct" ? fmtPct(r.value as number) : r.value}`}
                className={cn("min-w-0 flex-1 rounded-t-sm bg-primary/70")}
                style={{ height: `${h}%` }}
              />
            );
          })}
        </div>
      </div>

      <div className="overflow-x-auto rounded-[var(--r-md)] border border-border">
        <table className="w-full min-w-[280px] text-left text-[12.5px]">
          <thead className="border-b border-border bg-muted/40 text-muted-foreground">
            <tr>
              <th className="px-2.5 py-2 font-medium">週結算</th>
              <th className="px-2.5 py-2 font-medium">{mode === "pct" ? "持股比例" : "持股人數"}</th>
            </tr>
          </thead>
          <tbody>
            {tableRows.map((r) => {
              const cell = r.thresholds?.[key];
              return (
                <tr key={r.t} className="border-b border-border/70 last:border-0">
                  <td className="px-2.5 py-1.5 num">{fmtYMD(r.t)}</td>
                  <td className="px-2.5 py-1.5 num">
                    {mode === "pct"
                      ? fmtPct(cell?.shares_pct)
                      : cell?.holders != null
                        ? cell.holders.toLocaleString("zh-TW")
                        : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {history.length > TABLE_PREVIEW && (
        <button
          type="button"
          className="text-[12px] text-muted-foreground underline-offset-2 hover:underline"
          onClick={() => setShowAll((v) => !v)}
        >
          {showAll ? "收合" : `顯示全部 ${history.length} 週`}
        </button>
      )}
    </div>
  );
}
