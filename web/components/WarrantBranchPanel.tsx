"use client";

import { useEffect, useMemo, useRef, useState, type RefObject } from "react";
import KChart from "@/components/KChart";
import { dataFetch } from "@/lib/dataFetch";
import type { Candle } from "@/lib/types";
import { cn, pillTabClass } from "@/lib/utils";
import {
  branchAmount,
  branchSeries,
  buildStripItems,
  defaultBranch,
  fmtWanSigned,
  fmtWanValueSigned,
  hasSelfIssued,
  rankBranches,
  resolveBreakdown,
  searchBranches,
  selfIssuedTag,
  stepIndex,
  stripOptionLabel,
  toWanSeries,
  type DailyEntry,
  type RankedBranch,
  type SelfIssued,
  type StripItem,
  type WarrantKind,
} from "@/lib/warrantBranches";
import { Skeleton } from "@/components/ui/skeleton";

export type WarrantBreakdown = {
  warrant_id: string;
  warrant_name: string;
  kind: "call" | "put" | string;
  net_lots: number;
  net_amount: number;
  /** 可選:這檔權證是該券商同集團發行的。 */
  self?: boolean;
};

export type WarrantBranchRow = {
  branch_name: string;
  underlying_id: string;
  underlying_name: string;
  net_amount: number;
  /** 舊分片內嵌;新分片(breakdown_split)拆到 {id}.breakdown.json。 */
  breakdown?: WarrantBreakdown[];
  self?: SelfIssued;
};

/** {id}.breakdown.json:timeframe → 券商 → 逐檔明細。 */
type SplitBreakdown = Record<string, Record<string, WarrantBreakdown[]>>;

