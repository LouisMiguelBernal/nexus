"use client";

import { memo, useEffect, useMemo, useState } from "react";
import { usePolling } from "@/lib/usePolling";
import { num, fmtUSD, fmtPct } from "@/lib/format";
import { signalLabel } from "@/lib/labels";
import AdvisoryNotice from "@/components/AdvisoryNotice";

interface Props {
  symbol: string;
  api: string;
}

interface Signal {
  name?: string;
  direction?: string;
  strength?: number;
  confidence?: number;
  reasoning?: string;
  timeframe?: string;
}

interface AlphaData {
  symbol?: string;
  composite_score?: number;
  composite_direction?: string;
  confidence?: number;
  agreement_ratio?: number;
  signals?: Signal[];
  regime?: { regime?: string; confidence?: number };
  smart_money?: {
    net_flow?: number;
    intensity?: string;
    large_trade_count?: number;
    recent_whales?: Array<Record<string, unknown>>;
  };
  meta?: { generated_at?: string; data_age_ms?: number };
}

export default function AlphaTab({ symbol, api }: Props) {
  const { data, loading, error, refetch } = usePolling<AlphaData>({
    url: `${api}/api/alpha/${symbol}`,
    intervalMs: 5000,
  });
  const [expandedSignal, setExpandedSignal] = useState<number | null>(null);

  if (loading && !data) return <LoadingSkeleton />;

  if (error && !data) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="card" style={{ padding: 24, textAlign: "center" }}>
          <div style={{ color: "var(--accent-red)", fontSize: "var(--fs-title)", fontWeight: 700, marginBottom: 8 }}>
            CONNECTION ERROR
          </div>
          <div style={{ color: "var(--text-secondary)", fontSize: "var(--fs-data)" }}>{error}</div>
          <button onClick={refetch} className="btn-primary" style={{ marginTop: 12 }}>
            RETRY
          </button>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const score = num(data.composite_score);
  const scoreColor = getScoreColor(score);
  const dirLabel = String(data.composite_direction || "neutral").toUpperCase();
  const signals: Signal[] = Array.isArray(data.signals) ? data.signals : [];
  const sm = data.smart_money || {};
  const whales: Array<Record<string, unknown>> = Array.isArray(sm.recent_whales) ? sm.recent_whales : [];
  const regime = data.regime || {};
  const confidence = num(data.confidence);
  const agreement = num(data.agreement_ratio);
  const generatedAt = data.meta?.generated_at;

  return (
    <div className="flex flex-col gap-2 animate-slide-in">
      <AdvisoryNotice
        tag="ALPHA"
        message="Composite alpha and signal-grid outputs are regime-conditional statistical estimates. Aggregated scores are advisory only - never act on a single-metric trigger. Weights row sums to 1.0 within the active regime; values fall back to legacy SIGNAL_WEIGHTS when warmup data is insufficient."
      />
      {/* Row 1: Composite Score */}
      <div className="flex gap-2">
        <div className="card flex-1">
          <div className="card-header">
            <span>COMPOSITE ALPHA SCORE</span>
            <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>
              {generatedAt ? new Date(String(generatedAt)).toLocaleTimeString() : "--:--"}
            </span>
          </div>
          <div className="card-body flex items-center gap-6">
            <div className="flex items-center gap-4">
              <span
                style={{
                  fontSize: 36,
                  fontWeight: 800,
                  color: scoreColor,
                  lineHeight: 1,
                  letterSpacing: "-0.02em",
                }}
              >
                {score > 0 ? "+" : ""}{score.toFixed(1)}
              </span>
              <div className="flex flex-col gap-1">
                <span
                  className="badge"
                  style={{
                    fontSize: "var(--fs-data)",
                    padding: "2px 10px",
                    background: dirLabel === "LONG"
                      ? "rgba(0,200,83,0.12)"
                      : dirLabel === "SHORT"
                        ? "rgba(239,68,68,0.12)"
                        : "rgba(124,124,154,0.12)",
                    color: dirLabel === "LONG"
                      ? "var(--accent-green)"
                      : dirLabel === "SHORT"
                        ? "var(--accent-red)"
                        : "var(--text-secondary)",
                  }}
                >
                  {dirLabel}
                </span>
              </div>
            </div>

            <div className="flex-1 flex flex-col gap-1">
              <div className="flex justify-between" style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-tertiary)" }}>
                <span>-100</span>
                <span>0</span>
                <span>+100</span>
              </div>
              <div style={{ height: 6, background: "var(--bg-active)", borderRadius: 3, position: "relative" }}>
                <div className="score-gradient" style={{ position: "absolute", inset: 0, borderRadius: 3, opacity: 0.3 }} />
                <div
                  style={{
                    position: "absolute",
                    top: -2,
                    left: `${((Math.max(-100, Math.min(100, score)) + 100) / 200) * 100}%`,
                    width: 10,
                    height: 10,
                    borderRadius: "50%",
                    background: scoreColor,
                    transform: "translateX(-50%)",
                    boxShadow: `0 0 6px ${scoreColor}`,
                  }}
                />
              </div>
            </div>

            <div className="flex gap-6">
              <div className="text-center">
                <div style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-tertiary)", marginBottom: 2 }}>CONFIDENCE</div>
                <div style={{ fontSize: 16, fontWeight: 700, color: "var(--text-primary)" }}>
                  {(confidence * 100).toFixed(0)}%
                </div>
                <div className="confidence-bar" style={{ width: 60, marginTop: 2 }}>
                  <div className="confidence-bar-fill" style={{ width: `${confidence * 100}%` }} />
                </div>
              </div>
              <div className="text-center">
                <div style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-tertiary)", marginBottom: 2 }}>AGREEMENT</div>
                <div style={{ fontSize: 16, fontWeight: 700, color: "var(--text-primary)" }}>
                  {(agreement * 100).toFixed(0)}%
                </div>
                <div className="confidence-bar" style={{ width: 60, marginTop: 2 }}>
                  <div className="confidence-bar-fill" style={{ width: `${agreement * 100}%` }} />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Row 2: Signal Grid */}
      <div className="card">
        <div className="card-header">
          <span>SIGNAL MATRIX ({String(signals.length)} ACTIVE)</span>
          <span className="animate-pulse-live" style={{ color: "var(--accent-green)", fontSize: "var(--fs-data-xs)" }}>
            LIVE
          </span>
        </div>
        <div className="card-body" style={{ padding: 4 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 3 }}>
            {signals.map((sig, i) => (
              <SignalCard
                key={i}
                signal={sig}
                expanded={expandedSignal === i}
                onToggle={() => setExpandedSignal(expandedSignal === i ? null : i)}
              />
            ))}
          </div>
        </div>
      </div>

      {/* Macro row: Liquidation imbalance + Vol spread + Correlation */}
      <MacroRow symbol={symbol} api={api} />

      {/* Row 3: Smart Money + Regime + Reasoning */}
      <div className="flex gap-2">
        <SmartMoneyCard sm={sm} whales={whales} />

        <RegimeCard regime={regime} />

        <div className="card flex-[2]">
          <div className="card-header">SIGNAL REASONING</div>
          <div className="card-body" style={{ maxHeight: 200, overflowY: "auto" }}>
            <SignalReasoningPanel
              signals={signals}
              score={score}
              dirLabel={dirLabel}
              confidence={confidence}
              agreement={agreement}
              regime={regime as { regime?: string; confidence?: number }}
              sm={sm}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---- Macro Row ---- */

