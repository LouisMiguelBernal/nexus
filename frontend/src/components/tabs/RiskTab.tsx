"use client";

/**
 * Nexus - Risk Layer (Layer 4 of the institutional 5-layer hierarchy)
 *
 * Unified advisory-only risk panel. Lifts Kelly + F&G out of Research/Alerts
 * and adds the 3-method VaR ensemble + circuit-breaker strip on the extended
 * /api/health payload. ZERO order-execution controls - read-only by design.
 */

import { useEffect, useRef, useState } from "react";
import { usePolling } from "@/lib/usePolling";
import ParticleField from "@/components/ParticleField";
import AdvisoryNotice from "@/components/AdvisoryNotice";

interface Props {
  symbol: string;
  api: string;
}

interface KellyResp {
  recommended_position_pct?: number;
  recommended_position_usd?: number;
  kelly_fraction?: number;
  half_kelly_fraction?: number;
  vol_adjusted?: boolean;
  correlation_penalty?: number;
  capped_reason?: string | null;
  notes?: string[];
  warmup?: boolean;
  samples?: number;
  needed?: number;
  reason?: string;
  realized_stats?: {
    win_rate: number;
    avg_win_pct: number;
    avg_loss_pct: number;
    atr_pct: number | null;
    realized_vol_24h_pct: number | null;
    samples: number;
  };
}

interface VarLevel {
  return_pct: number;
  usd_loss: number;
  unleveraged_pct: number;
  confidence?: number;
}

interface VarMethod {
  var_95?: VarLevel;
  var_99?: VarLevel;
}

interface VarResp {
  symbol?: string;
  samples?: number;
  error?: string;
  historical?: VarMethod;
  monte_carlo?: VarMethod;
  parametric?: VarMethod;
  ensemble_max?: VarMethod;
  stressed_var?: { return_pct: number; usd_loss: number } | null;
  liquidation_risk?: {
    probability_horizon: number;
    threshold_pct: number;
    leverage: number;
  };
  inputs?: { n_returns: number; mc_paths: number; ewma_lambda: number };
}

interface HealthResp {
  circuit_breaker?: {
    triggered: boolean;
    trigger_reason: string;
    daily_loss_pct: number;
    weekly_loss_pct: number;
    drawdown_from_peak_pct: number;
    leverage_reduced: boolean;
    signals_suppressed: boolean;
    reset_time: string;
  };
  circuit_breaker_events?: Array<{ ts: number; kind: string; detail: string }>;
  event_bus_recent?: Array<{ ts: number; topic: string; payload: Record<string, unknown> }>;
}

export default function RiskTab({ symbol, api }: Props) {
  const { data: kelly, loading: kLoading } = usePolling<KellyResp>({
    url: `${api}/api/risk/kelly/${symbol}`,
    intervalMs: 30_000,
  });

  const { data: varData, loading: vLoading, error: vErr } = usePolling<VarResp>({
    url: `${api}/api/risk/var/${symbol}?position_usd=10000&leverage=5&lookback=200`,
    intervalMs: 30_000,
  });

  const { data: health } = usePolling<HealthResp>({
    url: `${api}/api/health`,
    intervalMs: 5_000,
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, height: "100%", minHeight: 0 }}>
      <AdvisoryNotice message="Read-only intelligence. Position-sizing, VaR, stressed-tail and circuit-breaker outputs are statistical estimates - not investment advice or order instructions. Ensemble VaR uses the worst-of-three methods as the Kelly denominator; stressed VaR is the empirical mean of the worst 5% of returns." />

      {/* Row 1: Kelly | VaR Distribution */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1.65fr", gap: 12, flex: "0 0 auto" }}>
        <Panel title="POSITION SIZER (Kelly)">
          {kLoading && !kelly ? (
            <Loading />
          ) : kelly?.warmup ? (
            <Empty>WARMUP {kelly.samples ?? 0}/{kelly.needed ?? 30} bars · realized stats unavailable</Empty>
          ) : kelly ? (
            <>
            <Grid>
              <KV k="Recommended %" v={fmtPct(kelly.recommended_position_pct)} />
              <KV k="Recommended $" v={fmtUsd(kelly.recommended_position_usd)} />
              <KV k="Half-Kelly" v={fmtPct((kelly.half_kelly_fraction ?? 0) * 100)} />
              <KV k="Vol-adjusted" v={kelly.vol_adjusted ? "yes" : "no"} />
              <KV k="ρ penalty" v={fmtPct((kelly.correlation_penalty ?? 0) * 100)} />
              <KV k="Cap" v={kelly.capped_reason || "-"} />
              {kelly.realized_stats ? (
                <>
                  <KV k="Win-rate (real)" v={fmtPct((kelly.realized_stats.win_rate ?? 0) * 100)} />
                  <KV k="Avg win %" v={fmtPct(kelly.realized_stats.avg_win_pct)} />
                  <KV k="Avg loss %" v={fmtPct(kelly.realized_stats.avg_loss_pct)} />
                  <KV k="ATR %" v={kelly.realized_stats.atr_pct === null ? "-" : fmtPct(kelly.realized_stats.atr_pct)} />
                  <KV k="RV 24h %" v={kelly.realized_stats.realized_vol_24h_pct === null ? "-" : fmtPct(kelly.realized_stats.realized_vol_24h_pct)} />
                  <KV k="Samples" v={String(kelly.realized_stats.samples)} />
                </>
              ) : null}
            </Grid>
            <KellyFractionBar kelly={kelly} />
            </>
          ) : (
            <Empty>kelly unavailable</Empty>
          )}
        </Panel>

        <Panel title="VaR ENSEMBLE · DISTRIBUTION">
          {vLoading && !varData ? (
            <Loading />
          ) : varData?.error ? (
            <Empty>{varData.error}</Empty>
          ) : vErr ? (
            <Empty>{vErr}</Empty>
          ) : varData ? (
            <>
              <VarBand data={varData} />
              <VarMethodBars data={varData} />
              <VarTable data={varData} />
            </>
          ) : (
            <Empty>no var data</Empty>
          )}
        </Panel>
      </div>

      {/* Row 2: Market Stress Index | Circuit Breaker */}
      <div style={{ display: "grid", gridTemplateColumns: "1.65fr 1fr", gap: 12, flex: "0 0 auto" }}>
        <Panel title="MARKET STRESS INDEX">
          <StressIndex varData={varData ?? null} health={health || null} />
        </Panel>

        <Panel title="CIRCUIT BREAKER">
          <BreakerStrip health={health || null} />
        </Panel>
      </div>

      {/* Row 3: Stressed VaR Tail | Liquidation | Drawdown */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, flex: "0 0 auto" }}>
        <Panel title="STRESSED VaR · TAIL">
          <StressedTail data={varData ?? null} />
        </Panel>
        <Panel title="LIQUIDATION RISK">
          <LiquidationGauge data={varData ?? null} />
        </Panel>
        <Panel title="DRAWDOWN PULSE">
          <DrawdownPulse health={health || null} />
        </Panel>
      </div>

      {/* Open-space flow field */}
      <FieldPanel title="RISK PULSE FIELD" caption="ambient · advisory only">
        <ParticleField mode="flow" intensity={0.55} density={0.55} edgeToEdge />
      </FieldPanel>
    </div>
  );
}

