"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ChevronRight, Info, X } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { Vs20Badge } from "@/components/Vs20Badge";
import { dataFetch } from "@/lib/dataFetch";
import { OFFLINE_DATA_COPY, isBrowserOffline } from "@/lib/pwa";
import { MARKET_LABEL, toneClass } from "@/lib/format";
import { cn, filterChipClass, pillTabClass, softSelectClass } from "@/lib/utils";
import type {
  InstiFlowGroup,
  InstiFlowJson,
  InstiFlowMember,
  InstiIdentity,
  InstiStockRow,
  InstiStocksJson,
  SectorFlow,
} from "@/lib/types";
import {
  IDENTITIES,
  IDENTITY_LABEL,
  INSTI_EMPTY,
  INSTI_FLOW_URL,
  INSTI_NO_GROUPS,
  INSTI_NO_STOCKS,
  INSTI_OTHER_LABEL,
  INSTI_STOCKS_EMPTY,
  INSTI_STOCKS_URL,
  SIDE_LIMIT,
  STOCK_INITIAL,
  VIEWS,
  VIEW_LABEL,
  VS20_LEGEND,
  vs20ByName,
  LS_STOCK_SORT,
  STOCK_SORTS,
  STOCK_SORT_LABEL,
  STOCK_SORT_DEFAULT,
  parseStockSort,
  sortStockRows,
  stockSideTitleSorted,
  type StockSort,
  fmtStockAmt,
  showAllText,
  stockCountLine,
  stockDefinitionText,
  streakText,
  type InstiView,
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
  lotsAmtMismatchText,
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
  vs20,
}: {
  g: InstiFlowGroup;
  side: "buy" | "sell";
  maxAbs: number;
  open: boolean;
  onToggle: () => void;
  /** 該族群今日成交金額 / 近 20 日均(首頁 head.json 的 sectors/themes);對不上就不畫 */
  vs20?: number;
}) {
  const tags = [concentrationText(g), clsStaleText(g.cls_date), lotsAmtMismatchText(g)].filter(Boolean) as string[];
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
        <span className="flex w-full min-w-0 flex-wrap items-center justify-end gap-x-2 text-right text-[11px] leading-[1.35] text-muted-foreground">
          {tags.map((t) => (
            <span key={t} className="text-[color:var(--warn)]">{t}</span>
          ))}
          {/* 量能徽章(原首頁資金流向面板的唯一族群層訊號,docs/49 §10):只在對得上 vs20 時出現 */}
          {vs20 != null && <Vs20Badge vs20={vs20} />}
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

/**
 * 個股列(390px 優化,2026-10-09):第一行 名稱｜張數｜金額(估)｜漲跌;第二行 連續日數膠囊
 * (使用者最常看的,放最前、側別色淡底)+ 代號 · 市場 · 產業。數字欄固定寬,條列對齊。
 */
function StockRow({ r, side, lookback }: { r: InstiStockRow; side: "buy" | "sell"; lookback: number }) {
  const streak = streakText(r.streak, side, lookback);
  return (
    <Link
      href={memberHref(r.id)}
      className="grid min-h-11 grid-cols-[minmax(0,1fr)_auto_auto_auto] items-center gap-x-1.5 gap-y-0.5 rounded-[10px] px-2 py-1.5 text-[13px] transition-colors hover:bg-secondary"
    >
      <span className="min-w-0 truncate font-semibold leading-tight text-foreground" title={r.name}>{r.name}</span>
      <span className={cn("num min-w-[4.5rem] text-right font-bold leading-tight", toneClass(r.net_lots))}>{fmtNetLots(r.net_lots)}</span>
      <span className="num min-w-[3.5rem] text-right text-[12px] leading-tight text-[color:var(--ink-2)]">{fmtStockAmt(r)}</span>
      <span className={cn("num w-12 text-right text-[12px] font-semibold leading-tight", toneClass(r.chg_pct))}>{fmtChg(r.chg_pct)}</span>
      {/* 第二行橫跨四欄:390px 下名稱欄只剩約 6 個字,連續日數/代號/市場/產業放這裡才放得下 */}
      <span className="col-span-4 flex min-w-0 items-center gap-1.5 text-[10.5px] leading-[15px] text-muted-foreground">
        {streak && (
          <span
            className={cn(
              "num shrink-0 rounded-full px-1.5 py-px text-[10.5px] font-bold leading-[15px]",
              side === "buy" ? "bg-up/15 text-up" : "bg-down/15 text-down",
            )}
          >
            {streak}
          </span>
        )}
        <span className="num shrink-0">{r.id}</span>
        <span className="shrink-0 rounded border border-border px-1 text-[10px] leading-[14px]">
          {MARKET_LABEL[r.market] ?? r.market}
        </span>
        {r.ind && <span className="min-w-0 truncate" title={r.ind}>{r.ind}</span>}
      </span>
    </Link>
  );
}

function StockColumn({
  side,
  rows,
  lookback,
  sort,
}: {
  side: "buy" | "sell";
  rows: InstiStockRow[];
  lookback: number;
  sort: StockSort;
}) {
  const [all, setAll] = useState(false);
  const sorted = useMemo(() => sortStockRows(rows, side, sort), [rows, side, sort]);
  const shown = all ? sorted : sorted.slice(0, STOCK_INITIAL);
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <div
        className={cn(
          "mb-0.5 flex items-baseline justify-between gap-2 border-b border-[color:var(--line)] pb-1 text-xs font-bold tracking-[0.5px]",
          side === "buy" ? "text-up" : "text-down",
        )}
      >
        <span>{`${side === "buy" ? "↑" : "↓"} ${stockSideTitleSorted(side, rows.length, sort)}`}</span>
        <span className="text-[10.5px] font-semibold tracking-normal text-muted-foreground">{"張數 / 金額(估) / 漲跌"}</span>
      </div>
      {shown.length ? (
        shown.map((r) => <StockRow key={r.id} r={r} side={side} lookback={lookback} />)
      ) : (
        <div className="p-2 text-xs text-muted-foreground">{INSTI_NO_STOCKS}</div>
      )}
      {rows.length > shown.length && (
        <button
          type="button"
          className="min-h-11 cursor-pointer rounded-[10px] text-[12px] font-semibold text-primary transition-colors hover:bg-secondary"
          onClick={() => setAll(true)}
        >
          {showAllText(rows.length)}
        </button>
      )}
    </div>
  );
}

