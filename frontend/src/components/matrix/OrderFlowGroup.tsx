"use client";

import type { MatrixFlow, MatrixOI } from "@/lib/matrix-types";

interface Props {
  flow: MatrixFlow;
  oi: MatrixOI;
}

function fmtUsd(v: number | null): string {
  if (v === null || !Number.isFinite(v)) return "-";
  const abs = Math.abs(v);
  if (abs >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return v.toFixed(0);
}

function fmtPct(v: number | null, digits = 2): string {
  if (v === null || !Number.isFinite(v)) return "-";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(digits)}%`;
}

function colorFromSign(v: number | null): string {
  if (v === null || !Number.isFinite(v)) return "var(--on-surface-dim)";
  if (v > 0) return "var(--chart-bull)";
  if (v < 0) return "var(--chart-bear)";
  return "var(--primary)";
}

export function OrderFlowGroup({ flow, oi }: Props) {
  const fr = flow.flow_ratio;
  const fr_pct = fr === null ? null : fr * 100;
  const fr_signed = fr === null ? null : (fr - 0.5) * 2; // [-1,+1]

  const abs = flow.absorption;
  const absText =
    !abs.detected ? "OFF" :
    abs.side === "bid" ? `BID · ${(abs.strength).toFixed(1)}x` :
    `ASK · ${(abs.strength).toFixed(1)}x`;
  const absColor =
    !abs.detected ? "var(--on-surface-dim)" :
    abs.side === "bid" ? "var(--chart-bull)" : "var(--chart-bear)";

  return (
    <div>
      <div style={{ color: "var(--on-surface-dim)", fontSize: 9, letterSpacing: "0.18em", fontWeight: 700, marginBottom: 8 }}>
        ORDER FLOW
      </div>
      <Row label="CVD 5M" value={fmtUsd(flow.cvd_5m)} color={colorFromSign(flow.cvd_5m)} />
      <Row label="CVD 15M" value={fmtUsd(flow.cvd_15m)} color={colorFromSign(flow.cvd_15m)} />
      <Row label="CVD 1H" value={fmtUsd(flow.cvd_1h)} color={colorFromSign(flow.cvd_1h)} />
      <Row label="CVD 4H" value={fmtUsd(flow.cvd_4h)} color={colorFromSign(flow.cvd_4h)} />
      <Row
        label="FLOW RATIO"
        value={fr_pct === null ? "-" : `${fr_pct.toFixed(0)}%`}
        color={colorFromSign(fr_signed)}
      />
      <Row label="ABSORPTION" value={absText} color={absColor} />
      <Row
        label="VPIN"
        value={flow.vpin === null ? "-" : flow.vpin.toFixed(2)}
        color={flow.vpin === null ? "var(--on-surface-dim)" : flow.vpin > 0.4 ? "var(--chart-bear)" : "var(--chart-bull)"}
      />
      <Row
        label="OBI"
        value={flow.obi === null ? "-" : flow.obi.toFixed(2)}
        color={colorFromSign(flow.obi)}
      />
      {flow.obi_z !== null ? (
        <Row
          label="OBI Z (3M)"
          value={`${flow.obi_z.toFixed(2)}σ`}
          color={
            flow.obi_z >= 2 ? "var(--chart-bull)" :
            flow.obi_z <= -2 ? "var(--chart-bear)" :
            colorFromSign(flow.obi_z)
          }
        />
      ) : null}
      <Row
        label="OI Δ 1H"
        value={fmtPct(oi.change_pct_1h)}
        color={colorFromSign(oi.change_pct_1h)}
      />
      {oi.zscore_4h_7d !== null ? (
        <Row
          label="OI Z 4H/7D"
          value={oi.zscore_4h_7d.toFixed(2) + "σ"}
          color={colorFromSign(oi.zscore_4h_7d)}
        />
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
        style={{
          color,
          fontWeight: 700,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </span>
    </div>
  );
}