// ── Shared visual primitives ──────────────────────────────────────────────────

/**
 * SparkLine - inline SVG mini time-series.
 * values: last N readings (left=oldest, right=newest).
 * Dot at the latest point; optional fill area beneath.
 */
function SparkLine({
  values,
  color,
  width = 88,
  height = 26,
  fill = false,
}: {
  values: number[];
  color: string;
  width?: number;
  height?: number;
  fill?: boolean;
}) {
  if (values.length < 2) {
    return (
      <svg width={width} height={height}>
        <line x1={0} y1={height / 2} x2={width} y2={height / 2} stroke="rgba(127,127,127,0.2)" strokeWidth={1} strokeDasharray="2 3" />
      </svg>
    );
  }
  const mn = Math.min(...values);
  const mx = Math.max(...values);
  const range = mx - mn || 0.0001;
  const pad = 3;
  const usableH = height - pad * 2;
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * width;
    const y = pad + usableH - ((v - mn) / range) * usableH;
    return [x, y] as [number, number];
  });
  const polyline = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const [lx, ly] = pts[pts.length - 1];
  const fillPath = fill
    ? `M ${pts[0][0].toFixed(1)},${height} L ${polyline.replace(/(\d+\.\d+,\d+\.\d+)/g, (m) => m)} L ${lx.toFixed(1)},${height} Z`
    : "";

  return (
    <svg width={width} height={height} style={{ overflow: "visible", display: "block" }}>
      {fill && (
        <path d={fillPath} fill={color} opacity={0.12} />
      )}
      <polyline points={polyline} fill="none" stroke={color} strokeWidth={1.5} opacity={0.85} strokeLinejoin="round" />
      <circle cx={lx} cy={ly} r={2.5} fill={color} />
    </svg>
  );
}

/**
 * StressArcGauge - SVG semicircular gauge 0-100.
 * Zone bands: 0-25 green · 25-50 silver · 50-70 silver · 70-100 red
 * Arc opens at the bottom (speedometer style), 270° sweep.
 */
function StressArcGauge({ score, color }: { score: number; color: string }) {
  const cx = 70, cy = 78, r = 54;
  // Start 225° (lower-left), sweep 270° CW → ends at 135° (lower-right).
  const START_DEG = 225;
  const SWEEP = 270;

  function arcD(fromDeg: number, toDeg: number, radius: number = r) {
    // Clockwise arc from fromDeg to toDeg.
    const sf = (deg: number) => {
      const rad = (deg * Math.PI) / 180;
      return { x: cx + radius * Math.cos(rad), y: cy + radius * Math.sin(rad) };
    };
    const s = sf(fromDeg);
    const e = sf(toDeg);
    let sweep = ((toDeg - fromDeg) + 360) % 360;
    if (sweep === 0) sweep = 360;
    const largeArc = sweep > 180 ? 1 : 0;
    return `M ${s.x.toFixed(2)} ${s.y.toFixed(2)} A ${radius} ${radius} 0 ${largeArc} 1 ${e.x.toFixed(2)} ${e.y.toFixed(2)}`;
  }

  // Zone background arcs (25/25/20/30 → % of 270°)
  const zones: Array<{ from: number; to: number; col: string }> = [
    { from: 0, to: 25, col: "rgba(22,199,132,0.18)" },
    { from: 25, to: 50, col: "rgba(198,198,199,0.12)" },
    { from: 50, to: 70, col: "rgba(198,198,199,0.12)" },
    { from: 70, to: 100, col: "rgba(234,57,67,0.18)" },
  ];

  // Fill arc
  const clampedScore = Math.max(0, Math.min(100, score));
  const fillSweep = (clampedScore / 100) * SWEEP;
  const fillEnd = START_DEG + fillSweep;

  // Tick angles for zone boundaries (at 25, 50, 70)
  const tickDeg = (pct: number) => START_DEG + (pct / 100) * SWEEP;
  const ticks = [25, 50, 70].map(tickDeg);

  return (
    <svg width={140} height={90} viewBox="0 0 140 90" style={{ overflow: "hidden" }}>
      {/* Zone background segments */}
      {zones.map((z) => (
        <path
          key={z.from}
          d={arcD(tickDeg(z.from), tickDeg(z.to), r)}
          fill="none"
          stroke={z.col}
          strokeWidth={12}
          strokeLinecap="butt"
        />
      ))}
      {/* Gray full background arc */}
      <path
        d={arcD(START_DEG, START_DEG + SWEEP - 0.1)}
        fill="none"
        stroke="rgba(127,127,127,0.13)"
        strokeWidth={9}
        strokeLinecap="round"
      />
      {/* Fill arc */}
      {clampedScore > 0 && (
        <path
          d={arcD(START_DEG, fillEnd)}
          fill="none"
          stroke={color}
          strokeWidth={9}
          strokeLinecap="round"
          style={{ filter: `drop-shadow(0 0 5px ${color}99)` }}
        />
      )}
      {/* Zone tick marks */}
      {ticks.map((deg) => {
        const outerPt = (() => {
          const rad = (deg * Math.PI) / 180;
          return { x: cx + (r + 7) * Math.cos(rad), y: cy + (r + 7) * Math.sin(rad) };
        })();
        const innerPt = (() => {
          const rad = (deg * Math.PI) / 180;
          return { x: cx + (r - 10) * Math.cos(rad), y: cy + (r - 10) * Math.sin(rad) };
        })();
        return (
          <line
            key={deg}
            x1={innerPt.x.toFixed(2)}
            y1={innerPt.y.toFixed(2)}
            x2={outerPt.x.toFixed(2)}
            y2={outerPt.y.toFixed(2)}
            stroke="rgba(127,127,127,0.40)"
            strokeWidth={1}
          />
        );
      })}
      {/* Score text */}
      <text
        x={cx}
        y={cy - 4}
        textAnchor="middle"
        dominantBaseline="middle"
        fill={color}
        fontSize={28}
        fontWeight={700}
        fontFamily="var(--font-mono, monospace)"
        style={{ filter: `drop-shadow(0 0 8px ${color}66)` }}
      >
        {score}
      </text>
      {/* Zone labels - small, anchored near arc ends */}
      <text x={14} y={82} textAnchor="middle" fill="rgba(127,127,127,0.40)" fontSize={7.5}>0</text>
      <text x={126} y={82} textAnchor="middle" fill="rgba(127,127,127,0.40)" fontSize={7.5}>100</text>
      <text x={cx} y={20} textAnchor="middle" fill="rgba(127,127,127,0.35)" fontSize={7}>STRESS</text>
    </svg>
  );
}

