"use client";

/**
 * Nexus - Matrix Engine Panel
 *
 * Replaces the legacy MatrixEngineCard inline in TradingTab.tsx.
 * Bound to a single REST endpoint /api/matrix/{symbol} which delivers a
 * typed envelope (see lib/matrix-types.ts).
 *
 * Layout:
 *   [Composite header - score, verdict, confidence/agreement]
 *   [7 layer bars - trend / flow / oi / basis / vol / liq / dealer]
 *   [Regime card - label + Hurst + Entropy]
 *   [Order Flow group - CVD multi-TF, flow ratio, absorption, VPIN, OBI]
 *   [Risk group - VaR ens/stressed, ES, liq proximity, VPIN tox]
 *   [Research group - basis, funding, GEX proxy]
 *   [Venue health strip]
 */

import { useEffect, useState } from "react";
import { usePolling } from "@/lib/usePolling";
import type { MatrixSnapshot } from "@/lib/matrix-types";

import { CompositeHeader } from "./CompositeHeader";
import { LayerBars } from "./LayerBars";
import { RegimeBadge } from "./RegimeBadge";
import { OrderFlowGroup } from "./OrderFlowGroup";
import { RiskGroup } from "./RiskGroup";
import { ResearchGroup } from "./ResearchGroup";
import { VenueHealthStrip } from "./VenueHealthStrip";

interface Props {
  api: string;
  symbol: string;
}

export function MatrixPanel({ api, symbol }: Props) {
  const url = `${api}/api/matrix/${symbol}`;
  const { data, error } = usePolling<MatrixSnapshot>({ url, intervalMs: 4000 });

  // Clock lives in state so render stays pure; staleness derives from it and
  // updates live between polls.
  const [nowSec, setNowSec] = useState<number>(() => Date.now() / 1000);
  useEffect(() => {
    const id = setInterval(() => setNowSec(Date.now() / 1000), 1000);
    return () => clearInterval(id);
  }, []);
  const stalenessSec = data ? Math.max(0, Math.round(nowSec - data.ts)) : null;

  if (error && !data) {
    return (
      <div style={{ color: "var(--on-surface-dim)", fontSize: 11 }}>
        MATRIX ENGINE
        <div style={{ marginTop: 8, opacity: 0.6 }}>Connection error: {error}</div>
      </div>
    );
  }

  if (!data) {
    return (
      <div style={{ color: "var(--on-surface-dim)", fontSize: 11 }}>
        MATRIX ENGINE
        <div style={{ marginTop: 8, opacity: 0.6 }}>Loading…</div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <CompositeHeader composite={data.composite} stalenessSec={stalenessSec} />
      <LayerBars layers={data.layers} weights={data.weights_used} />
      <RegimeBadge regime={data.regime} />
      <OrderFlowGroup flow={data.flow} oi={data.oi} />
      <RiskGroup risk={data.risk} />
      <ResearchGroup research={data.research} />
      <VenueHealthStrip venues={data.venues} />
      <div
        style={{
          marginTop: 4, paddingTop: 8,
          borderTop: "0.5px solid var(--hairline)",
          color: "var(--on-surface-dim)", fontSize: 9, letterSpacing: "0.18em",
          display: "flex", justifyContent: "space-between",
        }}
      >
        <span>ADVISORY</span>
        <span>K:{data.samples.klines} R:{data.samples.returns}</span>
      </div>
    </div>
  );
}
