"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from "lightweight-charts";
import DrawingLayer, {
  DEFAULT_FIB_LEVELS,
  type Drawing,
  type FibLevel,
  type Tool,
  type ZoneOverlay,
} from "./DrawingLayer";
import { MatrixPanel } from "@/components/matrix/MatrixPanel";

// =============================================================================
// Chart theme palettes - applied via chart.applyOptions() on toggle
// =============================================================================
// Shared right-axis width - keeps main chart, RSI strip, and on-chain strip
// in lockstep horizontally so candles, RSI ticks, and OI/basis bars line up.
const PRICE_AXIS_WIDTH = 72;

const CHART_THEME_DARK = {
  layout: {
    background: { color: "#0e0e0e" },
    textColor: "#acabaa",
  },
  grid: {
    vertLines: { color: "rgba(255,255,255,0.03)" },
    horzLines: { color: "rgba(255,255,255,0.03)" },
  },
  crosshair: {
    vertLine: { color: "rgba(198,198,199,0.3)", labelBackgroundColor: "#252626" },
    horzLine: { color: "rgba(198,198,199,0.3)", labelBackgroundColor: "#252626" },
  },
  rightPriceScale: { borderColor: "rgba(255,255,255,0.06)" },
  timeScale: { borderColor: "rgba(255,255,255,0.06)" },
};

const CHART_THEME_LIGHT = {
  layout: {
    background: { color: "#f4f4f6" },
    textColor: "#44445a",
  },
  grid: {
    vertLines: { color: "rgba(0,0,0,0.04)" },
    horzLines: { color: "rgba(0,0,0,0.04)" },
  },
  crosshair: {
    vertLine: { color: "rgba(0,0,0,0.25)", labelBackgroundColor: "#e2e2e6" },
    horzLine: { color: "rgba(0,0,0,0.25)", labelBackgroundColor: "#e2e2e6" },
  },
  rightPriceScale: { borderColor: "rgba(0,0,0,0.10)" },
  timeScale: { borderColor: "rgba(0,0,0,0.10)" },
};

interface Props {
  symbol: string;
  api: string;
  onSymbolChange?: (s: string) => void;
}

type Interval = "1m" | "5m" | "15m" | "30m" | "1h" | "4h" | "1d" | "1w";
const INTERVALS: Interval[] = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"];

interface Candle {
  time: number; open: number; high: number; low: number; close: number; volume: number;
}

interface IndicatorSnapshot {
  symbol: string;
  interval: string;
  last_close: number;
  latest: {
    rsi_14: number | null;
    ema_50: number | null;
    ema_200: number | null;
    ema_cross: number | null;
    ema_trend: string;
    bb_upper: number;
    bb_middle: number;
    bb_lower: number;
    bb_width_pct: number;
    macd: number | null;
    macd_signal: number | null;
    macd_hist: number | null;
    macd_bias: string | null;
    stoch_k: number | null;
    stoch_d: number | null;
    atr_14: number | null;
    adx_14: number | null;
    adx_regime: string;
    vwap?: number | null;
    obv?: number | null;
    ichimoku_tenkan?: number | null;
    ichimoku_kijun?: number | null;
    ichimoku_senkou_a?: number | null;
    ichimoku_senkou_b?: number | null;
    ichimoku_bias?: string | null;
    stddev_channel_upper?: number | null;
    stddev_channel_middle?: number | null;
    stddev_channel_lower?: number | null;
  };
  pivots: {
    r2: number | null; r1: number | null; pivot: number | null;
    s1: number | null; s2: number | null;
    variants?: {
      classic?: Record<string, number | null>;
      camarilla?: Record<string, number | null>;
      woodie?: Record<string, number | null>;
    };
  };
  series: {
    time: number[];
    ema_50: (number | null)[];
    ema_200: (number | null)[];
    bb_upper: (number | null)[];
    bb_middle: (number | null)[];
    bb_lower: (number | null)[];
    rsi_14: (number | null)[];
    macd: (number | null)[];
    macd_signal: (number | null)[];
    macd_hist: (number | null)[];
    vwap?: (number | null)[];
    obv?: (number | null)[];
    ichimoku_tenkan?: (number | null)[];
    ichimoku_kijun?: (number | null)[];
    ichimoku_senkou_a?: (number | null)[];
    ichimoku_senkou_b?: (number | null)[];
    ichimoku_chikou?: (number | null)[];
    stddev_channel_upper?: (number | null)[];
    stddev_channel_middle?: (number | null)[];
    stddev_channel_lower?: (number | null)[];
  };
}

interface Overlays {
  ema: boolean;
  bollinger: boolean;
  rsi: boolean;
  vwap: boolean;
  ichimoku: boolean;
  stddevChannel: boolean;
  pivots: boolean;
  obv: boolean;
  kumoFill: boolean;
  volumeProfile: boolean;
  derivativesStrip: boolean;
}

interface SeriesPoint { time: number; value: number; }
interface DerivativesData {
  basis:   SeriesPoint[];
  funding: SeriesPoint[];
  oi:      SeriesPoint[];
  latest?: {
    basis_pct?: number;
    funding_pct?: number;
    oi_total?: number;
    funding_venues?: Record<string, number> | null;
  };
}

interface DepthBin { price: number; cumulative: number; }
interface HeatmapPayload {
  current_price?: number;
  depth_profile?: {
    bid_prices?: number[]; bid_cumulative?: number[];
    ask_prices?: number[]; ask_cumulative?: number[];
  };
}

interface TickerStats {
  last_price: number;
  price_change_pct: number;
  high_24h: number;
  low_24h: number;
  volume_24h: number;
  quote_volume_24h: number;
  trades_24h: number;
}