// ── Market Stress Index ───────────────────────────────────────────────────────
function StressIndex({ varData, health }: { varData: VarResp | null; health: HealthResp | null }) {
  const [nowSec, setNowSec] = useState<number>(() => Date.now() / 1000);
  useEffect(() => {
    const id = setInterval(() => setNowSec(Date.now() / 1000), 10_000);
    return () => clearInterval(id);
  }, []);

  // History buffer - appended in an effect whenever inputs change, read for sparklines
  const [hist, setHist] = useState<{ score: number[]; disp: number[]; evt: number[]; dd: number[] }>({
    score: [], disp: [], evt: [], dd: [],
  });

  // ── dispersion (0-1): spread of 3 VaR estimators at 95% ──────────────────
  let dispersion: number | null = null;
  if (varData) {
    const pts: number[] = [];
    if (varData.historical?.var_95) pts.push(varData.historical.var_95.return_pct);
    if (varData.parametric?.var_95) pts.push(varData.parametric.var_95.return_pct);
    if (varData.monte_carlo?.var_95) pts.push(varData.monte_carlo.var_95.return_pct);
    if (pts.length >= 2) {
      const mn = Math.min(...pts), mx = Math.max(...pts);
      const span = Math.abs(mx - mn);
      const center = Math.max(0.001, (Math.abs(mn) + Math.abs(mx)) / 2);
      dispersion = Math.max(0, Math.min(1, span / (center * 0.5)));
    }
  }

  // ── event pressure (0-1): count of risk events in last 1h ────────────────
  const recentEvents = [
    ...(health?.circuit_breaker_events ?? []),
    ...(health?.event_bus_recent ?? []),
  ].filter((e) => typeof e.ts === "number" && nowSec - e.ts < 3600);
  const eventPressure = Math.max(0, Math.min(1, recentEvents.length / 10));

  // ── drawdown (0-1): current drawdown from peak ────────────────────────────
  const ddPct = Math.abs(Number(health?.circuit_breaker?.drawdown_from_peak_pct ?? 0));
  const drawdown = Math.max(0, Math.min(1, ddPct / 10));

  const components: Array<{ k: string; short: string; v: number | null; w: number; color: string }> = [
    { k: "Method dispersion",  short: "DISP",  v: dispersion,     w: 40, color: "var(--primary)" },
    { k: "Event pressure",     short: "EVENTS", v: eventPressure,  w: 35, color: "#c6c6c7" },
    { k: "Drawdown intensity", short: "DD",     v: drawdown,       w: 25, color: "var(--chart-bear)" },
  ];

  const valid = components.filter((c) => c.v !== null);
  const totalW = valid.reduce((s, c) => s + c.w, 0);
  const score = valid.length === 0
    ? null
    : Math.round(valid.reduce((s, c) => s + (c.v as number) * c.w, 0) / totalW * 100);

  // Push to history buffer (max 40 readings). Latest derived values are
  // mirrored into a ref after each render; a 10s sampler appends them to
  // state - render stays pure and setState only fires from the timer.
  const latestRef = useRef<{ score: number | null; disp: number; evt: number; dd: number }>({
    score: null, disp: 0, evt: 0, dd: 0,
  });
  useEffect(() => {
    latestRef.current = {
      score,
      disp: Math.round((dispersion ?? 0) * 100),
      evt:  Math.round(eventPressure * 100),
      dd:   Math.round(drawdown * 100),
    };
  });
  useEffect(() => {
    const sample = () => {
      const l = latestRef.current;
      if (l.score === null) return;
      setHist((h) => ({
        score: [...h.score, l.score as number].slice(-40),
        disp:  [...h.disp,  l.disp].slice(-40),
        evt:   [...h.evt,   l.evt].slice(-40),
        dd:    [...h.dd,    l.dd].slice(-40),
      }));
    };
    const t = setTimeout(sample, 0);
    const id = setInterval(sample, 10_000);
    return () => { clearTimeout(t); clearInterval(id); };
  }, []);

  if (score === null) {
    return <Empty>warming up - stress signals not ready</Empty>;
  }

  let label: string;
  let color: string;
  if (score >= 70)      { label = "EXTREME STRESS"; color = "var(--chart-bear)"; }
  else if (score >= 50) { label = "ELEVATED";        color = "var(--primary)"; }
  else if (score >= 25) { label = "GUARDED";          color = "var(--on-surface)"; }
  else                  { label = "BENIGN";            color = "var(--chart-bull)"; }

  return (
    <div style={{ display: "flex", gap: 20, alignItems: "flex-start" }}>
      {/* Arc gauge */}
      <div style={{ flexShrink: 0 }}>
        <StressArcGauge score={score} color={color} />
        <div
          style={{
            textAlign: "center",
            fontSize: 10,
            letterSpacing: "0.16em",
            color,
            fontWeight: 700,
            marginTop: -4,
          }}
        >
          {label}
        </div>
      </div>

      {/* Component detail + sparklines */}
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 12, paddingTop: 6 }}>
        {/* Score sparkline */}
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 3 }}>
            <span style={{ fontSize: 9, letterSpacing: "0.14em", color: "var(--on-surface-dim)" }}>STRESS HISTORY</span>
            <span className="text-mono" style={{ fontSize: 10, fontWeight: 700, color }}>{score}/100</span>
          </div>
          <SparkLine values={hist.score} color={color} width={180} height={28} fill />
        </div>

        {/* Component trio */}
        <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
          {components.map((c) => {
            const series = c.short === "DISP" ? hist.disp : c.short === "EVENTS" ? hist.evt : hist.dd;
            const val = c.v == null ? "-" : `${Math.round(c.v * 100)}`;
            const barW = c.v == null ? 0 : c.v * 100;
            return (
              <div key={c.k}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 2 }}>
                  <span style={{ fontSize: 9, letterSpacing: "0.10em", color: "var(--on-surface-dim)" }}>{c.k.toUpperCase()}</span>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <SparkLine values={series} color={c.color} width={56} height={14} />
                    <span className="text-mono" style={{ fontSize: 10, fontWeight: 600, color: c.v == null ? "var(--on-surface-muted)" : "var(--on-surface-variant)", width: 22, textAlign: "right" }}>{val}</span>
                  </div>
                </div>
                <div style={{ height: 3, background: "rgba(127,127,127,0.10)", borderRadius: 1.5, overflow: "hidden" }}>
                  <div style={{ width: `${barW}%`, height: "100%", background: c.color, borderRadius: 1.5, transition: "width 400ms ease", opacity: 0.75 }} />
                </div>
              </div>
            );
          })}
        </div>

        {/* Event count badge */}
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ fontSize: 9, color: "var(--on-surface-muted)", letterSpacing: "0.10em" }}>
            {recentEvents.length} event{recentEvents.length !== 1 ? "s" : ""} in last 1h
          </span>
          {(health?.circuit_breaker?.triggered) && (
            <span style={{ fontSize: 9, letterSpacing: "0.12em", color: "var(--chart-bear)", fontWeight: 700, padding: "1px 5px", border: "1px solid var(--chart-bear)", borderRadius: 2 }}>
              BREAKER TRIPPED
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

// ── VaR method bar chart ──────────────────────────────────────────────────────
// Horizontal bars, one row per method. Inner bar = 95%, outer fade = 99%.
// Lengths are proportional to absolute loss magnitude.
function VarMethodBars({ data }: { data: VarResp }) {
  const methods = [
    { name: "HIST",  v95: data.historical?.var_95?.return_pct,    v99: data.historical?.var_99?.return_pct,   isEnsemble: false },
    { name: "PAR-T", v95: data.parametric?.var_95?.return_pct,    v99: data.parametric?.var_99?.return_pct,   isEnsemble: false },
    { name: "MC",    v95: data.monte_carlo?.var_95?.return_pct,   v99: data.monte_carlo?.var_99?.return_pct,  isEnsemble: false },
    { name: "ENS",   v95: data.ensemble_max?.var_95?.return_pct,  v99: data.ensemble_max?.var_99?.return_pct, isEnsemble: true  },
  ];
  const allVals = methods.flatMap((m) => [m.v95, m.v99]).filter((v) => v != null) as number[];
  if (allVals.length === 0) return null;
  const maxAbs = Math.max(...allVals.map(Math.abs), 0.001);

  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ fontSize: 9, letterSpacing: "0.14em", color: "var(--on-surface-dim)", marginBottom: 5 }}>
        METHOD COMPARISON · LOSS MAGNITUDE
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        {methods.map((m) => {
          const bar95 = m.v95 != null ? (Math.abs(m.v95) / maxAbs) * 100 : 0;
          const bar99 = m.v99 != null ? (Math.abs(m.v99) / maxAbs) * 100 : 0;
          return (
            <div key={m.name} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span
                style={{
                  width: 36,
                  fontSize: 9,
                  letterSpacing: "0.06em",
                  textAlign: "right",
                  color: m.isEnsemble ? "var(--primary)" : "var(--on-surface-dim)",
                  fontWeight: m.isEnsemble ? 700 : 400,
                }}
              >
                {m.name}
              </span>
              <div style={{ flex: 1, position: "relative", height: 14, background: "rgba(127,127,127,0.07)", borderRadius: 2 }}>
                {/* 99% ghost bar */}
                {bar99 > 0 && (
                  <div
                    style={{
                      position: "absolute",
                      left: 0, top: 0, bottom: 0,
                      width: `${bar99}%`,
                      background: m.isEnsemble ? "rgba(198,198,199,0.15)" : "rgba(234,57,67,0.14)",
                      borderRadius: 2,
                    }}
                  />
                )}
                {/* 95% primary bar */}
                {bar95 > 0 && (
                  <div
                    style={{
                      position: "absolute",
                      left: 0, top: 2, bottom: 2,
                      width: `${bar95}%`,
                      background: m.isEnsemble
                        ? "linear-gradient(90deg, rgba(198,198,199,0.8) 0%, rgba(198,198,199,0.45) 100%)"
                        : "linear-gradient(90deg, rgba(234,57,67,0.65) 0%, rgba(234,57,67,0.30) 100%)",
                      borderRadius: 2,
                    }}
                  />
                )}
                {/* Ensemble glow line */}
                {m.isEnsemble && bar95 > 0 && (
                  <div
                    style={{
                      position: "absolute",
                      left: `${bar95}%`,
                      top: -1, bottom: -1,
                      width: 2,
                      background: "var(--primary)",
                      boxShadow: "0 0 5px rgba(198,198,199,0.7)",
                      transform: "translateX(-50%)",
                    }}
                  />
                )}
              </div>
              <span
                className="text-mono"
                style={{
                  width: 44,
                  fontSize: 10,
                  textAlign: "right",
                  color: m.isEnsemble ? "var(--primary)" : "var(--on-surface-variant)",
                  fontWeight: m.isEnsemble ? 700 : 500,
                }}
              >
                {m.v95 != null ? `${m.v95.toFixed(1)}%` : "-"}
              </span>
            </div>
          );
        })}
      </div>
      <div style={{ display: "flex", gap: 14, marginTop: 4, marginLeft: 42, fontSize: 9, color: "var(--on-surface-muted)" }}>
        <span>■ 95% VaR</span>
        <span style={{ opacity: 0.55 }}>■ 99% VaR (ghost)</span>
        <span style={{ color: "var(--primary)", opacity: 0.8 }}>| Kelly denom</span>
      </div>
    </div>
  );
}

