"use client";

import { useEffect, useState } from "react";

/**
 * Nexus - system documentation overlay.
 * Toggle with Cmd+/ (mac) or Ctrl+/ (windows). Esc closes.
 *
 * Lives outside the tab routing so it's always reachable; renders a
 * fixed-position panel from the left side, Bloomberg-terminal style.
 */

type Section = {
  id: string;
  title: string;
  body: Array<{ heading: string; bullets: string[] }>;
};

const SECTIONS: Section[] = [
  {
    id: "system",
    title: "System Constraints",
    body: [
      {
        heading: "Hardware envelope",
        bullets: [
          "Local-first. RTX 4050 (6 GB VRAM), 16 GB RAM, Windows.",
          "Gemma 4 (e4b) is the primary LLM via Ollama at :11434.",
          "Fallback chain: gemma2:2b → qwen2.5:1.5b → llama3.2:1b → phi3:mini.",
          "If a model 500s with 'more system memory', the chain auto-degrades.",
        ],
      },
      {
        heading: "Data sources",
        bullets: [
          "Binance USDT-M Perpetuals (REST + WS) - primary for klines, ticker, funding, OI.",
          "Multi-venue depth aggregator: Binance, OKX, MEXC, Deribit.",
          "BloFin REST polls at 60s for portfolio + margin + positions.",
          "Alternative.me Fear & Greed at 60s TTL.",
          "FRED macro release calendar - procedural (NFP/CPI/PPI/FOMC).",
        ],
      },
    ],
  },
  {
    id: "signals",
    title: "Signal Logic",
    body: [
      {
        heading: "Confluence score (-100 → +100)",
        bullets: [
          "RSI 14 in 55-70 → +15 · ≥70 → -10 · 30-45 → -15 · ≤30 → +10",
          "EMA trend bullish → +25 · bearish → -25",
          "MACD bias bullish → +20 · bearish → -20",
          "Stoch >80 → -5 · <20 → +5 · trend-aligned ±8",
          "ADX ≥25 amplifies prevailing trend by ±15",
          "Clamped to ±100. ≥60 strong bull, ≥25 bull, ≤-25 bear.",
        ],
      },
      {
        heading: "Golden Zones",
        bullets: [
          "Aggregated bid/ask clusters across all connected venues.",
          "Tier1 PLATINUM - ≥3 venues align within 0.05% band.",
          "Tier2 GOLD - ≥2 venues align within 0.10% band.",
          "Tier3 SILVER - single-venue cluster within 0.15% band.",
          "Stop-hunt risk fires when cluster magnitude > 5σ of trailing 24h depth.",
        ],
      },
      {
        heading: "Squeeze risk",
        bullets: [
          "BB Width % below 5th percentile of trailing 100 bars → squeeze coiling.",
          "Funding > +0.05% with rising OI → long squeeze risk.",
          "Funding < -0.05% with rising OI → short squeeze risk.",
        ],
      },
    ],
  },
  {
    id: "formulas",
    title: "Algo Formulas",
    body: [
      {
        heading: "Indicators",
        bullets: [
          "EMA(n) = EMA(n,t-1) + α(close - EMA(n,t-1)) · α = 2/(n+1)",
          "RSI(n) = 100 - 100/(1 + avgGain/avgLoss) over n bars",
          "ATR(n) = EMA of TR · TR = max(H-L, |H-Cₚ|, |L-Cₚ|)",
          "BB = SMA(20) ± 2·σ(20)",
          "MACD = EMA(12) - EMA(26) · Signal = EMA(9) of MACD",
        ],
      },
      {
        heading: "Risk",
        bullets: [
          "Kelly* = edge/odds - Nexus caps to fractional Kelly (½ K).",
          "Liquidation (isolated, x leverage) ≈ entry · (1 - 1/x + maintMargin)",
          "Effective leverage = Σ|notional| / equity",
          "VaR (parametric, 1d 99%) = z₀.₀₁ · σ · √Δt · notional",
        ],
      },
      {
        heading: "Order flow",
        bullets: [
          "OBI = (bidVol - askVol) / (bidVol + askVol)  [top-N levels]",
          "CVD = Σ (signedTradeVolume) - aggressor classified by tape side",
          "VWAP = Σ(price · vol) / Σ(vol) - session-anchored",
          "Tape speed = trades/sec, EMA(30s) over raw stream",
          "Funding z-score = (f - μ₃₀d) / σ₃₀d",
        ],
      },
    ],
  },
  {
    id: "shortcuts",
    title: "Keyboard Shortcuts",
    body: [
      {
        heading: "Navigation",
        bullets: [
          "Alt+1 … Alt+6 - switch tab",
          "Cmd+/  ·  Ctrl+/ - toggle this docs overlay",
          "Esc - close overlay / cancel drawing",
        ],
      },
      {
        heading: "Trading chart",
        bullets: [
          "F - fullscreen chart toggle",
          "R - rectangle drawing tool",
          "B - Fibonacci retracement tool",
          "X - clear all drawings",
        ],
      },
    ],
  },
];