export default function TradingTab({ symbol, api }: Props) {
  const [interval, setInterval] = useState<Interval>("1h");
  const [indicators, setIndicators] = useState<IndicatorSnapshot | null>(null);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [ticker, setTicker] = useState<TickerStats | null>(null);
  const [overlays, setOverlays] = useState<Overlays>({
    ema: true, bollinger: false, rsi: true,
    vwap: false, ichimoku: true, stddevChannel: false, pivots: false, obv: false,
    kumoFill: true, volumeProfile: true, derivativesStrip: true,
  });
  const [loading, setLoading] = useState(true);
  const [derivatives, setDerivatives] = useState<DerivativesData | null>(null);
  const [heatmap,     setHeatmap]     = useState<HeatmapPayload | null>(null);

  const [tool, setTool] = useState<Tool>("none");
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const [fibLevels, setFibLevels] = useState<FibLevel[]>(DEFAULT_FIB_LEVELS);
  const [fibSettingsOpen, setFibSettingsOpen] = useState(false);
  const [zones, setZones] = useState<ZoneOverlay[]>([]);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(`nexus.drawings.${symbol}`);
      setDrawings(raw ? (JSON.parse(raw) as Drawing[]) : []);
    } catch { setDrawings([]); }
  }, [symbol]);
  useEffect(() => {
    try { localStorage.setItem(`nexus.drawings.${symbol}`, JSON.stringify(drawings)); } catch { /* quota */ }
  }, [symbol, drawings]);

  useEffect(() => {
    try {
      const raw = localStorage.getItem("nexus.fibLevels");
      if (raw) setFibLevels(JSON.parse(raw) as FibLevel[]);
    } catch { /* ignore */ }
  }, []);
  useEffect(() => {
    try { localStorage.setItem("nexus.fibLevels", JSON.stringify(fibLevels)); } catch { /* quota */ }
  }, [fibLevels]);

  useEffect(() => {
    let cancelled = false;
    const ac = new AbortController();
    const load = async () => {
      try {
        const r = await fetch(`${api}/api/zones/${symbol}`, { signal: ac.signal });
        if (!r.ok) return;
        const d = await r.json();
        if (cancelled) return;
        const arr: ZoneOverlay[] = Array.isArray(d?.zones)
          ? (d.zones as Array<Record<string, unknown>>).map((z) => ({
              price_low: Number(z.price_low || 0),
              price_high: Number(z.price_high || 0),
              tier: String(z.tier || "bronze"),
              zone_type: z.zone_type ? String(z.zone_type) : undefined,
              score: z.score != null ? Number(z.score) : undefined,
            }))
          : [];
        setZones(arr.filter((z) => z.price_low > 0 && z.price_high > 0));
      } catch { /* silent */ }
    };
    void load();
    const h = window.setInterval(() => void load(), 30000);
    return () => { cancelled = true; ac.abort(); window.clearInterval(h); };
  }, [api, symbol]);

  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const fullscreenRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "r" || e.key === "R") { e.preventDefault(); setTool("rect"); }
      else if (e.key === "b" || e.key === "B") { e.preventDefault(); setTool("fib"); }
      else if (e.key === "t" || e.key === "T") { e.preventDefault(); setTool("trendline"); }
      else if (e.key === "h" || e.key === "H") { e.preventDefault(); setTool("hline"); }
      else if (e.key === "x" || e.key === "X") { e.preventDefault(); setDrawings([]); }
      else if (e.key === "f" || e.key === "F") {
        e.preventDefault();
        const el = fullscreenRef.current;
        if (!el) return;
        if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
        else el.requestFullscreen().catch(() => {});
      }
      else if (e.key === "Escape") { setTool("none"); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Single combined polling loop - 4 endpoints fanned out in parallel,
  // 20s cadence (was 10s for 2 endpoints). Backend caches keep work
  // minimal; UI only re-renders on changed JSON to save reconcile cost.
  const lastJsonRef = useRef<{ k?: string; i?: string; d?: string; h?: string }>({});
  useEffect(() => {
    let cancelled = false;
    const ac = new AbortController();
    const load = async () => {
      setLoading(true);
      try {
        const [kRes, iRes, dRes, hRes] = await Promise.all([
          fetch(`${api}/api/klines/${symbol}?interval=${interval}&limit=500`, { signal: ac.signal }),
          fetch(`${api}/api/indicators/${symbol}?interval=${interval}&limit=500`, { signal: ac.signal }),
          fetch(`${api}/api/derivatives/${symbol}?interval=${interval}&limit=500`, { signal: ac.signal }).catch(() => null),
          fetch(`${api}/api/heatmap/${symbol}`, { signal: ac.signal }).catch(() => null),
        ]);
        if (!kRes.ok || !iRes.ok) throw new Error(`klines/indicators HTTP ${kRes.status}/${iRes.status}`);
        const kText = await kRes.text();
        const iText = await iRes.text();
        if (cancelled) return;
        // Parse FIRST, then update both ref + state - otherwise a parse failure
        // poisons the dedup ref (we'd "remember" text we never successfully
        // applied, so the next identical fetch would silently skip it).
        if (lastJsonRef.current.k !== kText) {
          try {
            const parsed = JSON.parse(kText) as { candles?: Candle[] };
            setCandles((parsed.candles ?? []) as Candle[]);
            lastJsonRef.current.k = kText;
          } catch (e) { console.warn("[TradingTab] klines parse failed", e); }
        }
        if (lastJsonRef.current.i !== iText) {
          try {
            const parsed = JSON.parse(iText) as IndicatorSnapshot;
            setIndicators(parsed);
            lastJsonRef.current.i = iText;
          } catch (e) { console.warn("[TradingTab] indicators parse failed", e); }
        }
        if (dRes && dRes.ok) {
          const dText = await dRes.text();
          if (!cancelled && lastJsonRef.current.d !== dText) {
            try {
              const parsed = JSON.parse(dText) as DerivativesData;
              setDerivatives(parsed);
              lastJsonRef.current.d = dText;
            } catch (e) { console.warn("[TradingTab] derivatives parse failed", e); }
          }
        }
        if (hRes && hRes.ok) {
          const hText = await hRes.text();
          if (!cancelled && lastJsonRef.current.h !== hText) {
            try {
              const parsed = JSON.parse(hText) as HeatmapPayload;
              setHeatmap(parsed);
              lastJsonRef.current.h = hText;
            } catch (e) { console.warn("[TradingTab] heatmap parse failed", e); }
          }
        }
      } catch (e) {
        if (e instanceof DOMException && e.name === "AbortError") return;
        console.warn("[TradingTab] poll failed", e);
      }
      finally { if (!cancelled) setLoading(false); }
    };
    void load();
    const handle = window.setInterval(() => void load(), 20000);
    return () => { cancelled = true; ac.abort(); window.clearInterval(handle); };
  }, [api, symbol, interval]);

  useEffect(() => {
    let cancelled = false;
    const ac = new AbortController();
    const load = async () => {
      try {
        const r = await fetch(`${api}/api/ticker/${symbol}`, { signal: ac.signal });
        if (!r.ok) return;
        const d: TickerStats = await r.json();
        if (!cancelled) setTicker(d);
      } catch { /* silent */ }
    };
    void load();
    const h = window.setInterval(() => void load(), 5000);
    return () => { cancelled = true; ac.abort(); window.clearInterval(h); };
  }, [api, symbol]);

  return (
    <div
      className="no-select"
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 340px",
        gridTemplateRows: "auto 1fr",
        gap: 0,
        height: "100%",
        background: "var(--surface)",
      }}
    >
      {/* Secondary toolbar */}
      <div
        style={{
          gridColumn: "1 / -1",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          padding: "8px 16px",
          borderBottom: "1px solid var(--hairline)",
          background: "var(--surface-container-low)",
        }}
      >
        <div className="flex items-center gap-3" style={{ flex: "1 1 auto", minWidth: 0 }}>
          <span
            className="text-mono"
            style={{ color: "var(--on-surface)", fontWeight: 800, fontSize: 15, letterSpacing: "0.06em" }}
          >
            {symbol}
          </span>
          <span
            style={{
              padding: "2px 8px",
              background: "rgba(198,198,199,0.1)",
              color: "var(--primary)",
              fontSize: 9,
              fontWeight: 700,
              letterSpacing: "0.12em",
              borderRadius: 2,
            }}
          >
            {interval.toUpperCase()}
          </span>
          <div style={{ width: 1, height: 16, background: "var(--hairline)" }} />
          {ticker ? (
            <div
              className="flex items-center gap-3 text-mono"
              style={{ fontSize: 11, letterSpacing: "0.04em", overflow: "hidden", fontVariantNumeric: "tabular-nums" }}
            >
              <TickCell
                label="LAST"
                value={ticker.last_price.toLocaleString(undefined, {
                  minimumFractionDigits: ticker.last_price < 1 ? 5 : 2,
                  maximumFractionDigits: ticker.last_price < 1 ? 5 : 2,
                })}
                tone="on"
              />
              <TickCell
                label="24H"
                value={`${ticker.price_change_pct >= 0 ? "+" : ""}${ticker.price_change_pct.toFixed(2)}%`}
                tone={ticker.price_change_pct >= 0 ? "bull" : "bear"}
              />
              <TickCell label="HIGH" value={ticker.high_24h.toLocaleString(undefined, { maximumFractionDigits: 2 })} />
              <TickCell label="LOW"  value={ticker.low_24h.toLocaleString(undefined, { maximumFractionDigits: 2 })} />
              <TickCell label="VOL"  value={compact(ticker.volume_24h)} />
              <TickCell label="VOL $" value={compact(ticker.quote_volume_24h)} />
              <TickCell label="TRADES" value={compact(ticker.trades_24h)} />
            </div>
          ) : null}
        </div>

        <div className="flex items-center gap-2" style={{ flex: "0 0 auto" }}>
          <div className="flex items-center gap-1">
            {INTERVALS.map((iv) => (
              <button
                key={iv}
                onClick={() => setInterval(iv)}
                style={{
                  padding: "5px 9px",
                  fontSize: 11,
                  fontWeight: iv === interval ? 700 : 500,
                  color: iv === interval ? "var(--on-surface)" : "var(--on-surface-variant)",
                  background: iv === interval ? "rgba(198,198,199,0.12)" : "transparent",
                  border: `1px solid ${iv === interval ? "var(--primary)" : "var(--hairline)"}`,
                  borderRadius: 4,
                  cursor: "pointer",
                  letterSpacing: "0.04em",
                  textTransform: "uppercase",
                  fontFamily: "inherit",
                  transition: "background 150ms ease",
                }}
              >
                {iv}
              </button>
            ))}
          </div>
          
          <div style={{ width: 1, height: 18, background: "var(--hairline)", margin: "0 4px" }} />
          <button
            onClick={() => {
              const el = fullscreenRef.current;
              if (!el) return;
              if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
              else el.requestFullscreen().catch(() => {});
            }}
            title="Fullscreen chart (F)"
            style={{
              width: 28, height: 26, padding: 0,
              display: "flex", alignItems: "center", justifyContent: "center",
              background: "transparent", color: "var(--on-surface-variant)",
              border: "1px solid var(--hairline)", borderRadius: 4,
              cursor: "pointer", fontSize: 13, fontFamily: "inherit",
              transition: "background 150ms ease",
            }}
          >
            ⛶
          </button>
        </div>
      </div>

      {/* CHART */}
      <ChartContainer externalRef={fullscreenRef}>
        <ChartCanvas
          fitKey={`${symbol}:${interval}`}
          candles={candles}
          indicators={indicators}
          overlays={overlays}
          derivatives={derivatives}
          heatmap={heatmap}
          onChartReady={(c, s) => { chartRef.current = c; candleSeriesRef.current = s; }}
        />
        <TechnicalsButton overlays={overlays} setOverlays={setOverlays} />
        <DrawingSidebar
          tool={tool}
          setTool={setTool}
          hasDrawings={drawings.length > 0}
          clear={() => setDrawings([])}
          onFibSettings={() => setFibSettingsOpen((v) => !v)}
          fibSettingsOpen={fibSettingsOpen}
        />
        {fibSettingsOpen && (
          <FibSettingsPanel
            levels={fibLevels}
            setLevels={setFibLevels}
            onClose={() => setFibSettingsOpen(false)}
          />
        )}
        <DrawingLayer
          chart={chartRef.current}
          priceSeries={candleSeriesRef.current}
          tool={tool}
          setTool={setTool}
          drawings={drawings}
          setDrawings={setDrawings}
          fibLevels={fibLevels}
          zones={zones}
        />
        {loading && !candles.length && (
          <div
            style={{
              position: "absolute", inset: 0,
              display: "flex", alignItems: "center", justifyContent: "center",
              color: "var(--on-surface-dim)", fontSize: 12, letterSpacing: "0.18em",
            }}
          >
            LOADING CANDLES…
          </div>
        )}
      </ChartContainer>

      {/* RIGHT PANEL */}
      <aside
        style={{
          borderLeft: "1px solid var(--hairline)",
          background: "var(--surface-container-low)",
          overflowY: "auto",
          padding: 14,
        }}
      >
        <MatrixPanel api={api} symbol={symbol} />
      </aside>
    </div>
  );
}

