"use client";

import type { MatrixComposite } from "@/lib/matrix-types";

const ROW_LABEL: React.CSSProperties = {
  color: "var(--on-surface-dim)",
  fontSize: 9,
  letterSpacing: "0.18em",
  fontWeight: 700,
};

function verdictColor(score: number): string {
  if (score >= 50) return "var(--chart-bull)";
  if (score >= 15) return "#5dd8b8";
  if (score <= -50) return "var(--chart-bear)";
  if (score <= -15) return "#ff7b7f";
  return "#c6c6c7"; // institutional silver
}

interface Props {
  composite: MatrixComposite;
  stalenessSec: number | null;
}

export function CompositeHeader({ composite, stalenessSec }: Props) {
  const score = Number.isFinite(composite.score) ? composite.score : 0;
  const color = verdictColor(score);
  const sign = score > 0 ? "+" : "";
  const stale = stalenessSec !== null && stalenessSec > 5;

  return (
    <div>
      <div style={{ ...ROW_LABEL, marginBottom: 8 }}>MATRIX ENGINE</div>

      {/* Score + verdict */}
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 8 }}>
        <span
          className="text-mono"
          style={{
            color,
            fontSize: 38,
            fontWeight: 500,
            letterSpacing: "-0.02em",
            lineHeight: 1,
            fontVariantNumeric: "tabular-nums",
            transition: "color 250ms ease",
          }}
        >
          {sign}
          {score.toFixed(0)}
        </span>
        <span
          style={{
            color: "var(--on-surface)",
            fontSize: 11,
            letterSpacing: "0.14em",
            fontWeight: 600,
          }}
        >
          {composite.verdict}
        </span>
      </div>

      {/* Bear / bull spectrum bar with cursor */}
      <div
        style={{
          position: "relative",
          width: "100%",
          height: 5,
          borderRadius: 3,
          background: "rgba(127,127,127,0.10)",
          overflow: "hidden",
          marginBottom: 4,
        }}
      >
        <div
          style={{
            position: "absolute",
            inset: 0,
            background:
              "linear-gradient(90deg, #ea3943 0%, rgba(234,57,67,0.18) 30%, rgba(198,198,199,0.15) 50%, rgba(22,199,132,0.18) 70%, #16c784 100%)",
            opacity: 0.5,
          }}
        />
        <div
          style={{
            position: "absolute",
            left: `${Math.min(100, Math.max(0, (score + 100) / 2))}%`,
            top: -3,
            transform: "translateX(-50%)",
            width: 2,
            height: 11,
            background: color,
            transition: "left 250ms ease",
          }}
        />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", color: "var(--on-surface-dim)", fontSize: 9, letterSpacing: "0.10em" }}>
        <span>BEAR 100</span>
        <span>0</span>
        <span>BULL 100</span>
      </div>

      {/* Confidence + Agreement + Venue agreement micro-row */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10, marginTop: 12 }}>
        <Mini label="CONF" value={composite.confidence} suffix="%" />
        <Mini label="AGR" value={composite.agreement} suffix="%" />
        <Mini label="VENUE" value={composite.venue_agreement} suffix="%" />
      </div>

      {stale ? (
        <div
          style={{
            marginTop: 6,
            color: "var(--primary)",
            fontSize: 9,
            letterSpacing: "0.14em",
            fontWeight: 600,
          }}
        >
          STALE {stalenessSec}s
        </div>
      ) : null}
    </div>
  );
}

function Mini({ label, value, suffix }: { label: string; value: number; suffix?: string }) {
  const v = Number.isFinite(value) ? value : 0;
  const color = v >= 70 ? "var(--chart-bull)" : v <= 30 ? "var(--chart-bear)" : "#c6c6c7";
  return (
    <div>
      <div style={{ ...ROW_LABEL, fontSize: 8, marginBottom: 3 }}>{label}</div>
      <div style={{ position: "relative", height: 3, background: "rgba(127,127,127,0.10)", borderRadius: 2, marginBottom: 3 }}>
        <div style={{ position: "absolute", inset: 0, width: `${Math.min(100, Math.max(0, v))}%`, background: color, borderRadius: 2, transition: "width 250ms ease" }} />
      </div>
      <div className="text-mono" style={{ color, fontSize: 11, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>
        {v.toFixed(0)}{suffix ?? ""}
      </div>
    </div>
  );
}
