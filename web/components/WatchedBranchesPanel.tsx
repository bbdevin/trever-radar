"use client";

// 自選 →「特定分點」分頁(docs/52):選幾個分點(一個為主),看今天同步買超／賣超的股票與估計仍持有。

import { useMemo, useState } from "react";
import Link from "next/link";
import { ArrowUpDown, Plus, Search, Star, X } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { fmtAmount, fmtPct, chgClass } from "@/lib/format";
import { cn, filterChipClass, pillTabClass } from "@/lib/utils";
import type { WatchDataState } from "@/lib/watchedBranchSet";
import {
  addBranch,
  amountEst,
  cellLine,
  emptyText,
  filterRows,
  fmtMD,
  HONESTY_NOTE,
  isBigHold,
  MAX_BRANCHES,
  modeDefinition,
  modeLabel,
  PUSH_NOTE,
  removeBranch,
  searchBranches,
  setAnchor,
  SIDE_LABEL,
  sideLots,
  SORT_OPTIONS,
  sortRows,
  type BranchSet,
  type ComboMode,
  type ComboRow,
  type Side,
  type SortKey,
  type WatchIndex,
} from "@/lib/watchedBranches";

const MODES: ComboMode[] = ["anchor", "anchor_plus", "all", "any"];
const SIDES: Side[] = ["buy", "sell", "hold"];
const PAGE = 40;

const CHG_TEXT: Record<string, string> = { up: "text-up", down: "text-down", flat: "text-foreground" };

