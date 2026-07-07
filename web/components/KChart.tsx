"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Candle } from "@/lib/types";
import { bollinger, kd, macd, rsi, sma } from "@/lib/indicators";

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

interface Settings {
  ma: Record<MaKey, boolean>;
  boll: boolean;
  sub: SubKey;
}
const DEFAULT_SETTINGS: Settings = {
  ma: { ma5: true, ma10: true, ma20: true, ma60: true, ma120: true, ma240: true },
  boll: true,
  sub: "macd",
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

/** 日 K + 均線/布林(可勾選)+ 成交量 + 副圖 MACD/KD/RSI。偏好記在 localStorage。 */
export default function KChart({ candles, visibleDays }: { candles: Candle[]; visibleDays: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const legendRef = useRef<HTMLDivElement>(null);
  const [settings, setSettings] = useState<Settings>(loadSettings);

  useEffect(() => {
    if (typeof window !== "undefined") localStorage.setItem(LS_KEY, JSON.stringify(settings));
  }, [settings]);

  // 指標一律以「全歷史」計算,再切可視區間 → 區間邊緣的均線/布林不失真
  const calc = useMemo(() => {
    const closes = candles.map((c) => c.c as number | null);
    const highs = candles.map((c) => c.h as number | null);
    const lows = candles.map((c) => c.l as number | null);
    return {
      ma: Object.fromEntries(MA_DEFS.map((m) => [m.key, sma(closes, m.n)])) as Record<MaKey, (number | null)[]>,
      boll: bollinger(closes, 20, 2),
      macd: macd(closes),
      rsi: rsi(closes, 14),
      kd: kd(highs, lows, closes, 9),
    };
  }, [candles]);

  useEffect(() => {
    if (!ref.current || candles.length === 0) return;
    let disposed = false;
    let chart: import("lightweight-charts").IChartApi | undefined;
    const start = Math.max(0, candles.length - visibleDays);
    const idx = (arr: (number | null)[]) =>
      arr.slice(start).map((v, i) => ({ time: candles[start + i].t, value: v }))
        .filter((p): p is { time: string; value: number } => p.value != null);

    import("lightweight-charts").then((lw) => {
      if (disposed || !ref.current) return;
      const { createChart, CandlestickSeries, HistogramSeries, LineSeries, ColorType, LineStyle } = lw;
      chart = createChart(ref.current, {
        autoSize: true,
        layout: {
          background: { type: ColorType.Solid, color: "transparent" },
          textColor: "#898781",
          fontSize: 11,
          panes: { separatorColor: "#2c2c2a", enableResize: false },
        },
        grid: { vertLines: { color: "#222220" }, horzLines: { color: "#222220" } },
        rightPriceScale: { borderColor: "#383835" },
        timeScale: { borderColor: "#383835" },
        crosshair: { mode: 0 },
      });
      const view = candles.slice(start);

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

      if (settings.sub === "macd") {
        chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, 2)
          .setData(idx(calc.macd.hist).map((p) => ({ ...p, color: p.value >= 0 ? "rgba(230,103,103,0.7)" : "rgba(12,163,12,0.7)" })));
        chart.addSeries(LineSeries, { color: "#3987e5", ...thin }, 2).setData(idx(calc.macd.dif));
        chart.addSeries(LineSeries, { color: "#c98500", ...thin }, 2).setData(idx(calc.macd.dea));
      } else if (settings.sub === "kd") {
        chart.addSeries(LineSeries, { color: "#3987e5", ...thin }, 2).setData(idx(calc.kd.k));
        chart.addSeries(LineSeries, { color: "#d55181", ...thin }, 2).setData(idx(calc.kd.d));
      } else {
        chart.addSeries(LineSeries, { color: "#3987e5", ...thin }, 2).setData(idx(calc.rsi));
      }

      const panes = chart.panes() as unknown as { setStretchFactor?: (f: number) => void }[];
      panes[0]?.setStretchFactor?.(30);
      panes[1]?.setStretchFactor?.(8);
      panes[2]?.setStretchFactor?.(12);

      // legend:十字游標顯示 OHLC 與均線值
      const byTime = new Map(candles.map((c, i) => [c.t, i]));
      chart.subscribeCrosshairMove((param) => {
        const el = legendRef.current;
        if (!el) return;
        const t = param.time as string | undefined;
        const i = t ? byTime.get(t) : undefined;
        if (i == null) {
          el.textContent = "";
          return;
        }
        const c = candles[i];
        const prev = i > 0 ? candles[i - 1].c : null;
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
    };
  }, [candles, calc, settings, visibleDays]);

  return (
    <div>
      <div className="chart-toolbar">
        {MA_DEFS.map((m) => (
          <label key={m.key} className={`chip-toggle ${settings.ma[m.key] ? "on" : ""}`} style={{ "--c": m.color } as React.CSSProperties}>
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
        <label className={`chip-toggle ${settings.boll ? "on" : ""}`} style={{ "--c": "#898781" } as React.CSSProperties}>
          <input
            type="checkbox"
            checked={settings.boll}
            onChange={(e) => setSettings((s) => ({ ...s, boll: e.target.checked }))}
          />
          布林
        </label>
        <span className="toolbar-sep" />
        {(["macd", "kd", "rsi"] as SubKey[]).map((k) => (
          <button
            key={k}
            className={`chip-toggle sub ${settings.sub === k ? "on" : ""}`}
            onClick={() => setSettings((s) => ({ ...s, sub: k }))}
          >
            {k.toUpperCase()}
          </button>
        ))}
      </div>
      <div className="chart-shell">
        <div ref={legendRef} className="chart-legend" />
        <div ref={ref} className="chart-wrap tall" />
      </div>
    </div>
  );
}