interface LiqWindow {
  window_seconds: number;
  long_usd: number;
  short_usd: number;
  total_usd: number;
  imbalance: number | null;
  available: boolean;
}
interface LeverageStress {
  ls_ratio: number | null;
  top_trader_ls: number | null;
  imbalance_retail: number | null;
  imbalance_top: number | null;
  imbalance_combined: number | null;
  bias: string;
  source: string;
}
interface LiqData {
  summary?: {
    imbalance?: number | null;
    long_usd?: number | null;
    short_usd?: number | null;
    total_usd?: number | null;
    bias?: string;
    cascade?: boolean;
    available?: boolean;
    active_window?: string;
    windows?: { "5m"?: LiqWindow; "15m"?: LiqWindow; "1h"?: LiqWindow };
  };
  series?: Array<{ time: number; long_usd: number; short_usd: number; imbalance: number }>;
  leverage_stress?: LeverageStress | null;
}
interface VolData {
  rv?: number | null;
  iv?: number | null;
  spread?: number | null;
  regime?: string;
  dvol_series?: Array<{ time: number; value: number }>;
}
interface CorrData {
  symbols?: string[];
  matrix?: number[][];
  top_pairs?: Array<{ a: string; b: string; corr: number }>;
  n_bars?: number;
}

function MacroRow({ symbol, api }: { symbol: string; api: string }) {
  const liq = usePolling<LiqData>({ url: `${api}/api/liquidations/${symbol}?limit=120`, intervalMs: 5000 });
  const vol = usePolling<VolData>({ url: `${api}/api/vol-spread/${symbol}`, intervalMs: 30000 });
  const corr = usePolling<CorrData>({ url: `${api}/api/correlation?lookback=96`, intervalMs: 60000 });

  return (
    <div className="flex gap-2">
      <MemoLiqCard data={liq.data} />
      <MemoVolSpreadCard data={vol.data} />
      <MemoCorrMatrixCard data={corr.data} highlight={symbol} />
    </div>
  );
}

