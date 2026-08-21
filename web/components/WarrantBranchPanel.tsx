"use client";

import { useEffect, useMemo, useState } from "react";
import { dataFetch } from "@/lib/dataFetch";
import { cn, pillTabClass } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";

export type WarrantBreakdown = {
  warrant_id: string;
  warrant_name: string;
  kind: "call" | "put" | string;
  net_lots: number;
  net_amount: number;
};

export type WarrantBranchRow = {
  branch_name: string;
  underlying_id: string;
  underlying_name: string;
  net_amount: number;
  breakdown?: WarrantBreakdown[];
};

type Timeframe = "1d" | "2d" | "5d" | "30d" | "120d";

const TIMEFRAMES: { key: Timeframe; label: string }[] = [
  { key: "1d", label: "1日" },
  { key: "2d", label: "2日" },
  { key: "5d", label: "5日" },
  { key: "30d", label: "30日" },
  { key: "120d", label: "120日" },
];

function fmtWan(amt: number, digits = 0): string {
  return (Math.abs(amt) / 10000).toLocaleString("zh-TW", { maximumFractionDigits: digits });
}

/** 個股權證分頁：同標的分點淨買賣超（對齊 /branch 權證分點異動） */
export default function WarrantBranchPanel({ stockId }: { stockId: string }) {
  const [byTf, setByTf] = useState<Record<string, WarrantBranchRow[]> | null>(null);
  const [tf, setTf] = useState<Timeframe>("1d");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    dataFetch("/data/branches/warrant_branches.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((json: Record<string, WarrantBranchRow[]>) => {
        if (!cancelled) setByTf(json);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const rows = useMemo(() => {
    if (!byTf) return null;
    const list = (byTf[tf] ?? []).filter((r) => r.underlying_id === stockId);
    return [...list].sort((a, b) => Math.abs(b.net_amount) - Math.abs(a.net_amount));
  }, [byTf, tf, stockId]);

  useEffect(() => {
    setExpanded(null);
  }, [tf, stockId]);

  if (error) {
    return (
      <div className="rounded-[var(--r-lg)] border border-border bg-card p-3.5 text-sm text-muted-foreground shadow-[var(--shadow-card)]">
        權證分點異動資料載入失敗。可到「分點」頁的「權證分點異動」查看全市場。
      </div>
    );
  }

  if (rows === null) {
    return <Skeleton className="h-36 w-full rounded-[var(--r-lg)]" />;
  }

  const buyN = rows.filter((r) => r.net_amount > 0).length;
  const sellN = rows.filter((r) => r.net_amount < 0).length;

  return (
    <section className="grid gap-2.5 rounded-[var(--r-lg)] border border-border bg-card p-3.5 shadow-[var(--shadow-card)]">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h3 className="text-sm font-bold text-foreground">權證分點動向</h3>
          <p className="mt-0.5 text-[11.5px] text-muted-foreground">
            哪個分點在這檔標的的權證上買／賣超（估金額）；點列展開看是哪幾檔權證。門檻同分點頁：區間淨額 ≥ 500 萬。
          </p>
        </div>
        {(buyN > 0 || sellN > 0) && (
          <span className="text-[11.5px] text-muted-foreground">
            買超 {buyN} · 賣超 {sellN}
          </span>
        )}
      </div>

      <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="權證分點區間">
        {TIMEFRAMES.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tf === t.key}
            onClick={() => setTf(t.key)}
            className={pillTabClass(tf === t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {rows.length === 0 ? (
        <p className="py-4 text-center text-[13px] text-muted-foreground">
          此區間沒有淨買賣超達 500 萬的權證分點。可能尚未抓到熱門權證分點，或大戶尚未達門檻。
        </p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {rows.map((b) => {
            const isOpen = expanded === b.branch_name;
            const hasBd = (b.breakdown?.length ?? 0) > 0;
            const isBuy = b.net_amount > 0;
            return (
              <li
                key={b.branch_name}
                className="overflow-hidden rounded-[var(--r-md)] border border-border bg-background"
              >
                <button
                  type="button"
                  className="flex min-h-11 w-full items-center justify-between gap-2 px-3 py-2.5 text-left transition-colors hover:bg-secondary"
                  onClick={() => setExpanded(isOpen ? null : b.branch_name)}
                  aria-expanded={hasBd ? isOpen : undefined}
                  aria-label={`${b.branch_name} ${isBuy ? "買超" : "賣超"} ${fmtWan(b.net_amount)} 萬`}
                >
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="truncate text-[13.5px] font-semibold text-foreground" title={b.branch_name}>
                      {b.branch_name}
                    </span>
                    <span
                      className={cn(
                        "shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold",
                        isBuy ? "bg-up/10 text-up" : "bg-down/10 text-down",
                      )}
                    >
                      {isBuy ? "買超" : "賣超"}
                    </span>
                  </div>
                  <span className={cn("num shrink-0 text-[14.5px] font-bold", isBuy ? "text-up" : "text-down")}>
                    {isBuy ? "+" : "−"}
                    {fmtWan(b.net_amount)} 萬
                  </span>
                </button>

                {hasBd && isOpen && (
                  <div className="border-t border-border bg-secondary/30 px-2 py-2">
                    <div className="mb-1 grid grid-cols-[1.4fr_1fr_0.6fr] px-2 text-[10.5px] font-semibold text-muted-foreground">
                      <span>權證</span>
                      <span className="text-right">估金額</span>
                      <span className="text-right">佔比</span>
                    </div>
                    <ul className="flex flex-col gap-1">
                      {b.breakdown!.map((brk) => {
                        const brkBuy = brk.net_amount > 0;
                        const pct =
                          b.net_amount !== 0
                            ? Math.round((Math.abs(brk.net_amount) / Math.abs(b.net_amount)) * 100)
                            : 0;
                        return (
                          <li
                            key={brk.warrant_id}
                            className={cn(
                              "grid grid-cols-[1.4fr_1fr_0.6fr] items-center rounded-md border-l-2 px-2 py-1.5",
                              brkBuy ? "border-l-up/60" : "border-l-down/60",
                            )}
                          >
                            <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                              <span className="truncate text-[12.5px] font-medium text-foreground" title={brk.warrant_name}>
                                {brk.warrant_name}
                              </span>
                              <span className="num text-[10.5px] text-muted-foreground">{brk.warrant_id}</span>
                              <span
                                className={cn(
                                  "rounded px-1 py-0.5 text-[9px] font-bold leading-none",
                                  brk.kind === "call" ? "bg-up/10 text-up" : "bg-down/10 text-down",
                                )}
                              >
                                {brk.kind === "call" ? "購" : "售"}
                              </span>
                            </div>
                            <span
                              className={cn(
                                "num text-right text-[13px] font-semibold",
                                brkBuy ? "text-up" : "text-down",
                              )}
                            >
                              {brkBuy ? "+" : "−"}
                              {fmtWan(brk.net_amount, 1)} 萬
                            </span>
                            <span className="num text-right text-[11px] text-muted-foreground">{pct}%</span>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
