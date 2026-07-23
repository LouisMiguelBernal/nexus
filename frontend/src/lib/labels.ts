// Human-readable label mapping for backend variable names.
// Keeps the UI institutional-grade - no snake_case leaking into headings.

const LABELS: Record<string, string> = {
  // Alpha Engine signal names (backend/computation/alpha_engine.py)
  ofi: "Order Flow Imbalance",
  vwap_deviation: "VWAP Deviation",
  funding_arb: "Funding Arbitrage",
  cross_exchange_spread: "Cross-Exchange Spread",
  liquidation_cascade: "Liquidation Cascade",
  delta_divergence: "Delta Divergence",
  smart_money_flow: "Smart Money Flow",
  vol_regime: "Volatility Regime",

  // Technical indicators (/api/indicators)
  rsi_14: "RSI 14",
  ema_50: "EMA 50",
  ema_200: "EMA 200",
  ema_cross: "EMA Cross",
  ema_trend: "EMA Trend",
  bb_upper: "Bollinger Upper",
  bb_middle: "Bollinger Middle",
  bb_lower: "Bollinger Lower",
  bb_width_pct: "Bollinger Width",
  macd: "MACD",
  macd_signal: "MACD Signal",
  macd_hist: "MACD Histogram",
  macd_bias: "MACD Bias",
  stoch_k: "Stochastic %K",
  stoch_d: "Stochastic %D",
  atr_14: "ATR 14",
  adx_14: "ADX 14",
  adx_regime: "ADX Regime",

  // Market-data fields
  weighted_rate_pct: "Weighted Funding",
  oi_change_pct: "Open Interest Δ",
  ls_ratio: "Long/Short Ratio",
  top_trader_ls_ratio: "Top-Trader L/S",
  put_call_ratio: "Put/Call Ratio",
  max_pain: "Max Pain",
  perpetual_funding: "Perp Funding",
  change_24h_pct: "24h Change",
  mark_price: "Mark Price",
  index_price: "Index Price",
  funding_rate: "Funding Rate",
  quote_volume: "Quote Volume",
  quote_volume_24h: "24h Quote Volume",
  volume_24h: "24h Volume",
  trades_24h: "24h Trades",
  high_24h: "24h High",
  low_24h: "24h Low",
  open_24h: "24h Open",

  // Alpha-engine signal table fields
  composite_score: "Composite Score",
  composite_direction: "Composite Direction",
  agreement_ratio: "Agreement",
  net_flow: "Net Whale Flow",
  recent_whales: "Recent Whales",

  // Order flow
  trade_flow_ratio: "Trade Flow Ratio",
  buy_volume: "Buy Volume",
  sell_volume: "Sell Volume",
  oi_change_1h: "OI Change (1h)",
  cvd: "Cumulative Delta",

  // Zones
  price_center: "Price Center",
  zone_type: "Zone Type",

  // Regime
  regime: "Regime",
  confidence: "Confidence",
};

/**
 * Convert a backend variable name (snake_case or lowercase) to a
 * presentation label. Falls back to a Title-Cased, space-separated
 * version of the input.
 */
export function humanLabel(key: string): string {
  if (!key) return "";
  const direct = LABELS[key];
  if (direct) return direct;
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Convenience for rendering signal rows in Alpha tab etc. */
export const signalLabel = (name: string) => humanLabel(name);
