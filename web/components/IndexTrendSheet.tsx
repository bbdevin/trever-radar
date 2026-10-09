"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Dialog as DialogPrimitive } from "@base-ui/react/dialog";
import { X } from "lucide-react";
import { dataFetch } from "@/lib/dataFetch";
import { OFFLINE_DATA_COPY, isBrowserOffline } from "@/lib/pwa";
import { cn, filterChipClass, pillTabClass } from "@/lib/utils";
import type { IndicesHistJson, MarketIndex } from "@/lib/types";
import {
  INDEX_HIST_URL,
  TREND_EMPTY,
  TREND_HINT,
  TREND_RANGES,
  TREND_RANGE_DEFAULT,
  TREND_SHEET_TITLE,
  TX_STITCH_NOTE,
  axisTickLabel,
  dateTag,
  fmtIndex,
  indexChangeText,
  indexDecimals,
  mmdd,
  orderedIndices,
  rangeStats,
  rangeTone,
  sliceRange,
  txSubtitle,
  type TrendPoint,
  type TrendRange,
} from "@/lib/marketBrief";

const UP = "#e66767";
const DOWN = "#0ca30c";
const FLAT = "#3987e5";
const TONE_COLOR = { up: UP, down: DOWN, flat: FLAT } as const;
const TONE_CLASS = { up: "text-up", down: "text-down", flat: "text-foreground" } as const;

/** 與 KChart 同一組格線/軸色(那裡沒有 export;值逐字相同) */
function chartColors(isDark: boolean) {
  return isDark
    ? { text: "#898781", grid: "#222220", border: "#383835" }
    : { text: "#6b6a64", grid: "#e6e5e0", border: "#d8d7d2" };
}

// 歷史檔一個 session 只抓一次(三個序列都在同一檔);失敗不快取,下次開再試。
let histCache: Promise<IndicesHistJson> | null = null;
function loadHist(): Promise<IndicesHistJson> {
  if (!histCache) {
    histCache = dataFetch(INDEX_HIST_URL)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .catch((e) => {
        histCache = null;
        throw e;
      });
  }
  return histCache;
}

function useIsDark() {
  const [isDark, setIsDark] = useState(
    () => typeof document !== "undefined" && document.documentElement.classList.contains("dark"),
  );
  useEffect(() => {
    const el = document.documentElement;
    const obs = new MutationObserver(() => setIsDark(el.classList.contains("dark")));
    obs.observe(el, { attributes: true, attributeFilter: ["class"] });
    return () => obs.disconnect();
  }, []);
  return isDark;
}

function TrendChart({ points, decimals, onHover }: { points: TrendPoint[]; decimals: number; onHover: (p: TrendPoint | null) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const isDark = useIsDark();
  const onHoverRef = useRef(onHover);
  onHoverRef.current = onHover;

  useEffect(() => {
    if (!ref.current || points.length < 2) return;
    let disposed = false;
    let chart: import("lightweight-charts").IChartApi | undefined;
    const byTime = new Map(points.map((p) => [p[0], p]));
    const color = TONE_COLOR[rangeTone(points)];
    const host = ref.current;
    import("lightweight-charts").then((lw) => {
      if (disposed || !ref.current) return;
      const { createChart, AreaSeries, ColorType, CrosshairMode } = lw;
      const colors = chartColors(isDark);
      chart = createChart(ref.current, {
        autoSize: true,
        layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: colors.text, fontSize: 12 },
        grid: { vertLines: { color: colors.grid }, horzLines: { color: colors.grid } },
        rightPriceScale: { borderColor: colors.border },
        // 時間軸與游標日期一律 MM/DD(月刻度 M月、年刻度 YYYY年),與全站日期寫法一致
        localization: { timeFormatter: (t: unknown) => (typeof t === "string" ? mmdd(t) : String(t)) },
        timeScale: {
          borderColor: colors.border, timeVisible: false, fixLeftEdge: true, fixRightEdge: true,
          tickMarkFormatter: (t: unknown, type: number) => (typeof t === "string" ? axisTickLabel(t, type) : String(t)),
        },
        // 十字游標吸附到序列值(價格標籤顯示那天的收盤);手機垂直拖曳還給 sheet 捲動
        crosshair: { mode: CrosshairMode.Magnet },
        handleScroll: { vertTouchDrag: false, mouseWheel: false, pressedMouseMove: false, horzTouchDrag: false },
        handleScale: { mouseWheel: false, pinch: false, axisPressedMouseMove: false, axisDoubleClickReset: false },
      });
      // 價格軸位數:加權/台指期(萬點)整數就夠,櫃買(幾百點)兩位;手機價格軸要讓出寬度
      const prec = decimals === 0 || points[points.length - 1][1] >= 10000 ? 0 : 2;
      const series = chart.addSeries(AreaSeries, {
        lineColor: color,
        lineWidth: 2,
        topColor: `${color}55`,
        bottomColor: `${color}05`,
        priceLineVisible: false,
        lastValueVisible: true,
        crosshairMarkerVisible: true,
        priceFormat: { type: "price", precision: prec, minMove: 1 / 10 ** prec },
      });
      series.setData(points.map((p) => ({ time: p[0], value: p[1] })));
      chart.timeScale().fitContent();
      chart.subscribeCrosshairMove((param) => {
        const t = typeof param.time === "string" ? param.time : null;
        onHoverRef.current(t ? byTime.get(t) ?? null : null);
      });
      // TradingView 署名(授權要求保留,與 KChart 一致):補可讀名稱;位置與大小不動。
      requestAnimationFrame(() => {
        const logo = host.querySelector<HTMLAnchorElement>('a[href*="tradingview"]');
        if (logo) {
          logo.setAttribute("aria-label", "TradingView Lightweight Charts(圖表元件)");
          logo.setAttribute("title", "TradingView Lightweight Charts");
        }
      });
    });
    return () => {
      disposed = true;
      chart?.remove();
      onHoverRef.current(null);
    };
  }, [points, isDark, decimals]);

  return <div ref={ref} className="h-[300px] w-full" />;
}

