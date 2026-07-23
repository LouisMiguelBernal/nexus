"use client";

import { usePolling } from "@/lib/usePolling";

/**
 * Crypto ticker strip - Bloomberg-style scrolling marquee under the header.
 * Backed by GET /api/crypto/strip (one bulk Binance 24h-ticker call, 5s
 * server cache). Clicking a symbol switches the terminal's active pair.
 * Hover pauses the scroll. Hides itself until the first quotes arrive.
 */

interface StripQuote {
  symbol: string;
  price: number;
  change_pct: number;
  high: number;
  low: number;
  quote_volume: number;
}

interface StripResp {
  quotes: StripQuote[];
  count: number;
  updated_at: number;
}

const fmtPrice = (n: number) => {
  const abs = Math.abs(n);
  const digits = abs >= 100 ? 2 : abs >= 1 ? 3 : 5;
  return n.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
};

const compactVol = (n: number) => {
  const a = Math.abs(n);
  if (a >= 1e9) return (n / 1e9).toFixed(2) + "B";
  if (a >= 1e6) return (n / 1e6).toFixed(1) + "M";
  return (n / 1e3).toFixed(0) + "K";
};

export default function CryptoTicker({ api, onSelect }: { api: string; onSelect?: (symbol: string) => void }) {
  const { data } = usePolling<StripResp>({
    url: `${api}/api/crypto/strip`,
    intervalMs: 5_000,
  });

  if (!data?.quotes?.length) return null;

  return (
    <div
      className="no-select"
      style={{
        display: "flex",
        alignItems: "stretch",
        height: 26,
        borderBottom: "1px solid var(--hairline)",
        background: "var(--surface-container-lowest)",
        overflow: "hidden",
        flexShrink: 0,
      }}
    >
      {/* Fixed badge - perps trade around the clock, so the dot is always live */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 7,
          padding: "0 12px",
          borderRight: "1px solid var(--hairline)",
          flexShrink: 0,
        }}
      >
        <span
          className="animate-pulse-live"
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: "var(--chart-bull)",
            boxShadow: "0 0 5px var(--chart-bull)",
            display: "inline-block",
          }}
        />
        <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.16em", color: "var(--on-surface-variant)" }}>
          PERPS
        </span>
        <span style={{ fontSize: 9, fontWeight: 600, letterSpacing: "0.1em", color: "var(--chart-bull)" }}>
          24/7
        </span>
      </div>

      {/* Scrolling marquee - content duplicated once; track translates -50%
          for a seamless loop. Hover pauses (CSS in globals). */}
      <div className="quote-ticker-viewport" style={{ flex: 1, overflow: "hidden", position: "relative" }}>
        <div className="quote-ticker-track">
          {[0, 1].map((copy) => (
            <div key={copy} className="quote-ticker-group" aria-hidden={copy === 1}>
              {data.quotes.map((q) => {
                const up = q.change_pct >= 0;
                const tone = up ? "var(--chart-bull)" : "var(--chart-bear)";
                const base = q.symbol.replace("USDT", "");
                return (
                  <button
                    key={`${copy}-${q.symbol}`}
                    onClick={() => onSelect?.(q.symbol)}
                    title={`${q.symbol} · H ${fmtPrice(q.high)} · L ${fmtPrice(q.low)} · vol $${compactVol(q.quote_volume)} - click to set active pair`}
                    className="quote-ticker-item"
                    style={{
                      display: "flex", alignItems: "baseline", gap: 6, padding: "0 14px", whiteSpace: "nowrap",
                      background: "transparent", border: "none", cursor: onSelect ? "pointer" : "default",
                      fontFamily: "inherit", height: "100%",
                    }}
                  >
                    <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.06em", color: "var(--on-surface)" }}>
                      {base}
                    </span>
                    <span className="text-mono" style={{ fontSize: 10, color: "var(--on-surface-variant)" }}>
                      {fmtPrice(q.price)}
                    </span>
                    <span className="text-mono" style={{ fontSize: 10, fontWeight: 600, color: tone }}>
                      {up ? "▲" : "▼"} {Math.abs(q.change_pct).toFixed(2)}%
                    </span>
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