export default function WatchedBranchesPanel({
  set,
  onChange,
  data,
}: {
  set: BranchSet;
  onChange: (next: BranchSet) => void;
  data: WatchDataState;
}) {
  const [side, setSide] = useState<Side>("buy");
  const [mode, setMode] = useState<ComboMode>("anchor");
  const [sortKey, setSortKey] = useState<SortKey>("combo");
  const [shown, setShown] = useState(PAGE);

  const ready = data.status === "ready" ? data : null;
  const holdMin = ready?.index.hold_min ?? 100;
  const list = useMemo(() => {
    if (!ready) return [];
    const effSort: SortKey = side === "hold" && (sortKey === "lots" || sortKey === "amount") ? "hold" : sortKey;
    return sortRows(filterRows(ready.rows, set, side, mode, holdMin), side, effSort);
  }, [ready, set, side, mode, sortKey, holdMin]);

  return (
    <div className="pb-7" data-testid="watched-branches">
      <BranchSetEditor set={set} onChange={onChange} index={ready?.index ?? null} />

      {data.status === "loading" && (
        <div className="flex flex-col gap-2">
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-[120px] rounded-[var(--r-md)]" />)}
        </div>
      )}
      {data.status === "missing" && (
        <Notice>{"特定分點資料還沒產生,等下一次每日資料更新後就會出現。"}</Notice>
      )}
      {data.status === "error" && (
        <Notice>{"特定分點資料暫時讀不到,請稍後重新整理。"}</Notice>
      )}

      {ready && (
        <>
          <p className="mb-2.5 text-[11.5px] text-muted-foreground">
            {"分點資料日 "}<span className="num font-semibold text-foreground">{fmtMD(ready.index.as_of)}</span>
            {" · 估計仍持有看近 "}{ready.index.window_days}{" 個交易日("}{fmtMD(ready.index.window_from)}{" 起)。"}
            {PUSH_NOTE}
          </p>

          {/* 買超／賣超／估計仍持有 */}
          <div role="tablist" aria-label="方向" className="mb-2 flex w-fit max-w-full gap-0.5 rounded-full border border-border bg-card p-[3px]">
            {SIDES.map((s) => (
              <button
                key={s}
                role="tab"
                aria-selected={side === s}
                onClick={() => { setSide(s); setShown(PAGE); }}
                className={cn(pillTabClass(side === s, s === "buy" ? "primary" : s === "sell" ? "accent" : "warn"), "min-h-11 whitespace-nowrap")}
              >
                {SIDE_LABEL[s]}
              </button>
            ))}
          </div>

          {side !== "hold" && (
            <>
              <div className="mb-1.5 flex flex-wrap gap-1.5" role="group" aria-label="組合">
                {MODES.map((m) => (
                  <button
                    key={m}
                    aria-pressed={mode === m}
                    onClick={() => { setMode(m); setShown(PAGE); }}
                    className={cn(filterChipClass(mode === m), "min-h-11")}
                  >
                    {modeLabel(m, side)}
                  </button>
                ))}
              </div>
              <p className="mb-2.5 text-[12px] text-foreground/85" data-testid="watched-mode-definition">
                {modeDefinition(mode, side, set.anchor, set.branches.length)}
              </p>
            </>
          )}
          {side === "hold" && (
            <p className="mb-2.5 text-[12px] text-foreground/85">
              {`任一選的分點估計仍持有 ≥ ${holdMin.toLocaleString("zh-TW")} 張的股票,含今天沒進前 15 大的;每個分點最多列 ${ready.index.hold_top} 檔今天沒出現的。`}
            </p>
          )}

          <div className="mb-2.5 flex items-center gap-2">
            <span className="num text-[13px] font-bold">{list.length}{" 檔"}</span>
            {ready.loadingShards && <span className="text-[11.5px] text-muted-foreground">{"讀取中…"}</span>}
            <div className="ml-auto flex items-center gap-1.5">
              <ArrowUpDown size={13} className="text-muted-foreground" />
              <select
                value={sortKey}
                onChange={(e) => setSortKey(e.target.value as SortKey)}
                className="min-h-11 rounded-md border border-border bg-card px-2.5 py-1.5 text-[12.5px] text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                aria-label="排序方式"
              >
                {SORT_OPTIONS.filter((o) => side !== "hold" || o.key === "hold" || o.key === "combo").map((o) => (
                  <option key={o.key} value={o.key}>{o.label}</option>
                ))}
              </select>
            </div>
          </div>

          {list.length === 0 && !ready.loadingShards ? (
            <Notice>{emptyText(side, mode, ready.index.as_of)}</Notice>
          ) : (
            <div className="flex flex-col gap-2">
              {list.slice(0, shown).map((r) => (
                <ComboCard key={r.stock_id} row={r} set={set} side={side} />
              ))}
              {list.length > shown && (
                <button
                  onClick={() => setShown((n) => n + PAGE)}
                  className="min-h-11 cursor-pointer rounded-[var(--r-md)] border border-border bg-card text-[13px] font-semibold text-foreground transition-colors duration-200 hover:bg-secondary/80"
                >
                  {`再顯示 ${Math.min(PAGE, list.length - shown)} 檔(共 ${list.length} 檔)`}
                </button>
              )}
            </div>
          )}

          <p className="mt-4 text-[11.5px] leading-relaxed text-muted-foreground">{HONESTY_NOTE}</p>
        </>
      )}
    </div>
  );
}

function Notice({ children }: { children: React.ReactNode }) {
  return (
    <Alert className="bg-card">
      <AlertDescription className="text-[13px] text-foreground">{children}</AlertDescription>
    </Alert>
  );
}