function StockBody({ data, ident }: { data: InstiStocksJson; ident: InstiIdentity }) {
  const r = data.ranks[ident];
  const missing = missingText(data.amt_missing_n);
  // 排序偏好只是每個瀏覽器自己的便利,讀寫都 try/catch;讀不到就是預設「金額(估)」。
  const [sort, setSort] = useState<StockSort>(STOCK_SORT_DEFAULT);
  useEffect(() => {
    try {
      setSort(parseStockSort(localStorage.getItem(LS_STOCK_SORT)));
    } catch {
      /* 私密視窗或封鎖網站資料:維持預設 */
    }
  }, []);
  const chooseSort = (next: StockSort) => {
    setSort(next);
    try {
      localStorage.setItem(LS_STOCK_SORT, next);
    } catch {
      /* 寫不進去只是下次回到預設 */
    }
  };
  return (
    <>
      <p className="num mt-2 text-[12.5px] font-semibold text-foreground">{stockCountLine(ident, r)}</p>
      {missing && <p className="mt-0.5 text-[11px] text-muted-foreground">{missing}</p>}
      <div className="mt-2 flex flex-wrap items-center gap-1.5" role="group" aria-label="個股排序">
        <span className="text-[11.5px] text-muted-foreground">{"排序"}</span>
        {STOCK_SORTS.map((k) => (
          <button
            key={k}
            type="button"
            aria-pressed={sort === k}
            data-testid={`insti-stock-sort-${k}`}
            className={cn(filterChipClass(sort === k), "min-h-9")}
            onClick={() => chooseSort(k)}
          >
            {STOCK_SORT_LABEL[k]}
          </button>
        ))}
      </div>
      {/* key=ident:換身分時「顯示全部」收回 */}
      <div key={ident} className="mt-2.5 grid grid-cols-1 gap-x-6 gap-y-3 md:grid-cols-2">
        <StockColumn side="buy" rows={r.buy} lookback={data.streak_days} sort={sort} />
        <StockColumn side="sell" rows={r.sell} lookback={data.streak_days} sort={sort} />
      </div>
    </>
  );
}

function useLazyJson<T>(url: string, enabled: boolean): { data: T | null; error: boolean } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState(false);
  const requested = useRef(false);
  useEffect(() => {
    if (!enabled || requested.current) return;
    requested.current = true;
    dataFetch(url)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setData)
      .catch(() => setError(true));
  }, [url, enabled]);
  return { data, error };
}

