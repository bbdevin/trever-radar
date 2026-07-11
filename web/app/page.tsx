"use client";

import { useEffect, useMemo, useState } from "react";
import { Clock } from "lucide-react";
import { IconFlame, IconPulse, IconRadar, IconTrend, IconTrendDown, IconZap, IconStar } from "@/components/Icons";
import MoneyFlow from "@/components/MoneyFlow";
import StockCard from "@/components/StockCard";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { useSession, signInWithGoogle } from "@/lib/useSession";
import { cn } from "@/lib/utils";
import type { ListKey, MetaJson, RadarJson } from "@/lib/types";
import { SOURCE_LABEL, fmtE8 } from "@/lib/format";

// "mark" is the UI tab key for strategies; not a radar.lists key
type TabKey = ListKey | "mark";

const TABS: { key: TabKey; label: string; hint: string; icon: typeof IconFlame }[] = [
  { key: "score", label: "\u7db1\u5408", hint: "\u76e4\u5f8c\u7db1\u5408\u5206\u6578:\u5206\u9ede/\u6b0a\u8b49/\u6280\u8853/\u6cd5\u4eba\u52a0\u6b0a\u2212\u98a8\u96aa\u6263\u5206,\u226565 \u70ba\u89c0\u5bdf\u9580\u6ebb", icon: IconRadar },
  { key: "mark", label: "\u7b56\u7565", hint: "\u9032\u968e\u91cf\u5316\u9078\u80a1\uff0c\u6db5\u84cb\u6280\u8853\u9762\u8207\u7c4c\u78bc\u9762\u7b49\u591a\u7a2e\u7b56\u7565", icon: IconStar },
  { key: "hot", label: "\u71b1\u9580", hint: "\u6210\u4ea4\u91d1\u984d\u6700\u5927", icon: IconFlame },
  { key: "surge", label: "\u7206\u91cf", hint: "\u91cf\u6bd4 = \u4eca\u65e5\u91cf/20\u65e5\u5747\u91cf,\u22651.5 \u4e14\u91d1\u984d \u22651\u5104", icon: IconZap },
  { key: "strong", label: "\u5f37\u52e2", hint: "\u6f32\u5e45\u6392\u5e8f,\u91d1\u984d \u22651\u5104", icon: IconTrend },
  { key: "weak", label: "\u5f31\u52e2", hint: "\u8dcc\u5e45\u6392\u5e8f,\u91d1\u984d \u22651\u5104\u2014\u2014\u770b\u8cc7\u91d1\u9003\u96e2\u8ab0", icon: IconTrendDown },
  { key: "warrant", label: "\u6b0a\u8b49", hint: "\u8a8d\u8cfc\u6b0a\u8b49\u6210\u4ea4\u91d1\u984d\u76f8\u5c0d20\u65e5\u5747\u503c\u653e\u5927", icon: IconPulse },
];

