"use client";

import { useEffect, useMemo, useState } from "react";
import KChart from "@/components/KChart";
import { dataFetch } from "@/lib/dataFetch";
import type { Candle } from "@/lib/types";
import { cn, pillTabClass, segBtnClass } from "@/lib/utils";
import {
  branchSeries,
  defaultBranch,
  fmtWanSigned,
  fmtWanValueSigned,
  kindNet,
  rankBranches,
  toWanSeries,
  type DailyEntry,
  type RankedBranch,
  type WarrantKind,
} from "@/lib/warrantBranches";
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

type WarrantBranchDetailIndex = {
  version: number;
  threshold: number;
  /** 實際權證分點資料日；池內無資料時為 null（不以報價日充數）。 */
  data_date: string | null;
  stocks: string[];
};

type WarrantBranchDetailShard = {
  version: number;
  threshold: number;
  data_date: string | null;
  stock_id: string;
  timeframes: Record<string, WarrantBranchRow[]>;
  /** 可選:[日期, 認購金額, 認售金額],只含排行上的券商;缺的日子不是 0。 */
  daily_from?: string;
  daily?: Record<string, DailyEntry[]>;
};

type Timeframe = "1d" | "2d" | "5d" | "30d" | "120d";

const TIMEFRAMES: { key: Timeframe; label: string }[] = [
  { key: "1d", label: "1日" },
  { key: "2d", label: "2日" },
  { key: "5d", label: "5日" },
  { key: "30d", label: "30日" },
  { key: "120d", label: "120日" },
];

const DETAIL_MIN_AMOUNT = 1_000_000;
/** 明細預設只列金額最大的幾檔:熱門標的一個券商可以有上百檔權證。 */
const BREAKDOWN_PREVIEW = 10;
const LARGE_AMOUNT = 5_000_000;
const DETAIL_CONTRACT_VERSION = 1;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function fmtWan(amt: number, digits = 0): string {
  return (Math.abs(amt) / 10000).toLocaleString("zh-TW", { maximumFractionDigits: digits });
}

/** 個股權證分頁：同標的分點淨買賣超（對齊 /branch 權證分點異動） */
/**
 * 個股權證分頁(2026-10-02 改版,版面依使用者給的參考圖):左邊「權證買超／賣超金額
 * 最多券商」兩張排行,右邊點選券商後顯示股價 K 線與該券商在這檔權證上的逐日買賣超
 * 金額,下方是它在區間內買賣了哪幾檔權證。認購／認售分開(買認售是看空)。
 */