// =============================================================================
// Chart container
// =============================================================================
function ChartContainer({
  children,
  externalRef,
}: {
  children: React.ReactNode;
  externalRef?: React.MutableRefObject<HTMLDivElement | null>;
}) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const setRef = (el: HTMLDivElement | null) => {
    wrapRef.current = el;
    if (externalRef) externalRef.current = el;
  };
  return (
    <div ref={setRef} style={{ position: "relative", minHeight: 0, minWidth: 0, background: "var(--surface)" }}>
      {children}
    </div>
  );
}

// =============================================================================
// Technicals modal button
// =============================================================================
type TechnicalCategory = "TREND" | "MOMENTUM" | "VOLATILITY" | "VOLUME";
const TECHNICAL_DEFS: Array<{
  key: keyof Overlays;
  label: string;
  hint: string;
  category: TechnicalCategory;
  params?: string;
}> = [
  { key: "ema",          label: "EMA 50 / 200",      hint: "Exponential moving averages",                    category: "TREND",      params: "50, 200" },
  { key: "ichimoku",     label: "Ichimoku Cloud",     hint: "Tenkan / Kijun / Kumo bias",                    category: "TREND",      params: "9, 26, 52" },
  { key: "kumoFill",     label: "Kumo Cloud Fill",    hint: "Filled Senkou A / B band, color by sign",       category: "TREND",      params: "shaded" },
  { key: "pivots",       label: "Pivot Points",       hint: "Classic S/R levels from prior candle",          category: "TREND",      params: "classic" },
  { key: "rsi",          label: "RSI 14",             hint: "Relative Strength Index (oscillator pane)",     category: "MOMENTUM",   params: "14" },
  { key: "bollinger",    label: "Bollinger Bands",    hint: "Volatility envelope (price ± kσ)",              category: "VOLATILITY", params: "20, 2" },
  { key: "stddevChannel",label: "Std-dev Channel",   hint: "Linear regression ± kσ residuals",              category: "VOLATILITY", params: "100, 2" },
  { key: "vwap",         label: "VWAP",               hint: "Volume-weighted average price",                 category: "VOLUME",     params: "cumulative" },
  { key: "obv",          label: "OBV",                hint: "On-Balance Volume (readout)",                   category: "VOLUME" },
  { key: "volumeProfile",label: "Volume Profile",     hint: "Cross-venue depth histogram on right edge",     category: "VOLUME",     params: "live book" },
  { key: "derivativesStrip", label: "Derivatives Strip", hint: "Spot-perp basis + funding + OI sub-pane",   category: "VOLUME",     params: "lower pane" },
];

function WaveIcon({ size = 14, color = "currentColor" }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
         strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M2 12 L6 12 L8 6 L12 18 L14 10 L18 14 L22 12" />
    </svg>
  );
}

