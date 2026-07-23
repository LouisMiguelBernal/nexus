"use client";

type TabId = "trading" | "alpha" | "heatmap" | "research" | "orderflow" | "alerts" | "docs" | "journal" | "risk";

// Journal (trade calendar · trades · stats · portfolio · AI analysis).
// Flip to `false` to hide the sidebar button (e.g. for demos).
const SHOW_JOURNAL = true;

interface Props {
  active: TabId;
  onChange: (tab: TabId) => void;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}

// Institutional 5-layer hierarchy.
//   Layer 1 (Market Overview) lives in the header strip.
//   Layers 2-5 are surfaced here as primary nav.
//   Detail tabs (Liquidity / Order Flow / Alerts / Docs) sit underneath as
//   drill-downs - they back the same data the primary tabs summarize.
interface NavTab { id: TabId; label: string; shortcut: string; icon: string }
interface NavGroup { eyebrow: string; tabs: NavTab[] }

const NAV_GROUPS: NavGroup[] = [
  {
    eyebrow: "PRIMARY LAYERS",
    tabs: [
      { id: "alpha",    label: "SIGNALS",     shortcut: "⌥2", icon: "signals" },
      { id: "trading",  label: "EXECUTION",   shortcut: "⌥1", icon: "trading" },
      { id: "risk",     label: "RISK",        shortcut: "⌥8", icon: "risk" },
      { id: "research", label: "RESEARCH",    shortcut: "⌥4", icon: "research" },
    ],
  },
  {
    eyebrow: "DETAIL",
    tabs: [
      { id: "heatmap",   label: "LIQUIDITY MAP", shortcut: "⌥3", icon: "heatmap" },
      { id: "orderflow", label: "ORDER FLOW",    shortcut: "⌥5", icon: "flow" },
      { id: "alerts",    label: "ALERTS & NEWS", shortcut: "⌥6", icon: "alerts" },
      { id: "docs",      label: "SYSTEM DOCS",   shortcut: "⌥7", icon: "docs" },
    ],
  },
];