export default function WarrantBranchPanel({ stockId, candles }: { stockId: string; candles: Candle[] }) {
  const [byTf, setByTf] = useState<Record<string, WarrantBranchRow[]> | null>(null);
  const [daily, setDaily] = useState<Record<string, DailyEntry[]> | undefined>(undefined);
  const [tf, setTf] = useState<Timeframe>("5d");
  const [kind, setKind] = useState<WarrantKind>("call");
  const [picked, setPicked] = useState<string | null>(null);
  const [showAllWarrants, setShowAllWarrants] = useState(false);
  const [error, setError] = useState(false);
  const [usingMarketFallback, setUsingMarketFallback] = useState(false);
  const [dataDate, setDataDate] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setByTf(null);
    setDaily(undefined);
    setError(false);
    setUsingMarketFallback(false);
    setDataDate(null);
    dataFetch("/data/branches/warrant-stock-details/index.json")
      .then(async (indexResponse) => {
        // A code deploy can precede the next VPS export. Only a missing index
        // may use the established strict payload; other errors stay visible.
        if (indexResponse.status === 404) {
          const legacyResponse = await dataFetch("/data/branches/warrant_branches.json");
          if (!legacyResponse.ok) throw legacyResponse.status;
          // 全市場檔已改為 v1 wrapper，但程式碼可能早於下一次 export 上線，
          // 舊的裸 mapping 仍要能讀，且不替它捏造資料日。
          const legacy = await legacyResponse.json() as unknown;
          const asMapping = (value: unknown): Record<string, WarrantBranchRow[]> =>
            value && typeof value === "object" && !Array.isArray(value)
              ? value as Record<string, WarrantBranchRow[]>
              : {};
          const wrapper = asMapping(legacy) as { version?: unknown; data_date?: unknown; timeframes?: unknown };
          const isWrapped = wrapper.version === 1 && "timeframes" in wrapper;
          return {
            // 壞掉的 body 收斂成空 mapping,而不是 null——null 會讓面板永遠停在
            // 骨架屏,既不顯示資料也不顯示錯誤。
            rows: isWrapped ? asMapping(wrapper.timeframes) : asMapping(legacy),
            fallback: true,
            dataDate: isWrapped && typeof wrapper.data_date === "string" && ISO_DATE.test(wrapper.data_date)
              ? wrapper.data_date
              : null,
            daily: undefined,
          };
        }
        if (!indexResponse.ok) throw indexResponse.status;
        const index = await indexResponse.json() as WarrantBranchDetailIndex;
        if (
          index.version !== DETAIL_CONTRACT_VERSION
          || index.threshold !== DETAIL_MIN_AMOUNT
          || (index.data_date !== null && !ISO_DATE.test(index.data_date))
          || !Array.isArray(index.stocks)
          || !index.stocks.every((id) => typeof id === "string")
        ) throw new Error("權證分點索引格式錯誤");
        // The index is authoritative: never read an old shard for a stock
        // absent from the current snapshot.
        if (!index.stocks.includes(stockId)) {
          return { rows: {} as Record<string, WarrantBranchRow[]>, fallback: false, dataDate: index.data_date, daily: undefined };
        }
        const shardResponse = await dataFetch(`/data/branches/warrant-stock-details/${encodeURIComponent(stockId)}.json`);
        if (!shardResponse.ok) throw shardResponse.status;
        const shard = await shardResponse.json() as WarrantBranchDetailShard;
        if (
          shard.version !== index.version
          || shard.threshold !== index.threshold
          || shard.data_date !== index.data_date
          || shard.stock_id !== stockId
          || !shard.timeframes
          || !TIMEFRAMES.every((timeframe) => Array.isArray(shard.timeframes[timeframe.key]))
        ) throw new Error("權證分點明細格式錯誤");
        // daily 是 2026-10-02 起的可選鍵:舊分片沒有它 → undefined(圖只畫 K 線)。
        const nextDaily = shard.daily && typeof shard.daily === "object" && !Array.isArray(shard.daily)
          ? shard.daily
          : undefined;
        return { rows: shard.timeframes, fallback: false, dataDate: index.data_date, daily: nextDaily };
      })
      .then(({ rows, fallback, dataDate: nextDataDate, daily: nextDaily }) => {
        if (!cancelled) {
          setUsingMarketFallback(fallback);
          setDataDate(nextDataDate);
          setByTf(rows);
          setDaily(nextDaily);
        }
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [stockId]);


  const rows = useMemo(() => {
    if (!byTf) return null;
    return (byTf[tf] ?? []).filter((r) => r.underlying_id === stockId);
  }, [byTf, tf, stockId]);

  const buys = useMemo(() => (rows ? rankBranches(rows, kind, "buy") : []), [rows, kind]);
  const sells = useMemo(() => (rows ? rankBranches(rows, kind, "sell") : []), [rows, kind]);

  // 換區間或種類時,若原本選的券商已不在兩張排行裡,改回預設(買超第一名)。
  const onBoard = (name: string | null) =>
    !!name && (buys.some((b) => b.branch_name === name) || sells.some((b) => b.branch_name === name));
  const selected = onBoard(picked) ? picked : defaultBranch(buys, sells);
  const selectedRow = rows?.find((r) => r.branch_name === selected) ?? null;
  const series = useMemo(() => toWanSeries(branchSeries(daily, selected, kind)), [daily, selected, kind]);
  const kindLabel = kind === "call" ? "認購" : "認售";

  useEffect(() => {
    setPicked(null);
  }, [stockId]);

  useEffect(() => {
    setShowAllWarrants(false);
  }, [selected, tf, kind]);

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

  const threshold = (usingMarketFallback ? LARGE_AMOUNT : DETAIL_MIN_AMOUNT) / 10000;
  const breakdown = (selectedRow?.breakdown ?? [])
    .filter((b) => b.kind === kind)
    .sort((a, b) => Math.abs(b.net_amount) - Math.abs(a.net_amount));

  return (
    <section className="grid gap-3 rounded-[var(--r-lg)] border border-border bg-card p-3.5 shadow-[var(--shadow-card)]">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h3 className="text-sm font-bold text-foreground">權證分點進出</h3>
          <p className="mt-0.5 text-[11.5px] leading-relaxed text-muted-foreground">
            點選左邊的券商,右邊對照股價看它每天在這檔股票權證上的買賣超金額。
            認購與認售分開看:<b className="font-semibold text-foreground">買認售是看空</b>。
            金額為估計值(張數 × 1000 × 當日權證收盤價);每檔權證只有前 15 大分點,
            區間淨額 ≥ {threshold} 萬才列入。
          </p>
          {dataDate && <p className="mt-1 text-[11px] text-muted-foreground">資料日 {dataDate}</p>}
          {usingMarketFallback && (
            <p className="mt-1 text-[11px] text-muted-foreground">
              100 萬明細快照尚未發布,暫以既有 500 萬門檻快照顯示{dataDate ? "" : ";該快照未提供資料日"}。
            </p>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
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
        <div className="flex gap-0.5 rounded-md border border-border p-0.5" role="group" aria-label="權證種類">
          {(["call", "put"] as const).map((k) => (
            <button
              key={k}
              type="button"
              aria-pressed={kind === k}
              onClick={() => setKind(k)}
              className={cn(segBtnClass(kind === k), "min-h-9 px-3")}
            >
              {k === "call" ? "認購" : "認售"}
            </button>
          ))}
        </div>
      </div>

      {buys.length === 0 && sells.length === 0 ? (
        <p className="py-4 text-center text-[13px] text-muted-foreground">
          此區間沒有{kindLabel}權證淨買賣超達 {threshold} 萬的券商。涵蓋依已匯入且符合條件的權證池,每檔僅前 15 大分點;沒有資料不代表沒有交易。
        </p>
      ) : (
        <div className="grid min-w-0 gap-3 md:grid-cols-[minmax(0,17rem)_minmax(0,1fr)]">
          <div className="grid min-w-0 content-start gap-3">
            <RankTable
              title={`${kindLabel}權證買超金額最多券商`}
              tone="up"
              rows={buys}
              selected={selected}
              onSelect={setPicked}
            />
            <RankTable
              title={`${kindLabel}權證賣超金額最多券商`}
              tone="down"
              rows={sells}
              selected={selected}
              onSelect={setPicked}
            />
          </div>

          <div className="grid min-w-0 content-start gap-2.5">
            {selected && (
              <div className="flex flex-wrap items-baseline gap-2">
                <span className="text-[15px] font-bold text-foreground">{selected}</span>
                {selectedRow && (
                  <span className={cn("num text-[13px] font-semibold", kindNet(selectedRow, kind) >= 0 ? "text-up" : "text-down")}>
                    {TIMEFRAMES.find((t) => t.key === tf)?.label}{kindLabel} {fmtWanSigned(kindNet(selectedRow, kind))}
                  </span>
                )}
              </div>
            )}
            {candles.length > 0 ? (
              <KChart
                candles={candles}
                visibleDays={120}
                branchFlow={series}
                branchFlowLabel={selected ? `${selected} ${kindLabel}權證進出` : undefined}
                branchFlowFormat={fmtWanValueSigned}
              />
            ) : (
              <p className="py-6 text-center text-[13px] text-muted-foreground">尚無 K 線資料。</p>
            )}
            {selected && !series && (
              <p className="text-[11.5px] text-muted-foreground">
                {daily === undefined
                  ? "逐日權證進出要等下一次資料匯出後才會出現,目前只能看區間合計。"
                  : `${selected} 在近 120 個交易日沒有${kindLabel}權證的逐日紀錄(不在任何一檔權證的前 15 大分點)。`}
              </p>
            )}

            {breakdown.length > 0 && (
              <div className="rounded-[var(--r-md)] border border-border bg-background px-2 py-2">
                <p className="mb-1 px-2 text-[11.5px] font-semibold text-foreground">
                  {selected} 這段期間的{kindLabel}權證明細
                </p>
                <div className="mb-1 grid grid-cols-[1.4fr_1fr_0.6fr] px-2 text-[10.5px] font-semibold text-muted-foreground">
                  <span>權證</span>
                  <span className="text-right">估金額</span>
                  <span className="text-right">張數</span>
                </div>
                <ul className="flex flex-col gap-1">
                  {(showAllWarrants ? breakdown : breakdown.slice(0, BREAKDOWN_PREVIEW)).map((brk) => {
                    const brkBuy = brk.net_amount > 0;
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
                        </div>
                        <span className={cn("num text-right text-[13px] font-semibold", brkBuy ? "text-up" : "text-down")}>
                          {brkBuy ? "+" : "−"}
                          {fmtWan(brk.net_amount, 1)} 萬
                        </span>
                        <span className="num text-right text-[11px] text-muted-foreground">
                          {brk.net_lots > 0 ? "+" : ""}
                          {brk.net_lots.toLocaleString("zh-TW")}
                        </span>
                      </li>
                    );
                  })}
                </ul>
                {breakdown.length > BREAKDOWN_PREVIEW && (
                  <button
                    type="button"
                    onClick={() => setShowAllWarrants((v) => !v)}
                    className="mt-1.5 min-h-9 w-full rounded-md text-[12px] text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
                  >
                    {showAllWarrants ? "收合" : `顯示全部 ${breakdown.length} 檔權證`}
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

/** 左邊的排行表:券商、金額(萬)。點列選取,右邊的圖跟著換。 */
function RankTable({
  title,
  tone,
  rows,
  selected,
  onSelect,
}: {
  title: string;
  tone: "up" | "down";
  rows: RankedBranch[];
  selected: string | null;
  onSelect: (name: string) => void;
}) {
  return (
    <div className="min-w-0 overflow-hidden rounded-[var(--r-md)] border border-border">
      <div
        className={cn(
          "px-3 py-1.5 text-center text-[12px] font-bold",
          tone === "up" ? "bg-up/12 text-up" : "bg-down/12 text-down",
        )}
      >
        {title}
      </div>
      {rows.length === 0 ? (
        <p className="px-3 py-3 text-center text-[11.5px] text-muted-foreground">這段期間沒有</p>
      ) : (
        <ol className="divide-y divide-[color:var(--line)]">
          {rows.map((r) => {
            const active = r.branch_name === selected;
            return (
              <li key={r.branch_name}>
                <button
                  type="button"
                  onClick={() => onSelect(r.branch_name)}
                  aria-pressed={active}
                  className={cn(
                    "flex min-h-10 w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-[12.5px] transition-colors hover:bg-secondary",
                    active && "bg-secondary font-bold",
                  )}
                >
                  <span className="min-w-0 truncate text-foreground" title={r.branch_name}>{r.branch_name}</span>
                  <span className={cn("num shrink-0 font-semibold", tone === "up" ? "text-up" : "text-down")}>
                    {fmtWanSigned(r.amount)}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
