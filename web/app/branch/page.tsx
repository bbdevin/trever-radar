"use client";

import { useEffect, useState } from "react";
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

function WarrantBranchCard({ m }: { m: WarrantBranch }) {
  const [expanded, setExpanded] = useState(false);
  const hasBreakdown = m.breakdown && m.breakdown.length > 0;

  return (
    <div className="flex flex-col rounded-[var(--r-lg)] border border-border bg-card/60 backdrop-blur-md shadow-sm hover:shadow-[var(--shadow-card)] transition-all overflow-hidden">
      {/* 觸發區塊 */}
      <button 
        className="p-4 flex flex-col gap-2 text-left w-full focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex justify-between items-start w-full">
          <div className="font-bold text-foreground text-lg">{m.branch_name}</div>
          <div className={cn("px-2 py-1 rounded-md font-bold text-[11.5px]", m.net_amount > 0 ? "bg-up/15 text-up" : "bg-down/15 text-down")}>
            {m.net_amount > 0 ? "大買" : "大賣"}
          </div>
        </div>
        <div className="flex justify-between items-end mt-2 w-full">
          <a href={`/stock?id=${m.underlying_id}`} className="flex items-baseline gap-1.5 hover:opacity-80 z-10 relative" onClick={(e) => e.stopPropagation()}>
            <span className="text-foreground font-semibold">{m.underlying_name}</span>
            <span className="text-xs text-muted-foreground">{m.underlying_id}</span>
          </a>
          <div className="flex items-center gap-2">
            <div className={cn("text-[17px] font-bold num tracking-tight", m.net_amount > 0 ? "text-up" : "text-down")}>
              {(Math.abs(m.net_amount) / 10000).toLocaleString('zh-TW', { maximumFractionDigits: 0 })} 萬
            </div>
          </div>
        </div>
        {hasBreakdown && (
          <div className="w-full flex justify-center mt-2 opacity-50 hover:opacity-100 transition-opacity">
            <div className={cn("h-1 w-8 rounded-full bg-border transition-transform duration-300", expanded ? "bg-foreground" : "")} />
          </div>
        )}
      </button>

      {/* 展開明細 */}
      {hasBreakdown && (
        <div className={cn(
          "grid transition-[grid-template-rows] duration-300 ease-out", 
          expanded ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
        )}>
          <div className="overflow-hidden bg-secondary/40 border-t border-border">
            <div className="p-3 flex flex-col gap-1.5">
              <div className="grid grid-cols-[1.5fr_1fr_1fr] items-center px-2 py-1 pb-1.5 text-[11.5px] font-semibold text-muted-foreground border-b border-border">
                <div>權證 (張數)</div>
                <div className="text-right">淨買賣金額</div>
                <div className="text-right">佔總額</div>
              </div>
              {m.breakdown?.map(b => (
                <div key={b.warrant_id} className="grid grid-cols-[1.5fr_1fr_1fr] items-center px-2 py-1.5 rounded-md hover:bg-secondary transition-colors">
                  <div className="flex flex-col">
                    <div className="flex items-baseline gap-1">
                      <span className="text-foreground text-[13px]">{b.warrant_name}</span>
                      <span className={cn("text-[10px] px-1 rounded-sm", b.kind === "call" ? "bg-up/15 text-up" : "bg-down/15 text-down")}>
                        {b.kind === "call" ? "購" : "售"}
                      </span>
                    </div>
                    <span className="text-xs text-muted-foreground">淨 {b.net_lots > 0 ? "+" : ""}{b.net_lots} 張</span>
                  </div>
                  <div className={cn("text-right num font-semibold text-[13.5px]", b.net_amount > 0 ? "text-up" : "text-down")}>
                    {(Math.abs(b.net_amount) / 10000).toLocaleString('zh-TW', { maximumFractionDigits: 1 })} 萬
                  </div>
                  <div className="text-right num text-xs text-muted-foreground">
                    {Math.round(Math.abs(b.net_amount) / Math.abs(m.net_amount) * 100)}%
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function BranchPage() {
  const [tab, setTab] = useState<"rankings" | "today" | "warrant">("rankings");
  const [rankings, setRankings] = useState<Ranking[] | null>(null);
  const [today, setToday] = useState<TodayMovements | null>(null);
  const [warrantBranches, setWarrantBranches] = useState<Record<string, WarrantBranch[]>>({
    "1d": [], "2d": [], "5d": [], "30d": []
  });
  const [warrantTimeframe, setWarrantTimeframe] = useState<"1d" | "2d" | "5d" | "30d">("5d");
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
      .then((r) => (r.ok ? r.json() : { "1d": [], "2d": [], "5d": [], "30d": [] }))
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

      {tab === "warrant" && (
        <div className="flex flex-col gap-4 pb-7 animate-in fade-in duration-300">
          <div className="flex justify-center mb-2">
            <div className="flex bg-secondary p-1 rounded-full border border-border shadow-inner">
              {(["1d", "2d", "5d", "30d"] as const).map(tf => (
                <button
                  key={tf}
                  onClick={() => setWarrantTimeframe(tf)}
                  className={cn(
                    "px-4 py-1.5 rounded-full text-[13px] font-semibold transition-all",
                    warrantTimeframe === tf ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  近 {tf.replace('d', ' 日')}
                </button>
              ))}
            </div>
          </div>
          
          {warrantBranches[warrantTimeframe]?.length === 0 && (
            <div className="py-[46px] text-center text-sm text-muted-foreground">
              此區間內無淨買賣超 500 萬以上之權證分點大戶
            </div>
          )}
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 items-start">
            {warrantBranches[warrantTimeframe]?.map((m, idx) => (
              <WarrantBranchCard key={`${m.branch_name}-${m.underlying_id}-${idx}`} m={m} />
            ))}
          </div>
        </div>
      )}

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
