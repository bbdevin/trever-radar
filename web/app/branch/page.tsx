"use client";

import { useEffect, useState } from "react";
import { Search, Info, TrendingUp, TrendingDown, Building2, User } from "lucide-react";
import { IconFlame, IconTrend, IconZap } from "@/components/Icons";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import BranchTrackView from "@/components/BranchTrackView";
import type { RadarJson } from "@/lib/types";
import type { TrackIndexEntry } from "@/lib/branchTrack";
import { MARKET_LABEL, fmtX } from "@/lib/format";
import { cn } from "@/lib/utils";

type Ranking = {
  branch_name: string;
  as_of: string;
  rank_score: number;
  win_rate: number | null;
  avg_ret5: number | null;
  samples: number;
  style: string;
  is_daytrade: number;
  source: string;
};

type RankingsData = {
  as_of: string | null;
  rankings: Ranking[];
  daytrade: Ranking[];
};

function NoTrackDetailPanel({ branchName }: { branchName: string }) {
  return (
    <div className="flex h-full min-h-[300px] flex-col items-center justify-center rounded-[var(--r-lg)] border border-border bg-card p-6 text-center shadow-[var(--shadow-card)] animate-in fade-in duration-300">
      <div className="mb-3 rounded-full bg-[color:var(--ink-2)]/10 p-3 text-[color:var(--ink-2)]">
        <svg
          width="28"
          height="28"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="opacity-80"
        >
          <path d="M2 12h20M12 2v20M4.93 4.93l14.14 14.14M4.93 19.07L19.07 4.93" />
        </svg>
      </div>
      <h3 className="text-base font-bold text-foreground mb-1">{branchName}</h3>
      <p className="max-w-xs text-xs leading-relaxed text-muted-foreground">
        {"目前此分點暫無 120 日歷勲買賣明細（系統自 2026-07-07 起僅追蹤熱門股，若要追蹤此分點請等待數據持續累積－特定地緣分點可追蹤）。"}
      </p>
    </div>
  );
}

const MIN_SAMPLES = 10; // 樣本 < 10 顯示「樣本不足」(docs/13 §4)

const SOURCE_BADGE: Record<string, { label: string; cls: string }> = {
  manual: { label: "手動", cls: "bg-warn/10 text-warn" },
  auto: { label: "自動", cls: "bg-primary/10 text-primary" },
  candidate: { label: "候選", cls: "bg-muted text-muted-foreground" },
};

function RankCard({ r, trackable, active }: { r: Ranking; trackable?: boolean; active?: boolean }) {
  const enoughSamples = r.samples >= MIN_SAMPLES;
  const badge = SOURCE_BADGE[r.source] ?? SOURCE_BADGE.candidate;
  return (
    <div className={cn(
      "flex h-full flex-col gap-3 rounded-[var(--r-lg)] border p-3.5 shadow-[var(--shadow-card)] transition-all duration-200",
      r.is_daytrade === 1 ? "border-down/40" : "border-border",
      active ? "border-[color:var(--border-strong)] bg-secondary/60 ring-1 ring-[color:var(--border-strong)]" : "bg-card",
      trackable && "cursor-pointer hover:border-border-strong hover:bg-secondary",
    )}>
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-1 text-lg text-foreground">
          {r.branch_name}
          {trackable && <span aria-hidden className="text-muted-foreground">›</span>}
        </h3>
        <div className="flex items-center gap-1.5">
          <span className={cn("rounded-md px-1.5 py-0.5 text-[10.5px] font-bold", badge.cls)}>{badge.label}</span>
          {r.is_daytrade === 1 && <span className="rounded-md bg-down/10 px-2 py-0.5 text-[11.5px] font-bold text-down">隔日沖</span>}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <div className="text-xs text-muted-foreground">勝率 (5日)</div>
          {enoughSamples ? (
            <div className={cn("text-lg font-semibold", r.win_rate != null ? (r.win_rate > 50 ? "text-up" : "text-down") : "text-[color:var(--ink-2)]")}>
              {r.win_rate != null ? `${r.win_rate.toFixed(1)}%` : "-"}
            </div>
          ) : (
            <div className="text-[13px] font-medium text-[color:var(--ink-2)]">樣本不足</div>
          )}
        </div>
        <div>
          <div className="text-xs text-muted-foreground">平均報酬 (5日)</div>
          {enoughSamples ? (
            <div className={cn("text-lg font-semibold", r.avg_ret5 != null ? (r.avg_ret5 > 0 ? "text-up" : "text-down") : "text-[color:var(--ink-2)]")}>
              {r.avg_ret5 != null ? `${r.avg_ret5.toFixed(1)}%` : "-"}
            </div>
          ) : (
            <div className="text-[13px] font-medium text-[color:var(--ink-2)]">樣本不足</div>
          )}
        </div>
        <div>
          <div className="text-xs text-muted-foreground">事件數</div>
          <div className="num text-foreground">{r.samples}</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">可信度分數</div>
          <div className={cn("num", r.rank_score >= 70 ? "text-warn" : "text-[color:var(--accent-2)]")}>{r.rank_score}</div>
        </div>
      </div>
    </div>
  );
}