/**
 * 大盤走勢 bottom sheet(docs/49 §12)。base-ui Dialog 提供 focus trap、ESC、點背景關閉、
 * 鎖頁面捲動;這裡只管內容:指數切換 chips、範圍 chips、走勢圖(十字游標讀值)、區間統計。
 * 歷史檔 `market/indices_hist.json` 第一次開才抓;抓不到時退回 head.json 的 spark(只有收盤)。
 */
export default function IndexTrendSheet({
  open,
  onOpenChange,
  market,
  onMarketChange,
  indices,
  dataDate,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  market: string;
  onMarketChange: (m: string) => void;
  indices: MarketIndex[];
  dataDate: string;
}) {
  const [hist, setHist] = useState<IndicesHistJson | null>(null);
  const [error, setError] = useState(false);
  const [range, setRange] = useState<TrendRange>(TREND_RANGE_DEFAULT);
  const [hover, setHover] = useState<TrendPoint | null>(null);

  // 鎖頁面捲動(與 BranchDrillView 同一招;base-ui 的鎖法在 overflow 上看不出來,這裡明寫一次)
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    setError(false);
    loadHist()
      .then((h) => alive && setHist(h))
      .catch(() => alive && setError(true));
    return () => {
      alive = false;
    };
  }, [open]);

  const ordered = orderedIndices(indices);
  const head = ordered.find((i) => i.market === market) ?? ordered[0];
  const series = hist?.series?.[head?.market ?? ""];
  const allPoints = useMemo<TrendPoint[]>(() => {
    if (series?.points?.length) return series.points;
    // 歷史檔還沒到(或抓不到):用 head.json 的 spark 先畫,沒有日期就用序號當 time 會壞掉,所以略過
    return [];
  }, [series]);
  const points = useMemo(() => sliceRange(allPoints, range), [allPoints, range]);
  const stats = useMemo(() => rangeStats(points), [points]);
  const shown = hover ?? (points.length ? points[points.length - 1] : null);
  const shownTone = shown ? ((shown[2] ?? shown[3] ?? 0) > 0 ? "up" : (shown[2] ?? shown[3] ?? 0) < 0 ? "down" : "flat") : "flat";
  const dec = indexDecimals(head?.market);
  // 台指期副標跟著游標:歷史列第 5 個元素是那天的近月月份;結算價只有最新一天有,游標停在過去日就不顯示
  const sub = head?.market === "tx"
    ? txSubtitle({
        contract_month: hover ? (hover[4] ?? null) : (series?.contract_month ?? head.contract_month),
        settlement: hover ? null : head.settlement,
      })
    : null;

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Backdrop className="fixed inset-0 z-50 bg-black/40 duration-150 data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0" />
        <DialogPrimitive.Popup
          data-testid="index-trend-sheet"
          className={cn(
            "fixed inset-x-0 bottom-0 z-50 mx-auto flex max-h-[calc(100dvh-2rem)] w-full max-w-xl flex-col rounded-t-2xl border border-border bg-card text-foreground shadow-[var(--shadow-card)] outline-none",
            "pb-[max(0.75rem,env(safe-area-inset-bottom))] duration-200 data-open:animate-in data-open:slide-in-from-bottom data-closed:animate-out data-closed:slide-out-to-bottom",
          )}
        >
          {/* 拖曳把手(純視覺;關閉用 X / ESC / 點背景 / 下滑手勢不另做) */}
          <div className="mx-auto mt-2 h-1 w-10 shrink-0 rounded-full bg-[color:var(--line)]" aria-hidden />
          <div className="flex items-start gap-2 px-4 pt-2">
            <div className="min-w-0 flex-1">
              <DialogPrimitive.Title className="text-[12px] font-semibold text-muted-foreground">
                {TREND_SHEET_TITLE}
                {head && <span className="num ml-2 text-[11.5px] font-normal">{`${mmdd(shown ? shown[0] : head.date)} 收盤`}</span>}
              </DialogPrimitive.Title>
              <DialogPrimitive.Description className="sr-only">{TREND_HINT}</DialogPrimitive.Description>
            </div>
            <DialogPrimitive.Close
              className="-mr-2 -mt-1 flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
              aria-label="關閉走勢圖"
            >
              <X size={18} strokeWidth={1.8} />
            </DialogPrimitive.Close>
          </div>

          <div className="overflow-y-auto px-4">
            {/* 指數切換 */}
            <div role="tablist" aria-label="指數" className="mt-1 inline-flex gap-0.5 rounded-full border border-border bg-card p-[3px]">
              {ordered.map((ix) => (
                <button
                  key={ix.market}
                  type="button"
                  role="tab"
                  aria-selected={ix.market === head?.market}
                  className={cn(pillTabClass(ix.market === head?.market), "min-h-9")}
                  onClick={() => { onMarketChange(ix.market); setHover(null); }}
                >
                  {ix.name}
                </button>
              ))}
            </div>

            {/* 標頭:名稱、收盤、漲跌(游標停在哪天就顯示那天) */}
            {head && (
              <div className="mt-2.5" data-testid="index-trend-head">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <span className="text-[13px] font-bold">{head.name}</span>
                  {sub && <span className="num text-[11px] text-muted-foreground">{sub}</span>}
                  {dateTag(head.date, dataDate) && !hover && (
                    <span className="num text-[11px] text-warn">{`指數日 ${mmdd(head.date)}`}</span>
                  )}
                </div>
                <div className="mt-0.5 flex flex-wrap items-baseline gap-x-3">
                  <span className={cn("num text-[30px] font-bold leading-none tracking-tight", TONE_CLASS[shownTone])}>
                    {fmtIndex(shown ? shown[1] : head.close, dec)}
                  </span>
                  <span className={cn("num text-[13px] font-semibold", TONE_CLASS[shownTone])}>
                    {shown ? indexChangeText(shown[2], shown[3], dec) : indexChangeText(head.change, head.chg_pct, dec)}
                  </span>
                </div>
              </div>
            )}

            {/* 圖 */}
            <div className="mt-2 min-h-[300px]">
              {error ? (
                <p className="py-16 text-center text-sm text-muted-foreground">{isBrowserOffline() ? OFFLINE_DATA_COPY : TREND_EMPTY}</p>
              ) : !hist ? (
                <div className="h-[300px] w-full animate-pulse rounded-[var(--r-md)] bg-secondary" aria-label="載入中" />
              ) : points.length < 2 ? (
                <p className="py-16 text-center text-sm text-muted-foreground">{TREND_EMPTY}</p>
              ) : (
                <TrendChart points={points} decimals={dec} onHover={setHover} />
              )}
            </div>

            {/* 範圍 */}
            <div role="group" aria-label="範圍" className="mt-2 flex flex-wrap items-center gap-1.5">
              {TREND_RANGES.map((r) => (
                <button
                  key={r.key}
                  type="button"
                  aria-pressed={range === r.key}
                  data-testid={`index-trend-range-${r.key}`}
                  className={cn(filterChipClass(range === r.key), "min-h-9")}
                  onClick={() => { setRange(r.key); setHover(null); }}
                >
                  {r.label}
                </button>
              ))}
              {stats && (
                <span className="num ml-auto text-[10.5px] text-muted-foreground">{`${mmdd(stats.from)} – ${mmdd(stats.to)}`}</span>
              )}
            </div>

            {/* 區間統計 */}
            {stats && (
              <dl className="mt-2.5 grid grid-cols-3 gap-2 rounded-[var(--r-md)] bg-secondary/60 px-3 py-2 text-center" data-testid="index-trend-stats">
                <div>
                  <dt className="text-[10.5px] text-muted-foreground">區間高</dt>
                  <dd className="num text-[13px] font-semibold">{fmtIndex(stats.high, dec)}</dd>
                </div>
                <div>
                  <dt className="text-[10.5px] text-muted-foreground">區間低</dt>
                  <dd className="num text-[13px] font-semibold">{fmtIndex(stats.low, dec)}</dd>
                </div>
                <div title={`區間漲跌 ${indexChangeText(stats.change, stats.chgPct, dec)}`}>
                  <dt className="text-[10.5px] text-muted-foreground">區間漲跌</dt>
                  {/* 只放 %(點數在 title),390px 三格並排才不換行 */}
                  <dd className={cn("num whitespace-nowrap text-[13px] font-semibold", TONE_CLASS[rangeTone(points)])}>
                    {indexChangeText(null, stats.chgPct, dec)}
                  </dd>
                </div>
              </dl>
            )}
            <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
              {TREND_HINT}
              {head?.market === "tx" && ` ${TX_STITCH_NOTE}`}
            </p>
          </div>
        </DialogPrimitive.Popup>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