type WarrantBreakdownFile = {
  version: number;
  data_date: string | null;
  stock_id: string;
  timeframes: SplitBreakdown;
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
  /** 可選:[日期, 認購金額, 認售金額],分片內每一家券商;缺的日子不是 0。 */
  daily_from?: string;
  daily?: Record<string, DailyEntry[]>;
  /** 可選:券商名稱 → 代號(參考圖的「代號」欄)。 */
  branch_codes?: Record<string, string>;
  /** 可選:true = 列上沒有 breakdown,點選券商時才抓 {id}.breakdown.json。 */
  breakdown_split?: boolean;
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
/**
 * 手機版 K 線高度(2026-10-03):390×844 扣掉頁首、個股摘要列、分頁列與底部導覽約剩
 * 620px,要讓「切換券商列 + 整張圖」同屏,圖只能約 350px。桌機不受影響。
 */
export const MOBILE_CHART_HEIGHT = "[height:clamp(300px,42vh,380px)]";

function SummaryChevron() {
  return (
    <span aria-hidden className="text-muted-foreground transition-transform duration-200 group-open:rotate-90">
      ›
    </span>
  );
}

function fmtWan(amt: number, digits = 0): string {
  return (Math.abs(amt) / 10000).toLocaleString("zh-TW", { maximumFractionDigits: digits });
}

/** 個股權證分頁：同標的分點淨買賣超（對齊 /branch 權證分點異動） */
/**
 * 個股權證分頁(2026-10-02 改版,版面依使用者給的參考圖):左邊「權證買超／賣超金額
 * 最多券商」兩張排行,右邊點選券商後顯示股價 K 線與該券商在這檔權證上的逐日買賣超
 * 金額,下方是它在區間內買賣了哪幾檔權證。金額為認購＋認售合計(使用者 2026-10-02 選擇),
 * 明細逐檔標「購／售」:買認售是看空,讀合計時要看明細。
 */
export default function WarrantBranchPanel({
  stockId,
  stockName,
  candles,
}: {
  stockId: string;
  stockName?: string;
  candles: Candle[];
}) {
  const [byTf, setByTf] = useState<Record<string, WarrantBranchRow[]> | null>(null);
  const [daily, setDaily] = useState<Record<string, DailyEntry[]> | undefined>(undefined);
  const [codes, setCodes] = useState<Record<string, string>>({});
  const [query, setQuery] = useState("");
  const [tf, setTf] = useState<Timeframe>("5d");
  // 使用者 2026-10-02:不分認購／認售,合計顯示;明細逐檔標「購／售」。
  const kind: WarrantKind = "all";
  const [picked, setPicked] = useState<string | null>(null);
  const [showAllWarrants, setShowAllWarrants] = useState(false);
  const [error, setError] = useState(false);
  const [usingMarketFallback, setUsingMarketFallback] = useState(false);
  const [dataDate, setDataDate] = useState<string | null>(null);
  // 拆檔明細:breakdownSplit = 分片宣告明細在第二個檔;split 載入後才有值。
  const [breakdownSplit, setBreakdownSplit] = useState(false);
  const [split, setSplit] = useState<SplitBreakdown | null>(null);
  const [splitError, setSplitError] = useState(false);
  const [excludeSelf, setExcludeSelf] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setByTf(null);
    setDaily(undefined);
    setCodes({});
    setBreakdownSplit(false);
    setSplit(null);
    setSplitError(false);
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
            codes: {},
            splitFile: false,
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
          return { rows: {} as Record<string, WarrantBranchRow[]>, fallback: false, dataDate: index.data_date, daily: undefined, codes: {}, splitFile: false };
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
        const nextCodes = shard.branch_codes && typeof shard.branch_codes === "object" && !Array.isArray(shard.branch_codes)
          ? shard.branch_codes
          : {};
        return {
          rows: shard.timeframes, fallback: false, dataDate: index.data_date, daily: nextDaily, codes: nextCodes,
          // 舊分片沒有這個鍵,明細仍內嵌在列上(程式碼可能先於下一次 VPS 匯出上線)。
          splitFile: shard.breakdown_split === true,
        };
      })
      .then(({ rows, fallback, dataDate: nextDataDate, daily: nextDaily, codes: nextCodes, splitFile }) => {
        if (!cancelled) {
          setUsingMarketFallback(fallback);
          setDataDate(nextDataDate);
          setByTf(rows);
          setDaily(nextDaily);
          setCodes(nextCodes ?? {});
          setBreakdownSplit(splitFile);
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

  const minAbs = usingMarketFallback ? LARGE_AMOUNT : DETAIL_MIN_AMOUNT;
  const canExclude = !!rows && hasSelfIssued(rows);
  const exclude = excludeSelf && canExclude;
  const buys = useMemo(
    () => (rows ? rankBranches(rows, kind, "buy", 10, { excludeSelf: exclude, minAbs }) : []),
    [rows, kind, exclude, minAbs],
  );
  const sells = useMemo(
    () => (rows ? rankBranches(rows, kind, "sell", 10, { excludeSelf: exclude, minAbs }) : []),
    [rows, kind, exclude, minAbs],
  );

  // 選中的券商(點排行或搜尋)只要還在這段期間的資料裡就保留;換區間後不在了,
  // 才改回預設(買超第一名)。搜尋到的券商可以不在前 10 名裡。
  const inRows = (name: string | null) => !!name && !!rows?.some((r) => r.branch_name === name);
  const selected = inRows(picked) ? picked : defaultBranch(buys, sells);
  const hits = useMemo(
    () => (rows ? searchBranches(rows, query, kind, codes, 20, exclude) : []),
    [rows, query, kind, codes, exclude],
  );
  const selectedRow = rows?.find((r) => r.branch_name === selected) ?? null;
  const series = useMemo(() => toWanSeries(branchSeries(daily, selected, kind)), [daily, selected, kind]);
  // 手機「切換券商」下拉選單:排行順序;排除模式下金額已不含自家權證,標籤會誤導,所以不標(與排行表一致)。
  const stripItems = useMemo(() => buildStripItems(buys, sells, codes, !exclude), [buys, sells, codes, exclude]);
  // 手機:點下方排行列或搜尋結果後,把 K 線上方的切換列捲回畫面頂端,直接看到重畫的圖。
  // 下拉選單與 ‹ › 本身就在圖上方,不捲動。桌機排行就在圖左邊,不捲動。
  const switcherRef = useRef<HTMLDivElement>(null);
  const pickAndReveal = (name: string) => {
    setPicked(name);
    if (!window.matchMedia("(max-width:767px)").matches) return;
    const row = switcherRef.current;
    if (!row) return;
    // 不能直接 scrollIntoView:頂端有站台標頭＋個股分頁列(sticky,高度隨精簡摘要變),
    // 會蓋住切換列。量出頂端 sticky/fixed 層的下緣,捲到它下方 8px。
    const stickyBottom = Math.max(0, ...[...document.querySelectorAll<HTMLElement>("header, .sticky")]
      .filter((el) => {
        const pos = getComputedStyle(el).position;
        const r = el.getBoundingClientRect();
        return (pos === "sticky" || pos === "fixed") && r.height > 0 && r.top < window.innerHeight / 3;
      })
      .map((el) => el.getBoundingClientRect().bottom));
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.scrollBy({ top: row.getBoundingClientRect().top - stickyBottom - 8, behavior: reduce ? "auto" : "smooth" });
  };

  useEffect(() => {
    setPicked(null);
    setExcludeSelf(false);
  }, [stockId]);

  // 明細拆檔:有券商被選中(含預設選中的買超第一名)才抓,每檔股票只抓一次。
  // 排行與 K 線不等它,第一屏只需要分片本身。
  const needSplit = breakdownSplit && !!selected && split === null && !splitError;
  // 載入失敗不卡到換股票:改選別的券商就重試一次。
  useEffect(() => {
    setSplitError(false);
  }, [selected]);
  useEffect(() => {
    if (!needSplit) return;
    let cancelled = false;
    dataFetch(`/data/branches/warrant-stock-details/${encodeURIComponent(stockId)}.breakdown.json`)
      .then(async (response) => {
        if (!response.ok) throw response.status;
        const file = await response.json() as WarrantBreakdownFile;
        if (
          file.version !== DETAIL_CONTRACT_VERSION
          || file.stock_id !== stockId
          || file.data_date !== dataDate
          || !file.timeframes || typeof file.timeframes !== "object"
        ) throw new Error("權證分點明細格式錯誤");
        if (!cancelled) setSplit(file.timeframes);
      })
      .catch(() => {
        if (!cancelled) setSplitError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [needSplit, stockId, dataDate]);

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

  const threshold = minAbs / 10000;
  // null = 拆檔明細還沒到(或載入失敗);[] = 真的沒有明細。
  const resolved = resolveBreakdown(selectedRow, split, tf);
  const breakdown = [...(resolved ?? [])]
    .sort((a, b) => Math.abs(b.net_amount) - Math.abs(a.net_amount));
  const selectedAmount = selectedRow ? branchAmount(selectedRow, kind, exclude) : 0;
  const selectedSelf = selectedRow?.self;
  const selectedTag = selfIssuedTag(selectedSelf);
  // 排除模式下列上的金額已不含自家權證,標籤會誤導,所以不標。
  const anyTag = !exclude && [...buys, ...sells].some((r) => selfIssuedTag(r.self));

  return (
    <section className="grid gap-3 max-md:gap-2 rounded-[var(--r-lg)] border border-border bg-card p-3.5 shadow-[var(--shadow-card)]">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="max-md:w-full">
          {/* 手機:說明折起來、與標題同一行,讓切換列與整張圖留在同一屏;展開時換到下一行全寬。 */}
          <div className="flex flex-wrap items-center gap-x-2">
            <h3 className="text-sm font-bold text-foreground">權證分點進出</h3>
            {dataDate && <span className="ml-auto text-[11px] text-muted-foreground md:hidden">資料日 {dataDate}</span>}
            <details className={cn("group md:hidden open:basis-full", !dataDate && "ml-auto")}>
              <summary className="flex min-h-7 cursor-pointer list-none items-center gap-1 text-[11.5px] text-muted-foreground [&::-webkit-details-marker]:hidden">
                說明<SummaryChevron />
              </summary>
              <p className="pb-1 text-[11.5px] leading-relaxed text-muted-foreground">
              用 K 線上方的「切換券商」(或下方排行、搜尋)選券商,對照股價看它每天在這檔股票權證上的買賣超金額。
              金額為認購＋認售合計;明細逐檔標示<b className="font-semibold text-foreground">購／售</b>,買認售是看空。
              金額為估計值(張數 × 1000 × 當日權證收盤價);每檔權證只有前 15 大分點,
              區間淨額 ≥ {threshold} 萬才列入。
              </p>
            </details>
          </div>
          <p className="mt-0.5 text-[11.5px] leading-relaxed text-muted-foreground max-md:hidden">
            點選左邊的券商,右邊對照股價看它每天在這檔股票權證上的買賣超金額。
            金額為認購＋認售合計;下方明細逐檔標示<b className="font-semibold text-foreground">購／售</b>,買認售是看空。
            金額為估計值(張數 × 1000 × 當日權證收盤價);每檔權證只有前 15 大分點,
            區間淨額 ≥ {threshold} 萬才列入。
          </p>
          {dataDate && <p className="mt-1 text-[11px] text-muted-foreground max-md:hidden">資料日 {dataDate}</p>}
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
        {canExclude && (
          <button
            type="button"
            role="switch"
            aria-checked={exclude}
            onClick={() => setExcludeSelf((v) => !v)}
            className={pillTabClass(exclude)}
          >
            排除同券商發行
          </button>
        )}
      </div>
      {exclude && (
        <p className="-mt-1 text-[11px] leading-relaxed text-muted-foreground">
          只扣有「發行商」「同券商」標籤的分點(過半金額在自家集團發行的權證)在自家權證上的金額,其他分點保留全額;
          扣完仍 ≥ {threshold} 萬才列入。只在原本已上榜的分點中重排;K 線下方的逐日圖仍是合計。
        </p>
      )}

      {buys.length === 0 && sells.length === 0 ? (
        <p className="py-4 text-center text-[13px] text-muted-foreground">
          此區間沒有權證淨買賣超達 {threshold} 萬的券商。涵蓋依已匯入且符合條件的權證池,每檔僅前 15 大分點;沒有資料不代表沒有交易。
        </p>
      ) : (
        // 手機順序:切換券商 → K 線 → 註記 → 搜尋與排行 → 權證明細。右欄在手機上是
        // display:contents,子元素直接排進這個單欄 grid,再用 order 把左欄與明細排到後面;
        // 桌機(md 以上)左右兩欄與改版前相同。
        // 手機必須明寫單欄 minmax(0,1fr):隱式欄寬是 auto,會被最寬的子元素(放大字級時尤其)
        // 撐開,右側被卡片裁掉(2026-10-03 使用者回報「右邊被截斷」;字級大 +36px、特大 +104px)。
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-3 max-md:gap-2 md:grid-cols-[minmax(0,17rem)_minmax(0,1fr)]">
          <div className="grid min-w-0 content-start gap-3 max-md:order-1 max-md:mt-1">
            {/* 搜尋券商:名稱或代號,不限排行前 10(參考圖右上角的「搜尋券商」)。 */}
            <div className="relative">
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="搜尋券商(名稱或代號)"
                aria-label="搜尋券商"
                className="min-h-10 w-full rounded-md border border-border bg-background px-3 text-[13px] text-foreground placeholder:text-muted-foreground focus:border-[color:var(--accent-2)] focus:outline-none"
              />
              {query.trim() && (
                <ul className="absolute z-20 mt-1 max-h-72 w-full overflow-y-auto rounded-md border border-border bg-card shadow-[var(--shadow-card)]">
                  {hits.length === 0 ? (
                    <li className="px-3 py-2 text-[12px] text-muted-foreground">這段期間沒有符合的券商(淨額 ≥ {threshold} 萬才列入)</li>
                  ) : hits.map((h) => (
                    <li key={h.branch_name}>
                      <button
                        type="button"
                        onClick={() => { pickAndReveal(h.branch_name); setQuery(""); }}
                        className="flex min-h-10 w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-[12.5px] hover:bg-secondary"
                      >
                        <span className="min-w-0 truncate">
                          {h.code && <span className="num mr-2 text-muted-foreground">{h.code}</span>}
                          {h.branch_name}
                        </span>
                        <span className={cn("num shrink-0", h.amount > 0 ? "text-up" : h.amount < 0 ? "text-down" : "text-muted-foreground")}>
                          {fmtWanSigned(h.amount)}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <RankTable
              title="權證買超金額最多券商"
              tone="up"
              rows={buys}
              codes={codes}
              showTags={!exclude}
              selected={selected}
              onSelect={pickAndReveal}
            />
            <RankTable
              title="權證賣超金額最多券商"
              tone="down"
              rows={sells}
              codes={codes}
              showTags={!exclude}
              selected={selected}
              onSelect={pickAndReveal}
            />
            {anyTag && (
              <p className="text-[11px] leading-relaxed text-muted-foreground">
                <SelfBadge label="發行商" /> 發行券商的總公司席位,過半金額在自家發行的權證:發行商依規定要為自家權證造市,
                這類進出多為造市／避險,不代表看多或看空。
                <SelfBadge label="同券商" className="ml-1" /> 同集團分公司,過半金額是自家發行的權證,只陳述事實。
                發行商取自權證簡稱。
              </p>
            )}
          </div>

          <div className="grid min-w-0 content-start gap-2.5 max-md:contents">
            {/* 使用者 2026-10-03:手機排行維持原本樣式(全展開),K 線正上方用下拉選單切換券商(桌機不顯示)。 */}
            <BrokerSelect
              items={stripItems}
              selected={selected}
              searchItem={selectedRow && !stripItems.some((i) => i.name === selected) ? {
                name: selectedRow.branch_name,
                amount: selectedAmount,
                tone: selectedAmount >= 0 ? "up" : "down",
                ...(codes[selectedRow.branch_name] ? { code: codes[selectedRow.branch_name] } : {}),
              } : null}
              onSelect={setPicked}
              rowRef={switcherRef}
            />
            {candles.length > 0 ? (
              <KChart
                candles={candles}
                visibleDays={120}
                mobileHeightClass={MOBILE_CHART_HEIGHT}
                hideMaRowOnMobile
                branchFlow={series}
                branchFlowLabel={selected ? `${selected} 權證進出` : undefined}
                branchFlowFormat={fmtWanValueSigned}
                // 使用者 2026-10-02:這一行併到均線列下方(圖表上緣),不在 K 線上方另起一行。
                caption={selected ? (
                  <>
                    <span className="font-bold text-foreground">
                      {codes[selected] && <span className="num mr-1 text-muted-foreground">{codes[selected]}</span>}
                      {selected}
                    </span>
                    <span className="text-muted-foreground">·</span>
                    <span className="text-foreground">
                      <span className="num mr-1">{stockId}</span>{stockName}
                    </span>
                    {selectedRow && (
                      <>
                        <span className="text-muted-foreground">·</span>
                        <span className={cn("num font-semibold", selectedAmount >= 0 ? "text-up" : "text-down")}>
                          {TIMEFRAMES.find((t) => t.key === tf)?.label}權證{exclude ? "(排除同券商)" : ""} {fmtWanSigned(selectedAmount)}
                        </span>
                      </>
                    )}
                  </>
                ) : undefined}
              />
            ) : (
              <p className="py-6 text-center text-[13px] text-muted-foreground">尚無 K 線資料。</p>
            )}
            {selected && !series && (
              <p className="text-[11.5px] text-muted-foreground">
                {daily === undefined
                  ? "逐日權證進出要等下一次資料匯出後才會出現,目前只能看區間合計。"
                  : `${selected} 在近 120 個交易日沒有權證的逐日紀錄(不在任何一檔權證的前 15 大分點)。`}
              </p>
            )}

            {selectedSelf && selectedSelf.pct > 0 && (
              <p className="text-[11.5px] leading-relaxed text-muted-foreground">
                {selected} 這段期間 <b className="num font-semibold text-foreground">{selectedSelf.pct}%</b> 的權證金額是同券商發行的權證
                (淨 {fmtWanSigned(selectedSelf.net)})
                {selectedTag?.hq ? ";這是發行商總公司席位,多為發行商造市／避險,不代表看多或看空。" : "。"}
              </p>
            )}
            {selectedRow && resolved === null && breakdownSplit && (
              splitError ? (
                <p className="text-[11.5px] text-muted-foreground max-md:order-2">權證明細載入失敗(改選其他券商會重試),區間合計與排行不受影響。</p>
              ) : (
                <Skeleton className="h-24 w-full rounded-[var(--r-md)] max-md:order-2" />
              )
            )}
            {breakdown.length > 0 && (
              <div className="rounded-[var(--r-md)] border border-border bg-background px-2 py-2 max-md:order-2">
                <p className="mb-1 px-2 text-[11.5px] font-semibold text-foreground">
                  {selected} 這段期間的權證明細
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
                          <span
                            className={cn(
                              "rounded px-1 py-0.5 text-[9px] font-bold leading-none",
                              brk.kind === "call" ? "bg-up/10 text-up" : "bg-down/10 text-down",
                            )}
                          >
                            {brk.kind === "call" ? "購" : "售"}
                          </span>
                          {brk.self && <SelfBadge label="自家" />}
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

/** 同券商發行的小標籤(中性色:它不是買賣方向,只是提醒這筆金額的性質)。 */
function SelfBadge({ label, title, className }: { label: string; title?: string; className?: string }) {
  return (
    <span
      title={title}
      className={cn(
        "inline-block shrink-0 rounded border border-border px-1 py-0.5 text-[9.5px] font-semibold leading-none text-muted-foreground",
        className,
      )}
    >
      {label}
    </span>
  );
}

const STEP_BTN =
  "flex size-11 shrink-0 items-center justify-center rounded-[var(--r-md)] border border-border bg-card text-lg text-foreground disabled:opacity-35";

/**
 * 手機版 K 線正上方的「切換券商」下拉選單(桌機隱藏,桌機用左邊排行表)。選項 = 目前區間、
 * 目前「排除同券商發行」狀態下的買超／賣超排行;搜尋選到、不在排行裡的券商列在最前面。
 */
function BrokerSelect({
  items,
  selected,
  searchItem,
  onSelect,
  rowRef,
}: {
  items: StripItem[];
  selected: string | null;
  /** 搜尋選到、不在排行裡的券商(放在「搜尋」群組);null = 選中的券商就在排行裡。 */
  searchItem: StripItem | null;
  onSelect: (name: string) => void;
  rowRef: RefObject<HTMLDivElement | null>;
}) {
  if (items.length === 0 && !searchItem) return null;
  const idx = items.findIndex((i) => i.name === selected);
  const prev = stepIndex(items.length, idx, -1);
  const next = stepIndex(items.length, idx, 1);
  const buys = items.filter((i) => i.tone === "up");
  const sells = items.filter((i) => i.tone === "down");
  return (
    // min-w-0 / w-full:<select> 的固有寬度是最長那個選項,不限制就會把這列撐出卡片(字級放大時更明顯)。
    <div ref={rowRef} className="grid min-w-0 gap-1 md:hidden">
      <label htmlFor="warrant-broker-select" className="text-[11px] font-semibold text-muted-foreground">
        切換券商
      </label>
      <div className="flex min-w-0 items-center gap-1.5">
        <button
          type="button"
          aria-label="上一家券商"
          disabled={prev === null}
          onClick={() => prev !== null && onSelect(items[prev].name)}
          className={STEP_BTN}
        >
          ‹
        </button>
        <select
          id="warrant-broker-select"
          value={selected ?? ""}
          onChange={(e) => onSelect(e.target.value)}
          className="min-h-11 w-0 min-w-0 flex-1 truncate rounded-[var(--r-md)] border border-border bg-card px-2.5 text-[13px] text-foreground focus:border-[color:var(--accent-2)] focus:outline-none"
        >
          {buys.length > 0 && (
            <optgroup label="買超">
              {buys.map((i) => <option key={i.name} value={i.name}>{stripOptionLabel(i)}</option>)}
            </optgroup>
          )}
          {sells.length > 0 && (
            <optgroup label="賣超">
              {sells.map((i) => <option key={i.name} value={i.name}>{stripOptionLabel(i)}</option>)}
            </optgroup>
          )}
          {searchItem && (
            <optgroup label="搜尋">
              <option value={searchItem.name}>{stripOptionLabel(searchItem)}</option>
            </optgroup>
          )}
        </select>
        <button
          type="button"
          aria-label="下一家券商"
          disabled={next === null}
          onClick={() => next !== null && onSelect(items[next].name)}
          className={STEP_BTN}
        >
          ›
        </button>
      </div>
    </div>
  );
}

/** 左邊的排行表:代號、券商、金額(萬)。點列選取,右邊的圖跟著換。 */
function RankTable({
  title,
  tone,
  rows,
  codes,
  showTags,
  selected,
  onSelect,
}: {
  title: string;
  tone: "up" | "down";
  rows: RankedBranch[];
  codes: Record<string, string>;
  showTags: boolean;
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
            const tag = showTags ? selfIssuedTag(r.self) : null;
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
                  <span className="flex min-w-0 items-baseline gap-2">
                    <span className="num w-10 shrink-0 text-[11px] text-muted-foreground">{codes[r.branch_name] ?? ""}</span>
                    <span className="min-w-0 truncate text-foreground" title={r.branch_name}>{r.branch_name}</span>
                    {tag && (
                      <SelfBadge
                        label={tag.label}
                        title={`${tag.pct}% 金額是同券商發行的權證${tag.hq ? ",多為發行商造市／避險" : ""}`}
                      />
                    )}
                  </span>
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
