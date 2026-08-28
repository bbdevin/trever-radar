"use client";

import { Fragment, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  getExpandedRowModel,
  getSortedRowModel,
  useReactTable,
  type SortingState,
} from "@tanstack/react-table";
import { Building2, ChevronDown, ChevronUp, Flame, MapPin, Phone, ShieldCheck, Tags } from "lucide-react";
import { IconArrowLeft } from "@/components/Icons";
import KChart from "@/components/KChart";
import BranchFlowSection from "@/components/BranchFlowSection";
import BranchDrillView from "@/components/BranchDrillView";
import InstiPanel from "@/components/InstiPanel";
import MarginPanel from "@/components/MarginPanel";
import HoldersPanel from "@/components/HoldersPanel";
import WarrantBranchPanel from "@/components/WarrantBranchPanel";
import ReasonPill from "@/components/ReasonPill";
import PocketBadges from "@/components/PocketBadges";
import { Skeleton } from "@/components/ui/skeleton";
import WatchlistButton from "@/components/WatchlistButton";
import { dataFetch } from "@/lib/dataFetch";
import { OFFLINE_DATA_COPY, isBrowserOffline } from "@/lib/pwa";
import type { Buyback, CompanyTheme, RecentThemeHeat, StockJson } from "@/lib/types";
import { MARKET_LABEL, chgClass, fmtE8, fmtPct, fmtX } from "@/lib/format";
import { signInWithGoogle, useSession } from "@/lib/useSession";
import { cn, pillTabClass } from "@/lib/utils";

const RANGES = [
  { key: "1m", label: "1月", days: 22 },
  { key: "3m", label: "3月", days: 66 },
  { key: "6m", label: "6月", days: 132 },
  { key: "1y", label: "1年", days: 240 },
  { key: "5y", label: "5年", days: 1200 },
  { key: "all", label: "全部", days: Infinity },
] as const;

const CHG_TEXT: Record<string, string> = { up: "text-up", down: "text-down", flat: "text-foreground" };
const CHG_BADGE: Record<string, string> = {
  up: "text-up bg-up/15",
  down: "text-down bg-down/15",
  flat: "text-foreground bg-secondary",
};

