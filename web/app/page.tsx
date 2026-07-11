"use client";

import { useEffect, useState, useMemo } from "react";
import { Clock, Search, TrendingUp, TrendingDown, Star, Sparkles, ShieldCheck, Zap } from "lucide-react";
import { IconFlame, IconTrend, IconZap, IconRadar, IconPulse, IconStar, IconTrendDown } from "@/components/Icons";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import MoneyFlow from "@/components/MoneyFlow";
import StockCard from "@/components/StockCard";
import { useSession, signInWithGoogle } from "@/lib/useSession";
import { cn } from "@/lib/utils";
import type { ListKey, MetaJson, RadarJson } from "@/lib/types";
import { SOURCE_LABEL, fmtE8 } from "@/lib/format";

// TabKey for the 4 main task-oriented tabs
type TabKey = "score" | "armed" | "triggered" | "scan" | "mark" | "warrant";

// Scan modes within the "scan" tab
type ScanModeKey = "hot" | "surge" | "strong" | "weak";

const TABS: { key: TabKey; label: string; hint: string; icon: any }[] = [
  { key: "score", label: "綜合", hint: "盤後綜合分數:分點/權證/技術/法人加權−風險扣分,≥65 為觀察門檻", icon: IconRadar },
  { key: "armed", label: "未發動", hint: "分點/權證籌碼異常進駐，且股價尚未表態", icon: ShieldCheck },
  { key: "triggered", label: "已發動", hint: "分點/權證籌碼進駐，且今日放量突破或創高", icon: Zap },
  { key: "scan", label: "市場掃描", hint: "多維度市場量價特徵掃描 (熱門/爆量/強勢/弱勢)", icon: IconZap },
  { key: "mark", label: "策略", hint: "進階量化選股，涵蓋技術面與籌碼面等多種策略", icon: IconStar },
  { key: "warrant", label: "權證", hint: "認購權證成交金額相對20日均值放大", icon: IconPulse },
];

const SCAN_MODES: { key: ScanModeKey; label: string; hint: string; icon: typeof IconFlame }[] = [
  { key: "hot", label: "熱門排行", hint: "成交金額最大", icon: IconFlame },
  { key: "surge", label: "爆量突破", hint: "量比 = 今日量/20日均量,≥1.5 且金額 ≥1億", icon: IconZap },
  { key: "strong", label: "強勢大漲", hint: "漲幅排序,金額 ≥1億", icon: IconTrend },
  { key: "weak", label: "弱勢回跌", hint: "跌幅排序,金額 ≥1億——看資金逃離誰", icon: IconTrendDown },
];

const STRATEGIES = [
  { key: "S1_REBOUND", label: "漲停二次發動", desc: "雙軌條件：嚴謹版為近 20 日曾漲停、MACD 零軸上黃金交叉、5 日內爆量（2 倍）；相似（放寬）版為近 20 日曾大漲 7%、MACD 任意金叉、5 日內量增 1.5 倍。榜內嚴謹版優先排前" },
  { key: "S2_BREAKOUT20", label: "20日爆量突破", desc: "創 20 日新高，當日爆量且收紅 K，中長期均線多頭排列" },
  { key: "S3_MA_CONVERGE_BREAKOUT", label: "均線糾結突破", desc: "5/10/20 日均線距離極近，當日帶量長紅突破糾結區" },
  { key: "S4_VOLATILITY_CONTRACTION", label: "波動收斂突破", desc: "近 10 日布林通道極度壓縮（帶寬 < 8%），當日帶量突破上軌" },
  { key: "S5_PULLBACK_SUPPORT", label: "強勢量縮回踩", desc: "近期創高後回檔，量縮至極致並於 10 日或 20 日均線獲得支撐收紅" },
  { key: "S6_HIGH_BASE_BREAKOUT", label: "高檔平台突破", desc: "在 60 日高點附近高姿勢橫盤整理，當日帶量突破平台上緣" },
  { key: "S7_MACD_ZERO_CROSS", label: "MACD零軸金叉", desc: "MACD 於零軸之上發生黃金交叉，且當日帶量收紅" },
  { key: "S8_GAP_BREAKOUT", label: "跳空不回補", desc: "發生向上跳空缺口，後續 3 日未封閉缺口且量縮整理後轉強" },
  { key: "S9_MA5_TREND", label: "五日線強攻", desc: "股價沿 5 日線強勢上攻，未曾跌破 5 日線，當日量價配合延續強勢" },
  { key: "S10_BOTTOM_MACD", label: "底部MACD轉強", desc: "股價處於長期低檔區，MACD 於零軸下方黃金交叉且柱狀圖明顯翻紅" },
  { key: "S11_INSTI_BREAKOUT", label: "法人連買突破", desc: "外資或投信連續 3 日買超，配合技術面突破轉強" },
  { key: "S12_BRANCH_ACCUMULATION", label: "分點集中未發動", desc: "主力分點買超極度集中（佔比 > 15% 且倍增），但股價尚未明顯大漲" },
  { key: "S13_SHORT_SQUEEZE", label: "融券回補軋空", desc: "融券餘額處於高檔（> 1000 張）且近期連續減少，當日帶量長紅突破" },
];

