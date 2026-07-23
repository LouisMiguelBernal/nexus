"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface Props {
  symbol: string;
  api: string;
}

interface VenueHealth {
  name: string;
  connected: boolean;
  staleness_s: number | null;
  gaps: number;
}

export default function LiveMapTab({ symbol, api }: Props) {
  const [zones, setZones] = useState<Array<Record<string, unknown>>>([]);
  const [oi, setOi] = useState<Record<string, unknown> | null>(null);
  const [deribit, setDeribit] = useState<Record<string, unknown> | null>(null);
  const [mark, setMark] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [venues, setVenues] = useState<VenueHealth[]>([]);

  // Single in-flight request gate. Manual refresh aborts the polling fetch
  // (and vice-versa) so we can never apply stale state writes on top of a
  // newer payload - the previous double-fetch path could interleave.
  const acRef = useRef<AbortController | null>(null);

  const fetchAll = useCallback(async () => {
    acRef.current?.abort();
    const ac = new AbortController();
    acRef.current = ac;
    setLoading(true);
    try {
      const [zRes, oiRes, dRes, tRes, hRes] = await Promise.all([
        fetch(`${api}/api/zones/${symbol}`, { signal: ac.signal }).then((r) => (r.ok ? r.json() : null)),
        fetch(`${api}/api/oi/${symbol}`, { signal: ac.signal }).then((r) => (r.ok ? r.json() : null)),
        fetch(`${api}/api/deribit/options/BTC`, { signal: ac.signal }).then((r) => (r.ok ? r.json() : null)),
        fetch(`${api}/api/ticker/${symbol}`, { signal: ac.signal }).then((r) => (r.ok ? r.json() : null)),
        fetch(`${api}/api/feed/health`, { signal: ac.signal }).then((r) => (r.ok ? r.json() : null)),
      ]);
      if (ac.signal.aborted) return;
      setZones((zRes?.zones as Array<Record<string, unknown>> | undefined) ?? []);
      setOi(oiRes);
      setDeribit(dRes);
      if (tRes?.last_price) setMark(Number(tRes.last_price));
      // Per-venue feed health drives the failover badge - Binance → OKX → MEXC.
      // The matrix back-end already exposes staleness_ms + gap counts; we
      // normalize to seconds here to keep the UI consistent.
      if (hRes && typeof hRes === "object") {
        const list: VenueHealth[] = [];
        const vMap = (hRes as Record<string, unknown>).venues;
        if (vMap && typeof vMap === "object") {
          for (const [name, raw] of Object.entries(vMap as Record<string, Record<string, unknown>>)) {
            const stalenessMs = typeof raw.staleness_ms === "number" ? raw.staleness_ms : null;
            list.push({
              name,
              connected: raw.connected !== false,
              staleness_s: stalenessMs == null ? null : stalenessMs / 1000,
              gaps: typeof raw.gaps === "number" ? raw.gaps : 0,
            });
          }
        }
        setVenues(list);
      }
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      console.warn(`[LiveMapTab] fetchAll ${symbol} failed`, e);
    } finally {
      if (!ac.signal.aborted) setLoading(false);
    }
  }, [api, symbol]);

  // Manual refresh button delegates to the same gated fetcher.
  const refresh = fetchAll;

  useEffect(() => {
    void fetchAll();
    let timer: ReturnType<typeof setInterval> | null = null;
    const start = () => {
      if (timer) return;
      timer = setInterval(() => { void fetchAll(); }, 15000);
    };
    const stop = () => {
      if (timer) { clearInterval(timer); timer = null; }
    };
    if (!document.hidden) start();
    const onVisibility = () => {
      if (document.hidden) stop();
      else { void fetchAll(); start(); }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      acRef.current?.abort();
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [fetchAll]);

  const pcr = deribit?.put_call_ratio as Record<string, unknown> | undefined;
  const maxPain = deribit?.max_pain as Record<string, unknown> | undefined;
  const trend = oi?.trend as Record<string, unknown> | undefined;

  const golden = zones.filter((z) => z.tier === "golden" || z.tier === "platinum");
  const silver = zones.filter((z) => z.tier === "silver");
  const bronze = zones.filter((z) => z.tier === "bronze");

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-xl font-bold">Live Zone Map - {symbol}</h2>
        <FeedHealthBadge venues={venues} />
        <button onClick={() => void refresh()} disabled={loading}
          className="px-4 py-2 bg-[#222233] text-xs rounded hover:bg-[#333] disabled:opacity-50">
          {loading ? "..." : "Refresh"}
        </button>
      </div>

      {/* Quick stats row */}
      <div className="grid grid-cols-4 gap-4">
        <MiniCard label="Total Zones" value={String(zones.length)} />
        <MiniCard label="Golden+" value={String(golden.length)} color="#c6c6c7" />
        <MiniCard label="OI Trend" value={String(trend?.trend || "-")}
          color={trend?.trend === "rising" ? "#00e676" : trend?.trend === "falling" ? "#ff1744" : "#8888aa"} />
        <MiniCard label="Put/Call Ratio" value={pcr?.put_call_ratio ? Number(pcr.put_call_ratio).toFixed(3) : "-"}
          color={String(pcr?.sentiment) === "bearish" ? "#ff1744" : String(pcr?.sentiment) === "bullish" ? "#00e676" : "#8888aa"} />
      </div>

      {/* Deribit options */}
      {maxPain && (
        <div className="bg-[#111118] border border-[#222233] rounded-lg p-4">
          <h3 className="text-[10px] font-bold text-[#8888aa] tracking-widest mb-2">DERIBIT OPTIONS</h3>
          <div className="grid grid-cols-3 gap-4 text-xs">
            <div><span className="text-[#8888aa]">Max Pain: </span><span className="font-bold">${Number(maxPain.max_pain || 0).toLocaleString()}</span></div>
            <div><span className="text-[#8888aa]">Call OI: </span><span className="font-bold">{Number(pcr?.call_oi || 0).toLocaleString()}</span></div>
            <div><span className="text-[#8888aa]">Put OI: </span><span className="font-bold">{Number(pcr?.put_oi || 0).toLocaleString()}</span></div>
          </div>
        </div>
      )}

      {/* Visual zone map */}
      {zones.length > 0 && <ZoneMap zones={zones} mark={mark} />}

      {/* Zone tiers */}
      {golden.length > 0 && <ZoneTable title="GOLDEN / PLATINUM ZONES" zones={golden} />}
      {silver.length > 0 && <ZoneTable title="SILVER ZONES" zones={silver} />}
      {bronze.length > 0 && <ZoneTable title="BRONZE ZONES" zones={bronze} />}

      {zones.length === 0 && (
        <div className="text-center py-12 text-[#555]">
          <p className="text-lg">Waiting for multi-exchange order book data...</p>
          <p className="text-xs mt-2">Zones appear after WebSocket feeds populate order books</p>
        </div>
      )}
    </div>
  );
}

function ZoneMap({ zones, mark }: { zones: Array<Record<string, unknown>>; mark: number | null }) {
  // Collect numeric bounds
  const lows = zones.map((z) => Number(z.price_low || 0)).filter((v) => v > 0);
  const highs = zones.map((z) => Number(z.price_high || 0)).filter((v) => v > 0);
  if (lows.length === 0 || highs.length === 0) return null;

  const allPrices = [...lows, ...highs, ...(mark ? [mark] : [])];
  const pMin = Math.min(...allPrices);
  const pMax = Math.max(...allPrices);
  const pad = (pMax - pMin) * 0.05 || 1;
  const yMin = pMin - pad;
  const yMax = pMax + pad;

  const H = 360;
  const W = 900;
  const leftPad = 70;
  const rightPad = 20;
  const topPad = 12;
  const botPad = 12;
  const plotH = H - topPad - botPad;
  const plotW = W - leftPad - rightPad;

  const yFor = (p: number) => topPad + (1 - (p - yMin) / (yMax - yMin)) * plotH;

  const tierColor = (tier: string) => {
    if (tier === "platinum") return "#e0e0ff";
    if (tier === "golden") return "#c6c6c7";
    if (tier === "silver") return "#b8b8c8";
    return "#8b5a2b";
  };
  const tierOpacity = (tier: string) => {
    if (tier === "platinum") return 0.55;
    if (tier === "golden") return 0.45;
    if (tier === "silver") return 0.28;
    return 0.18;
  };

  // Price axis ticks
  const ticks = 6;
  const tickVals = Array.from({ length: ticks + 1 }, (_, i) => yMin + ((yMax - yMin) * i) / ticks);

  // Sort so wider/weaker zones render first, hotter on top
  const tierRank = (t: string) => (t === "platinum" ? 4 : t === "golden" ? 3 : t === "silver" ? 2 : 1);
  const ordered = [...zones].sort((a, b) => tierRank(String(a.tier)) - tierRank(String(b.tier)));

  return (
    <div className="bg-[#111118] border border-[#222233] rounded-lg p-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-[10px] font-bold text-[#8888aa] tracking-widest">AGGREGATED LIQUIDITY MAP</h3>
        {mark !== null && (
          <span className="text-xs text-[#8888aa]">
            Mark <span className="text-[#e8e8f0] font-bold">${mark.toLocaleString()}</span>
          </span>
        )}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" preserveAspectRatio="none">
        {/* Grid + price ticks */}
        {tickVals.map((v, i) => (
          <g key={i}>
            <line x1={leftPad} x2={W - rightPad} y1={yFor(v)} y2={yFor(v)} stroke="#1a1a25" strokeWidth={1} />
            <text x={leftPad - 6} y={yFor(v) + 3} fill="#555" fontSize={10} textAnchor="end" fontFamily="monospace">
              ${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}
            </text>
          </g>
        ))}

        {/* Zone bands */}
        {ordered.map((z, i) => {
          const lo = Number(z.price_low || 0);
          const hi = Number(z.price_high || 0);
          if (!(lo > 0 && hi > 0)) return null;
          const tier = String(z.tier || "bronze");
          const type = String(z.zone_type || "");
          const yTop = yFor(hi);
          const yBot = yFor(lo);
          const h = Math.max(1, yBot - yTop);
          const col = tierColor(tier);
          const op = tierOpacity(tier);
          // Width scaled by zone score (0..1 roughly)
          const score = Number(z.score || 0);
          const w = Math.min(plotW, Math.max(plotW * 0.35, plotW * (0.35 + Math.min(score, 1) * 0.65)));
          return (
            <g key={i}>
              <rect x={leftPad} y={yTop} width={w} height={h} fill={col} opacity={op} />
              <rect x={leftPad} y={yTop} width={w} height={1} fill={col} opacity={Math.min(1, op + 0.3)} />
              <rect x={leftPad} y={yBot - 1} width={w} height={1} fill={col} opacity={Math.min(1, op + 0.3)} />
              {h > 14 && (
                <text x={leftPad + 6} y={yTop + 11} fill={col} fontSize={10} fontFamily="monospace" opacity={0.95}>
                  {tier.toUpperCase()} · {type} · {score.toFixed(2)}
                </text>
              )}
            </g>
          );
        })}

        {/* Mark needle */}
        {mark !== null && (
          <g>
            <line x1={leftPad} x2={W - rightPad} y1={yFor(mark)} y2={yFor(mark)}
              stroke="#e8e8f0" strokeWidth={1} strokeDasharray="4 3" />
            <rect x={W - rightPad - 78} y={yFor(mark) - 9} width={78} height={18} fill="#e8e8f0" />
            <text x={W - rightPad - 39} y={yFor(mark) + 4} fill="#111118" fontSize={11}
              textAnchor="middle" fontFamily="monospace" fontWeight="bold">
              ${mark.toLocaleString(undefined, { maximumFractionDigits: 0 })}
            </text>
          </g>
        )}
      </svg>

      {/* Legend */}
      <div className="flex items-center gap-4 mt-2 text-[10px] text-[#8888aa]">
        <LegendSwatch color="#e0e0ff" label="Platinum" />
        <LegendSwatch color="#c6c6c7" label="Golden" />
        <LegendSwatch color="#b8b8c8" label="Silver" />
        <LegendSwatch color="#8b5a2b" label="Bronze" />
        <span className="ml-auto">Bar width ∝ score</span>
      </div>
    </div>
  );
}

function LegendSwatch({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="inline-block w-3 h-3 rounded-sm" style={{ background: color, opacity: 0.6 }} />
      {label}
    </span>
  );
}

function ZoneTable({ title, zones }: { title: string; zones: Array<Record<string, unknown>> }) {
  return (
    <div className="bg-[#111118] border border-[#222233] rounded-lg p-4">
      <h3 className="text-[10px] font-bold text-[#8888aa] tracking-widest mb-2">{title}</h3>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-[#8888aa] border-b border-[#222233]">
            <th className="text-left p-2">Price Range</th>
            <th className="text-left p-2">Type</th>
            <th className="text-right p-2">Score</th>
            <th className="text-right p-2">Exchanges</th>
            <th className="text-right p-2">Bid Depth</th>
            <th className="text-right p-2">Ask Depth</th>
            <th className="text-right p-2">Age</th>
            <th className="text-center p-2">Persistent</th>
          </tr>
        </thead>
        <tbody>
          {zones.map((z, i) => (
            <tr key={i} className={`border-b border-[#1a1a25] zone-${String(z.tier)}`}>
              <td className="p-2 font-bold">${Number(z.price_low || 0).toLocaleString()} - ${Number(z.price_high || 0).toLocaleString()}</td>
              <td className="p-2">{String(z.zone_type || "")}</td>
              <td className="p-2 text-right font-bold">{Number(z.score || 0).toFixed(2)}</td>
              <td className="p-2 text-right">{String(z.exchange_count || 0)}</td>
              <td className="p-2 text-right text-[#00e676]">${Number(z.bid_depth_total || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
              <td className="p-2 text-right text-[#ff1744]">${Number(z.ask_depth_total || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
              <td className="p-2 text-right">{Number(z.age_hours || 0).toFixed(1)}h</td>
              <td className="p-2 text-center">{z.persistent ? "Yes" : "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MiniCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="bg-[#111118] border border-[#222233] rounded-lg p-3 text-center">
      <div className="text-[10px] text-[#8888aa] tracking-wider">{label}</div>
      <div className="text-lg font-bold mt-1" style={{ color: color || "#e8e8f0" }}>{value}</div>
    </div>
  );
}

/* ---- Feed health / failover badge ----
 * Shows the active primary venue + a strip of fallbacks. Spec failover order
 * is Binance → OKX → MEXC. A venue is "active" if connected AND staleness
 * under 5s. The first active venue in priority order is the data source. */
const FAILOVER_ORDER = ["binance", "okx", "mexc"] as const;

function FeedHealthBadge({ venues }: { venues: VenueHealth[] }) {
  if (!venues || venues.length === 0) return null;

  const byName: Record<string, VenueHealth> = {};
  for (const v of venues) byName[v.name.toLowerCase()] = v;

  const activeOf = (v: VenueHealth | undefined): boolean =>
    !!v && v.connected && (v.staleness_s == null || v.staleness_s < 5);
  const primary = FAILOVER_ORDER.find((n) => activeOf(byName[n])) ?? null;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "4px 10px",
        border: "1px solid var(--hairline)",
        borderRadius: 3,
        background: "var(--surface-container-low)",
        fontSize: 10,
        letterSpacing: "0.10em",
      }}
      title="Failover order: Binance → OKX → MEXC. The first connected, fresh feed is the active source."
    >
      <span style={{ color: "var(--on-surface-dim)", letterSpacing: "0.18em", fontWeight: 700 }}>
        FEED
      </span>
      {FAILOVER_ORDER.map((name) => {
        const v = byName[name];
        const active = activeOf(v);
        const isPrimary = primary === name;
        const dotColor = !v
          ? "var(--on-surface-muted)"
          : !v.connected
          ? "var(--chart-bear)"
          : v.staleness_s != null && v.staleness_s >= 5
          ? "var(--primary)"
          : "var(--chart-bull)";
        return (
          <span
            key={name}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              opacity: active ? 1 : 0.55,
              fontWeight: isPrimary ? 700 : 500,
              color: isPrimary ? "var(--primary)" : "var(--on-surface-variant)",
            }}
          >
            <span
              style={{
                width: 7,
                height: 7,
                borderRadius: "50%",
                background: dotColor,
                boxShadow: isPrimary ? `0 0 6px ${dotColor}` : "none",
              }}
            />
            {name.toUpperCase()}
            {v?.gaps ? (
              <span style={{ color: "var(--primary)", fontVariantNumeric: "tabular-nums" }}>
                {" "}{v.gaps}g
              </span>
            ) : null}
          </span>
        );
      })}
      {!primary && (
        <span style={{ color: "var(--chart-bear)", fontWeight: 700, letterSpacing: "0.14em" }}>
          ALL DOWN
        </span>
      )}
    </div>
  );
}
