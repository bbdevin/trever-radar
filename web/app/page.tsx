"use client";

import { useEffect, useMemo, useState } from "react";
import { IconFlame, IconPulse, IconRadar, IconTrend, IconTrendDown, IconZap, IconStar } from "@/components/Icons";
import MoneyFlow from "@/components/MoneyFlow";
import StockCard from "@/components/StockCard";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { useSession, signInWithGoogle } from "@/lib/useSession";
import { cn } from "@/lib/utils";
import type { ListKey, MetaJson, RadarJson } from "@/lib/types";
import { DATASET_LABEL, SOURCE_LABEL, fmtE8 } from "@/lib/format";

const TABS: { key: ListKey; label: string; hint: string; icon: typeof IconFlame }[] = [
  { key: "score", label: "綜合", hint: "盤後綜合分數:分點/權證/技術/法人加權−風險扣分,≥65 為觀察門檻", icon: IconRadar },
  { key: "mark", label: "策略", hint: "進階量化選股，涵蓋技術面與籌碼面等多種策略", icon: IconStar },
  { key: "hot", label: "熱門", hint: "成交金額最大", icon: IconFlame },
  { key: "surge", label: "爆量", hint: "量比 = 今日量/20日均量,≥1.5 且金額 ≥1億", icon: IconZap },
  { key: "strong", label: "強勢", hint: "漲幅排序,金額 ≥1億", icon: IconTrend },
  { key: "weak", label: "弱勢", hint: "跌幅排序,金額 ≥1億——看資金逃離誰", icon: IconTrendDown },
  { key: "warrant", label: "權證", hint: "認購權證成交金額相對20日均值放大", icon: IconPulse },
];

const STRATEGIES = [
  { key: "T6_MARK_STRATEGY", label: "綜合策略(嚴謹)", desc: "結合分點、技術、權證的綜合嚴謹策略，需滿足多項嚴格條件" },
  { key: "T6_MARK_STRATEGY_RELAXED", label: "綜合策略(寬鬆)", desc: "放寬部分指標門檻的綜合寬鬆策略，適合提早捕捉可能發動的標的" },
  { key: "S1_REBOUND", label: "漲停二次發動", desc: "近 20 日曾漲停，現價站上均線且 MACD 零上金叉，近日爆量突破" },
  { key: "S2_BREAKOUT20", label: "20日爆量突破", desc: "創 20 日新高，當日爆量且收紅 K，中長期均線多頭排列" },
  { key: "S3_MA_CONVERGE_BREAKOUT", label: "均線糾結突破", desc: "5/10/20 日均線距離極近，當日帶量長紅突破糾結區" },
  { key: "S4_VOLATILITY_CONTRACTION", label: "波動收斂突破", desc: "近 10 日布林通道極度壓縮（帶寬 < 8%），當日帶量突破上軌" },
  { key: "S5_PULLBACK_SUPPORT", label: "強勢量縮回踩", desc: "近期創高後回檔，量縮至極致並於 10 日或 20 日均線獲得支撐收紅" },
  { key: "S6_HIGH_BASE_BREAKOUT", label: "高檔平台突破", desc: "在 60 日高點附近高姿態橫盤整理，當日帶量突破箱型上緣" },
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
      <div className="my-3.5 flex gap-2.5 overflow-x-auto">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-[68px] w-full min-w-[150px] shrink-0 rounded-[var(--r-md)]" />
        ))}
      </div>
      <Skeleton className="mb-3.5 h-[180px] rounded-[var(--r-lg)]" />
      <div className="grid grid-cols-1 gap-2.5 pb-7 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <Skeleton key={i} className="h-[148px] rounded-[var(--r-lg)]" />
        ))}
      </div>
    </>
  );
}

