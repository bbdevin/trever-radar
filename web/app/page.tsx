"use client";

import { useEffect, useState, useMemo, useRef, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { Clock, ShieldCheck, Zap, ChevronDown, Briefcase, AlertTriangle, Ban, Percent } from "lucide-react";
import { IconFlame, IconTrend, IconZap, IconRadar, IconPulse, IconStar, IconTrendDown } from "@/components/Icons";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import MoneyFlow from "@/components/MoneyFlow";
import StockCard from "@/components/StockCard";
import ThemeGroupedList from "@/components/ThemeGroupedList";
import MarginUsageRank from "@/components/MarginUsageRank";
import { useSession, signInWithGoogle } from "@/lib/useSession";
import { cn, navPillClass, pillTabClass } from "@/lib/utils";
import { dataFetch } from "@/lib/dataFetch";
import { OFFLINE_DATA_COPY, isBrowserOffline } from "@/lib/pwa";
import type { ListKey, MetaJson, RadarJson, StrategyMeta } from "@/lib/types";
import { SOURCE_LABEL, fmtE8 } from "@/lib/format";

// TabKey for the main task-oriented tabs（資券嵌首頁，手機 BottomNav 不另開第 5 項）
type TabKey =
  | "score"
  | "armed"
  | "triggered"
  | "extended"
  | "faded"
  | "pocket"
  | "margin"
  | "scan"
  | "mark"
  | "warrant";

// Scan modes within the "scan" tab
type ScanModeKey = "hot" | "surge" | "strong" | "weak";

const TABS: { key: TabKey; label: string; hint: string; icon: any }[] = [
  {
    key: "score",
    label: "綜合",
    hint: "依盤後綜合分排序（分點／權證／技術／法人加權 − 風險扣分）。≥65 為觀察門檻——用來掃「今天籌碼與技術都偏強」的名單。",
    icon: IconRadar,
  },
  {
    key: "armed",
    label: "未發動",
    hint: "分點或權證籌碼已異常進駐，但股價尚未明顯表態。適合盤中盯「何時發動」，不是已經大漲的名單。",
    icon: ShieldCheck,
  },
  {
    key: "triggered",
    label: "已發動",
    hint: "籌碼進駐且今日放量突破或創高——價格已開始反應訊號，偏「確認發動」而非提前埋伏。",
    icon: Zap,
  },
  {
    key: "extended",
    label: "追高風險",
    hint: "籌碼仍在，但漲幅已大或帶過熱／長上影等風險標籤。提醒勿盲目追高，不是加碼建議。",
    icon: AlertTriangle,
  },
  {
    key: "faded",
    label: "失效",
    hint: "收盤觸及失效價，或籌碼訊號已淡出（同日近似）。表示先前觀察條件可能已不成立。",
    icon: Ban,
  },
  {
    key: "pocket",
    label: "口袋",
    hint: "地緣／關鍵分點／熱門題材等理由疊加（≥2）的觀察池；不進綜合分，只做排序與提醒。",
    icon: Briefcase,
  },
  {
    key: "margin",
    label: "資券",
    hint: "全市場融資使用率（餘額÷限額）排行。越高＝融資額度越緊；≥60% 視為過熱風險觀察，不進綜合分。",
    icon: Percent,
  },
  {
    key: "scan",
    label: "市場掃描",
    hint: "依量價特徵掃描：熱門、爆量、強勢、弱勢——偏市場廣度，不依綜合分。",
    icon: IconZap,
  },
  {
    key: "mark",
    label: "策略",
    hint: "進階規則選股（技術／籌碼等策略標籤）。需登入；績效標籤僅供觀察。",
    icon: IconStar,
  },
  {
    key: "warrant",
    label: "權證",
    hint: "認購權證成交金額相對 20 日均值放大的標的——籌碼熱度參考，非下單建議。",
    icon: IconPulse,
  },
];

const TAB_KEYS = new Set<string>(TABS.map((t) => t.key));

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
  { key: "S4_VOLATILITY_CONTRACTION", label: "波動收斂突破", desc: "兩階段觀察：先找壓縮蓄勢，再確認帶量壓縮突破；突破優先排序，兩者皆不計入綜合分" },
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

// F4.2: 四類 UI 分群(見 docs/20 §4.1)。只分群、不改 S code 語意;籌碼事件預設展開。
const STRATEGY_GROUPS: { key: string; label: string; codes: string[] }[] = [
  { key: "chips", label: "籌碼事件", codes: ["S11_INSTI_BREAKOUT", "S12_BRANCH_ACCUMULATION", "S13_SHORT_SQUEEZE"] },
  { key: "breakout", label: "突破發動", codes: ["S2_BREAKOUT20", "S3_MA_CONVERGE_BREAKOUT", "S4_VOLATILITY_CONTRACTION", "S6_HIGH_BASE_BREAKOUT", "S7_MACD_ZERO_CROSS", "S8_GAP_BREAKOUT"] },
  { key: "trend", label: "趨勢續強/回踩", codes: ["S1_REBOUND", "S5_PULLBACK_SUPPORT", "S9_MA5_TREND"] },
  { key: "reversal", label: "低檔反轉", codes: ["S10_BOTTOM_MACD"] },
];

const STRATEGY_BY_KEY: Record<string, (typeof STRATEGIES)[number]> = Object.fromEntries(
  STRATEGIES.map((s) => [s.key, s]),
);

const THEME_SORT_TABS = new Set<TabKey>(["score", "scan", "pocket"]);
const LS_LIST_SORT = "trever.home.listSort.v1";
type ListSort = "score" | "theme";

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
  return (
    <Suspense fallback={<LoadingSkeleton />}>
      <RadarView />
    </Suspense>
  );
}