function TechnicalsButton({ overlays, setOverlays }: { overlays: Overlays; setOverlays: React.Dispatch<React.SetStateAction<Overlays>> }) {
  const [open, setOpen] = useState(false);
  const activeCount = (Object.values(overlays) as boolean[]).filter(Boolean).length;
  const activeLabels = TECHNICAL_DEFS.filter((d) => overlays[d.key]).map((d) => d.label);

  return (
    <>
      <div style={{ position: "absolute", top: 8, left: 8, zIndex: 10, display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
        <button
          onClick={() => setOpen(true)}
          title={`Indicators${activeCount ? ` (${activeCount} active)` : ""}`}
          style={{
            position: "relative", width: 32, height: 28, padding: 0,
            display: "flex", alignItems: "center", justifyContent: "center",
            background: "var(--surface-container-low, rgba(14,14,14,0.72))",
            color: activeCount > 0 ? "var(--primary)" : "var(--on-surface-variant)",
            border: `1px solid ${activeCount > 0 ? "rgba(var(--primary-rgb,198,198,199),0.45)" : "var(--hairline)"}`,
            borderRadius: 4, cursor: "pointer", fontFamily: "inherit",
            backdropFilter: "blur(4px)", flexShrink: 0, transition: "background 150ms ease, border-color 150ms ease",
            boxShadow: "0 1px 4px rgba(0,0,0,0.12)",
          }}
        >
          <WaveIcon size={15} />
          {activeCount > 0 && (
            <span style={{
              position: "absolute", top: -5, right: -5, minWidth: 14, height: 14, padding: "0 3px",
              borderRadius: 7, background: "var(--primary)", color: "var(--on-primary, #fff)", fontSize: 9, fontWeight: 700,
              display: "flex", alignItems: "center", justifyContent: "center",
              boxShadow: "0 0 0 2px var(--surface)",
            }}>
              {activeCount}
            </span>
          )}
        </button>
        {activeLabels.length > 0 && (
          <div className="flex items-center" style={{ gap: 4, fontSize: 10, color: "var(--on-surface-variant)", flexWrap: "wrap" }}>
            {activeLabels.map((lbl, i) => (
              <span key={lbl} className="text-mono" style={{
                display: "inline-flex", alignItems: "center", gap: 4,
                padding: "2px 8px", background: "var(--surface-container, rgba(14,14,14,0.55))",
                color: "var(--on-surface)",
                border: "1px solid var(--hairline)", borderRadius: 4,
                backdropFilter: "blur(2px)", whiteSpace: "nowrap",
              }}>
                {i === 0 && <span style={{ width: 4, height: 4, borderRadius: "50%", background: "var(--primary)" }} />}
                {lbl}
              </span>
            ))}
          </div>
        )}
      </div>
      {open && <IndicatorModal overlays={overlays} setOverlays={setOverlays} onClose={() => setOpen(false)} />}
    </>
  );
}

function IndicatorModal({ overlays, setOverlays, onClose }: {
  overlays: Overlays;
  setOverlays: React.Dispatch<React.SetStateAction<Overlays>>;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const q = query.trim().toLowerCase();
  const filtered = TECHNICAL_DEFS.filter((d) => !q || d.label.toLowerCase().includes(q) || d.hint.toLowerCase().includes(q) || d.category.toLowerCase().includes(q));
  const grouped = (["TREND", "MOMENTUM", "VOLATILITY", "VOLUME"] as TechnicalCategory[])
    .map((cat) => ({ cat, items: filtered.filter((d) => d.category === cat) }))
    .filter((g) => g.items.length > 0);

  return (
    <div
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{
        position: "fixed", inset: 0, zIndex: 100,
        background: "rgba(0,0,0,0.45)", backdropFilter: "blur(2px)",
        display: "flex", alignItems: "center", justifyContent: "center",
        animation: "nx-fade-in 180ms ease-out",
      }}
    >
      <div
        role="dialog" aria-modal="true" aria-label="Indicators"
        style={{
          width: 520, maxHeight: "min(520px, 80vh)",
          display: "flex", flexDirection: "column",
          background: "var(--surface-container-high, rgba(13,17,23,0.96))",
          backdropFilter: "blur(20px)",
          border: "1px solid var(--hairline)", borderRadius: 16,
          boxShadow: "0 12px 48px rgba(0,0,0,0.35)", color: "var(--on-surface)",
          animation: "nx-scale-in 180ms cubic-bezier(0.2, 0.8, 0.2, 1)",
        }}
      >
        <div style={{ padding: "14px 18px", display: "flex", alignItems: "center", gap: 10, borderBottom: "1px solid var(--hairline)" }}>
          <WaveIcon size={16} color="var(--primary)" />
          <span style={{ fontSize: 12, fontWeight: 700, letterSpacing: "0.12em", textTransform: "uppercase" }}>Indicators</span>
          <span style={{ flex: 1 }} />
          <button onClick={onClose} style={{ width: 26, height: 26, padding: 0, display: "flex", alignItems: "center", justifyContent: "center", background: "transparent", color: "var(--on-surface-variant)", border: "1px solid var(--hairline)", borderRadius: 6, cursor: "pointer", fontSize: 13, fontFamily: "inherit" }}>✕</button>
        </div>
        <div style={{ padding: "10px 18px 6px" }}>
          <input
            value={query} onChange={(e) => setQuery(e.target.value)} autoFocus placeholder="Search indicators…"
            style={{ width: "100%", padding: "8px 10px", fontSize: 12, color: "var(--on-surface)", background: "var(--surface-container, rgba(127,127,127,0.06))", border: "1px solid var(--hairline)", borderRadius: 6, outline: "none", fontFamily: "inherit" }}
          />
        </div>
        <div style={{ padding: "4px 10px 14px", overflowY: "auto" }}>
          {grouped.map(({ cat, items }) => (
            <div key={cat} style={{ marginTop: 10 }}>
              <div style={{ padding: "4px 8px", fontSize: 9, fontWeight: 700, letterSpacing: "0.18em", color: "var(--on-surface-dim)" }}>{cat}</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {items.map((d) => {
                  const active = overlays[d.key];
                  return (
                    <label key={d.key} style={{
                      display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, padding: "10px 10px",
                      background: active ? "rgba(var(--primary-rgb,198,198,199),0.10)" : "transparent",
                      border: `1px solid ${active ? "rgba(var(--primary-rgb,198,198,199),0.30)" : "transparent"}`,
                      borderRadius: 8, cursor: "pointer", transition: "background 120ms ease, border-color 120ms ease",
                    }}>
                      <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
                        <div className="flex items-center" style={{ gap: 8 }}>
                          <span style={{ fontSize: 12, fontWeight: 600 }}>{d.label}</span>
                          {d.params && <span className="text-mono" style={{ fontSize: 9, padding: "1px 6px", borderRadius: 3, background: "var(--surface-container, rgba(127,127,127,0.08))", color: "var(--on-surface-dim)" }}>{d.params}</span>}
                        </div>
                        <span style={{ fontSize: 10.5, color: "var(--on-surface-dim)" }}>{d.hint}</span>
                      </div>
                      <button
                        type="button" role="switch" aria-checked={active}
                        onClick={() => setOverlays((o) => ({ ...o, [d.key]: !o[d.key] }))}
                        style={{ position: "relative", width: 32, height: 18, borderRadius: 10, background: active ? "var(--primary)" : "var(--surface-container-high, rgba(127,127,127,0.18))", border: "none", cursor: "pointer", transition: "background 150ms ease", flexShrink: 0 }}
                      >
                        <span style={{ position: "absolute", top: 2, left: active ? 16 : 2, width: 14, height: 14, borderRadius: 7, background: "#ffffff", transition: "left 180ms cubic-bezier(0.2, 0.8, 0.2, 1)", boxShadow: "0 1px 3px rgba(0,0,0,0.25)" }} />
                      </button>
                    </label>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// Drawing sidebar
// =============================================================================
function DrawingSidebar({ tool, setTool, hasDrawings, clear, onFibSettings, fibSettingsOpen }: {
  tool: Tool; setTool: (t: Tool) => void;
  hasDrawings: boolean; clear: () => void;
  onFibSettings: () => void; fibSettingsOpen: boolean;
}) {
  const btn = (active: boolean, disabled = false): React.CSSProperties => ({
    width: 28, height: 28, display: "flex", alignItems: "center", justifyContent: "center",
    background: active ? "rgba(var(--primary-rgb,198,198,199),0.18)" : "var(--surface-container)",
    color: active ? "var(--primary)" : "var(--on-surface-variant)",
    border: `1px solid ${active ? "rgba(var(--primary-rgb,198,198,199),0.55)" : "var(--hairline)"}`,
    borderRadius: 4, cursor: disabled ? "not-allowed" : "pointer",
    fontFamily: "inherit", fontSize: 13, fontWeight: 600, opacity: disabled ? 0.35 : 1,
    padding: 0, backdropFilter: "blur(4px)", transition: "background 150ms ease",
  });
  const sep = <div style={{ height: 1, background: "var(--hairline)", margin: "2px 4px" }} />;
  return (
    <div role="toolbar" aria-label="Drawing tools" style={{
      position: "absolute", left: 8, top: "42%", transform: "translateY(-50%)",
      zIndex: 10, display: "flex", flexDirection: "column", alignItems: "center", gap: 3,
      padding: "4px", background: "var(--surface-container-low)", border: "1px solid var(--hairline)", borderRadius: 8,
      boxShadow: "0 2px 10px rgba(0,0,0,0.12)",
    }}>
      <button title="Crosshair / select (Esc)" onClick={() => setTool("none")} style={btn(tool === "none")}>✛</button>
      {sep}
      <button title="Trendline (T)" onClick={() => setTool(tool === "trendline" ? "none" : "trendline")} style={btn(tool === "trendline")}>╱</button>
      <button title="Horizontal line (H)" onClick={() => setTool(tool === "hline" ? "none" : "hline")} style={btn(tool === "hline")}>━</button>
      <button title="Rectangle (R)" onClick={() => setTool(tool === "rect" ? "none" : "rect")} style={btn(tool === "rect")}>▭</button>
      {sep}
      <button title="Fibonacci retracement (B)" onClick={() => setTool(tool === "fib" ? "none" : "fib")} style={btn(tool === "fib")}>ƒ</button>
      <button title="Fibonacci settings" onClick={onFibSettings} style={btn(fibSettingsOpen)}>⚙</button>
      {sep}
      <button title="Clear all drawings (X)" onClick={clear} style={btn(false, !hasDrawings)} disabled={!hasDrawings}>✕</button>
    </div>
  );
}

function FibSettingsPanel({ levels, setLevels, onClose }: {
  levels: FibLevel[]; setLevels: React.Dispatch<React.SetStateAction<FibLevel[]>>; onClose: () => void;
}) {
  const [newRatio, setNewRatio] = useState("");
  const toggle = (i: number) => setLevels((ls) => ls.map((l, j) => j === i ? { ...l, enabled: !l.enabled } : l));
  const updateColor = (i: number, color: string) => setLevels((ls) => ls.map((l, j) => j === i ? { ...l, color } : l));
  const remove = (i: number) => setLevels((ls) => ls.filter((_, j) => j !== i));
  const add = () => {
    const r = parseFloat(newRatio);
    if (!isFinite(r)) return;
    setLevels((ls) => [...ls, { ratio: r, color: "#a78bfa", enabled: true }].sort((a, b) => a.ratio - b.ratio));
    setNewRatio("");
  };

  return (
    <div style={{
      position: "absolute", top: "42%", left: 48, transform: "translateY(-50%)", zIndex: 20,
      width: 250, padding: 10, background: "var(--surface-container)",
      border: "1px solid var(--hairline)", borderRadius: 8, color: "var(--on-surface)", backdropFilter: "blur(6px)",
      boxShadow: "0 4px 20px rgba(0,0,0,0.18)",
    }}>
      <div className="flex items-center justify-between" style={{ marginBottom: 8 }}>
        <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.14em", color: "var(--on-surface-dim)" }}>FIBONACCI LEVELS</span>
        <button onClick={onClose} style={{ background: "transparent", border: "none", color: "var(--on-surface-variant)", cursor: "pointer", fontSize: 14 }}>✕</button>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 3, maxHeight: 280, overflowY: "auto" }}>
        {levels.map((l, i) => (
          <div key={`${l.ratio}-${i}`} className="flex items-center gap-2" style={{ fontSize: 11 }}>
            <input type="checkbox" checked={l.enabled} onChange={() => toggle(i)} />
            <span style={{ width: 52, fontFamily: "monospace", color: "var(--on-surface)" }}>{(l.ratio * 100).toFixed(1)}%</span>
            <input type="color" value={l.color} onChange={(e) => updateColor(i, e.target.value)} style={{ width: 22, height: 18, border: "none", background: "transparent", cursor: "pointer", padding: 0 }} />
            <span style={{ fontFamily: "monospace", color: "var(--on-surface-dim)", flex: 1, fontSize: 10 }}>ratio {l.ratio}</span>
            <button onClick={() => remove(i)} style={{ background: "transparent", border: "none", color: "var(--on-surface-variant)", cursor: "pointer", fontSize: 12 }}>✕</button>
          </div>
        ))}
      </div>
      <div className="flex items-center gap-2" style={{ marginTop: 10, paddingTop: 8, borderTop: "1px solid var(--hairline)" }}>
        <input
          type="number" step="0.01" placeholder="Add ratio (e.g. 1.414)" value={newRatio}
          onChange={(e) => setNewRatio(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }}
          style={{ flex: 1, padding: "4px 6px", fontSize: 11, background: "var(--surface-container-lowest)", border: "1px solid var(--hairline)", borderRadius: 2, color: "var(--on-surface)", fontFamily: "monospace" }}
        />
        <button onClick={add} style={{ padding: "4px 10px", fontSize: 10, fontWeight: 700, background: "rgba(var(--primary-rgb,198,198,199),0.14)", color: "var(--primary)", border: "1px solid rgba(var(--primary-rgb,198,198,199),0.55)", borderRadius: 2, cursor: "pointer", fontFamily: "inherit" }}>ADD</button>
      </div>
      <button
        onClick={() => setLevels(DEFAULT_FIB_LEVELS)}
        style={{ marginTop: 8, width: "100%", padding: "4px 0", fontSize: 10, fontWeight: 600, background: "transparent", color: "var(--on-surface-variant)", border: "1px solid var(--hairline)", borderRadius: 2, cursor: "pointer", fontFamily: "inherit" }}
      >
        RESET TO DEFAULTS
      </button>
    </div>
  );
}

// =============================================================================
// Chart canvas - now listens for nexus-theme-change to re-theme via applyOptions
// =============================================================================
function ChartCanvas({
  candles, indicators, overlays, derivatives, heatmap, fitKey = "", onChartReady,
}: {
  candles: Candle[];
  indicators: IndicatorSnapshot | null;
  overlays: Overlays;
  derivatives?: DerivativesData | null;
  heatmap?: HeatmapPayload | null;
  fitKey?: string;
  onChartReady?: (chart: IChartApi, candleSeries: ISeriesApi<"Candlestick">) => void;
}) {
  const boxRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volRef    = useRef<ISeriesApi<"Histogram"> | null>(null);
  const ema50Ref  = useRef<ISeriesApi<"Line"> | null>(null);
  const ema200Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const bbUpperRef  = useRef<ISeriesApi<"Line"> | null>(null);
  const bbMiddleRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bbLowerRef  = useRef<ISeriesApi<"Line"> | null>(null);
  const vwapRef   = useRef<ISeriesApi<"Line"> | null>(null);
  const obvRef    = useRef<ISeriesApi<"Line"> | null>(null);
  const ichiTenRef = useRef<ISeriesApi<"Line"> | null>(null);
  const ichiKijRef = useRef<ISeriesApi<"Line"> | null>(null);
  const ichiSaRef  = useRef<ISeriesApi<"Line"> | null>(null);
  const ichiSbRef  = useRef<ISeriesApi<"Line"> | null>(null);
  const sdcUpRef  = useRef<ISeriesApi<"Line"> | null>(null);
  const sdcMidRef = useRef<ISeriesApi<"Line"> | null>(null);
  const sdcLoRef  = useRef<ISeriesApi<"Line"> | null>(null);
  const pivotLinesRef = useRef<Array<{ line: unknown; remove: () => void }>>([]);

  // Canonical time grid for indicator alignment - recomputed only when the
  // candle list reference changes. Every indicator setData() below passes
  // this as the 3rd arg to `seriesPoints` so overlays anchor exactly to
  // candle close_times during pan/zoom (no sub-bar drift).
  const candleTimes = useMemo(() => candles.map((c) => c.time), [candles]);

  // Create chart once
  useEffect(() => {
    if (!boxRef.current) return;
    const el = boxRef.current;

    // Seed with persisted theme preference
    const savedLight = localStorage.getItem("nexus-theme") === "light";
    const themeOpts = savedLight ? CHART_THEME_LIGHT : CHART_THEME_DARK;

    const chart = createChart(el, {
      ...themeOpts,
      layout: {
        ...themeOpts.layout,
        fontFamily: "Inter, system-ui, sans-serif",
        fontSize: 11,
      },
      crosshair: {
        ...themeOpts.crosshair,
        mode: CrosshairMode.Normal,
        vertLine: { ...themeOpts.crosshair.vertLine, width: 1, style: 3 },
        horzLine: { ...themeOpts.crosshair.horzLine, width: 1, style: 3 },
      },
      rightPriceScale: { ...themeOpts.rightPriceScale, minimumWidth: PRICE_AXIS_WIDTH },
      timeScale: {
        ...themeOpts.timeScale,
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 5,
        barSpacing: 6,
      },
      autoSize: true,
    });
    chartRef.current = chart;

    const cs = chart.addSeries(CandlestickSeries, {
      upColor: "#16c784", downColor: "#ea3943",
      borderVisible: false, wickUpColor: "#16c784", wickDownColor: "#ea3943",
    });
    candleRef.current = cs;
    onChartReady?.(chart, cs);

    const vs = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" }, priceScaleId: "volume", color: "rgba(198,198,199,0.4)",
    });
    chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.78, bottom: 0.12 } });
    volRef.current = vs;

    return () => {
      chart.remove();
      chartRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- Listen for theme change and re-apply chart options ----
  useEffect(() => {
    const onTheme = (e: Event) => {
      const chart = chartRef.current;
      if (!chart) return;
      const isLight = (e as CustomEvent<{ light: boolean }>).detail.light;
      chart.applyOptions(isLight ? CHART_THEME_LIGHT : CHART_THEME_DARK);
    };
    window.addEventListener("nexus-theme-change", onTheme);
    return () => window.removeEventListener("nexus-theme-change", onTheme);
  }, []);

  // Update candles + volume
  const didFitRef = useRef(false);
  const lastFitKeyRef = useRef<string>("");
  useEffect(() => {
    if (fitKey !== lastFitKeyRef.current) {
      didFitRef.current = false;
      lastFitKeyRef.current = fitKey;
    }
  }, [fitKey]);
  useEffect(() => {
    const cs = candleRef.current;
    const vs = volRef.current;
    if (!cs || !vs || !candles.length) return;
    cs.setData(candles.map((c) => ({ time: c.time as Time, open: c.open, high: c.high, low: c.low, close: c.close })));
    vs.setData(candles.map((c) => ({
      time: c.time as Time, value: c.volume,
      color: c.close >= c.open ? "rgba(22,199,132,0.45)" : "rgba(234,57,67,0.45)",
    })));
    if (!didFitRef.current) {
      chartRef.current?.timeScale().fitContent();
      didFitRef.current = true;
    }
  }, [candles]);

  // Overlay: EMA
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    if (!overlays.ema) {
      [ema50Ref, ema200Ref].forEach((r) => { if (r.current) { try { chart.removeSeries(r.current); } catch { /**/ } r.current = null; } });
      return;
    }
    if (!ema50Ref.current)  ema50Ref.current  = chart.addSeries(LineSeries, { color: "#60a5fa", lineWidth: 2, priceLineVisible: false, lastValueVisible: true, title: "EMA50" });
    if (!ema200Ref.current) ema200Ref.current = chart.addSeries(LineSeries, { color: "#c6c6c7", lineWidth: 2, priceLineVisible: false, lastValueVisible: true, title: "EMA200" });
    if (!indicators) return;
    const s = indicators.series;
    ema50Ref.current.setData(seriesPoints(s.time, s.ema_50, candleTimes));
    ema200Ref.current.setData(seriesPoints(s.time, s.ema_200, candleTimes));
  }, [indicators, overlays.ema, candleTimes]);

  // Overlay: Bollinger
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    if (!overlays.bollinger) {
      [bbUpperRef, bbMiddleRef, bbLowerRef].forEach((r) => { if (r.current) { try { chart.removeSeries(r.current); } catch { /**/ } r.current = null; } });
      return;
    }
    if (!bbUpperRef.current)  bbUpperRef.current  = chart.addSeries(LineSeries, { color: "#a78bfa", lineWidth: 1, priceLineVisible: false, lastValueVisible: false, title: "BB UP" });
    if (!bbMiddleRef.current) bbMiddleRef.current = chart.addSeries(LineSeries, { color: "rgba(167,139,250,0.45)", lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false });
    if (!bbLowerRef.current)  bbLowerRef.current  = chart.addSeries(LineSeries, { color: "#a78bfa", lineWidth: 1, priceLineVisible: false, lastValueVisible: false, title: "BB LO" });
    if (!indicators) return;
    const s = indicators.series;
    bbUpperRef.current.setData(seriesPoints(s.time, s.bb_upper, candleTimes));
    bbMiddleRef.current.setData(seriesPoints(s.time, s.bb_middle, candleTimes));
    bbLowerRef.current.setData(seriesPoints(s.time, s.bb_lower, candleTimes));
  }, [indicators, overlays.bollinger, candleTimes]);

  // Overlay: VWAP
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    if (!overlays.vwap) {
      if (vwapRef.current) { try { chart.removeSeries(vwapRef.current); } catch { /**/ } vwapRef.current = null; }
      return;
    }
    if (!vwapRef.current) vwapRef.current = chart.addSeries(LineSeries, { color: "#14b8a6", lineWidth: 2, priceLineVisible: false, lastValueVisible: true, title: "VWAP" });
    if (!indicators?.series.vwap) return;
    vwapRef.current.setData(seriesPoints(indicators.series.time, indicators.series.vwap, candleTimes));
  }, [indicators, overlays.vwap, candleTimes]);

  // Overlay: OBV (bottom band, own invisible scale)
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    if (!overlays.obv) {
      if (obvRef.current) { try { chart.removeSeries(obvRef.current); } catch { /**/ } obvRef.current = null; }
      return;
    }
    if (!obvRef.current) {
      obvRef.current = chart.addSeries(LineSeries, {
        color: "#e879f9",
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
        title: "OBV",
        priceScaleId: "obv",
      });
      chart.priceScale("obv").applyOptions({
        scaleMargins: { top: 0.90, bottom: 0 },
        visible: false,
      });
    }
    if (!indicators?.series.obv) return;
    obvRef.current.setData(seriesPoints(indicators.series.time, indicators.series.obv, candleTimes));
  }, [indicators, overlays.obv, candleTimes]);

  // Overlay: Ichimoku
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    if (!overlays.ichimoku) {
      [ichiTenRef, ichiKijRef, ichiSaRef, ichiSbRef].forEach((r) => { if (r.current) { try { chart.removeSeries(r.current); } catch { /**/ } r.current = null; } });
      return;
    }
    if (!ichiTenRef.current) ichiTenRef.current = chart.addSeries(LineSeries, { color: "#ef4444", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    if (!ichiKijRef.current) ichiKijRef.current = chart.addSeries(LineSeries, { color: "#3b82f6", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    if (!ichiSaRef.current)  ichiSaRef.current  = chart.addSeries(LineSeries, { color: "rgba(34,197,94,0.85)", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    if (!ichiSbRef.current)  ichiSbRef.current  = chart.addSeries(LineSeries, { color: "rgba(239,68,68,0.85)", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    const s = indicators?.series;
    if (!s) return;
    if (s.ichimoku_tenkan)   ichiTenRef.current.setData(seriesPoints(s.time, s.ichimoku_tenkan));
    if (s.ichimoku_kijun)    ichiKijRef.current.setData(seriesPoints(s.time, s.ichimoku_kijun));
    if (s.ichimoku_senkou_a) ichiSaRef.current.setData(seriesPoints(s.time, s.ichimoku_senkou_a));
    if (s.ichimoku_senkou_b) ichiSbRef.current.setData(seriesPoints(s.time, s.ichimoku_senkou_b));
  }, [indicators, overlays.ichimoku]);

  // Overlay: Std-dev channel
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    if (!overlays.stddevChannel) {
      [sdcUpRef, sdcMidRef, sdcLoRef].forEach((r) => { if (r.current) { try { chart.removeSeries(r.current); } catch { /**/ } r.current = null; } });
      return;
    }
    if (!sdcUpRef.current)  sdcUpRef.current  = chart.addSeries(LineSeries, { color: "#c6c6c7", lineWidth: 1, priceLineVisible: false, lastValueVisible: false, title: "SDC UP" });
    if (!sdcMidRef.current) sdcMidRef.current = chart.addSeries(LineSeries, { color: "rgba(245,158,11,0.55)", lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false });
    if (!sdcLoRef.current)  sdcLoRef.current  = chart.addSeries(LineSeries, { color: "#c6c6c7", lineWidth: 1, priceLineVisible: false, lastValueVisible: false, title: "SDC LO" });
    const s = indicators?.series;
    if (!s) return;
    if (s.stddev_channel_upper)  sdcUpRef.current.setData(seriesPoints(s.time, s.stddev_channel_upper, candleTimes));
    if (s.stddev_channel_middle) sdcMidRef.current.setData(seriesPoints(s.time, s.stddev_channel_middle, candleTimes));
    if (s.stddev_channel_lower)  sdcLoRef.current.setData(seriesPoints(s.time, s.stddev_channel_lower, candleTimes));
  }, [indicators, overlays.stddevChannel, candleTimes]);

  // Overlay: Pivot price lines
  useEffect(() => {
    const cs = candleRef.current;
    if (!cs) return;
    for (const { remove } of pivotLinesRef.current) { try { remove(); } catch { /**/ } }
    pivotLinesRef.current = [];
    if (!overlays.pivots || !indicators?.pivots) return;
    const p = indicators.pivots;
    const entries: Array<[string, number | null | undefined, string]> = [
      ["R2", p.r2, "#ef4444"], ["R1", p.r1, "#f97316"],
      ["P", p.pivot, "#e0e0ff"], ["S1", p.s1, "#60a5fa"], ["S2", p.s2, "#14b8a6"],
    ];
    for (const [label, price, color] of entries) {
      if (price == null || !Number.isFinite(price)) continue;
      const line = cs.createPriceLine({ price, color, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: label });
      pivotLinesRef.current.push({ line, remove: () => cs.removePriceLine(line) });
    }
  }, [indicators, overlays.pivots]);

  // Crosshair OHLC tooltip
  const [hover, setHover] = useState<{ candle: Candle; x: number; y: number } | null>(null);
  useEffect(() => {
    const chart = chartRef.current;
    const cs = candleRef.current;
    if (!chart || !cs) return;
    type Param = Parameters<Parameters<typeof chart.subscribeCrosshairMove>[0]>[0];
    const onMove = (param: Param) => {
      if (!param?.time || !param.point) { setHover(null); return; }
      const data = param.seriesData?.get(cs) as { open?: number; high?: number; low?: number; close?: number } | undefined;
      if (!data || data.open == null) { setHover(null); return; }
      setHover({ candle: { time: Number(param.time), open: data.open!, high: data.high!, low: data.low!, close: data.close!, volume: 0 }, x: param.point.x, y: param.point.y });
    };
    chart.subscribeCrosshairMove(onMove);
    return () => chart.unsubscribeCrosshairMove(onMove);
  }, []);

  const readout = hover?.candle ?? null;
  const readoutIdx = readout ? candles.findIndex((c) => c.time === readout.time) : -1;
  const prevClose = readout && readoutIdx > 0 ? candles[readoutIdx - 1]?.close ?? readout.open : readout?.open ?? 0;
  const delta = readout ? readout.close - prevClose : 0;
  const deltaPct = readout && prevClose ? (delta / prevClose) * 100 : 0;
  const tipW = 180, tipH = 108, pad = 12;
  const boxEl = boxRef.current;
  const w = boxEl?.clientWidth ?? 0;
  const h = boxEl?.clientHeight ?? 0;
  const rawX = hover ? hover.x + pad : 0;
  const rawY = hover ? hover.y + pad : 0;
  const tipX = hover ? (rawX + tipW > w - 8 ? hover.x - tipW - pad : rawX) : 0;
  const tipY = hover ? (rawY + tipH > h - 8 ? hover.y - tipH - pad : rawY) : 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0, position: "relative" }}>
      <div ref={boxRef} style={{ flex: 1, minHeight: 0, position: "relative" }}>
        {overlays.kumoFill && (
          <KumoCloud
            chart={chartRef.current}
            priceSeries={candleRef.current}
            tenkan={indicators?.series.ichimoku_tenkan ?? null}
            kijun={indicators?.series.ichimoku_kijun ?? null}
            senkouA={indicators?.series.ichimoku_senkou_a ?? null}
            senkouB={indicators?.series.ichimoku_senkou_b ?? null}
            time={indicators?.series.time ?? null}
          />
        )}
        {overlays.volumeProfile && (
          <VolumeProfileOverlay
            chart={chartRef.current}
            priceSeries={candleRef.current}
            heatmap={heatmap ?? null}
          />
        )}
      </div>
      {hover && readout ? (
        <div style={{
          position: "absolute",
          left: Math.max(8, Math.min(w - tipW - 8, tipX)),
          top:  Math.max(8, Math.min(h - tipH - 8, tipY)),
          zIndex: 5, width: tipW, padding: "8px 10px",
          background: "var(--surface-container)", border: "1px solid var(--hairline)", borderRadius: 4,
          fontFamily: "var(--font-mono, ui-monospace, monospace)", fontSize: 11, color: "var(--on-surface-variant)",
          backdropFilter: "blur(6px)", pointerEvents: "none", fontVariantNumeric: "tabular-nums",
          display: "grid", gridTemplateColumns: "auto 1fr", rowGap: 3, columnGap: 10,
        }}>
          <span style={{ color: "var(--on-surface-dim)" }}>O</span><span style={{ color: "var(--on-surface)", fontWeight: 600, textAlign: "right" }}>{ohlcFmt(readout.open)}</span>
          <span style={{ color: "var(--on-surface-dim)" }}>H</span><span style={{ color: "var(--on-surface)", fontWeight: 600, textAlign: "right" }}>{ohlcFmt(readout.high)}</span>
          <span style={{ color: "var(--on-surface-dim)" }}>L</span><span style={{ color: "var(--on-surface)", fontWeight: 600, textAlign: "right" }}>{ohlcFmt(readout.low)}</span>
          <span style={{ color: "var(--on-surface-dim)" }}>C</span><span style={{ color: "var(--on-surface)", fontWeight: 600, textAlign: "right" }}>{ohlcFmt(readout.close)}</span>
          <span style={{ color: "var(--on-surface-dim)" }}>Δ</span>
          <span style={{ color: delta >= 0 ? "#16c784" : "#ea3943", fontWeight: 600, textAlign: "right" }}>
            {delta >= 0 ? "+" : ""}{ohlcFmt(delta)} ({deltaPct >= 0 ? "+" : ""}{deltaPct.toFixed(2)}%)
          </span>
          <span style={{ gridColumn: "1 / -1", marginTop: 4, paddingTop: 4, borderTop: "1px solid var(--hairline)", color: "var(--on-surface-dim)", fontSize: 10 }}>
            {new Date(readout.time * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
          </span>
        </div>
      ) : null}
      {overlays.rsi && indicators ? (
        <RsiStrip indicators={indicators} mainChart={chartRef.current} />
      ) : null}
      {overlays.derivativesStrip && derivatives ? (
        <OnChainStrip data={derivatives} mainChart={chartRef.current} />
      ) : null}
    </div>
  );
}

// =============================================================================
// RSI strip - also listens for nexus-theme-change
// =============================================================================
function RsiStrip({ indicators, mainChart }: { indicators: IndicatorSnapshot; mainChart: IChartApi | null }) {
  const boxRef     = useRef<HTMLDivElement | null>(null);
  const chartRef   = useRef<IChartApi | null>(null);
  const seriesRef  = useRef<ISeriesApi<"Line"> | null>(null);
  const smaSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  useEffect(() => {
    if (!boxRef.current) return;
    const savedLight = localStorage.getItem("nexus-theme") === "light";
    const themeOpts  = savedLight ? CHART_THEME_LIGHT : CHART_THEME_DARK;

    const chart = createChart(boxRef.current, {
      ...themeOpts,
      layout: { ...themeOpts.layout, fontFamily: "Inter, system-ui, sans-serif", fontSize: 10 },
      rightPriceScale: { ...themeOpts.rightPriceScale, minimumWidth: PRICE_AXIS_WIDTH },
      timeScale: { ...themeOpts.timeScale, visible: false, rightOffset: 5, barSpacing: 6 },
      crosshair: { mode: CrosshairMode.Normal },
      autoSize: true,
    });
    chartRef.current = chart;

    // Two-line RSI: violet primary + amber SMA(14) signal - divergence between
    // the two reads cleanly. 70/30 levels removed for less clutter; midline kept.
    const s = chart.addSeries(LineSeries, { color: "#a78bfa", lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: "RSI 14" });
    seriesRef.current = s;
    const sma = chart.addSeries(LineSeries, { color: "#c6c6c7", lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: "MA" });
    smaSeriesRef.current = sma;
    s.createPriceLine({ price: 50, color: "rgba(127,127,127,0.35)", lineWidth: 1, lineStyle: 2, axisLabelVisible: false });

    return () => { chart.remove(); chartRef.current = null; };
  }, []);

  // Theme listener for RSI pane
  useEffect(() => {
    const onTheme = (e: Event) => {
      const chart = chartRef.current;
      if (!chart) return;
      const isLight = (e as CustomEvent<{ light: boolean }>).detail.light;
      chart.applyOptions(isLight ? CHART_THEME_LIGHT : CHART_THEME_DARK);
    };
    window.addEventListener("nexus-theme-change", onTheme);
    return () => window.removeEventListener("nexus-theme-change", onTheme);
  }, []);

  // Sync timescale with main chart
  useEffect(() => {
    const rsi = chartRef.current;
    if (!mainChart || !rsi) return;
    let syncingFromMain = false, syncingFromRsi = false;
    const mainTs = mainChart.timeScale();
    const rsiTs  = rsi.timeScale();
    const onMainRange = (range: { from: number; to: number } | null) => {
      if (!range || syncingFromRsi) return;
      syncingFromMain = true;
      try { rsiTs.setVisibleLogicalRange(range); } catch { /**/ }
      syncingFromMain = false;
    };
    const onRsiRange = (range: { from: number; to: number } | null) => {
      if (!range || syncingFromMain) return;
      syncingFromRsi = true;
      try { mainTs.setVisibleLogicalRange(range); } catch { /**/ }
      syncingFromRsi = false;
    };
    mainTs.subscribeVisibleLogicalRangeChange(onMainRange);
    rsiTs.subscribeVisibleLogicalRangeChange(onRsiRange);
    type Param = Parameters<Parameters<typeof mainChart.subscribeCrosshairMove>[0]>[0];
    const onCrosshair = (p: Param) => {
      if (!p?.time || !seriesRef.current) { rsi.clearCrosshairPosition(); return; }
      try { rsi.setCrosshairPosition(NaN, p.time, seriesRef.current); } catch { /**/ }
    };
    mainChart.subscribeCrosshairMove(onCrosshair);
    const seed = () => { const r = mainTs.getVisibleLogicalRange(); if (r) { try { rsiTs.setVisibleLogicalRange(r); } catch { /**/ } } };
    seed(); const id = requestAnimationFrame(seed);
    return () => {
      cancelAnimationFrame(id);
      mainTs.unsubscribeVisibleLogicalRangeChange(onMainRange);
      rsiTs.unsubscribeVisibleLogicalRangeChange(onRsiRange);
      mainChart.unsubscribeCrosshairMove(onCrosshair);
    };
  }, [mainChart]);

  useEffect(() => {
    const s = seriesRef.current;
    const sma = smaSeriesRef.current;
    if (!s || !sma) return;
    const pts = seriesPoints(indicators.series.time, indicators.series.rsi_14);
    s.setData(pts);
    // SMA(14) of RSI - second line drawn for crossovers & divergence cues.
    const N = 14;
    const smaPts: { time: Time; value: number }[] = [];
    if (pts.length >= N) {
      let sum = 0;
      for (let i = 0; i < N; i++) sum += pts[i].value;
      smaPts.push({ time: pts[N - 1].time, value: sum / N });
      for (let i = N; i < pts.length; i++) {
        sum += pts[i].value - pts[i - N].value;
        smaPts.push({ time: pts[i].time, value: sum / N });
      }
    }
    sma.setData(smaPts);
  }, [indicators]);

  return <div ref={boxRef} style={{ height: 110, borderTop: "1px solid var(--hairline)" }} />;
}

// =============================================================================
// Kumo Cloud overlay - canvas painted between Senkou A and B, color by sign
// =============================================================================
function KumoCloud({ chart, priceSeries, tenkan, kijun, senkouA, senkouB, time }: {
  chart: IChartApi | null;
  priceSeries: ISeriesApi<"Candlestick"> | null;
  tenkan:  (number | null)[] | null;
  kijun:   (number | null)[] | null;
  senkouA: (number | null)[] | null;
  senkouB: (number | null)[] | null;
  time:    number[] | null;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    if (!chart || !priceSeries || !canvasRef.current) return;
    const cvs = canvasRef.current;

    const draw = () => {
      const parent = cvs.parentElement;
      if (!parent) return;
      const w = parent.clientWidth;
      const h = parent.clientHeight;
      const dpr = window.devicePixelRatio || 1;
      if (cvs.width !== w * dpr || cvs.height !== h * dpr) {
        cvs.width = w * dpr; cvs.height = h * dpr;
        cvs.style.width = w + "px"; cvs.style.height = h + "px";
      }
      const ctx = cvs.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      if (!senkouA || !senkouB || !time) return;

      const ts = chart.timeScale();
      const nA: { x: number; ya: number; yb: number }[] = [];
      const N = Math.min(time.length, senkouA.length, senkouB.length);
      for (let i = 0; i < N; i++) {
        const a = senkouA[i]; const b = senkouB[i];
        if (a == null || b == null) continue;
        const x = ts.timeToCoordinate(time[i] as Time);
        if (x == null) continue;
        const ya = priceSeries.priceToCoordinate(a);
        const yb = priceSeries.priceToCoordinate(b);
        if (ya == null || yb == null) continue;
        nA.push({ x, ya, yb });
      }
      if (nA.length < 2) return;

      // Segment by sign of (A - B) so each contiguous run gets one fill color.
      const segs: { pts: typeof nA; bullish: boolean }[] = [];
      let cur: typeof nA = [];
      let curBull = nA[0].ya < nA[0].yb;
      for (const p of nA) {
        const bull = p.ya < p.yb;
        if (bull !== curBull && cur.length) {
          segs.push({ pts: cur, bullish: curBull });
          cur = [];
          curBull = bull;
        }
        cur.push(p);
      }
      if (cur.length) segs.push({ pts: cur, bullish: curBull });

      for (const seg of segs) {
        if (seg.pts.length < 2) continue;
        ctx.beginPath();
        ctx.moveTo(seg.pts[0].x, seg.pts[0].ya);
        for (let i = 1; i < seg.pts.length; i++) ctx.lineTo(seg.pts[i].x, seg.pts[i].ya);
        for (let i = seg.pts.length - 1; i >= 0; i--) ctx.lineTo(seg.pts[i].x, seg.pts[i].yb);
        ctx.closePath();
        ctx.fillStyle = seg.bullish ? "rgba(0,212,170,0.16)" : "rgba(255,71,87,0.16)";
        ctx.fill();
      }

      // Senkou A / B / Tenkan / Kijun lines on top of the fill
      const drawLine = (vals: (number | null)[] | null, color: string, lw = 1) => {
        if (!vals) return;
        ctx.beginPath(); ctx.lineWidth = lw; ctx.strokeStyle = color;
        let pen = false;
        for (let i = 0; i < N; i++) {
          const v = vals[i];
          if (v == null) { pen = false; continue; }
          const x = ts.timeToCoordinate(time[i] as Time);
          if (x == null) { pen = false; continue; }
          const y = priceSeries.priceToCoordinate(v);
          if (y == null) { pen = false; continue; }
          if (!pen) { ctx.moveTo(x, y); pen = true; } else ctx.lineTo(x, y);
        }
        ctx.stroke();
      };
      drawLine(senkouA, "rgba(0,212,170,0.55)");
      drawLine(senkouB, "rgba(255,71,87,0.55)");
      drawLine(tenkan,  "#3b82f6");
      drawLine(kijun,   "#ef4444");
    };

    // Event-driven redraw: data change, chart pan/zoom, container resize.
    let pendingRaf: number | null = null;
    const schedule = () => {
      if (pendingRaf != null) return;
      pendingRaf = requestAnimationFrame(() => { pendingRaf = null; draw(); });
    };
    const ts = chart.timeScale();
    ts.subscribeVisibleLogicalRangeChange(schedule);
    const ro = new ResizeObserver(schedule);
    if (cvs.parentElement) ro.observe(cvs.parentElement);
    schedule();
    return () => {
      ts.unsubscribeVisibleLogicalRangeChange(schedule);
      ro.disconnect();
      if (pendingRaf != null) cancelAnimationFrame(pendingRaf);
    };
  }, [chart, priceSeries, tenkan, kijun, senkouA, senkouB, time]);

  return (
    <canvas ref={canvasRef} style={{ position: "absolute", inset: 0, pointerEvents: "none", zIndex: 1 }} />
  );
}

// =============================================================================
// Volume Profile overlay - horizontal histogram pinned to right edge
// =============================================================================
function VolumeProfileOverlay({ chart, priceSeries, heatmap }: {
  chart: IChartApi | null;
  priceSeries: ISeriesApi<"Candlestick"> | null;
  heatmap: HeatmapPayload | null;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    if (!chart || !priceSeries || !canvasRef.current) return;
    const cvs = canvasRef.current;

    const draw = () => {
      const parent = cvs.parentElement;
      if (!parent) return;
      const w = parent.clientWidth;
      const h = parent.clientHeight;
      const dpr = window.devicePixelRatio || 1;
      if (cvs.width !== w * dpr || cvs.height !== h * dpr) {
        cvs.width = w * dpr; cvs.height = h * dpr;
        cvs.style.width = w + "px"; cvs.style.height = h + "px";
      }
      const ctx = cvs.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      const dp = heatmap?.depth_profile;
      if (!dp || !dp.bid_prices || !dp.ask_prices) return;

      const bidLevels: DepthBin[] = (dp.bid_prices || []).map((p, i) => ({ price: p, cumulative: dp.bid_cumulative?.[i] ?? 0 }));
      const askLevels: DepthBin[] = (dp.ask_prices || []).map((p, i) => ({ price: p, cumulative: dp.ask_cumulative?.[i] ?? 0 }));
      const all = [...bidLevels, ...askLevels];
      if (!all.length) return;
      const maxQty = all.reduce((m, b) => Math.max(m, b.cumulative), 0);
      if (!maxQty) return;

      const VP_W = Math.min(120, Math.floor(w * 0.16));
      const xRight = w - 4; // chart right price scale clearance handled by container
      const drawSide = (levels: DepthBin[], color: string) => {
        for (const lvl of levels) {
          const y = priceSeries.priceToCoordinate(lvl.price);
          if (y == null) continue;
          const wPx = Math.max(1, (lvl.cumulative / maxQty) * VP_W);
          ctx.fillStyle = color;
          ctx.fillRect(xRight - wPx, y - 1, wPx, 2);
        }
      };
      drawSide(bidLevels, "rgba(22,199,132,0.45)");
      drawSide(askLevels, "rgba(234,57,67,0.45)");
    };

    let pendingRaf: number | null = null;
    const schedule = () => {
      if (pendingRaf != null) return;
      pendingRaf = requestAnimationFrame(() => { pendingRaf = null; draw(); });
    };
    const ts = chart.timeScale();
    ts.subscribeVisibleLogicalRangeChange(schedule);
    const ro = new ResizeObserver(schedule);
    if (cvs.parentElement) ro.observe(cvs.parentElement);
    schedule();
    return () => {
      ts.unsubscribeVisibleLogicalRangeChange(schedule);
      ro.disconnect();
      if (pendingRaf != null) cancelAnimationFrame(pendingRaf);
    };
  }, [chart, priceSeries, heatmap]);

  return (
    <canvas ref={canvasRef} style={{ position: "absolute", inset: 0, pointerEvents: "none", zIndex: 2 }} />
  );
}