export default function RadarPage() {
  const [radar, setRadar] = useState<RadarJson | null>(null);
  const [meta, setMeta] = useState<MetaJson | null>(null);
  const [error, setError] = useState(false);
  const [tab, setTab] = useState<ListKey>("score");
  const [strategy, setStrategy] = useState<string>("T6_MARK_STRATEGY");
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
        找不到資料檔。請先執行管線:
        <code className="rounded-md border border-border bg-card px-1.5 py-0.5 text-[12.5px] text-[color:var(--ink-2)]">
          python -m radar import-daily
        </code>{" "}
        再{" "}
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
      <div className="my-3.5 grid auto-cols-[minmax(150px,1fr)] grid-flow-col gap-2.5 overflow-x-auto [scroll-snap-type:x_proximity] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <div className="flex snap-start flex-col gap-0.5 rounded-[var(--r-md)] border border-border bg-card p-3 shadow-[var(--shadow-card)]">
          <span className="text-[11.5px] text-muted-foreground">資料日</span>
          <span className="num text-[17px] font-bold">
            {radar.data_date}
            {stale.length > 0 && <span className="ml-1.5 text-[12px] font-medium text-warn">部分待更新</span>}
          </span>
        </div>
        {radar.summary.map((m) => (
          <div
            key={m.market}
            className="flex snap-start flex-col gap-0.5 rounded-[var(--r-md)] border border-border bg-card p-3 shadow-[var(--shadow-card)]"
          >
            <span className="text-[11.5px] text-muted-foreground">{SOURCE_LABEL[m.market] ?? m.market}成交金額</span>
            <span className="num text-[17px] font-bold">
              {fmtE8(m.turnover)}
              <span className="ml-1.5 text-[12px] font-medium text-[color:var(--ink-2)]">
                <span className="text-up">↑{m.up}</span> / <span className="text-down">↓{m.down}</span> 家
              </span>
            </span>
          </div>
        ))}
      </div>

      {stale.length > 0 && (
        <Alert className="mb-4 bg-card">
          <AlertDescription className="flex flex-wrap items-baseline gap-2.5 text-[13px] text-foreground">
            <span className="shrink-0 rounded-md bg-[color:var(--ink-2)]/10 px-2 py-0.5 text-[11.5px] font-bold tracking-[0.3px] text-[color:var(--ink-2)]">
              資料狀態
            </span>
            <span>
              {stale.map((s) => `${s.label}今日尚未公布,暫用 ${s.date}`).join("；")}
              (依交易所公布時間分批自動更新)
            </span>
          </AlertDescription>
        </Alert>
      )}

      <MoneyFlow sectors={radar.sectors} themes={radar.themes} />

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
                    : "bg-muted text-muted-foreground hover:bg-muted/80"
                )}
              >
                {st.label}
                <span className={cn(
                  "ml-1.5 rounded px-1 py-0.5 text-[10px]",
                  strategy === st.key ? "bg-[color:var(--bg-1)]/20" : "bg-background"
                )}>
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
          <span>進階策略榜單為會員專屬功能，請先登入 Google 帳號解鎖。</span>
          <button
            onClick={signInWithGoogle}
            className="rounded-md border border-border bg-card px-4 py-2 text-sm text-foreground"
          >
            使用 Google 登入
          </button>
        </div>
      ) : shown.length === 0 ? (
        <div className="py-[46px] text-center text-sm text-muted-foreground">此榜今日無符合條件的股票</div>
      ) : (
        <div className="grid grid-cols-1 gap-2.5 pb-7 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {shown.map((s, i) => (
            <StockCard key={s.id} s={s} index={i} />
          ))}
        </div>
      )}

      <Alert className="mt-1 bg-card">
        <AlertDescription className="flex flex-wrap items-baseline gap-2.5 text-[13px] text-foreground">
          <span className="shrink-0 rounded-md bg-warn/15 px-2 py-0.5 text-[11.5px] font-bold tracking-[0.3px] text-warn">
            免責聲明
          </span>
          <span>{radar.note}。本系統資訊僅供參考，不構成投資建議。分點資料目前涵蓋熱門股，效力隨每日數據累積提升。</span>
        </AlertDescription>
      </Alert>
    </>
  );
}
