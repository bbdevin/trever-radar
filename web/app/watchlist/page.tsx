"use client";

import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { ArrowUpDown, ChevronDown, ShieldCheck } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import WatchlistButton from "@/components/WatchlistButton";
import type { RadarJson, StockJson } from "@/lib/types";
import { chgClass, fmtPct, MARKET_LABEL } from "@/lib/format";
import { signInWithGoogle, useSession } from "@/lib/useSession";
import { useWatchlist } from "@/lib/watchlist";
import { cn } from "@/lib/utils";

type Row = {
  stock_id: string;
  data: StockJson | null;
  found: boolean;
};

// IA-4A: sort options for the watchlist queue
type SortKey = "risk" | "watch_dist" | "stop_dist" | "chg" | "added";

const SORT_OPTIONS: { key: SortKey; label: string }[] = [
  { key: "stop_dist", label: "\u63a5\u8fd1\u5931\u6548" },
  { key: "watch_dist", label: "\u63a5\u8fd1\u89c0\u5bdf" },
  { key: "risk", label: "\u98a8\u96aa\u512a\u5148" },
  { key: "chg", label: "\u6f32\u8dcc\u5e45" },
  { key: "added", label: "\u52a0\u5165\u9806\u5e8f" },
];

const CHG_TEXT: Record<string, string> = { up: "text-up", down: "text-down", flat: "text-foreground" };
const CHG_BADGE: Record<string, string> = {
  up: "text-up bg-up/15",
  down: "text-down bg-down/15",
  flat: "text-foreground bg-secondary",
};

function EmptyNotice({ children }: { children: React.ReactNode }) {
  return (
    <Alert className="mt-6 bg-card">
      <AlertDescription className="flex flex-wrap items-baseline gap-2.5 text-[13px] text-foreground">
        <span className="shrink-0 rounded-md bg-[color:var(--ink-2)]/10 px-2 py-0.5 text-[11.5px] font-bold tracking-[0.3px] text-[color:var(--ink-2)]">{"\u81ea\u9078\u8ffd\u8e64"}</span>
        <span>{children}</span>
      </AlertDescription>
    </Alert>
  );
}

/**
 * F1.3 一鍵加入今日 Armed。只加不減:對每檔「尚未在自選」的 armed 股呼叫 toggle(新增),
 * 已在自選者跳過;逐檔失敗不中斷,完成後 Sonner 回饋。radar.json 讀取沿用全站 /data 取法。
 * 未登入 / 今日無 Armed / 全部已在自選 → disabled。不自動同步,純手動一鍵。
 */
function AddTodayArmedButton({ className }: { className?: string }) {
  const { session } = useSession();
  const { ids, toggle } = useWatchlist();
  const [armed, setArmed] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch("/data/radar.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d: RadarJson) => { if (!cancelled) setArmed(d.lists?.armed ?? []); })
      .catch(() => { if (!cancelled) setArmed([]); });
    return () => { cancelled = true; };
  }, []);

  // 尚未在自選的 armed 檔(只加不減的目標集合)
  const pending = useMemo(() => (armed ?? []).filter((id) => !ids.has(id)), [armed, ids]);
  const noArmed = armed != null && armed.length === 0;
  const disabled = !session || busy || pending.length === 0;

  const label = busy
    ? "加入中…"
    : !session
      ? "登入後可用"
      : noArmed
        ? "今日無 Armed"
        : `加入今日 Armed(${pending.length} 檔)`;

  const handleClick = async () => {
    if (disabled) return;
    const targets = [...pending]; // 快照,避免 ids 於過程變動
    setBusy(true);
    let ok = 0;
    let fail = 0;
    for (const id of targets) {
      const { error } = await toggle(id); // pending 已排除在自選者 → 一律為新增
      if (error) fail++;
      else ok++;
    }
    setBusy(false);
    if (fail === 0) toast.success(`已加入 ${ok} 檔`, { duration: 2500 });
    else toast.warning(`已加入 ${ok} 檔;失敗 ${fail} 檔`, { duration: 3500 });
  };

  return (
    <Button
      variant="outline"
      size="sm"
      className={cn("gap-1.5", className)}
      onClick={handleClick}
      disabled={disabled}
      aria-busy={busy}
      title={label}
    >
      <ShieldCheck size={14} />
      {label}
    </Button>
  );
}

