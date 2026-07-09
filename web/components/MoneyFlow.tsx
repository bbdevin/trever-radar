"use client";

import { useMemo, useState } from "react";
import type { SectorFlow } from "@/lib/types";
import { chgClass, fmtE8, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";

type Mode = "industry" | "theme";
type SortBy = "volume" | "price";

/** 相對 20 日常態的偏離 %(+96 = 資金量能 1.96×) */
function dev(g: SectorFlow): number | null {
  return g.vs20 == null ? null : Math.round((g.vs20 - 1) * 100);
}

const CAP = 150; // 條長上限 ±150%

const segTabClass = (active: boolean) =>
  cn(
    "rounded-full px-3 py-1 text-[12.5px] font-semibold text-muted-foreground transition-colors",
    active && "bg-muted text-foreground shadow-[inset_0_0_0_1px_var(--border-strong)]",
  );

/** 資金流向 v2:以 20 日常態為中軸的流入/流出對向條。
    右紅=資金湧入、左綠=退潮;條長=偏離幅度、列序=強度。 */
export default function MoneyFlow({ sectors, themes }: { sectors: SectorFlow[]; themes?: SectorFlow[] }) {
  const [mode, setMode] = useState<Mode>("industry");
  const [sortBy, setSortBy] = useState<SortBy>("volume");
  const [selected, setSelected] = useState<string | null>(null);
  const hasThemes = !!themes?.length;

  const { inflow, outflow, maxAbs } = useMemo(() => {
    const src = (mode === "theme" && hasThemes ? themes! : sectors).filter(
      (g) => g.vs20 != null && g.turnover >= (mode === "theme" ? 1e9 : 2e9),
    );
    let ins = src;
    let outs = src;

    if (sortBy === "volume") {
      ins = src.filter((g) => (g.vs20 as number) >= 1.15)
        .sort((a, b) => (b.vs20 as number) - (a.vs20 as number)).slice(0, 7);
      outs = src.filter((g) => (g.vs20 as number) <= 0.85)
        .sort((a, b) => (a.vs20 as number) - (b.vs20 as number)).slice(0, 7);
    } else {
      ins = src.filter((g) => g.avg_chg != null && g.avg_chg >= 1.5)
        .sort((a, b) => b.avg_chg! - a.avg_chg!).slice(0, 7);
      outs = src.filter((g) => g.avg_chg != null && g.avg_chg <= -1.5)
        .sort((a, b) => a.avg_chg! - b.avg_chg!).slice(0, 7);
    }

    const all = [...ins, ...outs].map((g) => Math.min(Math.abs(sortBy === "volume" ? (dev(g) ?? 0) : ((g.avg_chg ?? 0) * 10)), CAP));
    return { inflow: ins, outflow: outs, maxAbs: Math.max(...all, 30) };
  }, [mode, sortBy, sectors, themes, hasThemes]);

  const sel =
    [...inflow, ...outflow].find((g) => g.name === selected) ??
    (mode === "theme" && hasThemes ? themes! : sectors).find((g) => g.name === selected) ??
    null;

  const Row = ({ g, side }: { g: SectorFlow; side: "in" | "out" }) => {
    const d = sortBy === "volume" ? Math.min(Math.abs(dev(g) ?? 0), CAP) : Math.min(Math.abs((g.avg_chg ?? 0) * 10), CAP);
    const width = (d / maxAbs) * 100;
    return (
      <button
        className={cn(
          "grid w-full grid-cols-[86px_1fr_auto] items-center gap-2.5 rounded-[10px] px-2 py-1.5 text-left text-foreground transition-colors hover:bg-secondary",
          selected === g.name && "bg-secondary shadow-[inset_0_0_0_1px_var(--border-strong)]",
        )}
        onClick={() => setSelected(selected === g.name ? null : g.name)}
      >
        <span
          className={cn(
            "truncate text-[13px] font-semibold text-[color:var(--ink-2)] transition-colors",
            (selected === g.name) && "text-foreground",
          )}
        >
          {g.name}
        </span>
        <span className="flex min-w-0 items-center gap-2">
          <span
            className={cn(
              "h-3.5 shrink-0 rounded transition-[width] duration-500 [transition-timing-function:cubic-bezier(0.22,1,0.36,1)]",
              side === "in"
                ? "bg-[linear-gradient(90deg,rgba(230,103,103,0.35),rgba(230,103,103,0.95))]"
                : "bg-[linear-gradient(90deg,rgba(12,163,12,0.9),rgba(12,163,12,0.3))]",
            )}
            style={{ width: `${Math.max(width, 6)}%` }}
          />
          <span
            className={cn("num whitespace-nowrap text-xs font-bold", side === "in" ? "text-up" : "text-down")}
            title={`今日成交金額為近20日平均的 ${g.vs20!.toFixed(2)} 倍`}
          >
            {dev(g)! > 0 ? "+" : ""}
            {dev(g)}%
          </span>
        </span>
        <span className="flex flex-col items-end gap-0 leading-[1.3]">
          <b className="num text-xs font-semibold text-[color:var(--ink-2)]">{fmtE8(g.turnover)}</b>
          <span className={cn("num text-[11px]", chgClass(g.avg_chg) === "up" ? "text-up" : chgClass(g.avg_chg) === "down" ? "text-down" : "text-foreground")}>
            {g.avg_chg != null ? `${g.avg_chg > 0 ? "+" : ""}${g.avg_chg.toFixed(1)}%` : "—"}
          </span>
        </span>
      </button>
    );
  };

  return (
    <section className="mb-3.5 rounded-[var(--r-lg)] border border-border bg-card p-3.5 shadow-[var(--shadow-card)]">
      <div className="mb-2.5 flex flex-wrap items-center gap-3">
        <h2 className="text-[15px] font-bold">資金流向</h2>
        <div className="inline-flex gap-0.5 rounded-full border border-border bg-card p-[3px]">
          <button className={segTabClass(mode === "industry")} onClick={() => { setMode("industry"); setSelected(null); }}>
            產業
          </button>
          <button
            className={cn(segTabClass(mode === "theme"), !hasThemes && "cursor-not-allowed opacity-50")}
            onClick={() => { setMode("theme"); setSelected(null); }}
            disabled={!hasThemes}
            title={hasThemes ? "概念股分類(成分重疊)" : "題材資料累積中"}
          >
            題材
          </button>
        </div>
        <div className="ml-auto inline-flex gap-0.5 rounded-full border border-border bg-card p-[3px]">
          <button className={segTabClass(sortBy === "volume")} onClick={() => { setSortBy("volume"); setSelected(null); }}>
            資金量能
          </button>
          <button className={segTabClass(sortBy === "price")} onClick={() => { setSortBy("price"); setSelected(null); }}>
            漲跌幅
          </button>
        </div>
      </div>
      <span className="text-[11px] text-muted-foreground">
        {sortBy === "volume"
          ? "基準=近20日平均成交金額;+80% = 今日資金比平時多八成、−20% = 比平時少兩成"
          : "依據該族群個股平均漲跌幅排序，找出族群性大漲或大跌板塊"}
      </span>

      {inflow.length === 0 && outflow.length === 0 ? (
        <div className="py-5 text-center text-sm text-muted-foreground">
          今日各{mode === "theme" ? "題材" : "產業"}量能都貼近 20 日常態,無明顯資金移動
        </div>
      ) : (
        <div className="mt-2.5 grid grid-cols-1 gap-x-6.5 gap-y-2 md:grid-cols-2">
          <div className="order-2 flex min-w-0 flex-col gap-1.5 md:order-none">
            <div className="mb-0.5 border-b border-[color:var(--line)] pb-1 text-xs font-bold tracking-[1px] text-down">
              {sortBy === "volume" ? "流出 ↓ 比平時冷清" : "弱勢 ↓ 族群性下跌"}
            </div>
            {outflow.length ? (
              outflow.map((g) => <Row key={g.name} g={g} side="out" />)
            ) : (
              <div className="p-2 text-xs text-muted-foreground">無明顯{sortBy === "volume" ? "退潮" : "弱勢"}</div>
            )}
          </div>
          <div className="flex min-w-0 flex-col gap-1.5">
            <div className="mb-0.5 border-b border-[color:var(--line)] pb-1 text-xs font-bold tracking-[1px] text-up">
              {sortBy === "volume" ? "流入 ↑ 比平時熱絡" : "強勢 ↑ 族群性上漲"}
            </div>
            {inflow.length ? (
              inflow.map((g) => <Row key={g.name} g={g} side="in" />)
            ) : (
              <div className="p-2 text-xs text-muted-foreground">無明顯{sortBy === "volume" ? "湧入" : "強勢"}</div>
            )}
          </div>
        </div>
      )}

      {sel && (
        <div className="mt-2.5 border-t border-dashed border-[color:var(--line)] pt-2.5">
          <div className="mb-2 flex items-baseline gap-2.5 text-[13.5px]">
            <b>{sel.name}</b>
            <span className="text-xs text-muted-foreground">
              {fmtE8(sel.turnover)} · 量能{sel.vs20 != null ? `${sel.vs20.toFixed(1)}×` : "—"} ·{" "}
              <span className="text-up">↑{sel.up}</span>/<span className="text-down">↓{sel.down}</span>
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            {sel.top.map((t) => {
              const c = chgClass(t.chg_pct);
              return (
                <a
                  key={t.id}
                  href={`/stock?id=${t.id}`}
                  className="inline-flex items-baseline gap-2 rounded-[10px] border border-border bg-secondary px-2.5 py-1.5 text-[12.5px] text-foreground hover:border-[color:var(--border-strong)]"
                >
                  <span className="text-[color:var(--ink-2)]">{t.name}</span>
                  <span className={cn("num font-bold", c === "up" ? "text-up" : c === "down" ? "text-down" : "text-foreground")}>
                    {fmtPct(t.chg_pct)}
                  </span>
                  {t.turnover != null && <span className="num text-[11px] text-muted-foreground">{fmtE8(t.turnover)}</span>}
                </a>
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
}