function VarTable({ data }: { data: VarResp }) {
  const rows: Array<{ method: string; v95?: VarLevel; v99?: VarLevel; isEnsemble?: boolean }> = [
    { method: "Historical",    v95: data.historical?.var_95,  v99: data.historical?.var_99 },
    { method: "Parametric-t",  v95: data.parametric?.var_95,  v99: data.parametric?.var_99 },
    { method: "Monte Carlo",   v95: data.monte_carlo?.var_95, v99: data.monte_carlo?.var_99 },
    { method: "Ensemble (max)", v95: data.ensemble_max?.var_95, v99: data.ensemble_max?.var_99, isEnsemble: true },
  ];

  return (
    <table style={{ width: "100%", fontSize: 11, borderCollapse: "collapse" }}>
      <thead>
        <tr style={{ color: "var(--on-surface-dim)", textAlign: "right" }}>
          <th style={{ textAlign: "left", padding: "4px 6px" }}>METHOD</th>
          <th style={{ padding: "4px 6px" }}>VaR 95%</th>
          <th style={{ padding: "4px 6px" }}>USD</th>
          <th style={{ padding: "4px 6px" }}>VaR 99%</th>
          <th style={{ padding: "4px 6px" }}>USD</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr
            key={r.method}
            style={{
              color: r.isEnsemble ? "var(--primary)" : "var(--on-surface)",
              fontWeight: r.isEnsemble ? 700 : 400,
              borderTop: "1px solid var(--hairline)",
              background: r.isEnsemble ? "rgba(198,198,199,0.04)" : "transparent",
            }}
          >
            <td style={{ padding: "5px 6px" }}>{r.method}</td>
            <td style={{ padding: "5px 6px", textAlign: "right" }}>{fmtPct(r.v95?.return_pct)}</td>
            <td style={{ padding: "5px 6px", textAlign: "right" }}>{fmtUsd(r.v95?.usd_loss)}</td>
            <td style={{ padding: "5px 6px", textAlign: "right" }}>{fmtPct(r.v99?.return_pct)}</td>
            <td style={{ padding: "5px 6px", textAlign: "right" }}>{fmtUsd(r.v99?.usd_loss)}</td>
          </tr>
        ))}
        {data.stressed_var ? (
          <tr style={{ color: "var(--chart-bear)", fontWeight: 700, borderTop: "1px solid var(--hairline)" }}>
            <td style={{ padding: "5px 6px" }}>Stressed (mean worst 5%)</td>
            <td style={{ padding: "5px 6px", textAlign: "right" }} colSpan={2}>
              {fmtPct(data.stressed_var.return_pct)} · {fmtUsd(data.stressed_var.usd_loss)}
            </td>
            <td style={{ padding: "5px 6px", textAlign: "right", color: "var(--on-surface-dim)", fontWeight: 400 }} colSpan={2}>
              empirical tail
            </td>
          </tr>
        ) : null}
      </tbody>
    </table>
  );
}