/** Calculate distance % between price and target. Returns null if either is missing. */
function distPct(price: number, target: number | null | undefined): number | null {
  if (target == null || target === 0) return null;
  return ((price - target) / Math.abs(target)) * 100;
}

/** Derive last close, chg, watch/stop distances for a row */
function rowMetrics(row: Row) {
  const data = row.data;
  if (!data) return { close: null, chg: null, watchDist: null, stopDist: null, hasRisk: false, final: null };
  const cs = data.candles;
  const last = cs[cs.length - 1];
  const prev = cs.length > 1 ? cs[cs.length - 2] : null;
  const close = last?.c ?? null;
  const chg = prev && close != null ? Math.round(((close - prev.c) / prev.c) * 10000) / 100 : null;
  const watchDist = close != null ? distPct(close, data.scores?.watch_price) : null;
  const stopDist = close != null ? distPct(close, data.scores?.stop_price) : null;
  const hasRisk = (data.scores?.risk_penalty ?? 0) <= -8;
  const final = data.scores?.final ?? null;
  return { close, chg, watchDist, stopDist, hasRisk, final };
}

function sortRows(rows: Row[], key: SortKey): Row[] {
  return [...rows].sort((a, b) => {
    const ma = rowMetrics(a);
    const mb = rowMetrics(b);
    // rows without data go last
    if (!a.found && b.found) return 1;
    if (a.found && !b.found) return -1;
    switch (key) {
      case "stop_dist": {
        // Closest to stop (most negative or small positive) comes first
        const da = ma.stopDist ?? Infinity;
        const db = mb.stopDist ?? Infinity;
        return da - db;
      }
      case "watch_dist": {
        // Closest to watch (price just below watch = small positive) comes first
        const da = Math.abs(ma.watchDist ?? Infinity);
        const db = Math.abs(mb.watchDist ?? Infinity);
        return da - db;
      }
      case "risk":
        // Risk rows first, then by final score desc
        if (ma.hasRisk !== mb.hasRisk) return ma.hasRisk ? -1 : 1;
        return (mb.final ?? 0) - (ma.final ?? 0);
      case "chg":
        return (mb.chg ?? -Infinity) - (ma.chg ?? -Infinity);
      case "added":
      default:
        return 0;
    }
  });
}

