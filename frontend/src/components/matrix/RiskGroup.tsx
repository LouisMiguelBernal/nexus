"use client";

import type { MatrixRisk } from "@/lib/matrix-types";

function fmtPct(v: number | null, digits = 2): string {
  if (v === null || !Number.isFinite(v)) return "-";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(digits)}%`;
}

function riskColor(v: number | null): string {
  if (v === null || !Number.isFinite(v)) return "var(--on-surface-dim)";
  if (v > -0.5) return "var(--chart-bull)";       // tiny VaR → safe
  if (v > -2) return "var(--primary)";
  if (v > -5) return "var(--primary-fixed)";
  return "var(--chart-bear)";
}

function liqProxColor(p: number | null): string {
  if (p === null || !Number.isFinite(p)) return "var(--on-surface-dim)";
  if (p < 0.5) return "var(--chart-bull)";
  if (p < 2) return "var(--primary)";
  if (p < 5) return "var(--primary-fixed)";
  return "var(--chart-bear)";
}

export function RiskGroup({ risk }: { risk: MatrixRisk }) {
  return (
    <div>
      <div style={{ color: "var(--on-surface-dim)", fontSize: 9, letterSpacing: "0.18em", fontWeight: 700, marginBottom: 8 }}>
        RISK
      </div>
      <Row label="VaR (ENS) 95" value={fmtPct(risk.var_ens, 2)} color={riskColor(risk.var_ens)} />
      <Row label="STRESSED" value={fmtPct(risk.var_stressed, 2)} color={riskColor(risk.var_stressed)} />
      <Row label="ES 95" value={fmtPct(risk.es_95, 2)} color={riskColor(risk.es_95)} />
      <Row
        label="LIQ PROX"
        value={risk.liq_proximity_pct === null ? "-" : `${risk.liq_proximity_pct.toFixed(2)}%`}
        color={liqProxColor(risk.liq_proximity_pct)}
      />
      <Row
        label="VPIN TOX"
        value={risk.vpin_toxicity === null ? "-" : risk.vpin_toxicity.toFixed(2)}
        color={risk.vpin_toxicity === null ? "var(--on-surface-dim)" : risk.vpin_toxicity > 0.4 ? "var(--chart-bear)" : "var(--chart-bull)"}
      />
      {risk.samples < 31 ? (
        <div
          style={{
            marginTop: 6,
            color: "var(--primary)",
            fontSize: 9,
            letterSpacing: "0.12em",
            fontWeight: 600,
          }}
        >
          WARMUP {risk.samples}/31
        </div>
      ) : null}
    </div>
  );
}

function Row({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        padding: "3px 0",
        borderBottom: "0.5px solid var(--hairline)",
        fontSize: 11,
      }}
    >
      <span style={{ color: "var(--on-surface-dim)", fontSize: 10, letterSpacing: "0.12em" }}>
        {label}
      </span>
      <span
        className="text-mono"
        style={{ color, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}
      >
        {value}
      </span>
    </div>
  );
}
