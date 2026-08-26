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
  insider: number | null;
  insiderDelta: number | null;
};

/** 個股「大戶」tab：TDCC 週更＋董監月更（docs/34 B2/D1/D2）。 */
export default function HoldersPanel({ data }: { data: StockJson }) {
  const [threshold, setThreshold] = useState<(typeof THRESHOLDS)[number]>(400);
  const [mode, setMode] = useState<"pct" | "holders" | "directors">("pct");
  const [showAll, setShowAll] = useState(false);

  const history = data.holders_history ?? [];
  const meta: HoldersMeta | undefined = data.holders_meta;
  const directors = data.directors_latest;
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
      const insider = r.insider_pct ?? null;
      const olderInsider = older?.insider_pct ?? null;
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
        insider,
        insiderDelta:
          insider != null && olderInsider != null ? insider - olderInsider : null,
      };
    });
  }, [history, key]);

  const chartRows = useMemo(() => {
    if (mode === "directors") return [];
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

  const hasTdcc = history.length > 0;
  const hasDirectors = !!(directors?.rows && directors.rows.length);

  if (!hasTdcc && !hasDirectors) {
    return (
      <div className="rounded-[var(--r-md)] border border-border bg-card px-3 py-4 text-[13px] text-muted-foreground">
        尚無集保大戶週資料與董監月資料。週六 TDCC／每月 16 日董監匯入後會出現。
      </div>
    );
  }

  const latestDelta =
    latestCell?.shares_pct != null && history[1]?.thresholds?.[key]?.shares_pct != null
      ? latestCell.shares_pct - history[1].thresholds[key].shares_pct
      : null;

  return (
    <div className="grid min-w-0 gap-3">
      {mode !== "directors" && windowNote && (
        <p className="text-[12px] text-muted-foreground">{windowNote}</p>
      )}
      <p className="text-[12px] text-muted-foreground">
        {mode === "directors"
          ? (directors?.note ?? "月更；證交所／櫃買董監事持股餘額明細")
          : (meta?.note ?? "週資料、級距為集保分級彙總，≠分點主力")}
      </p>

      <div className="flex min-w-0 flex-wrap items-center gap-2" role="group" aria-label="檢視模式">
        <span className="text-[12px] text-muted-foreground">檢視</span>
        <button
          type="button"
          className={cn(pillTabClass(mode === "pct"), "cursor-pointer")}
          onClick={() => setMode("pct")}
          disabled={!hasTdcc}
        >
          大戶比
        </button>
        <button
          type="button"
          className={cn(pillTabClass(mode === "holders"), "cursor-pointer")}
          onClick={() => setMode("holders")}
          disabled={!hasTdcc}
        >
          持股人數
        </button>
        <button
          type="button"
          className={cn(pillTabClass(mode === "directors"), "cursor-pointer")}
          onClick={() => setMode("directors")}
        >
          董監持股
        </button>
      </div>

      {mode !== "directors" && (
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
      )}

      {mode === "directors" ? (
        <>
          {hasDirectors ? (
            <>
              <div className="rounded-[var(--r-md)] border border-border bg-card px-3 py-2 text-[12px] text-muted-foreground">
                資料年月 <span className="num text-foreground">{directors!.as_of_ym}</span>
                {" · "}
                {directors!.rows.length} 人 · 月更
              </div>
              <div className="min-w-0 overflow-hidden rounded-[var(--r-md)] border border-border">
                <table className="w-full table-fixed border-collapse text-[11.5px] sm:text-[12.5px]">
                  <thead className="border-b border-border bg-secondary/80 text-muted-foreground">
                    <tr>
                      <th scope="col" className="w-[22%] px-1.5 py-2 text-left font-medium sm:px-2">
                        職稱
                      </th>
                      <th scope="col" className="w-[34%] px-1.5 py-2 text-left font-medium sm:px-2">
                        姓名
                      </th>
                      <th scope="col" className="w-[24%] px-1.5 py-2 text-right font-medium sm:px-2">
                        持股(張)
                      </th>
                      <th scope="col" className="w-[20%] px-1.5 py-2 text-right font-medium sm:px-2">
                        設質%
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {directors!.rows.map((r) => (
                      <tr
                        key={`${r.title}-${r.name}`}
                        className="border-b border-border/60 last:border-0 hover:bg-secondary/40"
                      >
                        <td className="truncate px-1.5 py-1.5 text-left sm:px-2" title={r.title}>
                          {r.title}
                        </td>
                        <td className="truncate px-1.5 py-1.5 text-left sm:px-2" title={r.name}>
                          {r.name}
                        </td>
                        <td className="num px-1.5 py-1.5 text-right sm:px-2">
                          {r.lots != null ? r.lots.toLocaleString("zh-TW") : "—"}
                        </td>
                        <td
                          className={cn(
                            "num px-1.5 py-1.5 text-right sm:px-2",
                            (r.pledged_pct ?? 0) > 0 ? "text-warn" : "text-muted-foreground",
                          )}
                        >
                          {r.pledged_pct == null ? "—" : fmtNum(r.pledged_pct)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <div className="rounded-[var(--r-md)] border border-border bg-card px-3 py-4 text-[13px] text-muted-foreground">
              尚無此檔董監月資料。每月 16 日匯入 OpenAPI 後會出現（≠大戶級距）。
            </div>
          )}
        </>
      ) : !hasTdcc ? (
        <div className="rounded-[var(--r-md)] border border-border bg-card px-3 py-4 text-[13px] text-muted-foreground">
          尚無集保大戶週資料。
        </div>
      ) : (
        <>
          <div className="flex min-w-0 flex-wrap items-center gap-3 rounded-[var(--r-md)] border border-border bg-card px-3 py-2.5 text-[12px]">
            <span className="text-muted-foreground">最新 {fmtMD(latest?.t)}</span>
            <span>
              ≥{threshold} 張{" "}
              <span className={cn("num font-semibold", trendClass(latestDelta))}>
                {fmtNum(latestCell?.shares_pct)}%
              </span>
            </span>
            {latestDelta != null && (
              <span className={cn("num font-semibold", trendClass(latestDelta))}>
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

          <div className="min-w-0 overflow-hidden rounded-[var(--r-md)] border border-border">
            <table className="w-full table-fixed border-collapse text-[11.5px] sm:text-[12.5px]">
              <thead className="border-b border-border bg-secondary/80 text-muted-foreground">
                <tr>
                  <th scope="col" className="w-[18%] px-1 py-2 text-left font-medium sm:px-1.5">
                    日期
                  </th>
                  {mode === "pct" ? (
                    <>
                      <th scope="col" className="w-[28%] px-1 py-2 text-right font-medium sm:px-1.5" title="大戶持股％與增減">
                        大戶<span className="font-normal opacity-70">%</span>
                      </th>
                      <th scope="col" className="w-[27%] px-1 py-2 text-right font-medium sm:px-1.5" title="散戶持股％">
                        散戶<span className="font-normal opacity-70">%</span>
                      </th>
                      <th scope="col" className="w-[27%] px-1 py-2 text-right font-medium sm:px-1.5" title="董監加總÷集保庫存（月更）">
                        內部人<span className="font-normal opacity-70">%</span>
                      </th>
                    </>
                  ) : (
                    <>
                      <th scope="col" className="w-[41%] px-1 py-2 text-right font-medium sm:px-1.5">
                        大戶人數
                      </th>
                      <th scope="col" className="w-[41%] px-1 py-2 text-right font-medium sm:px-1.5">
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
                        className="border-b border-border/60 last:border-0 hover:bg-secondary/40"
                      >
                        <td className="num px-1 py-1.5 text-left sm:px-1.5">{fmtMD(r.t)}</td>
                        <td className="px-1 py-1.5 text-right sm:px-1.5">
                          <div className={cn("num leading-tight", trendClass(r.holdersDelta))}>
                            {r.holders != null ? r.holders.toLocaleString("zh-TW") : "—"}
                          </div>
                          <div
                            className={cn(
                              "num text-[10px] leading-tight",
                              r.holdersDelta == null
                                ? "text-muted-foreground"
                                : trendClass(r.holdersDelta),
                            )}
                          >
                            {r.holdersDelta == null
                              ? "—"
                              : r.holdersDelta > 0
                                ? `+${r.holdersDelta.toLocaleString("zh-TW")}`
                                : r.holdersDelta.toLocaleString("zh-TW")}
                          </div>
                        </td>
                        <td
                          className={cn(
                            "num px-1 py-1.5 text-right sm:px-1.5",
                            r.retailHolders == null
                              ? "text-muted-foreground"
                              : trendClass(r.retailHoldersDelta),
                          )}
                        >
                          {r.retailHolders != null
                            ? r.retailHolders.toLocaleString("zh-TW")
                            : "—"}
                        </td>
                      </tr>
                    );
                  }

                  return (
                    <tr
                      key={r.t}
                      className="border-b border-border/60 last:border-0 hover:bg-secondary/40"
                    >
                      <td className="num px-1 py-1.5 text-left sm:px-1.5">{fmtMD(r.t)}</td>
                      <td className="px-1 py-1.5 text-right sm:px-1.5">
                        <div className={cn("num leading-tight", trendClass(r.majorDelta))}>
                          {fmtNum(r.major)}
                        </div>
                        <div
                          className={cn(
                            "num text-[10px] leading-tight",
                            r.majorDelta == null
                              ? "text-muted-foreground"
                              : trendClass(r.majorDelta),
                          )}
                        >
                          {fmtSigned(r.majorDelta)}
                        </div>
                      </td>
                      <td
                        className={cn(
                          "num px-1 py-1.5 text-right sm:px-1.5",
                          r.retail == null ? "text-muted-foreground" : trendClass(r.retailDelta),
                        )}
                      >
                        {fmtNum(r.retail)}
                      </td>
                      <td
                        className={cn(
                          "num px-1 py-1.5 text-right sm:px-1.5",
                          r.insider == null
                            ? "text-muted-foreground"
                            : trendClass(r.insiderDelta),
                        )}
                        title={meta?.insider_note ?? undefined}
                      >
                        {fmtNum(r.insider)}
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
              className="cursor-pointer text-[12px] font-semibold text-primary hover:underline"
              onClick={() => setShowAll((v) => !v)}
            >
              {showAll ? "收合" : `顯示全部 ${history.length} 週`}
            </button>
          )}
          <p className="text-[11px] text-muted-foreground">
            大戶第二行＝週增減（紅增綠減）。散戶＝未滿 400 張。內部人＝董監加總÷集保（月更
            {meta?.insider_as_of_ym ? `，最新 ${meta.insider_as_of_ym}` : ""}
            ）。
          </p>
        </>
      )}
    </div>
  );
}
