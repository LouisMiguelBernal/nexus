/**
 * Nexus - shared number/currency formatters
 * Null-safe: every formatter accepts `unknown` and returns a sensible string.
 */

export function num(v: unknown, fallback = 0): number {
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : fallback;
}

export function fmtUSD(value: unknown, opts: { signed?: boolean } = {}): string {
  const v = num(value);
  const abs = Math.abs(v);
  const prefix = opts.signed ? (v < 0 ? "-" : v > 0 ? "+" : "") : v < 0 ? "-" : "";
  if (abs >= 1_000_000_000) return `${prefix}$${(abs / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000) return `${prefix}$${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${prefix}$${(abs / 1_000).toFixed(1)}K`;
  return `${prefix}$${abs.toFixed(0)}`;
}

export function fmtCompact(value: unknown): string {
  const v = num(value);
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return v.toFixed(1);
}

export function fmtPrice(value: unknown, minFrac = 2): string {
  return num(value).toLocaleString(undefined, {
    minimumFractionDigits: minFrac,
    maximumFractionDigits: minFrac,
  });
}

export function fmtPct(value: unknown, frac = 2): string {
  if (value == null) return "-";
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "-";
  return `${n.toFixed(frac)}%`;
}

/** Risk/Kelly USD: `$1,234` form (rounded, no sign - magnitude only). */
export function fmtUsdAbs(value: unknown): string {
  if (value == null) return "-";
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "-";
  return `$${Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

export function fmtFixed(value: unknown, frac = 3): string {
  return num(value).toFixed(frac);
}
