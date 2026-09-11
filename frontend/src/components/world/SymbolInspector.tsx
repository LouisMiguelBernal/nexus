"use client";

/**
 * Nexus - cross-asset instrument inspector.
 *
 * Search any listed instrument and read its chart, fundamentals, analyst
 * targets and option chain. This is the OpenBB surface: equity, ETF, index,
 * currency, commodity and rates all resolve through the same endpoints.
 *
 * Read the header carefully - **nothing here is tradable from Nexus.** Every
 * row is tagged `cross_asset` at the source precisely so it can never be
 * mistaken for a perp symbol. Its job is answering questions the perp screens
 * cannot: is COIN leading BTC, what is MSTR's implied vol doing, is the equity
 * tape confirming the move.
 */

import { useEffect, useMemo, useState } from "react";
import { usePolling } from "@/lib/usePolling";
import CrossAssetChart, { type Candle } from "./CrossAssetChart";

const RANGES = ["1mo", "3mo", "6mo", "1y", "5y"] as const;
const MIN_QUERY = 2;
type Range = (typeof RANGES)[number];

interface Hit {
  symbol: string;
  name: string;
  exchange: string;
  type: string;
}

interface Fundamentals {
  available: boolean;
  reason?: string;
  name?: string;
  sector?: string | null;
  industry?: string | null;
  country?: string | null;
  summary?: string | null;
  market_cap?: number | null;
  trailing_pe?: number | null;
  forward_pe?: number | null;
  price_to_book?: number | null;
  price_to_sales?: number | null;
  beta?: number | null;
  eps?: number | null;
  dividend_yield?: number | null;
  profit_margin?: number | null;
  operating_margin?: number | null;
  gross_margin?: number | null;
  return_on_equity?: number | null;
  revenue_growth?: number | null;
  earnings_growth?: number | null;
  total_debt?: number | null;
  free_cashflow?: number | null;
  debt_to_equity?: number | null;
  recommendation?: string | null;
  target_mean?: number | null;
  target_high?: number | null;
  target_low?: number | null;
  analysts?: number | null;
  income?: { end_date: number | null; revenue: number | null; net_income: number | null; net_margin: number | null }[];
  holdings?: { symbol: string; name: string; weight: number | null }[];
}

interface Chain {
  available: boolean;
  reason?: string;
  underlying_price: number | null;
  expiry: number | null;
  expirations: number[];
  call_open_interest: number;
  put_open_interest: number;
  call_volume: number;
  put_volume: number;
  open_interest_credible: boolean;
  put_call_ratio: number | null;
  put_call_basis: "open_interest" | "volume" | null;
  max_pain: number | null;
  calls: { strike: number; last: number | null; iv: number | null; open_interest: number | null }[];
  puts: { strike: number; last: number | null; iv: number | null; open_interest: number | null }[];
}

function compact(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  if (abs >= 1e12) return `${sign}${(abs / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(1)}K`;
  // Open interest and share counts are integers; "0.00 contracts" is nonsense.
  return `${sign}${Number.isInteger(abs) ? abs : abs.toFixed(2)}`;
}

function money(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toFixed(Math.abs(v) >= 1 ? 2 : 4);
}

/** Yahoo returns these as fractions; the UI wants percent. */
function ratioPct(v: number | null | undefined): string | null {
  if (v == null || !Number.isFinite(v)) return null;
  return `${(v * 100).toFixed(2)}%`;
}

function fixed(v: number | null | undefined, d = 2): string | null {
  if (v == null || !Number.isFinite(v)) return null;
  return v.toFixed(d);
}

function dir(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "var(--on-surface-muted)";
  return v > 0 ? "var(--chart-bull)" : v < 0 ? "var(--chart-bear)" : "var(--on-surface-variant)";
}

function Row({ label, value }: { label: string; value: string | null }) {
  if (value === null) return null;
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        gap: 8,
        padding: "3px 0",
        borderBottom: "1px solid var(--hairline)",
      }}
    >
      <span className="eyebrow" style={{ letterSpacing: "0.1em" }}>{label}</span>
      <span className="text-mono" style={{ fontSize: 11 }}>{value}</span>
    </div>
  );
}

function Card({ title, right, children }: { title: string; right?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="card" style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
      <div className="card-header">
        <span>{title}</span>
        {right}
      </div>
      <div className="card-body" style={{ flex: 1, minHeight: 0, overflow: "auto" }}>{children}</div>
    </div>
  );
}

