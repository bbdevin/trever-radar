"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { fmtLots, fmtAmount } from "@/lib/format";
import { cn } from "@/lib/utils";
import {
  aggregateBranchRows,
  tradingDaysDesc,
  type BranchTrackFile,
  type TrackIndexEntry,
} from "@/lib/branchTrack";

const SOURCE_BADGE: Record<string, { label: string; cls: string }> = {
  manual: { label: "手動", cls: "bg-warn/10 text-warn" },
  auto: { label: "自動", cls: "bg-primary/10 text-primary" },
};

const PRESET_PERIODS = [1, 5, 10, 20];
const TOP_N = 15;

function fileFor(index: TrackIndexEntry[], branchName: string | null): TrackIndexEntry | null {
  if (!branchName) return null;
  return index.find((e) => e.branch_name === branchName) ?? null;
}

/** 聚合表格骨架:欄位版面與正式表格對齊(V1 慣例)。 */
function TableSkeleton() {
  return (
    <div className="overflow-hidden rounded-[var(--r-lg)] border border-border bg-card shadow-[var(--shadow-card)]">
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <div key={i} className="flex items-center justify-between gap-4 border-t border-[color:var(--line)] px-3.5 py-3 first:border-t-0">
          <Skeleton className="h-8 w-40 rounded-md" />
          <Skeleton className="h-5 w-16 rounded-md" />
          <Skeleton className="h-5 w-20 rounded-md" />
          <Skeleton className="h-5 w-12 rounded-md" />
        </div>
      ))}
    </div>
  );
}

