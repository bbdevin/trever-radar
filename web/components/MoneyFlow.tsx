"use client";

import { useMemo, useState } from "react";
import { ChevronRight, X } from "lucide-react";
import type { SectorFlow } from "@/lib/types";
import { chgClass, fmtE8, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";

type Mode = "industry" | "theme";
type SortBy = "volume" | "price";

/** 相對 20 日常態的偏離 %(+96 = 資金量能 1.96×) */
function dev(g: { vs20: number | null }): number | null {
  return g.vs20 == null ? null : Math.round((g.vs20 - 1) * 100);
}

const CAP = 150; // 條長上限 ±150%
const ALL_SUB = "__all__"; // 下鑽面板「全部成分股」sentinel

const segTabClass = (active: boolean) =>
  cn(
    "rounded-full px-3 py-1 text-[12.5px] font-semibold text-muted-foreground transition-colors",
    active && "bg-muted text-foreground shadow-[inset_0_0_0_1px_var(--border-strong)]",
  );

/** 成分股 chips(下鑽共用;sub.top 無 turnover 時自動省略該欄) */
function StockChips({ items }: { items: { id: string; name: string; chg_pct: number | null; turnover?: number }[] }) {
  return (
    <div className="flex flex-wrap gap-2 animate-[fadeUp_0.25s_ease_backwards]">
      {items.map((t) => {
        const c = chgClass(t.chg_pct);
        return (
          <a
            key={t.id}
            href={`/stock?id=${t.id}`}
            className="inline-flex min-h-9 items-center gap-2 rounded-[10px] border border-border bg-secondary px-2.5 py-1.5 text-[12.5px] text-foreground transition-colors hover:border-[color:var(--border-strong)]"
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
  );
}

/** vs20 量能徽章:文字自帶 +/-,顏色不作唯一訊號 */
function Vs20Badge({ vs20 }: { vs20: number | null }) {
  const d = dev({ vs20 });
  return (
    <span
      className={cn(
        "num shrink-0 rounded-full border px-1.5 py-px text-[10.5px] font-bold",
        d == null
          ? "border-border text-muted-foreground"
          : d >= 0
            ? "border-[color:color-mix(in_srgb,var(--up)_45%,transparent)] text-up"
            : "border-[color:color-mix(in_srgb,var(--down)_45%,transparent)] text-down",
      )}
      title={vs20 != null ? `今日成交金額為近20日平均的 ${vs20.toFixed(2)} 倍` : "近20日均量資料不足"}
    >
      量能{d == null ? "—" : `${d > 0 ? "+" : ""}${d}%`}
    </span>
  );
}

/** 資金流向 v2:以 20 日常態為中軸的流入/流出對向條。
    左紅=資金湧入、右綠=退潮;條長=偏離幅度、列序=強度。
    產業模式下鑽:族群 → 子題材 → 成分股。 */
export default function MoneyFlow({ sectors, themes }: { sectors: SectorFlow[]; themes?: SectorFlow[] }) {
  const [mode, setMode] = useState<Mode>("industry");
  const [sortBy, setSortBy] = useState<SortBy>("volume");
  const [selected, setSelected] = useState<string | null>(null);
  const [subSel, setSubSel] = useState<string | null>(null);
  const hasThemes = !!themes?.length;

  const select = (name: string | null) => {
    setSelected(name);
    setSubSel(null);
  };

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

  /** 族群列:名稱(固定寬截斷)｜條軌(flex 欄,條只在軌內縮放)｜數值區(固定寬,永不被條侵入) */
  const Row = ({ g, side }: { g: SectorFlow; side: "in" | "out" }) => {
    const d = sortBy === "volume" ? Math.min(Math.abs(dev(g) ?? 0), CAP) : Math.min(Math.abs((g.avg_chg ?? 0) * 10), CAP);
    const ratio = Math.max((d / maxAbs) * 100, 6) / 100;
    const dv = dev(g);
    const c = chgClass(g.avg_chg);
    return (
      <button
        className={cn(
          "grid min-h-11 w-full cursor-pointer grid-cols-[86px_minmax(0,1fr)_92px] items-center gap-2.5 rounded-[10px] px-2 py-1.5 text-left text-foreground transition-colors hover:bg-secondary",
          selected === g.name && "bg-secondary shadow-[inset_0_0_0_1px_var(--border-strong)]",
        )}
        onClick={() => select(selected === g.name ? null : g.name)}
        aria-expanded={selected === g.name}
      >
        <span
          className={cn(
            "truncate text-[13px] font-semibold text-[color:var(--ink-2)] transition-colors",
            selected === g.name && "text-foreground",
          )}
          title={g.name}
        >
          {g.name}
        </span>
        <span className="relative h-3.5 min-w-0 overflow-hidden rounded">
          <span
            className={cn(
              "absolute inset-0 origin-left rounded transition-transform duration-300 [transition-timing-function:cubic-bezier(0.22,1,0.36,1)]",
              side === "in"
                ? "bg-[linear-gradient(90deg,rgba(230,103,103,0.35),rgba(230,103,103,0.95))]"
                : "bg-[linear-gradient(90deg,rgba(12,163,12,0.9),rgba(12,163,12,0.3))]",
            )}
            style={{ transform: `scaleX(${ratio})` }}
          />
        </span>
        <span className="flex flex-col items-end gap-0 text-right leading-[1.3]">
          <b className="num whitespace-nowrap text-xs font-semibold text-[color:var(--ink-2)]">{fmtE8(g.turnover)}</b>
          <span className="num whitespace-nowrap text-[11px]">
            <span
              className={side === "in" ? "text-up" : "text-down"}
              title={`今日成交金額為近20日平均的 ${g.vs20!.toFixed(2)} 倍`}
            >
              {dv! > 0 ? "+" : ""}
              {dv}%
            </span>{" "}
            <span className={c === "up" ? "text-up" : c === "down" ? "text-down" : "text-foreground"}>
              {g.avg_chg != null ? `${g.avg_chg > 0 ? "+" : ""}${g.avg_chg.toFixed(1)}%` : "—"}
            </span>
          </span>
        </span>
      </button>
    );
  };

  const showSubs = mode === "industry" && !!sel?.subs?.length;

  return (
    <section className="mb-3.5 rounded-[var(--r-lg)] border border-border bg-card p-3.5 shadow-[var(--shadow-card)]">
      <div className="mb-2.5 flex flex-wrap items-center gap-3">
        <h2 className="text-[15px] font-bold">資金流向</h2>
        <div className="inline-flex gap-0.5 rounded-full border border-border bg-card p-[3px]">
          <button className={segTabClass(mode === "industry")} onClick={() => { setMode("industry"); select(null); }}>
            產業
          </button>
          <button
            className={cn(segTabClass(mode === "theme"), !hasThemes && "cursor-not-allowed opacity-50")}
            onClick={() => { setMode("theme"); select(null); }}
            disabled={!hasThemes}
            title={hasThemes ? "概念股分類(成分重疊)" : "題材資料累積中"}
          >
            題材
          </button>
        </div>
        <div className="ml-auto inline-flex gap-0.5 rounded-full border border-border bg-card p-[3px]">
          <button className={segTabClass(sortBy === "volume")} onClick={() => { setSortBy("volume"); select(null); }}>
            資金量能
          </button>
          <button className={segTabClass(sortBy === "price")} onClick={() => { setSortBy("price"); select(null); }}>
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
          {/* DOM 順序 = 視覺順序:流入在左(手機在上)、流出在右 */}
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
          <div className="flex min-w-0 flex-col gap-1.5">
            <div className="mb-0.5 border-b border-[color:var(--line)] pb-1 text-xs font-bold tracking-[1px] text-down">
              {sortBy === "volume" ? "流出 ↓ 比平時冷清" : "弱勢 ↓ 族群性下跌"}
            </div>
            {outflow.length ? (
              outflow.map((g) => <Row key={g.name} g={g} side="out" />)
            ) : (
              <div className="p-2 text-xs text-muted-foreground">無明顯{sortBy === "volume" ? "退潮" : "弱勢"}</div>
            )}
          </div>
        </div>
      )}

      {sel && (
        <div className="mt-2.5 border-t border-dashed border-[color:var(--line)] pt-2.5 animate-[fadeUp_0.25s_ease_backwards]">
          <div className="mb-2 flex items-center gap-2.5 text-[13.5px]">
            <b>{sel.name}</b>
            <span className="min-w-0 truncate text-xs text-muted-foreground">
              {fmtE8(sel.turnover)} · 量能{sel.vs20 != null ? `${sel.vs20.toFixed(1)}×` : "—"} ·{" "}
              <span className="text-up">↑{sel.up}</span>/<span className="text-down">↓{sel.down}</span>
              {showSubs && <span className="hidden sm:inline"> · 點子題材看成分股</span>}
            </span>
            <button
              className="ml-auto -my-1 flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
              onClick={() => select(null)}
              aria-label={`收合 ${sel.name}`}
            >
              <X size={16} strokeWidth={1.8} />
            </button>
          </div>

          {showSubs ? (
            <div className="flex flex-col gap-1">
              {sel.subs!.map((sub) => {
                const open = subSel === sub.name;
                const c = chgClass(sub.avg_chg);
                return (
                  <div key={sub.name} className="min-w-0">
                    <button
                      className={cn(
                        "flex min-h-11 w-full cursor-pointer items-center gap-2 rounded-[10px] px-2 py-1.5 text-left transition-colors hover:bg-secondary",
                        open && "bg-secondary shadow-[inset_0_0_0_1px_var(--border-strong)]",
                      )}
                      onClick={() => setSubSel(open ? null : sub.name)}
                      aria-expanded={open}
                    >
                      <ChevronRight
                        size={14}
                        strokeWidth={1.8}
                        className={cn("shrink-0 text-muted-foreground transition-transform duration-200", open && "rotate-90")}
                        aria-hidden
                      />
                      <span className="min-w-0 truncate text-[13px] font-semibold text-[color:var(--ink-2)]" title={sub.name}>
                        {sub.name}
                      </span>
                      <span className="ml-auto flex shrink-0 items-center gap-2">
                        <b className="num text-xs font-semibold text-[color:var(--ink-2)]">{fmtE8(sub.turnover)}</b>
                        <Vs20Badge vs20={sub.vs20} />
                        <span className={cn("num w-14 text-right text-[11px]", c === "up" ? "text-up" : c === "down" ? "text-down" : "text-foreground")}>
                          {sub.avg_chg != null ? `${sub.avg_chg > 0 ? "+" : ""}${sub.avg_chg.toFixed(1)}%` : "—"}
                        </span>
                      </span>
                    </button>
                    {open && (
                      <div className="px-2 pb-1.5 pt-1">
                        <StockChips items={sub.top} />
                      </div>
                    )}
                  </div>
                );
              })}
              <div className="min-w-0">
                <button
                  className={cn(
                    "flex min-h-11 w-full cursor-pointer items-center gap-2 rounded-[10px] px-2 py-1.5 text-left transition-colors hover:bg-secondary",
                    subSel === ALL_SUB && "bg-secondary shadow-[inset_0_0_0_1px_var(--border-strong)]",
                  )}
                  onClick={() => setSubSel(subSel === ALL_SUB ? null : ALL_SUB)}
                  aria-expanded={subSel === ALL_SUB}
                >
                  <ChevronRight
                    size={14}
                    strokeWidth={1.8}
                    className={cn("shrink-0 text-muted-foreground transition-transform duration-200", subSel === ALL_SUB && "rotate-90")}
                    aria-hidden
                  />
                  <span className="text-[13px] font-semibold text-muted-foreground">全部成分股(金額前 {sel.top.length})</span>
                </button>
                {subSel === ALL_SUB && (
                  <div className="px-2 pb-1.5 pt-1">
                    <StockChips items={sel.top} />
                  </div>
                )}
              </div>
            </div>
          ) : (
            <StockChips items={sel.top} />
          )}
        </div>
      )}
    </section>
  );
}