function BranchSetEditor({ set, onChange, index }: { set: BranchSet; onChange: (s: BranchSet) => void; index: WatchIndex | null }) {
  const [adding, setAdding] = useState(false);
  const [q, setQ] = useState("");
  const hits = index ? searchBranches(index, q, set.branches) : [];
  const full = set.branches.length >= MAX_BRANCHES;
  const known = new Set(index?.branches.map((b) => b[0]) ?? []);

  return (
    <section className="my-3.5 rounded-[var(--r-md)] border border-border bg-card p-3 shadow-[var(--shadow-card)]" aria-label="我的特定分點">
      <div className="mb-2 flex items-baseline gap-2">
        <h2 className="text-[13.5px] font-bold">{"我的特定分點"}</h2>
        <span className="text-[11.5px] text-muted-foreground">{"點名稱設為主分點"}</span>
      </div>
      <ul className="flex flex-wrap gap-1.5">
        {set.branches.map((b) => {
          const anchor = b === set.anchor;
          return (
            <li key={b} className={cn(
              "flex items-center rounded-full border pl-1",
              anchor ? "border-primary bg-primary/12" : "border-border bg-background",
            )}>
              <button
                onClick={() => onChange(setAnchor(set, b))}
                aria-pressed={anchor}
                title={anchor ? "主分點" : "設為主分點"}
                className="flex min-h-11 cursor-pointer items-center gap-1 px-2 text-[13px] font-semibold"
              >
                <Star size={13} className={anchor ? "fill-primary text-primary" : "text-muted-foreground"} />
                <span className={anchor ? "text-primary" : "text-foreground"}>{b}</span>
                {anchor && <span className="rounded-sm bg-primary px-1 text-[10.5px] font-bold text-primary-foreground">{"主"}</span>}
                {index && !known.has(b) && <span className="text-[10.5px] font-normal text-muted-foreground">{"(近 60 日未見)"}</span>}
              </button>
              <button
                onClick={() => onChange(removeBranch(set, b))}
                disabled={set.branches.length <= 1}
                aria-label={`移除 ${b}`}
                className="flex h-11 w-9 cursor-pointer items-center justify-center rounded-full text-muted-foreground transition-colors duration-200 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
              >
                <X size={14} />
              </button>
            </li>
          );
        })}
        {!adding && (
          <li>
            <button
              onClick={() => setAdding(true)}
              disabled={full || !index}
              className="flex min-h-11 cursor-pointer items-center gap-1 rounded-full border border-dashed border-border px-3 text-[13px] font-semibold text-muted-foreground transition-colors duration-200 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Plus size={14} />{full ? `最多 ${MAX_BRANCHES} 個` : "加分點"}
            </button>
          </li>
        )}
      </ul>
      {adding && (
        <div className="mt-2.5">
          <div className="flex items-center gap-1.5">
            <div className="relative flex min-w-0 flex-1 items-center">
              <Search size={13} className="absolute left-2.5 text-muted-foreground" />
              <input
                autoFocus
                type="text"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder={"搜尋分點,例如 凱基-台北"}
                aria-label={"搜尋要加入的分點"}
                className="min-h-11 w-full min-w-0 rounded-md border border-border bg-background pl-7 pr-2.5 text-[13px] text-foreground placeholder:text-muted-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
            </div>
            <button
              onClick={() => { setAdding(false); setQ(""); }}
              className="min-h-11 cursor-pointer rounded-md px-3 text-[13px] font-semibold text-muted-foreground hover:text-foreground"
            >
              {"完成"}
            </button>
          </div>
          {q.trim() && (
            <ul className="mt-1.5 flex flex-col overflow-hidden rounded-md border border-border">
              {hits.length === 0 && (
                <li className="px-3 py-2.5 text-[12.5px] text-muted-foreground">{"近 60 個交易日沒有符合的分點。"}</li>
              )}
              {hits.map(([name, , nb, ns]) => (
                <li key={name} className="border-b border-border last:border-b-0">
                  <button
                    onClick={() => { onChange(addBranch(set, name)); setQ(""); if (set.branches.length + 1 >= MAX_BRANCHES) setAdding(false); }}
                    disabled={full}
                    className="flex min-h-11 w-full cursor-pointer items-center gap-2 px-3 text-left text-[13px] transition-colors duration-200 hover:bg-secondary/80 disabled:cursor-not-allowed"
                  >
                    <span className="min-w-0 flex-1 truncate font-semibold" title={name}>{name}</span>
                    <span className="num shrink-0 text-[11.5px] text-muted-foreground">
                      {"今天 買超 "}<span className="text-up">{nb}</span>{" · 賣超 "}<span className="text-down">{ns}</span>{" 檔"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

function ComboCard({ row, set, side }: { row: ComboRow; set: BranchSet; side: Side }) {
  const cls = chgClass(row.chg);
  const lots = sideLots(row, side);
  const amt = side === "hold" ? null : amountEst(lots, row.close);
  const co = side === "buy" ? row.buyers.length : side === "sell" ? row.sellers.length : null;
  const anyBig = set.branches.some((b) => isBigHold(row.cells[b]?.hold ?? 0, row.avgVol));
  return (
    <article
      className={cn(
        "rounded-[var(--r-md)] border bg-card p-3 shadow-[var(--shadow-card)]",
        anyBig ? "border-warn/50" : "border-border",
      )}
      data-testid="watched-card"
    >
      <Link href={`/stock?id=${row.stock_id}`} className="flex min-h-11 items-center gap-2 no-underline">
        <div className="flex min-w-0 flex-1 items-baseline gap-1.5">
          <span className="truncate text-[15px] font-bold text-foreground" title={row.name}>{row.name}</span>
          <span className="num shrink-0 text-[11.5px] text-muted-foreground">{row.stock_id}</span>
        </div>
        <div className="flex shrink-0 items-baseline gap-1.5">
          <span className={cn("num text-[15px] font-bold", CHG_TEXT[cls])}>{row.close != null ? row.close.toLocaleString("zh-TW") : "—"}</span>
          <span className={cn("num text-[12px] font-semibold", CHG_TEXT[cls])}>{fmtPct(row.chg)}</span>
        </div>
      </Link>
      <div className="mb-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px]">
        {co != null && (
          <span className={cn(
            "num rounded-full px-2 py-0.5 font-bold",
            side === "buy" ? "bg-up/15 text-up" : "bg-down/15 text-down",
          )}>
            {`同${side === "buy" ? "買" : "賣"} ${co}/${set.branches.length}`}
          </span>
        )}
        <span className="num text-foreground">
          {side === "hold" ? `合計估計仍持有 ${lots.toLocaleString("zh-TW")} 張` : `合計${SIDE_LABEL[side]} ${lots.toLocaleString("zh-TW")} 張`}
        </span>
        {amt != null && <span className="num text-muted-foreground">{`約 ${fmtAmount(amt)}`}</span>}
        {row.avgVol != null && row.avgVol > 0 && (
          <span className="num text-muted-foreground">{`20 日均量 ${row.avgVol.toLocaleString("zh-TW")} 張`}</span>
        )}
      </div>
      <ul className="flex flex-col divide-y divide-border">
        {set.branches.map((b) => {
          const c = row.cells[b];
          const line = cellLine(c);
          const big = isBigHold(c?.hold ?? 0, row.avgVol);
          const net = c?.net ?? null;
          return (
            <li key={b} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-2 py-1.5">
              <span className="flex min-w-0 items-center gap-1 text-[12.5px]">
                {b === set.anchor && <span className="shrink-0 rounded-sm bg-primary px-1 text-[10.5px] font-bold text-primary-foreground">{"主"}</span>}
                <span className={cn("truncate", c ? "font-semibold text-foreground" : "text-muted-foreground")} title={b}>{b}</span>
              </span>
              <span className={cn(
                "num text-right text-[12.5px] font-semibold",
                net == null ? "font-normal text-muted-foreground" : net > 0 ? "text-up" : net < 0 ? "text-down" : "text-foreground",
              )}>
                {net == null ? (c ? "未進前 15 大" : "—") : `${net > 0 ? "+" : net < 0 ? "−" : ""}${Math.abs(net).toLocaleString("zh-TW")} 張`}
              </span>
              {c && (
                <span className="col-span-2 mt-0.5 flex flex-wrap items-center gap-1.5 text-[11.5px] text-muted-foreground">
                  <span className={cn("num", big && "font-semibold text-foreground")}>{line.hold}</span>
                  {big && (
                    <span
                      className="rounded-full bg-warn/15 px-1.5 py-px text-[10.5px] font-bold text-warn"
                      title={`估計仍持有 ≥ 1,000 張,或 ≥ 這檔近 20 日均量`}
                    >
                      {"持有量大"}
                    </span>
                  )}
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </article>
  );
}