// ── VaR distribution band ─────────────────────────────────────────────────────
function VarBand({ data }: { data: VarResp }) {
  const pts: Array<{ name: string; v: number; isEnsemble?: boolean }> = [];
  if (data.historical?.var_95) pts.push({ name: "Hist", v: data.historical.var_95.return_pct });
  if (data.parametric?.var_95) pts.push({ name: "Par-t", v: data.parametric.var_95.return_pct });
  if (data.monte_carlo?.var_95) pts.push({ name: "MC", v: data.monte_carlo.var_95.return_pct });
  const ens = data.ensemble_max?.var_95?.return_pct;
  if (pts.length < 2 || ens == null) return null;

  const all = pts.map((p) => p.v);
  const minV = Math.min(...all, ens);
  const maxV = Math.max(...all, ens);
  const range = Math.abs(maxV - minV) || 0.01;
  const pad = range * 0.15;
  const lo = minV - pad;
  const hi = maxV + pad;
  const span = hi - lo || 1;
  const x = (v: number) => ((v - lo) / span) * 100;

  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, letterSpacing: "0.14em", color: "var(--on-surface-dim)", marginBottom: 4 }}>
        <span>WORST {fmtPct(lo)}</span>
        <span>METHOD DISPERSION · 95% VaR</span>
        <span>BEST {fmtPct(hi)}</span>
      </div>
      <div
        style={{
          position: "relative",
          height: 22,
          background: "linear-gradient(90deg, rgba(234,57,67,0.20) 0%, rgba(198,198,199,0.10) 50%, rgba(22,199,132,0.20) 100%)",
          border: "1px solid var(--hairline)",
          borderRadius: 2,
        }}
      >
        {pts.map((p) => (
          <div
            key={p.name}
            title={`${p.name}: ${fmtPct(p.v)}`}
            style={{
              position: "absolute",
              left: `${x(p.v)}%`,
              top: 0, bottom: 0,
              width: 2,
              background: "var(--on-surface-variant)",
              transform: "translateX(-50%)",
            }}
          />
        ))}
        <div
          title={`Ensemble (Kelly denom): ${fmtPct(ens)}`}
          style={{
            position: "absolute",
            left: `${x(ens)}%`,
            top: -3, bottom: -3,
            width: 3,
            background: "var(--primary)",
            boxShadow: "0 0 8px rgba(198,198,199,0.6)",
            transform: "translateX(-50%)",
          }}
        />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: "var(--on-surface-muted)", marginTop: 3 }}>
        <span>tail (loss)</span>
        <span style={{ color: "var(--primary)", fontWeight: 700, letterSpacing: "0.10em" }}>● ENSEMBLE = KELLY DENOM</span>
        <span>safer</span>
      </div>
    </div>
  );
}

