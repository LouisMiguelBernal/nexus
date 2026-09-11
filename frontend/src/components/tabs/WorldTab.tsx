"use client";

/**
 * Nexus - World Layer: cross-asset context + global-event intelligence.
 *
 * This tab answers one question the perp screens cannot: *what is the rest of
 * the world doing, and is it about to reprice my book?* Everything on it is
 * context - there are no order controls and no tradable symbols here.
 *
 * The two readings at the top are the ones that actually feed the engines:
 *   - RISK APPETITE conditions the alpha engine's regime weight selection
 *   - GEO RISK feeds the macro gate and can tighten position sizing
 * Both are advisory until Phase 6, and the panel says so.
 */

import { useState } from "react";
import { usePolling } from "@/lib/usePolling";
import AdvisoryNotice from "@/components/AdvisoryNotice";
import SymbolInspector from "@/components/world/SymbolInspector";
import ScreenerPanel from "@/components/world/ScreenerPanel";

interface Props {
  api: string;
}

interface Quote {
  symbol: string;
  name: string;
  price: number;
  change_pct: number;
  market_open: boolean;
  currency: string;
  spark: number[];
  group: string;
}

interface BoardResp {
  groups: string[];
  quotes: Record<string, Quote[]>;
  age_seconds: number | null;
}

interface Axis {
  [key: string]: number | null;
}

interface RegimeResp {
  risk_appetite?: {
    score: number | null;
    state: string;
    axes: Axis;
    coverage: number;
  };
  stress?: { score: number | null; level: string };
  age_seconds: number | null;
}

interface Indicator {
  id: string;
  label: string;
  unit: string;
  available: boolean;
  latest: number | null;
  latest_date: string | null;
  change_abs: number | null;
  change_yoy: number | null;
  points: { date: string; value: number }[];
}

interface MacroResp {
  indicators: Indicator[];
  curve: { label: string; years: number; yield: number | null; change: number | null }[];
  curve_spread: number | null;
  inverted: boolean | null;
  age_seconds: number | null;
}

interface GeoResp {
  risk?: {
    score: number | null;
    raw_score?: number;
    band: string;
    components: Record<string, number | null>;
    available_weight: number;
    enriched: boolean;
    top_countries: { country: string; score: number }[];
  };
  seismic?: { available: boolean; events: { magnitude: number; place: string; tsunami: boolean }[] };
  disasters?: { available: boolean; events: { title: string; level: string; link: string }[] };
  space_weather?: { available: boolean; geomagnetic: number; radiation: number; radio_blackout: number };
  wires?: { available: boolean; items: { title: string; link: string; source: string }[]; keyword_hits?: Record<string, number> };
  natural?: { available: boolean; by_category: Record<string, number> };
  cyber?: {
    available: boolean;
    catalog_size?: number;
    added_7d?: number;
    added_30d?: number;
    ransomware_7d?: number;
    recent?: { cve: string; vendor: string; product: string; date_added: string; ransomware: boolean }[];
  };
  aviation?: {
    available: boolean;
    total_aircraft?: number;
    regions?: { region: string; available: boolean; aircraft?: number; warming_up?: boolean; deviation_pct?: number | null }[];
  };
  enrichment?: { available: boolean; mode?: string; reason?: string; sample?: boolean };
  age_seconds: number | null;
}

type View = "overview" | "inspector" | "screener";

const VIEWS: { id: View; label: string }[] = [
  { id: "overview", label: "OVERVIEW" },
  { id: "inspector", label: "INSTRUMENT" },
  { id: "screener", label: "SCREENER" },
];

const GROUP_LABEL: Record<string, string> = {
  index: "INDICES",
  rates: "RATES",
  currency: "CURRENCY",
  commodity: "COMMODITIES",
  sector: "SECTORS",
  equity: "EQUITIES",
};

const BAND_COLOR: Record<string, string> = {
  critical: "var(--accent-red-bright)",
  elevated: "var(--accent-orange)",
  watch: "var(--accent-amber)",
  normal: "var(--chart-bull)",
  unknown: "var(--on-surface-muted)",
};

