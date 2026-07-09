"use client";

import { useEffect, useMemo, useState } from "react";
import { IconCompass, IconFlame } from "@/components/Icons";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import type { RadarJson } from "@/lib/types";
import { MARKET_LABEL, chgClass, fmtE8, fmtPct, fmtX } from "@/lib/format";
import { cn } from "@/lib/utils";

const TABS = [
  { key: "concentration", label: "集中度", hint: "前5大買超分點佔成交量比,躍升幅度排序", icon: IconCompass },
  { key: "theme", label: "題材", hint: "題材成分股資金流與漲跌,依成交金額排序", icon: IconFlame },
] as const;

type TabKey = (typeof TABS)[number]["key"];

const CHG_TEXT: Record<string, string> = { up: "text-up", down: "text-down", flat: "text-foreground" };

export default function ExplorePage() {
  const [radar, setRadar] = useState<RadarJson | null>(null);
  const [error, setError] = useState(false);
  const [tab, setTab] = useState<TabKey>("concentration");

  useEffect(() => {
    fetch("/data/radar.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setRadar)
      .catch(() => setError(true));
  }, []);

  if (error) {
    return <div className="py-[46px] text-center text-sm text-muted-foreground">資料載入失敗,請稍後再試。</div>;
  }
  if (!radar) return <Skeleton className="my-4 h-[68px] rounded-[var(--r-md)]" />;

  return (
    <>
      <div className="my-1.5 mb-3 flex items-center gap-2.5">
        <div role="tablist" className="flex gap-0.5 rounded-full border border-border bg-card p-[3px]">
          {TABS.map((t) => (
            <button
              key={t.key}
              role="tab"
              aria-selected={tab === t.key}
              onClick={() => setTab(t.key)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-[13.5px] font-semibold text-muted-foreground transition-colors",
                tab === t.key && "bg-muted text-foreground shadow-[inset_0_0_0_1px_var(--border-strong)]",
              )}
            >
              <t.icon size={16} className="opacity-85" />
              {t.label}
            </button>
          ))}
        </div>
        <span className="hidden text-xs text-muted-foreground lg:inline">{TABS.find((t) => t.key === tab)?.hint}</span>
      </div>

      {tab === "concentration" && <ConcentrationTab radar={radar} />}
      {tab === "theme" && <ThemeTab radar={radar} />}
    </>
  );
}

function EmptyNotice({ tag, children }: { tag: string; children: React.ReactNode }) {
  return (
    <Alert className="mt-3.5 bg-card">
      <AlertDescription className="flex flex-wrap items-baseline gap-2.5 text-[13px] text-foreground">
        <span className="shrink-0 rounded-md bg-[color:var(--ink-2)]/10 px-2 py-0.5 text-[11.5px] font-bold tracking-[0.3px] text-[color:var(--ink-2)]">{tag}</span>
        <span>{children}</span>
      </AlertDescription>
    </Alert>
  );
}

function ConcentrationTab({ radar }: { radar: RadarJson }) {
  const rows = radar.concentration ?? [];
  if (rows.length === 0) {
    return <EmptyNotice tag="集中度">今日無符合條件的集中度資料(需有分點與成交量紀錄)。</EmptyNotice>;
  }
  return (
    <div className="mt-1 flex flex-col gap-1.5 pb-7">
      <div className="grid grid-cols-[1.6fr_1fr_1fr_1fr] gap-2 px-3.5 text-[11.5px] text-muted-foreground">
        <span>股票</span>
        <span>前5大買超佔量</span>
        <span>20日均</span>
        <span>躍升幅度</span>
      </div>
      {rows.map((r) => (
        <a
          key={r.id}
          href={`/stock?id=${r.id}`}
          className="num grid grid-cols-[1.6fr_1fr_1fr_1fr] items-center gap-2 rounded-[var(--r-md)] border border-border bg-card px-3.5 py-2.5 text-[13px] text-[color:var(--ink-2)]"
        >
          <span className="flex flex-col gap-0.5 font-sans">
            <b className="text-sm font-bold text-foreground">{r.name}</b>
            <small className="text-[11px] text-muted-foreground">
              {r.id} · {MARKET_LABEL[r.market] ?? r.market}
            </small>
          </span>
          <span>{(r.buy_concentration * 100).toFixed(1)}%</span>
          <span>{(r.concentration_avg20 * 100).toFixed(1)}%</span>
          <span className="font-bold text-warn">{fmtX(r.vs20)}</span>
        </a>
      ))}
    </div>
  );
}

function ThemeTab({ radar }: { radar: RadarJson }) {
  const themes = useMemo(() => [...(radar.themes ?? [])].sort((a, b) => b.turnover - a.turnover), [radar.themes]);
  if (themes.length === 0) {
    return <EmptyNotice tag="題材">今日無符合門檻的題材資料。</EmptyNotice>;
  }
  return (
    <div className="mt-1 flex flex-col gap-1.5 pb-7">
      <div className="grid grid-cols-[1.4fr_0.9fr_0.9fr_0.9fr_0.9fr] gap-2 px-3.5 text-[11.5px] text-muted-foreground">
        <span>題材</span>
        <span>成交金額</span>
        <span>vs20日均</span>
        <span>今日均漲</span>
        <span>上漲比</span>
      </div>
      {themes.map((t) => {
        const total = t.up + t.down;
        const upRatio = total > 0 ? (t.up / total) * 100 : null;
        return (
          <div key={t.name} className="num grid grid-cols-[1.4fr_0.9fr_0.9fr_0.9fr_0.9fr] items-center gap-2 rounded-[var(--r-md)] border border-border bg-card px-3.5 py-2.5 text-[13px] text-[color:var(--ink-2)]">
            <span className="font-sans font-bold text-foreground">{t.name}</span>
            <span>{fmtE8(t.turnover)}</span>
            <span className={t.vs20 != null && t.vs20 >= 1 ? "font-bold text-warn" : undefined}>{fmtX(t.vs20)}</span>
            <span className={CHG_TEXT[chgClass(t.avg_chg)]}>{fmtPct(t.avg_chg)}</span>
            <span>{upRatio == null ? "—" : `${upRatio.toFixed(0)}%`}</span>
            <div className="col-span-full mt-1.5 flex flex-wrap gap-1.5 border-t border-dashed border-[color:var(--line)] pt-2">
              {t.top.slice(0, 5).map((s) => (
                <a
                  key={s.id}
                  href={`/stock?id=${s.id}`}
                  className="inline-flex items-center gap-1.5 rounded-full border border-border bg-secondary px-2.5 py-1 font-sans text-[11.5px] text-[color:var(--ink-2)]"
                >
                  {s.name}
                  <em className={cn("not-italic", CHG_TEXT[chgClass(s.chg_pct)])}>{fmtPct(s.chg_pct)}</em>
                </a>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