// ── Stressed VaR Tail ─────────────────────────────────────────────────────────
function StressedTail({ data }: { data: VarResp | null }) {
  if (!data || data.error) return <Empty>insufficient data</Empty>;
  const sv = data.stressed_var;
  const ens99 = data.ensemble_max?.var_99;
  if (!sv) return <Empty>warmup - need 30+ returns</Empty>;
  const gap = ens99 ? Math.abs(sv.return_pct - ens99.return_pct) : null;

  // Visual: compare stressed vs ensemble bars
  const maxAbs = Math.max(Math.abs(sv.return_pct), ens99 ? Math.abs(ens99.return_pct) : 0, 0.01);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
        <span className="text-mono" style={{ fontSize: 26, fontWeight: 700, color: "var(--chart-bear)", lineHeight: 1, fontVariantNumeric: "tabular-nums" }}>
          {fmtPct(sv.return_pct)}
        </span>
        <span style={{ fontSize: 10, letterSpacing: "0.14em", color: "var(--on-surface-dim)" }}>WORST-5% MEAN</span>
      </div>

      {/* Mini comparison bars */}
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {[
          { label: "STRESSED", val: sv.return_pct, color: "var(--chart-bear)" },
          { label: "ENS 99%", val: ens99?.return_pct ?? null, color: "var(--primary)" },
        ].map((row) => (
          <div key={row.label} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 9, width: 52, textAlign: "right", color: "var(--on-surface-dim)", letterSpacing: "0.06em" }}>{row.label}</span>
            <div style={{ flex: 1, height: 8, background: "rgba(127,127,127,0.08)", borderRadius: 2, overflow: "hidden" }}>
              {row.val != null && (
                <div style={{ width: `${(Math.abs(row.val) / maxAbs) * 100}%`, height: "100%", background: row.color, borderRadius: 2, opacity: 0.75 }} />
              )}
            </div>
            <span className="text-mono" style={{ fontSize: 10, width: 44, textAlign: "right", color: "var(--on-surface-variant)", fontWeight: 600 }}>
              {row.val != null ? fmtPct(row.val) : "-"}
            </span>
          </div>
        ))}
      </div>

      <Grid>
        <KV k="USD loss"       v={fmtUsd(sv.usd_loss)} />
        <KV k="VaR 99% (ens)"  v={ens99 ? fmtPct(ens99.return_pct) : "-"} />
        <KV k="Tail premium"   v={gap == null ? "-" : `${gap.toFixed(2)} pp`} />
        <KV k="Method"         v={data.ensemble_max?.var_99?.confidence ? `${(data.ensemble_max.var_99.confidence * 100).toFixed(0)}% ens` : "-"} />
      </Grid>
      <div style={{ fontSize: 9, color: "var(--on-surface-muted)", letterSpacing: "0.10em" }}>
        gap &gt; 1pp suggests fatter tails than parametric assumptions
      </div>
    </div>
  );
}

// ── Liquidation Gauge ─────────────────────────────────────────────────────────
function LiquidationGauge({ data }: { data: VarResp | null }) {
  if (!data || data.error) return <Empty>insufficient data</Empty>;
  const lr = data.liquidation_risk;
  if (!lr) return <Empty>-</Empty>;
  const p = lr.probability_horizon;
  const sev = p >= 5 ? "var(--chart-bear)" : p >= 1 ? "var(--primary)" : "var(--chart-bull)";
  const fill = Math.min(100, Math.max(0, Math.log10(1 + p * 9) * 50));

  // Arc gauge for liquidation probability
  const cx = 60, cy = 56, r = 42;
  const START_DEG = 225;
  const SWEEP = 270;
  function arcLiq(from: number, to: number) {
    function pt(deg: number) {
      const rad = (deg * Math.PI) / 180;
      return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
    }
    const s = pt(from), e = pt(to);
    const sw = ((to - from) + 360) % 360;
    const la = sw > 180 ? 1 : 0;
    return `M ${s.x.toFixed(2)} ${s.y.toFixed(2)} A ${r} ${r} 0 ${la} 1 ${e.x.toFixed(2)} ${e.y.toFixed(2)}`;
  }
  const fillEnd = START_DEG + (fill / 100) * SWEEP;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
        {/* Arc gauge */}
        <svg width={120} height={72} viewBox="0 0 120 72" style={{ overflow: "hidden", flexShrink: 0 }}>
          <path d={arcLiq(START_DEG, START_DEG + SWEEP - 0.1)} fill="none" stroke="rgba(127,127,127,0.12)" strokeWidth={8} strokeLinecap="round" />
          {fill > 0 && (
            <path d={arcLiq(START_DEG, fillEnd)} fill="none" stroke={sev} strokeWidth={8} strokeLinecap="round" style={{ filter: `drop-shadow(0 0 4px ${sev === "var(--chart-bear)" ? "#ea394380" : sev === "var(--chart-bull)" ? "#16c78480" : "#c6c6c780"})` }} />
          )}
          <text x={cx} y={cy - 2} textAnchor="middle" dominantBaseline="middle" fill={sev} fontSize={20} fontWeight={700} fontFamily="var(--font-mono, monospace)">
            {p.toFixed(p < 1 ? 2 : 1)}
          </text>
          <text x={cx} y={cy + 14} textAnchor="middle" fill="rgba(127,127,127,0.55)" fontSize={8}>%</text>
        </svg>

        <div style={{ flex: 1, paddingTop: 4 }}>
          <div style={{ fontSize: 9, letterSpacing: "0.14em", color: "var(--on-surface-dim)", marginBottom: 2 }}>P(LIQ) · 1-STEP</div>
          <Grid>
            <KV k="Threshold" v={fmtPct(lr.threshold_pct)} />
            <KV k="Leverage"  v={`${lr.leverage.toFixed(1)}×`} />
            <KV k="Returns"   v={data.inputs ? String(data.inputs.n_returns) : "-"} />
            <KV k="MC paths"  v={data.inputs ? String(data.inputs.mc_paths) : "-"} />
          </Grid>
        </div>
      </div>

      {/* Linear gauge bar */}
      <div style={{ position: "relative", height: 6, background: "rgba(127,127,127,0.10)", borderRadius: 2, overflow: "hidden" }}>
        <div style={{ width: `${fill}%`, height: "100%", background: `linear-gradient(90deg, var(--chart-bull) 0%, var(--primary) 50%, var(--chart-bear) 100%)`, transition: "width 360ms ease" }} />
        {[20, 40, 60, 80].map((t) => (
          <div key={t} style={{ position: "absolute", left: `${t}%`, top: 0, bottom: 0, width: 1, background: "rgba(127,127,127,0.18)" }} />
        ))}
      </div>
    </div>
  );
}

