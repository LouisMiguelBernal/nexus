"use client";

import type { MatrixVenue } from "@/lib/matrix-types";

export function VenueHealthStrip({ venues }: { venues: MatrixVenue[] }) {
  if (!venues || venues.length === 0) return null;
  return (
    <div>
      <div style={{ color: "var(--on-surface-dim)", fontSize: 9, letterSpacing: "0.18em", fontWeight: 700, marginBottom: 8 }}>
        VENUES
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {venues.map((v) => {
          const stale = v.staleness_ms > 5000;
          const dead = !v.healthy;
          const dotColor = dead ? "var(--chart-bear)" : stale ? "var(--primary)" : "var(--chart-bull)";
          const stalenessLabel =
            v.staleness_ms < 1000 ? `${v.staleness_ms}ms` :
            `${(v.staleness_ms / 1000).toFixed(1)}s`;
          return (
            <div
              key={v.name}
              style={{
                display: "grid",
                gridTemplateColumns: "8px 1fr auto auto",
                alignItems: "center",
                gap: 8,
                fontSize: 10,
              }}
            >
              <span
                style={{
                  display: "inline-block",
                  width: 7,
                  height: 7,
                  borderRadius: "50%",
                  background: dotColor,
                  boxShadow: `0 0 6px ${dotColor}`,
                }}
              />
              <span style={{ color: "var(--on-surface)", letterSpacing: "0.10em", fontWeight: 600 }}>
                {v.name.toUpperCase()}
              </span>
              <span className="text-mono" style={{ color: dotColor, fontVariantNumeric: "tabular-nums" }}>
                {stalenessLabel}
              </span>
              <span className="text-mono" style={{ color: v.gaps > 0 ? "var(--primary)" : "var(--on-surface-dim)", fontVariantNumeric: "tabular-nums" }}>
                {v.gaps > 0 ? `${v.gaps}gap` : "ok"}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
