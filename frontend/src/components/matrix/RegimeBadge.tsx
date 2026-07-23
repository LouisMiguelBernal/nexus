"use client";

import type { MatrixRegime } from "@/lib/matrix-types";

const REGIME_COLOR: Record<string, string> = {
  trending_up: "var(--chart-bull)",
  trending_down: "var(--chart-bear)",
  ranging: "var(--primary)",
  volatile: "var(--primary-fixed)",
  low_liq: "var(--accent-purple)",
  unknown: "var(--on-surface-variant)",
};

export function RegimeBadge({ regime }: { regime: MatrixRegime }) {
  const color = REGIME_COLOR[regime.label] ?? "var(--primary)";
  const H = regime.hurst;
  const E = regime.entropy;

  const Hlabel =
    H === null ? "-" :
    H > 0.55 ? "PERSISTENT" :
    H < 0.45 ? "MEAN-REV" :
    "RANDOM";

  const Elabel =
    E === null ? "-" :
    E < 0.55 ? "STRUCTURED" :
    E > 0.85 ? "CHOPPY" :
    "MIXED";

  return (
    <div>
      <div style={{ color: "var(--on-surface-dim)", fontSize: 9, letterSpacing: "0.18em", fontWeight: 700, marginBottom: 8 }}>
        REGIME
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
        <Cell label="LABEL" valueText={regime.label.replace("_", " ").toUpperCase()} color={color} />
        <Cell
          label="HURST"
          valueText={H === null ? "-" : H.toFixed(2)}
          subText={Hlabel}
          color={H === null ? "var(--on-surface-dim)" : H > 0.55 ? "var(--chart-bull)" : H < 0.45 ? "var(--chart-bear-dim)" : "var(--primary)"}
        />
        <Cell
          label="ENTROPY"
          valueText={E === null ? "-" : E.toFixed(2)}
          subText={Elabel}
          color={E === null ? "var(--on-surface-dim)" : E < 0.55 ? "var(--chart-bull)" : E > 0.85 ? "var(--chart-bear-dim)" : "var(--primary)"}
        />
      </div>
    </div>
  );
}

function Cell({ label, valueText, subText, color }: {
  label: string;
  valueText: string;
  subText?: string;
  color: string;
}) {
  return (
    <div
      style={{
        background: "rgba(127,127,127,0.04)",
        border: "0.5px solid var(--hairline)",
        borderRadius: 3,
        padding: "8px 10px",
      }}
    >
      <div style={{ color: "var(--on-surface-dim)", fontSize: 8, letterSpacing: "0.14em", fontWeight: 700, marginBottom: 4 }}>
        {label}
      </div>
      <div className="text-mono" style={{ color, fontSize: 12, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>
        {valueText}
      </div>
      {subText ? (
        <div style={{ color: "var(--on-surface-dim)", fontSize: 8, letterSpacing: "0.10em", marginTop: 2 }}>
          {subText}
        </div>
      ) : null}
    </div>
  );
}