export default function WatchlistPage() {
  const { session, loading: sessionLoading } = useSession();
  const { items, loading: listLoading } = useWatchlist();
  const [rows, setRows] = useState<Row[] | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("stop_dist");

  useEffect(() => {
    if (!items.length) {
      setRows([]);
      return;
    }
    let cancelled = false;
    Promise.all(
      items.map(async (it) => {
        try {
          const res = await fetch(`/data/stocks/${it.stock_id}.json`);
          if (!res.ok) return { stock_id: it.stock_id, data: null, found: false };
          const data = (await res.json()) as StockJson;
          return { stock_id: it.stock_id, data, found: true };
        } catch {
          return { stock_id: it.stock_id, data: null, found: false };
        }
      }),
    ).then((r) => { if (!cancelled) setRows(r); });
    return () => { cancelled = true; };
  }, [items]);

  const sorted = useMemo(() => (rows ? sortRows(rows, sortKey) : null), [rows, sortKey]);

  if (sessionLoading) return null;

  if (!session) {
    return (
      <div>
        <div className="my-3.5 flex">
          <AddTodayArmedButton />
        </div>
        <EmptyNotice>
          {"\u767b\u5165\u5f8c\u53ef\u5c07\u4efb\u610f\u500b\u80a1\u52a0\u5165\u81ea\u9078\uff0c\u5feb\u901f\u8ffd\u8e64\u89c0\u5bdf\u50f9/\u5931\u6548\u50f9\u8207\u6700\u65b0\u7db1\u5408\u5206\u3002"}
          <Button variant="outline" size="sm" className="mt-2.5 block" onClick={signInWithGoogle}>
            {"\u4ee5 Google \u767b\u5165"}
          </Button>
        </EmptyNotice>
      </div>
    );
  }

  if (listLoading || sorted === null) {
    return (
      <div>
        <div className="my-3.5 flex gap-2.5">
          <Skeleton className="h-[64px] w-[120px] rounded-[var(--r-md)]" />
        </div>
        <div className="flex flex-col gap-2 pb-7">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-[72px] rounded-[var(--r-md)]" />
          ))}
        </div>
      </div>
    );
  }

  if (sorted.length === 0) {
    return (
      <div>
        <div className="my-3.5 flex">
          <AddTodayArmedButton />
        </div>
        <EmptyNotice>{"\u9084\u6c92\u6709\u81ea\u9078\u80a1\u3002\u5230\u4efb\u4e00\u80a1\u7968\u5361\u7247\u6216\u500b\u80a1\u9801\u9ede\u53f3\u4e0a\u89d2\u7684\u661f\u865f\u52a0\u5165\u3002"}</EmptyNotice>
      </div>
    );
  }

  // Split into "needs attention" and "normal tracking"
  const needsAttention = sorted.filter((r) => {
    const m = rowMetrics(r);
    return m.hasRisk || (m.stopDist != null && m.stopDist < 5);
  });
  const normal = sorted.filter((r) => !needsAttention.includes(r));

  return (
    <div>
      {/* Brief */}
      <div className="my-3.5 flex flex-wrap items-center gap-2.5">
        <div className="flex flex-col gap-0.5 rounded-[var(--r-md)] border border-border bg-card p-3 shadow-[var(--shadow-card)]">
          <span className="text-[11.5px] text-muted-foreground">{"\u81ea\u9078\u8ffd\u8e64"}</span>
          <span className="num text-[17px] font-bold">{"\u5171 "}{sorted.length}{" \u6a94"}</span>
        </div>
        {needsAttention.length > 0 && (
          <div className="flex flex-col gap-0.5 rounded-[var(--r-md)] border border-destructive/40 bg-destructive/5 p-3 shadow-[var(--shadow-card)]">
            <span className="text-[11.5px] text-muted-foreground">{"\u9700\u8981\u6ce8\u610f"}</span>
            <span className="num text-[17px] font-bold text-destructive">{needsAttention.length}{" \u6a94"}</span>
          </div>
        )}
        {/* F1.3 一鍵加入今日 Armed */}
        <AddTodayArmedButton className="ml-auto" />
        {/* Sort control */}
        <div className="flex items-center gap-1.5">
          <ArrowUpDown size={13} className="text-muted-foreground" />
          <select
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as SortKey)}
            className="rounded-md border border-border bg-card px-2.5 py-1.5 text-[12.5px] text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label="\u6392\u5e8f\u65b9\u5f0f"
          >
            {SORT_OPTIONS.map((o) => (
              <option key={o.key} value={o.key}>{o.label}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Needs attention group */}
      {needsAttention.length > 0 && (
        <div className="mb-4">
          <div className="mb-2 flex items-center gap-2 text-[11.5px] font-semibold text-destructive">
            <span className="h-px flex-1 bg-destructive/30" />
            {"\u9700\u8981\u6ce8\u610f"}
            <span className="h-px flex-1 bg-destructive/30" />
          </div>
          <div className="flex flex-col gap-2">
            {needsAttention.map((r) => <WatchlistRow key={r.stock_id} row={r} />)}
          </div>
        </div>
      )}

      {/* Normal tracking group */}
      {normal.length > 0 && (
        <div className="pb-7">
          {needsAttention.length > 0 && (
            <div className="mb-2 flex items-center gap-2 text-[11.5px] font-semibold text-muted-foreground">
              <span className="h-px flex-1 bg-border" />
              {"\u4e00\u822c\u8ffd\u8e64"}
              <span className="h-px flex-1 bg-border" />
            </div>
          )}
          <div className="flex flex-col gap-2">
            {normal.map((r) => <WatchlistRow key={r.stock_id} row={r} />)}
          </div>
        </div>
      )}
    </div>
  );
}

