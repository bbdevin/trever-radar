"use client";

import { Fragment, Suspense, useEffect, useMemo, useState } from "react";
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
import { ChevronDown, ChevronUp } from "lucide-react";
import { IconArrowLeft } from "@/components/Icons";
import KChart from "@/components/KChart";
import BranchFlowSection, { MAX_SELECTED_BRANCHES } from "@/components/BranchFlowSection";
import { Skeleton } from "@/components/ui/skeleton";
import WatchlistButton from "@/components/WatchlistButton";
import type { StockJson } from "@/lib/types";
import { MARKET_LABEL, chgClass, fmtE8, fmtPct, fmtX } from "@/lib/format";
import { signInWithGoogle, useSession } from "@/lib/useSession";
import { cn, pillTabClass } from "@/lib/utils";

const RANGES = [
  { key: "1m", label: "1月", days: 22 },
  { key: "3m", label: "3月", days: 66 },
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
  const [data, setData] = useState<StockJson | null>(null);
  const [error, setError] = useState(false);
  const [range, setRange] = useState<(typeof RANGES)[number]["key"]>("1y");
  const [view, setView] = useState<"chart" | "branch" | "warrant">("chart");
  const [selectedBranches, setSelectedBranches] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!id) return;
    setSelectedBranches(new Set()); // 換股重置勾選
    fetch(`/data/stocks/${id}.json`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setData)
      .catch(() => setError(true));
  }, [id]);

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

  // 分點進出:勾選分點集合的每日 net 加總;該日勾選分點都未上榜 → 缺日留白(不補 0)
  const branchFlow = useMemo(() => {
    const bh = data?.branch_history;
    if (!bh?.length || selectedBranches.size === 0) return undefined;
    const pts: { t: string; net: number }[] = [];
    for (const d of bh) {
      const rows = d.branches.filter((b) => selectedBranches.has(b.n));
      if (rows.length) pts.push({ t: d.t, net: rows.reduce((s, b) => s + b.net, 0) });
    }
    return pts.length ? pts.sort((a, b) => (a.t < b.t ? -1 : 1)) : undefined;
  }, [data, selectedBranches]);

  const toggleBranch = (name: string) =>
    setSelectedBranches((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else if (next.size < MAX_SELECTED_BRANCHES) next.add(name);
      return next;
    });

  if (!id) return <div className="py-[46px] text-center text-sm text-muted-foreground">網址缺少股票代號(?id=2330)</div>;
  if (error)
    return (
      <div className="py-[46px] text-center text-sm text-muted-foreground">
        尚無 {id} 的個股資料檔。目前僅產出雷達榜單內的股票,之後擴大到全候選池。
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

  return (
    <>
      <div className="flex flex-wrap items-center gap-2.5 py-4 pb-2.5">
        <a
          href="/"
          className="-ml-2.5 inline-flex items-center gap-1 rounded-full px-2.5 py-1.5 text-[13px] text-muted-foreground hover:bg-secondary hover:text-foreground"
        >
          <IconArrowLeft size={16} />
          雷達
        </a>
        <span className="text-[19px] font-extrabold">{data.name}</span>
        <span className="text-[13px] text-muted-foreground">
          {data.id} · {MARKET_LABEL[data.market] ?? data.market}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <span className={cn("num text-2xl font-extrabold tracking-[-0.3px]", CHG_TEXT[cls])}>
            {last.c.toLocaleString("zh-TW")}
          </span>
          <span className={cn("num inline-block rounded-full px-2 py-px text-[12.5px] font-bold", CHG_BADGE[cls])}>
            {fmtPct(chg)}
          </span>
        </div>
        <WatchlistButton stockId={data.id} size={20} />
      </div>
      <div className="mb-2.5 flex flex-wrap gap-3.5 text-xs text-muted-foreground">
        <span>
          {last.t} · 量 <span className="num text-[color:var(--ink-2)]">{last.v.toLocaleString("zh-TW")}</span> 張 · 額{" "}
          <span className="num text-[color:var(--ink-2)]">{fmtE8(last.amt)}</span>
        </span>
        <span>
          資料 <span className="num text-[color:var(--ink-2)]">{cs.length.toLocaleString("zh-TW")}</span> 個交易日(自 {cs[0].t})
        </span>
      </div>
      <div className="mb-2.5 flex flex-wrap items-center gap-2.5">
        <div role="tablist" className="flex w-fit gap-0.5 rounded-full border border-border bg-card p-[3px]">
          <button role="tab" aria-selected={view === "chart"} className={pillTabClass(view === "chart")} onClick={() => setView("chart")}>
            K線
          </button>
          <button role="tab" aria-selected={view === "branch"} className={pillTabClass(view === "branch")} onClick={() => setView("branch")}>
            分點
          </button>
          <button role="tab" aria-selected={view === "warrant"} className={pillTabClass(view === "warrant")} onClick={() => setView("warrant")}>
            權證
          </button>
        </div>
        {view === "chart" && (
          <div role="tablist" className="flex w-fit gap-0.5 rounded-full border border-border bg-card p-[3px]">
            {RANGES.map((r) => (
              <button key={r.key} role="tab" aria-selected={range === r.key} className={pillTabClass(range === r.key)} onClick={() => setRange(r.key)}>
                {r.label}
              </button>
            ))}
          </div>
        )}
      </div>
      {view === "chart" && <KChart candles={cs} visibleDays={visibleDays} mainForce={mainForce} branchFlow={branchFlow} />}
      {view === "branch" && <BranchPanel data={data} />}
      {view === "warrant" && <WarrantPanel data={data} />}
      {view === "chart" && <TechnicalPanel data={data} />}
      {view === "chart" && (
        <BranchFlowSection
          branches={data.branches}
          branchHistory={data.branch_history}
          heading="分點進出"
          selected={selectedBranches}
          onToggleSelect={toggleBranch}
        />
      )}
    </>
  );
}