// ── Drawdown Pulse ────────────────────────────────────────────────────────────
function DrawdownPulse({ health }: { health: HealthResp | null }) {
  const [hist, setHist] = useState<number[]>([]);

  const cb = health?.circuit_breaker;
  const dd = cb?.drawdown_from_peak_pct;

  // Accumulate history (max 40 readings) - latest value mirrored to a ref
  // after render, sampled by a 10s timer so setState never fires in render
  // or synchronously in an effect.
  const ddRef = useRef<number | null>(null);
  useEffect(() => {
    ddRef.current = dd ?? null;
  });
  useEffect(() => {
    const sample = () => {
      const v = ddRef.current;
      if (v == null) return;
      setHist((h) => [...h, v].slice(-40));
    };
    const t = setTimeout(sample, 0);
    const id = setInterval(sample, 10_000);
    return () => { clearTimeout(t); clearInterval(id); };
  }, []);

  if (!cb || dd == null) return <Empty>health unavailable</Empty>;

  const sev = dd <= -10 ? "var(--chart-bear)" : dd <= -3 ? "var(--primary)" : "var(--chart-bull)";
  const fill = Math.min(100, (Math.abs(dd) / 25) * 100);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <span className="text-mono" style={{ fontSize: 26, fontWeight: 700, color: sev, lineHeight: 1, fontVariantNumeric: "tabular-nums" }}>
          {fmtPct(dd)}
        </span>
        <span style={{ fontSize: 9, letterSpacing: "0.14em", color: "var(--on-surface-dim)" }}>FROM PEAK</span>
      </div>

      {/* Drawdown sparkline history */}
      <div>
        <div style={{ fontSize: 9, letterSpacing: "0.10em", color: "var(--on-surface-muted)", marginBottom: 2 }}>DRAWDOWN HISTORY</div>
        <SparkLine values={hist} color={sev} width={200} height={30} fill />
      </div>

      <div style={{ position: "relative", height: 6, background: "rgba(127,127,127,0.10)", borderRadius: 2, overflow: "hidden" }}>
        <div style={{ width: `${fill}%`, height: "100%", background: sev, transition: "width 360ms ease" }} />
      </div>
      <Grid>
        <KV k="Daily PnL"  v={fmtPct(cb.daily_loss_pct)} />
        <KV k="Weekly PnL" v={fmtPct(cb.weekly_loss_pct)} />
        <KV k="State"      v={cb.triggered ? "TRIPPED" : cb.leverage_reduced ? "REDUCED" : "ARMED"} />
        <KV k="Signals"    v={cb.signals_suppressed ? "off" : "live"} />
      </Grid>
    </div>
  );
}

