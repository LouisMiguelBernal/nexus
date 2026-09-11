"use client";

import type { LayerKey, MatrixLayer } from "@/lib/matrix-types";

const LAYER_ORDER: LayerKey[] = ["trend", "flow", "oi", "basis", "vol", "liq", "dealer"];
const LAYER_LABELS: Record<LayerKey, string> = {
  trend: "TREND",
  flow: "ORDER FLOW",
  oi: "OI",
  basis: "BASIS",
  vol: "VOL",
  liq: "LIQUIDATION",
  dealer: "DEALER",
};

interface Props {
  layers: Record<LayerKey, MatrixLayer>;
  weights: Record<string, number>;
}

export function LayerBars({ layers, weights }: Props) {
  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          marginBottom: 8,
        }}
      >
        <span style={{ color: "var(--on-surface-dim)", fontSize: 9, letterSpacing: "0.18em", fontWeight: 700 }}>
          LAYERS
        </span>
        <span style={{ color: "var(--on-surface-dim)", fontSize: 8, letterSpacing: "0.12em" }}>
          REWEIGHTED PER REGIME
        </span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {LAYER_ORDER.map((k) => (
          <Bar key={k} label={LAYER_LABELS[k]} layer={layers[k]} weight={weights[k]} />
        ))}
      </div>
    </div>
  );
}

function Bar({ label, layer, weight }: { label: string; layer: MatrixLayer; weight?: number }) {
  const v = Number.isFinite(layer?.value) ? layer.value : 0;
  const isProxy = layer?.source === "proxy";
  const isAbsent = layer?.source === "none" || (layer?.confidence ?? 0) === 0;
  const color = v >= 0.33 ? "var(--chart-bull)" : v <= -0.33 ? "var(--chart-bear)" : v > 0 ? "var(--chart-bull-dim)" : v < 0 ? "var(--chart-bear-dim)" : "var(--primary)";
  const opacity = isAbsent ? 0.35 : isProxy ? 0.78 : 1.0;
  // Bar geometry: -1..+1 maps to two halves around center.
  const half = Math.min(1, Math.abs(v));
  const isPositive = v >= 0;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "70px 1fr 38px", alignItems: "center", gap: 8, opacity }}>
      <span
        style={{
          color: "var(--on-surface-dim)",
          fontSize: 9,
          letterSpacing: "0.14em",
          fontWeight: 600,
        }}
      >
        {label}
        {isProxy ? <span style={{ color: "var(--primary)", marginLeft: 4 }}>~</span> : null}
      </span>
      <div
        style={{
          position: "relative",
          height: 6,
          background: "rgba(127,127,127,0.08)",
          borderRadius: 2,
        }}
      >
        {/* Center divider */}
        <div
          style={{
            position: "absolute",
            left: "50%",
            top: -1,
            bottom: -1,
            width: 1,
            background: "rgba(127,127,127,0.25)",
          }}
        />
        {/* Filled half */}
        <div
          style={{
            position: "absolute",
            left: isPositive ? "50%" : `${(1 - half) * 50}%`,
            width: `${half * 50}%`,
            top: 0,
            bottom: 0,
            background: color,
            borderRadius: 2,
            transition: "left 220ms ease, width 220ms ease, background 220ms ease",
          }}
        />
        {/* Tick marks at ±0.33 / ±0.66 */}
        {[16.5, 33, 67, 83.5].map((p) => (
          <div
            key={p}
            style={{
              position: "absolute",
              left: `${p}%`,
              top: 0,
              bottom: 0,
              width: 1,
              background: "rgba(127,127,127,0.12)",
            }}
          />
        ))}
      </div>
      <div
        className="text-mono"
        style={{
          color,
          fontSize: 11,
          fontWeight: 700,
          fontVariantNumeric: "tabular-nums",
          textAlign: "right",
        }}
        title={`${layer?.source ?? "none"} · conf ${((layer?.confidence ?? 0) * 100).toFixed(0)}%${weight !== undefined ? ` · w ${(weight * 100).toFixed(0)}%` : ""}`}
      >
        {v > 0 ? "+" : ""}
        {(v * 100).toFixed(0)}
      </div>
    </div>
  );
}