function WatchlistRow({ row }: { row: Row }) {
  const { stock_id, data, found } = row;
  const m = rowMetrics(row);

  if (!found || !data) {
    return (
      <div className="flex flex-wrap items-center gap-3.5 rounded-[var(--r-md)] border border-border bg-card p-3.5 text-muted-foreground shadow-[var(--shadow-card)]">
        <div className="flex min-w-[90px] flex-col gap-0.5">
          <span className="text-xs text-muted-foreground">{stock_id}</span>
          <span className="text-[11.5px] text-muted-foreground">{"\u672a\u5165\u8a55\u5206\u6c60(20\u65e5\u5747\u984d <3,000\u842c),\u7121\u5feb\u53d6\u8cc7\u6599"}</span>
        </div>
        <WatchlistButton stockId={stock_id} />
      </div>
    );
  }

  const last = data.candles[data.candles.length - 1];
  const cls = chgClass(m.chg);
  const isRisk = m.hasRisk;
  const nearStop = m.stopDist != null && m.stopDist < 5;

  return (
    <a
      href={`/stock?id=${stock_id}`}
      className={cn(
        "flex min-h-11 flex-wrap items-center gap-3 rounded-[var(--r-md)] border bg-card p-3.5 shadow-[var(--shadow-card)] cursor-pointer transition-colors duration-200 hover:border-[color:var(--border-strong)]",
        (isRisk || nearStop) ? "border-destructive/40" : "border-border",
      )}
    >
      {/* Status bar */}
      <span
        aria-hidden
        className={cn(
          "pointer-events-none absolute left-0 inset-y-1.5 w-[3px] rounded-full hidden",
          // only shown if card has relative position, but we keep this for consistency
        )}
      />

      {/* Name + id */}
      <div className="flex min-w-[90px] flex-col gap-0.5">
        <span className="text-sm font-bold text-foreground">{data.name}</span>
        <span className="text-[11.5px] text-muted-foreground">
          {stock_id} {"\u00b7"} {MARKET_LABEL[data.market] ?? data.market}
        </span>
      </div>

      {/* Price + chg */}
      <div className="flex min-w-[70px] flex-col items-end gap-0.5">
        <span className={cn("num text-[15px] font-bold", CHG_TEXT[cls])}>{last.c.toLocaleString("zh-TW")}</span>
        <span className={cn("num inline-block rounded-full px-2 py-px text-[12.5px] font-bold", CHG_BADGE[cls])}>{fmtPct(m.chg)}</span>
      </div>

      {/* Score */}
      <div className="min-w-10 text-center">
        {m.final != null ? (
          <span className={cn("num text-xl font-extrabold text-[color:var(--ink-2)]", m.final >= 65 && "text-warn")}>
            {m.final}
          </span>
        ) : (
          <span className="text-[11.5px] text-muted-foreground">{"\u672a\u8a55\u5206"}</span>
        )}
      </div>

      {/* Watch / Stop + distance */}
      <div className="ml-auto flex flex-col gap-0.5 text-[11px]">
        {data.scores?.watch_price != null && (
          <span className="text-[color:var(--accent-2)]">
            {"\u89c0\u5bdf"} {data.scores.watch_price.toFixed(2)}
            {m.watchDist != null && (
              <span className="ml-1 text-muted-foreground">
                ({m.watchDist > 0 ? "+" : ""}{m.watchDist.toFixed(1)}%)
              </span>
            )}
          </span>
        )}
        {data.scores?.stop_price != null && (
          <span className={cn("text-up", nearStop && "font-bold text-destructive")}>
            {"\u5931\u6548"} {data.scores.stop_price.toFixed(2)}
            {m.stopDist != null && (
              <span className={cn("ml-1", nearStop ? "text-destructive" : "text-muted-foreground")}>
                ({m.stopDist > 0 ? "+" : ""}{m.stopDist.toFixed(1)}%)
              </span>
            )}
          </span>
        )}
        {isRisk && (
          <span className="font-semibold text-destructive">{"\u98a8\u96aa\u5c0f\u5fc3"}</span>
        )}
      </div>

      <WatchlistButton stockId={stock_id} />
    </a>
  );
}
