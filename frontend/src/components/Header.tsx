"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useBriefStore } from "@/lib/briefStore";
import NexusLogo from "@/components/Logo";

interface Props {
  health?: Record<string, unknown> | null;
  symbol: string;
  onSymbolChange: (s: string) => void;
  api: string;
}

interface Ticker {
  symbol: string;
  last_price: number;
  price_change: number;
  price_change_pct: number;
  high_24h: number;
  low_24h: number;
  volume_24h: number;
  quote_volume_24h: number;
  trades_24h: number;
}

interface SymbolRow {
  symbol: string;
  base: string;
  quote: string;
  pricePrecision: number;
}

interface MarketSummary {
  ls_ratio_avg: number | null;
  top_trader_ls_avg: number | null;
  long_pct_24h: number | null;
  short_pct_24h: number | null;
}

export default function Header({ symbol, onSymbolChange, api }: Props) {
  const [ticker,  setTicker]  = useState<Ticker | null>(null);
  const [summary, setSummary] = useState<MarketSummary | null>(null);

  // ── F&G from Zustand store - same computed value as the AlertsTab gauge ──
  const { fng } = useBriefStore();

  // ── Theme toggle ──────────────────────────────────────────────────────────
  // Lazy-init from localStorage so the first paint reflects the saved theme,
  // without a setState-in-effect cascade. SSR-safe: returns false on server.
  const [isLight, setIsLight] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem("nexus-theme") === "light";
  });

  // Apply the theme class once on mount and notify listeners. No setState.
  useEffect(() => {
    document.documentElement.classList.toggle("light", isLight);
    window.dispatchEvent(new CustomEvent("nexus-theme-change", { detail: { light: isLight } }));
    // Empty deps: this only runs after hydration to sync the DOM with the
    // already-correct state value. Subsequent toggles go through `toggleTheme`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggleTheme = () => {
    const next = !isLight;
    setIsLight(next);
    document.documentElement.classList.toggle("light", next);
    localStorage.setItem("nexus-theme", next ? "light" : "dark");
    window.dispatchEvent(new CustomEvent("nexus-theme-change", { detail: { light: next } }));
  };

  // ── Pair ticker ───────────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    const ac = new AbortController();
    const fetchTicker = async () => {
      try {
        const res = await fetch(`${api}/api/ticker/${symbol}`, { signal: ac.signal });
        if (!res.ok) {
          console.warn(`[Header] ticker ${symbol} → HTTP ${res.status}`);
          return;
        }
        const data: Ticker = await res.json();
        if (!cancelled) setTicker(data);
      } catch (e) {
        if (e instanceof Error && e.name === "AbortError") return;
        console.warn(`[Header] ticker ${symbol} fetch failed`, e);
      }
    };
    void fetchTicker();
    const id = setInterval(() => void fetchTicker(), 5000);
    return () => { cancelled = true; ac.abort(); clearInterval(id); };
  }, [api, symbol]);

  // ── Market sentiment - L/S ratios only (F&G now comes from Zustand store) ─
  useEffect(() => {
    let cancelled = false;
    const ac = new AbortController();
    const load = async () => {
      try {
        const res = await fetch(`${api}/api/sentiment`, { signal: ac.signal });
        if (!res.ok) {
          console.warn(`[Header] sentiment → HTTP ${res.status}`);
          return;
        }
        const data: MarketSummary = await res.json();
        if (!cancelled) setSummary(data);
      } catch (e) {
        if (e instanceof Error && e.name === "AbortError") return;
        console.warn("[Header] sentiment fetch failed", e);
      }
    };
    void load();
    const id = setInterval(() => void load(), 60000);
    return () => { cancelled = true; ac.abort(); clearInterval(id); };
  }, [api]);

  const change       = ticker?.price_change_pct ?? 0;
  const changeColor  = change > 0 ? "var(--chart-bull)" : change < 0 ? "var(--chart-bear)" : "var(--on-surface-variant)";
  const changePrefix = change > 0 ? "+" : "";
  const pricePrecision = ticker?.last_price && ticker.last_price < 1 ? 5 : 2;

  return (
    <header
      className="no-select glass-panel"
      style={{
        height: "var(--nav-top-h)",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "0 20px", gap: 20,
        borderBottom: "1px solid var(--hairline)",
        position: "sticky", top: 0, zIndex: 40,
      }}
    >
      {/* LEFT - Logo + searchable pair input */}
      <div className="flex items-center gap-4" style={{ minWidth: 0, flex: "0 1 480px" }}>
        <LogoMark />
        <span style={{ color: "var(--on-surface)", fontSize: 15, fontWeight: 800, letterSpacing: "0.22em" }}>
          NEXUS
        </span>
        <PairSearch api={api} symbol={symbol} onSymbolChange={onSymbolChange} />
      </div>

      {/* CENTER - compact LAST/24H readout */}
      <div className="flex items-center gap-5" style={{ flex: 1, justifyContent: "center", minWidth: 0 }}>
        {ticker ? (
          <>
            <Metric label="LAST" value={`$${formatPrice(ticker.last_price, pricePrecision)}`} color="var(--on-surface)" bold large />
            <Metric label="24H"  value={`${changePrefix}${change.toFixed(2)}%`} color={changeColor} bold />
          </>
        ) : (
          <span style={{ color: "var(--on-surface-dim)", fontSize: 11, letterSpacing: "0.18em" }}>LOADING TICKER…</span>
        )}
      </div>

      {/* RIGHT - market summary + theme toggle (feed health lives in StatusBar) */}
      <div className="flex items-center gap-2">
        <MarketSummaryStrip summary={summary} fng={fng} />
        <button
          onClick={toggleTheme}
          title={isLight ? "Switch to dark mode" : "Switch to light mode"}
          className="btn-ghost"
          style={{ width: 28, height: 28, padding: 0, fontSize: 15, flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center" }}
        >
          {isLight ? "☀︎" : "◑"}
        </button>
      </div>
    </header>
  );
}

// ── MarketSummaryStrip ────────────────────────────────────────────────────────
// fng comes from the Zustand store - the same computed value shown by the
// AlertsTab canvas gauge, so header and gauge are always in sync.
function MarketSummaryStrip({
  summary,
  fng,
}: {
  summary: MarketSummary | null;
  fng: { score: number; label: string; color: string } | null | undefined;
}) {
  const fgValue = fng?.score  ?? null;
  const fgLabel = fng?.label  ?? null;
  const fgColor = fng?.color  ?? "var(--on-surface-dim)";

  const longPct  = summary?.long_pct_24h  ?? null;
  const shortPct = summary?.short_pct_24h ?? null;

  return (
    <div className="flex items-center gap-4" style={{ fontSize: 11, flex: "0 0 auto" }}>
      {/* Fear & Greed chip */}
      <div className="flex items-center gap-2">
        <span className="eyebrow" style={{ color: "var(--on-surface-dim)", fontSize: 9 }}>F&amp;G</span>
        <span className="text-mono" style={{ color: fgColor, fontWeight: 800, fontSize: 14, lineHeight: 1 }}>
          {fgValue ?? "-"}
        </span>
        <span style={{ color: "var(--on-surface-dim)", fontSize: 9, letterSpacing: "0.1em" }}>
          {fgLabel?.toUpperCase() || ""}
        </span>
      </div>

      {/* 24h long vs short bar */}
      <div className="flex items-center gap-2" style={{ minWidth: 160 }}>
        <span className="eyebrow" style={{ color: "var(--on-surface-dim)", fontSize: 9 }}>24H L/S</span>
        <div style={{ display: "flex", height: 6, width: 90, border: "1px solid var(--hairline)", borderRadius: 1, overflow: "hidden" }}>
          <div style={{ width: `${longPct ?? 50}%`, background: "var(--chart-bull)", transition: "width 0.5s ease" }} />
          <div style={{ flex: 1, background: "var(--chart-bear)" }} />
        </div>
        <span className="text-mono" style={{ color: "var(--chart-bull)", fontWeight: 700 }}>
          {longPct != null ? longPct.toFixed(0) : "-"}
        </span>
        <span style={{ color: "var(--on-surface-dim)" }}>/</span>
        <span className="text-mono" style={{ color: "var(--chart-bear)", fontWeight: 700 }}>
          {shortPct != null ? shortPct.toFixed(0) : "-"}
        </span>
      </div>

      <Metric label="L/S RATIO"  value={summary?.ls_ratio_avg     != null ? summary.ls_ratio_avg.toFixed(2)     : "-"} color="var(--on-surface)" />
      <Metric label="TOP TRADER" value={summary?.top_trader_ls_avg != null ? summary.top_trader_ls_avg.toFixed(2) : "-"} color="var(--on-surface-variant)" />
    </div>
  );
}

// ── Pair search ───────────────────────────────────────────────────────────────
function PairSearch({ api, symbol, onSymbolChange }: {
  api: string; symbol: string; onSymbolChange: (s: string) => void;
}) {
  const [query,     setQuery]     = useState("");
  const [results,   setResults]   = useState<SymbolRow[]>([]);
  const [open,      setOpen]      = useState(false);
  const [highlight, setHighlight] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const boxRef   = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    const ac = new AbortController();
    const handle = setTimeout(async () => {
      try {
        const res  = await fetch(`${api}/api/symbols/search?q=${encodeURIComponent(query)}`, { signal: ac.signal });
        const data: { results: SymbolRow[] } = await res.json();
        if (!cancelled) { setResults(data.results || []); setHighlight(0); }
      } catch { /* silent */ }
    }, 150);
    return () => { cancelled = true; ac.abort(); clearTimeout(handle); };
  }, [api, query]);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (!boxRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const pick = (row: SymbolRow) => {
    onSymbolChange(row.symbol.toUpperCase());
    setOpen(false); setQuery(""); inputRef.current?.blur();
  };

  // Enter pressed before the debounced results arrived: resolve the raw query
  // against the search API before binding. Blindly treating typed text as a
  // pair used to bind the Execution tab to nonexistent symbols, which then
  // showed stale data under a wrong label.
  const routeRaw = async (raw: string) => {
    const q = raw.trim().toUpperCase();
    if (!q) return;
    setOpen(false); setQuery(""); inputRef.current?.blur();
    let rows: SymbolRow[] = [];
    try {
      const res = await fetch(`${api}/api/symbols/search?q=${encodeURIComponent(q)}`);
      const data: { results: SymbolRow[] } = await res.json();
      rows = data.results || [];
    } catch { /* fall through */ }
    const hit =
      rows.find((r) => r.symbol === q) ||
      rows.find((r) => r.symbol === `${q}USDT`) ||
      rows[0];
    if (hit) onSymbolChange(hit.symbol.toUpperCase());
    // Unknown symbol: do nothing rather than mislabel the terminal.
  };

  const display = useMemo(() => symbol.replace("USDT", "/USDT"), [symbol]);

  return (
    <div ref={boxRef} style={{ position: "relative", flex: "0 0 auto", width: 190, minWidth: 160 }}>
      <div
        onClick={() => inputRef.current?.focus()}
        style={{
          display: "flex", alignItems: "center", gap: 8, padding: "7px 10px",
          background: "var(--surface-container-lowest)",
          border: `1px solid ${open ? "var(--primary)" : "var(--hairline)"}`,
          borderRadius: "var(--radius-sm)", transition: "border-color 0.15s", cursor: "text",
        }}
      >
        <SearchIcon />
        <input
          ref={inputRef} value={query}
          onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (!open) return;
            if (e.key === "ArrowDown") { e.preventDefault(); setHighlight(h => Math.min(h + 1, results.length - 1)); }
            else if (e.key === "ArrowUp")   { e.preventDefault(); setHighlight(h => Math.max(h - 1, 0)); }
            else if (e.key === "Enter")  { e.preventDefault(); const hit = results[highlight]; if (hit) pick(hit); else if (query.trim()) void routeRaw(query); }
            else if (e.key === "Escape") setOpen(false);
          }}
          placeholder={`Type pair - ${display}`}
          style={{
            flex: 1, background: "transparent", border: "none", outline: "none",
            color: "var(--on-surface)", fontFamily: "inherit",
            fontSize: 12, letterSpacing: "0.04em", textTransform: "uppercase",
          }}
        />
      </div>

      {open && results.length > 0 && (
        <div className="card-glass" style={{ position: "absolute", top: "calc(100% + 6px)", left: 0, right: 0, maxHeight: 360, overflowY: "auto", zIndex: 60, padding: 4 }}>
          {results.map((r, i) => {
            const active = i === highlight, selected = r.symbol === symbol;
            return (
              <button
                key={r.symbol}
                onMouseDown={(e) => { e.preventDefault(); pick(r); }}
                onMouseEnter={() => setHighlight(i)}
                style={{
                  display: "flex", width: "100%", textAlign: "left", padding: "7px 10px", border: "none",
                  background: active ? "rgba(198,198,199,0.10)" : selected ? "rgba(198,198,199,0.05)" : "transparent",
                  color: selected ? "var(--primary)" : "var(--on-surface)",
                  fontSize: 12, fontWeight: selected ? 700 : 500, letterSpacing: "0.04em",
                  cursor: "pointer", borderRadius: 2, alignItems: "center", justifyContent: "space-between", gap: 8,
                }}
              >
                <span>{r.symbol}</span>
                <span style={{ color: "var(--on-surface-dim)", fontSize: 10, letterSpacing: "0.12em" }}>{r.base}/{r.quote}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Shared helpers ────────────────────────────────────────────────────────────
function Metric({ label, value, color, bold, large }: {
  label: string; value: string; color: string; bold?: boolean; large?: boolean;
}) {
  return (
    <div className="flex flex-col" style={{ lineHeight: 1.1, minWidth: 0 }}>
      <span className="eyebrow" style={{ color: "var(--on-surface-dim)", fontSize: 9 }}>{label}</span>
      <span className="text-mono" style={{ color, fontSize: large ? 16 : 12, fontWeight: bold ? 700 : 500, letterSpacing: "-0.01em", marginTop: 1 }}>
        {value}
      </span>
    </div>
  );
}

function SearchIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--on-surface-variant)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" />
    </svg>
  );
}

function LogoMark() {
  // Particle-based "N" - Matrix-esque vertical data rain masked by the
  // letter silhouette, themed in --primary silver. See components/Logo.tsx.
  return <NexusLogo size={30} density={14} pulse />;
}

function formatPrice(n: number, precision: number): string {
  if (!isFinite(n)) return "--";
  return n.toLocaleString(undefined, { minimumFractionDigits: precision, maximumFractionDigits: precision });
}