function RadarView() {
  const searchParams = useSearchParams();
  const [radar, setRadar] = useState<RadarJson | null>(null);
  const [meta, setMeta] = useState<MetaJson | null>(null);
  const [error, setError] = useState(false);
  const [tab, setTab] = useState<TabKey>("score");
  const [scanMode, setScanMode] = useState<ScanModeKey>("hot");
  const [strategy, setStrategy] = useState<string>("S11_INSTI_BREAKOUT");
  // F4.2: 已展開的策略組(session 內即可,不持久化);預設只展開籌碼事件。
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(() => new Set(["chips"]));
  const strategyDefaulted = useRef(false);
  const [moneyFlowOpen, setMoneyFlowOpen] = useState(false);
  const [listSort, setListSort] = useState<ListSort>("score");
  const { session, loading } = useSession();

  useEffect(() => {
    const q = searchParams.get("tab");
    if (q && TAB_KEYS.has(q)) setTab(q as TabKey);
  }, [searchParams]);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(LS_LIST_SORT);
      if (raw === "theme" || raw === "score") setListSort(raw);
    } catch {
      /* ignore */
    }
  }, []);

  const setListSortPersist = (next: ListSort) => {
    setListSort(next);
    try {
      localStorage.setItem(LS_LIST_SORT, next);
    } catch {
      /* ignore */
    }
  };

  // F4.2: 預設選中「籌碼事件」組第一個有檔數的策略(都無檔數則 S11);radar 載入後套一次,不覆寫使用者選擇。
  useEffect(() => {
    if (!radar || strategyDefaulted.current) return;
    strategyDefaulted.current = true;
    const chips = STRATEGY_GROUPS[0].codes;
    const firstWithCount = chips.find((c) => (radar.strategies?.[c]?.length ?? 0) > 0);
    if (firstWithCount) setStrategy(firstWithCount);
  }, [radar]);

  const toggleGroup = (key: string) =>
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  useEffect(() => {
    dataFetch("/data/radar.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setRadar)
      .catch(() => setError(true));
    dataFetch("/data/meta.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setMeta)
      .catch(() => {});
  }, []);

  const shown = useMemo(() => {
    if (!radar || tab === "margin") return [];
    const byId = new Map(radar.stocks.map((s) => [s.id, s]));
    if (tab === "mark") {
      return (radar.strategies?.[strategy] ?? []).map((id) => byId.get(id)!).filter(Boolean);
    }
    if (tab === "scan") {
      return (radar.lists?.[scanMode] ?? []).map((id) => byId.get(id)!).filter(Boolean);
    }
    return (radar.lists?.[tab as ListKey] ?? []).map((id) => byId.get(id)!).filter(Boolean);
  }, [radar, tab, scanMode, strategy]);

  const selectTab = (next: TabKey) => {
    setTab(next);
    try {
      const url = new URL(window.location.href);
      if (next === "score") url.searchParams.delete("tab");
      else url.searchParams.set("tab", next);
      window.history.replaceState(null, "", url.pathname + url.search + url.hash);
    } catch {
      /* ignore */
    }
  };

  if (error) {
    if (isBrowserOffline()) {
      return <div className="py-[46px] text-center text-sm text-muted-foreground">{OFFLINE_DATA_COPY}</div>;
    }
    return (
      <div className="py-[46px] text-center text-sm text-muted-foreground">
        {"找不到資訊檚。請先執行管線:"}
        <code className="rounded-md border border-border bg-card px-1.5 py-0.5 text-[12.5px] text-[color:var(--ink-2)]">
          python -m radar import-daily
        </code>{" "}
        {"再"}{" "}
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
          <span className="text-[10.5px] text-muted-foreground">{"資料日"}</span>
          <span className="num text-[15px] font-bold">
            {radar.data_date}
            {stale.length > 0 && <span className="ml-1.5 text-[11px] font-medium text-warn">{"部分待更新"}</span>}
          </span>
        </div>
        {radar.summary.map((m) => (
          <div
            key={m.market}
            className="flex snap-start flex-col gap-0.5 rounded-[var(--r-md)] border border-border bg-card px-3 py-2 shadow-[var(--shadow-card)]"
          >
            <span className="text-[10.5px] text-muted-foreground">{(SOURCE_LABEL[m.market] ?? m.market) + "成交"}</span>
            <span className="num text-[15px] font-bold">
              {fmtE8(m.turnover)}
              <span className="ml-1 text-[11px] font-medium text-[color:var(--ink-2)]">
                <span className="text-up">{"↑"}{m.up}</span>{" / "}<span className="text-down">{"↓"}{m.down}</span>
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
              {"尚未更新"}
            </span>
            <span>
              {stale.map((s) => `${s.label}今日尚未公布,暫用 ${s.date}`).join("；")}
              {"(依交易所公布時間分批自動更新)"}
            </span>
          </AlertDescription>
        </Alert>
      )}

      {/* Primary Queue: tabs + stock list */}
      <div className="my-1.5 mb-2">
        <div
          role="tablist"
          aria-label="觀察名單"
          className="flex max-w-full gap-0.5 overflow-x-auto rounded-full border border-border bg-card p-[3px] whitespace-nowrap [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        >
          {TABS.map((t) => {
            const count =
              t.key === "scan"
                ? radar.lists?.[scanMode]?.length ?? 0
                : t.key === "mark" || t.key === "margin"
                  ? null
                  : radar.lists?.[t.key as ListKey]?.length ?? 0;
            return (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={tab === t.key}
                className={cn(
                  "inline-flex min-h-11 items-center gap-1.5",
                  navPillClass(tab === t.key),
                )}
                onClick={() => selectTab(t.key)}
                title={t.hint}
              >
                <t.icon size={15} className="opacity-85" aria-hidden />
                {t.label}
                {count != null && (
                  <small className={cn("num text-[11px]", tab === t.key ? "text-primary-foreground/80" : "text-muted-foreground")}>{count}</small>
                )}
              </button>
            );
          })}
        </div>
        {tab !== "margin" && (
          <p
            className="mt-2.5 rounded-[var(--r-md)] border border-border/80 bg-muted/25 px-3 py-2 text-[12.5px] leading-relaxed text-foreground/90"
            role="note"
          >
            <span className="mr-1.5 font-semibold text-foreground">
              {TABS.find((t) => t.key === tab)?.label}
            </span>
            {TABS.find((t) => t.key === tab)?.hint}
          </p>
        )}
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
                  "inline-flex cursor-pointer items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[12.5px] font-medium transition-colors duration-200",
                  scanMode === mode.key
                    ? "bg-[color:var(--accent-2)] text-white shadow-sm"
                    : "border border-border bg-card text-muted-foreground hover:bg-secondary hover:text-foreground",
                )}
                title={mode.hint}
              >
                <mode.icon size={13} />
                <span>{mode.label}</span>
                <span
                  className={cn(
                    "num rounded px-1 py-0.5 text-[10.5px]",
                    scanMode === mode.key ? "bg-white/20" : "bg-muted",
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
          <div className="flex flex-col gap-1.5">
            {STRATEGY_GROUPS.map((g) => {
              // 選中策略若落在本組,強制展開——選中態不能被藏住。
              const isOpen = expandedGroups.has(g.key) || g.codes.includes(strategy);
              const groupCount = g.codes.reduce((sum, c) => sum + (radar.strategies?.[c]?.length ?? 0), 0);
              return (
                <div key={g.key}>
                  <button
                    onClick={() => toggleGroup(g.key)}
                    aria-expanded={isOpen}
                    className="flex w-full items-center gap-2 rounded-md px-1 py-1.5 text-left text-[13px] font-semibold text-foreground transition-colors hover:text-[color:var(--ink-2)]"
                  >
                    <ChevronDown
                      size={15}
                      aria-hidden
                      className={cn(
                        "shrink-0 text-muted-foreground transition-transform duration-200",
                        !isOpen && "-rotate-90",
                      )}
                    />
                    <span>{g.label}</span>
                    <span className="num rounded bg-muted px-1.5 py-0.5 text-[10.5px] text-muted-foreground">
                      {groupCount}
                    </span>
                  </button>
                  {isOpen && (
                    <div className="mt-1.5 mb-1 flex flex-wrap gap-1.5 pl-6">
                      {g.codes.map((code) => {
                        const st = STRATEGY_BY_KEY[code];
                        if (!st) return null;
                        const meta: StrategyMeta | undefined = radar.strategy_meta?.[code];
                        const isRetired = meta?.status === "retired";
                        const isActive = strategy === code;
                        const insufficientSamples = meta ? !meta.sufficient_samples : false;
                        return (
                          <button
                            key={code}
                            onClick={() => setStrategy(code)}
                            title={isRetired ? "此策略在目前有限樣本下未顯示正向預測力，降級觀察中；樣本不足，非永久淘汰" : st.label}
                            className={cn(
                              "cursor-pointer rounded-md px-2.5 py-1 text-[12.5px] font-medium transition-colors duration-200",
                              isActive
                                ? "bg-primary text-primary-foreground shadow-sm"
                                : isRetired
                                  ? "bg-muted/50 text-muted-foreground/50 hover:bg-muted/60"
                                  : "bg-muted text-muted-foreground hover:bg-muted/80",
                            )}
                          >
                            {st.label}
                            <span
                              className={cn(
                                "ml-1.5 rounded px-1 py-0.5 text-[10px]",
                                isActive ? "bg-primary-foreground/20" : "bg-background",
                              )}
                            >
                              {radar.strategies?.[code]?.length ?? 0}
                            </span>
                            {isRetired && !isActive && (
                              <span className="ml-1 rounded bg-muted px-1 py-0.5 text-[9.5px] font-semibold text-muted-foreground/60 no-underline">
                                {"樣本不足"}
                              </span>
                            )}
                            {!isRetired && insufficientSamples && !isActive && (
                              <span className="ml-1 rounded bg-muted px-1 py-0.5 text-[9.5px] font-normal text-muted-foreground/60 no-underline">
                                {"Shadow"}
                              </span>
                            )}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          <div className="mt-2.5 flex items-start gap-2 rounded-md border border-border bg-muted/30 px-3 py-2 text-[12.5px] text-muted-foreground">
            <IconStar size={14} className="mt-[2px] shrink-0 opacity-70" />
            <div className="flex flex-col gap-1">
              <span>{STRATEGIES.find((s) => s.key === strategy)?.desc}</span>
              {strategy === "S4_VOLATILITY_CONTRACTION" && radar.strategy_phases?.S4_VOLATILITY_CONTRACTION && (
                <span className="text-[11px] text-muted-foreground/70">
                  {(() => {
                    const phases = radar.strategy_phases.S4_VOLATILITY_CONTRACTION;
                    return `壓縮突破 ${phases.breakout?.length ?? 0} 檔 · 壓縮蓄勢 ${phases.setup?.length ?? 0} 檔 · 舊版 ${phases.legacy?.length ?? 0} 檔`;
                  })()}
                </span>
              )}
              {(() => {
                const s4Phases = radar.strategy_phases?.S4_VOLATILITY_CONTRACTION;
                if (strategy === "S4_VOLATILITY_CONTRACTION" && s4Phases) {
                  const phaseRows = [
                    { key: "S4_COMPRESSION_BREAKOUT_V2", label: "壓縮突破" },
                    { key: "S4_COMPRESSION_SETUP_V2", label: "壓縮蓄勢" },
                    { key: "S4_VOLATILITY_CONTRACTION", label: "舊版" },
                  ];
                  return (
                    <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground/70">
                      {phaseRows.map((phase) => {
                        const phaseMeta = radar.strategy_meta?.[phase.key];
                        const h20 = phaseMeta?.h20;
                        const samples = h20?.samples ?? 0;
                        return (
                          <span key={phase.key}>
                            {phase.label}：{samples > 0 && h20
                              ? `20日勝率 ${h20.win_rate != null ? h20.win_rate.toFixed(1) + "%" : "—"}／樣本 ${samples}`
                              : "20日樣本尚不足"}
                          </span>
                        );
                      })}
                    </div>
                  );
                }
                const meta = radar.strategy_meta?.[strategy];
                if (!meta) return null;
                const h20 = meta.h20;
                const isRetired = meta.status === "retired";
                const hasSamples = (h20?.samples ?? 0) > 0;
                return (
                  <span className="mt-0.5 text-[11px] text-muted-foreground/70">
                    {isRetired && (
                      <span className="mr-1.5 rounded bg-muted px-1 py-0.5 text-[9.5px] font-semibold text-muted-foreground/60">
                        {"樣本不足·降級觀察"}
                      </span>
                    )}
                    {!isRetired && !meta.sufficient_samples && (
                      <span className="mr-1.5 rounded bg-muted px-1 py-0.5 text-[9.5px] font-normal">
                        {"Shadow · 樣本不足"}
                      </span>
                    )}
                    {hasSamples
                      ? `20日勝率 ${h20.win_rate != null ? h20.win_rate.toFixed(1) + "%" : "—"} ／樣本 ${h20.samples} 筆`
                      : "20日樣本尚不足，績效待觀察"}
                  </span>
                );
              })()}
            </div>
          </div>
        </div>
      )}

      {tab === "margin" ? (
        <div className="mb-4 animate-[fadeUp_0.35s_ease_backwards]">
          <MarginUsageRank embedded />
        </div>
      ) : tab === "mark" && !loading && !session ? (
        <div className="flex flex-col items-center gap-4 py-[46px] text-center text-sm text-muted-foreground">
          <span>進階策略榜單為會員專屬功能，請先登入 Google 帳號解鎖。</span>
          <button
            onClick={signInWithGoogle}
            className="min-h-11 cursor-pointer rounded-md border border-border bg-card px-4 py-2 text-sm text-foreground transition-colors duration-200 hover:bg-secondary"
          >
            {"使用 Google 登入"}
          </button>
        </div>
      ) : shown.length === 0 ? (
        <div className="mx-auto max-w-md py-[46px] text-center text-sm leading-relaxed text-muted-foreground">
          {tab === "pocket"
            ? (radar.pocket_note
              ?? "口袋名單要至少兩個獨立理由(地緣/關鍵分點/題材/未發動或集中度)才入榜。地緣目前僅涵蓋每日評分池,且要等公司住址匯入後才會出現。")
            : tab === "score" || tab === "mark"
            ? "今日無達門檻的標的。寧缺勿濫是一大設計原則——沒有符合條件時不硬湊，也可能是盤後分點尚未更新。"
            : "今日此榜無符合條件的標的，或該類資料尚未更新。稍後回來再看，系統會依交易所公佈時間分批更新。"}
        </div>
      ) : (
        <>
          {tab === "pocket" && radar.pocket_note && (
            <p className="mb-2 text-[12px] leading-relaxed text-muted-foreground">
              {radar.pocket_note}
              {"。地緣為統計推測；分點≠單一人。"}
            </p>
          )}
          {THEME_SORT_TABS.has(tab) && (
            <div className="mb-2.5 flex flex-wrap items-center gap-2">
              <span className="text-[12px] text-muted-foreground">{"排序"}</span>
              <div role="tablist" className="flex gap-0.5 rounded-full border border-border bg-card p-[3px]">
                <button
                  type="button"
                  role="tab"
                  aria-selected={listSort === "score"}
                  className={cn("min-h-11 cursor-pointer", pillTabClass(listSort === "score"))}
                  onClick={() => setListSortPersist("score")}
                >
                  {"分數"}
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={listSort === "theme"}
                  className={cn("min-h-11 cursor-pointer", pillTabClass(listSort === "theme"))}
                  onClick={() => setListSortPersist("theme")}
                  title={radar.themes?.length ? "依當日最熱題材分組,一檔只出現一次" : "今日無題材資金流,維持原排序"}
                >
                  {"題材"}
                </button>
              </div>
            </div>
          )}
          {THEME_SORT_TABS.has(tab) && listSort === "theme" ? (
            <ThemeGroupedList stocks={shown} themes={radar.themes} />
          ) : (
            <div className="grid grid-cols-1 gap-2.5 pb-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {shown.map((s, i) => (
                <StockCard key={s.id} s={s} index={i} />
              ))}
            </div>
          )}
        </>
      )}

      {/* Context: MoneyFlow collapsible */}
      <div className="mb-4">
        <button
          className="flex w-full items-center justify-between rounded-[var(--r-md)] border border-border bg-card px-4 py-2.5 text-left text-[13.5px] font-semibold text-foreground transition-colors hover:border-[color:var(--border-strong)] hover:bg-secondary"
          onClick={() => setMoneyFlowOpen((v) => !v)}
          aria-expanded={moneyFlowOpen}
          aria-controls="moneyflow-panel"
        >
          <span>市場資金流向</span>
          <span
            className={cn(
              "text-muted-foreground transition-transform duration-200",
              moneyFlowOpen && "rotate-180",
            )}
            aria-hidden
          >
            {"▾"}
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
            {"免責聲明"}
          </span>
          <span>{radar.note}{"。本系統資訊僅供參考，不構成投資建議。分點資料目前涵蓋熱門股，效力隨每日數據累積提升。"}</span>
        </AlertDescription>
      </Alert>
    </>
  );
}