function LiqCard({ data }: { data: LiqData | null }) {
  const s = data?.summary || {};
  const windows = s.windows || {};
  const activeKey = (s.active_window as "5m" | "15m" | "1h" | undefined) || "5m";
  const w = windows[activeKey];
  const lev = data?.leverage_stress ?? null;

  const hasAnyFlow = Boolean(w?.available) ||
                     Boolean(windows["5m"]?.available) ||
                     Boolean(windows["15m"]?.available) ||
                     Boolean(windows["1h"]?.available);

  // When all windows are genuinely quiet, surface the related-metric panel:
  // L/S ratio + Top Trader L/S → leverage stress proxy. Same risk dimension.
  if (!hasAnyFlow && lev) {
    return <LeverageStressCard lev={lev} />;
  }

  const imb = w?.imbalance ?? null;
  const longUsd = Number(w?.long_usd || 0);
  const shortUsd = Number(w?.short_usd || 0);
  const total = longUsd + shortUsd;
  const pctLong = total > 0 ? (longUsd / total) * 100 : 50;
  const bias = String(s.bias || "flat");
  const cascade = Boolean(s.cascade);
  const biasColor =
    bias === "long_cascade" || bias === "longs_bleeding" ? "var(--accent-red)"
    : bias === "short_squeeze" || bias === "shorts_bleeding" ? "var(--accent-green)"
    : !hasAnyFlow ? "var(--text-muted)"
    : "var(--text-secondary)";

  // Sparkline from imbalance series - uses the 5m sampled series even when
  // we surface a wider active_window for the headline number.
  const series = data?.series || [];
  const pts = series.slice(-60).map((p) => p.imbalance);
  const path = sparkPath(pts, 200, 36, -1, 1);

  return (
    <div className="card flex-1">
      <div className="card-header">
        <span>LIQUIDATION IMBALANCE · {activeKey}</span>
        {cascade && (
          <span className="badge" style={{ background: "rgba(239,68,68,0.18)", color: "var(--accent-red)" }}>
            CASCADE
          </span>
        )}
        {!hasAnyFlow && (
          <span className="badge" style={{ background: "rgba(127,127,127,0.10)", color: "var(--text-muted)" }}>
            QUIET
          </span>
        )}
      </div>
      <div className="card-body flex flex-col gap-2" style={{ opacity: hasAnyFlow ? 1 : 0.6 }}>
        <div className="flex items-baseline justify-between">
          <span style={{ fontSize: 22, fontWeight: 800, color: biasColor, lineHeight: 1 }}>
            {imb === null ? "-" : `${(imb * 100).toFixed(1)}%`}
          </span>
          <span style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            {!hasAnyFlow ? "no recent liquidations" : bias.replace(/_/g, " ")}
          </span>
        </div>

        {/* Long/Short bar */}
        <div style={{ height: 6, background: "var(--bg-active)", borderRadius: 3, overflow: "hidden", display: "flex" }}>
          <div style={{ width: hasAnyFlow ? `${pctLong}%` : "0%", background: "var(--accent-red)", opacity: 0.8 }} />
          <div style={{ width: hasAnyFlow ? `${100 - pctLong}%` : "0%", background: "var(--accent-green)", opacity: 0.8 }} />
        </div>
        <div className="flex justify-between" style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-tertiary)" }}>
          <span>L {hasAnyFlow ? `$${compactUSD(longUsd)}` : "-"}</span>
          <span>{hasAnyFlow ? `$${compactUSD(total)} tot` : "no flow"}</span>
          <span>S {hasAnyFlow ? `$${compactUSD(shortUsd)}` : "-"}</span>
        </div>

        <svg viewBox="0 0 200 36" style={{ width: "100%", height: 36 }} preserveAspectRatio="none">
          <line x1={0} x2={200} y1={18} y2={18} stroke="var(--border-primary)" strokeWidth={1} strokeDasharray="2 2" />
          {path && <path d={path} fill="none" stroke={biasColor} strokeWidth={1.5} />}
        </svg>
      </div>
    </div>
  );
}

/**
 * Related-metric substitute for LiqCard when all liquidation windows are
 * genuinely empty (quiet market). Displays Binance retail L/S ratio + Top
 * Trader L/S as a leverage-stress proxy - same risk dimension (crowd
 * positioning), different sensor (positions vs forced liquidations).
 */
function LeverageStressCard({ lev }: { lev: LeverageStress }) {
  const combined = lev.imbalance_combined;
  const retail = lev.imbalance_retail;
  const top = lev.imbalance_top;
  const ls = lev.ls_ratio;
  const topLs = lev.top_trader_ls;
  const bias = lev.bias;

  const biasColor =
    bias === "long_crowded" ? "var(--accent-red)" :
    bias === "short_crowded" ? "var(--accent-green)" :
    "var(--text-secondary)";

  const pctLong = combined !== null ? Math.max(0, Math.min(100, ((combined + 1) / 2) * 100)) : 50;
  const pctShort = 100 - pctLong;

  return (
    <div className="card flex-1">
      <div className="card-header">
        <span>LEVERAGE STRESS · L/S</span>
        <span className="badge" style={{ background: "rgba(127,127,127,0.10)", color: "var(--text-tertiary)" }}>
          QUIET LIQS · PROXY
        </span>
      </div>
      <div className="card-body flex flex-col gap-2">
        <div className="flex items-baseline justify-between">
          <span style={{ fontSize: 22, fontWeight: 800, color: biasColor, lineHeight: 1 }}>
            {combined === null ? "-" : `${(combined * 100).toFixed(1)}%`}
          </span>
          <span style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-tertiary)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            {bias.replace(/_/g, " ")}
          </span>
        </div>

        {/* Long-crowd / Short-crowd bar */}
        <div style={{ height: 6, background: "var(--bg-active)", borderRadius: 3, overflow: "hidden", display: "flex" }}>
          <div style={{ width: `${pctShort}%`, background: "var(--accent-green)", opacity: 0.7 }} />
          <div style={{ width: `${pctLong}%`, background: "var(--accent-red)", opacity: 0.7 }} />
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, fontSize: "var(--fs-data-xs)", marginTop: 2 }}>
          <div className="flex justify-between">
            <span style={{ color: "var(--text-tertiary)" }}>Retail L/S</span>
            <span className="text-mono" style={{
              color: retail === null ? "var(--text-muted)" : retail > 0 ? "var(--accent-red)" : "var(--accent-green)",
              fontWeight: 700,
            }}>
              {ls === null ? "-" : ls.toFixed(2)}
            </span>
          </div>
          <div className="flex justify-between">
            <span style={{ color: "var(--text-tertiary)" }}>Top Trader L/S</span>
            <span className="text-mono" style={{
              color: top === null ? "var(--text-muted)" : top > 0 ? "var(--accent-red)" : "var(--accent-green)",
              fontWeight: 700,
            }}>
              {topLs === null ? "-" : topLs.toFixed(2)}
            </span>
          </div>
        </div>
        <div style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-muted)", marginTop: 2 }}>
          {bias === "long_crowded" ? "Longs crowded → flush risk on selloff" :
           bias === "short_crowded" ? "Shorts crowded → squeeze risk on bid" :
           "Positioning balanced - no leverage edge"}
        </div>
      </div>
    </div>
  );
}