export default function DocsOverlay() {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState<string>(SECTIONS[0].id);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const isToggle = (e.metaKey || e.ctrlKey) && e.key === "/";
      if (isToggle) {
        e.preventDefault();
        setOpen((v) => !v);
        return;
      }
      if (open && e.key === "Escape") {
        e.preventDefault();
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // When closed, render nothing - keyboard shortcut (Ctrl+/ · Cmd+/) opens the overlay.
  // The previous floating "?" button overlapped the sidebar's Execute Order footer.
  if (!open) return null;

  const current = SECTIONS.find((s) => s.id === active) ?? SECTIONS[0];

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={() => setOpen(false)}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0,0,0,0.55)",
          zIndex: 70,
          backdropFilter: "blur(2px)",
        }}
      />
      {/* Drawer */}
      <aside
        style={{
          position: "fixed",
          left: 0,
          top: 0,
          bottom: 0,
          width: "min(640px, 100vw)",
          background: "var(--surface)",
          borderRight: "1px solid var(--primary)",
          boxShadow: "0 0 40px rgba(0,0,0,0.6)",
          zIndex: 71,
          display: "grid",
          gridTemplateColumns: "180px 1fr",
          gridTemplateRows: "auto 1fr auto",
        }}
      >
        {/* Header */}
        <div
          style={{
            gridColumn: "1 / -1",
            padding: "14px 18px",
            borderBottom: "1px solid var(--hairline)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span
              className="eyebrow"
              style={{ color: "var(--primary)", fontSize: 10, letterSpacing: "0.2em" }}
            >
              NEXUS · OPERATOR DOCS
            </span>
            <span style={{ color: "var(--on-surface-dim)", fontSize: 11 }}>
              System constraints · signal logic · algo formulas
            </span>
          </div>
          <button
            onClick={() => setOpen(false)}
            style={{
              padding: "4px 10px",
              fontSize: 10,
              letterSpacing: "0.14em",
              color: "var(--on-surface-variant)",
              background: "transparent",
              border: "1px solid var(--hairline)",
              borderRadius: 2,
              cursor: "pointer",
              fontFamily: "inherit",
            }}
          >
            ESC
          </button>
        </div>

        {/* Nav */}
        <nav
          style={{
            borderRight: "1px solid var(--hairline)",
            padding: 8,
            display: "flex",
            flexDirection: "column",
            gap: 2,
            overflowY: "auto",
          }}
        >
          {SECTIONS.map((s) => {
            const on = s.id === active;
            return (
              <button
                key={s.id}
                onClick={() => setActive(s.id)}
                style={{
                  textAlign: "left",
                  padding: "8px 10px",
                  fontSize: 11,
                  fontWeight: on ? 700 : 500,
                  letterSpacing: "0.06em",
                  color: on ? "var(--on-surface)" : "var(--on-surface-variant)",
                  background: on ? "rgba(198,198,199,0.10)" : "transparent",
                  border: `1px solid ${on ? "rgba(198,198,199,0.35)" : "transparent"}`,
                  borderRadius: 2,
                  cursor: "pointer",
                  fontFamily: "inherit",
                  textTransform: "uppercase",
                }}
              >
                {s.title}
              </button>
            );
          })}
        </nav>

        {/* Content */}
        <div style={{ padding: "16px 22px", overflowY: "auto" }}>
          <h2
            style={{
              color: "var(--on-surface)",
              fontSize: 16,
              fontWeight: 800,
              letterSpacing: "0.02em",
              margin: 0,
              marginBottom: 14,
            }}
          >
            {current.title}
          </h2>
          {current.body.map((b) => (
            <section key={b.heading} style={{ marginBottom: 18 }}>
              <div
                className="eyebrow"
                style={{
                  color: "var(--primary)",
                  fontSize: 10,
                  letterSpacing: "0.16em",
                  marginBottom: 6,
                }}
              >
                {b.heading}
              </div>
              <ul
                style={{
                  margin: 0,
                  paddingLeft: 16,
                  display: "flex",
                  flexDirection: "column",
                  gap: 5,
                }}
              >
                {b.bullets.map((line, i) => (
                  <li
                    key={i}
                    className="text-mono"
                    style={{
                      color: "var(--on-surface-variant)",
                      fontSize: 11.5,
                      lineHeight: 1.55,
                      letterSpacing: "0.005em",
                    }}
                  >
                    {line}
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>

        {/* Footer */}
        <div
          style={{
            gridColumn: "1 / -1",
            padding: "10px 18px",
            borderTop: "1px solid var(--hairline)",
            display: "flex",
            justifyContent: "space-between",
            color: "var(--on-surface-dim)",
            fontSize: 10,
            letterSpacing: "0.1em",
          }}
        >
          <span>Toggle: Ctrl+/ · Cmd+/</span>
          <span>NEXUS DOCS</span>
        </div>
      </aside>
    </>
  );
}
