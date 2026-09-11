"use client";

import { memo, useMemo } from "react";
import { usePolling } from "@/lib/usePolling";
import { fmtCompact, fmtUSD, fmtPrice, num } from "@/lib/format";
import ParticleField from "@/components/ParticleField";

interface Props {
  symbol: string;
  api: string;
}

interface WallContributor {
  exchange?: string;
  qty?: number;
  usd_value?: number;
}

interface Wall {
  price?: number;
  side?: string;
  total_size?: number;
  usd_value?: number;
  persistence?: number;
  contributors?: WallContributor[];
}

interface Void {
  price_start?: number;
  price_end?: number;
  avg_depth?: number;
}

interface LiqCluster {
  price?: number;
  estimated_size_usd?: number;
  side?: string;
}

interface InstLevel {
  price?: number;
  qty?: number;
  usd_value?: number;
  intensity?: number;
  contributors?: WallContributor[];
}

interface InstitutionalDepth {
  bids?: InstLevel[];
  asks?: InstLevel[];
  mid_price?: number;
  total_bid_usd?: number;
  total_ask_usd?: number;
  imbalance?: number;
  bin_usd?: number;
  min_usd_per_level?: number;
  max_usd?: number;
}

interface HeatmapData {
  price_levels?: number[];
  time_labels?: string[];
  bid_intensity?: number[][];
  ask_intensity?: number[][];
  liquidation_clusters?: LiqCluster[];
  walls?: Wall[];
  voids?: Void[];
  current_price?: number;
  depth_profile?: {
    bid_prices?: number[];
    bid_cumulative?: number[];
    ask_prices?: number[];
    ask_cumulative?: number[];
    imbalance?: number;
  };
  institutional_depth?: InstitutionalDepth;
  exchanges?: string[];
  exchange_count?: number;
}