function GroupBody({
  data,
  ident,
  mode,
  vs20Map,
}: {
  data: InstiFlowJson;
  ident: InstiIdentity;
  mode: InstiMode;
  vs20Map: Map<string, number>;
}) {
  const [openName, setOpenName] = useState<string | null>(null);

  const sides = useMemo(() => {
    const { buy, sell } = splitSides(data.groups[mode]?.[ident] ?? []);
    const shownBuy = buy.slice(0, SIDE_LIMIT);
    const shownSell = sell.slice(0, SIDE_LIMIT);
    const maxAbs = Math.max(0, ...[...shownBuy, ...shownSell].map((g) => Math.abs(g.amt_est)));
    return { buy, sell, shownBuy, shownSell, maxAbs };
  }, [data, mode, ident]);

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
              vs20={vs20Map.get(g.name)}
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
    <>
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
    </>
  );
}

/**
 * 法人族群分頁。`sectors`/`themes` 是首頁已載入的 head.json 族群成交金額(vs20),
 * 只用來在族群列加「量能」徽章(docs/49 §10 併入原首頁資金流向面板);不給就不畫。
 */
export default function InstiGroupFlow({ sectors, themes }: { sectors?: SectorFlow[]; themes?: SectorFlow[] } = {}) {
  const [ident, setIdent] = useState<InstiIdentity>("foreign");
  const [view, setView] = useState<InstiView>("industry");
  const isStock = view === "stock";
  const vs20Map = useMemo(() => vs20ByName(view === "theme" ? themes : sectors), [view, sectors, themes]);
  // 族群檔進分頁就抓;個股檔第一次切到「個股」才抓,之後切回來不重抓。
  const flow = useLazyJson<InstiFlowJson>(INSTI_FLOW_URL, true);
  const stocks = useLazyJson<InstiStocksJson>(INSTI_STOCKS_URL, isStock);
  const active = isStock ? stocks : flow;
  const data = active.data;

  const partial = data ? partialText(data) : null;
  const stale = data ? staleText(data) : null;

  return (
    <section className="min-w-0 rounded-[var(--r-lg)] border border-border bg-card p-3.5 shadow-[var(--shadow-card)]">
      <div className="mb-2.5 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
        <h2 className="text-[15px] font-bold">法人族群</h2>
        {data && <span className="num text-[11.5px] text-muted-foreground">{dateLine(data)}</span>}
      </div>

      <div role="tablist" aria-label="法人身分" className="mb-2.5 grid grid-cols-4 gap-1 rounded-[var(--r-md)] bg-secondary p-1">
        {IDENTITIES.map((k) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={ident === k}
            onClick={() => setIdent(k)}
            className={cn(
              "min-h-11 rounded-[var(--r-sm)] px-1.5 py-1.5 text-[13px] font-semibold leading-tight transition-colors touch-manipulation",
              ident === k ? "bg-primary text-primary-foreground shadow-sm" : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
            )}
          >
            {IDENTITY_LABEL[k]}
          </button>
        ))}
      </div>

      <div role="tablist" aria-label="檢視" className="mb-2.5 inline-flex gap-0.5 rounded-full border border-border bg-card p-[3px]">
        {VIEWS.map((k) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={view === k}
            className={cn(pillTabClass(view === k, "accent"), "min-h-9")}
            onClick={() => setView(k)}
          >
            {VIEW_LABEL[k]}
          </button>
        ))}
      </div>

      <p className="flex items-start gap-2 text-[12px] leading-relaxed text-muted-foreground">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" aria-hidden />
        <span>
          {isStock ? stockDefinitionText(ident) : definitionText(ident, view)}
          {!isStock && vs20Map.size > 0 && <>{" "}{VS20_LEGEND}</>}
        </span>
      </p>

      {(partial || stale) && (
        <div className="mt-2 flex items-start gap-2 rounded-[var(--r-md)] border border-[color:var(--warn)]/30 bg-[color:var(--warn)]/10 px-3 py-2 text-[12px] text-foreground/90">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[color:var(--warn)]" aria-hidden />
          <span>{[partial, stale].filter(Boolean).join(" ")}</span>
        </div>
      )}

      {active.error ? (
        <div className="py-12 text-center text-sm text-muted-foreground">
          {isBrowserOffline() ? OFFLINE_DATA_COPY : isStock ? INSTI_STOCKS_EMPTY : INSTI_EMPTY}
        </div>
      ) : !data ? (
        <div className="space-y-2 py-2">
          {[0, 1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-12 w-full rounded-[var(--r-md)]" />
          ))}
        </div>
      ) : isStock ? (
        <StockBody data={stocks.data!} ident={ident} />
      ) : (
        // key:換身分或模式時收合展開中的族群(與 MVP 行為一致)
        <GroupBody key={`${view}-${ident}`} data={flow.data!} ident={ident} mode={view} vs20Map={vs20Map} />
      )}
    </section>
  );
}