function VolSpreadCard({ data }: { data: VolData | null }) {
  const rv = data?.rv;
  const iv = data?.iv;
  const spread = data?.spread;
  const regime = String(data?.regime || "insufficient_data");
  const regimeColor =
    regime === "iv_rich" ? "var(--accent-green)"
    : regime === "iv_premium" ? "var(--accent-green)"
    : regime === "iv_cheap" ? "var(--accent-red)"
    : regime === "iv_discount" ? "var(--accent-red)"
    : regime === "fair" ? "var(--text-secondary)"
    : "var(--text-muted)";

  const dvol = (data?.dvol_series || []).map((p) => p.value);
  const path = sparkPath(dvol, 200, 36);

  return (
    <div className="card flex-1">
      <div className="card-header">
        <span>RV vs IV SPREAD</span>
        <span className="badge" style={{ background: "rgba(124,124,154,0.12)", color: regimeColor }}>
          {regime.replace(/_/g, " ").toUpperCase()}
        </span>
      </div>
      <div className="card-body flex flex-col gap-2">
        <div className="flex items-baseline justify-between">
          <span style={{ fontSize: 22, fontWeight: 800, color: regimeColor, lineHeight: 1 }}>
            {spread != null ? `${spread > 0 ? "+" : ""}${spread.toFixed(1)}` : "-"}
            <span style={{ fontSize: 12, fontWeight: 500, color: "var(--text-tertiary)", marginLeft: 4 }}>pts</span>
          </span>
          <div className="flex gap-3" style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-tertiary)" }}>
            <span>RV <strong style={{ color: "var(--text-primary)" }}>{rv != null ? `${rv.toFixed(1)}%` : "-"}</strong></span>
            <span>IV <strong style={{ color: "var(--text-primary)" }}>{iv != null ? `${iv.toFixed(1)}%` : "-"}</strong></span>
          </div>
        </div>
        <svg viewBox="0 0 200 36" style={{ width: "100%", height: 36 }} preserveAspectRatio="none">
          {path && <path d={path} fill="none" stroke="var(--accent-amber)" strokeWidth={1.5} />}
        </svg>
        <div style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-tertiary)" }}>
          Deribit DVOL (48h)
        </div>
      </div>
    </div>
  );
}

