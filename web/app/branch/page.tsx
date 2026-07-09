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

type WarrantMover = {
  branch_name: string;
  warrant_id: string;
  warrant_name: string;
  kind: "call" | "put";
  underlying_id: string | null;
  underlying_name: string | null;
  net_lots: number;
  buy_lots: number;
  active_days: number;
  last_date: string;
};

const TABS = [
  { key: "rankings", label: "排行榜", hint: "分點操作勝率與可信度排行", icon: IconFlame },
  { key: "today", label: "今日動向", hint: "追蹤分點於最近交易日的買超明細", icon: IconZap },
  { key: "warrant", label: "權證分點", hint: "近40個交易日對單一權證淨買 ≥300 張的分點(多為發行商造市,重點看非發行商)", icon: IconTrend },
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

export default function BranchPage() {
  const [tab, setTab] = useState<"rankings" | "today" | "warrant">("rankings");
  const [rankings, setRankings] = useState<Ranking[] | null>(null);
  const [today, setToday] = useState<TodayMovements | null>(null);
  const [movers, setMovers] = useState<WarrantMover[]>([]);
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

    fetch("/data/branches/warrant_movers.json")
      .then((r) => (r.ok ? r.json() : []))
      .then(setMovers)
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
        <div className="flex flex-col gap-2 pb-7">
          {movers.length === 0 && (
            <div className="py-[46px] text-center text-sm text-muted-foreground">
              近期無權證分點大額淨買紀錄(資料自每日成交前15大上市權證累積;上櫃權證無免費來源)
            </div>
          )}
          {movers.map((m) => (
            <div
              key={`${m.branch_name}-${m.warrant_id}`}
              className="grid grid-cols-[1.2fr_1.6fr_1fr_1fr] items-center gap-2.5 rounded-[var(--r-lg)] border border-border bg-card px-3.5 py-2.5 shadow-[var(--shadow-card)]"
            >
              <div className="font-semibold text-foreground">{m.branch_name}</div>
              <div>
                <a href={m.underlying_id ? `/stock?id=${m.underlying_id}` : "#"} className="text-foreground hover:underline">
                  {m.underlying_name ?? "—"}
                </a>{" "}
                <span className="text-xs text-muted-foreground">
                  {m.warrant_name}({m.warrant_id})
                </span>{" "}
                <span className={cn("rounded-md px-1.5 py-px text-[10.5px]", m.kind === "call" ? "text-up bg-up/15" : "text-down bg-down/15")}>
                  {m.kind === "call" ? "認購" : "認售"}
                </span>
              </div>
              <div className="num text-right font-bold text-up">淨買 {m.net_lots.toLocaleString("zh-TW")} 張</div>
              <div className="text-right text-xs text-muted-foreground">
                {m.active_days} 個交易日 · 最近 {m.last_date}
              </div>
            </div>
          ))}
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