export default function HeatmapTab({ symbol, api }: Props) {
  const { data, loading, error, refetch } = usePolling<HeatmapData>({
    url: `${api}/api/heatmap/${symbol}`,
    intervalMs: 3000,
  });

  if (loading && !data) {
    return (
      <div className="flex flex-col gap-2 p-2">
        <div className="skeleton" style={{ height: 400 }} />
        <div className="flex gap-2">
          <div className="skeleton flex-1" style={{ height: 120 }} />
          <div className="skeleton flex-1" style={{ height: 120 }} />
        </div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="card" style={{ padding: 24, textAlign: "center" }}>
          <div style={{ color: "var(--accent-red)", fontSize: "var(--fs-title)", fontWeight: 700, marginBottom: 8 }}>
            HEATMAP UNAVAILABLE
          </div>
          <div style={{ color: "var(--text-secondary)", fontSize: "var(--fs-data)" }}>{error}</div>
          <button onClick={refetch} className="btn-primary" style={{ marginTop: 12 }}>RETRY</button>
        </div>
      </div>
    );
  }

  if (!data) return null;

  // Normalize defensively - backend may omit any of these fields early on
  const priceLevels = data.price_levels ?? [];
  const timeLabels = data.time_labels ?? [];
  const walls = data.walls ?? [];
  const voids = data.voids ?? [];
  const clusters = data.liquidation_clusters ?? [];
  const currentPrice = num(data.current_price);
  const profile = data.depth_profile ?? {};
  const inst = data.institutional_depth;
  const hasInst = !!(inst && ((inst.bids?.length ?? 0) > 0 || (inst.asks?.length ?? 0) > 0));
  const imbalance = hasInst ? num(inst!.imbalance) : num(profile.imbalance);
  const minLevelUsd = num(inst?.min_usd_per_level);
  const binUsd = num(inst?.bin_usd);

  return (
    <div
      className="flex flex-col gap-2 h-full animate-slide-in"
      style={{ minHeight: 0 }}
    >
      <div
        className="flex items-center justify-between"
        style={{ flexShrink: 0 }}
      >
        <span style={{ fontSize: "var(--fs-title)", fontWeight: 700 }}>
          {symbol} Liquidity Map
        </span>
        <div className="flex items-center gap-3" style={{ fontSize: "var(--fs-data-sm)" }}>
          <span style={{ color: "var(--text-tertiary)" }}>
            Price: <span style={{ color: "var(--accent-amber)", fontWeight: 700 }}>
              ${fmtPrice(currentPrice)}
            </span>
          </span>
          <span style={{ color: "var(--text-tertiary)" }}>
            Imbalance: <span style={{
              color: imbalance > 0.1 ? "var(--accent-green)"
                : imbalance < -0.1 ? "var(--accent-red)"
                : "var(--text-secondary)",
              fontWeight: 700,
            }}>
              {(imbalance * 100).toFixed(1)}%
            </span>
          </span>
          {(data.exchanges?.length ?? 0) > 0 && (
            <span style={{ color: "var(--text-tertiary)" }}>
              Venues: <span style={{ color: "var(--accent-amber)", fontWeight: 700 }}>
                {data.exchanges!.map((e) => e.toUpperCase()).join(" + ")}
              </span>
            </span>
          )}
          <span className="animate-pulse-live" style={{ color: "var(--accent-green)", fontSize: "var(--fs-data-xs)" }}>LIVE</span>
        </div>
      </div>

      {/* Two-column main grid: left = heatmap+depth (stacked), right = detail rail */}
      <div
        className="flex-1"
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0,1fr) 320px",
          gap: 8,
          minHeight: 0,
        }}
      >
        {/* LEFT column - heatmap (top, fills) + institutional depth (bottom) */}
        <div style={{ display: "flex", flexDirection: "column", gap: 8, minHeight: 0 }}>
          <div className="card" style={{ flex: "1 1 0", minHeight: 0, display: "flex", flexDirection: "column" }}>
            <div className="card-header" style={{ flexShrink: 0 }}>
              <span>LIQUIDITY HEATMAP - {symbol}</span>
              <span style={{ color: "var(--text-muted)" }}>
                {timeLabels.length} time bins × {priceLevels.length} price levels
              </span>
            </div>
            <div className="card-body" style={{ padding: 0, flex: 1, minHeight: 0, overflow: "hidden" }}>
              <HeatmapGrid
                priceLevels={priceLevels}
                timeLabels={timeLabels}
                bidIntensity={data.bid_intensity ?? []}
                askIntensity={data.ask_intensity ?? []}
                currentPrice={currentPrice}
              />
            </div>
          </div>

          <div className="card" style={{ flex: "0 0 auto", maxHeight: "40%", display: "flex", flexDirection: "column" }}>
            <div className="card-header" style={{ flexShrink: 0 }}>
              <span>{hasInst ? "INSTITUTIONAL DEPTH" : "ORDER BOOK DEPTH"}</span>
              <span style={{ color: "var(--text-muted)" }}>
                {hasInst && minLevelUsd > 0
                  ? `≥ ${fmtUSD(minLevelUsd)} / ${binUsd > 0 ? `$${binUsd}` : "tick"}`
                  : `${imbalance > 0 ? "BID" : "ASK"} skew`}
              </span>
            </div>
            <div className="card-body" style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
              {hasInst ? (
                <InstitutionalDepthView inst={inst!} currentPrice={currentPrice} />
              ) : (
                <DepthProfileView profile={profile} currentPrice={currentPrice} />
              )}
            </div>
          </div>
        </div>

        {/* RIGHT column - detail rail (clusters / walls / voids stack and grow to fill) */}
        <div style={{ display: "flex", flexDirection: "column", gap: 8, minHeight: 0 }}>
          <LiquidationClusters clusters={clusters} />
          <WallsPanel walls={walls} />
          <VoidsPanel voids={voids} />
          {/* Open-space ASCII geometry - fills all remaining height in the
              right rail; moving block-char interference patterns. */}
          <AsciiStrip />
        </div>
      </div>
    </div>
  );
}

