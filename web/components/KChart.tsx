"use client";

import { useEffect, useRef } from "react";
import type { Candle } from "@/lib/types";

/** 日 K + 成交量(lightweight-charts v5)。台股慣例:紅漲綠跌。 */
export default function KChart({ candles }: { candles: Candle[] }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current || candles.length === 0) return;
    let chart: import("lightweight-charts").IChartApi | undefined;
    let disposed = false;

    import("lightweight-charts").then(
      ({ createChart, CandlestickSeries, HistogramSeries, ColorType }) => {
        if (disposed || !ref.current) return;
        chart = createChart(ref.current, {
          autoSize: true,
          layout: {
            background: { type: ColorType.Solid, color: "transparent" },
            textColor: "#898781",
            fontSize: 11,
          },
          grid: {
            vertLines: { color: "#242422" },
            horzLines: { color: "#242422" },
          },
          rightPriceScale: { borderColor: "#383835" },
          timeScale: { borderColor: "#383835", timeVisible: false },
          crosshair: { mode: 0 },
        });
        const candleSeries = chart.addSeries(CandlestickSeries, {
          upColor: "#e66767",
          borderUpColor: "#e66767",
          wickUpColor: "#e66767",
          downColor: "#0ca30c",
          borderDownColor: "#0ca30c",
          wickDownColor: "#0ca30c",
        });
        candleSeries.setData(
          candles.map((c) => ({ time: c.t, open: c.o, high: c.h, low: c.l, close: c.c })),
        );
        const volSeries = chart.addSeries(HistogramSeries, {
          priceScaleId: "vol",
          priceFormat: { type: "volume" },
        });
        chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
        volSeries.setData(
          candles.map((c, i) => ({
            time: c.t,
            value: c.v,
            color:
              i > 0 && c.c >= candles[i - 1].c
                ? "rgba(230, 103, 103, 0.45)"
                : "rgba(12, 163, 12, 0.45)",
          })),
        );
        chart.timeScale().fitContent();
      },
    );

    return () => {
      disposed = true;
      chart?.remove();
    };
  }, [candles]);

  return <div ref={ref} className="chart-wrap" />;
}
