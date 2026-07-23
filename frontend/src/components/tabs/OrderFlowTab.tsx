"use client";

import { useEffect, useState } from "react";
import { usePolling } from "@/lib/usePolling";
import { num, fmtUSD, fmtPct, fmtPrice, fmtFixed } from "@/lib/format";

interface Props {
  symbol: string;
  api: string;
}

interface CvdTf {
  cvd?: number | null;
  trade_count?: number;
  available?: boolean;
}

interface LargeTrade {
  price?: number;
  qty?: number;
  side?: string;
  usd_value?: number;
  time_ago?: string;
}

interface OrderFlowData {
  cvd?: Record<string, CvdTf>;
  absorption?: { detected?: boolean; side?: string; strength?: number };
  large_trades?: LargeTrade[];
  trade_flow_ratio?: number | null;
  volume_profile?: {
    buy_volume?: number | null;
    sell_volume?: number | null;
    total_volume?: number | null;
    trade_count?: number;
  };
  oi_change_1h?: number | null;
  oi_samples?: number;
  source?: { trades?: string | null; venues_active?: Record<string, unknown> | null };
}

interface ObiSample { time: number; obi: number; bid_vol: number; ask_vol: number }
interface ObiPayload {
  latest?: ObiSample | null;
  summary?: {
    latest?: number; mean?: number; std?: number;
    min?: number; max?: number; bias?: string; count?: number;
  };
  series?: ObiSample[];
}

interface FundingPayload {
  weighted_rate_pct?: number;
  classification?: string;
  zscore?: number;
  zscore_classification?: string;
  zscore_window?: number;
}

interface TapeSample { time: number; tps: number }
interface TapePayload {
  latest?: { tps?: number } | null;
  summary?: {
    latest?: number; mean?: number; std?: number; max?: number;
    count?: number; burst?: boolean;
  };
  series?: TapeSample[];
}