type Movement = {
  branch_name: string;
  stock_id: string;
  stock_name: string;
  buy_lots: number;
  sell_lots: number;
  net_lots: number;
  pct: number;
};

type TodayMovements = Record<string, Movement[]>;

type WarrantBreakdown = {
  warrant_id: string;
  warrant_name: string;
  kind: "call" | "put";
  net_lots: number;
  net_amount: number;
};

type WarrantBranch = {
  branch_name: string;
  underlying_id: string;
  underlying_name: string;
  net_amount: number;
  breakdown?: WarrantBreakdown[];
};

function EmptyNotice({ tag, children }: { tag: string; children: React.ReactNode }) {
  return (
    <Alert className="mb-4 bg-card">
      <AlertDescription className="flex flex-wrap items-baseline gap-2.5 text-[13px] text-foreground">
        <span className="shrink-0 rounded-md bg-[color:var(--ink-2)]/10 px-2 py-0.5 text-[11.5px] font-bold tracking-[0.3px] text-[color:var(--ink-2)]">{tag}</span>
        <span>{children}</span>
      </AlertDescription>
    </Alert>
  );
}

function ConcentrationTab({ radar }: { radar: RadarJson | null }) {
  if (!radar) return <Skeleton className="h-[68px] rounded-[var(--r-md)]" />;
  const rows = radar.concentration ?? [];
  if (rows.length === 0) {
    return <EmptyNotice tag="集中度">今日無符合條件的集中度資料(需有分點與成交量紀錄)。</EmptyNotice>;
  }
  return (
    <div className="flex flex-col gap-1.5 pb-2">
      <div className="mb-1 flex items-baseline gap-2">
        <h2 className="text-[15px] font-semibold text-foreground">買超集中度躍升榜</h2>
        <span className="text-xs text-muted-foreground">前5大買超分點佔成交量比,躍升幅度排序</span>
      </div>
      <div className="overflow-x-auto rounded-[var(--r-lg)] border border-border bg-card shadow-[var(--shadow-card)]">
        <table className="w-full border-collapse text-[13px]">
          <thead>
            <tr>
              <th className="px-3.5 py-2.5 text-left font-semibold text-muted-foreground">股票</th>
              <th className="px-3.5 py-2.5 text-right font-semibold text-muted-foreground">前5大買超佔量</th>
              <th className="px-3.5 py-2.5 text-right font-semibold text-muted-foreground">20日均</th>
              <th className="px-3.5 py-2.5 text-right font-semibold text-muted-foreground">躍升幅度</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.id}
                onClick={() => { window.location.href = `/stock?id=${r.id}`; }}
                className="num cursor-pointer border-t border-[color:var(--line)] text-[color:var(--ink-2)] transition-colors duration-200 hover:bg-secondary"
              >
                <td className="px-3.5 py-2.5 text-left">
                  <a href={`/stock?id=${r.id}`} onClick={(e) => e.stopPropagation()} className="flex flex-col gap-0.5 font-sans">
                    <b className="text-sm font-bold text-foreground">{r.name}</b>
                    <small className="text-[11px] text-muted-foreground">
                      {r.id} · {MARKET_LABEL[r.market] ?? r.market}
                    </small>
                  </a>
                </td>
                <td className="px-3.5 py-2.5 text-right whitespace-nowrap">{(r.buy_concentration * 100).toFixed(1)}%</td>
                <td className="px-3.5 py-2.5 text-right whitespace-nowrap">{(r.concentration_avg20 * 100).toFixed(1)}%</td>
                <td className="px-3.5 py-2.5 text-right font-bold whitespace-nowrap text-warn">{fmtX(r.vs20)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const TABS = [
  { key: "rankings", label: "排行榜", hint: "分點操作勝率與可信度排行", icon: IconFlame },
  { key: "today", label: "今日動向", hint: "追蹤分點於最近交易日的買超明細", icon: IconZap },
  { key: "warrant", label: "權證分點異動(實驗)", hint: "追蹤分點針對單一標的之多檔權證，累計買賣超達 500 萬的動向", icon: IconTrend },
] as const;

function LoadingSkeleton() {
  return (
    <>
      <div className="my-3.5 flex gap-2.5">
        <Skeleton className="h-[68px] w-[220px] rounded-[var(--r-md)]" />
      </div>
      <div className="grid grid-cols-1 gap-2.5 pb-7 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-[148px] rounded-[var(--r-lg)]" />
        ))}
      </div>
    </>
  );
}

function TabPill({ active, onClick, title, icon: Icon, label }: { active: boolean; onClick: () => void; title: string; icon: typeof IconFlame; label: string }) {
  return (
    <button
      role="tab"
      aria-selected={active}
      onClick={onClick}
      title={title}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-[13.5px] font-semibold text-muted-foreground transition-colors",
        active && "bg-muted text-foreground shadow-[inset_0_0_0_1px_var(--border-strong)]",
      )}
    >
      <Icon size={15} className="opacity-85" />
      {label}
    </button>
  );
}