const day = (unix: number) => new Date(unix * 1000).toISOString().slice(0, 10);

export default function SymbolInspector({ api }: { api: string }) {
  const [symbol, setSymbol] = useState("COIN");
  const [draft, setDraft] = useState("");
  const [range, setRange] = useState<Range>("6mo");
  const [hits, setHits] = useState<Hit[]>([]);
  const [expiry, setExpiry] = useState<number | null>(null);

  // Debounced symbol search. Nothing is set synchronously in the effect body:
  // a too-short query simply skips the fetch, and the dropdown's visibility is
  // derived below rather than stored, so there is no state to clear.
  useEffect(() => {
    const q = draft.trim();
    if (q.length < MIN_QUERY) return;

    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const res = await fetch(`${api}/api/world/search?q=${encodeURIComponent(q)}`);
        const json: { results?: Hit[] } = await res.json();
        if (!cancelled) setHits((json.results ?? []).slice(0, 8));
      } catch {
        if (!cancelled) setHits([]);
      }
    }, 250);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [draft, api]);

  const chart = usePolling<{ candles: Candle[] }>({
    url: `${api}/api/world/chart/${encodeURIComponent(symbol)}?range=${range}`,
    intervalMs: 120000,
  });
  const fundamentals = usePolling<Fundamentals>({
    url: `${api}/api/world/fundamentals/${encodeURIComponent(symbol)}`,
    intervalMs: 900000,
  });
  const chainUrl = useMemo(() => {
    const base = `${api}/api/world/options/${encodeURIComponent(symbol)}`;
    return expiry ? `${base}?expiry=${expiry}` : base;
  }, [api, symbol, expiry]);

  const chain = usePolling<Chain>({ url: chainUrl, intervalMs: 180000 });

  const f = fundamentals.data;
  const c = chain.data;
  const candles = useMemo(() => chart.data?.candles ?? [], [chart.data]);
  const last = candles.length ? candles[candles.length - 1].close : null;
  const implied =
    f?.target_mean != null && last ? ((f.target_mean - last) / last) * 100 : null;

  // Only show hits for a query still long enough to have produced them; that
  // makes the stale-results-after-backspace case impossible without an effect.
  const visibleHits = draft.trim().length >= MIN_QUERY ? hits : [];

  const pick = (s: string) => {
    setSymbol(s.toUpperCase());
    setDraft("");
    setHits([]);
    // A new underlying invalidates the selected expiry - dates do not carry
    // over between symbols. Reset here, where the symbol actually changes.
    setExpiry(null);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {/* ── Search + header ──────────────────────────────────────────── */}
      <div className="card" style={{ padding: "12px 14px" }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 14, alignItems: "flex-end" }}>
          <div style={{ position: "relative", minWidth: 240 }}>
            <div className="eyebrow" style={{ marginBottom: 4 }}>INSTRUMENT · CONTEXT ONLY</div>
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") pick(visibleHits[0]?.symbol ?? draft);
                if (e.key === "Escape") { setDraft(""); setHits([]); }
              }}
              placeholder="Search — COIN, MSTR, SPY, GC=F"
              spellCheck={false}
              className="text-mono"
              style={{
                width: "100%",
                height: 28,
                padding: "0 8px",
                fontSize: 12,
                color: "var(--on-surface)",
                background: "var(--bg-input)",
                border: "1px solid var(--hairline-strong)",
                borderRadius: "var(--radius)",
              }}
            />
            {visibleHits.length > 0 && (
              <div
                className="card"
                style={{ position: "absolute", zIndex: 40, top: 56, left: 0, right: 0, maxHeight: 240, overflow: "auto" }}
              >
                {visibleHits.map((h) => (
                  <button
                    key={h.symbol}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => pick(h.symbol)}
                    style={{
                      display: "flex",
                      width: "100%",
                      gap: 8,
                      padding: "5px 8px",
                      textAlign: "left",
                      background: "transparent",
                      borderBottom: "1px solid var(--hairline)",
                      cursor: "pointer",
                    }}
                  >
                    <span className="text-mono" style={{ width: 72, color: "var(--primary)", fontSize: 11 }}>{h.symbol}</span>
                    <span className="truncate-1" style={{ fontSize: 11, color: "var(--on-surface-dim)" }}>
                      {h.name} · {h.type}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div>
            <div className="eyebrow" style={{ marginBottom: 4 }}>{symbol}</div>
            <div className="text-mono" style={{ fontSize: 22, fontWeight: 700, lineHeight: 1 }}>{money(last)}</div>
          </div>

          {f?.available && (
            <>
              <div>
                <div className="eyebrow">MKT CAP</div>
                <div className="text-mono" style={{ fontSize: 13, fontWeight: 600 }}>{compact(f.market_cap)}</div>
              </div>
              {f.recommendation && (
                <div>
                  <div className="eyebrow">CONSENSUS</div>
                  <div className="text-mono" style={{ fontSize: 13, fontWeight: 600, color: "var(--accent-blue)" }}>
                    {f.recommendation.replace("_", " ").toUpperCase()}
                  </div>
                </div>
              )}
              {implied != null && (
                <div>
                  <div className="eyebrow">TARGET IMPLIED</div>
                  <div className="text-mono" style={{ fontSize: 13, fontWeight: 600, color: dir(implied) }}>
                    {implied > 0 ? "+" : ""}{implied.toFixed(1)}%
                  </div>
                </div>
              )}
            </>
          )}

          <div style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
            {RANGES.map((r) => (
              <button
                key={r}
                onClick={() => setRange(r)}
                className="eyebrow"
                style={{
                  padding: "3px 8px",
                  borderRadius: 3,
                  cursor: "pointer",
                  border: `1px solid ${r === range ? "var(--border-accent)" : "transparent"}`,
                  background: r === range ? "var(--surface-container-highest)" : "transparent",
                  color: r === range ? "var(--primary)" : "var(--on-surface-dim)",
                }}
              >
                {r.toUpperCase()}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── Chart ────────────────────────────────────────────────────── */}
      <Card title={`PRICE · ${symbol}`} right={<span className="eyebrow">{candles.length} BARS</span>}>
        {candles.length === 0 ? (
          <div className="eyebrow" style={{ padding: 28, textAlign: "center" }}>
            {chart.loading ? "LOADING CANDLES" : "NO DATA FOR THIS SYMBOL"}
          </div>
        ) : (
          <CrossAssetChart candles={candles} height={320} />
        )}
      </Card>

      {/* ── Fundamentals ─────────────────────────────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 12 }}>
        <Card title="VALUATION">
          {f?.available === false ? (
            <div className="eyebrow" style={{ padding: 14, textAlign: "center" }}>
              UNAVAILABLE — {(f.reason ?? "upstream declined").toUpperCase()}
            </div>
          ) : (
            <div>
              <Row label="MARKET CAP" value={f?.market_cap != null ? compact(f.market_cap) : null} />
              <Row label="TRAILING P/E" value={fixed(f?.trailing_pe)} />
              <Row label="FORWARD P/E" value={fixed(f?.forward_pe)} />
              <Row label="PRICE / BOOK" value={fixed(f?.price_to_book)} />
              <Row label="PRICE / SALES" value={fixed(f?.price_to_sales)} />
              <Row label="EPS TTM" value={fixed(f?.eps)} />
              <Row label="BETA" value={fixed(f?.beta)} />
              <Row label="DIVIDEND YIELD" value={ratioPct(f?.dividend_yield)} />
            </div>
          )}
        </Card>

        <Card title="QUALITY & GROWTH">
          <div>
            <Row label="GROSS MARGIN" value={ratioPct(f?.gross_margin)} />
            <Row label="OPERATING MARGIN" value={ratioPct(f?.operating_margin)} />
            <Row label="PROFIT MARGIN" value={ratioPct(f?.profit_margin)} />
            <Row label="RETURN ON EQUITY" value={ratioPct(f?.return_on_equity)} />
            <Row label="REVENUE GROWTH" value={ratioPct(f?.revenue_growth)} />
            <Row label="EARNINGS GROWTH" value={ratioPct(f?.earnings_growth)} />
            <Row label="FREE CASH FLOW" value={f?.free_cashflow != null ? compact(f.free_cashflow) : null} />
            <Row label="DEBT / EQUITY" value={fixed(f?.debt_to_equity)} />
          </div>
        </Card>

        <Card title="OPTIONS" right={c?.expiry ? <span className="eyebrow">{day(c.expiry)}</span> : null}>
          {c?.available === false || (!c && !chain.loading) ? (
            <div className="eyebrow" style={{ padding: 14, textAlign: "center" }}>
              NO CHAIN — {(c?.reason ?? "not listed").toUpperCase()}
            </div>
          ) : (
            <div>
              <Row label="UNDERLYING" value={money(c?.underlying_price)} />
              <Row
                label="PUT / CALL"
                value={c?.put_call_ratio != null ? c.put_call_ratio.toFixed(2) : null}
              />
              <Row label="CALL VOLUME" value={c?.call_volume ? compact(c.call_volume) : null} />
              <Row label="PUT VOLUME" value={c?.put_volume ? compact(c.put_volume) : null} />
              {/* Max pain is an open-interest construct. When Yahoo is not
                  populating OI it stays absent rather than being faked. */}
              <Row label="MAX PAIN" value={c?.max_pain != null ? String(c.max_pain) : null} />
              <Row
                label="OPEN INTEREST"
                value={
                  c?.open_interest_credible
                    ? `${compact(c.call_open_interest)} C / ${compact(c.put_open_interest)} P`
                    : "UNRELIABLE UPSTREAM"
                }
              />
              {c?.put_call_basis && (
                <div className="eyebrow" style={{ marginTop: 6, letterSpacing: "0.06em", lineHeight: 1.5 }}>
                  RATIO ON {c.put_call_basis === "volume" ? "VOLUME" : "OPEN INTEREST"} BASIS
                </div>
              )}
              {(c?.expirations ?? []).length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 8 }}>
                  {(c?.expirations ?? []).slice(0, 8).map((e) => (
                    <button
                      key={e}
                      onClick={() => setExpiry(e)}
                      className="eyebrow"
                      style={{
                        padding: "2px 6px",
                        borderRadius: 3,
                        cursor: "pointer",
                        border: `1px solid ${e === c?.expiry ? "var(--border-accent)" : "var(--hairline-strong)"}`,
                        color: e === c?.expiry ? "var(--primary)" : "var(--on-surface-dim)",
                        background: "transparent",
                      }}
                    >
                      {day(e)}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </Card>
      </div>

      {/* ── Income statement ─────────────────────────────────────────── */}
      {f?.income && f.income.length > 0 && (
        <Card title="ANNUAL INCOME STATEMENT">
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", fontSize: 11, minWidth: 380 }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--hairline)" }}>
                  <th className="eyebrow" style={{ textAlign: "left", padding: "4px 8px" }}>FISCAL YEAR</th>
                  <th className="eyebrow" style={{ textAlign: "right", padding: "4px 8px" }}>REVENUE</th>
                  <th className="eyebrow" style={{ textAlign: "right", padding: "4px 8px" }}>NET INCOME</th>
                  <th className="eyebrow" style={{ textAlign: "right", padding: "4px 8px" }}>NET MARGIN</th>
                </tr>
              </thead>
              <tbody>
                {f.income.map((r, i) => (
                  <tr key={r.end_date ?? i} style={{ borderBottom: "1px solid var(--hairline)" }}>
                    <td className="text-mono" style={{ padding: "4px 8px", color: "var(--on-surface-dim)" }}>
                      {r.end_date ? new Date(r.end_date * 1000).getFullYear() : "—"}
                    </td>
                    <td className="text-mono" style={{ padding: "4px 8px", textAlign: "right" }}>{compact(r.revenue)}</td>
                    <td className="text-mono" style={{ padding: "4px 8px", textAlign: "right", color: dir(r.net_income) }}>
                      {compact(r.net_income)}
                    </td>
                    <td className="text-mono" style={{ padding: "4px 8px", textAlign: "right", color: dir(r.net_margin) }}>
                      {r.net_margin != null ? `${r.net_margin.toFixed(1)}%` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {f?.summary && (
        <Card title="PROFILE">
          <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginBottom: 8 }}>
            {[f.sector, f.industry, f.country].filter(Boolean).map((t) => (
              <span
                key={String(t)}
                className="eyebrow"
                style={{ padding: "2px 6px", border: "1px solid var(--hairline-strong)", borderRadius: 3, letterSpacing: "0.06em" }}
              >
                {t}
              </span>
            ))}
          </div>
          <p style={{ fontSize: 11, lineHeight: 1.5, color: "var(--on-surface-dim)", margin: 0 }}>{f.summary}</p>
        </Card>
      )}
    </div>
  );
}
