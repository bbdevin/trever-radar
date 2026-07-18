"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Candle } from "@/lib/types";
import { fmtLots } from "@/lib/format";
import { bollinger, kd, macd, rsi, sma } from "@/lib/indicators";
import { barsForDays, periodKey, resample, type Timeframe } from "@/lib/resample";
import { cn } from "@/lib/utils";

const TF_DEFS: { key: Timeframe; label: string }[] = [
  { key: "D", label: "日K" },
  { key: "W", label: "週K" },
  { key: "M", label: "月K" },
];

const MA_DEFS = [
  { key: "ma5", n: 5, label: "5日", color: "#3987e5" },
  { key: "ma10", n: 10, label: "10日", color: "#c98500" },
  { key: "ma20", n: 20, label: "20日", color: "#9085e9" },
  { key: "ma60", n: 60, label: "季線", color: "#199e70" },
  { key: "ma120", n: 120, label: "半年線", color: "#d55181" },
  { key: "ma240", n: 240, label: "年線", color: "#d95926" },
] as const;
type MaKey = (typeof MA_DEFS)[number]["key"];
type SubKey = "macd" | "kd" | "rsi";
/** 手機版子 pane 切換 key(< 768px)：sub=副圖、main=主力買賣超、sel=分點進出 */
type MobilePaneKey = "sub" | "main" | "sel";
const LS_MOBILE_PANE = "trever.chart.mobilepane.v1";

interface Settings {
  ma: Record<MaKey, boolean>;
  boll: boolean;
  sub: SubKey;
  tf: Timeframe;
  mainForce: boolean;
}
const DEFAULT_SETTINGS: Settings = {
  ma: { ma5: true, ma10: true, ma20: true, ma60: true, ma120: true, ma240: true },
  boll: true,
  sub: "macd",
  tf: "D",
  mainForce: true,
};
const LS_KEY = "trever.chart.settings.v1";