export default function TabBar({ active, onChange, collapsed = false, onToggleCollapse }: Props) {
  const railWidth = collapsed ? 56 : undefined;

  return (
    <nav
      className="no-select flex flex-col"
      style={{
        width: collapsed ? `${railWidth}px` : "var(--nav-side-w)",
        minWidth: collapsed ? `${railWidth}px` : "var(--nav-side-w)",
        background: "var(--surface-container-low)",
        borderRight: "1px solid var(--hairline)",
        height: "100%",
        transition: "width 180ms ease, min-width 180ms ease",
      }}
    >
      {/* Eyebrow header + hamburger */}
      <div
        style={{
          padding: collapsed ? "14px 8px 12px" : "20px 20px 14px 20px",
          borderBottom: "1px solid var(--hairline)",
          display: "flex",
          alignItems: collapsed ? "center" : "flex-start",
          justifyContent: collapsed ? "center" : "space-between",
          gap: 8,
        }}
      >
        {!collapsed && (
          <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
            <div className="eyebrow" style={{ color: "var(--primary)", marginBottom: 4 }}>
              INSTITUTIONAL
            </div>
            <div
              style={{
                color: "var(--on-surface-dim)",
                fontSize: 11,
                letterSpacing: "0.05em",
              }}
            >
              Obsidian Terminal
            </div>
          </div>
        )}
        <button
          onClick={onToggleCollapse}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          style={{
            background: "transparent",
            border: "1px solid var(--hairline)",
            borderRadius: 6,
            padding: "6px 8px",
            color: "var(--on-surface-variant)",
            cursor: "pointer",
            fontFamily: "inherit",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            lineHeight: 1,
            flexShrink: 0,
          }}
          onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "rgba(127,127,127,0.08)"; }}
          onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 6h16" /><path d="M4 12h16" /><path d="M4 18h16" />
          </svg>
        </button>
      </div>

      {/* 5-layer hierarchy: primary 4 layers (Signals/Execution/Risk/Research)
          on top, detail drill-downs below. Header strip = Layer 1 Market
          Overview. */}
      <div className="flex-1 overflow-auto" style={{ paddingTop: 12 }}>
        {NAV_GROUPS.map((group, gi) => (
          <div key={group.eyebrow} style={{ marginBottom: 8 }}>
            {!collapsed && (
              <div
                className="eyebrow"
                style={{
                  padding: "8px 20px 4px",
                  color: "var(--on-surface-dim)",
                  fontSize: 9,
                  letterSpacing: "0.16em",
                  opacity: 0.65,
                  ...(gi > 0 && {
                    borderTop: "1px solid var(--hairline)",
                    marginTop: 4,
                    paddingTop: 12,
                  }),
                }}
              >
                {group.eyebrow}
              </div>
            )}
            {collapsed && gi > 0 && (
              <div style={{ borderTop: "1px solid var(--hairline)", margin: "8px 8px" }} />
            )}
            {group.tabs.map((tab) => {
              const isActive = active === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => onChange(tab.id)}
                  className={`nav-item ${isActive ? "active" : ""}`}
                  style={{
                    width: "100%",
                    textAlign: "left",
                    background: "transparent",
                    fontFamily: "inherit",
                    justifyContent: collapsed ? "center" : undefined,
                    paddingLeft: collapsed ? 0 : undefined,
                    paddingRight: collapsed ? 0 : undefined,
                  }}
                  title={`${tab.label} (${tab.shortcut})`}
                >
                  <NavIcon name={tab.icon} active={isActive} />
                  {!collapsed && <span>{tab.label}</span>}
                  {!collapsed && <span className="kbd">{tab.shortcut}</span>}
                </button>
              );
            })}
          </div>
        ))}
      </div>

      {/* Footer: journal + execute order */}
      <div style={{ borderTop: "1px solid var(--hairline)" }}>
        {SHOW_JOURNAL && !collapsed && (
          <div style={{ padding: "10px 20px 4px", fontSize: 9, color: "var(--on-surface-dim)", letterSpacing: "0.1em", textTransform: "uppercase", opacity: 0.5 }}>
            Tools
          </div>
        )}

        {/* Journal - premium, matches Execute Order chrome. Hidden until demo (SHOW_JOURNAL). */}
        {SHOW_JOURNAL && (
        <div style={{ padding: collapsed ? "6px 8px 8px" : "0 12px 10px" }}>
          <button
            onClick={() => onChange("journal")}
            title="Trading Journal (⌥9)"
            style={{
              width: "100%",
              textAlign: collapsed ? "center" : "left",
              background: active === "journal"
                ? "linear-gradient(135deg, rgba(var(--primary-rgb,198,198,199),0.24) 0%, rgba(var(--primary-rgb,198,198,199),0.10) 100%)"
                : "linear-gradient(135deg, rgba(var(--primary-rgb,198,198,199),0.10) 0%, rgba(var(--primary-rgb,198,198,199),0.04) 100%)",
              border: active === "journal"
                ? "1px solid rgba(var(--primary-rgb,198,198,199),0.55)"
                : "1px solid rgba(var(--primary-rgb,198,198,199),0.25)",
              borderRadius: 8,
              fontFamily: "inherit",
              padding: collapsed ? "8px 0" : "10px 12px",
              display: "flex",
              alignItems: "center",
              justifyContent: collapsed ? "center" : "flex-start",
              gap: 8,
              cursor: "pointer",
              transition: "all 0.15s",
              boxShadow: active === "journal"
                ? "0 0 0 1px rgba(var(--primary-rgb,198,198,199),0.15), 0 2px 10px rgba(var(--primary-rgb,198,198,199),0.12)"
                : "none",
            }}
            onMouseEnter={e => {
              if (active !== "journal") {
                (e.currentTarget as HTMLElement).style.background = "linear-gradient(135deg, rgba(var(--primary-rgb,198,198,199),0.18) 0%, rgba(var(--primary-rgb,198,198,199),0.08) 100%)";
                (e.currentTarget as HTMLElement).style.borderColor = "rgba(var(--primary-rgb,198,198,199),0.45)";
              }
            }}
            onMouseLeave={e => {
              if (active !== "journal") {
                (e.currentTarget as HTMLElement).style.background = "linear-gradient(135deg, rgba(var(--primary-rgb,198,198,199),0.10) 0%, rgba(var(--primary-rgb,198,198,199),0.04) 100%)";
                (e.currentTarget as HTMLElement).style.borderColor = "rgba(var(--primary-rgb,198,198,199),0.25)";
              }
            }}
          >
            <NavIcon name="journal" active={active === "journal"} />
            {!collapsed && (
              <>
                <span style={{
                  fontSize: 11,
                  fontWeight: 600,
                  color: active === "journal" ? "var(--primary)" : "var(--on-surface)",
                  letterSpacing: "0.06em",
                }}>
                  JOURNAL
                </span>
                {active === "journal" && (
                  <span style={{ marginLeft: "auto", width: 5, height: 5, borderRadius: "50%", background: "var(--primary)", display: "inline-block", flexShrink: 0 }} />
                )}
              </>
            )}
          </button>
        </div>
        )}

        {!collapsed && (
          <div style={{ padding: "0 12px 14px" }}>
            <button
              className="btn-primary"
              style={{ width: "100%", padding: "10px 14px", fontSize: 11 }}
            >
              Execute Order
            </button>
            <div
              className="flex items-center justify-end"
              style={{ marginTop: 10, fontSize: 10, color: "var(--on-surface-dim)", letterSpacing: "0.08em" }}
            >
              <span style={{ color: "var(--chart-bull)" }}>● LIVE</span>
            </div>
          </div>
        )}
      </div>
    </nav>
  );
}

