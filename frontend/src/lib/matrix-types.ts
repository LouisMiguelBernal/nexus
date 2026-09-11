/**
 * Matrix Engine - typed envelope returned by /api/matrix/{symbol}
 * Mirrors backend/api/matrix.py make_router output exactly.
 */

export type LayerKey =
  | "trend" | "flow" | "oi" | "basis" | "vol" | "liq" | "dealer";

export interface MatrixLayer {
  value: number;            // [-1, +1]
  source: "direct" | "proxy" | "none";
  confidence: number;       // [0, 1]
  note: string;
}

export interface MatrixComposite {
  score: number;            // [-100, +100]
  verdict: string;
  confidence: number;       // [0, 100]
  agreement: number;        // [0, 100]
  venue_agreement: number;  // [0, 100]
}

export interface MatrixRegime {
  label: string;
  confidence: number;
  hurst: number | null;
  hurst_signed: number;
  entropy: number | null;
  entropy_signed: number;
}

export interface MatrixFlow {
  cvd_5m: number | null;
  cvd_15m: number | null;
  cvd_1h: number | null;
  cvd_4h: number | null;
  trades_5m: number | null;
  trades_1h: number | null;
  flow_ratio: number | null;
  absorption: {
    detected: boolean;
    side: "bid" | "ask" | "none";
    strength: number;
    buy_sell_ratio?: number | null;
    volume_usd?: number | null;
    sample_age_s?: number | null;
  };
  vpin: number | null;
  obi: number | null;
  obi_z: number | null;
  obi_bias: string | null;
}

export interface MatrixOI {
  change_pct_1h: number | null;
  zscore_4h_7d: number | null;
}

export interface MatrixResearch {
  basis_pct: number | null;
  basis_dispersion_pct: number | null;
  funding_pct: number | null;
  funding_persistence: number | null;
  gex_proxy: number | null;
  dealer_skew: number | null;
}

export interface MatrixRisk {
  var_ens: number | null;
  var_stressed: number | null;
  es_95: number | null;
  liq_proximity_pct: number | null;
  vpin_toxicity: number | null;
  samples: number;
}

export interface MatrixVenue {
  name: string;
  staleness_ms: number;
  healthy: boolean;
  gaps: number;
}

export interface MatrixSnapshot {
  ts: number;
  symbol: string;
  composite: MatrixComposite;
  layers: Record<LayerKey, MatrixLayer>;
  weights_used: Record<string, number>;
  regime: MatrixRegime;
  flow: MatrixFlow;
  oi: MatrixOI;
  research: MatrixResearch;
  risk: MatrixRisk;
  venues: MatrixVenue[];
  samples: { klines: number; returns: number };
}