const STRATEGIES = [
  { key: "S1_REBOUND", label: "\u6f32\u505c\u4e8c\u6b21\u767c\u52d5", desc: "\u96d9\u8ecc\u689d\u4ef6\uff1a\u56b4\u8b39\u7248\u70ba\u8fd1 20 \u65e5\u66fe\u6f32\u505c\u3001MACD \u96f6\u8ef8\u4e0a\u9ec3\u91d1\u4ea4\u53c9\u30015 \u65e5\u5167\u7206\u91cf\uff082 \u500d\uff09\uff1b\u76f8\u8fd1\uff08\u653e\u5bec\uff09\u7248\u70ba\u8fd1 20 \u65e5\u66fe\u5927\u6f32 7%\u3001MACD \u4efb\u610f\u91d1\u53c9\u30015 \u65e5\u5167\u91cf\u589e 1.5 \u500d\u3002\u699c\u5167\u56b4\u8b39\u7248\u512a\u5148\u6392\u524d" },
  { key: "S2_BREAKOUT20", label: "20\u65e5\u7206\u91cf\u7a81\u7834", desc: "\u5275 20 \u65e5\u65b0\u9ad8\uff0c\u7576\u65e5\u7206\u91cf\u4e14\u6536\u7d05 K\uff0c\u4e2d\u9577\u671f\u5747\u7dda\u591a\u982d\u6392\u5217" },
  { key: "S3_MA_CONVERGE_BREAKOUT", label: "\u5747\u7dda\u7cfe\u7d50\u7a81\u7834", desc: "5/10/20 \u65e5\u5747\u7dda\u8ddd\u96e2\u6975\u8fd1\uff0c\u7576\u65e5\u5e36\u91cf\u9577\u7d05\u7a81\u7834\u7cfe\u7d50\u5340" },
  { key: "S4_VOLATILITY_CONTRACTION", label: "\u6ce2\u52d5\u6536\u6582\u7a51\u7834", desc: "\u8fd1 10 \u65e5\u5e03\u6797\u901a\u9053\u6975\u5ea6\u58d3\u7e2e\uff08\u5e36\u5bec < 8%\uff09\uff0c\u7576\u65e5\u5e36\u91cf\u7a81\u7834\u4e0a\u8ecc" },
  { key: "S5_PULLBACK_SUPPORT", label: "\u5f37\u52e2\u91cf\u7e2e\u56de\u8e29", desc: "\u8fd1\u671f\u5275\u9ad8\u5f8c\u56de\u6a94\uff0c\u91cf\u7e2e\u81f3\u6975\u81f4\u4e26\u65bc 10 \u65e5\u6216 20 \u65e5\u5747\u7dda\u7372\u5f97\u652f\u6491\u6536\u7d05" },
  { key: "S6_HIGH_BASE_BREAKOUT", label: "\u9ad8\u6a94\u5e73\u53f0\u7a51\u7834", desc: "\u5728 60 \u65e5\u9ad8\u9ede\u9644\u8fd1\u9ad8\u59ff\u614b\u6a6b\u76e4\u6574\u7406\uff0c\u7576\u65e5\u5e36\u91cf\u7a51\u7834\u7b2c\u578b\u4e0a\u7de3" },
  { key: "S7_MACD_ZERO_CROSS", label: "MACD\u96f6\u8ef8\u91d1\u53c9", desc: "MACD \u65bc\u96f6\u8ef8\u4e4b\u4e0a\u767c\u751f\u9ec3\u91d1\u4ea4\u53c9\uff0c\u4e14\u7576\u65e5\u5e36\u91cf\u6536\u7d05" },
  { key: "S8_GAP_BREAKOUT", label: "\u8df3\u7a7a\u4e0d\u56de\u88dc", desc: "\u767c\u751f\u5411\u4e0a\u8df3\u7a7a\u7f3a\u53e3\uff0c\u5f8c\u7e8c 3 \u65e5\u672a\u5c01\u9589\u7f3a\u53e3\u4e14\u91cf\u7e2e\u6574\u7406\u5f8c\u8f49\u5f37" },
  { key: "S9_MA5_TREND", label: "\u4e94\u65e5\u7dda\u5f37\u653b", desc: "\u80a1\u50f9\u6c3f 5 \u65e5\u7dda\u5f37\u52e2\u4e0a\u653b\uff0c\u672a\u66fe\u8dcc\u7834 5 \u65e5\u7dda\uff0c\u7576\u65e5\u91cf\u50f9\u914d\u5408\u5ef6\u7e8c\u5f37\u52e2" },
  { key: "S10_BOTTOM_MACD", label: "\u5e95\u90e8MACD\u8f49\u5f37", desc: "\u80a1\u50f9\u8655\u65bc\u9577\u671f\u4f4e\u6a94\u5340\uff0cMACD \u65bc\u96f6\u8ef8\u4e0b\u65b9\u9ec3\u91d1\u4ea4\u53c9\u4e14\u67f1\u72c0\u5716\u660e\u986f\u7ffb\u7d05" },
  { key: "S11_INSTI_BREAKOUT", label: "\u6cd5\u4eba\u9023\u8cb7\u7a51\u7834", desc: "\u5916\u8cc7\u6216\u6295\u4fe1\u9023\u7e8c 3 \u65e5\u8cb7\u8d85\uff0c\u914d\u5408\u6280\u8853\u9762\u7a51\u7834\u8f49\u5f37" },
  { key: "S12_BRANCH_ACCUMULATION", label: "\u5206\u9ede\u96c6\u4e2d\u672a\u767c\u52d5", desc: "\u4e3b\u529b\u5206\u9ede\u8cb7\u8d85\u6975\u5ea6\u96c6\u4e2d\uff08\u4f54\u6bd4 > 15% \u4e14\u500d\u589e\uff09\uff0c\u4f46\u80a1\u50f9\u5c1a\u672a\u660e\u986f\u5927\u6f32" },
  { key: "S13_SHORT_SQUEEZE", label: "\u878d\u5238\u56de\u88dc\u8ecd\u7a7a", desc: "\u878d\u5238\u9918\u984d\u8655\u65bc\u9ad8\u6a94\uff08> 1000 \u5f35\uff09\u4e14\u8fd1\u671f\u9023\u7e8c\u6e1b\u5c11\uff0c\u7576\u65e5\u5e36\u91cf\u9577\u7d05\u7a51\u7834" },
];