/* ---- Open-space ASCII strip ---------------------------------------------
   Distinct from the Risk page's flow field. Moving geometric ASCII patterns
   (diamond + ring wave interference) on a monospace grid; flexes to fill
   the open tail of the right rail down to the bottom edge. */
function AsciiStrip() {
  return (
    <div
      style={{
        position: "relative",
        flex: "1 1 140px",
        minHeight: 140,
        // Break out of the page's 16px padding - touch the page's right + bottom edges
        marginRight: -16,
        marginBottom: -16,
        background: "var(--surface-container-lowest)",
        borderTop: "1px solid var(--hairline)",
        borderLeft: "1px solid var(--hairline)",
        overflow: "hidden",
      }}
    >
      <ParticleField mode="ascii" intensity={0.85} density={0.45} edgeToEdge />
      <div
        style={{
          position: "absolute",
          top: 8, left: 12, right: 12,
          display: "flex", justifyContent: "space-between", alignItems: "baseline",
          zIndex: 2, pointerEvents: "none",
        }}
      >
        <span
          className="eyebrow"
          style={{ color: "var(--on-surface-dim)", fontSize: 10, letterSpacing: "0.18em" }}
        >
          DEPTH GEOMETRY
        </span>
        <span style={{ color: "var(--on-surface-muted)", fontSize: 9, letterSpacing: "0.14em" }}>
          ASCII · LIVE
        </span>
      </div>
    </div>
  );
}

/* ---- Heatmap Grid ----
 * 1000+ cells render path. Two memoization seams keep this cheap:
 *   1. `cellGrid` - useMemo-ed JSX over (priceLevels, timeLabels, bid/ask matrices, cpIdx)
 *   2. `HeatmapGrid` itself wrapped in React.memo - parent state churn (e.g. price tick)
 *      no longer reconciles every cell when matrices haven't changed reference. */