function StockView() {
  const id = useSearchParams().get("id");
  const tabParam = useSearchParams().get("tab");
  const [data, setData] = useState<StockJson | null>(null);
  const [error, setError] = useState(false);
  const [range, setRange] = useState<(typeof RANGES)[number]["key"]>("6m");
  const [view, setView] = useState<"chart" | "chips" | "insti" | "margin" | "holders" | "basic" | "tech" | "warrant">("chart");
  const [drillBranch, setDrillBranch] = useState<string | null>(null);
  const activeTabRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!id) return;
    setDrillBranch(null);
    dataFetch(`/data/stocks/${id}.json`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setData)
      .catch(() => setError(true));
  }, [id]);

  // #branch hash：開籌碼日報分頁（IA-5；舊行為是捲到 K 線下方分點區）
  useEffect(() => {
    if (!data) return;
    if (typeof window === "undefined") return;
    if (window.location.hash === "#branch") {
      setView("chips");
    }
    if (tabParam === "margin") {
      setView("margin");
    }
    if (tabParam === "holders") {
      setView("holders");
    }
    if (tabParam === "basic") {
      setView("basic");
    }
  }, [data, tabParam]);

  useEffect(() => {
    const tab = activeTabRef.current;
    const tabList = tab?.parentElement;
    if (!tab || !tabList) return;
    const left = tab.offsetLeft - (tabList.clientWidth - tab.offsetWidth) / 2;
    tabList.scrollTo({ left: Math.max(0, left), behavior: "auto" });
  }, [view]);

  const visibleDays = useMemo(() => {
    const days = RANGES.find((r) => r.key === range)?.days ?? Infinity;
    return days === Infinity ? Number.MAX_SAFE_INTEGER : days;
  }, [range]);

  // 主力買賣超:每日全部分點(前15大裁剪版)net 加總;branch_history 為新到舊,圖表要舊到新
  const mainForce = useMemo(() => {
    const bh = data?.branch_history;
    if (!bh?.length) return undefined;
    return bh
      .map((d) => ({ t: d.t, net: d.branches.reduce((s, b) => s + b.net, 0) }))
      .sort((a, b) => (a.t < b.t ? -1 : 1));
  }, [data]);

  // 分點理由過濾：B* 系列(分點) + S11-S13(籌碼事件)
  // 必須在所有條件 return 之前宣告，符合 Rules of Hooks
  const branchReasons = useMemo(
    () => (data?.raw_reasons ?? []).filter((r) => {
      const c = r.code ?? "";
      return c.startsWith("B") || ["S11", "S12", "S13"].includes(c);
    }),
    [data]
  );

  if (!id) return <div className="py-[46px] text-center text-sm text-muted-foreground">網址缺少股票代號(?id=2330)</div>;
  if (error)
    return (
      <div className="py-[46px] text-center text-sm text-muted-foreground">
        {isBrowserOffline() ? OFFLINE_DATA_COPY : `尚無 ${id} 的個股資料檔。目前僅產出雷達榜單內的股票,之後擴大到全候選池。`}
      </div>
    );
  if (!data)
    return (
      <>
        <Skeleton className="my-4 h-[68px] rounded-[var(--r-md)]" />
        <Skeleton className="h-[52vh] rounded-[var(--r-lg)]" />
      </>
    );

  const cs = data.candles;
  const last = cs[cs.length - 1];
  const prev = cs.length > 1 ? cs[cs.length - 2] : null;
  const chg = prev ? Math.round(((last.c - prev.c) / prev.c) * 10000) / 100 : null;
  const cls = chgClass(chg);
  const branchScore = data.scores?.branch ?? null;
  const activeThemes = currentActiveThemes(data.recent_theme_heat, last.t);

  return (
    <div className="min-w-0 max-w-full overflow-x-hidden">
      <header data-testid="stock-header" className="py-3.5 pb-2.5">
        <div data-testid="stock-primary-row" className="flex min-w-0 items-center gap-1.5 sm:gap-2">
          <a
            href="/"
            className="-ml-2 inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center gap-1 rounded-full text-[13px] text-muted-foreground transition-colors duration-200 hover:bg-secondary hover:text-foreground sm:px-2.5"
            aria-label="返回雷達"
          >
            <IconArrowLeft size={17} />
            <span className="hidden sm:inline">雷達</span>
          </a>
          <div className="min-w-0 flex-1 pt-0.5">
            <h1 data-testid="stock-name" className="truncate text-[26px] font-extrabold leading-tight tracking-[-0.02em]" title={data.name}>{data.name}</h1>
            <p className="mt-1 truncate text-[13px] text-muted-foreground">{data.id} · {MARKET_LABEL[data.market] ?? data.market}{data.industry ? ` · ${data.industry}` : ""}</p>
          </div>
          <div data-testid="stock-price" className="flex shrink-0 items-center gap-1.5 whitespace-nowrap">
            <span className={cn("num text-[27px] font-extrabold leading-none tracking-[-0.03em] sm:text-[30px]", CHG_TEXT[cls])}>
              {last.c.toLocaleString("zh-TW")}
            </span>
            <span data-testid="stock-change" className={cn("num inline-block rounded-full px-2 py-1 text-[12px] font-bold", CHG_BADGE[cls])}>
              {fmtPct(chg)}
            </span>
            <WatchlistButton stockId={data.id} size={20} />
          </div>
        </div>
        {activeThemes.length > 0 && (
          <div className="mt-2 flex min-w-0 flex-wrap items-center gap-1.5 text-[11px]" aria-label="活躍題材">
            <span className="shrink-0 text-[color:var(--warn)]">活躍題材</span>
            {activeThemes.slice(0, 2).map((theme) => (
              <span key={theme.id} className="max-w-[10rem] truncate rounded-full border border-[color:var(--warn)]/35 bg-[color:var(--warn)]/8 px-1.5 py-0.5 text-[color:var(--ink-2)]" title={`${theme.name}（資料日 ${theme.heat_date}）`}>
                {theme.name}
              </span>
            ))}
            {activeThemes.length > 2 && (
              <span className="rounded-full bg-[color:var(--warn)]/12 px-1.5 py-0.5 font-semibold text-[color:var(--warn)]">
                +{activeThemes.length - 2}
              </span>
            )}
          </div>
        )}
      </header>

      {/* IA-2 + F3: the default-collapsed decision and quote evidence share the first screen. */}
      <div className="mb-2.5 grid min-w-0 grid-cols-[minmax(0,1.2fr)_minmax(8.25rem,0.8fr)] items-start gap-2.5 sm:grid-cols-[minmax(0,1fr)_minmax(14rem,0.72fr)]">
        <StockDecisionHeader data={data} close={last.c} className="mb-0" />
        <section data-testid="stock-market-summary" className="min-w-0 rounded-[var(--r-md)] border border-border bg-card px-2.5 py-2.5" aria-label={`行情摘要，資料日 ${last.t}`}>
          <p className="mb-1.5 text-[10.5px] text-muted-foreground">行情 {last.t}</p>
          <dl className="grid gap-y-1 text-[11px]">
          {[
            ["量", `${last.v.toLocaleString("zh-TW")} 張`],
            ["額", fmtE8(last.amt)],
            ["昨收", prev?.c.toLocaleString("zh-TW") ?? "—"],
            ["開盤", last.o.toLocaleString("zh-TW")],
            ["最高", last.h.toLocaleString("zh-TW")],
            ["最低", last.l.toLocaleString("zh-TW")],
          ].map(([label, value]) => (
            <div key={label} className="flex min-w-0 items-baseline justify-between gap-2">
              <dt className="shrink-0 text-muted-foreground">{label}</dt>
              <dd className="num truncate text-right font-bold text-[color:var(--ink-2)]" title={value}>{value}</dd>
            </div>
          ))}
          </dl>
        </section>
      </div>
      <div className="sticky top-0 z-20 -mx-1 mb-2.5 flex min-w-0 flex-col gap-2 bg-background/95 px-1 py-1.5 backdrop-blur-sm md:static md:mx-0 md:bg-transparent md:px-0 md:py-0 md:backdrop-blur-none md:flex-row md:flex-wrap md:items-center md:gap-2.5">
        <div
          role="tablist"
          aria-label="個股內容"
          className="flex w-full max-w-full shrink-0 gap-0.5 overflow-x-auto rounded-full border border-border bg-card p-[3px] scrollbar-hide [scrollbar-width:none] max-md:flex-nowrap max-md:[&>*]:shrink-0 [&::-webkit-scrollbar]:hidden md:w-fit"
        >
          {(
            [
              { key: "chart" as const, label: "K線" },
              { key: "chips" as const, label: "籌碼日報" },
              { key: "insti" as const, label: "三大法人" },
              { key: "margin" as const, label: "資券" },
              { key: "holders" as const, label: "大戶" },
              { key: "basic" as const, label: "基本資料" },
              { key: "tech" as const, label: "技術" },
              { key: "warrant" as const, label: "權證" },
            ] as const
          ).map((t) => (
          <button
              key={t.key}
              ref={view === t.key ? activeTabRef : undefined}
              data-testid={`stock-tab-${t.key}`}
              type="button"
              role="tab"
              aria-selected={view === t.key}
              className={cn(pillTabClass(view === t.key), "min-h-11 touch-manipulation")}
              onClick={() => setView(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>
        {view === "chart" && (
          <div
            role="tablist"
            aria-label="K線區間"
            className="flex max-w-full gap-0.5 overflow-x-auto rounded-full border border-border bg-card p-[3px] scrollbar-hide [scrollbar-width:none] max-md:flex-nowrap max-md:[&>*]:shrink-0 [&::-webkit-scrollbar]:hidden"
          >
            {RANGES.map((r) => (
              <button key={r.key} type="button" role="tab" aria-selected={range === r.key} className={pillTabClass(range === r.key)} onClick={() => setRange(r.key)}>
                {r.label}
              </button>
            ))}
          </div>
        )}
      </div>
      {view === "chart" && <KChart candles={cs} visibleDays={visibleDays} mainForce={mainForce} />}
      {view === "chips" && (
        <BranchFlowSection
          branches={data.branches}
          branchHistory={data.branch_history}
          score={branchScore}
          reasons={branchReasons}
          heading="分點進出"
          id="branch"
          quoteDate={last.t}
          onOpenBranch={setDrillBranch}
        />
      )}
      {view === "insti" && <InstiPanel data={data} candles={cs} />}
      {view === "margin" && <MarginPanel data={data} candles={cs} />}
      {view === "holders" && <HoldersPanel data={data} />}
      {view === "basic" && <BasicInfoPanel data={data} quoteDate={last.t} />}
      {view === "tech" && <TechnicalPanel data={data} />}
      {view === "warrant" && <WarrantPanel data={data} />}

      {drillBranch && (
        <div className="safe-overlay fixed inset-0 z-50 overflow-y-auto bg-background">
          <BranchDrillView
            stockName={data.name}
            stockId={data.id}
            branchName={drillBranch}
            candles={cs}
            branchHistory={data.branch_history}
            onBack={() => setDrillBranch(null)}
          />
        </div>
      )}
    </div>
  );
}

function buybackStatusLabel(status: Buyback["status"]) {
  return status === "in_progress" ? "進行中" : "狀態未提供";
}

function buybackValue(value: number | null | undefined) {
  return value == null ? "資料未提供" : value.toLocaleString("zh-TW");
}

function currentActiveThemes(recentThemeHeat: RecentThemeHeat[] | undefined, quoteDate: string) {
  // The compact identity label must be stricter than a classification: an old,
  // ineligible, or unknown snapshot is never described as currently active.
  return (recentThemeHeat ?? []).filter(
    (theme) => theme.eligible && theme.status === "active" && theme.heat_date === quoteDate,
  );
}

function absoluteHttpUrl(source: string | null) {
  const trimmed = source?.trim();
  if (!trimmed || !/^https?:\/\//i.test(trimmed)) return null;
  try {
    new URL(trimmed);
    return trimmed;
  } catch {
    return null;
  }
}

function themeStatusLabel(status: CompanyTheme["status"]) {
  if (status === "active") return "有效";
  if (status === "stale") return "過時";
  if (status === "retired") return "停用";
  return "狀態未提供";
}

function BasicInfoPanel({ data, quoteDate }: { data: StockJson; quoteDate: string }) {
  const profile = data.company_profile;
  const buyback = data.buyback;
  const classifications = data.company_themes ?? [];
  const recent = currentActiveThemes(data.recent_theme_heat, quoteDate);
  const relatedButNotCurrent = (data.recent_theme_heat ?? []).filter((theme) => !recent.includes(theme));
  const period = buyback?.start_date && buyback.end_date
    ? `${buyback.start_date} 至 ${buyback.end_date}`
    : "期間資料未提供";
  const priceRange = buyback?.price_min != null || buyback?.price_max != null
    ? `${buyback?.price_min ?? "資料未提供"}～${buyback?.price_max ?? "資料未提供"} 元/股`
    : "資料未提供";

  return (
    <section role="tabpanel" aria-label="基本資料" className="mt-3.5 min-w-0 overflow-hidden rounded-[var(--r-lg)] border border-border bg-card shadow-[var(--shadow-card)]">
      <section className="min-w-0 p-3.5" aria-labelledby="company-info-heading">
        <div className="mb-3 flex items-center gap-2">
          <Building2 size={17} className="text-[color:var(--accent-2)]" aria-hidden="true" />
          <h2 id="company-info-heading" className="text-sm font-bold">公司資料</h2>
        </div>
        <dl className="grid gap-2.5 text-sm sm:grid-cols-2">
          <div className="min-w-0 rounded-[var(--r-sm)] border border-[color:var(--line)] bg-secondary/35 p-3">
            <dt className="flex items-center gap-1.5 text-xs text-muted-foreground"><MapPin size={14} aria-hidden="true" /> 公司地址</dt>
            <dd className="mt-1.5 break-words font-medium text-[color:var(--ink-2)]">{profile?.address ?? "資料未提供"}</dd>
          </div>
          <div className="min-w-0 rounded-[var(--r-sm)] border border-[color:var(--line)] bg-secondary/35 p-3">
            <dt className="flex items-center gap-1.5 text-xs text-muted-foreground"><Phone size={14} aria-hidden="true" /> 股務代理</dt>
            <dd className="mt-1.5 break-words font-medium text-[color:var(--ink-2)]">
              {profile?.transfer_agent ?? "資料未提供"}
              {profile?.transfer_agent_phone ? `（${profile.transfer_agent_phone}）` : ""}
              {profile?.transfer_agent_address ? `；${profile.transfer_agent_address}` : ""}
            </dd>
          </div>
          <div className="min-w-0 rounded-[var(--r-sm)] border border-[color:var(--line)] bg-secondary/35 p-3">
            <dt className="flex items-center gap-1.5 text-xs text-muted-foreground"><Building2 size={14} aria-hidden="true" /> 產業代碼</dt>
            <dd className="mt-1.5 font-medium text-[color:var(--ink-2)]">{profile?.industry_code ?? "資料未提供"}</dd>
          </div>
          <div className="min-w-0 rounded-[var(--r-sm)] border border-[color:var(--line)] bg-secondary/35 p-3">
            <dt className="flex items-center gap-1.5 text-xs text-muted-foreground"><ShieldCheck size={14} aria-hidden="true" /> 官方資料日與來源</dt>
            <dd className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 font-medium text-[color:var(--ink-2)]">
              <span>{profile?.source_updated_at ?? "資料未提供"}</span>
              {profile?.source ? (
                <a className="inline-flex min-h-11 items-center font-semibold text-primary underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" href={profile.source} target="_blank" rel="noreferrer">官方來源</a>
              ) : <span className="text-muted-foreground">官方來源未提供</span>}
            </dd>
          </div>
        </dl>
        {!!data.company_groups?.length && (
          <div className="mt-3 border-t border-[color:var(--line)] pt-3">
            <p className="text-xs text-muted-foreground">集團</p>
            <div className="mt-1.5 flex flex-wrap gap-2">
              {data.company_groups.map((group) => (
                <a key={group.id} href={`/group?id=${encodeURIComponent(group.id)}`} className="inline-flex min-h-11 items-center gap-1 rounded-full border border-[color:var(--accent-2)]/40 px-2.5 text-xs font-semibold text-[color:var(--accent-2)] transition-colors duration-200 hover:bg-[color:var(--accent-2)]/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" title={`查看${group.name}成員股`}>
                  <Building2 size={14} aria-hidden="true" /> {group.name}
                </a>
              ))}
            </div>
          </div>
        )}
      </section>

      <section className="min-w-0 border-t border-[color:var(--line)] p-3.5" aria-labelledby="theme-info-heading">
        <div className="mb-3 flex items-center gap-2">
          <Tags size={17} className="text-[color:var(--accent-2)]" aria-hidden="true" />
          <h2 id="theme-info-heading" className="text-sm font-bold">題材</h2>
        </div>
        {classifications.length ? (
          <div className="flex min-w-0 flex-wrap gap-2">
            {classifications.map((theme) => {
              const sourceUrl = absoluteHttpUrl(theme.source);
              return (
                <div key={theme.id} className="min-w-0 rounded-[var(--r-sm)] border border-[color:var(--line)] bg-secondary/35 px-2.5 py-2 text-xs">
                  <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                    {sourceUrl ? (
                      <a className="inline-flex min-h-11 max-w-full items-center font-semibold text-primary underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" href={sourceUrl} target="_blank" rel="noreferrer" aria-label={`查看 ${theme.name} 題材來源：${sourceUrl}`} title={`${theme.name} 題材來源：${sourceUrl}`}>
                        {theme.name}
                      </a>
                    ) : <span className="font-semibold text-foreground">{theme.name}</span>}
                    {theme.status && (
                      <span className={theme.status === "active" ? "text-[color:var(--accent-2)]" : "text-muted-foreground"}>{themeStatusLabel(theme.status)}</span>
                    )}
                  </div>
                  {(theme.data_date || theme.source_updated_at) && (
                    <p className="mt-0.5 flex flex-wrap gap-x-2 text-[10.5px] text-muted-foreground">
                      {theme.data_date && <span title="分類日">分類 {theme.data_date}</span>}
                      {theme.source_updated_at && <span title="來源更新日">更新 {theme.source_updated_at}</span>}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        ) : <p className="text-sm text-muted-foreground">尚無題材分類資料。</p>}
        {recent.length > 0 ? (
          <div className="mt-3 flex min-w-0 items-start gap-2 rounded-[var(--r-sm)] bg-[color:var(--warn)]/8 p-2.5 text-sm text-[color:var(--ink-2)]">
            <Flame size={16} className="mt-0.5 shrink-0 text-[color:var(--warn)]" aria-hidden="true" />
            <div className="min-w-0"><span className="font-semibold text-foreground">近期可能相關題材</span><span className="ml-1.5">{recent.map((theme) => `${theme.name}（量能 ${theme.vs20 == null ? "資料不足" : `${theme.vs20}×`}、資料日 ${theme.heat_date}）`).join("、")}</span></div>
          </div>
        ) : relatedButNotCurrent.length > 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">題材熱度資料未與本檔報價日一致或分類已非有效，僅保留分類參考，不標示近期關聯。</p>
        ) : <p className="mt-3 text-sm text-muted-foreground">尚無可核驗的當日有效題材熱度；不代表沒有題材。</p>}
      </section>

      <section className="min-w-0 border-t border-[color:var(--line)] p-3.5" aria-labelledby="buyback-info-heading">
        <div className="mb-3 flex items-center gap-2"><ShieldCheck size={17} className="text-[color:var(--warn)]" aria-hidden="true" /><h2 id="buyback-info-heading" className="text-sm font-bold">庫藏股</h2></div>
        {buyback ? (
          <div className="grid gap-1.5 text-sm text-[color:var(--ink-2)]">
            <p><span className="font-semibold text-foreground">庫藏股買回期間</span> <span className="text-[color:var(--warn)]">{buybackStatusLabel(buyback.status)}（MOPS {buyback.completed_flag ?? "狀態未提供"}）</span></p>
            <p>期間：{period}</p><p>預定／已執行：{buybackValue(buyback.planned_shares)}／{buybackValue(buyback.executed_shares)} 股</p><p>價格區間：{priceRange}</p><p className="break-words">目的：{buyback.purpose ?? "資料未提供"}</p><p>來源：官方 MOPS t35sc09 · 出表日 {buyback.report_date ?? "資料未提供"}</p>
          </div>
        ) : <p className="text-sm text-muted-foreground">本次資料未提供庫藏股欄位；舊版資料缺此欄位不表示沒有買回計畫。</p>}
      </section>
    </section>
  );
}

/** IA-2 + F3: Decision Header — shown before chart to answer "why is this here + when to exit" */
function StockDecisionHeader({
  data,
  close,
  defaultCollapsed = true,
  className,
}: {
  data: StockJson;
  close: number;
  defaultCollapsed?: boolean;
  className?: string;
}) {
  const scores = data.scores;
  // 個股頁詳情區不設家族數上限;帶 code 的 raw_reasons 用來判語意家族色,缺時退回純文字(中性)。
  const reasons = (data.raw_reasons?.length ? data.raw_reasons : (data.reasons ?? []).map((text) => ({ text, code: undefined }))).slice(0, 3);
  const risks = (data.risks ?? []).slice(0, 2);
  const watchPrice = scores?.watch_price;
  const stopPrice = scores?.stop_price;
  const [open, setOpen] = useState(!defaultCollapsed);

  const distPct = (price: number, target: number) =>
    ((price - target) / Math.abs(target)) * 100;

  // Source badge: branch / warrant / both
  const hasBranch = (scores?.branch ?? 0) > 0;
  const hasWarrant = (scores?.warrant ?? 0) > 0;
  const sourceLabel = hasBranch && hasWarrant ? "分點+權證" : hasBranch ? "分點" : hasWarrant ? "權證" : null;
  const primaryJudgment = reasons[0]?.text ?? (risks[0] ? `注意：${risks[0]}` : "尚無可顯示的判讀理由");

  if (!scores && !reasons.length && !risks.length && !(data.pocket_tags?.length)) return null;

  return (
    <div data-testid="stock-decision" className={cn("mb-2.5 min-w-0 overflow-hidden rounded-[var(--r-lg)] border border-border bg-card shadow-[var(--shadow-card)]", className)}>
      <button
        type="button"
        className="flex w-full min-w-0 items-center gap-3 px-3.5 py-3 text-left transition-colors duration-200 hover:bg-secondary/60"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {scores && (
          <span className={cn("num min-w-14 shrink-0 text-center text-[34px] font-extrabold leading-none sm:min-w-16 sm:text-[38px]", scores.final >= 65 ? "text-warn" : "text-[color:var(--ink-2)]")}>
            {scores.final}
          </span>
        )}
        <span className="min-w-0 flex-1">
          <span className="flex min-w-0 items-center gap-1.5 text-[11.5px] text-muted-foreground">
            綜合評分
            {sourceLabel && <span className="rounded-md bg-[color:var(--ink-2)]/10 px-1.5 py-0.5 text-[10.5px] font-bold text-[color:var(--ink-2)]">{sourceLabel}</span>}
          </span>
          <span data-testid="stock-primary-judgment" className="mt-1 block truncate text-[14px] font-semibold text-foreground" title={primaryJudgment}>{primaryJudgment}</span>
        </span>
        <span className="ml-auto flex shrink-0 items-center gap-2 text-[11.5px]">
          {watchPrice != null && (
            <span className="hidden items-center gap-1 rounded-md border border-[color:var(--line)] px-2 py-0.5 text-[color:var(--accent-2)] md:inline-flex">
              <span>觀察</span>
              <span className="num font-bold">{watchPrice.toFixed(2)}</span>
            </span>
          )}
          {stopPrice != null && (
            <span className={cn(
              "hidden items-center gap-1 rounded-md border px-2 py-0.5 md:inline-flex",
              distPct(close, stopPrice) < 5 ? "border-destructive/40 text-destructive" : "border-[color:var(--line)] text-up",
            )}>
              <span>失效</span>
              <span className="num font-bold">{stopPrice.toFixed(2)}</span>
            </span>
          )}
          {open ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
        </span>
      </button>

      {open && (
        <div className="border-t border-[color:var(--line)] px-3.5 py-3">
          <div className="mb-2.5 flex min-w-0 flex-wrap gap-2 text-[11.5px] md:hidden">
            {watchPrice != null && (
              <span className="flex items-center gap-1 rounded-md border border-[color:var(--line)] px-2 py-0.5 text-[color:var(--accent-2)]">
                <span>觀察</span>
                <span className="num font-bold">{watchPrice.toFixed(2)}</span>
                <span className="text-muted-foreground">
                  ({distPct(close, watchPrice) > 0 ? "+" : ""}{distPct(close, watchPrice).toFixed(1)}%)
                </span>
              </span>
            )}
            {stopPrice != null && (
              <span className={cn(
                "flex items-center gap-1 rounded-md border px-2 py-0.5",
                distPct(close, stopPrice) < 5 ? "border-destructive/40 text-destructive" : "border-[color:var(--line)] text-up",
              )}>
                <span>失效</span>
                <span className="num font-bold">{stopPrice.toFixed(2)}</span>
                <span className={cn("text-muted-foreground", distPct(close, stopPrice) < 5 && "text-destructive")}>
                  ({distPct(close, stopPrice) > 0 ? "+" : ""}{distPct(close, stopPrice).toFixed(1)}%)
                </span>
              </span>
            )}
          </div>
          {(reasons.length > 0 || risks.length > 0 || (data.pocket_tags?.length ?? 0) > 0) && (
            <div className="flex flex-wrap gap-1.5">
              {reasons.map((r, i) => (
                <ReasonPill key={`reason-${i}`} code={r.code} text={r.text} />
              ))}
              <PocketBadges tags={data.pocket_tags} compact={false} />
              {risks.map((r, i) => (
                <ReasonPill key={`risk-${i}`} text={r} risk />
              ))}
            </div>
          )}
          {(watchPrice != null || stopPrice != null) && (
            <div className="mt-2.5 hidden min-w-0 flex-wrap gap-2 text-[11.5px] md:flex">
              {watchPrice != null && (
                <span className="flex items-center gap-1 rounded-md border border-[color:var(--line)] px-2 py-0.5 text-[color:var(--accent-2)]">
                  <span>觀察</span>
                  <span className="num font-bold">{watchPrice.toFixed(2)}</span>
                  <span className="text-muted-foreground">
                    ({distPct(close, watchPrice) > 0 ? "+" : ""}{distPct(close, watchPrice).toFixed(1)}%)
                  </span>
                </span>
              )}
              {stopPrice != null && (
                <span className={cn(
                  "flex items-center gap-1 rounded-md border px-2 py-0.5",
                  distPct(close, stopPrice) < 5 ? "border-destructive/40 text-destructive" : "border-[color:var(--line)] text-up",
                )}>
                  <span>失效</span>
                  <span className="num font-bold">{stopPrice.toFixed(2)}</span>
                  <span className={cn("text-muted-foreground", distPct(close, stopPrice) < 5 && "text-destructive")}>
                    ({distPct(close, stopPrice) > 0 ? "+" : ""}{distPct(close, stopPrice).toFixed(1)}%)
                  </span>
                </span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function TechnicalPanel({ data }: { data: StockJson }) {
  const t = data.technical;
  if (!t) {
    return (
      <div className="mt-3.5 flex gap-2.5 rounded-[var(--r-md)] border border-border bg-card px-4.5 py-3.5 text-sm">
        <span className="font-bold text-muted-foreground">技術</span>
        <span className="text-foreground">尚未產出技術指標;請先跑 compute-indicators。</span>
      </div>
    );
  }

  return (
    <div className="mt-3.5 min-w-0 grid gap-2.5 rounded-[var(--r-lg)] border border-border bg-card p-3.5 shadow-[var(--shadow-card)] md:grid-cols-[90px_1fr] md:items-center">
      <div className="flex flex-col gap-0.5">
        <span className="text-[11px] text-muted-foreground">技術分</span>
        <span className="num text-[30px] leading-none font-extrabold text-[color:var(--accent-2)]">{t.score}</span>
      </div>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <span className="flex justify-between gap-2 rounded-[var(--r-sm)] border border-border bg-secondary px-2.5 py-2 text-xs text-muted-foreground">
          MA20 <b className="num font-bold text-[color:var(--ink-2)]">{t.ma20 == null ? "—" : t.ma20.toFixed(2)}</b>
        </span>
        <span className="flex justify-between gap-2 rounded-[var(--r-sm)] border border-border bg-secondary px-2.5 py-2 text-xs text-muted-foreground">
          MA60 <b className="num font-bold text-[color:var(--ink-2)]">{t.ma60 == null ? "—" : t.ma60.toFixed(2)}</b>
        </span>
        <span className="flex justify-between gap-2 rounded-[var(--r-sm)] border border-border bg-secondary px-2.5 py-2 text-xs text-muted-foreground">
          RSI14 <b className="num font-bold text-[color:var(--ink-2)]">{t.rsi14 == null ? "—" : t.rsi14.toFixed(1)}</b>
        </span>
        <span className="flex justify-between gap-2 rounded-[var(--r-sm)] border border-border bg-secondary px-2.5 py-2 text-xs text-muted-foreground">
          量比 <b className="num font-bold text-[color:var(--ink-2)]">{fmtX(t.volume_ratio)}</b>
        </span>
      </div>
      {(data.scores?.watch_price != null || data.scores?.stop_price != null) && (
        <div className="flex flex-wrap gap-2 md:col-span-2">
          {data.scores?.watch_price != null && (
            <span className="rounded-[var(--r-sm)] border border-border bg-secondary px-2.5 py-2 text-xs text-muted-foreground">
              觀察價 <b className="num font-bold text-[color:var(--accent-2)]">{data.scores.watch_price.toFixed(2)}</b>
            </span>
          )}
          {data.scores?.stop_price != null && (
            <span className="rounded-[var(--r-sm)] border border-border bg-secondary px-2.5 py-2 text-xs text-muted-foreground">
              失效價 <b className="num font-bold text-up">{data.scores.stop_price.toFixed(2)}</b>
            </span>
          )}
        </div>
      )}
      <div className="flex flex-wrap gap-1.5 md:col-span-2">
        {t.reasons.length > 0 ? (
          t.reasons.map((r) => <ReasonPill key={r.code} code={r.code} text={r.text} />)
        ) : (
          <span className="rounded-full border border-[color:var(--line)] px-2 py-[3px] text-[11.5px] text-[color:var(--ink-2)]">未觸發技術加分條件</span>
        )}
      </div>
    </div>
  );
}

function WarrantPanel({ data }: { data: StockJson }) {
  const { session } = useSession();
  const [sorting, setSorting] = useState<SortingState>([]);
  const [expanded, setExpanded] = useState({});
  const maxTurnover = Math.max(1, ...data.warrant_history.map((p) => Math.max(p.call_turnover, p.put_turnover)));
  // History is ordered old→new by the export contract, so its final point is
  // the only safe per-stock data date for this summary.
  const warrantDataDate = data.warrant_history[data.warrant_history.length - 1]?.t;

  const columns = useMemo<ColumnDef<StockJson["active_warrants"][number]>[]>(
    () => [
      { accessorKey: "id", header: "代號", cell: (c) => <span className="num">{c.getValue<string>()}</span> },
      {
        accessorKey: "name",
        header: "名稱",
        cell: ({ row }) => (
          <span>
            {row.original.name}
            {!!row.original.branches?.length && (
              <span className="ml-1.5 rounded-md border border-[color:var(--line)] px-1.5 py-px text-[10.5px] whitespace-nowrap text-muted-foreground">分點</span>
            )}
          </span>
        ),
      },
      {
        accessorKey: "kind",
        header: "類型",
        cell: (c) => {
          const kind = c.getValue<string>();
          return (
            <span className={cn("rounded-md px-1.5 py-px text-[10.5px]", kind === "call" ? "text-up bg-up/15" : "text-down bg-down/15")}>
              {kind === "call" ? "認購" : "認售"}
            </span>
          );
        },
      },
      {
        accessorKey: "strike",
        header: "履約價",
        cell: (c) => <span className="num">{c.getValue<number>() == null ? "—" : c.getValue<number>().toLocaleString("zh-TW")}</span>,
      },
      { accessorKey: "maturity_date", header: "到期日", cell: (c) => <span className="num">{c.getValue<string>() ?? "—"}</span> },
      { accessorKey: "turnover", header: "成交", cell: (c) => <span className="num">{fmtE8(c.getValue<number>())}</span> },
    ],
    [],
  );

  const table = useReactTable({
    data: data.active_warrants,
    columns,
    state: { sorting, expanded },
    onSortingChange: setSorting,
    onExpandedChange: setExpanded,
    getRowCanExpand: () => true,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getExpandedRowModel: getExpandedRowModel(),
  });

  if (!data.warrant) {
    return (
      <div className="grid gap-3">
        <WarrantBranchPanel stockId={data.id} />
        <div className="py-[46px] text-center text-sm text-muted-foreground">目前沒有可彙總的權證成交資料；權證資料日未提供不代表整批資料未更新。</div>
      </div>
    );
  }

  return (
    <div className="grid gap-3">
      <WarrantBranchPanel stockId={data.id} />
      <div className="grid gap-3 rounded-[var(--r-lg)] border border-border bg-card p-3.5 shadow-[var(--shadow-card)]">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h3 className="text-sm font-bold text-foreground">權證成交摘要</h3>
        <span className="text-[11.5px] text-muted-foreground">
          權證資料日 {warrantDataDate ?? "未提供（舊版資料）"}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
        <div className="flex flex-col gap-0.5 rounded-[var(--r-sm)] border border-border bg-secondary p-2.5">
          <span className="text-[11px] text-muted-foreground">認購成交</span>
          <span className="text-base font-bold text-foreground">{fmtE8(data.warrant.call_turnover)}</span>
        </div>
        <div className="flex flex-col gap-0.5 rounded-[var(--r-sm)] border border-border bg-secondary p-2.5">
          <span className="text-[11px] text-muted-foreground">20日倍數</span>
          <span className="text-base font-bold text-foreground">{fmtX(data.warrant.call_turnover_ratio)}</span>
        </div>
        <div className="flex flex-col gap-0.5 rounded-[var(--r-sm)] border border-border bg-secondary p-2.5">
          <span className="text-[11px] text-muted-foreground">認售成交</span>
          <span className="text-base font-bold text-foreground">{fmtE8(data.warrant.put_turnover)}</span>
        </div>
        <div className="flex flex-col gap-0.5 rounded-[var(--r-sm)] border border-border bg-secondary p-2.5">
          <span className="text-[11px] text-muted-foreground">有成交檔數</span>
          <span className="text-base font-bold text-foreground">
            {data.warrant.call_count} / {data.warrant.put_count}
          </span>
        </div>
      </div>

      <div className="flex items-end gap-[3px] px-0.5 pt-2 [height:120px]" aria-label="權證60日成交金額">
        {data.warrant_history.map((p) => (
          <div key={p.t} className="grid h-full min-w-[3px] flex-1 grid-rows-2 items-end gap-px" title={`${p.t} 認購 ${fmtE8(p.call_turnover)} / 認售 ${fmtE8(p.put_turnover)}`}>
            <span className="min-h-px rounded-t-[3px] bg-up opacity-80 self-end" style={{ height: `${Math.max(2, (p.call_turnover / maxTurnover) * 100)}%` }} />
            <span className="min-h-px rounded-b-[3px] bg-down opacity-75 self-start" style={{ height: `${Math.max(2, (p.put_turnover / maxTurnover) * 100)}%` }} />
          </div>
        ))}
      </div>

      {data.active_warrants.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-xs">
            <thead>
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id}>
                  {hg.headers.map((header, i) => {
                    const sorted = header.column.getIsSorted();
                    const canSort = header.column.getCanSort();
                    return (
                      <th
                        key={header.id}
                        aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : canSort ? "none" : undefined}
                        className={cn(
                          "border-t border-[color:var(--line)] px-1.5 py-2 font-semibold text-muted-foreground select-none",
                          i < 2 ? "text-left" : "text-right",
                          sorted && "bg-primary/10 text-primary",
                        )}
                      >
                        {canSort ? (
                          <button
                            type="button"
                            onClick={header.column.getToggleSortingHandler()}
                            className={cn("inline-flex items-center gap-0.5", i >= 2 && "w-full justify-end")}
                          >
                            {flexRender(header.column.columnDef.header, header.getContext())}
                            {sorted === "asc" && <ChevronUp size={12} />}
                            {sorted === "desc" && <ChevronDown size={12} />}
                          </button>
                        ) : (
                          <span className={cn("inline-flex items-center gap-0.5", i >= 2 && "justify-end")}>
                            {flexRender(header.column.columnDef.header, header.getContext())}
                          </span>
                        )}
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row) => (
                <Fragment key={row.id}>
                  <tr
                    className="cursor-pointer"
                    onClick={row.getToggleExpandedHandler()}
                    title={row.original.branches?.length ? "點擊展開分點進出" : "此權證無分點資料(上櫃權證無來源)"}
                  >
                    {row.getVisibleCells().map((cell, i) => (
                      <td key={cell.id} className={cn("border-t border-[color:var(--line)] px-1.5 py-2 text-[color:var(--ink-2)]", i < 2 ? "text-left" : "text-right")}>
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                  {row.getIsExpanded() && (
                    <tr className="bg-secondary">
                      <td colSpan={columns.length} className="!px-2.5 !py-2">
                        {!session ? (
                          <button
                            className="rounded-full border border-[color:var(--border-strong)] bg-card px-3.5 py-1.5 text-[12.5px] font-semibold text-primary hover:bg-muted"
                            onClick={signInWithGoogle}
                          >
                            以 Google 登入後查看分點進出明細
                          </button>
                        ) : row.original.branches?.length ? (
                          <div className="flex flex-wrap gap-x-3.5 gap-y-1.5 text-xs">
                            {row.original.branches.map((b) => (
                              <span key={b.name} className="inline-flex items-baseline gap-1.5">
                                <span className="text-[color:var(--ink-2)]">{b.name}</span>
                                <span className={cn("num font-bold", b.net > 0 ? "text-up" : b.net < 0 ? "text-down" : "text-foreground")}>
                                  {b.net > 0 ? "+" : ""}
                                  {b.net.toLocaleString("zh-TW")}張
                                </span>
                              </span>
                            ))}
                            <span className="text-xs text-muted-foreground">※ 權證分點多為發行商造市部位,重點看非發行商大額買超</span>
                          </div>
                        ) : (
                          <span className="text-xs text-muted-foreground">此權證無分點資料(僅上市權證有免費來源,且僅榜單熱門權證每晚抓取)</span>
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="py-[46px] text-center text-sm text-muted-foreground">今日沒有權證成交明細</div>
      )}
      </div>
    </div>
  );
}

export default function StockPage() {
  return (
    <Suspense fallback={<div className="py-[46px] text-center text-sm text-muted-foreground">載入中…</div>}>
      <StockView />
    </Suspense>
  );
}