function LoadingSkeleton() {
  return (
    <>
      <div className="my-3.5 flex gap-2 overflow-x-auto">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-[52px] w-full min-w-[120px] shrink-0 rounded-[var(--r-md)]" />
        ))}
      </div>
      <Skeleton className="mb-3 h-[44px] rounded-[var(--r-md)]" />
      <div className="grid grid-cols-1 gap-2.5 pb-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <Skeleton key={i} className="h-[148px] rounded-[var(--r-lg)]" />
        ))}
      </div>
      <Skeleton className="mb-3.5 h-[180px] rounded-[var(--r-lg)]" />
    </>
  );
}

export default function RadarPage() {
  const [radar, setRadar] = useState<RadarJson | null>(null);
  const [meta, setMeta] = useState<MetaJson | null>(null);
  const [error, setError] = useState(false);
  const [tab, setTab] = useState<TabKey>("score");
  const [strategy, setStrategy] = useState<string>("S1_REBOUND");
  const [moneyFlowOpen, setMoneyFlowOpen] = useState(false);
  const { session, loading } = useSession();

  useEffect(() => {
    fetch("/data/radar.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setRadar)
      .catch(() => setError(true));
    fetch("/data/meta.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setMeta)
      .catch(() => {});
  }, []);

  const shown = useMemo(() => {
    if (!radar) return [];
    const byId = new Map(radar.stocks.map((s) => [s.id, s]));
    if (tab === "mark") {
      return (radar.strategies?.[strategy] ?? []).map((id) => byId.get(id)!).filter(Boolean);
    }
    return (radar.lists?.[tab] ?? []).map((id) => byId.get(id)!).filter(Boolean);
  }, [radar, tab, strategy]);

  if (error) {
    return (
      <div className="py-[46px] text-center text-sm text-muted-foreground">
        {"\u627e\u4e0d\u5230\u8cc7\u6599\u6a94\u3002\u8acb\u5148\u57f7\u884c\u7ba1\u7dda:"}
        <code className="rounded-md border border-border bg-card px-1.5 py-0.5 text-[12.5px] text-[color:var(--ink-2)]">
          python -m radar import-daily
        </code>{" "}
        {"\u518d"}{" "}
        <code className="rounded-md border border-border bg-card px-1.5 py-0.5 text-[12.5px] text-[color:var(--ink-2)]">
          python -m radar export-json
        </code>
      </div>
    );
  }
  if (!radar) return <LoadingSkeleton />;

  const FRESH_LABEL: Record<string, string> = {
    insti: "\u6cd5\u4eba", margin: "\u878d\u8cc7\u5238", warrant: "\u6b0a\u8b49", branch: "\u5206\u9ede",
  };
  const stale = Object.entries(radar.freshness ?? {})
    .filter(([k, v]) => k !== "quotes" && v.stale && v.date)
    .map(([k, v]) => ({ label: FRESH_LABEL[k] ?? k, date: v.date! }));

  return (
    <>
      {/* Compact Daily Brief */}
      <div className="my-3.5 grid auto-cols-[minmax(110px,1fr)] grid-flow-col gap-2 overflow-x-auto [scroll-snap-type:x_proximity] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <div className="flex snap-start flex-col gap-0.5 rounded-[var(--r-md)] border border-border bg-card px-3 py-2 shadow-[var(--shadow-card)]">
          <span className="text-[10.5px] text-muted-foreground">{"\u8cc7\u6599\u65e5"}</span>
          <span className="num text-[15px] font-bold">
            {radar.data_date}
            {stale.length > 0 && <span className="ml-1.5 text-[11px] font-medium text-warn">{"\u90e8\u5206\u5f85\u66f4\u65b0"}</span>}
          </span>
        </div>
        {radar.summary.map((m) => (
          <div
            key={m.market}
            className="flex snap-start flex-col gap-0.5 rounded-[var(--r-md)] border border-border bg-card px-3 py-2 shadow-[var(--shadow-card)]"
          >
            <span className="text-[10.5px] text-muted-foreground">{(SOURCE_LABEL[m.market] ?? m.market) + "\u6210\u4ea4"}</span>
            <span className="num text-[15px] font-bold">
              {fmtE8(m.turnover)}
              <span className="ml-1 text-[11px] font-medium text-[color:var(--ink-2)]">
                <span className="text-up">{"\u2191"}{m.up}</span>{" / "}<span className="text-down">{"\u2193"}{m.down}</span>
              </span>
            </span>
          </div>
        ))}
      </div>

      {stale.length > 0 && (
        <Alert className="mb-3 border-warn/30 bg-warn/5">
          <AlertDescription className="flex flex-wrap items-baseline gap-2.5 text-[13px] text-foreground">
            <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-warn/15 px-2 py-0.5 text-[11.5px] font-bold tracking-[0.3px] text-warn">
              <Clock size={12} strokeWidth={1.8} />
              {"\u5c1a\u672a\u66f4\u65b0"}
            </span>
            <span>
              {stale.map((s) => `${s.label}\u4eca\u65e5\u5c1a\u672a\u516c\u5e03,\u66ab\u7528 ${s.date}`).join("\uff1b")}
              {"(\u4f9d\u4ea4\u6613\u6240\u516c\u5e03\u6642\u9593\u5206\u6279\u81ea\u52d5\u66f4\u65b0)"}
            </span>
          </AlertDescription>
        </Alert>
      )}

      {/* F2: Daily summary text */}
      {(radar.summary_text?.length ?? 0) > 0 && (
        <div className="mb-3 flex flex-col gap-1 rounded-[var(--r-md)] border border-border bg-card px-3.5 py-2.5">
          {radar.summary_text!.map((s, i) => (
            <p key={i} className="text-[12.5px] leading-[1.5] text-muted-foreground">{s}</p>
          ))}
        </div>
      )}

      {/* Primary Queue: tabs + stock list */}
      <div className="my-1.5 mb-3 flex items-center gap-2.5">
        <div
          role="tablist"
          className="flex max-w-full gap-0.5 overflow-x-auto rounded-full border border-border bg-card p-[3px] whitespace-nowrap [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        >
          {TABS.map((t) => (
            <button
              key={t.key}
              role="tab"
              aria-selected={tab === t.key}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-[13.5px] font-semibold text-muted-foreground transition-colors",
                tab === t.key && "bg-muted text-foreground shadow-[inset_0_0_0_1px_var(--border-strong)]",
              )}
              onClick={() => setTab(t.key)}
              title={t.hint}
            >
              <t.icon size={15} className="opacity-85" />
              {t.label}
              {t.key !== "mark" && (
                <small className="num text-[11px] text-muted-foreground">{radar.lists?.[t.key]?.length ?? 0}</small>
              )}
            </button>
          ))}
        </div>
        <span className="hidden text-xs text-muted-foreground lg:inline">{TABS.find((t) => t.key === tab)?.hint}</span>
      </div>

      {tab === "mark" && (
        <div className="mb-4">
          <div className="flex flex-wrap gap-1.5">
            {STRATEGIES.map((st) => (
              <button
                key={st.key}
                onClick={() => setStrategy(st.key)}
                className={cn(
                  "rounded-md px-2.5 py-1 text-[12.5px] font-medium transition-colors",
                  strategy === st.key
                    ? "bg-[color:var(--ink-2)] text-[color:var(--bg-1)] shadow-[0_1px_2px_rgba(0,0,0,0.1)]"
                    : "bg-muted text-muted-foreground hover:bg-muted/80",
                )}
              >
                {st.label}
                <span
                  className={cn(
                    "ml-1.5 rounded px-1 py-0.5 text-[10px]",
                    strategy === st.key ? "bg-[color:var(--bg-1)]/20" : "bg-background",
                  )}
                >
                  {radar.strategies?.[st.key]?.length ?? 0}
                </span>
              </button>
            ))}
          </div>
          <div className="mt-2.5 flex items-start gap-2 rounded-md border border-border bg-muted/30 px-3 py-2 text-[12.5px] text-muted-foreground">
            <IconStar size={14} className="mt-[2px] shrink-0 opacity-70" />
            <span>{STRATEGIES.find((s) => s.key === strategy)?.desc}</span>
          </div>
        </div>
      )}

      {tab === "mark" && !loading && !session ? (
        <div className="flex flex-col items-center gap-4 py-[46px] text-center text-sm text-muted-foreground">
          <span>{"\u9032\u968e\u7b56\u7565\u699c\u55ae\u70ba\u6703\u54e1\u5c08\u5c6c\u529f\u80fd\uff0c\u8acb\u5148\u767b\u5165 Google \u5e33\u865f\u89e3\u9396\u3002"}</span>
          <button
            onClick={signInWithGoogle}
            className="rounded-md border border-border bg-card px-4 py-2 text-sm text-foreground"
          >
            {"\u4f7f\u7528 Google \u767b\u5165"}
          </button>
        </div>
      ) : shown.length === 0 ? (
        <div className="mx-auto max-w-md py-[46px] text-center text-sm leading-relaxed text-muted-foreground">
          {tab === "score" || tab === "mark"
            ? "\u4eca\u65e5\u7121\u9054\u9580\u6ebb\u7684\u6a19\u7684\u3002\u5be7\u7f3a\u52ff\u6feb\u662f\u8a2d\u8a08\u539f\u5247\u2014\u2014\u6c92\u6709\u7b26\u5408\u689d\u4ef6\u6642\u4e0d\u786c\u6e4a,\u4e5f\u53ef\u80fd\u662f\u76e4\u5f8c\u5206\u6578\u5c1a\u672a\u66f4\u65b0\u3002"
            : "\u4eca\u65e5\u6b64\u699c\u7121\u7b26\u5408\u689d\u4ef6\u7684\u6a19\u7684,\u6216\u8a72\u985e\u8cc7\u6599\u5c1a\u672a\u66f4\u65b0\u3002\u7a0d\u5f8c\u56de\u4f86\u518d\u770b,\u7cfb\u7d71\u6703\u4f9d\u4ea4\u6613\u6240\u516c\u5e03\u6642\u9593\u5206\u6279\u66f4\u65b0\u3002"}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-2.5 pb-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {shown.map((s, i) => (
            <StockCard key={s.id} s={s} index={i} />
          ))}
        </div>
      )}

      {/* Context: MoneyFlow collapsible */}
      <div className="mb-4">
        <button
          className="flex w-full items-center justify-between rounded-[var(--r-md)] border border-border bg-card px-4 py-2.5 text-left text-[13.5px] font-semibold text-foreground transition-colors hover:border-[color:var(--border-strong)] hover:bg-secondary"
          onClick={() => setMoneyFlowOpen((v) => !v)}
          aria-expanded={moneyFlowOpen}
          aria-controls="moneyflow-panel"
        >
          <span>{"\u5e02\u5834\u8cc7\u91d1\u6d41\u5411"}</span>
          <span
            className={cn(
              "text-muted-foreground transition-transform duration-200",
              moneyFlowOpen && "rotate-180",
            )}
            aria-hidden
          >
            {"\u25be"}
          </span>
        </button>
        {moneyFlowOpen && (
          <div id="moneyflow-panel" className="mt-2">
            <MoneyFlow sectors={radar.sectors} themes={radar.themes} />
          </div>
        )}
      </div>

      <Alert className="mt-1 bg-card">
        <AlertDescription className="flex flex-wrap items-baseline gap-2.5 text-[13px] text-foreground">
          <span className="shrink-0 rounded-md bg-warn/15 px-2 py-0.5 text-[11.5px] font-bold tracking-[0.3px] text-warn">
            {"\u514d\u8cac\u8072\u660e"}
          </span>
          <span>{radar.note}{"\u3002\u672c\u7cfb\u7d71\u8cc7\u8a0a\u50c5\u4f9b\u53c3\u8003\uff0c\u4e0d\u69cb\u6210\u6295\u8cc7\u5efa\u8b70\u3002\u5206\u9ede\u8cc7\u6599\u76ee\u524d\u6db5\u84cb\u71b1\u9580\u80a1\uff0c\u6548\u529b\u96a8\u6bcf\u65e5\u6578\u64da\u7d2f\u7a4d\u63d0\u5347\u3002"}</span>
        </AlertDescription>
      </Alert>
    </>
  );
}