const HeatmapGrid = memo(function HeatmapGrid({
  priceLevels,
  timeLabels,
  bidIntensity,
  askIntensity,
  currentPrice,
}: {
  priceLevels: number[];
  timeLabels: string[];
  bidIntensity: number[][];
  askIntensity: number[][];
  currentPrice: number;
}) {
  const cpIdx = useMemo(() => {
    for (let i = 0; i < priceLevels.length - 1; i++) {
      if (priceLevels[i] <= currentPrice && priceLevels[i + 1] > currentPrice) return i;
    }
    return -1;
  }, [priceLevels, currentPrice]);

  const labelEvery = useMemo(
    () => Math.max(1, Math.floor(priceLevels.length / 20)),
    [priceLevels.length],
  );
  const timeLabelEvery = useMemo(
    () => Math.max(1, Math.floor(timeLabels.length / 10)),
    [timeLabels.length],
  );

  // Pre-compute the cell color matrix once per data change. Avoids repeated
  // string concatenation inside the hot render loop on parent re-renders.
  const cellBg = useMemo(() => {
    const out: string[][] = [];
    for (let i = 0; i < priceLevels.length; i++) {
      const row: string[] = new Array(timeLabels.length);
      for (let j = 0; j < timeLabels.length; j++) {
        const bidVal = bidIntensity[i]?.[j] ?? 0;
        const askVal = askIntensity[i]?.[j] ?? 0;
        if (bidVal > askVal && bidVal > 0.05) row[j] = bidColor(bidVal);
        else if (askVal > bidVal && askVal > 0.05) row[j] = askColor(askVal);
        else row[j] = "var(--bg-primary)";
      }
      out.push(row);
    }
    return out;
  }, [priceLevels, timeLabels, bidIntensity, askIntensity]);

  const priceColumn = useMemo(
    () =>
      priceLevels.map((p, i) => (
        <div
          key={i}
          style={{
            flex: 1,
            minHeight: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "flex-end",
            color: i === cpIdx ? "var(--accent-amber)" : "var(--text-muted)",
            fontWeight: i === cpIdx ? 700 : 400,
            fontSize: 8,
            lineHeight: 1,
            overflow: "hidden",
          }}
        >
          {i % labelEvery === 0 ? `$${num(p).toLocaleString()}` : ""}
        </div>
      )),
    [priceLevels, cpIdx, labelEvery],
  );

  const timeRow = useMemo(
    () =>
      timeLabels.map((t, j) => (
        <div
          key={j}
          style={{
            flex: 1,
            minWidth: 4,
            textAlign: "center",
            color: "var(--text-muted)",
            fontSize: 7,
          }}
        >
          {j % timeLabelEvery === 0 ? t : ""}
        </div>
      )),
    [timeLabels, timeLabelEvery],
  );

  const cellGrid = useMemo(
    () =>
      priceLevels.map((_, i) => {
        const isCurrent = i === cpIdx;
        return (
          <div key={i} style={{ display: "flex", flex: 1, minHeight: 0 }}>
            {timeLabels.map((_, j) => (
              <div
                key={j}
                className="heatmap-cell"
                style={{
                  flex: 1,
                  minWidth: 4,
                  background: cellBg[i]?.[j] ?? "var(--bg-primary)",
                  borderBottom: isCurrent ? "1px solid var(--accent-amber)" : "none",
                }}
              />
            ))}
          </div>
        );
      }),
    [priceLevels, timeLabels, cellBg, cpIdx],
  );

  if (priceLevels.length === 0 || timeLabels.length === 0) {
    return (
      <div className="flex items-center justify-center" style={{ height: "100%", color: "var(--text-tertiary)" }}>
        Collecting order book data...
      </div>
    );
  }

  return (
    <div style={{ display: "flex", fontSize: "var(--fs-data-xs)", contain: "layout paint", height: "100%", width: "100%" }}>
      <div style={{ display: "flex", flexDirection: "column", minWidth: 65, paddingRight: 4, height: "100%" }}>
        <div style={{ height: 18, flexShrink: 0 }} />
        <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
          {priceColumn}
        </div>
      </div>

      <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column", height: "100%", minWidth: 0 }}>
        <div style={{ display: "flex", height: 18, marginBottom: 1, flexShrink: 0 }}>
          {timeRow}
        </div>
        <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
          {cellGrid}
        </div>
      </div>
    </div>
  );
});

