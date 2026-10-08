"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ChevronRight, Info, X } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { dataFetch } from "@/lib/dataFetch";
import { OFFLINE_DATA_COPY, isBrowserOffline } from "@/lib/pwa";
import { MARKET_LABEL, toneClass } from "@/lib/format";
import { cn, pillTabClass, softSelectClass } from "@/lib/utils";
import type { InstiFlowGroup, InstiFlowJson, InstiFlowMember, InstiIdentity } from "@/lib/types";
import {
  IDENTITIES,
  IDENTITY_LABEL,
  INSTI_EMPTY,
  INSTI_FLOW_URL,
  INSTI_NO_GROUPS,
  INSTI_OTHER_LABEL,
  MODE_LABEL,
  SIDE_LIMIT,
  barRatio,
  clsStaleText,
  concentrationText,
  countFull,
  countShort,
  dateLine,
  definitionText,
  fmtAmt,
  fmtAmtEst,
  fmtNetLots,
  marketLine,
  memberHref,
  missingText,
  moreText,
  partialText,
  splitSides,
  staleText,
  type InstiMode,
} from "@/lib/instiGroupFlow";

function fmtChg(n: number | null): string {
  if (n == null) return "—";
  return `${n > 0 ? "+" : n < 0 ? "-" : ""}${Math.abs(n).toFixed(1)}%`;
}

function MemberRow({ m }: { m: InstiFlowMember }) {
  return (
    <Link
      href={memberHref(m.id)}
      className="grid min-h-11 grid-cols-[minmax(0,1fr)_auto_auto_auto_12px] items-center gap-x-2 rounded-[10px] px-2 py-1 text-[12.5px] transition-colors hover:bg-secondary"
    >
      {/* 名稱一行、代號＋市場一行:390px 下數字三欄佔掉大半,名稱同一行會被截成一個字 */}
      <span className="flex min-w-0 flex-col leading-tight">
        <span className="truncate font-semibold text-foreground" title={m.name}>{m.name}</span>
        <span className="flex items-center gap-1 text-[10.5px] text-muted-foreground">
          <span className="num">{m.id}</span>
          <span className="rounded border border-border px-1 text-[10px] leading-[14px]">
            {MARKET_LABEL[m.market] ?? m.market}
          </span>
        </span>
      </span>
      <span className={cn("num min-w-[4.75rem] text-right font-semibold", toneClass(m.net_lots))}>{fmtNetLots(m.net_lots)}</span>
      <span className="num min-w-[3.5rem] text-right text-[color:var(--ink-2)]">{fmtAmt(m.amt_est)}</span>
      <span className={cn("num w-12 text-right text-[11.5px]", toneClass(m.chg_pct))}>{fmtChg(m.chg_pct)}</span>
      <ChevronRight size={14} strokeWidth={1.8} className="text-muted-foreground" aria-hidden />
    </Link>
  );
}

function GroupDetail({ g, onClose }: { g: InstiFlowGroup; onClose: () => void }) {
  return (
    <div className="mx-1 mb-1.5 rounded-[10px] border border-dashed border-[color:var(--line)] px-1.5 pb-1.5 pt-1 animate-[fadeUp_0.25s_ease_backwards]">
      <div className="flex items-center gap-2 px-1">
        <span className="min-w-0 flex-1 text-[12px] leading-snug text-muted-foreground">
          <b className="text-foreground">{g.name}</b>
          {" · "}
          <span className="num">{countFull(g)}</span>
        </span>
        <button
          type="button"
          className="-my-1 flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
          onClick={onClose}
          aria-label={`收合 ${g.name}`}
        >
          <X size={16} strokeWidth={1.8} />
        </button>
      </div>
      {g.buy_top.length > 0 && (
        <>
          <div className="px-2 pt-1 text-[11.5px] font-bold text-up">{`買超前 ${g.buy_top.length} · 張數/金額(估)/漲跌`}</div>
          {g.buy_top.map((m) => <MemberRow key={m.id} m={m} />)}
        </>
      )}
      {g.sell_top.length > 0 && (
        <>
          <div className="px-2 pt-1.5 text-[11.5px] font-bold text-down">{`賣超前 ${g.sell_top.length} · 張數/金額(估)/漲跌`}</div>
          {g.sell_top.map((m) => <MemberRow key={m.id} m={m} />)}
        </>
      )}
      {missingText(g.amt_missing_n) && (
        <p className="px-2 pt-1 text-[11px] text-muted-foreground">{missingText(g.amt_missing_n)}</p>
      )}
    </div>
  );
}

