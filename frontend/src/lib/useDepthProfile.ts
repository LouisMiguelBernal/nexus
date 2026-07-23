"use client";

/**
 * Nexus - Single source for cross-exchange depth.
 *
 * Wraps {@link usePolling} against `/api/book/merged/{symbol}`. Replaces the
 * separate `/api/heatmap/{symbol}` fetches that HeatmapTab and OrderFlowTab
 * each ran independently, killing the duplicate poll under the institutional
 * 5-layer Execution hierarchy.
 */

import { usePolling } from "./usePolling";

export interface MergedBookLevel {
  price: number;
  size: number;
  weighted_size: number;
  sources: Record<string, number>;
}

export interface MergedBook {
  symbol: string;
  depth: number;
  bids: MergedBookLevel[];
  asks: MergedBookLevel[];
  mid: number | null;
  spread: number | null;
  spread_bps: number | null;
  contributors: string[];
  ts: number;
}

interface Options {
  api: string;
  symbol: string;
  depth?: number;
  intervalMs?: number;
  enabled?: boolean;
}

export function useDepthProfile({
  api,
  symbol,
  depth = 20,
  intervalMs = 2000,
  enabled = true,
}: Options) {
  const url = symbol ? `${api}/api/book/merged/${symbol}?depth=${depth}` : null;
  return usePolling<MergedBook>({ url, intervalMs, enabled });
}