function dir(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "var(--on-surface-muted)";
  if (v > 0) return "var(--chart-bull)";
  if (v < 0) return "var(--chart-bear)";
  return "var(--on-surface-variant)";
}

function num(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 10000) return v.toLocaleString("en-US", { maximumFractionDigits: 0 });
  return v.toFixed(abs >= 1 ? digits : 4);
}

function pct(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

/** FRED publishes each series in its own scale; lift it back to a readable unit. */
function reading(i: Indicator): string {
  if (i.latest == null) return "—";
  if (i.unit === "%") return `${i.latest.toFixed(2)}%`;
  if (i.unit === "$B") {
    return Math.abs(i.latest) >= 1000
      ? `$${(i.latest / 1000).toFixed(2)}T`
      : `$${i.latest.toFixed(0)}B`;
  }
  // PAYEMS is in thousands of persons: 159075 is 159.1M jobs, not 159K.
  if (i.unit === "K") return `${(i.latest / 1000).toFixed(1)}M`;
  return i.latest.toLocaleString("en-US", { maximumFractionDigits: 1 });
}

/**
 * The period-on-period change, in the same unit the headline reading uses.
 * Payrolls are published in thousands, so a raw "+162" next to "159.1M" reads
 * as 162 jobs rather than 162,000.
 */
function delta(i: Indicator): string {
  if (i.change_abs == null) return "—";
  const sign = i.change_abs > 0 ? "+" : "";
  if (i.unit === "K") return `${sign}${i.change_abs.toFixed(0)}K`;
  if (i.unit === "$B") {
    return Math.abs(i.change_abs) >= 1000
      ? `${sign}$${(i.change_abs / 1000).toFixed(2)}T`
      : `${sign}$${i.change_abs.toFixed(0)}B`;
  }
  if (i.unit === "%") return `${sign}${i.change_abs.toFixed(2)}pp`;
  return `${sign}${i.change_abs.toFixed(2)}`;
}

function Spark({ points, up }: { points: number[]; up: boolean }) {
  if (!points || points.length < 2) return <div style={{ width: 52, height: 16 }} />;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const step = 52 / (points.length - 1);
  const d = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${(i * step).toFixed(1)},${(16 - ((p - min) / span) * 16).toFixed(1)}`)
    .join(" ");
  return (
    <svg width={52} height={16} viewBox="0 0 52 16" style={{ flexShrink: 0 }} aria-hidden>
      <path d={d} fill="none" stroke={up ? "var(--chart-bull)" : "var(--chart-bear)"} strokeWidth="1" opacity="0.8" />
    </svg>
  );
}

/** A -100..+100 reading rendered as a centred bar. Zero is the middle. */
function Gauge({ value, label, hint }: { value: number | null; label: string; hint?: string }) {
  const v = value ?? 0;
  const pos = ((v + 100) / 200) * 100;
  return (
    <div style={{ flex: 1, minWidth: 190 }}>
      <div className="eyebrow" style={{ marginBottom: 4 }}>{label}</div>
      <div className="text-mono" style={{ fontSize: 22, fontWeight: 700, color: dir(value), lineHeight: 1 }}>
        {value == null ? "—" : (value > 0 ? "+" : "") + value.toFixed(1)}
      </div>
      <div style={{ position: "relative", height: 4, background: "var(--surface-container-highest)", borderRadius: 2, marginTop: 8 }}>
        <div style={{ position: "absolute", left: "50%", top: -2, width: 1, height: 8, background: "var(--outline-variant)" }} />
        {value != null && (
          <div
            style={{
              position: "absolute",
              left: `calc(${pos}% - 3px)`,
              top: -2,
              width: 6,
              height: 8,
              borderRadius: 1,
              background: dir(value),
            }}
          />
        )}
      </div>
      {hint && <div className="eyebrow" style={{ marginTop: 5, letterSpacing: "0.08em" }}>{hint}</div>}
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

function Age({ seconds }: { seconds: number | null | undefined }) {
  if (seconds == null) return <span className="eyebrow">NO DATA</span>;
  const stale = seconds > 600;
  return (
    <span className="eyebrow" style={{ color: stale ? "var(--accent-orange)" : undefined }}>
      {seconds < 60 ? `${Math.round(seconds)}S AGO` : `${Math.round(seconds / 60)}M AGO`}
    </span>
  );
}

function ViewSwitch({ view, onChange }: { view: View; onChange: (v: View) => void }) {
  return (
    <div style={{ display: "flex", gap: 4 }}>
      {VIEWS.map((v) => (
        <button
          key={v.id}
          onClick={() => onChange(v.id)}
          className="eyebrow"
          style={{
            padding: "4px 10px",
            borderRadius: 3,
            cursor: "pointer",
            border: `1px solid ${v.id === view ? "var(--border-accent)" : "var(--hairline)"}`,
            background: v.id === view ? "var(--surface-container-highest)" : "transparent",
            color: v.id === view ? "var(--primary)" : "var(--on-surface-dim)",
          }}
        >
          {v.label}
        </button>
      ))}
    </div>
  );
}

export default function WorldTab({ api }: Props) {
  const [view, setView] = useState<View>("overview");
  const [group, setGroup] = useState<string>("index");

  // Hooks run unconditionally (rules of hooks), so the overview's four feeds are
  // gated by `enabled` rather than by the early return below - otherwise sitting
  // on the Instrument view would keep polling four endpoints nobody is reading.
  const onOverview = view === "overview";
  const board = usePolling<BoardResp>({ url: `${api}/api/world/board`, intervalMs: 60000, enabled: onOverview });
  const regime = usePolling<RegimeResp>({ url: `${api}/api/world/regime`, intervalMs: 60000, enabled: onOverview });
  const macro = usePolling<MacroResp>({ url: `${api}/api/world/macro`, intervalMs: 300000, enabled: onOverview });
  const geo = usePolling<GeoResp>({ url: `${api}/api/world/geo`, intervalMs: 120000, enabled: onOverview });

  const roro = regime.data?.risk_appetite;
  const stress = regime.data?.stress;
  const risk = geo.data?.risk;
  const rows = board.data?.quotes?.[group] ?? [];
  const groups = board.data?.groups ?? Object.keys(GROUP_LABEL);

  if (view !== "overview") {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 12, minHeight: "100%" }}>
        <AdvisoryNotice />
        <ViewSwitch view={view} onChange={setView} />
        {view === "inspector" ? <SymbolInspector api={api} /> : <ScreenerPanel api={api} />}
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, minHeight: "100%" }}>
      <AdvisoryNotice />
      <ViewSwitch view={view} onChange={setView} />

      {/* ── Headline readings: the two that feed the engines ─────────── */}
      <div className="card" style={{ padding: "14px 16px", display: "flex", flexWrap: "wrap", gap: 24, alignItems: "flex-start" }}>
        <Gauge
          value={roro?.score ?? null}
          label="RISK APPETITE"
          hint={`${(roro?.state ?? "unknown").replace("_", "-").toUpperCase()} · CONDITIONS ALPHA REGIME`}
        />

        <div style={{ flex: 1, minWidth: 170 }}>
          <div className="eyebrow" style={{ marginBottom: 4 }}>MACRO STRESS</div>
          <div className="text-mono" style={{ fontSize: 22, fontWeight: 700, lineHeight: 1, color: "var(--on-surface)" }}>
            {stress?.score == null ? "—" : stress.score.toFixed(0)}
          </div>
          <div className="eyebrow" style={{ marginTop: 8, letterSpacing: "0.08em" }}>
            {(stress?.level ?? "unknown").toUpperCase()}
          </div>
        </div>

        <div style={{ flex: 1, minWidth: 200 }}>
          <div className="eyebrow" style={{ marginBottom: 4 }}>GEOPOLITICAL RISK</div>
          <div
            className="text-mono"
            style={{ fontSize: 22, fontWeight: 700, lineHeight: 1, color: BAND_COLOR[risk?.band ?? "unknown"] }}
          >
            {risk?.score == null ? "—" : risk.score.toFixed(0)}
            <span style={{ fontSize: 12, color: "var(--on-surface-dim)" }}> /100</span>
          </div>
          <div className="eyebrow" style={{ marginTop: 8, letterSpacing: "0.08em", color: BAND_COLOR[risk?.band ?? "unknown"] }}>
            {(risk?.band ?? "unknown").toUpperCase()} · FEEDS MACRO GATE
          </div>
          {risk != null && risk.available_weight < 0.6 && (
            <div className="eyebrow" style={{ marginTop: 3, color: "var(--accent-orange)", letterSpacing: "0.06em" }}>
              THIN COVERAGE {Math.round(risk.available_weight * 100)}%
            </div>
          )}
        </div>

        <div style={{ minWidth: 150 }}>
          <div className="eyebrow" style={{ marginBottom: 6 }}>SOURCES</div>
          {[
            ["CROSS-ASSET", board.data?.age_seconds],
            ["FRED MACRO", macro.data?.age_seconds],
            ["GLOBAL EVENTS", geo.data?.age_seconds],
          ].map(([label, age]) => (
            <div key={String(label)} style={{ display: "flex", justifyContent: "space-between", gap: 10, fontSize: 10 }}>
              <span style={{ color: "var(--on-surface-dim)" }}>{label}</span>
              <Age seconds={age as number | null} />
            </div>
          ))}
          <div
            style={{ display: "flex", justifyContent: "space-between", gap: 10, fontSize: 10, marginTop: 2 }}
            title={geo.data?.enrichment?.reason ?? undefined}
          >
            <span style={{ color: "var(--on-surface-dim)" }}>WORLDMONITOR</span>
            <span className="eyebrow" style={{ color: risk?.enriched ? "var(--chart-bull)" : "var(--on-surface-muted)" }}>
              {/* "No key" and "unreachable" are different states; say which. */}
              {risk?.enriched
                ? geo.data?.enrichment?.sample
                  ? "SAMPLE"
                  : "ENRICHED"
                : geo.data?.enrichment?.mode === "unavailable"
                  ? "NO KEY"
                  : "LOCAL ONLY"}
            </span>
          </div>
        </div>
      </div>

      {/* ── Cross-asset board ────────────────────────────────────────── */}
      <Card
        title="CROSS-ASSET BOARD"
        right={
          <span style={{ display: "flex", gap: 4 }}>
            {groups.map((g) => (
              <button
                key={g}
                onClick={() => setGroup(g)}
                className="eyebrow"
                style={{
                  padding: "2px 7px",
                  borderRadius: 3,
                  border: `1px solid ${g === group ? "var(--border-accent)" : "transparent"}`,
                  background: g === group ? "var(--surface-container-highest)" : "transparent",
                  color: g === group ? "var(--primary)" : "var(--on-surface-dim)",
                  cursor: "pointer",
                }}
              >
                {GROUP_LABEL[g] ?? g.toUpperCase()}
              </button>
            ))}
          </span>
        }
      >
        {rows.length === 0 ? (
          <div className="eyebrow" style={{ padding: 16, textAlign: "center" }}>
            {board.loading ? "LOADING BOARD" : "NO DATA — POLLER HAS NOT REPORTED YET"}
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(178px, 1fr))", gap: 8 }}>
            {rows.map((q) => (
              <div
                key={q.symbol}
                style={{
                  padding: "8px 10px",
                  border: "1px solid var(--hairline)",
                  borderRadius: "var(--radius)",
                  background: "var(--surface-container-low)",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 6 }}>
                  <span style={{ fontSize: 11, color: "var(--on-surface-variant)" }} className="truncate-1">{q.name}</span>
                  {!q.market_open && <span className="eyebrow" style={{ fontSize: 8 }}>CLSD</span>}
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginTop: 4 }}>
                  <div>
                    <div className="text-mono" style={{ fontSize: 14, fontWeight: 700 }}>{num(q.price)}</div>
                    <div className="text-mono" style={{ fontSize: 11, fontWeight: 600, color: dir(q.change_pct) }}>
                      {pct(q.change_pct)}
                    </div>
                  </div>
                  <Spark points={q.spark} up={q.change_pct >= 0} />
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* ── Curve + risk components ──────────────────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 12 }}>
        <Card
          title="US TREASURY CURVE"
          right={
            <span
              className="eyebrow"
              style={{ color: macro.data?.inverted ? "var(--accent-red-bright)" : "var(--chart-bull)" }}
            >
              {macro.data?.inverted == null ? "—" : macro.data.inverted ? "INVERTED" : "NORMAL"}
            </span>
          }
        >
          <div style={{ display: "flex", gap: 18, flexWrap: "wrap" }}>
            {(macro.data?.curve ?? []).map((c) => (
              <div key={c.label} style={{ minWidth: 62 }}>
                <div className="eyebrow">{c.label}</div>
                <div className="text-mono" style={{ fontSize: 15, fontWeight: 700 }}>
                  {c.yield == null ? "—" : `${c.yield.toFixed(2)}%`}
                </div>
                <div className="text-mono" style={{ fontSize: 10, color: dir(c.change) }}>
                  {c.change == null ? "—" : `${c.change > 0 ? "+" : ""}${c.change.toFixed(3)}`}
                </div>
              </div>
            ))}
            <div style={{ minWidth: 80 }}>
              <div className="eyebrow">10Y − 13W</div>
              <div className="text-mono" style={{ fontSize: 15, fontWeight: 700, color: dir(macro.data?.curve_spread) }}>
                {macro.data?.curve_spread == null ? "—" : macro.data.curve_spread.toFixed(3)}
              </div>
            </div>
          </div>
        </Card>

        <Card title="GEO RISK COMPONENTS" right={<Age seconds={geo.data?.age_seconds} />}>
          {Object.entries(risk?.components ?? {}).map(([name, value]) => (
            <div key={name} style={{ display: "flex", alignItems: "center", gap: 8, padding: "3px 0" }}>
              <span className="eyebrow" style={{ width: 108, letterSpacing: "0.1em" }}>
                {name.replace("_", " ").toUpperCase()}
              </span>
              <div style={{ flex: 1, height: 4, background: "var(--surface-container-highest)", borderRadius: 2 }}>
                {value != null && (
                  <div
                    style={{
                      width: `${Math.min(value, 100)}%`,
                      height: "100%",
                      borderRadius: 2,
                      background: value >= 60 ? "var(--accent-red)" : value >= 30 ? "var(--accent-orange)" : "var(--chart-bull)",
                    }}
                  />
                )}
              </div>
              <span
                className="text-mono"
                style={{ width: 44, textAlign: "right", fontSize: 11, color: value == null ? "var(--on-surface-muted)" : "var(--on-surface)" }}
              >
                {/* A dead feed reads "N/A", never 0 - they are not the same signal. */}
                {value == null ? "N/A" : value.toFixed(0)}
              </span>
            </div>
          ))}
          {geo.data?.wires?.keyword_hits && Object.keys(geo.data.wires.keyword_hits).length > 0 && (
            <div style={{ marginTop: 10, display: "flex", flexWrap: "wrap", gap: 5 }}>
              {Object.entries(geo.data.wires.keyword_hits).map(([term, n]) => (
                <span
                  key={term}
                  className="eyebrow"
                  style={{
                    padding: "2px 6px",
                    border: "1px solid var(--hairline-strong)",
                    borderRadius: 3,
                    letterSpacing: "0.06em",
                  }}
                >
                  {term} ×{n}
                </span>
              ))}
            </div>
          )}
        </Card>
      </div>

      {/* ── FRED macro board ─────────────────────────────────────────── */}
      <Card title="MACRO INDICATORS · FRED" right={<Age seconds={macro.data?.age_seconds} />}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(210px, 1fr))", gap: 8 }}>
          {(macro.data?.indicators ?? []).map((i) => (
            <div
              key={i.id}
              style={{
                padding: "8px 10px",
                border: "1px solid var(--hairline)",
                borderRadius: "var(--radius)",
                background: "var(--surface-container-low)",
                opacity: i.available ? 1 : 0.45,
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: 6, alignItems: "baseline" }}>
                <span style={{ fontSize: 11, color: "var(--on-surface-variant)" }} className="truncate-1">{i.label}</span>
                <Spark points={i.points.map((p) => p.value)} up={(i.change_yoy ?? i.change_abs ?? 0) >= 0} />
              </div>
              <div className="text-mono" style={{ fontSize: 15, fontWeight: 700, marginTop: 3 }}>{reading(i)}</div>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 6, marginTop: 2 }}>
                <span className="eyebrow" style={{ letterSpacing: "0.06em" }}>{i.latest_date ?? "—"}</span>
                <span className="text-mono" style={{ fontSize: 10, color: dir(i.change_yoy ?? i.change_abs) }}>
                  {i.change_yoy != null ? `${pct(i.change_yoy)} YoY` : delta(i)}
                </span>
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* ── Global events ────────────────────────────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 12 }}>
        <Card title="CONFLICT & POLICY WIRE">
          {(geo.data?.wires?.items ?? []).slice(0, 14).map((n) => (
            <a
              key={n.link || n.title}
              href={n.link}
              target="_blank"
              rel="noopener noreferrer"
              style={{ display: "block", padding: "5px 0", borderBottom: "1px solid var(--hairline)", color: "var(--on-surface)" }}
            >
              <div style={{ fontSize: 11, lineHeight: 1.35 }}>{n.title}</div>
              <span className="eyebrow" style={{ letterSpacing: "0.06em" }}>{n.source}</span>
            </a>
          ))}
          {(geo.data?.wires?.items ?? []).length === 0 && (
            <div className="eyebrow" style={{ padding: 12, textAlign: "center" }}>NO WIRE ITEMS</div>
          )}
        </Card>

        <Card
          title="PHYSICAL EVENTS"
          right={
            <span className="eyebrow">
              G{geo.data?.space_weather?.geomagnetic ?? 0} · S{geo.data?.space_weather?.radiation ?? 0} · R
              {geo.data?.space_weather?.radio_blackout ?? 0}
            </span>
          }
        >
          <div className="eyebrow" style={{ marginBottom: 4 }}>SEISMIC · M4.5+ 24H</div>
          {(geo.data?.seismic?.events ?? []).slice(0, 5).map((e, idx) => (
            <div key={idx} style={{ display: "flex", gap: 8, padding: "2px 0", fontSize: 11 }}>
              <span
                className="text-mono"
                style={{ width: 34, fontWeight: 700, color: e.magnitude >= 6 ? "var(--accent-orange)" : "var(--on-surface-variant)" }}
              >
                {e.magnitude.toFixed(1)}
              </span>
              <span className="truncate-1" style={{ color: "var(--on-surface-dim)" }}>{e.place}</span>
              {e.tsunami && <span className="eyebrow" style={{ color: "var(--accent-red)" }}>TSU</span>}
            </div>
          ))}

          <div className="eyebrow" style={{ margin: "10px 0 4px" }}>GDACS ALERTS</div>
          {(geo.data?.disasters?.events ?? []).slice(0, 5).map((e, idx) => (
            <div key={idx} style={{ display: "flex", gap: 8, padding: "2px 0", fontSize: 11 }}>
              <span
                className="eyebrow"
                style={{
                  width: 46,
                  color:
                    e.level === "red"
                      ? "var(--accent-red-bright)"
                      : e.level === "orange"
                        ? "var(--accent-orange)"
                        : "var(--chart-bull-dim)",
                }}
              >
                {e.level.toUpperCase()}
              </span>
              <span className="truncate-1" style={{ color: "var(--on-surface-dim)" }}>{e.title}</span>
            </div>
          ))}

          {geo.data?.natural?.by_category && (
            <>
              <div className="eyebrow" style={{ margin: "10px 0 4px" }}>NASA EONET · OPEN</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                {Object.entries(geo.data.natural.by_category).map(([cat, n]) => (
                  <span
                    key={cat}
                    className="eyebrow"
                    style={{ padding: "2px 6px", border: "1px solid var(--hairline-strong)", borderRadius: 3, letterSpacing: "0.06em" }}
                  >
                    {cat} {n}
                  </span>
                ))}
              </div>
            </>
          )}
        </Card>

        <Card
          title="CYBER · CISA KEV"
          right={<span className="eyebrow">{geo.data?.cyber?.catalog_size ?? 0} CATALOGUED</span>}
        >
          <div style={{ display: "flex", gap: 18, marginBottom: 8 }}>
            {[
              ["ADDED 7D", geo.data?.cyber?.added_7d],
              ["ADDED 30D", geo.data?.cyber?.added_30d],
              ["RANSOMWARE 7D", geo.data?.cyber?.ransomware_7d],
            ].map(([label, value]) => (
              <div key={String(label)}>
                <div className="eyebrow">{label}</div>
                <div
                  className="text-mono"
                  style={{
                    fontSize: 15,
                    fontWeight: 700,
                    color: label === "RANSOMWARE 7D" && Number(value) > 0 ? "var(--accent-red)" : "var(--on-surface)",
                  }}
                >
                  {value ?? "—"}
                </div>
              </div>
            ))}
          </div>
          {(geo.data?.cyber?.recent ?? []).slice(0, 6).map((v) => (
            <div key={v.cve} style={{ display: "flex", gap: 8, padding: "2px 0", fontSize: 11 }}>
              <span className="text-mono" style={{ width: 118, color: "var(--primary)" }}>{v.cve}</span>
              <span className="truncate-1" style={{ color: "var(--on-surface-dim)" }}>
                {v.vendor} {v.product}
              </span>
              {v.ransomware && <span className="eyebrow" style={{ color: "var(--accent-red)" }}>RANSOM</span>}
            </div>
          ))}
        </Card>

        <Card
          title="AVIATION · OPENSKY"
          right={<span className="eyebrow">{geo.data?.aviation?.total_aircraft ?? 0} TRACKED</span>}
        >
          {(geo.data?.aviation?.regions ?? []).map((r) => (
            <div
              key={r.region}
              style={{ display: "flex", alignItems: "baseline", gap: 8, padding: "4px 0", borderBottom: "1px solid var(--hairline)" }}
            >
              <span className="eyebrow" style={{ width: 92, letterSpacing: "0.1em" }}>{r.region.toUpperCase()}</span>
              <span className="text-mono" style={{ fontSize: 13, fontWeight: 600 }}>
                {r.available ? r.aircraft : "—"}
              </span>
              <span
                className="text-mono"
                style={{ marginLeft: "auto", fontSize: 10, color: dir(r.deviation_pct) }}
              >
                {/* A deviation needs a baseline; say so rather than showing 0%. */}
                {r.warming_up
                  ? "BASELINE WARMING"
                  : r.deviation_pct != null
                    ? `${r.deviation_pct > 0 ? "+" : ""}${r.deviation_pct.toFixed(1)}% VS BASE`
                    : "—"}
              </span>
            </div>
          ))}
          <div className="eyebrow" style={{ marginTop: 8, letterSpacing: "0.06em", lineHeight: 1.5 }}>
            DISPLAY ONLY — AIRSPACE DEVIATION IS NOT SCORED INTO GEO RISK
          </div>
        </Card>
      </div>
    </div>
  );
}