function loadSettings(): Settings {
  if (typeof window === "undefined") return DEFAULT_SETTINGS;
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    const p = JSON.parse(raw);
    return { ...DEFAULT_SETTINGS, ...p, ma: { ...DEFAULT_SETTINGS.ma, ...(p.ma ?? {}) } };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

const UP = "#e66767";
const DOWN = "#0ca30c";
const CUM_COLOR = "#c98500"; // 累計買賣超線:非紅綠(避免與漲跌柱混淆)
const MF_TITLE = "主力買賣超(前15大)";
const SEL_TITLE = "分點進出(勾選分點)";

/** chart 的格線/軸/水印色隨主題切換。dark = 遷移前寫死值逐字不變;light = 柔和淺色組(對白 grid≥1.25、文字≥5:1)。
 *  K 棒紅綠、均線、成交量、布林、副圖線色不隨主題變(白底上皆可讀)。 */
function chartColors(isDark: boolean) {
  return isDark
    ? { text: "#898781", separator: "#2c2c2a", grid: "#222220", border: "#383835", paneText: "#898781" }
    : { text: "#6b6a64", separator: "#e6e5e0", grid: "#e6e5e0", border: "#d8d7d2", paneText: "#6b6a64" };
}

/** 每日分點淨買賣序列(t 同 candles 的 YYYY-MM-DD) */
export interface NetPoint {
  t: string;
  net: number;
}

/** 依 tf 把日淨買賣序列聚成 K 棒桶(net 加總、t 對齊該桶 K 棒),並算自序列起點的累計 */
function resampleNet(points: NetPoint[], bars: Candle[], tf: Timeframe) {
  if (!points.length) return undefined;
  const barByKey = new Map(bars.map((b) => [periodKey(b.t, tf), b.t]));
  const agg = new Map<string, number>();
  for (const p of points) {
    const bt = barByKey.get(periodKey(p.t, tf));
    if (bt == null) continue;
    agg.set(bt, (agg.get(bt) ?? 0) + p.net);
  }
  let cum = 0;
  const out: { t: string; net: number; cum: number }[] = [];
  for (const b of bars) {
    const net = agg.get(b.t);
    if (net == null) continue; // 缺資料日留白,不補 0
    cum += net;
    out.push({ t: b.t, net, cum });
  }
  return out.length ? out : undefined;
}

/** 日 K + 均線/布林(可勾選)+ 成交量 + 副圖 MACD/KD/RSI + 主力買賣超/分點進出 pane。偏好記在 localStorage。 */
export default function KChart({
  candles,
  visibleDays,
  mainForce,
  branchFlow,
}: {
  candles: Candle[];
  visibleDays: number;
  /** 每日全部分點 net 加總(branch_history 裁剪版);缺省時不渲染主力買賣超 pane */
  mainForce?: NetPoint[];
  /** 已勾選分點集合的每日 net 加總;缺省時不渲染分點進出 pane */
  branchFlow?: NetPoint[];
}) {
  const ref = useRef<HTMLDivElement>(null);
  const legendRef = useRef<HTMLDivElement>(null);
  const mobileLegendRef = useRef<HTMLDivElement>(null);
  const [settings, setSettings] = useState<Settings>(loadSettings);
  // 手機版子 pane 切換(< 768px)；桌機版全部 pane 同時顯示
  const [mobilePaneKey, setMobilePaneKey] = useState<MobilePaneKey>(() => {
    if (typeof window === "undefined") return "sub";
    return (localStorage.getItem(LS_MOBILE_PANE) as MobilePaneKey | null) ?? "sub";
  });
  // 手機版偵測(<768px)。KChart 僅在資料載入後於 client 渲染(SSR 期間顯示骨架屏),
  // 故初始化直接讀 matchMedia,無 hydration mismatch;跨斷點時觸發 chart 重建(effect 依賴 isMobile)。
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== "undefined" && !window.matchMedia("(min-width:768px)").matches,
  );
  useEffect(() => {
    if (typeof window === "undefined") return;
    const mq = window.matchMedia("(min-width:768px)");
    const on = () => setIsMobile(!mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);

  // 主題偵測:讀 <html class="dark"> + MutationObserver 監聽切換 → 不重建 chart,改 applyOptions 更新色
  const [isDark, setIsDark] = useState(
    () => typeof document !== "undefined" && document.documentElement.classList.contains("dark"),
  );
  const isDarkRef = useRef(isDark);
  isDarkRef.current = isDark;
  const paneTextRef = useRef(chartColors(isDark).paneText);
  paneTextRef.current = chartColors(isDark).paneText;
  // 現存 chart 與 pane 水印標題(供主題切換時就地 applyOptions,不重建避免閃爍)
  const chartRef = useRef<import("lightweight-charts").IChartApi | undefined>(undefined);
  const titlesRef = useRef<{ wm: { applyOptions: (o: unknown) => void }; base: string }[]>([]);

  useEffect(() => {
    if (typeof document === "undefined") return;
    const el = document.documentElement;
    const obs = new MutationObserver(() => setIsDark(el.classList.contains("dark")));
    obs.observe(el, { attributes: true, attributeFilter: ["class"] });
    return () => obs.disconnect();
  }, []);

  useEffect(() => {
    if (typeof window !== "undefined") localStorage.setItem(LS_KEY, JSON.stringify(settings));
  }, [settings]);

  // 依週期重取樣(日K→週/月K),指標對重取樣後序列計算 → 週K的MA20=20週線(主流慣例)
  const bars = useMemo(() => resample(candles, settings.tf), [candles, settings.tf]);

  // 分點淨買賣序列跟著 tf 重取樣(net 按週/月加總,累計線自序列起點照舊)
  const flow = useMemo(
    () => ({
      main: mainForce ? resampleNet(mainForce, bars, settings.tf) : undefined,
      sel: branchFlow ? resampleNet(branchFlow, bars, settings.tf) : undefined,
    }),
    [mainForce, branchFlow, bars, settings.tf],
  );

  // 指標一律以「全歷史」計算,再切可視區間 → 區間邊緣的均線/布林不失真
  const calc = useMemo(() => {
    const closes = bars.map((c) => c.c as number | null);
    const highs = bars.map((c) => c.h as number | null);
    const lows = bars.map((c) => c.l as number | null);
    return {
      ma: Object.fromEntries(MA_DEFS.map((m) => [m.key, sma(closes, m.n)])) as Record<MaKey, (number | null)[]>,
      boll: bollinger(closes, 20, 2),
      macd: macd(closes),
      rsi: rsi(closes, 14),
      kd: kd(highs, lows, closes, 9),
    };
  }, [bars]);

  useEffect(() => {
    if (!ref.current || bars.length === 0) return;
    let disposed = false;
    let chart: import("lightweight-charts").IChartApi | undefined;
    const visibleBars = barsForDays(visibleDays, settings.tf);
    const start = Math.max(0, bars.length - visibleBars);
    const idx = (arr: (number | null)[]) =>
      arr.slice(start).map((v, i) => ({ time: bars[start + i].t, value: v }))
        .filter((p): p is { time: string; value: number } => p.value != null);

    import("lightweight-charts").then((lw) => {
      if (disposed || !ref.current) return;
      const { createChart, createTextWatermark, CandlestickSeries, HistogramSeries, LineSeries, ColorType, LineStyle } = lw;
      const colors = chartColors(isDarkRef.current);
      const mobile = isMobile;
      // 手機版子 pane 擇一:main/sel 需有資料,否則退回副圖(sub)。桌機版此值不使用。
      const effPane: MobilePaneKey =
        mobilePaneKey === "main" && flow.main?.length ? "main"
        : mobilePaneKey === "sel" && flow.sel?.length ? "sel"
        : "sub";
      chart = createChart(ref.current, {
        autoSize: true,
        layout: {
          background: { type: ColorType.Solid, color: "transparent" },
          textColor: colors.text,
          fontSize: 11,
          // 桌機開啟 pane 分隔線可拖曳(v5 內建),讓使用者微調子 pane 高度;手機關閉,垂直拖曳留給頁面捲動
          panes: { separatorColor: colors.separator, enableResize: !mobile },
        },
        grid: { vertLines: { color: colors.grid }, horzLines: { color: colors.grid } },
        rightPriceScale: { borderColor: colors.border },
        timeScale: { borderColor: colors.border },
        crosshair: { mode: 0 },
        // 手機版：垂直拖曳還給頁面捲動；水平 pan/縮放維持
        handleScroll: { vertTouchDrag: !mobile },
      });
      chartRef.current = chart;
      const view = bars.slice(start);

      const candleSeries = chart.addSeries(CandlestickSeries, {
        upColor: UP, borderUpColor: UP, wickUpColor: UP,
        downColor: DOWN, borderDownColor: DOWN, wickDownColor: DOWN,
      }, 0);
      candleSeries.setData(view.map((c) => ({ time: c.t, open: c.o, high: c.h, low: c.l, close: c.c })));

      const thin = { lineWidth: 1 as const, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false };
      for (const m of MA_DEFS) {
        if (!settings.ma[m.key]) continue;
        chart.addSeries(LineSeries, { color: m.color, ...thin }, 0).setData(idx(calc.ma[m.key]));
      }
      if (settings.boll) {
        const bopt = { color: "rgba(137,135,129,0.6)", ...thin };
        chart.addSeries(LineSeries, bopt, 0).setData(idx(calc.boll.upper));
        chart.addSeries(LineSeries, bopt, 0).setData(idx(calc.boll.lower));
        chart.addSeries(LineSeries, { ...bopt, lineStyle: LineStyle.Dotted }, 0).setData(idx(calc.boll.mid));
      }

      const volSeries = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false }, 1);
      volSeries.setData(view.map((c, i) => ({
        time: c.t,
        value: c.v,
        color: i > 0 && c.c >= view[i - 1].c ? "rgba(230,103,103,0.45)" : "rgba(12,163,12,0.45)",
      })));

      // 副圖(MACD/KD/RSI)加到指定 pane
      const addSub = (pane: number) => {
        if (settings.sub === "macd") {
          chart!.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, pane)
            .setData(idx(calc.macd.hist).map((p) => ({ ...p, color: p.value >= 0 ? "rgba(230,103,103,0.7)" : "rgba(12,163,12,0.7)" })));
          chart!.addSeries(LineSeries, { color: "#3987e5", ...thin }, pane).setData(idx(calc.macd.dif));
          chart!.addSeries(LineSeries, { color: "#c98500", ...thin }, pane).setData(idx(calc.macd.dea));
        } else if (settings.sub === "kd") {
          chart!.addSeries(LineSeries, { color: "#3987e5", ...thin }, pane).setData(idx(calc.kd.k));
          chart!.addSeries(LineSeries, { color: "#d55181", ...thin }, pane).setData(idx(calc.kd.d));
        } else {
          chart!.addSeries(LineSeries, { color: "#3987e5", ...thin }, pane).setData(idx(calc.rsi));
        }
      };

      const firstT = view[0].t;
      const addFlowPane = (pts: { t: string; net: number; cum: number }[], pane: number) => {
        const vis = pts.filter((p) => p.t >= firstT);
        chart!
          .addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false }, pane)
          .setData(vis.map((p) => ({ time: p.t, value: p.net, color: p.net >= 0 ? "rgba(230,103,103,0.7)" : "rgba(12,163,12,0.7)" })));
        // 累計線走獨立 overlay 價格軸,避免累計量把每日柱壓扁
        chart!
          .addSeries(LineSeries, { color: CUM_COLOR, priceScaleId: `cum-${pane}`, priceFormat: { type: "volume" }, ...thin }, pane)
          .setData(vis.map((p) => ({ time: p.t, value: p.cum })));
      };

      // pane 標題:v5 pane watermark(游標移動時同一位置追加當日/累計數字)。色讀 paneTextRef → 主題切換即時反映
      const wmLine = (text: string) => ({ text, color: paneTextRef.current, fontSize: 12 });
      const mkTitle = (pane: number, text: string) =>
        createTextWatermark(chart!.panes()[pane], { horzAlign: "left", vertAlign: "top", lines: [wmLine(text)] });

      // mfTitle/selTitle 供桌機游標更新 watermark 數值;手機不用 watermark 值,改上方 compact legend。
      let mfTitle: ReturnType<typeof mkTitle> | null = null;
      let selTitle: ReturnType<typeof mkTitle> | null = null;
      const panes = chart.panes() as unknown as { setStretchFactor?: (f: number) => void }[];

      if (mobile) {
        // 子 pane 擇一放在 pane 2:副圖 / 主力買賣超 / 分點進出
        if (effPane === "main") addFlowPane(flow.main!, 2);
        else if (effPane === "sel") addFlowPane(flow.sel!, 2);
        else addSub(2);
        titlesRef.current = []; // 手機不建 pane 內 watermark(避免小 pane 壓資料),數值走上方 compact legend
        // 主圖佔比加大;子 pane 於總高 clamp(360,52vh,480) 下仍 ≥120px
        panes[0]?.setStretchFactor?.(13);
        panes[1]?.setStretchFactor?.(4);
        panes[2]?.setStretchFactor?.(11);
      } else {
        // 桌機:副圖常駐 pane 2,主力/分點依序接 pane 3/4(逐位元不變)
        addSub(2);
        const showMain = settings.mainForce && !!flow.main?.length;
        const showSel = !!flow.sel?.length;
        let nextPane = 3;
        const mainPane = showMain ? nextPane++ : -1;
        const selPane = showSel ? nextPane++ : -1;
        if (showMain) addFlowPane(flow.main!, mainPane);
        if (showSel) addFlowPane(flow.sel!, selPane);
        mfTitle = showMain ? mkTitle(mainPane, MF_TITLE) : null;
        selTitle = showSel ? mkTitle(selPane, SEL_TITLE) : null;
        titlesRef.current = [
          ...(mfTitle ? [{ wm: mfTitle as { applyOptions: (o: unknown) => void }, base: MF_TITLE }] : []),
          ...(selTitle ? [{ wm: selTitle as { applyOptions: (o: unknown) => void }, base: SEL_TITLE }] : []),
        ];
        // 固定像素預算(2026-07-19 使用者定案):factor 直接用目標 px,
        // 容器總高 = 各 pane 目標 px 加總(見 desktopHeight),故每 pane 實得 ≈ 目標值,
        // 不再隨視窗高低被壓縮——副圖保證 ~180px
        panes[0]?.setStretchFactor?.(380);
        panes[1]?.setStretchFactor?.(100);
        panes[2]?.setStretchFactor?.(180);
        if (mainPane >= 0) panes[mainPane]?.setStretchFactor?.(180);
        if (selPane >= 0) panes[selPane]?.setStretchFactor?.(180);
      }

      // 手機 compact legend 初始文字(pane 名);游標移動時附加買賣超/累計數值
      if (mobile && mobileLegendRef.current) {
        mobileLegendRef.current.textContent =
          effPane === "main" ? MF_TITLE : effPane === "sel" ? SEL_TITLE : `副圖 · ${settings.sub.toUpperCase()}`;
      }

      // legend:十字游標顯示 OHLC 與均線值;主力/分點數值直接更新在對應 pane 標題(帶正負號)
      const byTime = new Map(bars.map((c, i) => [c.t, i]));
      const mainByTime = new Map((flow.main ?? []).map((p) => [p.t, p]));
      const selByTime = new Map((flow.sel ?? []).map((p) => [p.t, p]));
      const updTitle = (
        wm: typeof mfTitle,
        byT: Map<string, { net: number; cum: number }>,
        title: string,
        t: string | undefined,
      ) => {
        const p = t != null ? byT.get(t) : undefined;
        wm?.applyOptions({ lines: [wmLine(p ? `${title} 買賣超 ${fmtLots(p.net)}張/累計 ${fmtLots(p.cum)}張` : title)] });
      };
      chart.subscribeCrosshairMove((param) => {
        const t = param.time as string | undefined;
        const i = t ? byTime.get(t) : undefined;
        if (mobile) {
          // 手機:主力/分點 pane 的當日/累計數值更新在上方 compact legend(pane 名 + 買賣超 ±N/累計 ±M)
          const ml = mobileLegendRef.current;
          if (ml && (effPane === "main" || effPane === "sel")) {
            const byT = effPane === "main" ? mainByTime : selByTime;
            const title = effPane === "main" ? MF_TITLE : SEL_TITLE;
            const p = t ? byT.get(t) : undefined;
            ml.textContent = p ? `${title} 買賣超 ${fmtLots(p.net)}張 · 累計 ${fmtLots(p.cum)}張` : title;
          }
        } else {
          updTitle(mfTitle, mainByTime, MF_TITLE, t);
          updTitle(selTitle, selByTime, SEL_TITLE, t);
        }
        const el = legendRef.current;
        if (!el) return;
        if (i == null) {
          el.textContent = "";
          return;
        }
        const c = bars[i];
        const prev = i > 0 ? bars[i - 1].c : null;
        const chg = prev ? (((c.c - prev) / prev) * 100).toFixed(2) : "—";
        const mas = MA_DEFS.filter((m) => settings.ma[m.key])
          .map((m) => {
            const v = calc.ma[m.key][i];
            return v == null ? "" : `<span style="color:${m.color}">${m.label} ${v.toFixed(2)}</span>`;
          })
          .filter(Boolean)
          .join(" ");
        el.innerHTML =
          `<b>${c.t}</b> 開${c.o} 高${c.h} 低${c.l} 收<b>${c.c}</b> ` +
          `<span class="${prev != null && c.c >= prev ? "up" : "down"}">${chg}%</span> ` +
          `量${c.v.toLocaleString()}張 ${mas}`;
      });
      chart.timeScale().fitContent();
    });

    return () => {
      disposed = true;
      chart?.remove();
      chartRef.current = undefined;
      titlesRef.current = [];
    };
  }, [bars, calc, flow, settings, visibleDays, mobilePaneKey, isMobile]);

  // 主題切換:就地更新既有 chart 的 grid/軸/水印色(不重建 → 不閃爍)。chart 建立時已用當下主題色,故此處僅處理「建立後」的切換。
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const c = chartColors(isDark);
    chart.applyOptions({
      layout: { textColor: c.text, panes: { separatorColor: c.separator } },
      grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
      rightPriceScale: { borderColor: c.border },
      timeScale: { borderColor: c.border },
    });
    // 水印色不能由 applyOptions 單獨改,重貼各 pane 基礎標題(帶新色);游標懸停時的動態數值由 wmLine 讀 paneTextRef 已即時跟色
    for (const t of titlesRef.current) t.wm.applyOptions({ lines: [{ text: t.base, color: c.paneText, fontSize: 12 }] });
  }, [isDark]);

  // 額外 pane 數決定桌機圖表總高:主圖不被壓縮,pane 多時整體加高(手機恆為單一子 pane,用固定 clamp)
  const extraPanes = (settings.mainForce && flow.main?.length ? 1 : 0) + (flow.sel?.length ? 1 : 0);
  // 桌機改固定像素預算(2026-07-19 使用者定案:vh 綁視窗會把副圖壓扁):
  // K 線 380 + 量能 100 + 每個副圖 180 + 時間軸/邊框 ~46,總高隨 pane 數增加,頁面捲動吸收
  const desktopHeight = 380 + 100 + 180 * (1 + extraPanes) + 46;

  const chipBase =
    "inline-flex items-center gap-1 rounded-full border border-[color:var(--line)] bg-card px-2.5 py-[3px] text-xs font-semibold text-muted-foreground cursor-pointer select-none [&_input]:hidden before:content-none has-checked:before:content-['✓_'] has-checked:before:text-[10px] aria-pressed:before:content-['✓_'] aria-pressed:before:text-[10px]";

  // 手機版 mobilePaneKey 持久化
  const handleMobilePaneChange = (key: MobilePaneKey) => {
    setMobilePaneKey(key);
    if (typeof window !== "undefined") localStorage.setItem(LS_MOBILE_PANE, key);
  };

  return (
    <div id="stock-kchart">
      {/* 工具列:桌機維持換行(逐位元不變);手機(max-md)單行橫滑不換行、各 chip min-h-11 觸控 */}
      <div className="flex flex-wrap items-center gap-1.5 px-0.5 py-2 max-md:flex-nowrap max-md:overflow-x-auto max-md:scrollbar-hide max-md:[&>*]:shrink-0 max-md:[&_label]:min-h-11 max-md:[&_button]:min-h-11">
        <span className="inline-flex gap-0.5 rounded-lg border border-border bg-card p-0.5">
          {TF_DEFS.map((t) => (
            <button
              key={t.key}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs font-semibold text-muted-foreground",
                settings.tf === t.key && "bg-muted text-foreground shadow-[inset_0_0_0_1px_var(--border-strong)]",
              )}
              onClick={() => setSettings((s) => ({ ...s, tf: t.key }))}
            >
              {t.label}
            </button>
          ))}
        </span>
        <span className="mx-1 h-[18px] w-px bg-[color:var(--line)]" />
        {MA_DEFS.map((m) => (
          <label
            key={m.key}
            className={chipBase}
            style={settings.ma[m.key] ? { color: m.color, borderColor: m.color } : undefined}
          >
            <input
              type="checkbox"
              checked={settings.ma[m.key]}
              onChange={(e) =>
                setSettings((s) => ({ ...s, ma: { ...s.ma, [m.key]: e.target.checked } }))
              }
            />
            {m.label}
          </label>
        ))}
        <label className={chipBase} style={settings.boll ? { color: "#898781", borderColor: "#898781" } : undefined}>
          <input
            type="checkbox"
            checked={settings.boll}
            onChange={(e) => setSettings((s) => ({ ...s, boll: e.target.checked }))}
          />
          布林
        </label>
        <span className="mx-1 h-[18px] w-px bg-[color:var(--line)]" />
        {/* 副圖(MACD/KD/RSI):選 indicator;手機同時把子 pane 切回「副圖」→ 三選一的返回路徑 */}
        {(["macd", "kd", "rsi"] as SubKey[]).map((k) => (
          <button
            key={k}
            className={cn(
              "rounded-lg",
              chipBase,
              settings.sub === k && (!isMobile || mobilePaneKey === "sub") && "border-[color:var(--border-strong)] bg-muted text-foreground",
            )}
            onClick={() => {
              setSettings((s) => ({ ...s, sub: k }));
              if (isMobile) handleMobilePaneChange("sub");
            }}
          >
            {k.toUpperCase()}
          </button>
        ))}
        {/* 手機版子 pane 三選一的另兩個選項:主力 / 分點(分點無勾選時 disabled)*/}
        {isMobile && !!mainForce?.length && (
          <>
            <span className="mx-1 h-[18px] w-px bg-[color:var(--line)]" />
            <button
              className={cn(
                "rounded-lg",
                chipBase,
                mobilePaneKey === "main" && "border-[color:var(--border-strong)] bg-muted text-foreground",
              )}
              onClick={() => handleMobilePaneChange("main")}
            >
              主力
            </button>
          </>
        )}
        {isMobile && (
          <button
            disabled={!branchFlow?.length}
            aria-disabled={!branchFlow?.length}
            className={cn(
              "rounded-lg",
              chipBase,
              !branchFlow?.length && "cursor-not-allowed opacity-40",
              mobilePaneKey === "sel" && !!branchFlow?.length && "border-[color:var(--border-strong)] bg-muted text-foreground",
            )}
            onClick={() => branchFlow?.length && handleMobilePaneChange("sel")}
          >
            分點
          </button>
        )}
        {/* 桌機版:主力買賣超 checkbox(手機版由上方子 pane 切換控制)*/}
        {!isMobile && !!mainForce?.length && (
          <label className={chipBase} style={settings.mainForce ? { color: CUM_COLOR, borderColor: CUM_COLOR } : undefined}>
            <input
              type="checkbox"
              checked={settings.mainForce}
              onChange={(e) => setSettings((s) => ({ ...s, mainForce: e.target.checked }))}
            />
            主力買賣超
          </label>
        )}
      </div>
      {/* 手機版:游標數值改此處一行 compact legend(pane 名 + 買賣超 ±N/累計 ±M);桌機用 pane 內 watermark */}
      {isMobile && (
        <div
          ref={mobileLegendRef}
          className="num truncate px-0.5 pb-1 text-[11px] leading-tight text-[color:var(--ink-2)]"
        />
      )}
      <div className="relative">
        <div
          ref={legendRef}
          className="num pointer-events-none absolute top-1.5 left-2.5 z-[5] max-w-[92%] text-[11.5px] leading-[1.5] text-[color:var(--ink-2)] [text-shadow:0_1px_2px_rgba(0,0,0,0.7)]"
        />
        <div
          ref={ref}
          className={cn(
            "w-full rounded-t-none rounded-b-[var(--r-lg)] border border-border bg-card p-2 shadow-[var(--shadow-card)]",
            // 手機版(<768px):單一子 pane,固定總高 clamp(360,52vh,480)
            isMobile && "[height:clamp(360px,52vh,480px)]",
          )}
          // 桌機:固定像素總高(K380+量100+副圖180×N+軸46),副圖不再隨視窗被壓縮
          style={!isMobile ? { height: desktopHeight } : undefined}
        />
      </div>
    </div>
  );
}