// =============================================================================
// On-chain strip - basis (line), funding (histogram), OI (line); shared scale
// timed against the main chart's time axis
// =============================================================================
function OnChainStrip({ data, mainChart }: { data: DerivativesData; mainChart: IChartApi | null }) {
  const boxRef    = useRef<HTMLDivElement | null>(null);
  const chartRef  = useRef<IChartApi | null>(null);
  const basisRef  = useRef<ISeriesApi<"Line"> | null>(null);
  const fundRef   = useRef<ISeriesApi<"Histogram"> | null>(null);
  const oiRef     = useRef<ISeriesApi<"Line"> | null>(null);

  useEffect(() => {
    if (!boxRef.current) return;
    const savedLight = localStorage.getItem("nexus-theme") === "light";
    const themeOpts  = savedLight ? CHART_THEME_LIGHT : CHART_THEME_DARK;
    const chart = createChart(boxRef.current, {
      ...themeOpts,
      layout: { ...themeOpts.layout, fontFamily: "Inter, system-ui, sans-serif", fontSize: 10 },
      rightPriceScale: { ...themeOpts.rightPriceScale, minimumWidth: PRICE_AXIS_WIDTH },
      timeScale: { ...themeOpts.timeScale, visible: false, rightOffset: 5, barSpacing: 6 },
      crosshair: { mode: CrosshairMode.Normal },
      autoSize: true,
    });
    chartRef.current = chart;
    basisRef.current = chart.addSeries(LineSeries, { color: "#60a5fa", lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: "BASIS%", priceScaleId: "right" });
    fundRef.current  = chart.addSeries(HistogramSeries, { priceFormat: { type: "price", precision: 4, minMove: 0.0001 }, priceScaleId: "fund", title: "FUND" });
    chart.priceScale("fund").applyOptions({ scaleMargins: { top: 0.55, bottom: 0 } });
    oiRef.current    = chart.addSeries(LineSeries, { color: "#e879f9", lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: "OI", priceScaleId: "oi" });
    chart.priceScale("oi").applyOptions({ scaleMargins: { top: 0, bottom: 0.55 }, visible: false });
    return () => { chart.remove(); chartRef.current = null; };
  }, []);

  useEffect(() => {
    const onTheme = (e: Event) => {
      const chart = chartRef.current;
      if (!chart) return;
      const isLight = (e as CustomEvent<{ light: boolean }>).detail.light;
      chart.applyOptions(isLight ? CHART_THEME_LIGHT : CHART_THEME_DARK);
    };
    window.addEventListener("nexus-theme-change", onTheme);
    return () => window.removeEventListener("nexus-theme-change", onTheme);
  }, []);

  useEffect(() => {
    const c = chartRef.current;
    if (!mainChart || !c) return;
    const a = mainChart.timeScale(), b = c.timeScale();
    let lockA = false, lockB = false;
    const onA = (r: { from: number; to: number } | null) => {
      if (!r || lockB) return;
      lockA = true; try { b.setVisibleLogicalRange(r); } catch { /**/ } lockA = false;
    };
    const onB = (r: { from: number; to: number } | null) => {
      if (!r || lockA) return;
      lockB = true; try { a.setVisibleLogicalRange(r); } catch { /**/ } lockB = false;
    };
    a.subscribeVisibleLogicalRangeChange(onA);
    b.subscribeVisibleLogicalRangeChange(onB);
    const seed = () => { const r = a.getVisibleLogicalRange(); if (r) { try { b.setVisibleLogicalRange(r); } catch { /**/ } } };
    seed(); const id = requestAnimationFrame(seed);
    return () => {
      cancelAnimationFrame(id);
      a.unsubscribeVisibleLogicalRangeChange(onA);
      b.unsubscribeVisibleLogicalRangeChange(onB);
    };
  }, [mainChart]);

  useEffect(() => {
    // lightweight-charts requires strictly ascending unique timestamps.
    // Tracker priming can produce same-second duplicates → dedupe (last wins) + sort.
    const dedupeAsc = (pts: SeriesPoint[]): SeriesPoint[] => {
      const m = new Map<number, number>();
      for (const p of pts) {
        if (!Number.isFinite(p.time) || !Number.isFinite(p.value)) continue;
        m.set(Math.floor(p.time), p.value);
      }
      return Array.from(m.entries())
        .sort((a, b) => a[0] - b[0])
        .map(([time, value]) => ({ time, value }));
    };
    const basis = dedupeAsc(data.basis);
    const fund  = dedupeAsc(data.funding);
    const oi    = dedupeAsc(data.oi);
    if (basisRef.current) basisRef.current.setData(basis.map((p) => ({ time: p.time as Time, value: p.value })));
    if (fundRef.current)  fundRef.current.setData(fund.map((p) => ({
      time: p.time as Time, value: p.value,
      color: p.value >= 0 ? "rgba(0,212,170,0.7)" : "rgba(255,71,87,0.7)",
    })));
    if (oiRef.current)    oiRef.current.setData(oi.map((p) => ({ time: p.time as Time, value: p.value })));
  }, [data]);

  return <div ref={boxRef} style={{ height: 110, borderTop: "1px solid var(--hairline)" }} />;
}

