"use client";

import { useMemo, useState } from "react";
import type { HoldersHistoryPoint, HoldersMeta, StockJson } from "@/lib/types";
import { cn, pillTabClass } from "@/lib/utils";

const THRESHOLDS = [400, 600, 800, 1000] as const;
const TABLE_PREVIEW = 16;

function fmtMD(iso: string | undefined): string {
  if (!iso) return "—";
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

/** 百分比數字（表內不帶 %；表頭已標單位） */
function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v == null) return "—";
  return v.toFixed(digits);
}

function fmtSigned(v: number | null | undefined, digits = 2): string {
  if (v == null) return "—";
  if (v > 0) return `+${v.toFixed(digits)}`;
  if (v < 0) return v.toFixed(digits);
  return (0).toFixed(digits);
}

function trendClass(delta: number | null | undefined): string {
  if (delta == null || delta === 0) return "text-foreground";
  return delta > 0 ? "text-up" : "text-down";
}

type RowView = {
  t: string;
  major: number | null;
  majorDelta: number | null;
  retail: number | null;
  retailDelta: number | null;
  holders: number | null;
  holdersDelta: number | null;
  retailHolders: number | null;
  retailHoldersDelta: number | null;
};

/** 個股「大戶」tab：TDCC 週更門檻＋大戶比｜持股人數（docs/34 B2）。 */
export default function HoldersPanel({ data }: { data: StockJson }) {
  const [threshold, setThreshold] = useState<(typeof THRESHOLDS)[number]>(400);
  const [mode, setMode] = useState<"pct" | "holders">("pct");
  const [showAll, setShowAll] = useState(false);

  const history = data.holders_history ?? [];
  const meta: HoldersMeta | undefined = data.holders_meta;
  const latest = history[0];
  const key = String(threshold);
  const latestCell = latest?.thresholds?.[key];

  const rows: RowView[] = useMemo(() => {
    return history.map((r, i) => {
      const older: HoldersHistoryPoint | undefined = history[i + 1];
      const cell = r.thresholds?.[key];
      const olderCell = older?.thresholds?.[key];
      const major = cell?.shares_pct ?? null;
      const olderMajor = olderCell?.shares_pct ?? null;
      const holders = cell?.holders ?? null;
      const olderHolders = olderCell?.holders ?? null;
      const retail = r.retail_pct ?? null;
      const olderRetail = older?.retail_pct ?? null;
      const retailHolders = r.retail_holders ?? null;
      const olderRetailHolders = older?.retail_holders ?? null;
      return {
        t: r.t,
        major,
        majorDelta: major != null && olderMajor != null ? major - olderMajor : null,
        retail,
        retailDelta: retail != null && olderRetail != null ? retail - olderRetail : null,
        holders,
        holdersDelta: holders != null && olderHolders != null ? holders - olderHolders : null,
        retailHolders,
        retailHoldersDelta:
          retailHolders != null && olderRetailHolders != null
            ? retailHolders - olderRetailHolders
            : null,
      };
    });
  }, [history, key]);

  const chartRows = useMemo(() => {
    const slice = rows.slice().reverse();
    return slice.map((r) => ({
      t: r.t,
      value: mode === "pct" ? r.major : r.holders,
    }));
  }, [rows, mode]);

  const values = chartRows.map((r) => r.value).filter((v): v is number => v != null);
  const maxV = Math.max(0.01, ...values, 0.01);
  const minV = values.length ? Math.min(...values) : 0;
  const span = Math.max(maxV - minV, 0.01);

  const tableRows = showAll ? rows : rows.slice(0, TABLE_PREVIEW);

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

  const latestDelta =
    latestCell?.shares_pct != null && history[1]?.thresholds?.[key]?.shares_pct != null
      ? latestCell.shares_pct - history[1].thresholds[key].shares_pct
      : null;

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
            className={cn(pillTabClass(threshold === th), "cursor-pointer")}
            onClick={() => setThreshold(th)}
          >
            {th} 張
          </button>
        ))}
      </div>

      <div className="flex min-w-0 flex-wrap items-center gap-2" role="group" aria-label="檢視模式">
        <span className="text-[12px] text-muted-foreground">檢視</span>
        <button
          type="button"
          className={cn(pillTabClass(mode === "pct"), "cursor-pointer")}
          onClick={() => setMode("pct")}
        >
          大戶比
        </button>
        <button
          type="button"
          className={cn(pillTabClass(mode === "holders"), "cursor-pointer")}
          onClick={() => setMode("holders")}
        >
          持股人數
        </button>
      </div>

      <div className="flex min-w-0 flex-wrap items-center gap-3 rounded-[var(--r-md)] border border-border bg-card px-3 py-2.5 text-[12px]">
        <span className="text-muted-foreground">最新 {fmtMD(latest?.t)}</span>
        <span>
          ≥{threshold} 張{" "}
          <span className={cn("num font-semibold", trendClass(latestDelta))}>
            {fmtNum(latestCell?.shares_pct)}%
          </span>
        </span>
        {latestDelta != null && (
          <span className={cn("num font-semibold", trendClass(latestDelta))} aria-label={`較上週 ${fmtSigned(latestDelta)} 百分點`}>
            {fmtSigned(latestDelta)}
          </span>
        )}
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
            const h = r.value == null ? 0 : Math.max(4, ((r.value - minV) / span) * 100);
            return (
              <div
                key={r.t}
                title={`${fmtMD(r.t)}: ${mode === "pct" ? `${fmtNum(r.value as number)}%` : r.value}`}
                className="min-w-0 flex-1 rounded-t-sm bg-primary/70 transition-[height] duration-200"
                style={{ height: `${h}%` }}
              />
            );
          })}
        </div>
      </div>

      <div className="overflow-x-auto rounded-[var(--r-md)] border border-border">
        <table className="w-full min-w-[520px] border-collapse text-[12.5px]">
          <thead className="sticky top-0 z-[1] border-b border-border bg-secondary/80 text-muted-foreground backdrop-blur-sm">
            <tr>
              <th scope="col" className="whitespace-nowrap px-2.5 py-2.5 text-left font-medium">
                日期
              </th>
              {mode === "pct" ? (
                <>
                  <th scope="col" className="whitespace-nowrap px-2.5 py-2.5 text-right font-medium">
                    大戶持股
                    <span className="block text-[10px] font-normal opacity-80">(%)</span>
                  </th>
                  <th scope="col" className="whitespace-nowrap px-2.5 py-2.5 text-right font-medium">
                    大戶增減
                    <span className="block text-[10px] font-normal opacity-80">(%)</span>
                  </th>
                  <th scope="col" className="whitespace-nowrap px-2.5 py-2.5 text-right font-medium">
                    散戶持股
                    <span className="block text-[10px] font-normal opacity-80">(%)</span>
                  </th>
                  <th scope="col" className="whitespace-nowrap px-2.5 py-2.5 text-right font-medium">
                    內部人持股
                    <span className="block text-[10px] font-normal opacity-80">(%)</span>
                  </th>
                </>
              ) : (
                <>
                  <th scope="col" className="whitespace-nowrap px-2.5 py-2.5 text-right font-medium">
                    大戶人數
                  </th>
                  <th scope="col" className="whitespace-nowrap px-2.5 py-2.5 text-right font-medium">
                    人數增減
                  </th>
                  <th scope="col" className="whitespace-nowrap px-2.5 py-2.5 text-right font-medium">
                    散戶人數
                  </th>
                </>
              )}
            </tr>
          </thead>
          <tbody>
            {tableRows.map((r) => {
              if (mode === "holders") {
                return (
                  <tr
                    key={r.t}
                    className="border-b border-border/60 transition-colors duration-150 last:border-0 hover:bg-secondary/40"
                  >
                    <td className="num whitespace-nowrap px-2.5 py-2 text-left text-foreground">{fmtMD(r.t)}</td>
                    <td className={cn("num whitespace-nowrap px-2.5 py-2 text-right", trendClass(r.holdersDelta))}>
                      {r.holders != null ? r.holders.toLocaleString("zh-TW") : "—"}
                    </td>
                    <td className={cn("num whitespace-nowrap px-2.5 py-2 text-right", trendClass(r.holdersDelta))}>
                      {r.holdersDelta == null
                        ? "—"
                        : r.holdersDelta > 0
                          ? `+${r.holdersDelta.toLocaleString("zh-TW")}`
                          : r.holdersDelta.toLocaleString("zh-TW")}
                    </td>
                    <td
                      className={cn(
                        "num whitespace-nowrap px-2.5 py-2 text-right",
                        r.retailHolders == null
                          ? "text-muted-foreground"
                          : trendClass(r.retailHoldersDelta),
                      )}
                    >
                      {r.retailHolders != null ? r.retailHolders.toLocaleString("zh-TW") : "—"}
                    </td>
                  </tr>
                );
              }

              return (
                <tr
                  key={r.t}
                  className="border-b border-border/60 transition-colors duration-150 last:border-0 hover:bg-secondary/40"
                >
                  <td className="num whitespace-nowrap px-2.5 py-2 text-left text-foreground">{fmtMD(r.t)}</td>
                  <td className={cn("num whitespace-nowrap px-2.5 py-2 text-right", trendClass(r.majorDelta))}>
                    {fmtNum(r.major)}
                  </td>
                  <td className={cn("num whitespace-nowrap px-2.5 py-2 text-right", trendClass(r.majorDelta))}>
                    {fmtSigned(r.majorDelta)}
                  </td>
                  <td
                    className={cn(
                      "num whitespace-nowrap px-2.5 py-2 text-right",
                      r.retail == null ? "text-muted-foreground" : trendClass(r.retailDelta),
                    )}
                  >
                    {fmtNum(r.retail)}
                  </td>
                  <td
                    className="num whitespace-nowrap px-2.5 py-2 text-right text-muted-foreground"
                    title="內部人持股尚未接入"
                  >
                    —
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
          className="cursor-pointer text-[12px] font-semibold text-primary transition-opacity duration-150 hover:underline"
          onClick={() => setShowAll((v) => !v)}
        >
          {showAll ? "收合" : `顯示全部 ${history.length} 週`}
        </button>
      )}
      <p className="text-[11px] text-muted-foreground">
        紅＝較上週增加、綠＝減少（台股慣例）。散戶＝未滿 400 張；內部人尚未接入。
      </p>
    </div>
  );
}