function StockGroupCard({ stockId, stockName, totalAmt, branches }: { stockId: string, stockName: string, totalAmt: number, branches: WarrantBranch[] }) {
  const [expandedBranch, setExpandedBranch] = useState<string | null>(null);

  return (
    <div className="flex flex-col rounded-[var(--r-lg)] border border-border bg-card shadow-sm hover:border-border-strong transition-all duration-300 overflow-hidden">
      <div className="p-4 pb-3 flex justify-between items-center border-b border-border bg-card">
        <a href={`/stock?id=${stockId}`} className="flex items-baseline gap-2 hover:opacity-80 transition-opacity">
          <span className="text-foreground font-semibold text-lg tracking-tight">{stockName}</span>
          <span className="text-sm font-medium text-muted-foreground">{stockId}</span>
        </a>
        <div className="flex flex-col items-end">
          <span className="text-[10px] uppercase font-bold tracking-wider text-muted-foreground mb-0.5">Total Net</span>
          <span className={cn("text-xl font-bold num tracking-tight", totalAmt > 0 ? "text-up drop-shadow-[0_0_8px_rgba(239,68,68,0.3)]" : "text-down drop-shadow-[0_0_8px_rgba(34,197,94,0.3)]")}>
            {(Math.abs(totalAmt) / 10000).toLocaleString('zh-TW', { maximumFractionDigits: 0 })} 萬
          </span>
        </div>
      </div>
      
      <div className="flex flex-col p-3 gap-2 bg-background">
        {branches.map((b) => {
          const isExpanded = expandedBranch === b.branch_name;
          const hasBreakdown = b.breakdown && b.breakdown.length > 0;
          return (
            <div key={b.branch_name} className="flex flex-col rounded-md border border-border/40 bg-card/50 shadow-sm hover:bg-card transition-colors duration-200 overflow-hidden group">
              <button
                className="min-h-11 px-3 py-2.5 flex items-center justify-between text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                onClick={() => setExpandedBranch(isExpanded ? null : b.branch_name)}
                aria-expanded={hasBreakdown ? isExpanded : undefined}
                aria-label={`${b.branch_name} 權證明細`}
              >
                <div className="flex items-center gap-2">
                  <span className="font-medium text-[14px] text-foreground tracking-tight group-hover:text-primary transition-colors">{b.branch_name}</span>
                  <div className={cn("px-1.5 py-0.5 rounded text-[10px] font-bold", b.net_amount > 0 ? "bg-up/10 text-up" : "bg-down/10 text-down")}>
                    {b.net_amount > 0 ? "買" : "賣"}
                  </div>
                </div>
                <div className="flex items-center gap-2.5">
                  <span className={cn("text-[14.5px] font-bold num tracking-tight", b.net_amount > 0 ? "text-up" : "text-down")}>
                    {(Math.abs(b.net_amount) / 10000).toLocaleString('zh-TW', { maximumFractionDigits: 0 })} 萬
                  </span>
                  {hasBreakdown && (
                    <div className={cn("transition-transform duration-300 text-muted-foreground/50 group-hover:text-muted-foreground", isExpanded && "rotate-180 text-foreground")}>
                      <svg width="12" height="12" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M2.5 4.5L6 8L9.5 4.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
                    </div>
                  )}
                </div>
              </button>
              
              {hasBreakdown && (
                <div className={cn("grid transition-[grid-template-rows] duration-300 ease-out", isExpanded ? "grid-rows-[1fr]" : "grid-rows-[0fr]")}>
                  <div className="overflow-hidden bg-secondary/20 border-t border-border/40">
                    <div className="p-2 flex flex-col gap-1">
                      {b.breakdown?.map(brk => (
                        <div key={brk.warrant_id} className={cn("grid grid-cols-[1.5fr_1fr_1fr] items-center px-2 py-1.5 rounded-md hover:bg-secondary/60 transition-colors border-l-2", brk.net_amount > 0 ? "border-l-up/60" : "border-l-down/60")}>
                          <div className="flex flex-col">
                            <div className="flex items-center gap-1.5">
                              <span className="text-foreground text-[12.5px] font-medium">{brk.warrant_name}</span>
                              <span className={cn("text-[9px] px-1 py-0.5 rounded font-bold leading-none", brk.kind === "call" ? "bg-up/10 text-up" : "bg-down/10 text-down")}>
                                {brk.kind === "call" ? "購" : "售"}
                              </span>
                            </div>
                          </div>
                          <div className={cn("text-right num font-medium text-[13px] tracking-tight", brk.net_amount > 0 ? "text-up" : "text-down")}>
                            {(Math.abs(brk.net_amount) / 10000).toLocaleString('zh-TW', { maximumFractionDigits: 1 })} 萬
                          </div>
                          <div className="text-right num text-[11px] text-muted-foreground">
                            {Math.round(Math.abs(brk.net_amount) / Math.abs(b.net_amount) * 100)}%
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function BranchGroupCard({ branchName, totalAmt, stocks }: { branchName: string, totalAmt: number, stocks: WarrantBranch[] }) {
  const [expandedStock, setExpandedStock] = useState<string | null>(null);

  return (
    <div className="flex flex-col rounded-[var(--r-lg)] border border-border bg-card shadow-sm hover:border-border-strong transition-all duration-300 overflow-hidden">
      <div className="p-4 pb-3 flex justify-between items-center border-b border-border bg-card">
        <span className="text-foreground font-semibold text-lg tracking-tight">{branchName}</span>
        <div className="flex flex-col items-end">
          <span className="text-[10px] uppercase font-bold tracking-wider text-muted-foreground mb-0.5">Total Net</span>
          <span className={cn("text-xl font-bold num tracking-tight", totalAmt > 0 ? "text-up drop-shadow-[0_0_8px_rgba(239,68,68,0.3)]" : "text-down drop-shadow-[0_0_8px_rgba(34,197,94,0.3)]")}>
            {(Math.abs(totalAmt) / 10000).toLocaleString('zh-TW', { maximumFractionDigits: 0 })} 萬
          </span>
        </div>
      </div>
      
      <div className="flex flex-col p-3 gap-2 bg-background">
        {stocks.map((s) => {
          const isExpanded = expandedStock === s.underlying_id;
          const hasBreakdown = s.breakdown && s.breakdown.length > 0;
          return (
            <div key={s.underlying_id} className="flex flex-col rounded-md border border-border/40 bg-card/50 shadow-sm hover:bg-card transition-colors duration-200 overflow-hidden group">
              <button
                className="min-h-11 px-3 py-2.5 flex items-center justify-between text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                onClick={() => setExpandedStock(isExpanded ? null : s.underlying_id)}
                aria-expanded={hasBreakdown ? isExpanded : undefined}
                aria-label={`${s.underlying_name} 權證明細`}
              >
                <div className="flex items-center gap-2">
                  <a href={`/stock?id=${s.underlying_id}`} className="font-medium text-[14px] text-foreground tracking-tight hover:text-primary transition-colors z-10" onClick={(e) => e.stopPropagation()}>
                    {s.underlying_name}
                  </a>
                  <div className={cn("px-1.5 py-0.5 rounded text-[10px] font-bold", s.net_amount > 0 ? "bg-up/10 text-up" : "bg-down/10 text-down")}>
                    {s.net_amount > 0 ? "買" : "賣"}
                  </div>
                </div>
                <div className="flex items-center gap-2.5">
                  <span className={cn("text-[14.5px] font-bold num tracking-tight", s.net_amount > 0 ? "text-up" : "text-down")}>
                    {(Math.abs(s.net_amount) / 10000).toLocaleString('zh-TW', { maximumFractionDigits: 0 })} 萬
                  </span>
                  {hasBreakdown && (
                    <div className={cn("transition-transform duration-300 text-muted-foreground/50 group-hover:text-muted-foreground", isExpanded && "rotate-180 text-foreground")}>
                      <svg width="12" height="12" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M2.5 4.5L6 8L9.5 4.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
                    </div>
                  )}
                </div>
              </button>
              
              {hasBreakdown && (
                <div className={cn("grid transition-[grid-template-rows] duration-300 ease-out", isExpanded ? "grid-rows-[1fr]" : "grid-rows-[0fr]")}>
                  <div className="overflow-hidden bg-secondary/20 border-t border-border/40">
                    <div className="p-2 flex flex-col gap-1">
                      {s.breakdown?.map(brk => (
                        <div key={brk.warrant_id} className={cn("grid grid-cols-[1.5fr_1fr_1fr] items-center px-2 py-1.5 rounded-md hover:bg-secondary/60 transition-colors border-l-2", brk.net_amount > 0 ? "border-l-up/60" : "border-l-down/60")}>
                          <div className="flex flex-col">
                            <div className="flex items-center gap-1.5">
                              <span className="text-foreground text-[12.5px] font-medium">{brk.warrant_name}</span>
                              <span className={cn("text-[9px] px-1 py-0.5 rounded font-bold leading-none", brk.kind === "call" ? "bg-up/10 text-up" : "bg-down/10 text-down")}>
                                {brk.kind === "call" ? "購" : "售"}
                              </span>
                            </div>
                          </div>
                          <div className={cn("text-right num font-medium text-[13px] tracking-tight", brk.net_amount > 0 ? "text-up" : "text-down")}>
                            {(Math.abs(brk.net_amount) / 10000).toLocaleString('zh-TW', { maximumFractionDigits: 1 })} 萬
                          </div>
                          <div className="text-right num text-[11px] text-muted-foreground">
                            {Math.round(Math.abs(brk.net_amount) / Math.abs(s.net_amount) * 100)}%
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function BranchPage() {
  const [radar, setRadar] = useState<RadarJson | null>(null);
  const [tab, setTab] = useState<"rankings" | "today" | "warrant">("rankings");
  const [rankingsData, setRankingsData] = useState<RankingsData | null>(null);
  const [today, setToday] = useState<TodayMovements | null>(null);
  const [warrantBranches, setWarrantBranches] = useState<Record<string, WarrantBranch[]>>({
    "1d": [], "2d": [], "5d": [], "30d": [], "120d": []
  });
  const [warrantTimeframe, setWarrantTimeframe] = useState<"1d" | "2d" | "5d" | "30d" | "120d">("1d");
  const [viewMode, setViewMode] = useState<"by_stock" | "by_branch">("by_stock");
  const [trackIndex, setTrackIndex] = useState<TrackIndexEntry[]>([]);
  const [trackOpen, setTrackOpen] = useState(false);
  const [trackBranch, setTrackBranch] = useState<string | null>(null);
  const [error, setError] = useState(false);
  // IA-3: filter state
  const [filterSearch, setFilterSearch] = useState("");
  const [filterTrackable, setFilterTrackable] = useState(false);
  const [filterEnough, setFilterEnough] = useState(false);
  const [filterDaytrade, setFilterDaytrade] = useState<"all" | "exclude" | "only">("all");

  useEffect(() => {
    fetch("/data/radar.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setRadar)
      .catch(() => setError(true));

    fetch("/data/branches/rankings.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setRankingsData)
      .catch(() => setError(true));

    fetch("/data/branches/today.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setToday)
      .catch(() => setError(true));

    fetch("/data/branches/warrant_branches.json")
      .then((r) => (r.ok ? r.json() : { "1d": [], "2d": [], "5d": [], "30d": [], "120d": [] }))
      .then(setWarrantBranches)
      .catch(() => {});

    fetch("/data/branches/track/index.json")
      .then((r) => (r.ok ? r.json() : []))
      .then((j: TrackIndexEntry[]) => {
        const arr = Array.isArray(j) ? j : [];
        setTrackIndex(arr);
        if (arr.length > 0) {
          setTrackBranch((prev) => prev || arr[0].branch_name);
        }
      })
      .catch(() => setTrackIndex([]));
  }, []);

  if (error) {
    return (
      <div className="py-[46px] text-center text-sm text-muted-foreground">
        找不到分點資料。請先執行{" "}
        <code className="rounded-md border border-border bg-card px-1.5 py-0.5 text-[12.5px] text-[color:var(--ink-2)]">
          python -m radar compute-branch-stats
        </code>{" "}
        與{" "}
        <code className="rounded-md border border-border bg-card px-1.5 py-0.5 text-[12.5px] text-[color:var(--ink-2)]">export-json</code>
      </div>
    );
  }
  if (!rankingsData || !today) return <LoadingSkeleton />;

  const mainRankings = rankingsData.rankings;
  const daytradeRankings = rankingsData.daytrade;
  const totalBranches = mainRankings.length + daytradeRankings.length;
  const enoughSampleCount = [...mainRankings, ...daytradeRankings].filter(r => r.samples >= MIN_SAMPLES).length;
  const trackNames = new Set(trackIndex.map((e) => e.branch_name));
  const hasDataWarning = [...mainRankings, ...daytradeRankings].some((r) => r.samples < MIN_SAMPLES);

  // IA-3: filter logic
  const allRankings = [...mainRankings, ...daytradeRankings];
  const filteredRankings = allRankings.filter(r => {
    if (filterSearch && !r.branch_name.includes(filterSearch)) return false;
    if (filterTrackable && !trackNames.has(r.branch_name)) return false;
    if (filterEnough && r.samples < MIN_SAMPLES) return false;
    if (filterDaytrade === "exclude" && r.is_daytrade === 1) return false;
    if (filterDaytrade === "only" && r.is_daytrade !== 1) return false;
    return true;
  });
  const filteredMain = filteredRankings.filter(r => r.is_daytrade !== 1);
  const filteredDaytrade = filteredRankings.filter(r => r.is_daytrade === 1);

  return (
    <>
      {/* IA-3: Page Brief */}
      <div className="my-3.5 grid auto-cols-[minmax(100px,1fr)] grid-flow-col gap-2 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <div className="flex flex-col gap-0.5 rounded-[var(--r-md)] border border-border bg-card px-3 py-2 shadow-[var(--shadow-card)]">
          <span className="text-[10.5px] text-muted-foreground">{"入榜分點"}</span>
          <span className="num text-[15px] font-bold">{totalBranches}</span>
        </div>
        <div className="flex flex-col gap-0.5 rounded-[var(--r-md)] border border-border bg-card px-3 py-2 shadow-[var(--shadow-card)]">
          <span className="text-[10.5px] text-muted-foreground">{"樣本足夠"}</span>
          <span className="num text-[15px] font-bold">{enoughSampleCount}</span>
        </div>
        <div className="flex flex-col gap-0.5 rounded-[var(--r-md)] border border-border bg-card px-3 py-2 shadow-[var(--shadow-card)]">
          <span className="text-[10.5px] text-muted-foreground">{"可追蹤"}</span>
          <span className="num text-[15px] font-bold">{trackIndex.length}</span>
        </div>
        <div className="flex flex-col gap-0.5 rounded-[var(--r-md)] border border-border bg-card px-3 py-2 shadow-[var(--shadow-card)]">
          <span className="text-[10.5px] text-muted-foreground">{"資料起始"}</span>
          <span className="num text-[13px] font-bold">{"2026-07-07"}</span>
        </div>
      </div>

      {hasDataWarning && (
        <Alert className="mb-4 bg-card">
          <AlertDescription className="flex flex-wrap items-baseline gap-2.5 text-[13px] text-foreground">
            <span className="shrink-0 rounded-md bg-warn/15 px-2 py-0.5 text-[11.5px] font-bold tracking-[0.3px] text-warn">{"樣本不足"}</span>
            <span>{"由於系統自 2026-07-07 才開始收集免費分點資料，部分分點的歷史交易筆數過少，導致無法計算勝率。需待資料持續累積數週。"}</span>
          </AlertDescription>
        </Alert>
      )}

      {/* IA-3: Filter UI */}
      {tab === "rankings" && (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <div className="relative flex items-center">
            <Search size={13} className="absolute left-2.5 text-muted-foreground" />
            <input
              type="text"
              value={filterSearch}
              onChange={e => setFilterSearch(e.target.value)}
              placeholder={"搜尋分點"}
              aria-label={"分點名稱搜尋"}
              className="h-8 rounded-md border border-border bg-card pl-7 pr-2.5 text-[12.5px] text-foreground placeholder:text-muted-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>
          <button
            onClick={() => setFilterTrackable(v => !v)}
            className={cn(
              "rounded-full px-3 py-1 text-[12px] font-semibold transition-colors",
              filterTrackable
                ? "bg-[color:var(--ink-2)] text-[color:var(--bg-1)]"
                : "bg-muted text-muted-foreground hover:bg-secondary",
            )}
            aria-pressed={filterTrackable}
          >
            {"可追蹤"}
          </button>
          <button
            onClick={() => setFilterEnough(v => !v)}
            className={cn(
              "rounded-full px-3 py-1 text-[12px] font-semibold transition-colors",
              filterEnough
                ? "bg-[color:var(--ink-2)] text-[color:var(--bg-1)]"
                : "bg-muted text-muted-foreground hover:bg-secondary",
            )}
            aria-pressed={filterEnough}
          >
            {"樣本足夠"}
          </button>
          <button
            onClick={() => setFilterDaytrade(v => v === "exclude" ? "all" : "exclude")}
            className={cn(
              "rounded-full px-3 py-1 text-[12px] font-semibold transition-colors",
              filterDaytrade === "exclude"
                ? "bg-down/15 text-down"
                : "bg-muted text-muted-foreground hover:bg-secondary",
            )}
            aria-pressed={filterDaytrade === "exclude"}
          >
            {"排除雔日沖"}
          </button>
          {(filterSearch || filterTrackable || filterEnough || filterDaytrade !== "all") && (
            <button
              onClick={() => { setFilterSearch(""); setFilterTrackable(false); setFilterEnough(false); setFilterDaytrade("all"); }}
              className="rounded-full px-3 py-1 text-[12px] text-muted-foreground hover:bg-secondary"
            >
              {"清除"}
            </button>
          )}
          <span className="ml-auto text-[11.5px] text-muted-foreground">
            {"顯示"} {filteredRankings.length} {"個"}
          </span>
        </div>
      )}

      <div className="my-1.5 mb-3 flex items-center gap-2.5">
        <div role="tablist" className="flex max-w-full gap-0.5 overflow-x-auto rounded-full border border-border bg-card p-[3px] whitespace-nowrap">
          {TABS.map((t) => (
            <TabPill key={t.key} active={tab === t.key} onClick={() => { setTab(t.key); setTrackOpen(false); }} title={t.hint} icon={t.icon} label={t.label} />
          ))}
        </div>
        <span className="hidden text-xs text-muted-foreground lg:inline">{TABS.find((t) => t.key === tab)?.hint}</span>
      </div>

      {tab === "rankings" && (() => {
        const openTrack = (name: string) => {
          setTrackBranch(name);
          setTrackOpen(true);
        };

        const renderCard = (r: Ranking) => {
          const isTrackable = trackNames.has(r.branch_name);
          const isActive = trackBranch === r.branch_name;
          return (
            <button
              key={r.branch_name}
              onClick={() => {
                setTrackBranch(r.branch_name);
                if (!isActive) {
                  // 手機點擊且未打開時，打開下鑽詳情
                  setTrackOpen(true);
                }
              }}
              aria-label={`${"查看"} ${r.branch_name} ${"的近 N 日買賣超明細"}`}
              className="block w-full min-h-11 rounded-[var(--r-lg)] p-0 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <RankCard r={r} trackable={isTrackable} active={isActive} />
            </button>
          );
        };

        return (
          <div className="grid grid-cols-1 md:grid-cols-[380px_1fr] gap-5 items-start pb-7">
            {/* 左側：分點列表（手機上當詳情被打開時隱藏） */}
            <div className={cn("flex flex-col gap-4 w-full md:max-h-[85vh] md:overflow-y-auto pr-1 md:scrollbar-thin", trackOpen && "hidden md:flex")}>
              {filteredRankings.length === 0 && (
                <div className="py-[46px] text-center text-sm text-muted-foreground">
                  {"沒有符合筛選條件的分點。調整筛選條件或清除搜尋。"}
                </div>
              )}
              {filteredMain.length > 0 && (
                <div className="flex flex-col gap-2.5">
                  {filteredMain.map(renderCard)}
                </div>
              )}

              {filteredDaytrade.length > 0 && (
                <div className="flex flex-col gap-2.5 mt-2">
                  <div className="flex items-baseline gap-2 px-1">
                    <h2 className="text-[14px] font-semibold text-down">{"雔日沖分點"}</h2>
                    <span className="text-[11px] text-muted-foreground">{"反指標/風險訊號"}</span>
                  </div>
                  <div className="flex flex-col gap-2.5">
                    {filteredDaytrade.map(renderCard)}
                  </div>
                </div>
              )}
            </div>

            {/* 右側：詳情面板（手機上當詳情未被打開時隱藏） */}
            <div className={cn("flex-1 w-full", !trackOpen && "hidden md:block")}>
              {trackBranch ? (
                trackNames.has(trackBranch) ? (
                  <BranchTrackView
                    index={trackIndex}
                    branchName={trackBranch}
                    onBack={() => setTrackOpen(false)}
                    onSelectBranch={setTrackBranch}
                    hideBack={true} // 桌機版隱藏返回按鈕，手機版則在下面以 portal/單獨 state 來展示
                  />
                ) : (
                  <NoTrackDetailPanel branchName={trackBranch} />
                )
              ) : (
                <div className="flex h-full min-h-[300px] flex-col items-center justify-center rounded-[var(--r-lg)] border border-border bg-card p-6 text-center text-muted-foreground shadow-[var(--shadow-card)]">
                  {"請選取左剗分點以查看買賣明細"}
                </div>
              )}
            </div>

            {/* 手機版專屬下鑽蓋屏（只在手機且 trackOpen 被打開時，多渲染一個帶有返回鍵的浮動詳情以保證返回路徑清晰） */}
            {trackOpen && trackBranch && trackNames.has(trackBranch) && (
              <div className="md:hidden fixed inset-0 z-50 overflow-y-auto bg-background p-4 animate-in slide-in-from-right duration-200">
                <BranchTrackView
                  index={trackIndex}
                  branchName={trackBranch}
                  onBack={() => setTrackOpen(false)}
                  onSelectBranch={setTrackBranch}
                  hideBack={false} // 手機版顯示返回按鈕
                />
              </div>
            )}
            {trackOpen && trackBranch && !trackNames.has(trackBranch) && (
              <div className="md:hidden fixed inset-0 z-50 flex flex-col gap-4 bg-background p-4 animate-in slide-in-from-right duration-200">
                <button
                  onClick={() => setTrackOpen(false)}
                  className="inline-flex min-h-11 w-fit items-center gap-1.5 rounded-full border border-border bg-card px-3 text-[13.5px] font-semibold text-muted-foreground transition-colors hover:text-foreground"
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="mr-1">
                    <path d="M19 12H5M12 19l-7-7 7-7" />
                  </svg>
                  {"返回"}
                </button>
                <div className="flex-1">
                  <NoTrackDetailPanel branchName={trackBranch} />
                </div>
              </div>
            )}
          </div>
        );
      })()}

      {tab === "warrant" && (() => {
        const data = warrantBranches[warrantTimeframe] || [];
        
        let content;
        if (data.length === 0) {
          content = (
            <div className="py-[46px] text-center text-sm text-muted-foreground">
              此區間內無淨買賣超 500 萬以上之權證大戶
            </div>
          );
        } else if (viewMode === "by_stock") {
          const grouped = data.reduce((acc, curr) => {
            if (!acc[curr.underlying_id]) {
              acc[curr.underlying_id] = {
                stockId: curr.underlying_id,
                stockName: curr.underlying_name,
                totalAmt: 0,
                branches: []
              };
            }
            acc[curr.underlying_id].totalAmt += curr.net_amount;
            acc[curr.underlying_id].branches.push(curr);
            return acc;
          }, {} as Record<string, { stockId: string, stockName: string, totalAmt: number, branches: WarrantBranch[] }>);
          
          const sortedStocks = Object.values(grouped).sort((a, b) => Math.abs(b.totalAmt) - Math.abs(a.totalAmt));
          sortedStocks.forEach(s => s.branches.sort((a, b) => Math.abs(b.net_amount) - Math.abs(a.net_amount)));
          
          content = (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 items-start">
              {sortedStocks.map(s => (
                <StockGroupCard key={s.stockId} stockId={s.stockId} stockName={s.stockName} totalAmt={s.totalAmt} branches={s.branches} />
              ))}
            </div>
          );
        } else {
          const grouped = data.reduce((acc, curr) => {
            if (!acc[curr.branch_name]) {
              acc[curr.branch_name] = {
                branchName: curr.branch_name,
                totalAmt: 0,
                stocks: []
              };
            }
            acc[curr.branch_name].totalAmt += curr.net_amount;
            acc[curr.branch_name].stocks.push(curr);
            return acc;
          }, {} as Record<string, { branchName: string, totalAmt: number, stocks: WarrantBranch[] }>);
          
          const sortedBranches = Object.values(grouped).sort((a, b) => Math.abs(b.totalAmt) - Math.abs(a.totalAmt));
          sortedBranches.forEach(b => b.stocks.sort((a, b) => Math.abs(b.net_amount) - Math.abs(a.net_amount)));

          content = (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 items-start">
              {sortedBranches.map(b => (
                <BranchGroupCard key={b.branchName} branchName={b.branchName} totalAmt={b.totalAmt} stocks={b.stocks} />
              ))}
            </div>
          );
        }

        return (
          <div className="flex flex-col gap-4 pb-7 animate-in fade-in duration-300">
            <div className="flex flex-col sm:flex-row justify-between items-center gap-3 mb-4">
              <div className="flex bg-background/80 p-1.5 rounded-full border border-border/40 shadow-inner overflow-x-auto max-w-full">
                {[
                  { k: "1d", l: "近 1 日" },
                  { k: "2d", l: "近 2 日" },
                  { k: "5d", l: "近 5 日" },
                  { k: "30d", l: "近 30 日" },
                  { k: "120d", l: "近 120 日" }
                ].map(t => (
                  <button
                    key={t.k}
                    onClick={() => setWarrantTimeframe(t.k as any)}
                    className={cn(
                      "px-4 py-1.5 rounded-full text-[13px] font-medium transition-all duration-300 whitespace-nowrap",
                      warrantTimeframe === t.k 
                        ? "bg-secondary text-foreground shadow-sm ring-1 ring-border/60" 
                        : "text-muted-foreground hover:text-foreground hover:bg-secondary/50"
                    )}
                  >
                    {t.l}
                  </button>
                ))}
              </div>
              <div className="flex bg-background/80 p-1.5 rounded-full border border-border/40 shadow-inner">
                <button
                  onClick={() => setViewMode("by_stock")}
                  className={cn(
                    "px-4 py-1.5 rounded-full text-[13px] font-medium transition-all duration-300 flex items-center gap-1.5",
                    viewMode === "by_stock" 
                      ? "bg-secondary text-foreground shadow-sm ring-1 ring-border/60" 
                      : "text-muted-foreground hover:text-foreground hover:bg-secondary/50"
                  )}
                >
                  <Building2 size={16} /> 依標的
                </button>
                <button
                  onClick={() => setViewMode("by_branch")}
                  className={cn(
                    "px-4 py-1.5 rounded-full text-[13px] font-medium transition-all duration-300 flex items-center gap-1.5",
                    viewMode === "by_branch" 
                      ? "bg-secondary text-foreground shadow-sm ring-1 ring-border/60" 
                      : "text-muted-foreground hover:text-foreground hover:bg-secondary/50"
                  )}
                >
                  <User size={16} /> 依分點
                </button>
              </div>
            </div>
            {content}
          </div>
        );
      })()}

      {tab === "today" && (
        <div className="flex flex-col gap-6 pb-7">
          <ConcentrationTab radar={radar} />
          
          <div className="mb-[-12px] flex items-baseline gap-2">
            <h2 className="text-[15px] font-semibold text-foreground">分點今日買超</h2>
          </div>
          {Object.entries(today).length === 0 && <div className="py-[46px] text-center text-sm text-muted-foreground">今日無追蹤分點的買超紀錄</div>}
          {Object.entries(today).map(([branchName, trades]) => (
            <div key={branchName} className="rounded-[var(--r-lg)] border border-border bg-card p-4 shadow-[var(--shadow-card)]">
              <div className="mb-3 flex items-center justify-between border-b border-border pb-3">
                <span className="text-lg font-semibold text-foreground">{branchName}</span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-[13px]">
                  <thead>
                    <tr>
                      <th className="px-2 py-2 text-left font-semibold text-muted-foreground">股票</th>
                      <th className="px-2 py-2 text-right font-semibold text-muted-foreground">買超</th>
                      <th className="px-2 py-2 text-right font-semibold text-muted-foreground">淨額</th>
                      <th className="px-2 py-2 text-right font-semibold text-muted-foreground">佔比</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.map((t) => (
                      <tr
                        key={t.stock_id}
                        onClick={() => { window.location.href = `/stock?id=${t.stock_id}`; }}
                        className="num cursor-pointer border-t border-[color:var(--line)] transition-colors duration-200 hover:bg-secondary"
                      >
                        <td className="px-2 py-2.5 text-left font-sans">
                          <a href={`/stock?id=${t.stock_id}`} onClick={(e) => e.stopPropagation()} className="no-underline">
                            <span className="text-foreground">{t.stock_name}</span> <span className="text-xs text-muted-foreground">{t.stock_id}</span>
                          </a>
                        </td>
                        <td className="px-2 py-2.5 text-right whitespace-nowrap text-up">{t.buy_lots}</td>
                        <td className={cn("px-2 py-2.5 text-right whitespace-nowrap", t.net_lots > 0 ? "text-up" : "text-down")}>
                          {t.net_lots > 0 ? "+" : ""}{t.net_lots}
                        </td>
                        <td className="px-2 py-2.5 text-right whitespace-nowrap text-xs text-[color:var(--ink-2)]">{t.pct}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