// =============================================================================
// Right-panel subcomponents
// =============================================================================
function TickCell({ label, value, tone }: { label: string; value: string; tone?: "bull" | "bear" | "on" }) {
  const color = tone === "bull" ? "var(--chart-bull)" : tone === "bear" ? "var(--chart-bear)" : tone === "on" ? "var(--on-surface)" : "var(--on-surface-variant)";
  return (
    <span className="flex items-baseline gap-1" style={{ flexShrink: 0 }}>
      <span style={{ color: "var(--on-surface-dim)", fontSize: 9, letterSpacing: "0.12em" }}>{label}</span>
      <span style={{ color, fontWeight: 700 }}>{value}</span>
    </span>
  );
}

function compact(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1e9) return (n / 1e9).toFixed(2) + "B";
  if (abs >= 1e6) return (n / 1e6).toFixed(2) + "M";
  if (abs >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return n.toFixed(0);
}

// =============================================================================
// Helpers
// =============================================================================
/**
 * Build a Lightweight-Charts point list from an indicator value array.
 *
 * Pan/zoom alignment matters: every overlay (EMA, BB, VWAP, Ichimoku, SDC, OBV)
 * is plotted by *time* - if its time array is even a millisecond off from the
 * candle's close_time, the overlay floats. The backend should align indicator
 * timestamps to klines, but networks/clocks slip. When the caller passes the
 * canonical candle-time array AND its length equals values.length, we anchor
 * the points to the candle grid - guaranteed alignment under pan/zoom. We
 * fall back to the indicator-supplied times otherwise (warmup truncation,
 * deliberate offset like Ichimoku Senkou).
 */
function seriesPoints(
  times: number[],
  values: (number | null)[],
  candleTimes?: number[],
): { time: Time; value: number }[] {
  const useTimes =
    candleTimes && candleTimes.length === values.length ? candleTimes : times;
  const out: { time: Time; value: number }[] = [];
  const n = Math.min(useTimes.length, values.length);
  for (let i = 0; i < n; i++) {
    const v = values[i];
    if (v == null || !Number.isFinite(v)) continue;
    out.push({ time: useTimes[i] as Time, value: v });
  }
  return out;
}

function ohlcFmt(n: number): string {
  if (!isFinite(n)) return "-";
  const abs = Math.abs(n);
  const digits = abs < 1 ? 5 : abs < 100 ? 3 : 2;
  return n.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}