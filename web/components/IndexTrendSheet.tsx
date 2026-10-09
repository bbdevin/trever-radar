"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Dialog as DialogPrimitive } from "@base-ui/react/dialog";
import { X } from "lucide-react";
import { dataFetch } from "@/lib/dataFetch";
import { OFFLINE_DATA_COPY, isBrowserOffline } from "@/lib/pwa";
import { cn, filterChipClass, pillTabClass } from "@/lib/utils";
import type { IndicesHistJson, IndicesIntradayJson, MarketIndex } from "@/lib/types";
import {
  INDEX_HIST_URL,
  INDEX_INTRADAY_URL,
  INTRADAY_EMPTY,
  INTRADAY_HINT,
  PREV_CLOSE_LABEL,
  TX_INTRADAY_EMPTY,
  TX_INTRADAY_NOTE,
  changeVsPrev,
  hhmmOf,
  intradayStats,
  intradayTone,
  prevCloseBefore,
  type IntradayPoint,
  TREND_EMPTY,
  TREND_HINT,
  TREND_RANGES,
  TREND_RANGE_DEFAULT,
  TREND_SHEET_TITLE,
  TX_STITCH_NOTE,
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
import { crosshairTimeLabel, tickMarkLabel } from "@/lib/chartTime";
import { chartTimeOf, twWallKey } from "@/lib/resample";

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

// 當日 1 分線(§12.5):選「1日」才抓、一個 session 一次;404/空檔 = 還沒有(null,不重試),其他失敗不快取。
let intradayCache: Promise<IndicesIntradayJson | null> | null = null;
function loadIntraday(): Promise<IndicesIntradayJson | null> {
  if (!intradayCache) {
    intradayCache = dataFetch(INDEX_INTRADAY_URL)
      .then((r) => (r.status === 404 ? null : r.ok ? r.json() : Promise.reject(r.status)))
      .catch((e) => {
        intradayCache = null;
        throw e;
      });
  }
  return intradayCache;
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
        // (與個股 K 線共用 lib/chartTime)
        localization: { timeFormatter: (t: unknown) => crosshairTimeLabel(t) },
        timeScale: {
          borderColor: colors.border, timeVisible: false, fixLeftEdge: true, fixRightEdge: true,
          tickMarkFormatter: (t: unknown, type: number) => tickMarkLabel(t, type),
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
 * 「1日」:當日 1 分線(§12.5)。時間用「台北牆上時間當 UTC」(chartTimeOf(twWallKey(epoch)),
 * 與個股分K同一招),軸與游標一律 HH:MM;虛線 = 前一交易日收盤,價格軸範圍一定含它。
 */
function IntradayChart({ points, prev, decimals, onHover }: {
  points: IntradayPoint[]; prev: number | null; decimals: number; onHover: (p: IntradayPoint | null) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const isDark = useIsDark();
  const onHoverRef = useRef(onHover);
  onHoverRef.current = onHover;

  useEffect(() => {
    if (!ref.current || points.length < 2) return;
    let disposed = false;
    let chart: import("lightweight-charts").IChartApi | undefined;
    const toChart = (p: IntradayPoint) => chartTimeOf(twWallKey(p[0])) as number;
    const byTime = new Map(points.map((p) => [toChart(p), p]));
    const color = TONE_COLOR[intradayTone(points, prev)];
    const host = ref.current;
    import("lightweight-charts").then((lw) => {
      if (disposed || !ref.current) return;
      const { createChart, AreaSeries, ColorType, CrosshairMode, LineStyle } = lw;
      const colors = chartColors(isDark);
      const hhmm = (t: unknown) => tickMarkLabel(t, 3); // 數字 time → 「HH:MM」
      chart = createChart(ref.current, {
        autoSize: true,
        layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: colors.text, fontSize: 12 },
        grid: { vertLines: { color: colors.grid }, horzLines: { color: colors.grid } },
        rightPriceScale: { borderColor: colors.border },
        localization: { timeFormatter: hhmm },
        timeScale: {
          borderColor: colors.border, timeVisible: true, secondsVisible: false, fixLeftEdge: true, fixRightEdge: true,
          tickMarkFormatter: hhmm,
        },
        crosshair: { mode: CrosshairMode.Magnet },
        handleScroll: { vertTouchDrag: false, mouseWheel: false, pressedMouseMove: false, horzTouchDrag: false },
        handleScale: { mouseWheel: false, pinch: false, axisPressedMouseMove: false, axisDoubleClickReset: false },
      });
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
        // 前收虛線一定在畫面內(開低走低時它會在線的上方)
        autoscaleInfoProvider: (orig: () => import("lightweight-charts").AutoscaleInfo | null) => {
          const r = orig();
          if (!r || r.priceRange == null || prev == null) return r;
          return { ...r, priceRange: { minValue: Math.min(r.priceRange.minValue, prev), maxValue: Math.max(r.priceRange.maxValue, prev) } };
        },
      });
      series.setData(points.map((p) => ({ time: toChart(p) as import("lightweight-charts").UTCTimestamp, value: p[1] })));
      if (prev != null) {
        series.createPriceLine({
          price: prev, color: colors.text, lineWidth: 1, lineStyle: LineStyle.Dashed,
          axisLabelVisible: true, title: PREV_CLOSE_LABEL,
        });
      }
      chart.timeScale().fitContent();
      chart.subscribeCrosshairMove((param) => {
        const t = typeof param.time === "number" ? param.time : null;
        onHoverRef.current(t != null ? byTime.get(t) ?? null : null);
      });
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
  }, [points, prev, isDark, decimals]);

  return <div ref={ref} className="h-[300px] w-full" data-testid="index-intraday-chart" />;
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
  // 1日:undefined = 還沒抓/抓取中;null = 沒有檔(404)
  const [intra, setIntra] = useState<IndicesIntradayJson | null | undefined>(undefined);
  const [intraError, setIntraError] = useState(false);
  const [iHover, setIHover] = useState<IntradayPoint | null>(null);
  const isDay = range === "1d";

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

  // 當日 1 分線只在選了「1日」才抓(預設 3月 不抓)
  useEffect(() => {
    if (!open || !isDay) return;
    let alive = true;
    setIntraError(false);
    loadIntraday()
      .then((j) => alive && setIntra(j))
      .catch(() => alive && setIntraError(true));
    return () => {
      alive = false;
    };
  }, [open, isDay]);

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

  // ── 1日 ──
  const dayPoints = useMemo<IntradayPoint[]>(
    () => (intra?.series?.[(head?.market ?? "") as "twse" | "tpex" | "tx"] ?? []),
    [intra, head?.market],
  );
  const dayPrev = intra ? prevCloseBefore(series?.points, intra.date) : null;
  const dayStats = useMemo(() => intradayStats(dayPoints, dayPrev), [dayPoints, dayPrev]);
  const dayShown = iHover ?? (dayPoints.length ? dayPoints[dayPoints.length - 1] : null);
  const dayChg = dayShown ? changeVsPrev(dayShown[1], dayPrev) : { change: null, chgPct: null };
  const dayTone = (dayChg.change ?? 0) > 0 ? "up" : (dayChg.change ?? 0) < 0 ? "down" : "flat";
  const dayReady = isDay && intra && dayPoints.length >= 2;
  const dayEmpty = head?.market === "tx" && intra ? TX_INTRADAY_EMPTY : INTRADAY_EMPTY;

  // 標頭:1日且有資料時顯示那一分鐘;其餘(含 1日 尚無資料)照日收盤
  const headTime = dayReady && dayShown
    ? `${mmdd(intra!.date)} ${hhmmOf(dayShown[0])}`
    : `${mmdd(shown ? shown[0] : head?.date)} 收盤`;
  const headValue = dayReady && dayShown ? dayShown[1] : shown ? shown[1] : head?.close ?? 0;
  const headChange = dayReady
    ? indexChangeText(dayChg.change, dayChg.chgPct, dec)
    : shown ? indexChangeText(shown[2], shown[3], dec) : indexChangeText(head?.change ?? null, head?.chg_pct ?? null, dec);
  const headTone = dayReady ? dayTone : shownTone;
  const daySub = head?.market === "tx" && isDay
    ? txSubtitle({ contract_month: series?.contract_month ?? head.contract_month, settlement: null })
    : null;

  const statsView = isDay
    ? dayReady && dayStats
      ? { labels: ["日高", "日低", "日漲跌"], high: dayStats.high, low: dayStats.low, change: dayStats.change,
          chgPct: dayStats.chgPct, tone: intradayTone(dayPoints, dayPrev), from: dayStats.from, to: dayStats.to }
      : null
    : stats
      ? { labels: ["區間高", "區間低", "區間漲跌"], high: stats.high, low: stats.low, change: stats.change as number | null,
          chgPct: stats.chgPct, tone: rangeTone(points), from: mmdd(stats.from), to: mmdd(stats.to) }
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
                {head && <span className="num ml-2 text-[11.5px] font-normal" data-testid="index-trend-time">{headTime}</span>}
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
                  onClick={() => { onMarketChange(ix.market); setHover(null); setIHover(null); }}
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
                  {(isDay ? daySub : sub) && <span className="num text-[11px] text-muted-foreground">{isDay ? daySub : sub}</span>}
                  {!isDay && dateTag(head.date, dataDate) && !hover && (
                    <span className="num text-[11px] text-warn">{`指數日 ${mmdd(head.date)}`}</span>
                  )}
                  {dayReady && dateTag(intra!.date, dataDate) && (
                    <span className="num text-[11px] text-warn">{`日內 ${mmdd(intra!.date)}`}</span>
                  )}
                </div>
                <div className="mt-0.5 flex flex-wrap items-baseline gap-x-3">
                  <span className={cn("num text-[30px] font-bold leading-none tracking-tight", TONE_CLASS[headTone])}>
                    {fmtIndex(headValue, dec)}
                  </span>
                  <span className={cn("num text-[13px] font-semibold", TONE_CLASS[headTone])}>{headChange}</span>
                </div>
              </div>
            )}

            {/* 圖 */}
            <div className="mt-2 min-h-[300px]">
              {isDay ? (
                intraError ? (
                  <p className="py-16 text-center text-sm text-muted-foreground">{isBrowserOffline() ? OFFLINE_DATA_COPY : INTRADAY_EMPTY}</p>
                ) : intra === undefined ? (
                  <div className="h-[300px] w-full animate-pulse rounded-[var(--r-md)] bg-secondary" aria-label="載入中" />
                ) : !dayReady ? (
                  <p className="py-16 text-center text-sm text-muted-foreground" data-testid="index-intraday-empty">{dayEmpty}</p>
                ) : (
                  <IntradayChart points={dayPoints} prev={dayPrev} decimals={dec} onHover={setIHover} />
                )
              ) : error ? (
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
                  onClick={() => { setRange(r.key); setHover(null); setIHover(null); }}
                >
                  {r.label}
                </button>
              ))}
              {statsView && (
                <span className="num ml-auto text-[10.5px] text-muted-foreground">{`${statsView.from} – ${statsView.to}`}</span>
              )}
            </div>

            {/* 區間統計(1日:日高/日低/日漲跌,漲跌相對前一交易日收盤) */}
            {statsView && (
              <dl className="mt-2.5 grid grid-cols-3 gap-2 rounded-[var(--r-md)] bg-secondary/60 px-3 py-2 text-center" data-testid="index-trend-stats">
                <div>
                  <dt className="text-[10.5px] text-muted-foreground">{statsView.labels[0]}</dt>
                  <dd className="num text-[13px] font-semibold">{fmtIndex(statsView.high, dec)}</dd>
                </div>
                <div>
                  <dt className="text-[10.5px] text-muted-foreground">{statsView.labels[1]}</dt>
                  <dd className="num text-[13px] font-semibold">{fmtIndex(statsView.low, dec)}</dd>
                </div>
                <div title={`${statsView.labels[2]} ${indexChangeText(statsView.change, statsView.chgPct, dec)}`}>
                  <dt className="text-[10.5px] text-muted-foreground">{statsView.labels[2]}</dt>
                  {/* 只放 %(點數在 title),390px 三格並排才不換行 */}
                  <dd className={cn("num whitespace-nowrap text-[13px] font-semibold", TONE_CLASS[statsView.tone])}>
                    {indexChangeText(null, statsView.chgPct, dec)}
                  </dd>
                </div>
              </dl>
            )}
            <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
              {isDay ? INTRADAY_HINT : TREND_HINT}
              {head?.market === "tx" && ` ${isDay ? TX_INTRADAY_NOTE : TX_STITCH_NOTE}`}
            </p>
          </div>
        </DialogPrimitive.Popup>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