function GroupRow({
  g,
  side,
  maxAbs,
  open,
  onToggle,
}: {
  g: InstiFlowGroup;
  side: "buy" | "sell";
  maxAbs: number;
  open: boolean;
  onToggle: () => void;
}) {
  const tags = [concentrationText(g), clsStaleText(g.cls_date)].filter(Boolean) as string[];
  return (
    <div className="min-w-0">
      <button
        type="button"
        className={cn(
          "flex w-full min-w-0 cursor-pointer flex-col gap-0.5 rounded-[10px] px-2 py-1.5 text-left transition-colors hover:bg-secondary",
          open && softSelectClass(true),
        )}
        onClick={onToggle}
        aria-expanded={open}
      >
        <span className="grid w-full grid-cols-[84px_minmax(0,1fr)_auto] items-center gap-2.5">
          <span
            className={cn("truncate text-[13px] font-semibold text-[color:var(--ink-2)]", open && "text-foreground")}
            title={g.name}
          >
            {g.name}
          </span>
          <span className="relative h-3.5 min-w-0 overflow-hidden rounded">
            <span
              className={cn(
                "absolute inset-0 origin-left rounded transition-transform duration-300 [transition-timing-function:cubic-bezier(0.22,1,0.36,1)]",
                side === "buy"
                  ? "bg-[linear-gradient(90deg,rgba(230,103,103,0.35),rgba(230,103,103,0.95))]"
                  : "bg-[linear-gradient(90deg,rgba(12,163,12,0.9),rgba(12,163,12,0.3))]",
              )}
              style={{ transform: `scaleX(${barRatio(g.amt_est, maxAbs)})` }}
            />
          </span>
          <b className={cn("num whitespace-nowrap text-right text-[12.5px] font-semibold", toneClass(g.amt_est))}>
            {fmtAmtEst(g.amt_est)}
          </b>
        </span>
        <span className="flex w-full min-w-0 flex-wrap items-baseline justify-end gap-x-2 text-right text-[11px] leading-[1.35] text-muted-foreground">
          {tags.map((t) => (
            <span key={t} className="text-[color:var(--warn)]">{t}</span>
          ))}
          <span className="num whitespace-nowrap">
            {fmtNetLots(g.net_lots)}
            {" · "}
            {countShort(g)}
          </span>
        </span>
      </button>
      {open && <GroupDetail g={g} onClose={onToggle} />}
    </div>
  );
}

