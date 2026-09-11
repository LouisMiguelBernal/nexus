"use client";

/**
 * Nexus - cross-asset candle chart.
 *
 * Deliberately much simpler than TradingTab's chart: no drawings, no overlays,
 * no zone rendering. This is a context chart for an instrument you cannot
 * trade here, so it carries only what answers "what has this done lately" -
 * candles, volume and two moving averages.
 *
 * The series are created once and re-fed on each poll rather than torn down,
 * so a refresh never throws away the user's pan and zoom.
 */

import { useEffect, useRef } from "react";
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from "lightweight-charts";

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

/** Simple moving average over closes; the leading window is left undefined. */
function sma(candles: Candle[], period: number) {
  const out: { time: Time; value: number }[] = [];
  let sum = 0;
  for (let i = 0; i < candles.length; i++) {
    sum += candles[i].close;
    if (i >= period) sum -= candles[i - period].close;
    if (i >= period - 1) out.push({ time: candles[i].time as Time, value: sum / period });
  }
  return out;
}

export default function CrossAssetChart({
  candles,
  height = 320,
}: {
  candles: Candle[];
  height?: number;
}) {
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const price = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volume = useRef<ISeriesApi<"Histogram"> | null>(null);
  const ma20 = useRef<ISeriesApi<"Line"> | null>(null);
  const ma50 = useRef<ISeriesApi<"Line"> | null>(null);
  const fitted = useRef(false);

  useEffect(() => {
    if (!host.current) return;
    const css = getComputedStyle(document.documentElement);
    const v = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback;

    const bull = v("--chart-bull", "#16c784");
    const bear = v("--chart-bear", "#ea3943");

    const c = createChart(host.current, {
      height,
      layout: {
        background: { color: "transparent" },
        textColor: v("--on-surface-dim", "#767575"),
        fontSize: 10,
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: v("--chart-grid", "rgba(255,255,255,0.03)") },
        horzLines: { color: v("--chart-grid", "rgba(255,255,255,0.03)") },
      },
      rightPriceScale: {
        borderColor: v("--chart-axis", "rgba(255,255,255,0.08)"),
        scaleMargins: { top: 0.08, bottom: 0.26 },
      },
      timeScale: {
        borderColor: v("--chart-axis", "rgba(255,255,255,0.08)"),
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: { mode: CrosshairMode.Normal },
      // The chart sits in a scrolling tab; swallowing the wheel to zoom would
      // strand the reader halfway down the page.
      handleScroll: { mouseWheel: false, pressedMouseMove: true },
      handleScale: { mouseWheel: false, pinch: true, axisPressedMouseMove: true },
    });

    price.current = c.addSeries(CandlestickSeries, {
      upColor: bull,
      downColor: bear,
      borderUpColor: bull,
      borderDownColor: bear,
      wickUpColor: bull,
      wickDownColor: bear,
    });

    volume.current = c.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
    });
    c.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });

    ma20.current = c.addSeries(LineSeries, {
      color: v("--primary", "#c6c6c7"),
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    ma50.current = c.addSeries(LineSeries, {
      color: v("--accent-blue", "#60a5fa"),
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    chart.current = c;

    const observer = new ResizeObserver(([entry]) => {
      c.applyOptions({ width: entry.contentRect.width });
    });
    observer.observe(host.current);

    return () => {
      observer.disconnect();
      c.remove();
      chart.current = null;
      fitted.current = false;
    };
  }, [height]);

  useEffect(() => {
    if (!price.current || candles.length === 0) return;

    // lightweight-charts requires strictly ascending unique timestamps.
    const seen = new Map<number, Candle>();
    for (const k of candles) {
      if (Number.isFinite(k.time) && Number.isFinite(k.close)) seen.set(Math.floor(k.time), k);
    }
    const rows = Array.from(seen.values()).sort((a, b) => a.time - b.time);

    price.current.setData(
      rows.map((k) => ({
        time: k.time as Time,
        open: k.open,
        high: k.high,
        low: k.low,
        close: k.close,
      })),
    );

    volume.current?.setData(
      rows.map((k) => ({
        time: k.time as Time,
        value: k.volume,
        color: k.close >= k.open ? "rgba(22,199,132,0.28)" : "rgba(234,57,67,0.28)",
      })),
    );

    ma20.current?.setData(rows.length > 20 ? sma(rows, 20) : []);
    ma50.current?.setData(rows.length > 50 ? sma(rows, 50) : []);

    // Only auto-fit the first load; after that the viewport belongs to the user.
    if (!fitted.current) {
      chart.current?.timeScale().fitContent();
      fitted.current = true;
    }
  }, [candles]);

  return <div ref={host} style={{ width: "100%", height }} />;
}