function NavIcon({ name, active }: { name: string; active: boolean }) {
  const color = active ? "var(--primary)" : "var(--on-surface-dim)";
  const stroke = 1.6;
  const size = 14;

  const common = { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: color, strokeWidth: stroke, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };

  switch (name) {
    case "trading":
      return (
        <svg {...common}><path d="M3 20V8" /><path d="M9 20V4" /><path d="M15 20v-8" /><path d="M21 20V10" /><path d="M3 20h18" /></svg>
      );
    case "signals":
      return (
        <svg {...common}><path d="M3 17l4-4 3 3 5-6 6 6" /><circle cx="21" cy="7" r="1.2" /></svg>
      );
    case "heatmap":
      return (
        <svg {...common}><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></svg>
      );
    case "research":
      return (
        <svg {...common}><circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" /></svg>
      );
    case "flow":
      return (
        <svg {...common}><path d="M3 12h12" /><path d="M13 6l6 6-6 6" /><path d="M3 6h6" /><path d="M3 18h6" /></svg>
      );
    case "alerts":
      return (
        <svg {...common}><path d="M6 8a6 6 0 1112 0v4l2 3H4l2-3V8z" /><path d="M10 19a2 2 0 004 0" /></svg>
      );
    case "journal":
      return (
        <svg {...common}><rect x="5" y="2" width="14" height="20" rx="2" /><path d="M9 7h6" /><path d="M9 11h6" /><path d="M9 15h4" /><path d="M2 7l2 2 3-3" /></svg>
      );
    case "docs":
      return (
        <svg {...common}><path d="M4 19.5A2.5 2.5 0 016.5 17H20" /><path d="M4 4.5A2.5 2.5 0 016.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15z" /><path d="M9 9h6" /><path d="M9 13h4" /></svg>
      );
    case "risk":
      return (
        <svg {...common}><path d="M12 2L3 21h18L12 2z" /><path d="M12 9v6" /><circle cx="12" cy="18" r="0.6" fill={color} stroke="none" /></svg>
      );
    default:
      return <span style={{ width: size, height: size }} />;
  }
}