export default function InstiGroupFlow() {
  const [data, setData] = useState<InstiFlowJson | null>(null);
  const [error, setError] = useState(false);
  const [ident, setIdent] = useState<InstiIdentity>("foreign");
  const [mode, setMode] = useState<InstiMode>("industry");
  const [openName, setOpenName] = useState<string | null>(null);

  useEffect(() => {
    dataFetch(INSTI_FLOW_URL)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setData)
      .catch(() => setError(true));
  }, []);

  const sides = useMemo(() => {
    if (!data) return null;
    const { buy, sell } = splitSides(data.groups[mode]?.[ident] ?? []);
    const shownBuy = buy.slice(0, SIDE_LIMIT);
    const shownSell = sell.slice(0, SIDE_LIMIT);
    const maxAbs = Math.max(0, ...[...shownBuy, ...shownSell].map((g) => Math.abs(g.amt_est)));
    return { buy, sell, shownBuy, shownSell, maxAbs };
  }, [data, mode, ident]);

  if (error) {
    return (
      <div className="py-12 text-center text-sm text-muted-foreground">
        {isBrowserOffline() ? OFFLINE_DATA_COPY : INSTI_EMPTY}
      </div>
    );
  }

  if (!data || !sides) {
    return (
      <div className="space-y-2 py-2">
        <Skeleton className="h-24 w-full rounded-[var(--r-md)]" />
        {[0, 1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-12 w-full rounded-[var(--r-md)]" />
        ))}
      </div>
    );
  }

  const partial = partialText(data);
  const stale = staleText(data);
  const missing = missingText(data.amt_missing_n);
  const other = mode === "industry" ? data.groups.other?.[ident] : undefined;
  const toggle = (name: string) => setOpenName((cur) => (cur === name ? null : name));

  const column = (side: "buy" | "sell") => {
    const all = side === "buy" ? sides.buy : sides.sell;
    const shown = side === "buy" ? sides.shownBuy : sides.shownSell;
    const more = moreText(all.length, shown.length);
    return (
      <div className="flex min-w-0 flex-col gap-1">
        <div
          className={cn(
            "mb-0.5 border-b border-[color:var(--line)] pb-1 text-xs font-bold tracking-[1px]",
            side === "buy" ? "text-up" : "text-down",
          )}
        >
          {side === "buy" ? "買超 ↑" : "賣超 ↓"}
        </div>
        {shown.length ? (
          shown.map((g) => (
            <GroupRow
              key={g.name}
              g={g}
              side={side}
              maxAbs={sides.maxAbs}
              open={openName === g.name}
              onToggle={() => toggle(g.name)}
            />
          ))
        ) : (
          <div className="p-2 text-xs text-muted-foreground">{INSTI_NO_GROUPS}</div>
        )}
        {more && <div className="px-2 text-[11px] text-muted-foreground">{more}</div>}
      </div>
    );
  };

  return (
    <section className="min-w-0 rounded-[var(--r-lg)] border border-border bg-card p-3.5 shadow-[var(--shadow-card)]">
      <div className="mb-2.5 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
        <h2 className="text-[15px] font-bold">法人族群</h2>
        <span className="num text-[11.5px] text-muted-foreground">{dateLine(data)}</span>
      </div>

      <div role="tablist" aria-label="法人身分" className="mb-2.5 grid grid-cols-4 gap-1 rounded-[var(--r-md)] bg-secondary p-1">
        {IDENTITIES.map((k) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={ident === k}
            onClick={() => {
              setIdent(k);
              setOpenName(null);
            }}
            className={cn(
              "min-h-11 rounded-[var(--r-sm)] px-1.5 py-1.5 text-[13px] font-semibold leading-tight transition-colors touch-manipulation",
              ident === k ? "bg-primary text-primary-foreground shadow-sm" : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
            )}
          >
            {IDENTITY_LABEL[k]}
          </button>
        ))}
      </div>

      <div role="tablist" aria-label="族群分類" className="mb-2.5 inline-flex gap-0.5 rounded-full border border-border bg-card p-[3px]">
        {(["industry", "theme"] as const).map((k) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={mode === k}
            className={cn(pillTabClass(mode === k, "accent"), "min-h-9")}
            onClick={() => {
              setMode(k);
              setOpenName(null);
            }}
          >
            {MODE_LABEL[k]}
          </button>
        ))}
      </div>

      <p className="flex items-start gap-2 text-[12px] leading-relaxed text-muted-foreground">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" aria-hidden />
        <span>{definitionText(ident, mode)}</span>
      </p>

      {(partial || stale) && (
        <div className="mt-2 flex items-start gap-2 rounded-[var(--r-md)] border border-[color:var(--warn)]/30 bg-[color:var(--warn)]/10 px-3 py-2 text-[12px] text-foreground/90">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[color:var(--warn)]" aria-hidden />
          <span>{[partial, stale].filter(Boolean).join(" ")}</span>
        </div>
      )}

      <p className="num mt-2 text-[12.5px] font-semibold text-foreground">{marketLine(data, ident)}</p>
      {missing && <p className="mt-0.5 text-[11px] text-muted-foreground">{missing}</p>}

      <div className="mt-2.5 grid grid-cols-1 gap-x-6 gap-y-3 md:grid-cols-2">
        {column("buy")}
        {column("sell")}
      </div>

      {other && other.n > 0 && (
        <p className="mt-2.5 border-t border-dashed border-[color:var(--line)] pt-2 text-[11.5px] leading-relaxed text-muted-foreground">
          {`${INSTI_OTHER_LABEL} `}
          <span className="num">{`${fmtNetLots(other.net_lots)} · ${fmtAmtEst(other.amt_est)} · ${countFull(other)}`}</span>
        </p>
      )}
    </section>
  );
}
