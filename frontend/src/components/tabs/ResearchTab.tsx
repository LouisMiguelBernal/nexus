"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import { num, fmtPrice, fmtPct, fmtFixed } from "@/lib/format";
import { useBriefStore, type StoredBrief } from "@/lib/briefStore";
import { renderBriefBody, fmtBriefStamp } from "@/lib/mdRender";

interface Props {
  symbol: string;
  api: string;
}

interface Cluster {
  exchange: string;
  price: number;
  bid_depth: number;
  ask_depth: number;
  net_depth: number;
}

export default function ResearchTab({ symbol, api }: Props) {
  const [brief, setBrief] = useState<Record<string, unknown> | null>(null);
  const [kelly, setKelly] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const aiBrief      = useBriefStore(s => s.brief);
  const isGenerating = useBriefStore(s => s.isGenerating);
  const setAiBrief   = useBriefStore(s => s.setBrief);
  const clearAiBrief = useBriefStore(s => s.clearBrief);
  const setGenerating = useBriefStore(s => s.setGenerating);

  const loadBrief = useCallback(async () => {
    setLoading(true);
    const ac = new AbortController();
    const safeFetch = async <T,>(path: string, label: string): Promise<T | null> => {
      try {
        const r = await fetch(`${api}${path}`, { signal: ac.signal });
        if (!r.ok) {
          console.warn(`[ResearchTab] ${label} → HTTP ${r.status}`);
          return null;
        }
        return (await r.json()) as T;
      } catch (e) {
        if (e instanceof DOMException && e.name === "AbortError") return null;
        console.warn(`[ResearchTab] ${label} fetch failed`, e);
        return null;
      }
    };
    try {
      const [briefRes, kellyRes] = await Promise.all([
        safeFetch<unknown>(`/api/brief/${symbol}`, `brief ${symbol}`),
        safeFetch<unknown>(`/api/risk/kelly/${symbol}`, `kelly ${symbol}`),
      ]);
      setBrief(briefRes as Record<string, unknown> | null);
      setKelly(kellyRes as Record<string, unknown> | null);
    } finally {
      setLoading(false);
    }
    return () => ac.abort();
  }, [api, symbol]);

  // Structured data: fetch once on symbol change.
  useEffect(() => {
    void loadBrief();
  }, [loadBrief]);

  // Hydrate previously-generated AI brief from backend on mount.
  useEffect(() => {
    if (aiBrief) return;
    (async () => {
      try {
        const r = await fetch(`${api}/api/sentiment/brief-load`);
        if (!r.ok) {
          console.warn(`[ResearchTab] brief-load → HTTP ${r.status}`);
          return;
        }
        const d = await r.json();
        if (d?.brief || d?.news_synthesis) setAiBrief(d as StoredBrief);
      } catch (e) {
        console.warn("[ResearchTab] brief-load failed", e);
      }
    })();
  }, [api, aiBrief, setAiBrief]);

  const generateAiBrief = async () => {
    clearAiBrief();
    setGenerating(true);
    try {
      await fetch(`${api}/api/sentiment/brief-clear`, { method: "DELETE" });
    } catch (e) {
      console.warn("[ResearchTab] brief-clear failed (non-fatal)", e);
    }
    try {
      const r = await fetch(`${api}/api/ai/brief`, {
        method: "POST",
        signal: AbortSignal.timeout(150_000),
      });
      const d = await r.json();
      const curFng = useBriefStore.getState().fng;
      const curSm  = useBriefStore.getState().smartMoney;
      const stored: StoredBrief = {
        brief:          d.brief ?? null,
        news_synthesis: d.news_synthesis ?? null,
        news_sentiment: d.news_sentiment ?? null,
        news_count:     d.news_count ?? 0,
        generated_at:   d.generated_at ?? new Date().toISOString(),
        symbol,
        fng_score:  curFng?.score ?? null,
        fng_label:  curFng?.label ?? null,
        sm_signal:  curSm?.signal?.label ?? null,
        sm_score:   curSm?.signal?.score ?? null,
        error: null,
      };
      setAiBrief(stored);
      fetch(`${api}/api/sentiment/brief-save`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(stored),
      }).catch((e) => console.warn("[ResearchTab] brief-save failed (non-fatal)", e));
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Brief failed";
      setAiBrief({
        brief: null, news_synthesis: null, news_sentiment: null, news_count: 0,
        generated_at: new Date().toISOString(), symbol,
        fng_score: null, fng_label: null, sm_signal: null, sm_score: null,
        error: msg,
      });
    } finally {
      setGenerating(false);
    }
  };

  const copyAiBrief = () => {
    if (!aiBrief) return;
    const txt = [
      `NEXUS AI BRIEF - ${aiBrief.symbol ?? symbol} - ${aiBrief.generated_at ? new Date(aiBrief.generated_at).toLocaleString() : ""}`,
      "", aiBrief.news_synthesis ?? "", "", aiBrief.brief ?? "",
    ].filter(Boolean).join("\n");
    navigator.clipboard.writeText(txt).catch(() => {});
  };

  const zones: Array<Record<string, unknown>> = Array.isArray(brief?.zones) ? (brief.zones as Array<Record<string, unknown>>) : [];
  const funding = (brief?.funding as Record<string, unknown> | undefined) || undefined;
  const squeeze = (brief?.squeeze_risk as Record<string, unknown> | undefined) || undefined;
  const markData = (brief?.mark_price as Record<string, unknown> | undefined) || undefined;
  const gate = (brief?.macro_gate as Record<string, unknown> | undefined) || undefined;
  const cvd = (brief?.cvd as Record<string, Record<string, unknown>> | undefined) || undefined;
  const regime = (brief?.regime as Record<string, unknown> | undefined) || undefined;

  const fundingRate = num(funding?.weighted_rate_pct);
  const longSqueeze = num(squeeze?.long_squeeze_risk_pct);
  const shortSqueeze = num(squeeze?.short_squeeze_risk_pct);

  return (
    <div className="flex flex-col gap-2 animate-slide-in">
      {/* Top bar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span style={{ fontSize: "var(--fs-title)", fontWeight: 700 }}>{symbol} Intelligence Brief</span>
          {markData?.mark_price !== undefined ? (
            <span style={{ fontSize: 16, fontWeight: 800, color: "var(--accent-amber)" }}>
              ${fmtPrice(markData.mark_price)}
            </span>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => void loadBrief()} disabled={loading} className="btn-ghost" title="Refresh structured data">
            {loading ? "Loading…" : "REFRESH DATA"}
          </button>
          <button onClick={() => void generateAiBrief()} disabled={isGenerating} className="btn-primary" title="Generate AI synthesis via Gemma 4">
            {isGenerating ? "Synthesising…" : "GENERATE AI BRIEF"}
          </button>
        </div>
      </div>

      {/* AI Brief output - powered by Gemma 4 via Ollama */}
      <AiBriefCard
        brief={aiBrief}
        isGenerating={isGenerating}
        onGenerate={() => void generateAiBrief()}
        onCopy={copyAiBrief}
      />

      {/* Row 1: Key metrics */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 6 }}>
        {/* Funding Rate */}
        <div className="card">
          <div className="card-header">FUNDING RATE</div>
          <div className="card-body">
            <StatRow
              label="Weighted"
              value={fmtPct(fundingRate, 4)}
              color={fundingRate > 0.05 ? "var(--accent-red)" : fundingRate < -0.05 ? "var(--accent-green)" : "var(--text-secondary)"}
            />
            <StatRow label="Classification" value={String(funding?.classification || "-")} />
            <StatRow label="Leverage Impact" value={String(funding?.leverage_impact || "-")} />
          </div>
        </div>

        {/* Squeeze Risk */}
        <div className="card">
          <div className="card-header">SQUEEZE RISK</div>
          <div className="card-body">
            <StatRow
              label="Long Squeeze"
              value={`${longSqueeze.toFixed(0)}%`}
              color={longSqueeze > 50 ? "var(--accent-red)" : "var(--text-secondary)"}
            />
            <StatRow
              label="Short Squeeze"
              value={`${shortSqueeze.toFixed(0)}%`}
              color={shortSqueeze > 50 ? "var(--accent-green)" : "var(--text-secondary)"}
            />
            <StatRow
              label="Alert Level"
              value={String(squeeze?.alert_level || "normal").toUpperCase()}
              color={
                squeeze?.alert_level === "critical"
                  ? "var(--accent-red)"
                  : squeeze?.alert_level === "elevated"
                    ? "var(--accent-amber)"
                    : "var(--text-secondary)"
              }
            />
          </div>
        </div>

        {/* Macro Gate */}
        <div className="card">
          <div className="card-header">MACRO GATE</div>
          <div className="card-body">
            <StatRow
              label="Status"
              value={gate?.is_restricted ? "RESTRICTED" : "OPEN"}
              color={gate?.is_restricted ? "var(--accent-red)" : "var(--accent-green)"}
            />
            {gate?.active_event ? <StatRow label="Event" value={String(gate.active_event)} /> : null}
            <StatRow label="Leverage Cap" value={`${String(gate?.leverage_cap ?? 10)}x`} />
          </div>
        </div>

        {/* Market Regime + Kelly */}
        <div className="card">
          <div className="card-header">REGIME / RISK</div>
          <div className="card-body">
            {regime ? (
              <StatRow
                label="Regime"
                value={String(regime.regime || "unknown").replace(/_/g, " ").toUpperCase()}
                color={
                  String(regime.regime || "").includes("bull")
                    ? "var(--accent-green)"
                    : String(regime.regime || "").includes("bear")
                      ? "var(--accent-red)"
                      : "var(--accent-amber)"
                }
              />
            ) : null}
            {regime ? (
              <StatRow label="Confidence" value={`${(num(regime.confidence) * 100).toFixed(0)}%`} />
            ) : null}
            {kelly ? (
              kelly.warmup ? (
                <>
                  <StatRow
                    label="Kelly Size"
                    value={`WARMUP ${num(kelly.samples)}/${num(kelly.needed) || 30}`}
                    color="var(--accent-amber)"
                  />
                  <StatRow label="Position Cap" value="-" />
                </>
              ) : (
                <>
                  <StatRow
                    label="Kelly Size"
                    value={`${(num(kelly.kelly_final ?? kelly.kelly_half ?? kelly.kelly_fraction) * 100).toFixed(2)}%`}
                    color="var(--accent-cyan)"
                  />
                  <StatRow
                    label="Position Cap"
                    value={`${num(kelly.position_pct_of_collateral ?? num(kelly.kelly_final) * 100).toFixed(2)}%`}
                  />
                </>
              )
            ) : null}
          </div>
        </div>
      </div>

      {/* Row 2: CVD Multi-timeframe - strict null contract: distinguishes
          "no flow yet" (cold start) from genuine zero. */}
      {cvd && Object.keys(cvd).length > 0 ? (
        <div className="card">
          <div className="card-header">CVD (CUMULATIVE VOLUME DELTA)</div>
          <div className="card-body">
            <div style={{ display: "grid", gridTemplateColumns: `repeat(${Object.keys(cvd).length}, 1fr)`, gap: 8 }}>
              {Object.entries(cvd).map(([tf, d]) => {
                const tradeCount = num(d?.trade_count);
                const cvdRaw = d?.cvd;
                const available = (d?.available === true) || tradeCount > 0 || (cvdRaw !== null && cvdRaw !== undefined);
                const val = available ? num(cvdRaw) : 0;
                return (
                  <div key={tf} className="text-center" style={{ opacity: available ? 1 : 0.55 }}>
                    <div style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-tertiary)", fontWeight: 700 }}>{tf.toUpperCase()}</div>
                    <div style={{
                      fontSize: "var(--fs-data)",
                      fontWeight: 700,
                      color: !available ? "var(--text-muted)" : val > 0 ? "var(--accent-green)" : val < 0 ? "var(--accent-red)" : "var(--text-secondary)",
                    }}>
                      {!available ? "-" : `${val > 0 ? "+" : ""}$${Math.abs(val).toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
                    </div>
                    <div style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-muted)" }}>
                      {available ? `${tradeCount.toLocaleString()} trades` : "warming up"}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      ) : null}

      {/* Row 3: Golden Zones */}
      <div className="card">
        <div className="card-header">
          <span>GOLDEN ZONES ({zones.length})</span>
        </div>
        <div className="card-body" style={{ padding: 0, overflow: "auto", maxHeight: 420 }}>
          {zones.length === 0 ? (
            <div style={{ padding: 12, color: "var(--text-muted)", fontSize: "var(--fs-data-xs)" }}>
              No zones detected yet - waiting for order book data
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ width: 24 }}></th>
                  <th>Price</th>
                  <th>Type</th>
                  <th>Tier</th>
                  <th className="col-right">Score</th>
                  <th className="col-right">Exchanges</th>
                  <th className="col-right">Bid Depth</th>
                  <th className="col-right">Ask Depth</th>
                  <th className="col-right">Age (h)</th>
                  <th className="col-right">Persistent</th>
                </tr>
              </thead>
              <tbody>
                {zones.map((z, i) => {
                  const clusters = Array.isArray(z.clusters) ? (z.clusters as unknown as Cluster[]) : [];
                  const isOpen = expanded.has(i);
                  return (
                    <Fragment key={i}>
                      <tr
                        className={`zone-${String(z.tier || "bronze")}`}
                        onClick={() => {
                          setExpanded((prev) => {
                            const next = new Set(prev);
                            if (next.has(i)) next.delete(i);
                            else next.add(i);
                            return next;
                          });
                        }}
                        style={{ cursor: clusters.length > 0 ? "pointer" : "default" }}
                      >
                        <td style={{ textAlign: "center", color: "var(--text-muted)" }}>
                          {clusters.length > 0 ? (isOpen ? "▾" : "▸") : ""}
                        </td>
                        <td style={{ fontWeight: 700 }}>${fmtPrice(z.price_center)}</td>
                        <td>{String(z.zone_type || "")}</td>
                        <td style={{ fontWeight: 700, textTransform: "uppercase" }}>{String(z.tier || "")}</td>
                        <td className="col-right">{fmtFixed(z.score, 2)}</td>
                        <td className="col-right">{String(num(z.exchange_count))}</td>
                        <td className="col-right" style={{ color: "var(--accent-green)" }}>
                          ${num(z.bid_depth_total).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                        </td>
                        <td className="col-right" style={{ color: "var(--accent-red)" }}>
                          ${num(z.ask_depth_total).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                        </td>
                        <td className="col-right">{fmtFixed(z.age_hours, 1)}</td>
                        <td className="col-right">{z.persistent ? "YES" : "-"}</td>
                      </tr>
                      {isOpen && clusters.length > 0 ? (
                        <tr>
                          <td colSpan={10} style={{ padding: "6px 12px 8px 36px", background: "var(--bg-tertiary)" }}>
                            <div style={{ fontSize: "var(--fs-data-xs)", color: "var(--text-tertiary)", fontWeight: 700, marginBottom: 4 }}>
                              PER-EXCHANGE LIMIT ORDERS
                            </div>
                            <table className="data-table" style={{ fontSize: "var(--fs-data-xs)" }}>
                              <thead>
                                <tr>
                                  <th>Exchange</th>
                                  <th className="col-right">Price</th>
                                  <th className="col-right">Bid Depth</th>
                                  <th className="col-right">Ask Depth</th>
                                  <th className="col-right">Net</th>
                                </tr>
                              </thead>
                              <tbody>
                                {clusters.map((c, j) => (
                                  <tr key={j}>
                                    <td style={{ fontWeight: 700, textTransform: "uppercase" }}>{c.exchange}</td>
                                    <td className="col-right">${fmtPrice(c.price)}</td>
                                    <td className="col-right" style={{ color: "var(--accent-green)" }}>
                                      ${num(c.bid_depth).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                                    </td>
                                    <td className="col-right" style={{ color: "var(--accent-red)" }}>
                                      ${num(c.ask_depth).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                                    </td>
                                    <td className="col-right" style={{ color: c.net_depth >= 0 ? "var(--accent-green)" : "var(--accent-red)", fontWeight: 700 }}>
                                      {c.net_depth >= 0 ? "+" : ""}${num(c.net_depth).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

function StatRow({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="flex justify-between items-center" style={{ padding: "2px 0" }}>
      <span style={{ fontSize: "var(--fs-data-sm)", color: "var(--text-tertiary)" }}>{label}</span>
      <span style={{ fontSize: "var(--fs-data)", fontWeight: 700, color: color || "var(--text-primary)" }}>{value}</span>
    </div>
  );
}

function AiBriefCard({
  brief,
  isGenerating,
  onGenerate,
  onCopy,
}: {
  brief: StoredBrief | null;
  isGenerating: boolean;
  onGenerate: () => void;
  onCopy: () => void;
}) {
  const hasContent = !!(brief?.brief || brief?.news_synthesis);
  const stamp = brief?.generated_at ? fmtBriefStamp(brief.generated_at) : null;

  return (
    <div
      className="card"
      style={{
        border: "1px solid var(--hairline)",
        borderRadius: 10,
        background: "var(--surface-container, rgba(127,127,127,0.04))",
      }}
    >
      <div
        className="card-header flex items-center justify-between"
        style={{ gap: 10 }}
      >
        <div className="flex items-center gap-2">
          <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.14em", color: "var(--primary)" }}>
            AI SYNTHESIS · GEMMA 4
          </span>
          {isGenerating && (
            <span
              style={{
                fontSize: 9,
                letterSpacing: "0.14em",
                padding: "2px 8px",
                borderRadius: 20,
                color: "var(--primary)",
                background: "rgba(198,198,199,0.10)",
                border: "1px solid rgba(198,198,199,0.35)",
                animation: "nx-pulse 1.4s ease-in-out infinite",
              }}
            >
              SYNTHESISING…
            </span>
          )}
          {stamp && !isGenerating && (
            <span style={{ fontSize: 10, color: "var(--on-surface-dim)" }}>· {stamp}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {hasContent && (
            <button
              onClick={onCopy}
              className="btn-ghost"
              style={{ fontSize: 10, padding: "4px 10px" }}
              title="Copy brief to clipboard"
            >
              COPY
            </button>
          )}
          <button
            onClick={onGenerate}
            disabled={isGenerating}
            className="btn-ghost"
            style={{ fontSize: 10, padding: "4px 10px" }}
            title="Regenerate"
          >
            {isGenerating ? "…" : hasContent ? "REGENERATE" : "GENERATE"}
          </button>
        </div>
      </div>
      <div
        className="card-body"
        style={{
          position: "relative",
          padding: 14,
          maxHeight: "min(380px, 42vh)",
          overflowY: "auto",
          overflowX: "hidden",
          scrollbarGutter: "stable",
        }}
      >
        <style>{`@keyframes nx-pulse{0%,100%{opacity:.35}50%{opacity:1}}`}</style>

        {brief?.error && (
          <div
            style={{
              fontSize: 12,
              color: "var(--accent-red, #ef4444)",
              padding: "8px 10px",
              borderRadius: 6,
              border: "1px solid rgba(239,68,68,0.35)",
              background: "rgba(239,68,68,0.08)",
            }}
          >
            Brief failed: {brief.error}
          </div>
        )}

        {!hasContent && !brief?.error && !isGenerating && (
          <div style={{ fontSize: 12, color: "var(--on-surface-dim)", lineHeight: 1.55 }}>
            No AI synthesis yet. Click <b style={{ color: "var(--on-surface)" }}>GENERATE AI BRIEF</b> above to run Gemma 4
            over the current zones, funding, OI, squeeze, macro gate, and news feed. Output persists across tab switches.
          </div>
        )}

        {brief?.news_synthesis && (
          <section style={{ marginBottom: brief?.brief ? 14 : 0 }}>
            <div
              style={{
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: "0.14em",
                color: "var(--on-surface-dim)",
                marginBottom: 6,
              }}
            >
              NEWS SYNTHESIS {brief.news_count ? `· ${brief.news_count} HEADLINES` : ""} {brief.news_sentiment ? `· ${String(brief.news_sentiment).toUpperCase()}` : ""}
            </div>
            <div style={{ fontSize: 12.5, lineHeight: 1.7, color: "var(--on-surface)" }}>
              {renderBriefBody(brief.news_synthesis)}
            </div>
          </section>
        )}

        {brief?.brief && (
          <section>
            <div
              style={{
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: "0.14em",
                color: "var(--on-surface-dim)",
                marginBottom: 6,
              }}
            >
              MARKET BRIEF
            </div>
            <div style={{ fontSize: 12.5, lineHeight: 1.7, color: "var(--on-surface)" }}>
              {renderBriefBody(brief.brief)}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