// ── Circuit Breaker Strip ─────────────────────────────────────────────────────
function BreakerStrip({ health }: { health: HealthResp | null }) {
  const cb = health?.circuit_breaker;
  const events = health?.circuit_breaker_events ?? [];
  if (!cb) return <Empty>breaker state unavailable</Empty>;

  const dotColor = cb.triggered
    ? "var(--chart-bear)"
    : cb.leverage_reduced
    ? "var(--primary)"
    : "var(--chart-bull)";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ width: 8, height: 8, borderRadius: "50%", background: dotColor, boxShadow: `0 0 6px ${dotColor}`, display: "inline-block" }} />
        <span style={{ fontSize: 11, letterSpacing: "0.14em", color: "var(--on-surface)", fontWeight: 700 }}>
          {cb.triggered ? "TRIPPED" : cb.leverage_reduced ? "LEVERAGE REDUCED" : "ARMED"}
        </span>
        <span style={{ fontSize: 10, color: "var(--on-surface-dim)", marginLeft: "auto" }}>
          reset {cb.reset_time}
        </span>
      </div>
      {cb.trigger_reason && (
        <div style={{ fontSize: 11, color: "var(--chart-bear)" }}>{cb.trigger_reason}</div>
      )}
      <Grid>
        <KV k="Daily PnL"  v={fmtPct(cb.daily_loss_pct)} />
        <KV k="Weekly PnL" v={fmtPct(cb.weekly_loss_pct)} />
        <KV k="Drawdown"   v={fmtPct(cb.drawdown_from_peak_pct)} />
        <KV k="Signals"    v={cb.signals_suppressed ? "suppressed" : "live"} />
      </Grid>
      {events.length > 0 && (
        <div style={{ borderTop: "1px solid var(--hairline)", paddingTop: 6 }}>
          <div style={{ fontSize: 9, letterSpacing: "0.16em", color: "var(--on-surface-dim)", marginBottom: 6 }}>
            RECENT EVENTS
          </div>
          {/* Event density timeline - last 1 hour in 6 buckets of 10 min */}
          <EventTimeline events={events} />
          <div style={{ display: "flex", flexDirection: "column", gap: 2, maxHeight: 96, overflowY: "auto", marginTop: 6 }}>
            {events
              .slice(-8)
              .reverse()
              .map((e, i) => (
                <div key={`${e.ts}-${i}`} style={{ fontSize: 10, color: "var(--on-surface-variant)", display: "flex", gap: 8 }}>
                  <span style={{ color: "var(--on-surface-dim)" }}>{new Date(e.ts * 1000).toLocaleTimeString()}</span>
                  <span style={{ color: "var(--primary)" }}>{e.kind}</span>
                  <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.detail}</span>
                </div>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Event Timeline ────────────────────────────────────────────────────────────
// Bucketed density bar - 6×10min buckets spanning the last hour.
// Height of each bar = count of events in that 10-min window.
function EventTimeline({ events }: { events: Array<{ ts: number; kind: string; detail: string }> }) {
  // Clock lives in state so render stays pure; re-buckets every 30s.
  const [nowSec, setNowSec] = useState<number>(() => Date.now() / 1000);
  useEffect(() => {
    const id = setInterval(() => setNowSec(Date.now() / 1000), 30_000);
    return () => clearInterval(id);
  }, []);
  const BUCKETS = 6;
  const BUCKET_SEC = 600; // 10 min
  const counts = Array(BUCKETS).fill(0);
  events.forEach((e) => {
    const age = nowSec - e.ts;
    if (age < 0 || age >= BUCKETS * BUCKET_SEC) return;
    const idx = BUCKETS - 1 - Math.floor(age / BUCKET_SEC);
    counts[idx]++;
  });
  const maxCount = Math.max(...counts, 1);
  return (
    <div>
      <div style={{ display: "flex", gap: 2, alignItems: "flex-end", height: 28 }}>
        {counts.map((c, i) => {
          const h = (c / maxCount) * 24;
          const color = c === 0 ? "rgba(127,127,127,0.12)" : c >= 3 ? "var(--chart-bear)" : "var(--primary)";
          return (
            <div
              key={i}
              title={`${c} event${c !== 1 ? "s" : ""} · ${(BUCKETS - i) * 10}-${(BUCKETS - i - 1) * 10}min ago`}
              style={{
                flex: 1,
                height: Math.max(h, 3),
                background: color,
                borderRadius: 1,
                opacity: c === 0 ? 1 : 0.75,
                transition: "height 300ms ease",
              }}
            />
          );
        })}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 8, color: "var(--on-surface-muted)", marginTop: 2, letterSpacing: "0.08em" }}>
        <span>−60m</span>
        <span>now</span>
      </div>
    </div>
  );
}

// ── Kelly Fraction Bar ────────────────────────────────────────────────────────
// Visual comparison: recommended % vs half-kelly vs cap zones.
function KellyFractionBar({ kelly }: { kelly: KellyResp }) {
  const rec = kelly.recommended_position_pct ?? 0;
  const half = (kelly.half_kelly_fraction ?? 0) * 100;
  const maxDisplay = 20; // clamp display scale to 20% for legibility

  const zones = [
    { label: "0-5%", start: 0, end: 25, color: "rgba(22,199,132,0.12)" },
    { label: "5-10%", start: 25, end: 50, color: "rgba(198,198,199,0.08)" },
    { label: "10-20%", start: 50, end: 100, color: "rgba(234,57,67,0.10)" },
  ];

  const toX = (pct: number) => Math.min((pct / maxDisplay) * 100, 100);

  return (
    <div style={{ marginTop: 10 }}>
      <div style={{ fontSize: 9, letterSpacing: "0.14em", color: "var(--on-surface-dim)", marginBottom: 4 }}>
        KELLY FRACTION · VISUAL SCALE
      </div>
      <div style={{ position: "relative", height: 20, borderRadius: 2, overflow: "hidden", background: "rgba(127,127,127,0.06)" }}>
        {zones.map((z) => (
          <div
            key={z.label}
            style={{ position: "absolute", left: `${z.start}%`, width: `${z.end - z.start}%`, top: 0, bottom: 0, background: z.color }}
          />
        ))}
        {/* Half-kelly marker */}
        {half > 0 && (
          <div
            title={`Half-Kelly: ${half.toFixed(2)}%`}
            style={{
              position: "absolute", left: `${toX(half)}%`, top: 0, bottom: 0,
              width: 1.5, background: "rgba(198,198,199,0.55)", transform: "translateX(-50%)",
            }}
          />
        )}
        {/* Recommended fill */}
        {rec > 0 && (
          <div
            style={{
              position: "absolute", left: 0, top: 3, bottom: 3,
              width: `${toX(rec)}%`,
              background: rec > 10 ? "rgba(234,57,67,0.65)" : "rgba(22,199,132,0.65)",
              borderRadius: 2, transition: "width 400ms ease",
            }}
          />
        )}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 8, color: "var(--on-surface-muted)", marginTop: 2 }}>
        <span>0%</span>
        <span style={{ color: "var(--on-surface-dim)" }}>10%</span>
        <span>20%+</span>
      </div>
    </div>
  );
}

// ── Field Panel (ambient visual) ──────────────────────────────────────────────
function FieldPanel({ title, caption, children }: { title: string; caption?: string; children: React.ReactNode }) {
  return (
    <div
      style={{
        position: "relative",
        flex: "1 1 200px",
        minHeight: 200,
        marginLeft: -16,
        marginRight: -16,
        marginBottom: -16,
        background: "var(--surface-container-lowest)",
        borderTop: "1px solid var(--hairline)",
        overflow: "hidden",
      }}
    >
      {children}
      <div style={{ position: "absolute", top: 8, left: 12, right: 12, display: "flex", justifyContent: "space-between", alignItems: "baseline", zIndex: 2, pointerEvents: "none" }}>
        <span className="eyebrow" style={{ color: "var(--on-surface-dim)", fontSize: 10, letterSpacing: "0.18em" }}>{title}</span>
        {caption && <span style={{ color: "var(--on-surface-muted)", fontSize: 9, letterSpacing: "0.14em" }}>{caption.toUpperCase()}</span>}
      </div>
    </div>
  );
}

// ── Layout primitives ─────────────────────────────────────────────────────────

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div
      style={{
        background: "var(--surface-container-low)",
        border: "1px solid var(--hairline)",
        borderRadius: 4,
        padding: 12,
        minHeight: 140,
      }}
    >
      <div className="eyebrow" style={{ color: "var(--on-surface-dim)", fontSize: 10, marginBottom: 10 }}>
        {title}
      </div>
      {children}
    </div>
  );
}

function Grid({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px 16px" }}>
      {children}
    </div>
  );
}

function KV({ k, v }: { k: string; v: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
      <span style={{ color: "var(--on-surface-dim)" }}>{k}</span>
      <span className="text-mono" style={{ color: "var(--on-surface)", fontWeight: 600 }}>{v}</span>
    </div>
  );
}

function Loading() {
  return <span style={{ fontSize: 11, color: "var(--on-surface-dim)" }}>loading…</span>;
}

function Empty({ children }: { children: React.ReactNode }) {
  return <span style={{ fontSize: 11, color: "var(--on-surface-dim)" }}>{children}</span>;
}

function fmtPct(n: number | null | undefined): string {
  if (n == null || !isFinite(n)) return "-";
  return `${n >= 0 ? "" : ""}${n.toFixed(2)}%`;
}

function fmtUsd(n: number | null | undefined): string {
  if (n == null || !isFinite(n)) return "-";
  return `$${Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}