/* ---- Institutional Depth (USD-binned, retail filtered) ---- */
function InstitutionalDepthView({
  inst,
  currentPrice,
}: {
  inst: InstitutionalDepth;
  currentPrice: number;
}) {
  // Asks rendered top-down (highest → lowest), bids top-down (highest → lowest)
  const asks = (inst.asks ?? []).slice().sort((a, b) => num(b.price) - num(a.price));
  const bids = (inst.bids ?? []).slice().sort((a, b) => num(b.price) - num(a.price));
  const totalBid = num(inst.total_bid_usd);
  const totalAsk = num(inst.total_ask_usd);

  const renderRow = (lv: InstLevel, side: "bid" | "ask", key: string) => {
    const intensity = Math.max(0, Math.min(1, num(lv.intensity)));
    const usd = num(lv.usd_value);
    const contribs = (lv.contributors ?? []).filter((c) => num(c.usd_value) > 0);
    const baseColor = side === "bid" ? "0,200,83" : "239,68,68";
    const accentColor = side === "bid" ? "var(--accent-green)" : "var(--accent-red)";
    const barWidth = Math.max(2, intensity * 100);
    const isMega = intensity >= 0.6;

    return (
      <div
        key={key}
        style={{
          position: "relative",
          padding: "3px 6px",
          marginBottom: 1,
          borderLeft: `2px solid rgba(${baseColor},${0.35 + intensity * 0.55})`,
          background: `linear-gradient(90deg, rgba(${baseColor},${0.05 + intensity * 0.18}) 0%, rgba(${baseColor},${0.02 + intensity * 0.08}) ${barWidth}%, transparent ${barWidth}%)`,
        }}
      >
        <div className="flex items-center justify-between" style={{ fontSize: "var(--fs-data-xs)" }}>
          <span style={{
            color: accentColor,
            fontWeight: 700,
            fontVariantNumeric: "tabular-nums",
          }}>
            ${fmtPrice(num(lv.price))}
          </span>
          <span style={{
            color: isMega ? "var(--accent-amber)" : "var(--text-primary)",
            fontWeight: isMega ? 700 : 600,
            fontVariantNumeric: "tabular-nums",
          }}>
            {fmtUSD(usd)}
          </span>
        </div>
        {contribs.length > 0 && (
          <div className="flex flex-wrap" style={{ gap: 3, marginTop: 2 }}>
            {contribs.slice(0, 4).map((c, ci) => (
              <span
                key={ci}
                style={{
                  fontSize: 9,
                  color: "var(--text-muted)",
                  background: "var(--bg-active, rgba(255,255,255,0.04))",
                  padding: "0 4px",
                  borderRadius: 2,
                  letterSpacing: 0.3,
                }}
              >
                {String(c.exchange ?? "?").toUpperCase()}
              </span>
            ))}
          </div>
        )}
      </div>
    );
  };

  return (
    <div>
      <div className="flex items-center justify-between" style={{
        fontSize: "var(--fs-data-xs)",
        color: "var(--text-tertiary)",
        marginBottom: 4,
        fontWeight: 700,
        letterSpacing: 0.5,
      }}>
        <span>ASKS · RESISTANCE</span>
        <span style={{ color: "var(--accent-red)" }}>{fmtUSD(totalAsk)}</span>
      </div>
      {asks.length === 0 ? (
        <div style={{ color: "var(--text-muted)", fontSize: "var(--fs-data-xs)", padding: "4px 0" }}>
          No institutional asks near mid
        </div>
      ) : (
        asks.map((lv, i) => renderRow(lv, "ask", `ask-${i}`))
      )}

      <div className="flex items-center gap-2 my-2" style={{ height: 22 }}>
        <div style={{ flex: 1, height: 1, background: "var(--accent-amber)", opacity: 0.6 }} />
        <span style={{
          fontSize: "var(--fs-data)",
          fontWeight: 700,
          color: "var(--accent-amber)",
          padding: "1px 8px",
          border: "1px solid var(--accent-amber)",
          borderRadius: 3,
          fontVariantNumeric: "tabular-nums",
        }}>
          ${fmtPrice(currentPrice)}
        </span>
        <div style={{ flex: 1, height: 1, background: "var(--accent-amber)", opacity: 0.6 }} />
      </div>

      <div className="flex items-center justify-between" style={{
        fontSize: "var(--fs-data-xs)",
        color: "var(--text-tertiary)",
        marginBottom: 4,
        fontWeight: 700,
        letterSpacing: 0.5,
      }}>
        <span>BIDS · SUPPORT</span>
        <span style={{ color: "var(--accent-green)" }}>{fmtUSD(totalBid)}</span>
      </div>
      {bids.length === 0 ? (
        <div style={{ color: "var(--text-muted)", fontSize: "var(--fs-data-xs)", padding: "4px 0" }}>
          No institutional bids near mid
        </div>
      ) : (
        bids.map((lv, i) => renderRow(lv, "bid", `bid-${i}`))
      )}
    </div>
  );
}