function BranchPanel({ data }: { data: StockJson }) {
  const score = data.scores?.branch ?? null;
  const branchReasons = (data.reasons ?? []).filter((t) => t.includes("分點"));

  if (!data.branches.length && !data.branch_history?.length && score == null) {
    return (
      <div className="py-[46px] text-center text-sm text-muted-foreground">
        尚無此股分點資料。免費資料目前只抓評分池前80檔的前15大買賣超,會隨每日累積增加。
      </div>
    );
  }

  // 分點分卡 + 理由風險由 score/reasons 觸發;範圍選擇/摘要/買賣超列表與 K 線視圖共用同一元件,不留兩份代碼。
  return <BranchFlowSection branches={data.branches} branchHistory={data.branch_history} score={score} reasons={branchReasons} />;
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
    <div className="mt-3.5 grid gap-2.5 rounded-[var(--r-lg)] border border-border bg-card p-3.5 shadow-[var(--shadow-card)] md:grid-cols-[90px_1fr] md:items-center">
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
          t.reasons.map((r) => (
            <span key={r.code} className="rounded-full border border-[color:var(--line)] px-2 py-[3px] text-[11.5px] text-[color:var(--ink-2)]">
              {r.text}
            </span>
          ))
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
    return <div className="py-[46px] text-center text-sm text-muted-foreground">目前沒有可彙總的權證成交資料</div>;
  }

  return (
    <div className="grid gap-3 rounded-[var(--r-lg)] border border-border bg-card p-3.5 shadow-[var(--shadow-card)]">
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
                          sorted && "text-foreground shadow-[inset_0_0_0_1px_var(--border-strong)]",
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
  );
}

export default function StockPage() {
  return (
    <Suspense fallback={<div className="py-[46px] text-center text-sm text-muted-foreground">載入中…</div>}>
      <StockView />
    </Suspense>
  );
}
