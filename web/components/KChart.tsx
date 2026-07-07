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
      ({ createChart, CandlestickSeries, HistogramSeries, LineSeries, ColorType }) => {
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
        const ma5 = chart.addSeries(LineSeries, { color: "#fab219", lineWidth: 1, priceLineVisible: false });
        ma5.setData(candles.filter((c) => c.ma5 != null).map((c) => ({ time: c.t, value: c.ma5! })));
        const ma20 = chart.addSeries(LineSeries, { color: "#35b5c9", lineWidth: 1, priceLineVisible: false });
        ma20.setData(candles.filter((c) => c.ma20 != null).map((c) => ({ time: c.t, value: c.ma20! })));
        const ma60 = chart.addSeries(LineSeries, { color: "#898781", lineWidth: 1, priceLineVisible: false });
        ma60.setData(candles.filter((c) => c.ma60 != null).map((c) => ({ time: c.t, value: c.ma60! })));
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