export default function OrderFlowTab({ symbol, api }: Props) {
  const { data, loading, error, refetch } = usePolling<OrderFlowData>({
    url: `${api}/api/orderflow/${symbol}`,
    intervalMs: 5000,
  });
  const { data: obi } = usePolling<ObiPayload>({
    url: `${api}/api/obi/${symbol}?limit=180`,
    intervalMs: 2000,
  });
  const { data: funding } = usePolling<FundingPayload>({
    url: `${api}/api/funding/${symbol}`,
    intervalMs: 10000,
  });
  const { data: tape } = usePolling<TapePayload>({
    url: `${api}/api/tape/${symbol}?limit=180`,
    intervalMs: 2000,
  });

  if (loading && !data) {
    return (
      <div className="flex flex-col gap-2 p-2">
        <div className="skeleton" style={{ height: 100 }} />
        <div className="flex gap-2">
          <div className="skeleton flex-1" style={{ height: 200 }} />
          <div className="skeleton flex-1" style={{ height: 200 }} />
        </div>
        <div className="skeleton" style={{ height: 200 }} />
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="card" style={{ padding: 24, textAlign: "center" }}>
          <div style={{ color: "var(--accent-red)", fontSize: "var(--fs-title)", fontWeight: 700, marginBottom: 8 }}>ORDER FLOW UNAVAILABLE</div>
          <div style={{ color: "var(--text-secondary)", fontSize: "var(--fs-data)" }}>{error}</div>
          <button onClick={refetch} className="btn-primary" style={{ marginTop: 12 }}>RETRY</button>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const cvd: Record<string, CvdTf> = data.cvd || {};
  const cvdEntries = Object.entries(cvd);
  const volumeProfile = data.volume_profile || {};
  const absorption = data.absorption || {};
  const largeTrades: LargeTrade[] = Array.isArray(data.large_trades) ? data.large_trades : [];

  // Strict null-vs-zero contract: backend now sends `available: false` when
  // there is no trade data at all (cold start / WS stalled). We surface that
  // explicitly with - instead of fabricating $0 / 50% neutral.
  const buyVolRaw = volumeProfile.buy_volume;
  const sellVolRaw = volumeProfile.sell_volume;
  const volProfileAvailable = buyVolRaw !== null && buyVolRaw !== undefined &&
                              sellVolRaw !== null && sellVolRaw !== undefined;
  const buyVol = volProfileAvailable ? num(buyVolRaw) : 0;
  const sellVol = volProfileAvailable ? num(sellVolRaw) : 0;
  const totalVol = buyVol + sellVol;
  const buyPct = totalVol > 0 ? (buyVol / totalVol) * 100 : 50;
  const sellPct = 100 - buyPct;
  const tradeFlowRaw = data.trade_flow_ratio;
  const tradeFlowAvailable = tradeFlowRaw !== null && tradeFlowRaw !== undefined;
  const tradeFlow = tradeFlowAvailable ? num(tradeFlowRaw) : 0;
  const oiChangeRaw = data.oi_change_1h;
  const oiChangeAvailable = oiChangeRaw !== null && oiChangeRaw !== undefined;
  const oiChange = oiChangeAvailable ? num(oiChangeRaw) : 0;
  const maxCvd = Math.max(...cvdEntries.map(([, v]) => Math.abs(num(v?.cvd))), 1);
  const tradeSource = data.source?.trades ?? null;
  // A CVD timeframe is "available" if its trade_count > 0 OR backend signals
  // available:true. Distinguishes 0-flow (real signal) from no-data (warmup).
  const cvdAvailable = (d: CvdTf | undefined): boolean =>
    Boolean(d?.available) || num(d?.trade_count) > 0;

  return (
    <div className="flex flex-col gap-2 h-full animate-slide-in">
      {/* Row 0: Quant intelligence - OBI · Funding z-score · Tape speed · Session */}
      <div className="flex gap-2" style={{ minHeight: 0 }}>
        <ObiCard data={obi ?? null} />
        <FundingZCard data={funding ?? null} />
        <TapeSpeedCard data={tape ?? null} />
        <SessionContextCard />
      </div>

      {/* Row 1: CVD Multi-timeframe */}
      <div className="card">
        <div className="card-header">
          <span>CUMULATIVE VOLUME DELTA - {symbol}</span>
          <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {tradeSource ? (
              <span style={{
                fontSize: "var(--fs-data-xs)",
                color: "var(--text-tertiary)",
                letterSpacing: "0.10em",
                fontWeight: 600,
              }}>
                SRC: {tradeSource.toUpperCase()}
              </span>
            ) : (
              <span style={{ fontSize: "var(--fs-data-xs)", color: "#c6c6c7", fontWeight: 700, letterSpacing: "0.12em" }}>
                NO TRADE FEED
              </span>
            )}
            <span className="animate-pulse-live" style={{ color: "var(--accent-green)", fontSize: "var(--fs-data-xs)" }}>LIVE</span>
          </span>
        </div>
        <div className="card-body">
          {cvdEntries.length === 0 ? (
            <div style={{ color: "var(--text-muted)", fontSize: "var(--fs-data-xs)" }}>Waiting for CVD data...</div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: `repeat(${cvdEntries.length}, 1fr)`, gap: 8 }}>
              {cvdEntries.map(([tf, d]) => {
                const available = cvdAvailable(d);
                const val = available ? num(d?.cvd) : 0;
                const isPos = val >= 0;
                const barHeight = (Math.abs(val) / maxCvd) * 60;
                const tradeCount = num(d?.trade_count);
                return (
                  <div key={tf} className="flex flex-col items-center" style={{ opacity: available ? 1 : 0.5 }}>
                    <div style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-tertiary)", fontWeight: 700, marginBottom: 4 }}>
                      {tf.toUpperCase()}
                    </div>
                    <div style={{ width: "100%", height: 70, position: "relative", display: "flex", flexDirection: "column", justifyContent: "center" }}>
                      <div style={{ position: "absolute", top: "50%", left: 0, right: 0, height: 1, background: "var(--border-primary)" }} />
                      {available ? (
                        <div
                          style={{
                            position: "absolute",
                            left: "15%",
                            right: "15%",
                            height: barHeight,
                            background: isPos ? "rgba(0,200,83,0.3)" : "rgba(239,68,68,0.3)",
                            borderRadius: 2,
                            ...(isPos
                              ? { bottom: "50%", borderBottom: `2px solid var(--accent-green)` }
                              : { top: "50%", borderTop: `2px solid var(--accent-red)` }),
                          }}
                        />
                      ) : null}
                    </div>
                    <div style={{
                      fontSize: "var(--fs-data)",
                      fontWeight: 700,
                      color: !available ? "var(--text-muted)" : isPos ? "var(--accent-green)" : "var(--accent-red)",
                      marginTop: 4,
                    }}>
                      {available ? fmtUSD(val, { signed: true }) : "-"}
                    </div>
                    <div style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-muted)" }}>
                      {available ? `${tradeCount.toLocaleString()} trades` : "no data"}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Row 2: Volume Profile + Absorption */}
      <div className="flex gap-2">
        <div className="card flex-1">
          <div className="card-header">VOLUME PROFILE</div>
          <div className="card-body">
            <div className="flex items-center gap-2 mb-2" style={{ opacity: volProfileAvailable ? 1 : 0.55 }}>
              <div style={{ flex: 1 }}>
                <div className="flex justify-between mb-1" style={{ fontSize: "var(--fs-data-xs)" }}>
                  <span style={{ color: volProfileAvailable ? "var(--accent-green)" : "var(--text-muted)" }}>
                    {volProfileAvailable ? `BUY ${buyPct.toFixed(1)}%` : "BUY -"}
                  </span>
                  <span style={{ color: volProfileAvailable ? "var(--accent-red)" : "var(--text-muted)" }}>
                    {volProfileAvailable ? `SELL ${sellPct.toFixed(1)}%` : "SELL -"}
                  </span>
                </div>
                <div style={{ height: 12, display: "flex", borderRadius: 2, overflow: "hidden" }}>
                  <div style={{ width: volProfileAvailable ? `${buyPct}%` : "0%", background: "var(--accent-green)", opacity: 0.6 }} />
                  <div style={{ width: volProfileAvailable ? `${sellPct}%` : "0%", background: "var(--accent-red)", opacity: 0.6 }} />
                </div>
              </div>
            </div>
            <div className="flex justify-between" style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-tertiary)" }}>
              <span>Buy: {volProfileAvailable ? fmtUSD(buyVol) : "-"}</span>
              <span>Sell: {volProfileAvailable ? fmtUSD(sellVol) : "-"}</span>
            </div>
            <div className="flex justify-between mt-2" style={{ fontSize: "var(--fs-data-sm)" }}>
              <span style={{ color: "var(--text-tertiary)" }}>Trade Flow Ratio</span>
              <span style={{
                fontWeight: 700,
                color: !tradeFlowAvailable ? "var(--text-muted)" :
                       tradeFlow > 0.55 ? "var(--accent-green)" :
                       tradeFlow < 0.45 ? "var(--accent-red)" : "var(--text-secondary)"
              }}>
                {tradeFlowAvailable ? `${(tradeFlow * 100).toFixed(1)}% BUY` : "-"}
              </span>
            </div>
            <div className="flex justify-between mt-1" style={{ fontSize: "var(--fs-data-sm)" }}>
              <span style={{ color: "var(--text-tertiary)" }}>OI Change (1h)</span>
              <span style={{
                fontWeight: 700,
                color: !oiChangeAvailable ? "var(--text-muted)" :
                       oiChange > 0 ? "var(--accent-green)" :
                       oiChange < 0 ? "var(--accent-red)" : "var(--text-secondary)"
              }}>
                {!oiChangeAvailable ? "-" : `${oiChange > 0 ? "+" : ""}${fmtPct(oiChange)}`}
              </span>
            </div>
          </div>
        </div>

        <div className="card flex-1">
          <div className="card-header">ABSORPTION DETECTION</div>
          <div className="card-body flex flex-col items-center justify-center" style={{ minHeight: 100 }}>
            {absorption.detected ? (
              <>
                <div style={{
                  fontSize: "var(--fs-title)",
                  fontWeight: 800,
                  color: absorption.side === "bid" ? "var(--accent-green)" : "var(--accent-red)",
                  marginBottom: 4,
                }}>
                  {String(absorption.side || "").toUpperCase()} ABSORPTION
                </div>
                <div style={{ width: "100%", maxWidth: 200 }}>
                  <div className="flex justify-between" style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-tertiary)", marginBottom: 2 }}>
                    <span>WEAK</span>
                    <span>{(num(absorption.strength) * 100).toFixed(0)}%</span>
                    <span>STRONG</span>
                  </div>
                  <div style={{ height: 6, background: "var(--bg-active)", borderRadius: 3, overflow: "hidden" }}>
                    <div style={{
                      height: "100%",
                      width: `${num(absorption.strength) * 100}%`,
                      borderRadius: 3,
                      background: absorption.side === "bid" ? "var(--accent-green)" : "var(--accent-red)",
                    }} />
                  </div>
                </div>
                <div style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-tertiary)", marginTop: 4 }}>
                  Large orders being absorbed without price movement
                </div>
              </>
            ) : (
              <div style={{ color: "var(--text-muted)", fontSize: "var(--fs-data)" }}>
                No absorption detected
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Row 3: Large Trades Feed */}
      <div className="card flex-1 min-h-0">
        <div className="card-header">
          <span>LARGE TRADE FLOW ({largeTrades.length})</span>
          <span style={{ color: "var(--text-muted)" }}>Whale-sized transactions</span>
        </div>
        <div className="card-body" style={{ padding: 0, overflow: "auto", maxHeight: "calc(100vh - 450px)" }}>
          {largeTrades.length === 0 ? (
            <div style={{ padding: 12, color: "var(--text-muted)", fontSize: "var(--fs-data-xs)" }}>
              Waiting for large trades...
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Side</th>
                  <th>Price</th>
                  <th className="col-right">Size</th>
                  <th className="col-right">USD Value</th>
                  <th className="col-right">Time</th>
                </tr>
              </thead>
              <tbody>
                {largeTrades.map((t, i) => (
                  <tr key={i}>
                    <td>
                      <span style={{
                        color: t.side === "buy" ? "var(--accent-green)" : "var(--accent-red)",
                        fontWeight: 700,
                      }}>
                        {String(t.side || "").toUpperCase()}
                      </span>
                    </td>
                    <td style={{ fontWeight: 600 }}>${fmtPrice(t.price)}</td>
                    <td className="col-right">{fmtFixed(t.qty, 4)}</td>
                    <td className="col-right" style={{ fontWeight: 600, color: "var(--accent-amber)" }}>
                      {fmtUSD(t.usd_value)}
                    </td>
                    <td className="col-right" style={{ color: "var(--text-muted)" }}>{String(t.time_ago || "")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// Order book imbalance - sparkline + bias badge
// =============================================================================
function ObiCard({ data }: { data: ObiPayload | null }) {
  const series = data?.series ?? [];
  const latest = data?.summary?.latest ?? 0;
  const bias = data?.summary?.bias ?? "no_data";

  const tone =
    latest >= 0.2 ? "var(--accent-green)"
      : latest >= 0.05 ? "var(--accent-green)"
      : latest <= -0.2 ? "var(--accent-red)"
      : latest <= -0.05 ? "var(--accent-red)"
      : "var(--text-secondary)";

  // Build sparkline path: x is index, y normalized to [-1, 1] mapped to [H, 0]
  const W = 240, H = 48;
  const points = series.length >= 2
    ? series.map((s, i) => {
        const x = (i / (series.length - 1)) * W;
        const y = H / 2 - (s.obi * H / 2);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(" ")
    : "";

  return (
    <div className="card flex-1" style={{ minWidth: 0 }}>
      <div className="card-header">
        <span>ORDER BOOK IMBALANCE</span>
        <span style={{ fontSize: 10, letterSpacing: "0.14em", color: tone, fontWeight: 700 }}>
          {bias.replace(/_/g, " ").toUpperCase()}
        </span>
      </div>
      <div className="card-body">
        <div className="flex items-baseline gap-3" style={{ marginBottom: 6 }}>
          <span className="text-mono" style={{ color: tone, fontWeight: 800, fontSize: 26, lineHeight: 1 }}>
            {latest > 0 ? "+" : ""}{latest.toFixed(3)}
          </span>
          <span style={{ color: "var(--text-tertiary)", fontSize: 10, letterSpacing: "0.1em" }}>
            n={data?.summary?.count ?? 0}
          </span>
        </div>
        <svg
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
          style={{ width: "100%", height: 48, display: "block" }}
        >
          <line x1={0} x2={W} y1={H / 2} y2={H / 2} stroke="var(--hairline)" strokeWidth="1" strokeDasharray="2 3" />
          {points ? (
            <polyline points={points} fill="none" stroke={tone} strokeWidth="1.5" />
          ) : (
            <text x={W / 2} y={H / 2 + 4} textAnchor="middle" fontSize="10" fill="var(--text-muted)">
              sampling…
            </text>
          )}
        </svg>
        <div className="flex justify-between" style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2 }}>
          <span>min {data?.summary?.min?.toFixed(2) ?? "-"}</span>
          <span>μ {data?.summary?.mean?.toFixed(3) ?? "-"}</span>
          <span>max {data?.summary?.max?.toFixed(2) ?? "-"}</span>
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// Funding z-score gauge
// =============================================================================
function FundingZCard({ data }: { data: FundingPayload | null }) {
  const z = data?.zscore ?? 0;
  const rate = data?.weighted_rate_pct ?? 0;
  const cls = data?.zscore_classification ?? "no_data";

  const tone =
    Math.abs(z) >= 2 ? (z > 0 ? "var(--accent-red)" : "var(--accent-green)")
      : Math.abs(z) >= 1 ? "var(--accent-amber)"
      : "var(--text-secondary)";

  // Clamp z to [-3, 3] for the bar.
  const zClamped = Math.max(-3, Math.min(3, z));
  const pct = ((zClamped + 3) / 6) * 100;

  return (
    <div className="card flex-1" style={{ minWidth: 0 }}>
      <div className="card-header">
        <span>FUNDING Z-SCORE</span>
        <span style={{ fontSize: 10, letterSpacing: "0.14em", color: tone, fontWeight: 700 }}>
          {cls.replace(/_/g, " ").toUpperCase()}
        </span>
      </div>
      <div className="card-body">
        <div className="flex items-baseline gap-3" style={{ marginBottom: 8 }}>
          <span className="text-mono" style={{ color: tone, fontWeight: 800, fontSize: 26, lineHeight: 1 }}>
            {z > 0 ? "+" : ""}{z.toFixed(2)}σ
          </span>
          <span className="text-mono" style={{ color: "var(--text-tertiary)", fontSize: 11 }}>
            rate {rate >= 0 ? "+" : ""}{rate.toFixed(4)}%
          </span>
        </div>
        <div style={{ position: "relative", height: 8, background: "var(--bg-active)", borderRadius: 2, overflow: "hidden" }}>
          <div
            style={{
              position: "absolute",
              inset: 0,
              background:
                "linear-gradient(90deg, var(--accent-green) 0%, rgba(0,200,83,0.25) 33%, rgba(255,255,255,0.08) 50%, rgba(239,68,68,0.25) 67%, var(--accent-red) 100%)",
              opacity: 0.55,
            }}
          />
          <div
            style={{
              position: "absolute",
              left: `${pct}%`,
              top: -3,
              transform: "translateX(-50%)",
              width: 2,
              height: 14,
              background: tone,
              boxShadow: `0 0 6px ${tone}`,
            }}
          />
        </div>
        <div className="flex justify-between" style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 4, letterSpacing: "0.08em" }}>
          <span>-3σ SHORT</span>
          <span>0</span>
          <span>+3σ LONG</span>
        </div>
        <div style={{ fontSize: 10, color: "var(--text-tertiary)", marginTop: 4 }}>
          Window: {data?.zscore_window ?? 0} samples (≈ {Math.round((data?.zscore_window ?? 0) / 6)}h @ 10m funding)
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// Tape speed - trades/sec sparkline with burst badge
// =============================================================================
function TapeSpeedCard({ data }: { data: TapePayload | null }) {
  const series = data?.series ?? [];
  const latest = data?.summary?.latest ?? 0;
  const mean = data?.summary?.mean ?? 0;
  const max = data?.summary?.max ?? 1;
  const burst = !!data?.summary?.burst;

  const tone = burst ? "var(--accent-amber)" : latest > mean ? "var(--accent-green)" : "var(--text-secondary)";

  const W = 240, H = 48;
  const ceiling = Math.max(max, 1);
  const points = series.length >= 2
    ? series.map((s, i) => {
        const x = (i / (series.length - 1)) * W;
        const y = H - (s.tps / ceiling) * H;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(" ")
    : "";

  return (
    <div className="card flex-1" style={{ minWidth: 0 }}>
      <div className="card-header">
        <span>TAPE SPEED</span>
        <span style={{
          fontSize: 10, letterSpacing: "0.14em", fontWeight: 700,
          color: burst ? "var(--accent-amber)" : "var(--text-tertiary)",
        }}>
          {burst ? "● BURST" : "NORMAL"}
        </span>
      </div>
      <div className="card-body">
        <div className="flex items-baseline gap-3" style={{ marginBottom: 6 }}>
          <span className="text-mono" style={{ color: tone, fontWeight: 800, fontSize: 26, lineHeight: 1 }}>
            {latest.toFixed(1)}
          </span>
          <span style={{ color: "var(--text-tertiary)", fontSize: 10, letterSpacing: "0.08em" }}>
            tps · 5s window
          </span>
        </div>
        <svg
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
          style={{ width: "100%", height: 48, display: "block" }}
        >
          <line
            x1={0} x2={W}
            y1={H - (mean / ceiling) * H}
            y2={H - (mean / ceiling) * H}
            stroke="var(--hairline)"
            strokeWidth="1"
            strokeDasharray="2 3"
          />
          {points ? (
            <polyline points={points} fill="none" stroke={tone} strokeWidth="1.5" />
          ) : (
            <text x={W / 2} y={H / 2 + 4} textAnchor="middle" fontSize="10" fill="var(--text-muted)">
              sampling…
            </text>
          )}
        </svg>
        <div className="flex justify-between" style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2 }}>
          <span>μ {mean.toFixed(1)}</span>
          <span>σ {data?.summary?.std?.toFixed(1) ?? "-"}</span>
          <span>max {max.toFixed(1)}</span>
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// Trading session context - Asia / London / NY active bands (UTC hours)
// =============================================================================
const SESSIONS = [
  { key: "asia",   label: "ASIA",   start: 0,  end: 8,  color: "#60a5fa" },
  { key: "london", label: "LONDON", start: 7,  end: 16, color: "#c6c6c7" },
  { key: "ny",     label: "NY",     start: 13, end: 22, color: "#16c784" },
];

function SessionContextCard() {
  const [now, setNow] = useState<Date>(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 30000);
    return () => clearInterval(id);
  }, []);

  const h = now.getUTCHours() + now.getUTCMinutes() / 60;
  const active = SESSIONS.filter((s) => h >= s.start && h < s.end);
  const overlap = active.length >= 2;

  return (
    <div className="card flex-1" style={{ minWidth: 0 }}>
      <div className="card-header">
        <span>SESSION CONTEXT</span>
        <span
          className="text-mono"
          style={{ fontSize: 10, letterSpacing: "0.12em", color: overlap ? "var(--accent-amber)" : "var(--text-tertiary)", fontWeight: 700 }}
        >
          {overlap ? "OVERLAP · HIGH LIQUIDITY" : active.length ? "REGULAR" : "OFF-HOURS"}
        </span>
      </div>
      <div className="card-body">
        <div className="flex items-baseline gap-2" style={{ marginBottom: 10 }}>
          <span className="text-mono" style={{ color: "var(--text-primary)", fontWeight: 800, fontSize: 22, lineHeight: 1 }}>
            {now.toISOString().slice(11, 16)} UTC
          </span>
          <span style={{ color: "var(--text-tertiary)", fontSize: 10, letterSpacing: "0.12em" }}>
            {active.length ? active.map((s) => s.label).join(" + ") : "NO MAJOR SESSION"}
          </span>
        </div>
        <div style={{ position: "relative", height: 22, background: "var(--bg-active)", borderRadius: 2, overflow: "hidden" }}>
          {SESSIONS.map((s) => {
            const left = (s.start / 24) * 100;
            const width = ((s.end - s.start) / 24) * 100;
            const on = h >= s.start && h < s.end;
            return (
              <div
                key={s.key}
                title={`${s.label} ${s.start}-${s.end} UTC`}
                style={{
                  position: "absolute",
                  left: `${left}%`,
                  width: `${width}%`,
                  top: 0,
                  bottom: 0,
                  background: s.color,
                  opacity: on ? 0.55 : 0.15,
                  borderRight: "1px solid rgba(0,0,0,0.25)",
                }}
              />
            );
          })}
          <div
            style={{
              position: "absolute",
              left: `${(h / 24) * 100}%`,
              top: -2,
              bottom: -2,
              width: 2,
              background: "#fff",
              boxShadow: "0 0 6px rgba(255,255,255,0.9)",
            }}
          />
        </div>
        <div className="flex justify-between" style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 4, letterSpacing: "0.08em" }}>
          {SESSIONS.map((s) => (
            <span key={s.key} style={{ color: h >= s.start && h < s.end ? s.color : "var(--text-muted)" }}>
              {s.label} {s.start}-{s.end}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