function AggTable({
  title,
  hint,
  rows,
  stocks,
}: {
  title: string;
  hint: string;
  rows: { stock_id: string; net_lots: number; pct_avg: number | null }[];
  stocks: BranchTrackFile["stocks"];
}) {
  if (rows.length === 0) return null;
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline gap-2">
        <h3 className="text-[14px] font-semibold text-foreground">{title}</h3>
        <span className="text-xs text-muted-foreground">{hint}</span>
      </div>
      <div className="overflow-x-auto rounded-[var(--r-lg)] border border-border bg-card shadow-[var(--shadow-card)]">
        <table className="w-full border-collapse text-[13px]">
          <thead>
            <tr>
              <th className="px-3.5 py-2.5 text-left font-semibold text-muted-foreground">股票</th>
              <th className="px-3.5 py-2.5 text-right font-semibold text-muted-foreground whitespace-nowrap">淨買超張</th>
              <th className="px-3.5 py-2.5 text-right font-semibold text-muted-foreground whitespace-nowrap">估算金額</th>
              <th className="px-3.5 py-2.5 text-right font-semibold text-muted-foreground whitespace-nowrap">平均佔比</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const meta = stocks[r.stock_id];
              const amount = meta?.close != null ? r.net_lots * 1000 * meta.close : null;
              return (
                <tr
                  key={r.stock_id}
                  onClick={() => { window.location.href = `/stock?id=${r.stock_id}`; }}
                  className="num cursor-pointer border-t border-[color:var(--line)] transition-colors duration-200 hover:bg-secondary"
                >
                  <td className="px-3.5 py-2.5 text-left">
                    <a href={`/stock?id=${r.stock_id}`} onClick={(e) => e.stopPropagation()} className="flex flex-col gap-0.5 font-sans">
                      <b className="text-sm font-bold text-foreground">{meta?.name ?? r.stock_id}</b>
                      <small className="text-[11px] text-muted-foreground">{r.stock_id}</small>
                    </a>
                  </td>
                  <td className={cn("px-3.5 py-2.5 text-right font-bold whitespace-nowrap", r.net_lots > 0 ? "text-up" : r.net_lots < 0 ? "text-down" : "text-[color:var(--ink-2)]")}>
                    {fmtLots(r.net_lots)}
                  </td>
                  <td className={cn("px-3.5 py-2.5 text-right whitespace-nowrap", r.net_lots > 0 ? "text-up" : r.net_lots < 0 ? "text-down" : "text-[color:var(--ink-2)]")}>
                    {fmtAmount(amount)}
                  </td>
                  <td className="px-3.5 py-2.5 text-right whitespace-nowrap text-[color:var(--ink-2)]">
                    {r.pct_avg != null ? `${r.pct_avg.toFixed(2)}%` : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function BranchTrackView({
  index,
  branchName,
  onBack,
  onSelectBranch,
}: {
  index: TrackIndexEntry[];
  branchName: string | null;
  onBack: () => void;
  onSelectBranch: (name: string) => void;
}) {
  const entry = fileFor(index, branchName);
  const [data, setData] = useState<BranchTrackFile | null>(null);
  const [loading, setLoading] = useState(false);
  const [period, setPeriod] = useState<number | "custom">(20);
  const [customRaw, setCustomRaw] = useState("30");

  // 換分點時重載檔案(index 提供 branch_name → file 對照,檔名為確定性 hash)
  useEffect(() => {
    if (!entry) {
      setData(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setData(null);
    fetch(`/data/branches/track/${entry.file}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((j: BranchTrackFile) => { if (!cancelled) setData(j); })
      .catch(() => { if (!cancelled) setData(null); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [entry?.file]);

  const availableDays = useMemo(() => (data ? tradingDaysDesc(data.rows).length : 0), [data]);

  // 自訂 N:clamp 到可用交易日數;回報是否被 clamp 以提示
  const customParsed = Math.max(1, Math.floor(Number(customRaw) || 0));
  const customClamped = availableDays > 0 ? Math.min(customParsed, availableDays) : customParsed;
  const isCustomClamped = period === "custom" && customParsed > availableDays && availableDays > 0;
  const effectiveN = period === "custom" ? customClamped : period;

  const aggregated = useMemo(
    () => (data ? aggregateBranchRows(data.rows, effectiveN) : []),
    [data, effectiveN],
  );
  const buys = aggregated.filter((r) => r.net_lots > 0).slice(0, TOP_N);
  const sells = aggregated.filter((r) => r.net_lots < 0).sort((a, b) => a.net_lots - b.net_lots).slice(0, TOP_N);

  // ── index 空:尚無追蹤分點 ──
  if (index.length === 0) {
    return (
      <div className="flex flex-col gap-4 pb-7">
        <button
          onClick={onBack}
          className="inline-flex min-h-11 w-fit items-center gap-1.5 rounded-full px-3 text-[13.5px] font-semibold text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="返回排行榜"
        >
          <ArrowLeft size={16} /> 返回排行榜
        </button>
        <div className="py-[46px] text-center text-sm text-muted-foreground">尚無追蹤分點。</div>
      </div>
    );
  }

  const badge = entry ? SOURCE_BADGE[entry.source] : undefined;

  return (
    <div className="flex flex-col gap-4 pb-7">
      {/* 頂部:返回 + 分點下拉切換 */}
      <div className="flex flex-wrap items-center gap-2.5">
        <button
          onClick={onBack}
          className="inline-flex min-h-11 items-center gap-1.5 rounded-full border border-border bg-card px-3 text-[13.5px] font-semibold text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="返回排行榜"
        >
          <ArrowLeft size={16} /> 返回
        </button>
        <div className="flex items-center gap-2">
          <label htmlFor="track-branch" className="sr-only">選擇追蹤分點</label>
          <select
            id="track-branch"
            value={branchName ?? ""}
            onChange={(e) => onSelectBranch(e.target.value)}
            className="min-h-11 max-w-full truncate rounded-full border border-border bg-card px-3.5 text-[14px] font-semibold text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {index.map((e) => (
              <option key={e.branch_name} value={e.branch_name}>{e.branch_name}</option>
            ))}
          </select>
          {badge && (
            <span className={cn("rounded-md px-1.5 py-0.5 text-[10.5px] font-bold", badge.cls)}>{badge.label}</span>
          )}
        </div>
      </div>

      {/* 期間 pills */}
      <div className="flex flex-wrap items-center gap-2">
        <div role="tablist" aria-label="期間" className="flex flex-wrap gap-0.5 rounded-full border border-border bg-card p-[3px]">
          {PRESET_PERIODS.map((p) => (
            <button
              key={p}
              role="tab"
              aria-selected={period === p}
              onClick={() => setPeriod(p)}
              className={cn(
                "min-h-11 rounded-full px-3.5 text-[13.5px] font-semibold text-muted-foreground transition-colors",
                period === p && "bg-muted text-foreground shadow-[inset_0_0_0_1px_var(--border-strong)]",
              )}
            >
              近 {p} 日
            </button>
          ))}
          <button
            role="tab"
            aria-selected={period === "custom"}
            onClick={() => setPeriod("custom")}
            className={cn(
              "min-h-11 rounded-full px-3.5 text-[13.5px] font-semibold text-muted-foreground transition-colors",
              period === "custom" && "bg-muted text-foreground shadow-[inset_0_0_0_1px_var(--border-strong)]",
            )}
          >
            自訂
          </button>
        </div>
        {period === "custom" && (
          <div className="flex items-center gap-1.5">
            <input
              type="number"
              inputMode="numeric"
              min={1}
              max={availableDays || undefined}
              value={customRaw}
              onChange={(e) => setCustomRaw(e.target.value)}
              aria-label="自訂天數"
              className="num min-h-11 w-20 rounded-full border border-border bg-card px-3 text-right text-[14px] text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            <span className="text-[13px] text-muted-foreground">
              交易日{availableDays > 0 && `(可用 ${availableDays})`}
            </span>
          </div>
        )}
      </div>

      {isCustomClamped && (
        <div className="text-[12.5px] text-warn">已超過資料可用交易日數,實際以 {availableDays} 個交易日計算。</div>
      )}

      {/* 誠實限制 */}
      <p className="text-[11.5px] leading-relaxed text-muted-foreground">
        資料為每日前 15 大買賣超裁剪,非全量;分點 ≠ 單一人。
      </p>

      {/* 內容 */}
      {loading ? (
        <TableSkeleton />
      ) : !data || data.rows.length === 0 ? (
        <div className="rounded-[var(--r-lg)] border border-border bg-card px-4 py-[46px] text-center text-sm text-muted-foreground">
          此分點近 {data?.days ?? 120} 日無買賣超紀錄。免費分點資料自 2026-07-07 起累積,且僅涵蓋每日前 15 大買賣超,冷門進出不可見。
        </div>
      ) : (
        <div className="flex flex-col gap-5">
          <AggTable title="期間淨買超" hint={`近 ${effectiveN} 交易日加總,前 ${TOP_N}`} rows={buys} stocks={data.stocks} />
          {sells.length > 0 && (
            <AggTable title="期間反向賣超" hint={`近 ${effectiveN} 交易日淨賣出,前 ${TOP_N}`} rows={sells} stocks={data.stocks} />
          )}
          {buys.length === 0 && sells.length === 0 && (
            <div className="py-[46px] text-center text-sm text-muted-foreground">此期間無淨買賣超紀錄。</div>
          )}
          {data.truncated && (
            <p className="text-[11.5px] text-muted-foreground">資料量過大,已裁切至最近 120 個交易日。</p>
          )}
        </div>
      )}
    </div>
  );
}