function LoadingSkeleton() {
  return (
    <>
      <div className="my-3.5 flex gap-2 overflow-x-auto">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-[52px] w-full min-w-[120px] shrink-0 rounded-[var(--r-md)]" />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-2.5 pb-[46px] md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-[105px] rounded-[var(--r-lg)]" />
        ))}
      </div>
    </>
  );
}

export default function RadarPage() {
  const [radar, setRadar] = useState<RadarJson | null>(null);
  const [meta, setMeta] = useState<MetaJson | null>(null);
  const [error, setError] = useState(false);
  const [tab, setTab] = useState<TabKey>("score");
  const [scanMode, setScanMode] = useState<ScanModeKey>("hot");
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
    if (tab === "scan") {
      return (radar.lists?.[scanMode] ?? []).map((id) => byId.get(id)!).filter(Boolean);
    }
    return (radar.lists?.[tab as ListKey] ?? []).map((id) => byId.get(id)!).filter(Boolean);
  }, [radar, tab, scanMode, strategy]);

  if (error) {
    return (
      <div className="py-[46px] text-center text-sm text-muted-foreground">
        {"\u627e\u4e0d\u5230\u8cc7\u8a0a\u6a9a\u3002\u8acb\u5148\u57f7\u884c\u7ba1\u7dda:"}
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
    insti: "法人", margin: "融資券", warrant: "權證", branch: "分點",
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
          {TABS.map((t) => {
            const count = t.key === "scan" 
              ? radar.lists?.[scanMode]?.length ?? 0 
              : t.key === "mark" 
                ? 0 
                : radar.lists?.[t.key as ListKey]?.length ?? 0;
            return (
              <button
                key={t.key}
                role="tab"
                aria-selected={tab === t.key}
                className={cn(
                  "inline-flex min-h-11 items-center gap-1.5 rounded-full px-4 py-2 text-[13.5px] font-semibold text-muted-foreground transition-colors",
                  tab === t.key && "bg-muted text-foreground shadow-[inset_0_0_0_1px_var(--border-strong)]",
                )}
                onClick={() => setTab(t.key)}
                title={t.hint}
              >
                <t.icon size={15} className="opacity-85" />
                {t.label}
                {t.key !== "mark" && (
                  <small className="num text-[11px] text-muted-foreground">{count}</small>
                )}
              </button>
            );
          })}
        </div>
        <span className="hidden text-xs text-muted-foreground lg:inline">{TABS.find((t) => t.key === tab)?.hint}</span>
      </div>

      {/* Sub-selector for Market Scan */}
      {tab === "scan" && (
        <div className="mb-3.5 animate-in fade-in duration-200">
          <div className="flex flex-wrap gap-1.5">
            {SCAN_MODES.map((mode) => (
              <button
                key={mode.key}
                onClick={() => setScanMode(mode.key)}
                className={cn(
                  "rounded-md px-2.5 py-1.5 text-[12.5px] font-medium transition-colors inline-flex items-center gap-1.5",
                  scanMode === mode.key
                    ? "bg-[color:var(--ink-2)] text-[color:var(--bg-1)] shadow-[0_1px_2px_rgba(0,0,0,0.1)]"
                    : "bg-card border border-border text-muted-foreground hover:bg-secondary",
                )}
                title={mode.hint}
              >
                <mode.icon size={13} />
                <span>{mode.label}</span>
                <span
                  className={cn(
                    "num text-[10.5px] rounded px-1 py-0.5",
                    scanMode === mode.key ? "bg-[color:var(--bg-1)]/20" : "bg-muted",
                  )}
                >
                  {radar.lists?.[mode.key]?.length ?? 0}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

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
          <span>{"\u9032\u968e\u7b56\u7565\u699c\u55ae\u70ba\u6703\u54e1\u5c6c\u529f\u80fd\uff0c\u8acb\u5148\u76b1\u5165 Google \u5e33\u865f\u89e3\u9396\u3002"}</span>
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
            ? "\u4eca\u65e5\u7121\u9054\u9580\u6ebb\u7684\u6a19\u7684\u3002\u5be7\u7f3a\u52ff\u6feb\u66f4\u662f\u4e00\u8a2d\u8a0f\u539f\u5247\u2014\u2014\u6c92\u6709\u7b26\u5408\u689d\u4ef6\u6642\u4e0f\u786c\u6e4a,\u4e5f\u53ef\u80fd\u662f\u76e4\u5f8c\u5206\u653e\u5c1a\u672a\u66f4\u65b0\u3002"
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
          <span>{"\u5e02\u583a\u8cc7\u91d1\u6d41\u5411"}</span>
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
