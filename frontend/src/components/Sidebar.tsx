"use client";

import { useEffect, useState } from "react";
import { usePolling } from "@/lib/usePolling";

interface Props {
  api: string;
  symbol: string;
  health: Record<string, unknown> | null;
}

interface FeedSummary {
  venues: Record<
    string,
    { connected: boolean; avg_degradation: number; max_age_s: number | null }
  >;
}

const VENUES = ["binance", "okx", "mexc"] as const;

/**
 * Status bar - bottom strip showing per-venue feed health, latency, active symbol.
 * Feed dots are colour-coded by degradation factor (not just connected/disconnected):
 *   green ≥0.7, amber ≥0.3, red < 0.3 or stale. Tooltip exposes deg% + last-event age.
 */
export default function StatusBar({ api, symbol, health }: Props) {
  const [lastUpdate, setLastUpdate] = useState<string>("--:--:--");
  const [latency, setLatency] = useState<number | null>(null);

  useEffect(() => {
    const check = async () => {
      const start = Date.now();
      try {
        await fetch(`${api}/api/health`);
        setLatency(Date.now() - start);
        setLastUpdate(new Date().toLocaleTimeString());
      } catch {
        setLatency(null);
      }
    };
    void check();
    const interval = setInterval(() => void check(), 10000);
    return () => clearInterval(interval);
  }, [api]);

  const { data: feed } = usePolling<FeedSummary>({
    url: `${api}/api/feed/health`,
    intervalMs: 10_000,
  });

  return (
    <footer
      className="flex items-center justify-between no-select"
      style={{
        height: 26,
        padding: "0 16px",
        background: "var(--surface-container-lowest)",
        borderTop: "1px solid var(--hairline)",
        fontSize: 10,
        color: "var(--on-surface-dim)",
        letterSpacing: "0.04em",
      }}
    >
      {/* Left: per-venue feed health (degradation-aware) */}
      <div className="flex items-center gap-3">
        <span style={{ color: "var(--on-surface-dim)", fontSize: 9, letterSpacing: "0.18em" }}>
          FEEDS
        </span>
        {VENUES.map((v) => {
          const h = feed?.venues?.[v];
          const deg = h?.avg_degradation ?? 0;
          const connected = h?.connected ?? false;
          const live = connected && deg >= 0.3;
          const color = !connected
            ? "var(--chart-bear)"
            : deg >= 0.7
            ? "var(--chart-bull)"
            : deg >= 0.3
            ? "var(--primary)"
            : "var(--chart-bear)";
          const tip = !h
            ? `${v.toUpperCase()}: no data`
            : `${v.toUpperCase()} · ${connected ? "up" : "down"} · deg ${(deg * 100).toFixed(0)}% · age ${
                h.max_age_s != null ? `${h.max_age_s.toFixed(1)}s` : "-"
              }`;
          return (
            <div key={v} className="flex items-center gap-1.5" title={tip}>
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  background: color,
                  boxShadow: live ? `0 0 4px ${color}` : "none",
                  display: "inline-block",
                }}
              />
              <span
                style={{
                  textTransform: "uppercase",
                  color: connected ? "var(--on-surface-variant)" : "var(--on-surface-dim)",
                  fontWeight: 600,
                  letterSpacing: "0.08em",
                }}
              >
                {v}
              </span>
            </div>
          );
        })}
      </div>

      {/* Center: active symbol */}
      <div className="flex items-center gap-3">
        <span style={{ color: "var(--on-surface-dim)" }}>ACTIVE</span>
        <span className="text-mono" style={{ color: "var(--primary)", fontWeight: 700, letterSpacing: "0.08em" }}>
          {symbol}
        </span>
      </div>

      {/* Right: latency + last update + version */}
      <div className="flex items-center gap-4">
        {latency !== null ? (
          <span>
            LAT{" "}
            <span
              className="text-mono"
              style={{
                color:
                  latency < 200
                    ? "var(--chart-bull)"
                    : latency < 500
                    ? "var(--primary)"
                    : "var(--chart-bear)",
              }}
            >
              {latency}ms
            </span>
          </span>
        ) : (
          <span style={{ color: "var(--chart-bear)" }}>OFFLINE</span>
        )}
        <span>UPD <span className="text-mono">{lastUpdate}</span></span>
        <span>NEXUS <span className="text-mono">v{String(health?.version || "0.3.0")}</span></span>
      </div>
    </footer>
  );
}
