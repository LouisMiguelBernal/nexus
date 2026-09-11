"use client";

import type { MatrixResearch } from "@/lib/matrix-types";

function colorFromSign(v: number | null): string {
  if (v === null || !Number.isFinite(v)) return "var(--on-surface-dim)";
  if (v > 0) return "var(--chart-bull)";
  if (v < 0) return "var(--chart-bear)";
  return "var(--primary)";
}

export function ResearchGroup({ research }: { research: MatrixResearch }) {
  return (
    <div>
      <div style={{ color: "var(--on-surface-dim)", fontSize: 9, letterSpacing: "0.18em", fontWeight: 700, marginBottom: 8 }}>
        RESEARCH
      </div>
      <Row
        label="BASIS %"
        value={research.basis_pct === null ? "-" : `${research.basis_pct >= 0 ? "+" : ""}${research.basis_pct.toFixed(3)}%`}
        color={colorFromSign(research.basis_pct)}
      />
      {research.basis_dispersion_pct !== null ? (
        <Row
          label="VENUE DISP"
          value={`${research.basis_dispersion_pct.toFixed(3)}%`}
          color={
            research.basis_dispersion_pct > 0.10 ? "var(--chart-bear)" :
            research.basis_dispersion_pct > 0.05 ? "var(--primary)" :
            "var(--on-surface-variant)"
          }
        />
      ) : null}
      <Row
        label="FUNDING %"
        value={research.funding_pct === null ? "-" : `${research.funding_pct >= 0 ? "+" : ""}${research.funding_pct.toFixed(4)}%`}
        color={colorFromSign(research.funding_pct)}
      />
      <Row
        label="FUND PERSIST"
        value={research.funding_persistence === null ? "-" : research.funding_persistence.toFixed(2)}
        color={colorFromSign(research.funding_persistence)}
      />
      <Row
        label="GEX PROXY"
        value={research.gex_proxy === null ? "-" : research.gex_proxy.toFixed(2)}
        color={colorFromSign(research.gex_proxy)}
        proxy
      />
      <Row
        label="DEALER SKEW"
        value={research.dealer_skew === null ? "-" : research.dealer_skew.toFixed(2)}
        color={colorFromSign(research.dealer_skew)}
        proxy
      />
    </div>
  );
}

function Row({ label, value, color, proxy }: {
  label: string;
  value: string;
  color: string;
  proxy?: boolean;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        padding: "3px 0",
        borderBottom: "0.5px solid var(--hairline)",
        fontSize: 11,
        opacity: proxy && value !== "-" ? 0.85 : 1,
      }}
      title={proxy ? "Inferred proxy - not direct measurement" : undefined}
    >
      <span style={{ color: "var(--on-surface-dim)", fontSize: 10, letterSpacing: "0.12em" }}>
        {label}
        {proxy ? <span style={{ color: "var(--primary)", marginLeft: 4 }}>~</span> : null}
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