/* ---- Depth Profile ---- */
function DepthProfileView({
  profile,
  currentPrice,
}: {
  profile: NonNullable<HeatmapData["depth_profile"]>;
  currentPrice: number;
}) {
  const bidPrices = profile.bid_prices ?? [];
  const bidCum = profile.bid_cumulative ?? [];
  const askPrices = profile.ask_prices ?? [];
  const askCum = profile.ask_cumulative ?? [];

  const maxDepth = Math.max(
    bidCum.length > 0 ? Math.max(...bidCum) : 1,
    askCum.length > 0 ? Math.max(...askCum) : 1,
    1,
  );

  return (
    <div>
      <div style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-tertiary)", marginBottom: 4, fontWeight: 700 }}>
        BIDS (SUPPORT)
      </div>
      {bidPrices.map((price, i) => {
        const cum = num(bidCum[i]);
        const width = (cum / maxDepth) * 100;
        return (
          <div key={`bid-${i}`} className="flex items-center gap-2" style={{ height: 14, fontSize: "var(--fs-data-xs)" }}>
            <span style={{ width: 60, textAlign: "right", color: "var(--text-tertiary)" }}>
              ${num(price).toLocaleString()}
            </span>
            <div style={{ flex: 1, height: 8, background: "var(--bg-active)", borderRadius: 1, overflow: "hidden" }}>
              <div style={{ width: `${width}%`, height: "100%", background: "rgba(0,200,83,0.4)", borderRadius: 1 }} />
            </div>
            <span style={{ width: 50, textAlign: "right", color: "var(--accent-green)" }}>
              {fmtCompact(cum)}
            </span>
          </div>
        );
      })}

      <div className="flex items-center gap-2 my-2" style={{ height: 20 }}>
        <div style={{ flex: 1, height: 1, background: "var(--accent-amber)" }} />
        <span style={{ fontSize: "var(--fs-data)", fontWeight: 700, color: "var(--accent-amber)" }}>
          ${fmtPrice(currentPrice)}
        </span>
        <div style={{ flex: 1, height: 1, background: "var(--accent-amber)" }} />
      </div>

      <div style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-tertiary)", marginBottom: 4, fontWeight: 700 }}>
        ASKS (RESISTANCE)
      </div>
      {askPrices.map((price, i) => {
        const cum = num(askCum[i]);
        const width = (cum / maxDepth) * 100;
        return (
          <div key={`ask-${i}`} className="flex items-center gap-2" style={{ height: 14, fontSize: "var(--fs-data-xs)" }}>
            <span style={{ width: 60, textAlign: "right", color: "var(--text-tertiary)" }}>
              ${num(price).toLocaleString()}
            </span>
            <div style={{ flex: 1, height: 8, background: "var(--bg-active)", borderRadius: 1, overflow: "hidden" }}>
              <div style={{ width: `${width}%`, height: "100%", background: "rgba(239,68,68,0.4)", borderRadius: 1 }} />
            </div>
            <span style={{ width: 50, textAlign: "right", color: "var(--accent-red)" }}>
              {fmtCompact(cum)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/* ---- Side Panels ---- */
function LiquidationClusters({ clusters }: { clusters: LiqCluster[] }) {
  return (
    <div className="card">
      <div className="card-header">LIQUIDATION CLUSTERS ({clusters.length})</div>
      <div className="card-body" style={{ maxHeight: 150, overflowY: "auto" }}>
        {clusters.length === 0 ? (
          <div style={{ color: "var(--text-muted)", fontSize: "var(--fs-data-xs)" }}>No clusters detected</div>
        ) : (
          clusters.map((c, i) => {
            const side = String(c.side ?? "").toLowerCase();
            return (
              <div
                key={i}
                className="flex justify-between items-center"
                style={{ padding: "3px 0", borderBottom: "1px solid var(--border-primary)", fontSize: "var(--fs-data-xs)" }}
              >
                <div>
                  <span style={{ color: "var(--text-primary)", fontWeight: 600 }}>
                    ${num(c.price).toLocaleString()}
                  </span>
                  <span style={{ color: side === "long" ? "var(--accent-red)" : "var(--accent-green)", marginLeft: 4 }}>
                    {side.toUpperCase() || "-"} LIQ
                  </span>
                </div>
                <span style={{ color: "var(--accent-amber)", fontWeight: 600 }}>
                  {fmtUSD(c.estimated_size_usd)}
                </span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

function WallsPanel({ walls }: { walls: Wall[] }) {
  return (
    <div className="card">
      <div className="card-header">INSTITUTIONAL LIQUIDITY WALLS ({walls.length})</div>
      <div className="card-body" style={{ maxHeight: 220, overflowY: "auto" }}>
        {walls.length === 0 ? (
          <div style={{ color: "var(--text-muted)", fontSize: "var(--fs-data-xs)" }}>No walls detected</div>
        ) : (
          walls.map((w, i) => {
            const side = String(w.side ?? "").toLowerCase();
            const persistPct = num(w.persistence) * 100;
            const contribs = (w.contributors ?? []).filter((c) => num(c.usd_value) > 0);
            return (
              <div
                key={i}
                style={{ padding: "4px 0", borderBottom: "1px solid var(--border-primary)", fontSize: "var(--fs-data-xs)" }}
              >
                <div className="flex justify-between">
                  <span style={{ color: side === "bid" ? "var(--accent-green)" : "var(--accent-red)", fontWeight: 600 }}>
                    {side.toUpperCase() || "?"} @ ${num(w.price).toLocaleString()}
                  </span>
                  <span style={{ color: "var(--accent-amber)" }}>{fmtUSD(w.usd_value)}</span>
                </div>
                <div className="flex justify-between" style={{ color: "var(--text-muted)" }}>
                  <span>{num(w.total_size).toFixed(3)} units</span>
                  <span>persist: {persistPct.toFixed(0)}%</span>
                </div>
                {contribs.length > 0 && (
                  <div className="flex flex-wrap" style={{ gap: 6, marginTop: 3 }}>
                    {contribs.map((c, ci) => (
                      <span
                        key={ci}
                        style={{
                          color: "var(--text-secondary)",
                          background: "var(--bg-secondary, #1a1a25)",
                          padding: "1px 5px",
                          borderRadius: 3,
                          fontSize: "10px",
                        }}
                      >
                        {String(c.exchange ?? "?").toUpperCase()} {fmtUSD(c.usd_value)}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

function VoidsPanel({ voids }: { voids: Void[] }) {
  return (
    <div className="card">
      <div className="card-header">LIQUIDITY VOIDS ({voids.length})</div>
      <div className="card-body" style={{ maxHeight: 120, overflowY: "auto" }}>
        {voids.length === 0 ? (
          <div style={{ color: "var(--text-muted)", fontSize: "var(--fs-data-xs)" }}>No voids detected</div>
        ) : (
          voids.map((v, i) => (
            <div
              key={i}
              className="flex justify-between"
              style={{ padding: "3px 0", borderBottom: "1px solid var(--border-primary)", fontSize: "var(--fs-data-xs)" }}
            >
              <span style={{ color: "var(--accent-orange)", fontWeight: 600 }}>
                ${num(v.price_start).toLocaleString()} - ${num(v.price_end).toLocaleString()}
              </span>
              <span style={{ color: "var(--text-muted)" }}>thin ({num(v.avg_depth).toFixed(1)})</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

/* ---- Helpers ---- */
function bidColor(intensity: number): string {
  const a = Math.min(intensity, 1);
  if (a > 0.7) return `rgba(0, 200, 83, ${0.5 + a * 0.4})`;
  if (a > 0.3) return `rgba(0, 200, 83, ${0.15 + a * 0.35})`;
  return `rgba(0, 200, 83, ${a * 0.2})`;
}

function askColor(intensity: number): string {
  const a = Math.min(intensity, 1);
  if (a > 0.7) return `rgba(239, 68, 68, ${0.5 + a * 0.4})`;
  if (a > 0.3) return `rgba(239, 68, 68, ${0.15 + a * 0.35})`;
  return `rgba(239, 68, 68, ${a * 0.2})`;
}
