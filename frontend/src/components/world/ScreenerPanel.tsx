"use client";

/**
 * Nexus - equity screener (Yahoo saved screens).
 *
 * The closest keyless equivalent to OpenBB's `equity.screener`. Sortable on any
 * numeric column; nulls always sink regardless of sort direction, so a column
 * with sparse coverage does not fill the top of the table with blanks.
 *
 * Context only - clicking a row does nothing but tell you the symbol, because
 * nothing here is tradable from Nexus.
 */

import { useEffect, useState } from "react";
import { usePolling } from "@/lib/usePolling";

interface Row {
  symbol: string;
  name: string;
  price: number | null;
  change: number | null;
  change_pct: number | null;
  volume: number | null;
  market_cap: number | null;
  pe: number | null;
  week52_change_pct: number | null;
  exchange: string;
}

interface Resp {
  id: string;
  available: boolean;
  reason?: string;
  screens: { id: string; label: string }[];
  rows: Row[];
}

type SortKey = "change_pct" | "volume" | "market_cap" | "pe" | "week52_change_pct";

function compact(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  if (abs >= 1e12) return `${sign}${(abs / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(1)}K`;
  return `${sign}${abs.toFixed(2)}`;
}

function pct(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
}

function dir(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return "var(--on-surface-muted)";
  return v > 0 ? "var(--chart-bull)" : v < 0 ? "var(--chart-bear)" : "var(--on-surface-variant)";
}

export default function ScreenerPanel({ api }: { api: string }) {
  const [id, setId] = useState("most_actives");
  const [sort, setSort] = useState<SortKey>("change_pct");
  const [desc, setDesc] = useState(true);

  const { data, loading } = usePolling<Resp>({
    url: `${api}/api/world/screener?id=${id}&count=40`,
    intervalMs: 180000,
  });

  const screens = data?.screens ?? [{ id: "most_actives", label: "Most Active" }];
  const rows = [...(data?.rows ?? [])].sort((a, b) => {
    const av = a[sort];
    const bv = b[sort];
    if (av == null) return 1; // nulls sink whichever way we sort
    if (bv == null) return -1;
    return desc ? bv - av : av - bv;
  });

  // Sorting by a column then switching screens should keep the column.
  useEffect(() => setDesc(true), [id]);

  const th = (key: SortKey, label: string) => (
    <th
      onClick={() => (sort === key ? setDesc((d) => !d) : (setSort(key), setDesc(true)))}
      className="eyebrow"
      style={{
        textAlign: "right",
        padding: "6px 8px",
        cursor: "pointer",
        userSelect: "none",
        color: sort === key ? "var(--primary)" : undefined,
      }}
    >
      {label}
      {sort === key ? (desc ? " ↓" : " ↑") : ""}
    </th>
  );

  return (
    <div className="card" style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
      <div className="card-header">
        <span>EQUITY SCREENER</span>
        <span className="eyebrow">{rows.length} NAMES</span>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 4, padding: "8px 12px", borderBottom: "1px solid var(--hairline)" }}>
        {screens.map((s) => (
          <button
            key={s.id}
            onClick={() => setId(s.id)}
            className="eyebrow"
            style={{
              padding: "3px 8px",
              borderRadius: 3,
              cursor: "pointer",
              border: `1px solid ${s.id === id ? "var(--border-accent)" : "transparent"}`,
              background: s.id === id ? "var(--surface-container-highest)" : "transparent",
              color: s.id === id ? "var(--primary)" : "var(--on-surface-dim)",
            }}
          >
            {s.label.toUpperCase()}
          </button>
        ))}
      </div>

      <div style={{ flex: 1, minHeight: 0, overflow: "auto" }}>
        {rows.length === 0 ? (
          <div className="eyebrow" style={{ padding: 24, textAlign: "center" }}>
            {loading
              ? "RUNNING SCREEN"
              : `NO RESULTS — ${(data?.reason ?? "yahoo gates this endpoint; usually recovers next poll").toUpperCase()}`}
          </div>
        ) : (
          <table style={{ width: "100%", fontSize: 11, minWidth: 700 }}>
            <thead>
              <tr
                style={{
                  borderBottom: "1px solid var(--hairline)",
                  position: "sticky",
                  top: 0,
                  background: "var(--surface-container)",
                }}
              >
                <th className="eyebrow" style={{ textAlign: "left", padding: "6px 8px" }}>SYMBOL</th>
                <th className="eyebrow" style={{ textAlign: "left", padding: "6px 8px" }}>NAME</th>
                <th className="eyebrow" style={{ textAlign: "right", padding: "6px 8px" }}>LAST</th>
                {th("change_pct", "CHG %")}
                {th("volume", "VOLUME")}
                {th("market_cap", "MKT CAP")}
                {th("pe", "P/E")}
                {th("week52_change_pct", "52W %")}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.symbol} style={{ borderBottom: "1px solid var(--hairline)" }}>
                  <td className="text-mono" style={{ padding: "4px 8px", color: "var(--primary)", fontWeight: 600 }}>
                    {r.symbol}
                  </td>
                  <td className="truncate-1" style={{ padding: "4px 8px", maxWidth: 200, color: "var(--on-surface-dim)" }}>
                    {r.name}
                  </td>
                  <td className="text-mono" style={{ padding: "4px 8px", textAlign: "right" }}>
                    {r.price != null ? r.price.toFixed(2) : "—"}
                  </td>
                  <td className="text-mono" style={{ padding: "4px 8px", textAlign: "right", color: dir(r.change_pct) }}>
                    {pct(r.change_pct)}
                  </td>
                  <td className="text-mono" style={{ padding: "4px 8px", textAlign: "right" }}>{compact(r.volume)}</td>
                  <td className="text-mono" style={{ padding: "4px 8px", textAlign: "right" }}>{compact(r.market_cap)}</td>
                  <td className="text-mono" style={{ padding: "4px 8px", textAlign: "right" }}>
                    {r.pe != null ? r.pe.toFixed(1) : "—"}
                  </td>
                  <td
                    className="text-mono"
                    style={{ padding: "4px 8px", textAlign: "right", color: dir(r.week52_change_pct) }}
                  >
                    {pct(r.week52_change_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
