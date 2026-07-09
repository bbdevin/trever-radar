"use client";

import { useEffect, useState } from "react";
import { Search, Info, TrendingUp, TrendingDown, Building2, User } from "lucide-react";
import { IconFlame, IconTrend, IconZap } from "@/components/Icons";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
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
};

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

const TABS = [
  { key: "rankings", label: "排行榜", hint: "分點操作勝率與可信度排行", icon: IconFlame },
  { key: "today", label: "今日動向", hint: "追蹤分點於最近交易日的買超明細", icon: IconZap },
  { key: "warrant", label: "權證大戶", hint: "追蹤分點針對單一標的之多檔權證，累計買賣超達 500 萬的動向", icon: IconTrend },
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
                className="px-3 py-2.5 flex items-center justify-between text-left focus:outline-none"
                onClick={() => setExpandedBranch(isExpanded ? null : b.branch_name)}
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
                className="px-3 py-2.5 flex items-center justify-between text-left focus:outline-none"
                onClick={() => setExpandedStock(isExpanded ? null : s.underlying_id)}
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
  const [tab, setTab] = useState<"rankings" | "today" | "warrant">("rankings");
  const [rankings, setRankings] = useState<Ranking[] | null>(null);
  const [today, setToday] = useState<TodayMovements | null>(null);
  const [warrantBranches, setWarrantBranches] = useState<Record<string, WarrantBranch[]>>({
    "1d": [], "2d": [], "5d": [], "30d": [], "120d": []
  });
  const [warrantTimeframe, setWarrantTimeframe] = useState<"1d" | "2d" | "5d" | "30d" | "120d">("1d");
  const [viewMode, setViewMode] = useState<"by_stock" | "by_branch">("by_stock");
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch("/data/branches/rankings.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setRankings)
      .catch(() => setError(true));

    fetch("/data/branches/today.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setToday)
      .catch(() => setError(true));

    fetch("/data/branches/warrant_branches.json")
      .then((r) => (r.ok ? r.json() : { "1d": [], "2d": [], "5d": [], "30d": [], "120d": [] }))
      .then(setWarrantBranches)
      .catch(() => {});
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
  if (!rankings || !today) return <LoadingSkeleton />;

  const hasDataWarning = rankings.some((r) => r.win_rate === null);

  return (
    <>
      <div className="my-3.5 flex gap-2.5">
        <div className="flex flex-col gap-0.5 rounded-[var(--r-md)] border border-border bg-card p-3 shadow-[var(--shadow-card)]">
          <span className="text-[11.5px] text-muted-foreground">資料狀態</span>
          <span className="num text-[17px] font-bold">追蹤 {rankings.length} 個分點</span>
        </div>
      </div>

      {hasDataWarning && (
        <Alert className="mb-4 bg-card">
          <AlertDescription className="flex flex-wrap items-baseline gap-2.5 text-[13px] text-foreground">
            <span className="shrink-0 rounded-md bg-warn/15 px-2 py-0.5 text-[11.5px] font-bold tracking-[0.3px] text-warn">樣本不足</span>
            <span>由於系統自 2026-07-07 才開始收集免費分點資料，部分分點的歷史交易筆數過少，導致無法計算勝率。需待資料持續累積數週。</span>
          </AlertDescription>
        </Alert>
      )}

      <div className="my-1.5 mb-3 flex items-center gap-2.5">
        <div role="tablist" className="flex max-w-full gap-0.5 overflow-x-auto rounded-full border border-border bg-card p-[3px] whitespace-nowrap">
          {TABS.map((t) => (
            <TabPill key={t.key} active={tab === t.key} onClick={() => setTab(t.key)} title={t.hint} icon={t.icon} label={t.label} />
          ))}
        </div>
        <span className="hidden text-xs text-muted-foreground lg:inline">{TABS.find((t) => t.key === tab)?.hint}</span>
      </div>

      {tab === "rankings" && (
        <div className="grid grid-cols-1 gap-2.5 pb-7 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {rankings.map((r) => (
            <div key={r.branch_name} className="flex flex-col gap-3 rounded-[var(--r-lg)] border border-border bg-card p-3.5 shadow-[var(--shadow-card)]">
              <div className="flex items-center justify-between">
                <h3 className="text-lg text-foreground">{r.branch_name}</h3>
                {r.is_daytrade === 1 && <span className="rounded-md bg-warn/10 px-2 py-0.5 text-[11.5px] font-bold text-warn">疑似隔日沖</span>}
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <div className="text-xs text-muted-foreground">勝率 (5日)</div>
                  <div className={cn("text-lg font-semibold", r.win_rate ? (r.win_rate > 50 ? "text-up" : "text-down") : "text-[color:var(--ink-2)]")}>
                    {r.win_rate ? `${r.win_rate.toFixed(1)}%` : "-"}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">平均報酬 (5日)</div>
                  <div className={cn("text-lg font-semibold", r.avg_ret5 ? (r.avg_ret5 > 0 ? "text-up" : "text-down") : "text-[color:var(--ink-2)]")}>
                    {r.avg_ret5 ? `${r.avg_ret5.toFixed(1)}%` : "-"}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">交易筆數</div>
                  <div className="num text-foreground">{r.samples}</div>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">可信度分數</div>
                  <div className="num text-[color:var(--accent-2)]">{r.rank_score}</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

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
          {Object.entries(today).length === 0 && <div className="py-[46px] text-center text-sm text-muted-foreground">今日無追蹤分點的買超紀錄</div>}
          {Object.entries(today).map(([branchName, trades]) => (
            <div key={branchName} className="rounded-[var(--r-lg)] border border-border bg-card p-4 shadow-[var(--shadow-card)]">
              <div className="mb-3 flex items-center justify-between border-b border-border pb-3">
                <span className="text-lg font-semibold text-foreground">{branchName}</span>
              </div>
              <div className="grid gap-2">
                {trades.map((t) => (
                  <a
                    href={`/stock?id=${t.stock_id}`}
                    key={t.stock_id}
                    className="grid grid-cols-[2fr_1fr_1fr_1fr] items-center gap-2 rounded-md bg-secondary px-2 py-1.5 no-underline"
                  >
                    <div>
                      <span className="text-foreground">{t.stock_name}</span> <span className="text-xs text-muted-foreground">{t.stock_id}</span>
                    </div>
                    <div className="text-right text-up">買 {t.buy_lots}</div>
                    <div className={cn("text-right", t.net_lots > 0 ? "text-up" : "text-down")}>淨 {t.net_lots}</div>
                    <div className="text-right text-xs text-[color:var(--ink-2)]">佔比 {t.pct}%</div>
                  </a>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
