"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { dataFetch } from "@/lib/dataFetch";
import { fmtMoney, fmtMoneyAbs } from "@/lib/branchPnl";
import { cn, filterChipClass, pillTabClass } from "@/lib/utils";
import { toneClass } from "@/lib/format";
import { Skeleton } from "@/components/ui/skeleton";
import { warrantTabHref } from "@/lib/warrantDeepLink";
import {
  DEFAULT_SCREEN_FILTER,
  ENTRY_NOTE,
  KIND_LABEL,
  entryLine,
  SCREEN_LEAD,
  SCREEN_LOSS_STEPS,
  SCREEN_SORTS,
  WPOS_FOOTER,
  filterScreenRows,
  fmtPct,
  fmtUnderPrice,
  normalizeScreening,
  screenSummary,
  underDiffText,
  type ScreenFilter,
  type ScreenPayload,
  type WarrantKindKey,
} from "@/lib/warrantPositions";

const PAGE = 30;

/**
 * /branch 權證分點異動 → 「仍持有(估)」檢視(docs/51 §4):全市場仍持有成本 ≥ 500 萬的
 * 券商 × 標的,預設只看認購、帳面 −20% 以下,由差到好排。點了這個檢視才抓檔。
 */
export default function WarrantHoldersList() {
  const [payload, setPayload] = useState<ScreenPayload | null | undefined>(undefined);
  const [filter, setFilter] = useState<ScreenFilter>(DEFAULT_SCREEN_FILTER);
  const [limit, setLimit] = useState(PAGE);

  useEffect(() => {
    let cancelled = false;
    dataFetch("/data/branches/warrant_positions.json")
      .then(async (r) => (r.ok ? normalizeScreening(await r.json()) : null))
      .then((p) => { if (!cancelled) setPayload(p); })
      .catch(() => { if (!cancelled) setPayload(null); });
    return () => { cancelled = true; };
  }, []);

  const rows = useMemo(() => (payload ? filterScreenRows(payload.rows, filter) : []), [payload, filter]);
  useEffect(() => { setLimit(PAGE); }, [filter]);

  if (payload === undefined) return <Skeleton className="h-40 w-full rounded-[var(--r-lg)]" />;
  if (payload === null) {
    return (
      <div className="py-[46px] text-center text-sm text-muted-foreground">
        「仍持有(估)」清單要等下一次資料匯出後才會出現。
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3" data-testid="warrant-holders">
      <p className="text-[11.5px] leading-relaxed text-muted-foreground">
        {SCREEN_LEAD}
        {payload.data_date && <>{" "}資料日 {payload.data_date}{payload.window_from ? `，窗口自 ${payload.window_from}` : ""}。</>}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-full border border-border/40 bg-background/80 p-1" role="tablist" aria-label="權證種類">
          {(["call", "put"] as WarrantKindKey[]).map((k) => (
            <button key={k} type="button" role="tab" aria-selected={filter.kind === k}
              onClick={() => setFilter((f) => ({ ...f, kind: k }))} className={cn(pillTabClass(filter.kind === k), "min-h-9")}>
              {KIND_LABEL[k]}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="帳面門檻">
          {SCREEN_LOSS_STEPS.map((s) => (
            <button key={s.key} type="button" aria-pressed={filter.maxPct === s.key}
              onClick={() => setFilter((f) => ({ ...f, maxPct: s.key }))} className={cn(filterChipClass(filter.maxPct === s.key), "min-h-9")}>
              {s.label}
            </button>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-[11.5px] text-muted-foreground">{screenSummary(rows.length, payload)}</span>
        <label className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
          排序
          <select
            value={filter.sort}
            onChange={(e) => setFilter((f) => ({ ...f, sort: e.target.value as ScreenFilter["sort"] }))}
            className="min-h-9 rounded-md border border-border bg-card px-2 text-[12px] text-foreground"
            aria-label="排序"
          >
            {SCREEN_SORTS.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
        </label>
      </div>

      {rows.length === 0 ? (
        <div className="py-8 text-center text-[13px] text-muted-foreground">
          沒有符合條件的券商 × 標的。涵蓋已匯入權證池、每檔權證只有前 15 大分點;沒有資料不代表沒有持有。
        </div>
      ) : (
        <ol className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
          {rows.slice(0, limit).map((r) => {
            const pct = fmtPct(r.unrealized_pct);
            const under = underDiffText(r.avg_under, r.under_last);
            const entry = entryLine(r.buy_days);
            return (
              <li key={`${r.branch_name}|${r.underlying_id}|${r.kind}`} className="rounded-[var(--r-lg)] border border-border bg-card p-3 shadow-sm">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-[14px] font-semibold text-foreground" title={r.branch_name}>{r.branch_name}</div>
                    <Link href={warrantTabHref(r.underlying_id, r.branch_name)} className="inline-flex min-h-8 items-center text-[12.5px] text-foreground no-underline hover:text-primary" aria-label={`${r.underlying_name} 權證分頁,選中 ${r.branch_name}`}>
                      {r.underlying_name} <span className="num ml-1 text-[11px] text-muted-foreground">{r.underlying_id}</span> <span aria-hidden className="ml-0.5 text-muted-foreground">›</span>
                    </Link>
                  </div>
                  <div className="shrink-0 text-right">
                    <div className="text-[10px] text-muted-foreground">帳面估算</div>
                    {r.unrealized != null ? (
                      <div className={cn("num text-[15px] font-bold leading-tight", toneClass(r.unrealized) || "text-foreground")}>
                        {fmtMoney(r.unrealized)}
                        {pct && <span className="ml-1 text-[11.5px] font-semibold">({pct})</span>}
                      </div>
                    ) : (
                      <div className="text-[11.5px] text-muted-foreground">未估值</div>
                    )}
                  </div>
                </div>
                <dl className="mt-2 grid grid-cols-3 gap-x-2 gap-y-1 text-[11.5px]">
                  <div>
                    <dt className="text-[10px] text-muted-foreground">仍持有(估)</dt>
                    <dd className="num font-semibold text-foreground">{r.lots.toLocaleString("zh-TW")} 張</dd>
                  </div>
                  <div>
                    <dt className="text-[10px] text-muted-foreground">成本(估)</dt>
                    <dd className="num font-semibold text-foreground">{fmtMoneyAbs(r.cost)}</dd>
                  </div>
                  <div>
                    <dt className="text-[10px] text-muted-foreground">換算現股均價</dt>
                    <dd className="num font-semibold text-foreground">{r.avg_under != null ? fmtUnderPrice(r.avg_under) : "—"}</dd>
                  </div>
                </dl>
                {entry && <p className="num mt-1.5 text-[11.5px] font-semibold text-foreground" title={ENTRY_NOTE}>{entry}</p>}
                <p className="num mt-1 text-[11px] text-muted-foreground">
                  {under ?? (r.under_last != null ? `現股 ${fmtUnderPrice(r.under_last)}` : "")}
                  {!entry && r.last_buy_date && <> · 最後買超日 {r.last_buy_date}</>}
                  {r.n_unvalued > 0 && <> · {r.n_unvalued} 檔未估值</>}
                  {r.self_pct > 0 && <> · 自家發行 {r.self_pct}%</>}
                </p>
              </li>
            );
          })}
        </ol>
      )}
      {rows.length > limit && (
        <button type="button" onClick={() => setLimit((n) => n + PAGE)}
          className="min-h-10 w-full rounded-md border border-border text-[12.5px] text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground">
          顯示更多({rows.length - limit})
        </button>
      )}
      <p className="text-[10.5px] leading-relaxed text-muted-foreground">{ENTRY_NOTE} 點標的名稱直達個股權證分頁並選中該券商。</p>
      <p className="text-[10.5px] leading-relaxed text-muted-foreground">{WPOS_FOOTER}</p>
    </div>
  );
}