function CorrMatrixCard({ data, highlight }: { data: CorrData | null; highlight: string }) {
  const symbols = data?.symbols || [];
  const mat = data?.matrix || [];
  const topPairs = data?.top_pairs || [];

  return (
    <div className="card flex-1">
      <div className="card-header">
        <span>CROSS-ASSET CORRELATION</span>
        <span style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-tertiary)" }}>
          {data?.n_bars ? `${data.n_bars} bars` : "-"}
        </span>
      </div>
      <div className="card-body flex gap-3">
        {symbols.length > 0 ? (
          <table style={{ borderCollapse: "collapse", fontSize: "var(--fs-data-xs)" }}>
            <thead>
              <tr>
                <th />
                {symbols.map((s) => (
                  <th key={s} style={{
                    padding: "2px 4px",
                    color: s === highlight ? "var(--accent-amber)" : "var(--text-tertiary)",
                    fontWeight: 600,
                  }}>
                    {s.replace("USDT", "")}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {symbols.map((rowSym, i) => (
                <tr key={rowSym}>
                  <td style={{
                    padding: "2px 6px 2px 0",
                    color: rowSym === highlight ? "var(--accent-amber)" : "var(--text-tertiary)",
                    fontWeight: 600,
                    textAlign: "right",
                  }}>
                    {rowSym.replace("USDT", "")}
                  </td>
                  {symbols.map((colSym, j) => {
                    const r = mat[i]?.[j] ?? 0;
                    return (
                      <td key={colSym} style={{
                        padding: "2px 4px",
                        textAlign: "center",
                        color: Math.abs(r) > 0.5 ? "#fff" : "var(--text-secondary)",
                        background: corrColor(r),
                        fontWeight: i === j ? 700 : 500,
                        minWidth: 36,
                      }}>
                        {i === j ? "-" : r.toFixed(2)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div style={{ color: "var(--text-tertiary)", fontSize: "var(--fs-data-xs)" }}>Waiting for klines…</div>
        )}

        {topPairs.length > 0 && (
          <div className="flex flex-col gap-1" style={{ minWidth: 120 }}>
            <div style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-tertiary)", marginBottom: 2 }}>TOP |ρ|</div>
            {topPairs.slice(0, 5).map((p, i) => (
              <div key={i} className="flex justify-between" style={{ fontSize: "var(--fs-data-xs)" }}>
                <span style={{ color: "var(--text-secondary)" }}>
                  {p.a.replace("USDT", "")}·{p.b.replace("USDT", "")}
                </span>
                <span style={{ color: corrTextColor(p.corr), fontWeight: 700 }}>
                  {p.corr.toFixed(2)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ---- tiny helpers ---- */

// Memoized wrappers - each card only re-renders when its own data slice
// changes, so unrelated polling updates don't cascade rendering across the
// whole row. Noticeable perf win at ≥3 concurrent polls (liq 5s, vol 30s, corr 60s).
const MemoLiqCard = memo(LiqCard);
const MemoVolSpreadCard = memo(VolSpreadCard);
const MemoCorrMatrixCard = memo(CorrMatrixCard);

function compactUSD(n: number): string {
  const v = Math.abs(n);
  if (v >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
  return n.toFixed(0);
}

function sparkPath(values: number[], w: number, h: number, forceMin?: number, forceMax?: number): string {
  if (!values || values.length < 2) return "";
  const mn = forceMin != null ? forceMin : Math.min(...values);
  const mx = forceMax != null ? forceMax : Math.max(...values);
  const range = mx - mn || 1;
  const step = w / (values.length - 1);
  return values.map((v, i) => {
    const x = i * step;
    const y = h - ((v - mn) / range) * h;
    return `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(" ");
}

function corrColor(r: number): string {
  // Red (negative) → neutral → green (positive)
  const a = Math.min(1, Math.abs(r));
  if (r >= 0) return `rgba(0, 200, 83, ${(a * 0.55).toFixed(3)})`;
  return `rgba(239, 68, 68, ${(a * 0.55).toFixed(3)})`;
}

function corrTextColor(r: number): string {
  if (r >= 0.5) return "var(--accent-green)";
  if (r <= -0.5) return "var(--accent-red)";
  return "var(--text-secondary)";
}

/* ---- Sub Components ---- */

function SignalCard({
  signal,
  expanded,
  onToggle,
}: {
  signal: Signal;
  expanded: boolean;
  onToggle: () => void;
}) {
  const dir = String(signal.direction || "neutral");
  const dirColor = dir === "long"
    ? "var(--accent-green)"
    : dir === "short"
      ? "var(--accent-red)"
      : "var(--text-secondary)";

  const dirArrow = dir === "long" ? "^" : dir === "short" ? "v" : "-";
  const strength = num(signal.strength);
  const conf = num(signal.confidence);
  // Treat strength<=0 AND confidence<=0 as ABSENT - don't show fake 0%.
  // Reasoning text from backend will say "no data" / "insufficient bars"
  // and we surface that instead of a misleading neutral 0%.
  const reasoning = String(signal.reasoning || "");
  const isAbsent =
    strength <= 0 &&
    conf <= 0 &&
    /no data|insufficient|warmup|no proxy|invalid|flat realized vol/i.test(reasoning);

  return (
    <button
      onClick={onToggle}
      className="text-left transition-colors"
      style={{
        padding: "6px 8px",
        background: expanded ? "var(--bg-hover)" : "var(--bg-secondary)",
        border: `1px solid ${expanded ? "var(--border-accent)" : "var(--border-primary)"}`,
        borderRadius: 3,
        cursor: "pointer",
        opacity: isAbsent ? 0.55 : 1,
      }}
      title={isAbsent ? reasoning : undefined}
    >
      <div className="flex items-center justify-between" style={{ marginBottom: 3 }}>
        <span style={{ fontSize: "var(--fs-data-xs)", fontWeight: 700, color: "var(--text-primary)" }}>
          {signal.name ? signalLabel(String(signal.name)) : "-"}
        </span>
        <span style={{ fontSize: "var(--fs-data)", fontWeight: 800, color: isAbsent ? "var(--text-tertiary)" : dirColor }}>
          {isAbsent ? "·" : dirArrow}
        </span>
      </div>

      <div style={{ marginBottom: 3 }}>
        <div style={{ height: 3, background: "var(--bg-active)", borderRadius: 2, overflow: "hidden" }}>
          <div
            style={{
              height: "100%",
              width: isAbsent ? "0%" : `${Math.min(strength, 100)}%`,
              background: dirColor,
              borderRadius: 2,
              transition: "width 0.3s",
            }}
          />
        </div>
        <div className="flex justify-between" style={{ marginTop: 1 }}>
          <span style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-tertiary)" }}>
            {isAbsent ? "-" : fmtPct(strength, 0)}
          </span>
          <span className={`badge badge-${String(signal.timeframe || "")}`}>{String(signal.timeframe || "")}</span>
        </div>
      </div>

      <div className="flex items-center gap-1">
        <span style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-tertiary)" }}>conf:</span>
        <span style={{ fontSize: "var(--fs-data-xs)", fontWeight: 600, color: "var(--text-secondary)" }}>
          {isAbsent ? "-" : `${(conf * 100).toFixed(0)}%`}
        </span>
        {isAbsent ? (
          <span style={{ marginLeft: 4, fontSize: 8, letterSpacing: "0.12em", color: "var(--primary)", fontWeight: 700 }}>
            WARMUP
          </span>
        ) : null}
      </div>

      {expanded ? (
        <div style={{ marginTop: 4, fontSize: "var(--fs-data-xs)", color: "var(--text-secondary)", lineHeight: 1.3, borderTop: "1px solid var(--border-primary)", paddingTop: 4 }}>
          {reasoning || "-"}
        </div>
      ) : null}
    </button>
  );
}


function LoadingSkeleton() {
  return (
    <div className="flex flex-col gap-2 p-2">
      <div className="skeleton" style={{ height: 80 }} />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 3 }}>
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="skeleton" style={{ height: 70 }} />
        ))}
      </div>
      <div className="flex gap-2">
        <div className="skeleton flex-1" style={{ height: 120 }} />
        <div className="skeleton flex-1" style={{ height: 120 }} />
      </div>
    </div>
  );
}

/* ---- Helpers ---- */

function getScoreColor(score: number): string {
  if (score > 40) return "var(--accent-green-bright)";
  if (score > 15) return "var(--accent-green)";
  if (score > -15) return "var(--text-secondary)";
  if (score > -40) return "var(--accent-red)";
  return "var(--accent-red-bright)";
}

function getRegimeColor(regime: string): string {
  if (regime.includes("bull")) return "var(--accent-green)";
  if (regime.includes("bear")) return "var(--accent-red)";
  if (regime.includes("ranging") || regime.includes("neutral")) return "var(--accent-amber)";
  return "var(--text-secondary)";
}

/* ---- Signal Reasoning panel ----
 * Renders the per-signal reasoning when at least one signal is present.
 * When the signal grid is empty (warmup, all-zero confidence, regime missing),
 * derives a short narrative from the data we DO have: regime, composite
 * score/direction/confidence/agreement, and smart-money flow. The fallback
 * is tagged DERIVED so the operator never confuses it with engine output. */
function SignalReasoningPanel({
  signals,
  score,
  dirLabel,
  confidence,
  agreement,
  regime,
  sm,
}: {
  signals: Signal[];
  score: number;
  dirLabel: string;
  confidence: number;
  agreement: number;
  regime: { regime?: string; confidence?: number };
  sm: NonNullable<AlphaData["smart_money"]>;
}) {
  const populated = signals.filter(
    (s) => String(s.reasoning ?? "").trim().length > 0,
  );

  if (populated.length > 0) {
    return (
      <div className="flex flex-col gap-1">
        {populated.map((sig, i) => (
          <div
            key={i}
            style={{
              padding: "4px 8px",
              borderLeft: `2px solid ${
                sig.direction === "long"
                  ? "var(--accent-green)"
                  : sig.direction === "short"
                  ? "var(--accent-red)"
                  : "var(--text-muted)"
              }`,
              background: "var(--bg-secondary)",
              borderRadius: "0 2px 2px 0",
            }}
          >
            <div className="flex items-center gap-2" style={{ marginBottom: 2 }}>
              <span style={{ fontSize: "var(--fs-data-sm)", fontWeight: 700, color: "var(--text-primary)" }}>
                {sig.name ? signalLabel(String(sig.name)) : "-"}
              </span>
              <span className={`badge badge-${String(sig.timeframe || "")}`}>
                {String(sig.timeframe || "")}
              </span>
            </div>
            <div style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-secondary)", lineHeight: 1.3 }}>
              {String(sig.reasoning || "")}
            </div>
          </div>
        ))}
      </div>
    );
  }

  // Derived fallback. Build short narrative blocks from non-signal data.
  const regimeLabel = String(regime?.regime || "unknown").replace(/_/g, " ");
  const regimeConf = num(regime?.confidence) * 100;
  const netFlow = num(sm?.net_flow);
  const flowLabel = netFlow > 0 ? "buy" : netFlow < 0 ? "sell" : "balanced";
  const whaleCount = Array.isArray(sm?.recent_whales) ? sm.recent_whales.length : 0;

  const blocks: Array<{ tag: string; tone: "long" | "short" | "neutral"; body: string }> = [];

  // Composite block.
  const compTone: "long" | "short" | "neutral" =
    dirLabel === "LONG" ? "long" : dirLabel === "SHORT" ? "short" : "neutral";
  blocks.push({
    tag: "COMPOSITE",
    tone: compTone,
    body: `Aggregate score ${score > 0 ? "+" : ""}${score.toFixed(1)} (${dirLabel}). Confidence ${confidence.toFixed(0)}%, signal agreement ${agreement.toFixed(0)}%. ${
      confidence < 30
        ? "Below institutional threshold - treat as exploratory."
        : confidence < 60
        ? "Mid-band conviction - wait for confirmation."
        : "High-conviction read - still requires risk-sized execution."
    }`,
  });

  // Regime block.
  if (regime?.regime) {
    blocks.push({
      tag: "REGIME",
      tone: "neutral",
      body: `${regimeLabel.toUpperCase()} @ ${regimeConf.toFixed(0)}% confidence. ${
        regimeLabel.includes("ranging")
          ? "Mean-reversion edge dominates; momentum factors discounted."
          : regimeLabel.includes("bull")
          ? "Momentum + flow factors up-weighted; fades risk-off."
          : regimeLabel.includes("bear")
          ? "Downside momentum + smart-money flow lead the composite."
          : regimeLabel.includes("volatile")
          ? "Risk-off bias: liquidation cascade and smart-money tracking are dominant."
          : regimeLabel.includes("low_liq")
          ? "Structural factors lead (funding arb, cross-venue spread, carry)."
          : "Regime undetermined - fallback weights applied."
      }`,
    });
  }

  // Smart-money block.
  if (whaleCount > 0 || Math.abs(netFlow) > 0) {
    blocks.push({
      tag: "SMART MONEY",
      tone: netFlow > 0 ? "long" : netFlow < 0 ? "short" : "neutral",
      body: `Net whale flow ${netFlow >= 0 ? "+" : ""}$${(netFlow / 1e6).toFixed(2)}M across ${whaleCount} prints (${flowLabel || "balanced"}). ${
        Math.abs(netFlow) > 5e6
          ? "Outsized concentration - track for absorption / continuation."
          : "Within normal range; not a standalone trigger."
      }`,
    });
  }

  // Warmup notice if signals truly empty.
  if (signals.length === 0) {
    blocks.push({
      tag: "STATUS",
      tone: "neutral",
      body:
        "Signal grid is empty - engine is warming up or required venues are stale. Composite falls back to legacy SIGNAL_WEIGHTS while regime confidence rebuilds. Reasoning above is DERIVED from available macro context, not from individual factors.",
    });
  }

  return (
    <div className="flex flex-col gap-1">
      {blocks.map((b, i) => (
        <div
          key={i}
          style={{
            padding: "4px 8px",
            borderLeft: `2px solid ${
              b.tone === "long"
                ? "var(--accent-green)"
                : b.tone === "short"
                ? "var(--accent-red)"
                : "var(--text-muted)"
            }`,
            background: "var(--bg-secondary)",
            borderRadius: "0 2px 2px 0",
          }}
        >
          <div className="flex items-center gap-2" style={{ marginBottom: 2 }}>
            <span
              style={{
                fontSize: "var(--fs-data-sm)",
                fontWeight: 700,
                color: "var(--text-primary)",
                letterSpacing: "0.06em",
              }}
            >
              {b.tag}
            </span>
            <span
              style={{
                fontSize: 9,
                padding: "1px 5px",
                background: "rgba(198,198,199,0.10)",
                color: "var(--primary)",
                border: "1px solid rgba(198,198,199,0.20)",
                borderRadius: 2,
                letterSpacing: "0.10em",
                fontWeight: 700,
              }}
            >
              DERIVED
            </span>
          </div>
          <div style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-secondary)", lineHeight: 1.35 }}>
            {b.body}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ---- Smart Money Flow (interactive redesign) ---- */

type WhaleFilter = "all" | "buy" | "sell";

function SmartMoneyCard({
  sm,
  whales,
}: {
  sm: NonNullable<AlphaData["smart_money"]>;
  whales: Array<Record<string, unknown>>;
}) {
  const [filter, setFilter] = useState<WhaleFilter>("all");
  const [selected, setSelected] = useState<number | null>(null);
  const [flowHistory, setFlowHistory] = useState<number[]>([]);

  const netFlow = num(sm.net_flow);
  const intensity = String(sm.intensity || "normal");

  // Rolling net_flow history - capped at 60 samples. This is a legitimate
  // accumulation of polled prop values into a visualization buffer; the lint
  // rule can't distinguish this from cascade-prone patterns.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setFlowHistory((prev) => {
      const next = [...prev, netFlow];
      if (next.length > 60) next.shift();
      return next;
    });
  }, [netFlow]);

  const filtered = useMemo(() => {
    if (filter === "all") return whales;
    return whales.filter((w) => String(w.side || "").toLowerCase() === filter);
  }, [filter, whales]);

  const buyCount = whales.filter((w) => String(w.side || "").toLowerCase() === "buy").length;
  const sellCount = whales.filter((w) => String(w.side || "").toLowerCase() === "sell").length;
  const total = Math.max(1, buyCount + sellCount);
  const buyPct = (buyCount / total) * 100;

  const flowColor = netFlow > 0 ? "var(--accent-green)" : netFlow < 0 ? "var(--accent-red)" : "var(--text-secondary)";
  const sparkPts = flowHistory;
  const sparkMin = Math.min(0, ...sparkPts);
  const sparkMax = Math.max(0, ...sparkPts);
  const path = sparkPath(sparkPts, 200, 32, sparkMin, sparkMax);

  return (
    <div className="card flex-1">
      <div className="card-header">
        <span>SMART MONEY FLOW</span>
        <span
          className="badge"
          style={{
            background: intensity === "extreme" ? "rgba(239,68,68,0.18)" : intensity === "elevated" ? "rgba(245,158,11,0.18)" : "rgba(124,124,154,0.12)",
            color: intensity === "extreme" ? "var(--accent-red)" : intensity === "elevated" ? "var(--accent-amber)" : "var(--text-secondary)",
          }}
        >
          {intensity.toUpperCase()}
        </span>
      </div>
      <div className="card-body flex flex-col gap-2">
        <div className="flex items-baseline justify-between">
          <span style={{ fontSize: 22, fontWeight: 800, color: flowColor, lineHeight: 1 }}>
            {fmtUSD(netFlow, { signed: true })}
          </span>
          <span style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-tertiary)" }}>
            {num(sm.large_trade_count)} whales
          </span>
        </div>

        {/* Buy/Sell split bar */}
        <div>
          <div style={{ height: 6, background: "var(--bg-active)", borderRadius: 3, overflow: "hidden", display: "flex" }}>
            <div style={{ width: `${buyPct}%`, background: "var(--accent-green)", opacity: 0.85 }} />
            <div style={{ width: `${100 - buyPct}%`, background: "var(--accent-red)", opacity: 0.85 }} />
          </div>
          <div className="flex justify-between" style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-tertiary)", marginTop: 2 }}>
            <span style={{ color: "var(--accent-green)" }}>BUY {buyCount}</span>
            <span style={{ color: "var(--accent-red)" }}>SELL {sellCount}</span>
          </div>
        </div>

        {/* Rolling net-flow sparkline */}
        <svg viewBox="0 0 200 32" style={{ width: "100%", height: 32 }} preserveAspectRatio="none">
          <line x1={0} x2={200} y1={16} y2={16} stroke="var(--border-primary)" strokeWidth={1} strokeDasharray="2 2" />
          {path && <path d={path} fill="none" stroke={flowColor} strokeWidth={1.5} />}
        </svg>

        {/* Filter tabs */}
        {whales.length > 0 ? (
          <>
            <div className="flex gap-1" style={{ fontSize: "var(--fs-data-xs)" }}>
              {(["all", "buy", "sell"] as const).map((f) => (
                <button
                  key={f}
                  onClick={() => { setFilter(f); setSelected(null); }}
                  style={{
                    flex: 1,
                    padding: "2px 4px",
                    background: filter === f ? "var(--bg-hover)" : "var(--bg-secondary)",
                    border: `1px solid ${filter === f ? "var(--border-accent)" : "var(--border-primary)"}`,
                    color: filter === f ? "var(--text-primary)" : "var(--text-tertiary)",
                    borderRadius: 2,
                    cursor: "pointer",
                    fontWeight: 600,
                    textTransform: "uppercase",
                  }}
                >
                  {f}
                </button>
              ))}
            </div>
            <div className="flex flex-col gap-1" style={{ maxHeight: 110, overflowY: "auto" }}>
              {filtered.slice(0, 12).map((w, i) => {
                const side = String(w.side || "").toLowerCase();
                const sideColor = side === "buy" ? "var(--accent-green)" : "var(--accent-red)";
                const isOpen = selected === i;
                const ts = Number(w.time || w.timestamp || 0);
                const tsLabel = ts > 0 ? new Date(ts).toLocaleTimeString() : "-";
                return (
                  <div
                    key={i}
                    onClick={() => setSelected(isOpen ? null : i)}
                    style={{
                      padding: "3px 6px",
                      background: isOpen ? "var(--bg-hover)" : "var(--bg-active)",
                      border: `1px solid ${isOpen ? "var(--border-accent)" : "transparent"}`,
                      borderRadius: 2,
                      cursor: "pointer",
                      fontSize: "var(--fs-data-xs)",
                    }}
                  >
                    <div className="flex justify-between items-center">
                      <span style={{ color: sideColor, fontWeight: 700 }}>{side.toUpperCase()}</span>
                      <span style={{ color: "var(--text-primary)", fontWeight: 700 }}>{fmtUSD(w.usd_value)}</span>
                    </div>
                    {isOpen ? (
                      <div className="flex justify-between" style={{ marginTop: 2, color: "var(--text-tertiary)" }}>
                        <span>@ ${Number(w.price || 0).toFixed(2)}</span>
                        <span>{Number(w.quantity || w.qty || 0).toFixed(3)}</span>
                        <span>{tsLabel}</span>
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </>
        ) : (
          <div style={{ color: "var(--text-tertiary)", fontSize: "var(--fs-data-xs)" }}>No whale activity yet</div>
        )}
      </div>
    </div>
  );
}

/* ---- Market Regime (interactive redesign) ---- */

interface RegimeSnapshot {
  regime: string;
  confidence: number;
  t: number;
}

const REGIME_DESCRIPTIONS: Record<string, string> = {
  bull_trending: "Sustained upward momentum - trend-following systems favored",
  bull_ranging: "Upward bias with mean-reversion - sell strength, buy weakness",
  bear_trending: "Sustained downward momentum - avoid longs, fade rips",
  bear_ranging: "Downward bias with mean-reversion - buy weakness, sell strength",
  ranging: "Chop - neither trend nor breakout; reduce size",
  neutral: "No clear regime - lower conviction across signals",
  volatile: "High-vol chop - widen stops, reduce leverage",
};

function RegimeCard({ regime }: { regime: NonNullable<AlphaData["regime"]> }) {
  const [transitions, setTransitions] = useState<RegimeSnapshot[]>([]);

  const regimeName = String(regime.regime || "unknown");
  const conf = num(regime.confidence);

  // Accumulating regime transitions over time - see SmartMoneyCard comment.
  useEffect(() => {
    if (!regime.regime) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setTransitions((prev) => {
      const last = prev[prev.length - 1];
      if (!last || last.regime !== regimeName || Date.now() - last.t > 60_000) {
        const next = [...prev, { regime: regimeName, confidence: conf, t: Date.now() }];
        if (next.length > 40) next.shift();
        return next;
      }
      return prev;
    });
  }, [regimeName, conf, regime.regime]);

  const color = getRegimeColor(regimeName);
  const description = REGIME_DESCRIPTIONS[regimeName] || "Regime signal computed from trend + volatility + flow";
  const ringSize = 84;
  const ringR = 36;
  const ringC = 2 * Math.PI * ringR;
  const confDash = ringC * conf;

  return (
    <div className="card flex-1">
      <div className="card-header">
        <span>MARKET REGIME</span>
        <span style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-tertiary)" }}>
          {transitions.length > 1 ? `${transitions.length} snap` : "live"}
        </span>
      </div>
      <div className="card-body flex flex-col gap-2">
        <div className="flex items-center gap-3">
          {/* Conic/ring gauge */}
          <svg width={ringSize} height={ringSize} viewBox={`0 0 ${ringSize} ${ringSize}`}>
            <circle cx={ringSize / 2} cy={ringSize / 2} r={ringR} fill="none" stroke="var(--bg-active)" strokeWidth={6} />
            <circle
              cx={ringSize / 2}
              cy={ringSize / 2}
              r={ringR}
              fill="none"
              stroke={color}
              strokeWidth={6}
              strokeDasharray={`${confDash} ${ringC}`}
              strokeDashoffset={ringC / 4}
              transform={`rotate(-90 ${ringSize / 2} ${ringSize / 2})`}
              style={{ transition: "stroke-dasharray 0.3s" }}
            />
            <text
              x={ringSize / 2}
              y={ringSize / 2 + 4}
              textAnchor="middle"
              fontSize={14}
              fontWeight={800}
              fill={color}
            >
              {(conf * 100).toFixed(0)}%
            </text>
          </svg>

          <div className="flex-1 flex flex-col gap-1">
            <div style={{ fontSize: "var(--fs-title)", fontWeight: 800, color, letterSpacing: "0.05em", textTransform: "uppercase", lineHeight: 1 }}>
              {regimeName.replace(/_/g, " ")}
            </div>
            <div style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-tertiary)", lineHeight: 1.3 }}>
              {description}
            </div>
          </div>
        </div>

        {/* Regime transition timeline */}
        {transitions.length > 1 ? (
          <div>
            <div style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-tertiary)", marginBottom: 3 }}>TRANSITIONS</div>
            <div style={{ display: "flex", gap: 1, height: 14, borderRadius: 2, overflow: "hidden" }}>
              {transitions.map((t, i) => (
                <div
                  key={i}
                  title={`${t.regime} @ ${new Date(t.t).toLocaleTimeString()} (${(t.confidence * 100).toFixed(0)}%)`}
                  style={{
                    flex: 1,
                    background: getRegimeColor(t.regime),
                    opacity: 0.4 + t.confidence * 0.6,
                    cursor: "help",
                  }}
                />
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

