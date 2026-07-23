'use client'

import React, { useState, useRef, useEffect } from 'react'

type SectionId =
  | 'overview'
  | 'fusion-engine'
  | 'alpha-engine'
  | 'technical-indicators'
  | 'market-structure'
  | 'risk-engine'
  | 'circuit-breaker'
  | 'liquidity-map'
  | 'order-flow'
  | 'ai-synthesis'
  | 'data-sources'
  | 'reading-signals'

interface NavItem { id: SectionId; label: string; badge?: string; badgeColor?: string }
interface FormulaBlock {
  name: string; formula: string
  params: { symbol: string; description: string }[]
  interpretation: string; leverageUseCase: string
  thresholds?: { value: string; meaning: string; action: string }[]
}

const NAV_ITEMS: NavItem[] = [
  { id: 'overview',              label: 'System overview' },
  { id: 'fusion-engine',         label: 'Fusion engine',         badge: '3 venues',   badgeColor: 'teal'   },
  { id: 'alpha-engine',          label: 'Alpha engine',          badge: '11 × 5',     badgeColor: 'amber'  },
  { id: 'technical-indicators',  label: 'Technical indicators',  badge: '12 algos',   badgeColor: 'purple' },
  { id: 'market-structure',      label: 'Market structure',      badge: 'OBI+VPIN',   badgeColor: 'teal'   },
  { id: 'risk-engine',           label: 'Risk engine',           badge: 'VaR+Kelly',  badgeColor: 'coral'  },
  { id: 'circuit-breaker',       label: 'Circuit breaker',       badge: 'event-bus',  badgeColor: 'coral'  },
  { id: 'liquidity-map',         label: 'Liquidity map',         badge: 'Live',       badgeColor: 'green'  },
  { id: 'order-flow',            label: 'Order flow',            badge: 'Live',       badgeColor: 'green'  },
  { id: 'ai-synthesis',          label: 'AI synthesis',          badge: 'Gemma 4',    badgeColor: 'blue'   },
  { id: 'data-sources',          label: 'Data sources & limits' },
  { id: 'reading-signals',       label: 'How to read signals' },
]

const BADGE: Record<string, string> = {
  amber:  'bg-amber-500/15 text-amber-400 border border-amber-500/20',
  teal:   'bg-teal-500/15 text-teal-400 border border-teal-500/20',
  purple: 'bg-purple-500/15 text-purple-400 border border-purple-500/20',
  coral:  'bg-orange-500/15 text-orange-400 border border-orange-500/20',
  blue:   'bg-blue-500/15 text-blue-400 border border-blue-500/20',
  green:  'bg-emerald-500/15 text-emerald-400 border border-emerald-500/20',
}

// ─── Reusable primitives ──────────────────────────────────────────────────────

function SectionHeader({ title, subtitle, tag }: { title: string; subtitle: string; tag?: string }) {
  return (
    <div className="mb-8 pb-6 border-b" style={{ borderColor: 'var(--hairline)' }}>
      {tag && <span className="inline-block text-[11px] font-mono font-medium tracking-widest uppercase mb-3" style={{ color: 'var(--accent-amber)' }}>{tag}</span>}
      <h2 className="text-2xl font-semibold mb-2" style={{ color: 'var(--on-surface)' }}>{title}</h2>
      <p className="text-sm leading-relaxed max-w-2xl" style={{ color: 'var(--on-surface-variant)' }}>{subtitle}</p>
    </div>
  )
}

function Mono({ children }: { children: React.ReactNode }) {
  return <div className="font-mono text-sm text-amber-400 bg-black/40 rounded-lg px-4 py-3 mb-4 leading-relaxed">{children}</div>
}

function Callout({ type, children }: { type: 'warning' | 'info' | 'critical'; children: React.ReactNode }) {
  const s = {
    warning:  { background: 'rgba(245,158,11,0.08)', borderColor: 'rgba(245,158,11,0.35)', color: '#d97706' },
    info:     { background: 'rgba(59,130,246,0.08)', borderColor: 'rgba(59,130,246,0.35)', color: '#2563eb' },
    critical: { background: 'rgba(239,68,68,0.08)',  borderColor: 'rgba(239,68,68,0.35)',  color: '#dc2626' },
  }
  const icons = { warning: '⚠', info: 'ℹ', critical: '!' }
  return (
    <div className="rounded-xl border px-4 py-3 text-sm flex gap-3 mb-4" style={s[type]}>
      <span className="flex-shrink-0 font-bold">{icons[type]}</span>
      <span className="leading-relaxed">{children}</span>
    </div>
  )
}

function InfoCard({ title, children, accent = 'amber' }: { title: string; children: React.ReactNode; accent?: string }) {
  const accentColor: Record<string, string> = {
    amber: 'rgba(245,158,11,0.7)', teal: 'rgba(20,184,166,0.7)',
    blue: 'rgba(59,130,246,0.7)', red: 'rgba(239,68,68,0.7)',
    green: 'rgba(16,185,129,0.7)', purple: 'rgba(168,85,247,0.7)',
  }
  return (
    <div
      className="rounded-r-xl border border-l-2 px-5 py-4 mb-4"
      style={{
        borderColor: 'var(--hairline)',
        borderLeftColor: accentColor[accent] ?? accentColor.amber,
        background: 'var(--surface-container)',
      }}
    >
      <div className="text-[11px] uppercase tracking-widest mb-2" style={{ color: 'var(--on-surface-dim)' }}>{title}</div>
      <div className="text-sm leading-relaxed" style={{ color: 'var(--on-surface-variant)' }}>{children}</div>
    </div>
  )
}

function FormulaCard({ block }: { block: FormulaBlock }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="rounded-xl border overflow-hidden mb-4" style={{ borderColor: 'var(--hairline)', background: 'var(--surface-container)' }}>
      <button
        className="w-full text-left px-5 py-4 flex items-start justify-between gap-4 transition-colors"
        onClick={() => setOpen(v => !v)}
      >
        <div className="flex-1 min-w-0">
          <div className="font-mono text-sm font-semibold mb-1" style={{ color: 'var(--accent-amber)' }}>{block.name}</div>
          <div className="font-mono text-xs rounded px-3 py-1.5 inline-block" style={{ color: 'var(--on-surface-variant)', background: 'var(--surface-container-high, rgba(127,127,127,0.08))' }}>{block.formula}</div>
        </div>
        <span className="text-xs mt-1 flex-shrink-0" style={{ color: 'var(--on-surface-dim)' }}>{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="px-5 pb-5 border-t" style={{ borderColor: 'var(--hairline)' }}>
          <div className="grid grid-cols-1 gap-4 mt-4">
            <div>
              <div className="text-[11px] uppercase tracking-widest mb-2" style={{ color: 'var(--on-surface-dim)' }}>Parameters</div>
              <div className="space-y-1.5">
                {block.params.map(p => (
                  <div key={p.symbol} className="flex gap-3 text-xs">
                    <span className="font-mono min-w-[120px] flex-shrink-0" style={{ color: 'var(--accent-amber)' }}>{p.symbol}</span>
                    <span style={{ color: 'var(--on-surface-variant)' }}>{p.description}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <div className="text-[11px] uppercase tracking-widest mb-2" style={{ color: 'var(--on-surface-dim)' }}>Interpretation</div>
                <p className="text-xs leading-relaxed" style={{ color: 'var(--on-surface-variant)' }}>{block.interpretation}</p>
              </div>
              <div>
                <div className="text-[11px] uppercase tracking-widest mb-2" style={{ color: 'var(--on-surface-dim)' }}>Leverage use-case</div>
                <p className="text-xs leading-relaxed" style={{ color: 'var(--on-surface-variant)' }}>{block.leverageUseCase}</p>
              </div>
            </div>
            {block.thresholds && block.thresholds.length > 0 && (
              <div>
                <div className="text-[11px] uppercase tracking-widest mb-2" style={{ color: 'var(--on-surface-dim)' }}>Key thresholds</div>
                <div className="rounded-lg overflow-hidden border" style={{ borderColor: 'var(--hairline)' }}>
                  <table className="w-full text-xs">
                    <thead>
                      <tr style={{ background: 'var(--surface-container-high, rgba(127,127,127,0.06))' }}>
                        <th className="text-left px-3 py-2 font-medium" style={{ color: 'var(--on-surface-dim)' }}>Value</th>
                        <th className="text-left px-3 py-2 font-medium" style={{ color: 'var(--on-surface-dim)' }}>Meaning</th>
                        <th className="text-left px-3 py-2 font-medium" style={{ color: 'var(--on-surface-dim)' }}>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {block.thresholds.map((t, i) => (
                        <tr key={i} className="border-t" style={{ borderColor: 'var(--hairline)' }}>
                          <td className="px-3 py-2 font-mono" style={{ color: 'var(--accent-amber)' }}>{t.value}</td>
                          <td className="px-3 py-2" style={{ color: 'var(--on-surface-variant)' }}>{t.meaning}</td>
                          <td className="px-3 py-2" style={{ color: 'var(--on-surface)' }}>{t.action}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function SignalRow({ name, type, weight, description }: { name: string; type: string; weight: string; description: string }) {
  return (
    <div className="flex gap-4 items-start py-3 border-b last:border-0" style={{ borderColor: 'var(--hairline)' }}>
      <div className="min-w-[190px]">
        <div className="text-sm font-medium" style={{ color: 'var(--on-surface)' }}>{name}</div>
        <span className="text-[11px] font-mono" style={{ color: 'var(--accent-amber)' }}>{type}</span>
      </div>
      <div className="min-w-[60px]">
        <div className="text-xs font-mono text-teal-400">{weight}</div>
        <div className="text-[11px]" style={{ color: 'var(--on-surface-dim)' }}>weight</div>
      </div>
      <div className="flex-1">
        <p className="text-xs leading-relaxed" style={{ color: 'var(--on-surface-variant)' }}>{description}</p>
      </div>
    </div>
  )
}

// ─── Visual chart primitives ─────────────────────────────────────────────────

function SignalWeightsChart() {
  const signals = [
    { short: 'OFI',  name: 'Order Flow Imbalance',   w: 1.4, color: '#f59e0b' },
    { short: 'LIQ',  name: 'Liquidation Cascade',     w: 1.3, color: '#ef4444' },
    { short: 'FUND', name: 'Funding Arbitrage',        w: 1.2, color: '#6366f1' },
    { short: 'SMF',  name: 'Smart Money Flow',         w: 1.2, color: '#8b5cf6' },
    { short: 'CVD',  name: 'Delta Divergence',         w: 1.1, color: '#14b8a6' },
    { short: 'VWAP', name: 'VWAP Deviation',           w: 1.0, color: '#c6c6c7' },
    { short: 'VOL',  name: 'Volatility Regime',        w: 1.0, color: '#c6c6c7' },
    { short: 'XSP',  name: 'Cross-Exchange Spread',    w: 0.9, color: '#64748b' },
  ]
  return (
    <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-5 py-4 mb-6">
      <div className="text-[10px] uppercase tracking-widest text-white/30 mb-4">Signal weights - relative influence on composite</div>
      <div className="space-y-2">
        {signals.map(s => (
          <div key={s.short} className="flex items-center gap-3">
            <span className="font-mono text-[10px] text-white/40 w-10 text-right flex-shrink-0">{s.short}</span>
            <div className="flex-1 h-3.5 bg-white/[0.04] rounded overflow-hidden">
              <div style={{ width: `${(s.w / 1.4) * 100}%`, height: '100%', background: s.color, opacity: 0.65, borderRadius: 2, transition: 'width 400ms ease' }} />
            </div>
            <span className="font-mono text-xs text-white/55 w-8 flex-shrink-0">×{s.w}</span>
            <span className="text-[10px] text-white/25 hidden sm:block min-w-[140px]">{s.name}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function CompositeScoreBar() {
  return (
    <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-5 py-4 mb-6">
      <div className="text-[10px] uppercase tracking-widest text-white/30 mb-4">Composite score scale - −100 to +100</div>
      <div className="relative mb-3">
        <div className="h-5 rounded-lg overflow-hidden" style={{
          background: 'linear-gradient(to right, rgba(239,68,68,0.75) 0%, rgba(239,68,68,0.25) 20%, rgba(127,127,127,0.12) 40%, rgba(127,127,127,0.12) 60%, rgba(16,185,129,0.25) 80%, rgba(16,185,129,0.75) 100%)',
        }}>
          {[20, 50, 80].map(p => (
            <div key={p} style={{ position: 'absolute', left: `${p}%`, top: 0, bottom: 0, width: 1, background: 'rgba(255,255,255,0.18)' }} />
          ))}
        </div>
        <div className="flex justify-between font-mono text-[10px] mt-1.5 px-0.5">
          <span className="text-red-400/70">−100</span>
          <span className="text-red-400/50">−60</span>
          <span className="text-white/25">0</span>
          <span className="text-emerald-400/50">+60</span>
          <span className="text-emerald-400/70">+100</span>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2 mt-3">
        {[
          { range: '< −60', label: 'STRONG BEAR', desc: 'High-conviction short. Check funding for squeeze risk.', bc: 'border-red-500/30 bg-red-500/5', tc: 'text-red-400' },
          { range: '−60 to +60', label: 'NEUTRAL / NOISE', desc: 'No directional edge. Reduce size or stand aside.', bc: 'border-white/10 bg-white/[0.02]', tc: 'text-white/45' },
          { range: '> +60', label: 'STRONG BULL', desc: 'High-conviction long. Reduce Kelly if funding > 0.1%.', bc: 'border-emerald-500/30 bg-emerald-500/5', tc: 'text-emerald-400' },
        ].map(s => (
          <div key={s.range} className={`rounded-xl border px-3 py-3 ${s.bc}`}>
            <div className={`font-mono text-sm font-semibold mb-0.5 ${s.tc}`}>{s.range}</div>
            <div className={`text-[10px] font-medium mb-1.5 ${s.tc} opacity-70`}>{s.label}</div>
            <p className="text-[11px] text-white/35 leading-relaxed">{s.desc}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

function VenueWeightBars() {
  const venues = [
    { name: 'Binance', w: 0.55, color: '#f0b90b' },
    { name: 'OKX',     w: 0.27, color: '#14b8a6' },
    { name: 'MEXC',    w: 0.14, color: '#6366f1' },
    { name: 'Deribit', w: 0.04, color: '#64748b' },
  ]
  return (
    <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-5 py-4 mb-6">
      <div className="text-[10px] uppercase tracking-widest text-white/30 mb-4">Static venue weights - liquidity share priors</div>
      <div className="space-y-2.5">
        {venues.map(v => (
          <div key={v.name} className="flex items-center gap-3">
            <span className="text-xs text-white/50 w-16 flex-shrink-0">{v.name}</span>
            <div className="flex-1 h-4 bg-white/[0.04] rounded overflow-hidden">
              <div style={{ width: `${v.w * 100}%`, height: '100%', background: v.color, opacity: 0.7, borderRadius: 2 }} />
            </div>
            <span className="font-mono text-xs text-white/55 w-10 text-right flex-shrink-0">{(v.w * 100).toFixed(0)}%</span>
          </div>
        ))}
      </div>
      <p className="text-[11px] text-white/25 mt-3 leading-relaxed">Dynamic per-tick weight = static × degradation_factor. Stale or outlier feeds are downweighted automatically.</p>
    </div>
  )
}

function OIMatrix() {
  const cells = [
    { price: '↑', oi: '↑', interp: 'New longs entering',  action: 'Confirmed uptrend - hold/add longs', bull: true  },
    { price: '↑', oi: '↓', interp: 'Short covering rally', action: 'Weakening - reduce size near resistance', bull: null },
    { price: '↓', oi: '↑', interp: 'New shorts entering',  action: 'Confirmed downtrend - hold/add shorts', bull: false },
    { price: '↓', oi: '↓', interp: 'Long liquidation',     action: 'Weakening selloff - watch for snap-back', bull: null },
  ]
  return (
    <div className="grid grid-cols-2 gap-2 mb-4">
      {cells.map(c => {
        const bc = c.bull === true ? 'border-emerald-500/30 bg-emerald-500/5' : c.bull === false ? 'border-red-500/30 bg-red-500/5' : 'border-white/[0.07] bg-white/[0.02]'
        const tc = c.bull === true ? '#10b981' : c.bull === false ? '#ef4444' : '#c6c6c7'
        return (
          <div key={`${c.price}${c.oi}`} className={`rounded-lg border px-3 py-2.5 ${bc}`}>
            <div className="font-mono text-sm font-bold mb-1" style={{ color: tc }}>Price{c.price} · OI{c.oi}</div>
            <div className="text-xs font-medium text-white/65 mb-0.5">{c.interp}</div>
            <div className="text-[11px] text-white/35">{c.action}</div>
          </div>
        )
      })}
    </div>
  )
}

function LiquidityTierPyramid() {
  const tiers = [
    { tier: 'Platinum', ex: '4/4', kelly: 'Max Kelly',   desc: 'All venues agree', color: '#e2e8f0', widthPct: 52 },
    { tier: 'Golden',   ex: '3/4', kelly: 'Full Kelly',  desc: 'Strong confluence', color: '#f0b90b', widthPct: 66 },
    { tier: 'Silver',   ex: '2/4', kelly: 'Half Kelly',  desc: 'Moderate',          color: '#94a3b8', widthPct: 80 },
    { tier: 'Bronze',   ex: '1/4', kelly: 'Target only', desc: 'Single-venue',      color: '#78716c', widthPct: 100 },
  ]
  return (
    <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-5 py-4 mb-6">
      <div className="text-[10px] uppercase tracking-widest text-white/30 mb-4">Tier pyramid - confluence strength</div>
      <div className="flex flex-col items-center gap-1.5">
        {tiers.map(t => (
          <div
            key={t.tier}
            className="flex items-center justify-between rounded px-4 py-2 border"
            style={{
              width: `${t.widthPct}%`,
              borderColor: `${t.color}33`,
              background: `${t.color}08`,
            }}
          >
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold" style={{ color: t.color }}>{t.tier}</span>
              <span className="text-[10px] font-mono text-white/30">{t.ex} exchanges</span>
            </div>
            <div className="text-right">
              <div className="text-[10px] font-mono text-white/45">{t.kelly}</div>
              <div className="text-[10px] text-white/25">{t.desc}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function DataSourceFrequencyChart() {
  const feeds = [
    { name: 'WS Depth',    freqS: 0.1,  label: '100ms', color: '#10b981' },
    { name: 'Mark Price',  freqS: 1,    label: '1s',    color: '#10b981' },
    { name: 'Trade Ingest',freqS: 2,    label: '2s',    color: '#14b8a6' },
    { name: 'Tape Speed',  freqS: 2,    label: '2s',    color: '#14b8a6' },
    { name: 'Liq. Agg.',   freqS: 5,    label: '5s',    color: '#0ea5e9' },
    { name: 'Feed Health', freqS: 5,    label: '5s',    color: '#0ea5e9' },
    { name: 'Fear & Greed',freqS: 60,   label: '60s',   color: '#f59e0b' },
    { name: 'Zone Check',  freqS: 60,   label: '60s',   color: '#f59e0b' },
    { name: 'FinBERT',     freqS: 90,   label: '90s',   color: '#f97316' },
    { name: 'News Feed',   freqS: 90,   label: '90s',   color: '#f97316' },
    { name: 'Klines 15m',  freqS: 900,  label: '15m',   color: '#ef4444' },
  ]
  const maxLog = Math.log10(900)
  return (
    <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-5 py-4 mb-6">
      <div className="flex items-center justify-between mb-4">
        <div className="text-[10px] uppercase tracking-widest text-white/30">Update cadences - log scale</div>
        <div className="flex gap-3 text-[10px]">
          <span className="flex items-center gap-1"><span style={{ width: 6, height: 6, borderRadius: 1, background: '#10b981', display: 'inline-block' }} />fast</span>
          <span className="flex items-center gap-1"><span style={{ width: 6, height: 6, borderRadius: 1, background: '#f59e0b', display: 'inline-block' }} />medium</span>
          <span className="flex items-center gap-1"><span style={{ width: 6, height: 6, borderRadius: 1, background: '#ef4444', display: 'inline-block' }} />slow</span>
        </div>
      </div>
      <div className="space-y-1.5">
        {feeds.map(f => {
          const pct = (Math.log10(Math.max(f.freqS, 0.1)) / maxLog) * 100
          return (
            <div key={f.name} className="flex items-center gap-3">
              <span className="text-[10px] text-white/40 w-20 text-right flex-shrink-0">{f.name}</span>
              <div className="flex-1 h-3 bg-white/[0.04] rounded overflow-hidden">
                <div style={{ width: `${Math.max(pct, 3)}%`, height: '100%', background: f.color, opacity: 0.65, borderRadius: 2 }} />
              </div>
              <span className="font-mono text-[10px] text-white/50 w-10 flex-shrink-0">{f.label}</span>
            </div>
          )
        })}
      </div>
      <div className="flex justify-between text-[10px] text-white/20 mt-2">
        <span>← real-time</span>
        <span>polling →</span>
      </div>
    </div>
  )
}

function ThTable({ headers, rows }: { headers: string[]; rows: (string | React.ReactNode)[][] }) {
  return (
    <div className="rounded-xl border overflow-hidden mb-6" style={{ borderColor: 'var(--hairline)' }}>
      <table className="w-full text-xs">
        <thead>
          <tr style={{ background: 'var(--surface-container)' }}>
            {headers.map((h, i) => <th key={i} className="text-left px-4 py-2.5 font-medium" style={{ color: 'var(--on-surface-dim)' }}>{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-t" style={{ borderColor: 'var(--hairline)' }}>
              {row.map((cell, j) => (
                <td key={j} className="px-4 py-2.5" style={{ color: 'var(--on-surface-variant)' }}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ─── OVERVIEW ─────────────────────────────────────────────────────────────────

function OverviewSection() {
  return (
    <div>
      <SectionHeader
        tag="nexus v0.3 · obsidian terminal"
        title="System overview"
        subtitle="Nexus is a seven-layer institutional-grade crypto derivatives terminal. Every data point flows through a defined pipeline from raw exchange feeds to position sizing output. This page documents every algorithm, formula, signal, and threshold used across all layers."
      />
      <div className="grid grid-cols-3 gap-3 mb-8">
        {[
          { label: 'Active exchanges', value: '3',       sub: 'Binance · OKX · MEXC' },
          { label: 'Alpha signals',    value: '11',      sub: 'Regime-conditional composite' },
          { label: 'Risk models',      value: '3',       sub: 'VaR ensemble · Kelly · Circuit-breaker' },
          { label: 'Fusion engine',    value: 'merged',  sub: 'Weighted mid + consolidated book' },
          { label: 'AI model',         value: 'Gemma 4', sub: 'Local · Ollama :11434' },
          { label: 'Update frequency', value: '2s',      sub: 'WebSocket + REST fallback' },
        ].map(m => (
          <div key={m.label} className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-4">
            <div className="text-[10px] uppercase tracking-widest text-white/30 mb-1">{m.label}</div>
            <div className="text-xl font-semibold text-white/85">{m.value}</div>
            <div className="text-[11px] text-white/35 mt-0.5">{m.sub}</div>
          </div>
        ))}
      </div>
      <div className="mb-6">
        <div className="text-[10px] uppercase tracking-widest text-white/30 mb-4">Seven-layer data pipeline</div>
        <div className="space-y-2">
          {[
            { n: 'L0', label: 'Data ingestion',      desc: 'WebSocket streams from Binance, OKX, MEXC + REST fallbacks (gap-tracked)',         color: 'text-white/40' },
            { n: 'L1', label: 'Fusion engine',       desc: 'Consolidated book · Weighted mid · Feed validator · Cross-venue MAD outlier',     color: 'text-cyan-400/70' },
            { n: 'L2', label: 'Market structure',    desc: 'OI · Funding (term structure) · CVD · OBI (notional) · VPIN · Squeeze risk',      color: 'text-blue-400/70' },
            { n: 'L3', label: 'Technical indicators',desc: 'RSI · EMA · BB · MACD · Stoch · ATR · ADX · VWAP · OBV · Ichimoku · Pivots',      color: 'text-purple-400/70' },
            { n: 'L4', label: 'Alpha engine',        desc: '11 signals × 5 regimes → regime-conditional composite −100…+100',                  color: 'text-amber-400/70' },
            { n: 'L5', label: 'Risk engine',         desc: 'VaR ensemble (3 methods) · Vol+Corr Kelly · Circuit breaker (event-wired)',        color: 'text-orange-400/70' },
            { n: 'L6', label: 'Event bus',           desc: 'Async pub/sub · var.breach · ws.gap · funding.zscore · vpin.update · drop-oldest', color: 'text-pink-400/70' },
            { n: 'L7', label: 'Macro + AI',          desc: 'FRED gate · Deribit IV · Gemma 4 brief · FinBERT sentiment · News',                color: 'text-green-400/70' },
          ].map(layer => (
            <div key={layer.n} className="flex gap-4 items-center rounded-lg border border-white/[0.05] bg-white/[0.02] px-4 py-3">
              <span className="font-mono text-[10px] text-white/25 min-w-[24px]">{layer.n}</span>
              <div className="w-px h-6 bg-white/[0.08]" />
              <span className={`font-medium text-sm min-w-[190px] ${layer.color}`}>{layer.label}</span>
              <span className="text-xs text-white/35">{layer.desc}</span>
            </div>
          ))}
        </div>
      </div>
      <Callout type="info">All indicators are computed server-side from Binance USDT-M klines. The wire payload to the frontend is pre-computed JSON - the chart canvas does zero indicator math. This keeps the UI GPU-light and ensures every page sees identical values.</Callout>
      <div className="grid grid-cols-2 gap-4 mt-6">
        <InfoCard title="Hardware envelope" accent="teal">
          RTX 4050 (6 GB VRAM) · 16 GB RAM · Windows. Gemma 4 (e4b) runs via Ollama at port 11434. Fallback chain: gemma2:2b → qwen2.5:1.5b → llama3.2:1b → phi3:mini if RAM is constrained.
        </InfoCard>
        <InfoCard title="Latency characteristics" accent="blue">
          WebSocket depth arrives at 100ms cadence. Mark price at 1s. Klines at 15m. Trade ingest loop runs every 2s. Zone check loop runs every 60s. Liquidation aggregation every 5s.
        </InfoCard>
      </div>
    </div>
  )
}

// ─── FUSION ENGINE ────────────────────────────────────────────────────────────

function FusionEngineSection() {
  return (
    <div>
      <SectionHeader
        tag="layer 1 · multi-exchange fusion"
        title="Fusion engine - consolidated book + weighted mid"
        subtitle="Phase A delivery. Three live venues (Binance, OKX, MEXC) feed a single bin-aligned consolidated order book. The weighted-mid reference price is renormalised per tick from per-venue degradation factors so a stale/outlier feed is downweighted within seconds without manual intervention."
      />
      <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-5 py-4 mb-6">
        <div className="text-[10px] uppercase tracking-widest text-white/30 mb-3">Static venue weights</div>
        <Mono>EXCHANGE_WEIGHTS = {'{'} binance: 0.55, okx: 0.27, mexc: 0.14, deribit: 0.04 {'}'}</Mono>
        <p className="text-xs text-white/40 leading-relaxed">
          Static priors reflect 2026 USDT-M futures liquidity share. Bybit and Gate were retired (no live feeds in this build); Deribit remains for options-only context. Per-tick dynamic weights = static × degradation_factor.
        </p>
      </div>
      <VenueWeightBars />
      <div className="rounded-xl border border-white/[0.07] overflow-hidden mb-6">
        <div className="px-5 py-3 bg-white/[0.03] border-b border-white/[0.05]">
          <div className="text-[10px] uppercase tracking-widest text-white/30">Modules</div>
        </div>
        <div className="px-5 py-4 space-y-4 text-xs text-white/55 leading-relaxed">
          <div>
            <div className="font-mono text-white/75 mb-1">backend/ingestion/consolidated_book.py</div>
            merge_books(symbol, depth=20) - bin top-N depth across venues by BIN_SIZE_USD; per-bin {'{'}price, size, weighted_size, sources: {'{'}venue: size{'}'}{'}'}. Source attribution survives the merge so any caller can audit which venue contributes which level.
          </div>
          <div>
            <div className="font-mono text-white/75 mb-1">backend/ingestion/weighted_mid.py</div>
            compute_weighted_mid(symbol) - w_i = w_static × volume_factor × spread_tightness × latency_health, renormalised per tick. Latency input is read-only consumer of WSManager.gap_report().
          </div>
          <div>
            <div className="font-mono text-white/75 mb-1">backend/ingestion/feed_validator.py</div>
            evaluate_feeds(symbol) - per-venue z-score of mid vs cross-venue median (MAD-scaled, 50bps floor to avoid spurious-σ when venues quote to the cent). Staleness ramp 5-30s, spread bps factor (cap at 50bps), volume factor by recent trade count. Multiplicative degradation_factor ∈ [0,1]; near-zero kills the feed for fusion until it recovers.
          </div>
        </div>
      </div>
      <Callout type="info">All modules are read-only over per-venue data stores. The SSL permissive fallback in ws_manager.py (PLDT/corporate firewalls) is preserved end-to-end - no fusion module touches connection logic.</Callout>
      <div className="grid grid-cols-2 gap-4 mt-4">
        <InfoCard title="API surface" accent="teal">
          GET /api/midprice/{'{symbol}'} · GET /api/book/merged/{'{symbol}'}?depth=20 · GET /api/feed/health (per-venue degradation, gap age, dynamic weight)
        </InfoCard>
        <InfoCard title="Failure mode" accent="coral">
          Stop a venue → /api/feed/health flags it red within 5s; weighted_mid renormalises to remaining venues; consolidated book drops the venue from `sources`. No SPOF - the trade-ingest fallback chain is Binance → OKX → MEXC.
        </InfoCard>
      </div>
    </div>
  )
}

// ─── ALPHA ENGINE ─────────────────────────────────────────────────────────────

function AlphaEngineSection() {
  return (
    <div>
      <SectionHeader
        tag="layer 3 · alpha engine"
        title="Alpha engine - 8 signals"
        subtitle="Aggregates eight independent signals into a composite score from −100 to +100. Each signal has direction, magnitude, and confidence. The composite is the agreement-weighted blend; agreement_ratio reports what fraction of the eight concur."
      />
      <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-5 py-4 mb-6">
        <div className="text-[10px] uppercase tracking-widest text-white/30 mb-3">Composite score formula</div>
        <Mono>composite = Σ (signal_i × weight_i × confidence_i) / Σ weight_i</Mono>
        <div className="grid grid-cols-3 gap-4 text-xs text-white/45 mt-2">
          <div><span className="text-amber-400/70 font-mono">signal_i</span> - direction × magnitude</div>
          <div><span className="text-amber-400/70 font-mono">weight_i</span> - signal class weight</div>
          <div><span className="text-amber-400/70 font-mono">confidence_i</span> - 0-1 data quality multiplier</div>
        </div>
      </div>
      <SignalWeightsChart />
      <div className="rounded-xl border border-white/[0.07] overflow-hidden mb-6">
        <div className="px-5 py-3 bg-white/[0.03] border-b border-white/[0.05]">
          <div className="text-[10px] uppercase tracking-widest text-white/30">Eight signals - definitions and weights</div>
        </div>
        <div className="px-5">
          <SignalRow name="Order Flow Imbalance (OFI)" type="MICROSTRUCTURE" weight="×1.4"
            description="(aggressive_buys − aggressive_sells) / total_aggressor_volume over last N trades. A positive OFI spike = institutional buy-side pressure; negative = distribution. Most predictive over 5-15 min windows. The highest-weight signal because it directly measures who is paying the spread - the only genuinely informed participants." />
          <SignalRow name="VWAP Deviation" type="PRICE / VWAP" weight="×1.0"
            description="(price − VWAP) / ATR_14. Values beyond ±1.5 ATR from VWAP indicate overextension. In trending markets price can stay above VWAP for extended periods - use ADX regime filter. Below VWAP in uptrend = buy-the-dip signal; above VWAP in downtrend = sell-the-rip." />
          <SignalRow name="Funding Arbitrage" type="CARRY / DERIVATIVES" weight="×1.2"
            description="Composite of Binance + OKX 8-hourly funding rates. weighted_funding_rate > 0.08%/8h = longs paying heavily → contrarian short signal. < −0.05%/8h = short squeeze setup. Funding term structure (1h/8h/realized 7d annualized) feeds the on_funding_zscore circuit-breaker event. Extreme funding is one of the best mean-reversion setups in crypto." />
          <SignalRow name="Cross-Exchange Spread" type="ARBITRAGE" weight="×0.9"
            description="(binance_mark − competitor_mark) / binance_mark × 10000 bps. Spreads > ±15 bps signal either a liquidity event or informed directional flow on one venue. Sustained positive spread = Binance premium (more aggressive buying on Binance). Used as a leading directional indicator." />
          <SignalRow name="Liquidation Cascade" type="STRUCTURAL" weight="×1.3"
            description="Proximity score to liquidation heatmap clusters. score = cluster_size_usd / distance_to_cluster_pct². Large scores near current price = high cascade probability on a directional move. Cascade events are the single most violent source of alpha in crypto - identifying proximity gives a volatility edge." />
          <SignalRow name="Delta Divergence" type="FLOW" weight="×1.1"
            description="CVD divergence from price. divergence = price_trend_slope / cvd_trend_slope. Values < 0.3 = hidden selling (price rising but CVD flat/declining - distribution). Values > 3.0 = hidden buying. CVD divergence leads price reversal by 2-8 candles on average." />
          <SignalRow name="Smart Money Flow" type="POSITIONING" weight="×1.2"
            description="Top-trader L/S ratio deltas + whale print detection (threshold $50k/trade). score = (top_trader_ls_delta × 0.6) + (whale_net_flow_normalised × 0.4). Top-trader L/S is the smart-money proxy; retail L/S is the contrarian signal. Whale flow = the most direct institutional signal available on public data." />
          <SignalRow name="Volatility Regime" type="META-SIGNAL" weight="×1.0"
            description="ATR/BB-width classifier that switches the engine between trend-following and mean-reversion mode. ADX > 25 + BB width expanding → trend regime (momentum signals weighted higher). ADX < 20 + BB width compressing → chop regime (oscillator signals weighted higher). The regime switch is the engine's most important environmental adaptation." />
        </div>
      </div>
      <CompositeScoreBar />
      <Callout type="warning">A high composite score with agreement_ratio &lt; 0.5 (fewer than 4 of 8 signals agree) is noise, not signal. Always check agreement_ratio before acting on the composite. High score + low agreement usually means one signal is spiking anomalously due to data lag or thin liquidity.</Callout>
    </div>
  )
}

// ─── TECHNICAL INDICATORS ────────────────────────────────────────────────────

function TechnicalIndicatorsSection() {
  const formulas: FormulaBlock[] = [
    {
      name: 'RSI 14 (Wilder)',
      formula: 'RSI = 100 − (100 / (1 + RS))   RS = AvgGain(14) / AvgLoss(14)   Wilder smoothing: α = 1/14',
      params: [
        { symbol: 'AvgGain(n)', description: 'Wilder-smoothed average of up-closes over n periods - NOT simple mean' },
        { symbol: 'AvgLoss(n)', description: 'Wilder-smoothed average of down-closes (absolute value)' },
        { symbol: 'RS',         description: 'Relative Strength = ratio of average gain to average loss' },
        { symbol: 'n = 14',     description: 'Standard Wilder period - matches TradingView / Binance exactly' },
      ],
      interpretation: 'Momentum oscillator 0-100. In trending markets RSI pins above 50 (uptrend) or below 50 (downtrend). The 50-level is the bull/bear pivot, not 30/70. Divergence (price higher, RSI lower) is a counter-trend warning that precedes reversals by 2-10 candles.',
      leverageUseCase: 'Use RSI as a trend filter: RSI > 50 = favour longs; RSI < 50 = favour shorts. For reversals, require RSI divergence + structural confirmation (zone breach, funding extreme). Never fade RSI > 70 in a strong trend - wait for it to break back below 70 before entering a short.',
      thresholds: [
        { value: '> 70',  meaning: 'Overbought in ranging markets',  action: 'Short only if ADX < 20. In trend, hold longs.' },
        { value: '50-70', meaning: 'Bullish momentum zone',           action: 'Hold or add longs. RSI pins here in uptrend.' },
        { value: '30-50', meaning: 'Bearish momentum zone',           action: 'Hold or add shorts. RSI pins here in downtrend.' },
        { value: '< 30',  meaning: 'Oversold in ranging markets',     action: 'Long only if ADX < 20. In trend, hold shorts.' },
      ],
    },
    {
      name: 'EMA 50 / EMA 200 - Regime',
      formula: 'EMA(t) = Price(t) × k + EMA(t−1) × (1−k)   k = 2/(n+1)   Seeded: EMA(0) = SMA(n)',
      params: [
        { symbol: 'k (EMA50)',  description: '2/51 = 0.0385 - smoothing factor for 50-period EMA' },
        { symbol: 'k (EMA200)', description: '2/201 = 0.00995 - smoothing factor for 200-period EMA' },
        { symbol: 'EMA(t−1)',   description: 'Previous EMA - seeded from SMA on first n candles to avoid single-price distortion' },
        { symbol: 'Spread',     description: 'EMA50 − EMA200. Positive = golden cross regime; negative = death cross.' },
      ],
      interpretation: 'Defines the macro trend regime. EMA50 > EMA200 = golden cross (bullish). EMA50 < EMA200 = death cross (bearish). The spread magnitude tells you how extended the trend is - large positive spread = trend is mature. The cross transition itself is the highest-value entry, not an exit.',
      leverageUseCase: 'Hard regime filter. In a death cross, reduce all long Kelly fractions by 30%. In a golden cross, reduce all short Kelly fractions by 30%. Never fight a strong EMA regime with full leverage - the carry cost kills you before the reversal. The spread / ATR ratio normalises the signal across different-volatility assets.',
      thresholds: [
        { value: 'EMA50 > EMA200', meaning: 'Bullish regime (golden cross)',  action: 'Bias longs. Short setups require strong confluence.' },
        { value: 'EMA50 < EMA200', meaning: 'Bearish regime (death cross)',   action: 'Bias shorts. Long setups require strong confluence.' },
        { value: 'Spread > 2%',    meaning: 'Extended trend',                 action: 'Trend is mature - tighten stops, reduce new entries.' },
        { value: 'Cross transition',meaning: 'Regime flip',                   action: 'Highest-value signal - enter in the direction of the new cross.' },
      ],
    },
    {
      name: 'Bollinger Bands (20, 2σ) - Squeeze + Breakout',
      formula: 'Upper = SMA(20) + 2σ(20)   Lower = SMA(20) − 2σ(20)   Width% = (Upper − Lower) / Middle × 100',
      params: [
        { symbol: 'SMA(20)',     description: '20-period simple moving average - the middle band' },
        { symbol: 'σ(20)',       description: 'Population standard deviation of closes over 20 periods' },
        { symbol: 'bb_width_pct',description: 'Band width as % of middle - the squeeze detector. Floor near 0 = volatility compression.' },
      ],
      interpretation: 'Volatility envelope. Price hugging the upper band in an uptrend = strength, not reversal. Band width compression (squeeze) precedes explosive directional moves. The direction of the breakout from a squeeze is the trade. Bollinger bands are a volatility + mean-reversion tool, not a standalone entry trigger.',
      leverageUseCase: 'Monitor bb_width_pct for squeeze setups. When bb_width_pct drops to a 3-month low, increase monitoring frequency. Squeeze breakout + OFI confirmation is one of the highest-probability leveraged entry setups. ATR stop at 1.5× outside the opposite band.',
      thresholds: [
        { value: 'bb_width_pct < 1%', meaning: 'Extreme squeeze',         action: 'Pre-position for breakout. Direction from OFI + funding.' },
        { value: 'Price > Upper',     meaning: 'Overbought / trend ext.',  action: 'ADX > 25: hold longs. ADX < 20: fade cautiously.' },
        { value: 'Price < Lower',     meaning: 'Oversold / trend ext.',    action: 'ADX > 25: hold shorts. ADX < 20: buy dip cautiously.' },
      ],
    },
    {
      name: 'MACD (12, 26, 9) - Momentum',
      formula: 'MACD = EMA(12) − EMA(26)   Signal = EMA(9) of MACD   Histogram = MACD − Signal',
      params: [
        { symbol: 'EMA(12)',    description: 'Fast EMA - responds quickly to recent price changes' },
        { symbol: 'EMA(26)',    description: 'Slow EMA - provides the trend baseline' },
        { symbol: 'Signal',     description: '9-period EMA of the MACD line - the trigger' },
        { symbol: 'Histogram',  description: 'MACD − Signal. Peaks/troughs before line crossovers. The early warning.' },
      ],
      interpretation: 'Trend-following momentum. MACD crossing Signal triggers bias flips. The histogram peaks before line crossovers - histogram divergence from price is a leading reversal indicator 2-5 candles ahead. Zero-line crossovers confirm medium-term trend changes.',
      leverageUseCase: 'Histogram divergence is the most predictive MACD output for leverage entries. A positive histogram turning negative while price is still rising warns of momentum exhaustion. Use as a filter, not a standalone entry - combine with RSI and OFI for high-quality setups.',
      thresholds: [
        { value: 'MACD > Signal',     meaning: 'Bullish crossover',       action: 'Add to longs or initiate if other signals agree.' },
        { value: 'MACD < Signal',     meaning: 'Bearish crossover',       action: 'Add to shorts or initiate if other signals agree.' },
        { value: 'Histogram peak/trough', meaning: 'Momentum exhaustion', action: 'Reduce size, tighten stops on existing trades.' },
        { value: 'MACD > 0',          meaning: 'Above zero line',         action: 'Bullish medium-term trend context.' },
      ],
    },
    {
      name: 'Stochastic (14, 3, 3)',
      formula: '%K = (Close − LL14) / (HH14 − LL14) × 100   %D = SMA(3) of %K',
      params: [
        { symbol: '%K',  description: 'Raw stochastic - position of close within 14-period H/L range (0-100)' },
        { symbol: '%D',  description: '3-period SMA of %K - the signal line for crossover detection' },
        { symbol: 'LL14',description: 'Lowest low of last 14 periods' },
        { symbol: 'HH14',description: 'Highest high of last 14 periods' },
      ],
      interpretation: 'Like RSI but based on price position within its range rather than momentum. More sensitive to short-term reversals. Most useful in ranging markets (ADX < 20). In trending markets, Stoch stays pinned in overbought/oversold for extended periods - do NOT fade it.',
      leverageUseCase: 'Best used for timing entries after confluence is confirmed. Wait for %K to cross %D in the oversold zone (< 20) for long entries, or in overbought (> 80) for shorts. Only trigger in ADX < 20 environments - otherwise use as a timing filter only.',
      thresholds: [
        { value: '%K > 80 and %D > 80', meaning: 'Overbought',        action: 'Short signal in ranging market (ADX < 20 only).' },
        { value: '%K < 20 and %D < 20', meaning: 'Oversold',          action: 'Long signal in ranging market (ADX < 20 only).' },
        { value: '%K crosses above %D', meaning: 'Bullish crossover', action: 'Bullish momentum building - combine with MACD.' },
        { value: '%K crosses below %D', meaning: 'Bearish crossover', action: 'Bearish momentum building - combine with MACD.' },
      ],
    },
    {
      name: 'ATR 14 (Wilder) - Volatility',
      formula: 'TR = max(H−L, |H−Prev_C|, |L−Prev_C|)   ATR(n) = Wilder_smooth(TR, 14)',
      params: [
        { symbol: 'TR',       description: 'True Range - captures overnight/weekend gaps that H−L misses' },
        { symbol: 'H, L, C',  description: 'High, Low, Close of current candle' },
        { symbol: 'Prev_C',   description: 'Previous candle close - gap component' },
        { symbol: 'α = 1/14', description: 'Wilder smoothing: same as EMA with α=1/n - NOT standard EMA' },
      ],
      interpretation: 'The definitive volatility measure for position sizing. ATR tells you "how much does this asset typically move per candle?" Nexus ATR matches TradingView and Binance exactly because it uses Wilder smoothing (α=1/14) not standard EMA. Use ATR for stop distances, not fixed percentages.',
      leverageUseCase: 'Stop distance = 1.5 × ATR from entry. Position size = (account × risk_pct) / (1.5 × ATR). This keeps risk constant across different volatility regimes. When ATR is high (volatile market), you get fewer units. When ATR is low, more. Never use fixed pip/% stops - they ignore current volatility.',
      thresholds: [
        { value: 'ATR expanding', meaning: 'Volatility increasing',  action: 'Widen stops proportionally. Reduce position size.' },
        { value: 'ATR contracting',meaning: 'Volatility compressing',action: 'Squeeze alert. Pre-position for directional breakout.' },
        { value: '1.5× ATR stop', meaning: 'Nexus standard stop',    action: 'Default stop multiplier for all leveraged positions.' },
      ],
    },
    {
      name: 'ADX 14 (Wilder) - Trend Strength',
      formula: '+DI = 100×Wilder(+DM,14)/ATR   −DI = 100×Wilder(−DM,14)/ATR   DX = 100×|+DI−−DI|/(+DI+−DI)   ADX = Wilder(DX,14)',
      params: [
        { symbol: '+DM',   description: 'Positive Directional Movement: current high minus previous high (if positive, else 0)' },
        { symbol: '−DM',   description: 'Negative Directional Movement: previous low minus current low (if positive, else 0)' },
        { symbol: '+DI/−DI',description: 'Directional Indicators - +DI > −DI = uptrend. Crossover = trend reversal signal.' },
        { symbol: 'DX',    description: 'Directional Index - intermediate step before final ADX smoothing' },
        { symbol: 'ADX',   description: 'Average of DX - measures trend strength regardless of direction (0-100)' },
      ],
      interpretation: 'ADX measures trend STRENGTH, not direction. 0-20 = no trend (chop), 20-25 = forming trend, 25-50 = strong trend, > 50 = extreme trend (rare). The +DI/−DI crossover is the actual directional signal. ADX does NOT tell you if price is going up or down.',
      leverageUseCase: 'The most important regime filter in the system. ADX < 20: use oscillators (RSI, Stoch), avoid trend strategies. ADX > 25: use trend strategies (EMA cross, MACD), avoid counter-trend fades. ADX > 40: trend is fully extended, stops must be wide - reduce leverage.',
      thresholds: [
        { value: 'ADX < 20',  meaning: 'No trend (ranging)',       action: 'Use oscillators. Avoid trend-following strategies.' },
        { value: 'ADX 20-25', meaning: 'Trend developing',         action: 'Transition zone - monitor for confirmation.' },
        { value: 'ADX 25-40', meaning: 'Strong trend',             action: 'Full trend-following mode. Momentum signals valid.' },
        { value: 'ADX > 40',  meaning: 'Extreme/mature trend',     action: 'Trend extended - tighten stops, reduce new entries.' },
      ],
    },
    {
      name: 'VWAP - Volume-Weighted Average Price',
      formula: 'VWAP(i) = Σ(Typical_Price × Volume)[0..i] / Σ Volume[0..i]   TP = (H+L+C)/3',
      params: [
        { symbol: 'TP',       description: 'Typical price: (High + Low + Close) / 3' },
        { symbol: 'Cumulative',description: 'Nexus uses window-cumulative VWAP (not session-anchored) over the fetched candle range' },
        { symbol: 'VWAP_deviation',description: '(Price − VWAP) / ATR - normalised distance from fair value' },
      ],
      interpretation: 'The institutional fair-value benchmark. Institutional algorithms use VWAP as the execution benchmark - price significantly above VWAP is expensive; below is cheap. In trending markets, price can stay above VWAP for the entire trend. In ranging markets, VWAP is the mean-reversion anchor.',
      leverageUseCase: 'Long entries below VWAP in confirmed uptrends (catching the dip to fair value). Short entries above VWAP in confirmed downtrends. VWAP deviation > ±1.5 ATR = mean-reversion setup in ranging markets. Never use VWAP in isolation - confirm with ADX regime.',
      thresholds: [
        { value: 'Price > VWAP',       meaning: 'Above fair value',      action: 'Longs at premium. Better entries below VWAP in uptrend.' },
        { value: 'Price < VWAP',       meaning: 'Below fair value',      action: 'Shorts at discount. Better entries above VWAP in downtrend.' },
        { value: 'Dev > +1.5 ATR',     meaning: 'Overbought vs VWAP',    action: 'Mean-reversion short setup (ranging only).' },
        { value: 'Dev < −1.5 ATR',     meaning: 'Oversold vs VWAP',      action: 'Mean-reversion long setup (ranging only).' },
      ],
    },
    {
      name: 'OBV - On-Balance Volume',
      formula: 'OBV(i) = OBV(i−1) + Volume if Close > Prev_Close, else OBV(i−1) − Volume',
      params: [
        { symbol: 'OBV',   description: 'Cumulative signed volume - adds volume on up days, subtracts on down days' },
        { symbol: 'Volume',description: 'Total traded volume for the candle' },
        { symbol: 'Divergence',description: 'OBV trend vs price trend - the predictive output' },
      ],
      interpretation: 'Detects volume pressure behind price moves. Rising OBV + rising price = volume confirms trend. Rising OBV + falling price = hidden buying (accumulation). Falling OBV + rising price = hidden selling (distribution). OBV divergence is a leading indicator for reversals.',
      leverageUseCase: 'OBV divergence setups: if price makes new highs but OBV does not, distribution is occurring - reduce longs. If price makes new lows but OBV does not, accumulation is occurring - reduce shorts. Combine with CVD for confirmation of volume pressure signals.',
      thresholds: [
        { value: 'OBV rising + price rising',  meaning: 'Confirmed uptrend',     action: 'Hold / add longs.' },
        { value: 'OBV rising + price falling', meaning: 'Hidden accumulation',   action: 'Long setup developing - watch for breakout.' },
        { value: 'OBV falling + price rising', meaning: 'Hidden distribution',   action: 'Short setup developing - watch for breakdown.' },
        { value: 'OBV falling + price falling',meaning: 'Confirmed downtrend',   action: 'Hold / add shorts.' },
      ],
    },
    {
      name: 'Ichimoku Cloud (9, 26, 52)',
      formula: 'Tenkan = (HH9+LL9)/2   Kijun = (HH26+LL26)/2   Senkou_A = (Tenkan+Kijun)/2 +26   Senkou_B = (HH52+LL52)/2 +26',
      params: [
        { symbol: 'Tenkan-sen',  description: 'Conversion line (9-period midpoint) - short-term momentum' },
        { symbol: 'Kijun-sen',   description: 'Base line (26-period midpoint) - medium-term momentum and support/resistance' },
        { symbol: 'Senkou A/B',  description: 'Cloud boundaries shifted +26 bars forward - future support/resistance zones' },
        { symbol: 'Chikou',      description: 'Close plotted 26 bars back - shows current price vs past context' },
        { symbol: 'ichimoku_bias',description: 'Nexus output: "bullish" if Senkou A > B (green cloud), "bearish" if A < B' },
      ],
      interpretation: 'All-in-one trend + momentum + support/resistance system. The cloud (Kumo) provides dynamic support/resistance zones. Price above cloud = uptrend; below = downtrend; inside = chop. Tenkan/Kijun cross = medium-term momentum flip. Cloud twist = trend change 26 bars ahead.',
      leverageUseCase: 'The cloud provides natural stop zones. For longs: entry when price breaks above cloud, stop below cloud base. For shorts: entry when price breaks below cloud, stop above cloud top. Cloud thickness = strength of support/resistance. Thin cloud = weak zone. Respect the Kijun as a trailing stop level.',
      thresholds: [
        { value: 'Price above cloud',    meaning: 'Strong uptrend',           action: 'Longs preferred. Cloud base = natural stop.' },
        { value: 'Price below cloud',    meaning: 'Strong downtrend',         action: 'Shorts preferred. Cloud top = natural stop.' },
        { value: 'Price inside cloud',   meaning: 'Consolidation/chop',       action: 'Avoid leveraged entries. Wait for breakout.' },
        { value: 'Senkou A > B (green)', meaning: 'Bullish cloud',            action: 'Trend context is bullish.' },
        { value: 'Senkou A < B (red)',   meaning: 'Bearish cloud',            action: 'Trend context is bearish.' },
      ],
    },
    {
      name: 'Pivot Points - Classic, Camarilla, Woodie',
      formula: 'Classic: P=(H+L+C)/3  R1=2P−L  R2=P+(H−L)  S1=2P−H  S2=P−(H−L)\nCamarilla: H3=C+range×1.1/4  L3=C−range×1.1/4  H4=C+range×1.1/2  L4=C−range×1.1/2',
      params: [
        { symbol: 'P (Pivot)',    description: 'Primary pivot - calculated from prior period H/L/C' },
        { symbol: 'R1, R2, R3',  description: 'Resistance levels above pivot - projected reversal/extension zones' },
        { symbol: 'S1, S2, S3',  description: 'Support levels below pivot - projected reversal/extension zones' },
        { symbol: 'Camarilla H4/L4', description: 'Most-watched intraday breakout levels - break above H4 = strong bull signal' },
        { symbol: 'Prior period', description: 'Nexus uses the PREVIOUS closed candle - using in-progress candle causes jitter' },
      ],
      interpretation: 'Institutional price levels calculated from prior period data. Widely used by floor traders and algorithms as automatic support/resistance. Classic pivots work on all timeframes. Camarilla levels are most useful for intraday scalping - H3/L3 for reversal, H4/L4 for breakout trades.',
      leverageUseCase: 'Pivot levels are natural target and stop zones. Long entries at S1/S2 in uptrends with tight stops below. Short entries at R1/R2 in downtrends. Camarilla H4 break = strong breakout long. L4 break = strong breakout short. Use pivot levels to set R:R targets before entering any leveraged position.',
      thresholds: [
        { value: 'Price at R1/R2',    meaning: 'Resistance zone',           action: 'Short in downtrend, take profit for longs.' },
        { value: 'Price at S1/S2',    meaning: 'Support zone',              action: 'Long in uptrend, take profit for shorts.' },
        { value: 'Break above R2',    meaning: 'Strong bullish breakout',   action: 'Momentum long - target R3.' },
        { value: 'Cam H4 break',      meaning: 'Camarilla breakout bull',   action: 'Strong long signal - high conviction entry.' },
        { value: 'Cam L4 break',      meaning: 'Camarilla breakout bear',   action: 'Strong short signal - high conviction entry.' },
      ],
    },
    {
      name: 'Std Dev Channel (100-period LR)',
      formula: 'LR line = least-squares fit over 100 candles   Upper/Lower = midline ± 2σ(residuals)',
      params: [
        { symbol: 'Least-squares', description: 'Linear regression line through the last 100 closes - the "fair value trend line"' },
        { symbol: 'σ(residuals)',  description: 'Standard deviation of price distances from the regression line' },
        { symbol: '2σ bands',     description: 'Upper/lower channels - ~95% of price action contained within' },
        { symbol: 'Midline',      description: 'The regression line itself - acts as dynamic support/resistance' },
      ],
      interpretation: 'Linear regression channel showing where price "should" be based on recent trend. Upper/lower bands are ±2σ from the trend line. Price outside the channel = statistically unusual - either a breakout or a mean-reversion setup depending on ADX regime. More sophisticated than Bollinger Bands because it adapts to the trend slope.',
      leverageUseCase: 'In trending markets: channel defines the trend corridor. Entries near midline in trend direction with stops outside the opposite channel wall. In ranging markets: fade touches of upper (short) and lower (long) channel walls. Channel slope direction confirms trend bias.',
      thresholds: [
        { value: 'Price above upper', meaning: 'Statistically extended', action: 'Mean-reversion short in low ADX. Trend continuation in high ADX.' },
        { value: 'Price below lower', meaning: 'Statistically extended', action: 'Mean-reversion long in low ADX. Trend continuation in high ADX.' },
        { value: 'Price at midline',  meaning: 'Trend fair value',        action: 'Best entry zone in trending markets.' },
      ],
    },
  ]

  return (
    <div>
      <SectionHeader
        tag="layer 2 · technical indicators"
        title="Technical indicators - 12 algorithms"
        subtitle="All indicators are computed server-side using the same algorithms as TradingView and Binance (Wilder smoothing for RSI/ATR/ADX, SMA-seeded EMA, population stdev for Bollinger). NaN values during warm-up periods are serialised as null - the chart shows a clean gap, never a misleading partial value."
      />
      <Callout type="info">The implementation matches TradingView exactly: Wilder smoothing for RSI/ATR/ADX (α=1/n, NOT 2/(n+1)), SMA seed for EMA first values, population standard deviation for Bollinger Bands. If your Nexus value and TradingView value differ by more than 0.01%, check the interval and candle count - warm-up length affects early values.</Callout>
      <div className="mt-6">
        {formulas.map(f => <FormulaCard key={f.name} block={f} />)}
      </div>
    </div>
  )
}

// ─── MARKET STRUCTURE ────────────────────────────────────────────────────────

function MarketStructureSection() {
  return (
    <div>
      <SectionHeader
        tag="layer 1 · market structure"
        title="Market structure - 4 feeds"
        subtitle="Derivatives-specific signals that are invisible on spot charts. Open Interest, Funding Rate, Long/Short Ratio, and Cumulative Volume Delta together describe who is positioned where and what it costs them to hold. These are the signals that matter most for timing leveraged entries and exits."
      />
      {[
        {
          title: 'Open Interest (OI)', endpoint: '/api/oi/{symbol}',
          formula: 'OI_change_pct = (OI_now − OI_prev) / OI_prev × 100',
          rows: [
            { cond: 'Price ↑ + OI ↑',  interp: 'New longs entering - confirmed uptrend',      action: 'Trend has backing. Hold / add longs with trend.' },
            { cond: 'Price ↑ + OI ↓',  interp: 'Short covering - weakening rally',            action: 'Rally may be short-squeeze only. Reduce size near resistance.' },
            { cond: 'Price ↓ + OI ↑',  interp: 'New shorts entering - confirmed downtrend',   action: 'Trend has backing. Hold / add shorts with trend.' },
            { cond: 'Price ↓ + OI ↓',  interp: 'Long liquidation - weakening selloff',        action: 'Selloff may be liquidation only. Watch for snap-back.' },
            { cond: 'OI spike (>5%/hr)',interp: 'Rapid new positioning',                       action: 'Heightened volatility ahead. Widen stops or stand aside.' },
          ],
        },
        {
          title: 'Funding Rate', endpoint: '/api/funding/{symbol}',
          formula: 'weighted_rate = Σ(exchange_rate × exchange_weight) / Σ weights   [Binance×0.55 + OKX×0.27 + MEXC×0.14 + Deribit×0.04]',
          rows: [
            { cond: 'Rate > +0.1%/8h', interp: 'Extremely crowded longs paying heavily',   action: 'Contrarian short setup. Funding = carry cost on longs.' },
            { cond: 'Rate +0.05-0.1%', interp: 'Moderately bullish - longs paying',        action: 'Monitor. Not extreme enough for pure contrarian fade.' },
            { cond: 'Rate ±0.01%',     interp: 'Neutral / balanced positioning',            action: 'No funding edge. Other signals determine direction.' },
            { cond: 'Rate < −0.05%',   interp: 'Crowded shorts - short squeeze setup',     action: 'High-probability long. Shorts are underwater and paying.' },
            { cond: 'Rate < −0.1%',    interp: 'Extreme short squeeze pressure',           action: 'Aggressive long. Short liquidation cascade imminent.' },
          ],
        },
        {
          title: 'Long/Short Ratio (CVD)', endpoint: '/api/lsratio/{symbol} + /api/cvd/{symbol}',
          formula: 'CVD(t) = CVD(t−1) + (buy_volume − sell_volume)   LS_ratio = long_count / short_count',
          rows: [
            { cond: 'CVD 5m rising',       interp: 'Buy-side aggression dominant',         action: 'Short-term bullish momentum. Add to longs on dips.' },
            { cond: 'CVD 5m falling',       interp: 'Sell-side aggression dominant',       action: 'Short-term bearish momentum. Add to shorts on rallies.' },
            { cond: 'CVD diverges from price',interp: 'Hidden distribution or accumulation',action: 'Leading reversal signal. Reduce or reverse position.' },
            { cond: 'LS ratio > 1.5',       interp: 'Retail heavily long',                 action: 'Contrarian bearish. Retail crowds are usually wrong at extremes.' },
            { cond: 'LS ratio < 0.8',       interp: 'Retail heavily short',                action: 'Contrarian bullish. Short squeeze risk elevated.' },
            { cond: 'Top trader LS > 2.0',  interp: 'Smart money heavily long',            action: 'Bullish confirmation. Follow the smart money.' },
          ],
        },
        {
          title: 'Squeeze Risk Meter', endpoint: 'computed from funding + OI + LS',
          formula: 'squeeze_score = (|funding_extreme| × 0.4) + (oi_change_velocity × 0.35) + (ls_imbalance × 0.25)',
          rows: [
            { cond: 'Score > 70 (CRITICAL)', interp: 'Squeeze imminent',                  action: 'Stand aside or take small counter-trend position.' },
            { cond: 'Score 50-70 (HIGH)',     interp: 'Elevated squeeze probability',      action: 'Reduce existing position in squeeze direction.' },
            { cond: 'Score 30-50 (MODERATE)', interp: 'Moderate risk',                    action: 'Monitor closely. Watch for funding extremes.' },
            { cond: 'Score < 30 (LOW)',        interp: 'Normal market conditions',         action: 'Standard risk parameters apply.' },
          ],
        },
      ].map(feed => (
        <div key={feed.title} className="mb-8">
          <div className="flex items-center gap-3 mb-3">
            <h3 className="text-base font-semibold text-white/80">{feed.title}</h3>
            <span className="font-mono text-[10px] text-white/25 bg-white/[0.04] rounded px-2 py-0.5">{feed.endpoint}</span>
          </div>
          <Mono>{feed.formula}</Mono>
          {feed.title === 'Open Interest (OI)' && <OIMatrix />}
          <ThTable
            headers={['Condition', 'Interpretation', 'Trading action']}
            rows={feed.rows.map(r => [
              <span key="cond" className="font-mono text-[11px] text-white/50">{r.cond}</span>,
              r.interp, r.action
            ])}
          />
        </div>
      ))}
    </div>
  )
}

// ─── RISK ENGINE ─────────────────────────────────────────────────────────────

function RiskEngineSection() {
  return (
    <div>
      <SectionHeader
        tag="layer 5 · risk engine"
        title="Risk engine - VaR ensemble + Vol-adjusted Kelly + Monte Carlo"
        subtitle="Three complementary risk models. VaR ensemble (historical + Student-t parametric + Monte Carlo) produces the Kelly denominator (ensemble_max). Kelly is vol- and correlation-adjusted (half-Kelly default). Monte Carlo simulates equity curves over a 50-trade horizon. The Risk tab (⌥8) renders all four - Kelly · VaR · F&G · Circuit Breaker - in one advisory-only view."
      />
      <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-5 py-4 mb-6">
        <div className="text-[10px] uppercase tracking-widest text-white/30 mb-3">VaR ensemble (backend/risk/var.py)</div>
        <Mono>compute() → {'{historical, parametric_t, monte_carlo, ensemble_max, stressed_var, liquidation_risk}'}</Mono>
        <p className="text-xs text-white/45 leading-relaxed">
          historical() - empirical quantile · parametric_t() - Student-t (df fit from kurtosis) with EWMA σ (λ=0.94) · monte_carlo(n_paths=500, n_steps=50, dist=&apos;student_t&apos;, df=4). ensemble_max is the Kelly denominator. contribution_var(positions, returns_by_symbol) provides Euler-allocated marginal + component VaR for portfolio decomposition.
        </p>
      </div>
      <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-5 py-4 mb-6">
        <div className="text-[10px] uppercase tracking-widest text-white/30 mb-3">Vol- and correlation-adjusted Kelly (backend/risk/kelly.py)</div>
        <Mono>{'b = avg_win / max(atr_pct, realized_vol_24h)   →   f = half_kelly × (1 − max|ρ_ij|)'}</Mono>
        <p className="text-xs text-white/45 leading-relaxed">
          When vol inputs are supplied, the b-ratio is volatility-normalised - a 1% avg_win is more impressive in a low-vol tape than a high-vol one. The final fraction is multiplied by (1 − max|ρ_ij|) vs open positions, so adding a 0.9-correlated symbol shrinks size to 10% of standalone Kelly. Caps: max_position_pct, max_leverage, margin_buffer.
        </p>
      </div>
      <div className="mb-8">
        <h3 className="text-base font-semibold text-white/80 mb-3">Fractional Kelly criterion</h3>
        <Mono>f* = (edge × W − (1−W) / R) × fraction   [Nexus uses fraction = 0.25]</Mono>
        <div className="grid grid-cols-2 gap-3 mb-4">
          {[
            { sym: 'f*',       desc: 'Optimal fraction of capital to risk - Kelly output' },
            { sym: 'W',        desc: 'Win rate: probability of winning trade (0-1)' },
            { sym: 'R',        desc: 'Reward/risk ratio: avg_win / avg_loss' },
            { sym: 'edge',     desc: 'Additional edge factor - set to 1.0 for pure Kelly' },
            { sym: 'fraction', desc: '0.25 - quarter Kelly. Crypto-optimised drawdown reduction.' },
          ].map(p => (
            <div key={p.sym} className="flex gap-3 items-start">
              <span className="font-mono text-amber-400/70 text-xs min-w-[80px] flex-shrink-0">{p.sym}</span>
              <span className="text-xs text-white/45">{p.desc}</span>
            </div>
          ))}
        </div>
        <InfoCard title="Why quarter Kelly for crypto?" accent="amber">
          Full Kelly maximises long-run log growth but produces 30-50% drawdowns even when the edge is real. Crypto adds volatility clustering, liquidation risk, and funding carry that make full Kelly lethal. Quarter Kelly (0.25×) reduces expected growth by ~20% but cuts maximum drawdown by over 60%. This is the standard used by quantitative crypto funds.
        </InfoCard>
        <ThTable
          headers={['Win rate', 'R:R ratio', 'Full Kelly', 'Quarter Kelly (Nexus)', 'Interpretation']}
          rows={[
            ['55%', '1.5×', '16.7%', '4.2%',  'Minimal edge - small size'],
            ['55%', '2.0×', '27.5%', '6.9%',  'Moderate edge - standard size'],
            ['60%', '2.0×', '35.0%', '8.75%', 'Good edge - above average size'],
            ['65%', '2.5×', '47.0%', '11.75%','Strong edge - near max sizing'],
            ['45%', '3.0×', '13.3%', '3.3%',  'Low win rate - size down despite good R:R'],
          ].map(r => r.map((c, i) => i === 3 ? <span key={i} className="font-mono text-amber-400/80">{c}</span> : c))}
        />
      </div>
      <div className="mb-8">
        <h3 className="text-base font-semibold text-white/80 mb-3">Monte Carlo equity simulation</h3>
        <Mono>{'for n in range(500): simulate_path(entry, stop_pct, target_pct, win_rate, kelly_size)'}</Mono>
        <p className="text-sm text-white/45 leading-relaxed mb-4">
          Runs 500 independent equity-curve simulations for any proposed trade. Each path randomly samples win/loss based on your estimated win rate, applies Kelly-sized risk, and accumulates P&amp;L over a 50-trade horizon. Output shows P5 / P50 / P95 percentile equity curves.
        </p>
        <div className="grid grid-cols-3 gap-3 mb-4">
          {[
            { pct: 'P5',  desc: 'Bad luck scenario. If P5 drawdown > max tolerable loss, reduce size until it does not.', color: 'text-red-400' },
            { pct: 'P50', desc: 'Median path - realistic projection. Not optimistic. Size to tolerate this as the expected outcome.', color: 'text-white/60' },
            { pct: 'P95', desc: 'Good luck scenario - tail, not norm. Do not size based on this. It is the exception.', color: 'text-emerald-400' },
          ].map(p => (
            <div key={p.pct} className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-4">
              <div className={`font-mono text-lg font-semibold mb-2 ${p.color}`}>{p.pct}</div>
              <p className="text-xs text-white/40 leading-relaxed">{p.desc}</p>
            </div>
          ))}
        </div>
        <InfoCard title="Liquidation price calculation" accent="coral">
          estimate_liquidation_price(entry, leverage, side, margin_mode). Isolated margin: liq = entry × (1 − 1/leverage + maintenance_margin_rate). Cross margin: liq depends on total account equity. Always verify via Binance directly before entering a leveraged position - Nexus provides an estimate, not a guarantee.
        </InfoCard>
      </div>
      <Callout type="critical">Kelly Size of 0.0% means insufficient data or edge - do not enter. Position Cap is the hard maximum regardless of Kelly output. Always honour both. A Kelly of 8% with a 5% Position Cap means the cap wins - you risk 5%.</Callout>
    </div>
  )
}

// ─── CIRCUIT BREAKER ─────────────────────────────────────────────────────────

function CircuitBreakerSection() {
  return (
    <div>
      <SectionHeader
        tag="layer 5 · circuit breaker · event bus"
        title="Circuit breaker - event-wired risk halt"
        subtitle="Phase C delivery. The threshold-only breaker now consumes a live async event bus. Producers publish to typed topics; the breaker is the sole subscriber and fires escalating actions (alert → halve → halt) on configurable triggers."
      />
      <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-5 py-4 mb-6">
        <div className="text-[10px] uppercase tracking-widest text-white/30 mb-3">Event topics</div>
        <Mono>{`var.breach   correlation.snapshot   ws.gap   funding.zscore   vpin.update`}</Mono>
        <p className="text-xs text-white/40 leading-relaxed">
          Pub/sub is bounded with drop-oldest backpressure - producers (VaR loop, WSManager on_gap, FundingTracker, VPINTracker) NEVER block on a slow subscriber. /api/health surfaces breaker.state() and the last 50 events from the bus.
        </p>
      </div>
      <ThTable
        headers={['Trigger', 'Producer', 'Threshold', 'Action']}
        rows={[
          ['var.breach',           'risk/var.py ensemble_max',                 '> account_var_limit',                        'Halve sizing'],
          ['correlation.snapshot', 'risk/correlation.py periodic',             'Δρ ≥ 0.30 vs prior snapshot',                'Alert + freeze new entries'],
          ['ws.gap',               'ingestion/ws_manager.py on_gap',            'gap ≥ 60s',                                  'Halt new entries until reconnect'],
          ['funding.zscore',       'computation/funding.py rolling 168h',       '|z| ≥ 3.0',                                  'Bias filter - block crowded side'],
          ['vpin.update',          'computation/vpin.py bucket close',          'VPIN ≥ 0.85 (toxic)',                        'Halt - informed-flow regime'],
        ].map(r => [
          <span key="ev" className="text-amber-400/70 font-mono text-[11px]">{r[0]}</span>,
          <span key="src" className="text-white/55 text-[11px]">{r[1]}</span>,
          <span key="trig" className="text-white/55 text-[11px]">{r[2]}</span>,
          <span key="act" className="text-red-400/70 text-[11px]">{r[3]}</span>,
        ])}
      />
      <div className="grid grid-cols-2 gap-4 mt-6">
        <InfoCard title="Producer cadence" accent="amber">
          The _circuit_breaker_loop in main.py runs every 30s, gathering correlation snapshots, ws.gap scans, and funding-zscore samples. VPIN events fire from the live trade-ingest path on bucket close (no cadence - flow-driven).
        </InfoCard>
        <InfoCard title="Inspection" accent="teal">
          GET /api/health includes circuit_breaker (per-trigger state, last fire ts, cooldown remaining), circuit_breaker_events (recent fires), and event_bus_recent (last bus messages by topic).
        </InfoCard>
      </div>
      <Callout type="warning">Read-only invariant preserved. The breaker advises sizing/halt state - it does NOT cancel orders or mutate positions. BloFin paper execution remains the only execution surface and stays in demo mode until Phase 6.</Callout>
    </div>
  )
}

// ─── LIQUIDITY MAP ───────────────────────────────────────────────────────────

function LiquidityMapSection() {
  return (
    <div>
      <SectionHeader
        tag="layer 3 · liquidity"
        title="Liquidity map - institutional zones"
        subtitle="Aggregates order book depth from Binance, OKX, and MEXC into institutional golden zones, liquidation cluster heatmaps, liquidity walls, and void detection. Zones are classified by tier based on multi-exchange confluence (3 venues = Platinum)."
      />
      <div className="mb-6">
        <h3 className="text-base font-semibold text-white/80 mb-3">Zone tier classification</h3>
        <LiquidityTierPyramid />
        <ThTable
          headers={['Tier', 'Exchange count', 'Persistence', 'Meaning', 'Action']}
          rows={[
            ['Platinum', '4/4 exchanges', 'Persistent', 'Maximum institutional confluence - all major venues agree', 'Highest-conviction entry zone. Size at Kelly maximum.'],
            ['Golden',   '3/4 exchanges', 'Persistent', 'Strong institutional interest - 3 of 4 venues show depth',  'High-conviction zone. Standard Kelly sizing.'],
            ['Silver',   '2/4 exchanges', 'Transient',  'Moderate confluence - 2 venues agree',                       'Valid support/resistance but lower conviction. Half Kelly.'],
            ['Bronze',   '1/4 exchanges', 'Transient',  'Single-venue depth cluster',                                  'Weakest tier - use for target levels only, not entries.'],
          ]}
        />
      </div>
      <div className="mb-6">
        <h3 className="text-base font-semibold text-white/80 mb-3">Liquidity features</h3>
        <div className="space-y-4">
          {[
            { title: 'Liquidity walls', desc: 'Large standing limit orders in the order book creating a visible barrier. Detected when cumulative depth at a price level exceeds 3× the average depth across the visible book. Walls act as magnets - price tends to gravitate toward large liquidity to enable institutional execution. A wall above price = resistance. Below = support. But walls can be spoofed - always confirm with print flow.' },
            { title: 'Liquidity voids', desc: 'Price ranges with abnormally thin order book depth - gaps where price can travel rapidly with minimal resistance. Detected when a price range has < 20% of average depth density. When price enters a void, it accelerates. Voids above price = potential rapid upside extension. Voids below = potential flash crash zone. Never place stops inside a void.' },
            { title: 'Liquidation clusters', desc: 'Estimated price levels where large leveraged positions would be liquidated based on open interest distribution. Calculated from current mark price ± (1/leverage) for standard leverage bands (5×, 10×, 20×, etc). Clusters represent concentrated forced-selling or forced-buying if price reaches those levels, creating cascade potential.' },
            { title: 'Depth profile imbalance', desc: 'Bid depth / ask depth ratio across the visible order book. Imbalance > 1.5 = more bid depth (buyers supporting price). Imbalance < 0.67 = more ask depth (sellers overhead). Combined with OFI for the most accurate short-term direction signal. Extreme imbalance (> 3.0 or < 0.33) often precedes a rapid move toward the thinner side.' },
          ].map(f => (
            <div key={f.title} className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-5">
              <div className="text-sm font-semibold text-white/75 mb-2">{f.title}</div>
              <p className="text-xs text-white/45 leading-relaxed">{f.desc}</p>
            </div>
          ))}
        </div>
      </div>
      <Callout type="warning">Order book data from a single exchange can be spoofed. Nexus mitigates this by requiring multi-exchange confirmation for Platinum/Golden tier zones. A wall visible on Binance only (Bronze tier) should be treated with skepticism - it may be a spoof that disappears before execution.</Callout>
    </div>
  )
}

// ─── ORDER FLOW ──────────────────────────────────────────────────────────────

function OrderFlowSection() {
  return (
    <div>
      <SectionHeader
        tag="layer 1 · microstructure"
        title="Order flow - real-time trade analysis"
        subtitle="CVD multi-timeframe, volume profile, absorption detection, tape speed analysis, and large trade classification. These are the highest-frequency signals in the system - updated every 2 seconds from raw aggTrade streams."
      />
      <div className="space-y-6">
        {[
          {
            title: 'Cumulative Volume Delta (CVD)', endpoint: '/api/cvd/{symbol}',
            desc: 'CVD accumulates net buy/sell pressure: +volume for aggressor buys (taker hits ask), −volume for aggressor sells (taker hits bid). Computed across 5 timeframes: 1m, 5m, 15m, 1h, 4h. The divergence between CVD and price is the primary signal - if price is rising but CVD is flat or falling, institutional players are distributing into the retail-driven rally.',
            formula: 'CVD(t) = CVD(t−1) + qty if is_taker_buy, else CVD(t−1) − qty',
          },
          {
            title: 'Order Flow Imbalance (OFI)', endpoint: 'computed in alpha engine',
            desc: 'Measures aggressor pressure at the top of book. The most predictive short-term directional signal because it directly measures who is paying the spread - institutions rarely pay the spread unless they have information. OFI = (aggressive_buys − aggressive_sells) / total_aggressor_volume. Range: −1 (all sellers) to +1 (all buyers). Significant above ±0.3.',
            formula: 'OFI = (Σ buy_qty − Σ sell_qty) / (Σ buy_qty + Σ sell_qty)   over last N aggTrades',
          },
          {
            title: 'Absorption detection', endpoint: '/api/orderflow/{symbol}',
            desc: 'Detects when large volume is absorbed with minimal price movement - the signature of a large counter-party absorbing aggressive orders. If total volume in the last 50 trades exceeds a threshold but price has moved less than 0.05%, absorption is detected. Absorption on the bid = buying wall (bullish). On the ask = selling wall (bearish). Often precedes reversals.',
            formula: 'absorbed = (total_volume > threshold) AND (price_move_pct < 0.05%)   strength = total_vol / (price_move + ε)',
          },
          {
            title: 'Tape speed (trades/sec)', endpoint: '/api/tape/{symbol}',
            desc: 'Measures the raw rate of incoming trades (trades per second). High tape speed = active/volatile market. Low tape speed = quiet market. Bursts in tape speed often precede large directional moves - institutional algorithms increase order frequency when they have information. Tape speed sampled every 2s, stored in rolling 3-hour history.',
            formula: 'tps(t) = count(trades in last 10s) / 10   burst = tps > mean_tps × 2.5',
          },
          {
            title: 'Whale / smart money classification', endpoint: '/api/alpha/{symbol} → smart_money',
            desc: 'Individual trades > $50,000 notional are classified as whale prints. Net whale flow = (buy_whale_usd − sell_whale_usd) / total_whale_usd. Top-trader L/S ratio from Binance is the smart-money proxy - these are the traders with the highest PnL over the last 24h. When top-trader ratio diverges from retail ratio, follow the top traders.',
            formula: 'whale_threshold = $50,000 USD per trade   net_flow = (Σ whale_buys − Σ whale_sells) / Σ whale_total',
          },
          {
            title: 'Liquidation imbalance index', endpoint: '/api/liquidations/{symbol}',
            desc: 'Cross-exchange liquidation flow from Binance and OKX. Tracks long vs short liquidation USD volume over a 5-minute rolling window. imbalance = (long_liq_usd − short_liq_usd) / total_liq_usd. Extreme positive = long cascade (sell pressure). Extreme negative = short cascade (buy pressure). Cascade alert fires on rising edge of cascade detection.',
            formula: 'imbalance = (long_liq_usd − short_liq_usd) / total_liq_usd   cascade = |imbalance| > 0.7 AND total_usd > $500k/5min',
          },
        ].map(f => (
          <div key={f.title} className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-5">
            <div className="flex items-start justify-between gap-4 mb-3">
              <h3 className="text-sm font-semibold text-white/80">{f.title}</h3>
              <span className="font-mono text-[10px] text-white/25 bg-white/[0.04] rounded px-2 py-0.5 flex-shrink-0">{f.endpoint}</span>
            </div>
            <div className="font-mono text-xs text-amber-400/60 bg-black/30 rounded px-3 py-1.5 mb-3">{f.formula}</div>
            <p className="text-xs text-white/45 leading-relaxed">{f.desc}</p>
          </div>
        ))}
      </div>
      <Callout type="info">All order flow metrics are computed from raw Binance aggTrade WebSocket stream with 2-second ingestion cadence. The zone check loop at 60s is too slow for microstructure - a dedicated trade ingest loop processes every fill in real-time.</Callout>
    </div>
  )
}

// ─── AI SYNTHESIS ─────────────────────────────────────────────────────────────

function AISynthesisSection() {
  return (
    <div>
      <SectionHeader
        tag="layer 6 · ai"
        title="AI synthesis - Gemma 4 + FinBERT"
        subtitle="Two AI models serve different roles: Gemma 4 (Ollama local LLM) generates qualitative market briefs by synthesising quantitative signals with news context. FinBERT (HuggingFace local CUDA) scores news headline sentiment with a finance-domain BERT model."
      />
      <div className="space-y-6">
        <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-5">
          <div className="flex items-center gap-3 mb-3">
            <h3 className="text-sm font-semibold text-white/80">Gemma 4 brief generation</h3>
            <span className="font-mono text-[10px] text-white/25 bg-white/[0.04] rounded px-2 py-0.5">POST /api/ai/brief</span>
          </div>
          <p className="text-xs text-white/45 leading-relaxed mb-4">
            Runs Gemma 4 (gemma4:e4b via Ollama at localhost:11434) with a structured prompt containing: current golden zones, funding rates, OI trend, squeeze risk, macro gate status, and the 10 most recent news headlines. The model synthesises all inputs into a 300-500 word actionable brief. Temperature 0.3 for consistency. Max tokens 800.
          </p>
          <ThTable
            headers={['Input', 'Source', 'Purpose']}
            rows={[
              ['Golden zones',    '/api/zones/{sym}',   'Key support/resistance context'],
              ['Funding rate',    '/api/funding/{sym}', 'Sentiment / carry cost signal'],
              ['OI trend',        '/api/oi/{sym}',      'Positioning momentum context'],
              ['Squeeze risk',    'Computed',           'Alert to crowded positioning'],
              ['Macro gate',      '/api/macro/status',  'Event risk filter'],
              ['News headlines',  '/api/news',          'Qualitative catalyst context'],
            ]}
          />
          <InfoCard title="Model resource requirements" accent="blue">
            Gemma 4 (e4b) requires ~6.7 GB VRAM or RAM. If system RAM is under ~8 GB free, the model fails with HTTP 500. Fallback: switch OLLAMA_MODEL to gemma3:4b in journal_router.py (2-4 GB RAM). Brief generation takes 8-25 seconds depending on model warmth and hardware.
          </InfoCard>
        </div>
        <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-5">
          <div className="flex items-center gap-3 mb-3">
            <h3 className="text-sm font-semibold text-white/80">FinBERT sentiment scoring</h3>
            <span className="font-mono text-[10px] text-white/25 bg-white/[0.04] rounded px-2 py-0.5">local CUDA · 671ms/55 headlines</span>
          </div>
          <p className="text-xs text-white/45 leading-relaxed mb-4">
            ProsusAI/finbert - a BERT model fine-tuned on financial news. Runs locally via HuggingFace transformers + PyTorch CUDA. Scores each headline as positive / negative / neutral with a confidence score. Aggregate sentiment = weighted average of all headline scores. Updated every ~90 seconds on the news feed cycle.
          </p>
          <ThTable
            headers={['Score', 'Interpretation', 'Market implication']}
            rows={[
              ['> 0.6 positive',  'Strong bullish news sentiment',    'Potential catalyst for upward moves. Confirm with OI.'],
              ['0.3-0.6 positive','Mild positive sentiment',          'Supportive background but not a primary driver.'],
              ['Neutral',         'No directional news edge',         'Technicals and derivatives signals dominate.'],
              ['0.3-0.6 negative','Mild negative sentiment',          'Headwind for longs. Risk-off background.'],
              ['> 0.6 negative',  'Strong bearish news sentiment',    'Potential catalyst for downward moves. Check macro gate.'],
            ]}
          />
        </div>
        <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-5">
          <h3 className="text-sm font-semibold text-white/80 mb-3">Rule-based research brief</h3>
          <p className="text-xs text-white/45 leading-relaxed mb-3">
            The Research tab also generates a deterministic (non-LLM) brief from indicator snapshots via GET /api/research/brief/{"{symbol}"}. This is fast (no AI latency) and produces 5 sections: Bias (EMA/Ichimoku/MACD votes), Levels (pivots/BB/SDC), Signals (RSI/Stoch/MACD/VWAP), Macro (gate status/funding/regime), Risk (ATR stops/squeeze/ADX warnings).
          </p>
          <InfoCard title="When to use each brief type" accent="teal">
            Research brief (rule-based): use for every trade decision - it is instant, deterministic, and always available. AI brief (Gemma 4): use weekly or when preparing for major setups - it adds qualitative news context that the rules-based system cannot capture. Never rely on the AI brief alone - it is a supplement, not a replacement.
          </InfoCard>
        </div>
      </div>
    </div>
  )
}

// ─── DATA SOURCES ─────────────────────────────────────────────────────────────

function DataSourcesSection() {
  return (
    <div>
      <SectionHeader
        tag="infrastructure"
        title="Data sources & system constraints"
        subtitle="Every data feed, its update frequency, known limitations, and what breaks when it is unavailable."
      />
      <DataSourceFrequencyChart />
      <div className="space-y-4">
        {[
          { source: 'Binance USDT-M Futures', type: 'WebSocket + REST', feeds: 'Primary depth, klines, aggTrade, OI, funding, forceOrder, markPrice', freq: '100ms (depth) / 1s (mark) / 15m (klines)', limit: 'Primary venue (weight 0.55). Rate limit 1200 req/min REST. POST news endpoint returns 403 - GET fallback used.', status: 'ok' },
          { source: 'OKX Swap',               type: 'WebSocket + REST', feeds: 'Cross-venue depth, funding (with nextFundingRate), OI', freq: 'WS depth + REST 4-5s', limit: 'Secondary venue (weight 0.27). Rate limit 10 req/s. Used for funding term structure + outlier detection.', status: 'ok' },
          { source: 'MEXC Futures',           type: 'WebSocket',        feeds: 'Cross-venue depth, trades (contracts → base asset normalized)', freq: 'Real-time stream + 60s app-ping', limit: 'Tertiary venue (weight 0.14). Quantities are in contracts - normalised in mexc_ws.py before merging.', status: 'ok' },
          { source: 'Deribit Options',        type: 'REST',             feeds: 'IV surface, OI by strike, put/call ratio, max pain, option prints', freq: 'Polled on demand (Research page refresh)', limit: 'No WebSocket for options - REST only. IV surface may lag up to 60s. Weight 0.04 in fusion.', status: 'ok' },
          { source: 'Ollama / Gemma 4',       type: 'Local HTTP :11434', feeds: 'AI brief generation, trade analysis', freq: 'On-demand (user clicks Generate AI Brief)', limit: 'Requires 6.7 GB free RAM/VRAM. If RAM < 8 GB free → HTTP 500. Fallback: gemma3:4b (2-4 GB).', status: 'warn' },
          { source: 'FinBERT (HuggingFace)',  type: 'Local CUDA',       feeds: 'Headline sentiment scoring (positive/negative/neutral)', freq: 'Every ~90s news cycle', limit: 'Requires CUDA. First call ~3s load. Subsequent: 671ms for 55 headlines. CPU fallback is 10-20×  slower.', status: 'ok' },
          { source: 'Finnhub',                type: 'REST API',         feeds: 'Crypto news headlines', freq: 'Every 90s news cycle', limit: 'Free tier: 60 calls/min. Nexus uses 1 call/90s - well within limits.', status: 'ok' },
          { source: 'Alternative.me',         type: 'REST API',         feeds: 'Fear & Greed Index (0-100)', freq: '60s TTL cache', limit: 'Free public API. No auth required. Returns current + historical Fear & Greed.', status: 'ok' },
          { source: 'BloFin Paper',           type: 'REST',             feeds: 'Paper trading execution, account balance, positions', freq: 'On-demand', limit: 'Demo mode (paper=True). Real execution requires BloFin API keys + paper=False in config.', status: 'ok' },
          { source: 'Telegram Bot',           type: 'REST',             feeds: 'Alert delivery for zone breaches, funding extremes, whale prints', freq: 'Triggered by alert conditions', limit: 'Requires valid BOT_TOKEN in .env. Placeholder token causes 404 on all alerts.', status: 'warn' },
        ].map(d => (
          <div key={d.source} className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-5">
            <div className="flex items-start justify-between gap-4 mb-3">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${d.status === 'ok' ? 'bg-emerald-400' : 'bg-amber-400'}`} />
                  <span className="text-sm font-medium text-white/80">{d.source}</span>
                </div>
                <span className="font-mono text-[10px] text-white/30">{d.type}</span>
              </div>
              <span className="text-[10px] text-white/25 flex-shrink-0">{d.freq}</span>
            </div>
            <div className="text-xs text-white/40 mb-2"><span className="text-white/25">Feeds: </span>{d.feeds}</div>
            <div className={`text-xs rounded px-3 py-1.5 ${d.status === 'warn' ? 'bg-amber-500/10 text-amber-400/80' : 'bg-white/[0.03] text-white/30'}`}>
              <span className="font-medium">Constraint: </span>{d.limit}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── READING SIGNALS ─────────────────────────────────────────────────────────

function ReadingSignalsSection() {
  return (
    <div>
      <SectionHeader
        tag="practical guide"
        title="How to read signals - 8-step framework"
        subtitle="A step-by-step decision framework for using Nexus output in live leveraged trading. Follow this sequence before every trade entry. Skipping steps is how accounts get liquidated."
      />
      <div className="space-y-3 mb-8">
        {[
          { step: '01', title: 'Check the macro gate first', color: 'text-red-400',
            desc: 'Research page → Macro Gate. If CLOSED, stop. A high-impact macro event is within 48 hours (FOMC, CPI, NFP, Powell speech). Leverage is inadvisable until the event passes and volatility normalises. The gate overrides all other signals.' },
          { step: '02', title: 'Read the regime - ADX + EMA', color: 'text-amber-400',
            desc: 'Trading page right panel → ADX 14 and EMA CROSS. ADX > 25 = trending regime (use trend strategies). ADX < 20 = ranging (use oscillators, fade extremes). EMA CROSS determines direction bias. Write down: REGIME and DIRECTION before looking at anything else.' },
          { step: '03', title: 'Check the composite alpha score', color: 'text-amber-400',
            desc: 'Alpha Signals tab → composite score and agreement_ratio. Only proceed if |score| > 40 AND agreement_ratio > 0.625 (5+ of 8 signals agree). Below these thresholds the edge is not statistically meaningful for leverage. High score + low agreement = one signal is anomalous, not a real edge.' },
          { step: '04', title: 'Validate with market structure', color: 'text-teal-400',
            desc: 'Research page → funding rate, OI trend, CVD. All three should align with your directional thesis. Specifically: funding should not be extreme in your direction (you\'d be the crowded trade), OI should be rising with price if going long.' },
          { step: '05', title: 'Identify the nearest golden zone', color: 'text-teal-400',
            desc: 'Liquidity Map tab → find nearest Platinum or Gold institutional zone. Your entry should be within one ATR of a support zone for longs, or resistance zone for shorts. Do not enter in the middle of a liquidity void - price accelerates through voids unpredictably.' },
          { step: '06', title: 'Calculate position size from Kelly', color: 'text-emerald-400',
            desc: 'Research page → Kelly Size % and Position Cap. Risk per trade = min(Kelly Size, Position Cap) × account equity. Calculate stop in price terms: Entry ± 1.5 × ATR. Verify the stop is beyond the nearest zone boundary - a stop inside a support/resistance zone gets hunted.' },
          { step: '07', title: 'Run Monte Carlo before entry', color: 'text-emerald-400',
            desc: 'Research page → Monte Carlo simulation with your proposed entry, stop_pct, target_pct. If P5 (5th percentile) equity curve shows drawdown > 15% of account, reduce position size until P5 is within tolerance. The P5 is your worst-case realistic scenario - not the absolute worst, but 1-in-20 bad luck.' },
          { step: '08', title: 'Check AI brief for narrative context', color: 'text-blue-400',
            desc: 'Alerts & News tab → AI synthesis brief (if generated). This integrates qualitative macro news that quantitative signals cannot capture. A technically perfect setup against a "Fed signals prolonged higher rates" headline is a lower-quality trade. Use the brief to confirm, not initiate.' },
        ].map(s => (
          <div key={s.step} className="flex gap-4 rounded-xl border border-white/[0.06] bg-white/[0.02] px-5 py-4">
            <span className={`font-mono text-2xl font-bold ${s.color} opacity-40 min-w-[40px] leading-none pt-0.5`}>{s.step}</span>
            <div>
              <div className="text-sm font-medium text-white/75 mb-1">{s.title}</div>
              <p className="text-xs text-white/40 leading-relaxed">{s.desc}</p>
            </div>
          </div>
        ))}
      </div>
      <Callout type="warning">This framework assumes all data pipelines are healthy (green status indicators on the overview page). If Alpha Signals shows majority 0% values, the WebSocket feed has an issue - do not trade on stale data.</Callout>
      <div className="mt-8">
        <h3 className="text-base font-semibold text-white/80 mb-4">Quick-reference confluence checklist</h3>
        <ThTable
          headers={['Signal', 'Long setup requires', 'Short setup requires', 'Weight']}
          rows={[
            ['Macro Gate',       'OPEN',                                      'OPEN',                                      'Hard filter'],
            ['ADX regime',       '> 20 (trending) or < 20 (ranging)',         '> 20 (trending) or < 20 (ranging)',         'Filter'],
            ['EMA cross',        'EMA50 > EMA200 (golden cross)',              'EMA50 < EMA200 (death cross)',               'High'],
            ['Alpha composite',  '> +40, agreement > 0.625',                  '< −40, agreement > 0.625',                  'High'],
            ['Funding rate',     '< 0.08%/8h (not crowded long)',              '> −0.05%/8h (not crowded short)',            'Medium'],
            ['OI trend',         'Rising OI with rising price',               'Rising OI with falling price',               'Medium'],
            ['CVD',              'CVD divergence bullish or neutral',          'CVD divergence bearish or neutral',          'Medium'],
            ['Golden zone',      'Entry near support zone (≤ 1 ATR)',         'Entry near resistance zone (≤ 1 ATR)',       'Medium'],
            ['Kelly Size',       '> 0.0% (positive edge detected)',           '> 0.0% (positive edge detected)',           'High'],
            ['Monte Carlo P5',   'P5 drawdown ≤ 15% account',                'P5 drawdown ≤ 15% account',                 'Sizing'],
          ].map(r => [
            <span key="check" className="text-white/60 font-medium">{r[0]}</span>,
            <span key="long" className="text-emerald-400/70 text-[11px]">{r[1]}</span>,
            <span key="short" className="text-red-400/70 text-[11px]">{r[2]}</span>,
            <span key="prio" className="text-white/35 text-[11px]">{r[3]}</span>,
          ])}
        />
      </div>
    </div>
  )
}

// ─── MAIN COMPONENT ───────────────────────────────────────────────────────────

export default function SystemDocsTab() {
  const [activeSection, setActiveSection] = useState<SectionId>('overview')
  const [searchQuery, setSearchQuery] = useState('')
  const contentRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (contentRef.current) contentRef.current.scrollTop = 0
  }, [activeSection])

  const filteredNav = searchQuery
    ? NAV_ITEMS.filter(item => item.label.toLowerCase().includes(searchQuery.toLowerCase()))
    : NAV_ITEMS

  function renderSection() {
    switch (activeSection) {
      case 'overview':             return <OverviewSection />
      case 'fusion-engine':        return <FusionEngineSection />
      case 'alpha-engine':         return <AlphaEngineSection />
      case 'technical-indicators': return <TechnicalIndicatorsSection />
      case 'market-structure':     return <MarketStructureSection />
      case 'risk-engine':          return <RiskEngineSection />
      case 'circuit-breaker':      return <CircuitBreakerSection />
      case 'liquidity-map':        return <LiquidityMapSection />
      case 'order-flow':           return <OrderFlowSection />
      case 'ai-synthesis':         return <AISynthesisSection />
      case 'data-sources':         return <DataSourcesSection />
      case 'reading-signals':      return <ReadingSignalsSection />
    }
  }

  return (
    <div className="sysdocs-root flex h-full w-full overflow-hidden" style={{ background: 'var(--surface)', color: 'var(--on-surface)' }}>
      <style>{`
        /* ── Theme bridge: map Tailwind on-dark utilities to CSS vars so light mode reads well.
             Dark ink lifted from 0.92 → 1.0, dim 0.60 → 0.78, fainter 0.40 → 0.62,
             faint 0.30 → 0.50 so secondary text passes WCAG AA on both themes.
             Light ink lifted symmetrically. */
        .sysdocs-root {
          --sd-ink: rgba(255,255,255,1.0);
          --sd-dim: rgba(255,255,255,0.78);
          --sd-fainter: rgba(255,255,255,0.62);
          --sd-faint: rgba(255,255,255,0.50);
          --sd-line: rgba(255,255,255,0.08);
          --sd-line-strong: rgba(255,255,255,0.14);
          --sd-chip: rgba(255,255,255,0.04);
          --sd-chip-strong: rgba(255,255,255,0.07);
          --sd-code-bg: rgba(0,0,0,0.45);
          /* Density: base body text is ~13px (vs 11-12 elsewhere) because
             docs are READ, not scanned - readability beats density here. */
          font-size: 13px;
          line-height: 1.55;
        }
        html.light .sysdocs-root, body.light .sysdocs-root {
          --sd-ink: #0a0a0d;                       /* pure-black-ish for AAA on light bg */
          --sd-dim: rgba(10,10,13,0.80);
          --sd-fainter: rgba(10,10,13,0.64);
          --sd-faint: rgba(10,10,13,0.50);
          --sd-line: rgba(0,0,0,0.14);
          --sd-line-strong: rgba(0,0,0,0.22);
          --sd-chip: rgba(0,0,0,0.04);
          --sd-chip-strong: rgba(0,0,0,0.07);
          --sd-code-bg: rgba(0,0,0,0.06);
        }
        /* Body / paragraph readability - bump cramped Tailwind sizes. */
        .sysdocs-root .text-xs   { font-size: 12px !important; line-height: 1.55 !important; }
        .sysdocs-root .text-sm   { font-size: 13px !important; line-height: 1.6 !important; }
        .sysdocs-root .text-base { font-size: 15px !important; line-height: 1.6 !important; }
        .sysdocs-root .text-lg   { font-size: 17px !important; line-height: 1.45 !important; }
        .sysdocs-root .text-xl   { font-size: 20px !important; line-height: 1.35 !important; }
        .sysdocs-root .text-2xl  { font-size: 24px !important; line-height: 1.3 !important; }
        .sysdocs-root .text-3xl  { font-size: 30px !important; line-height: 1.2 !important; }
        .sysdocs-root .text-\\[11px\\] { font-size: 12px !important; }
        .sysdocs-root .text-\\[10px\\] { font-size: 12px !important; }
        /* Code blocks need monospace + slightly bigger to be scannable. */
        .sysdocs-root .font-mono { font-size: 13px !important; letter-spacing: 0.01em; }
        .sysdocs-root .text-white\\/90 { color: var(--sd-ink); }
        .sysdocs-root .text-white\\/80 { color: var(--sd-ink); }
        .sysdocs-root .text-white\\/70 { color: var(--sd-dim); }
        .sysdocs-root .text-white\\/60 { color: var(--sd-dim); }
        .sysdocs-root .text-white\\/50 { color: var(--sd-fainter); }
        .sysdocs-root .text-white\\/45 { color: var(--sd-fainter); }
        .sysdocs-root .text-white\\/40 { color: var(--sd-fainter); }
        .sysdocs-root .text-white\\/30 { color: var(--sd-faint); }
        .sysdocs-root .text-white\\/25 { color: var(--sd-faint); }
        .sysdocs-root .text-white\\/20 { color: var(--sd-faint); }
        .sysdocs-root .bg-white\\/\\[0\\.02\\] { background-color: var(--sd-chip); }
        .sysdocs-root .bg-white\\/\\[0\\.03\\] { background-color: var(--sd-chip); }
        .sysdocs-root .bg-white\\/\\[0\\.04\\] { background-color: var(--sd-chip-strong); }
        .sysdocs-root .bg-white\\/\\[0\\.05\\] { background-color: var(--sd-chip-strong); }
        .sysdocs-root .bg-white\\/\\[0\\.06\\] { background-color: var(--sd-chip-strong); }
        .sysdocs-root .border-white\\/\\[0\\.06\\] { border-color: var(--sd-line); }
        .sysdocs-root .border-white\\/\\[0\\.07\\] { border-color: var(--sd-line); }
        .sysdocs-root .border-white\\/\\[0\\.08\\] { border-color: var(--sd-line); }
        .sysdocs-root .border-white\\/\\[0\\.10\\] { border-color: var(--sd-line-strong); }
        .sysdocs-root .hover\\:bg-white\\/\\[0\\.03\\]:hover { background-color: var(--sd-chip-strong); }
        .sysdocs-root .hover\\:bg-white\\/\\[0\\.04\\]:hover { background-color: var(--sd-chip-strong); }
        .sysdocs-root .bg-black\\/40 { background-color: var(--sd-code-bg); }
        .sysdocs-root .bg-black\\/30 { background-color: var(--sd-code-bg); }
        /* Amber utility classes are remapped to silver primary in globals.css
           (silver-only spec). The inline amber fallbacks here have been removed
           so the institutional palette is single-sourced. */
        html.light .sysdocs-root .text-blue-300\\/80 { color: rgba(37,99,235,0.82); }
        html.light .sysdocs-root .text-red-300\\/80 { color: rgba(185,28,28,0.82); }
        html.light .sysdocs-root .text-teal-400 { color: #0f766e; }
        html.light .sysdocs-root .text-purple-400 { color: #6d28d9; }
        html.light .sysdocs-root .text-orange-400 { color: #c2410c; }
        html.light .sysdocs-root .text-blue-400 { color: #1d4ed8; }
        html.light .sysdocs-root .text-emerald-400 { color: #047857; }
      `}</style>

      {/* ── Left nav ── */}
      <div className="flex-shrink-0 flex flex-col" style={{ width: 200, borderRight: '1px solid var(--hairline)', background: 'var(--surface-container-low, transparent)' }}>
        <div className="px-4 pt-5 pb-4" style={{ borderBottom: '1px solid var(--hairline)' }}>
          <div className="text-[10px] uppercase tracking-widest mb-3" style={{ color: 'var(--on-surface-dim)' }}>System docs</div>
          <input
            type="text"
            placeholder="Search..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="w-full rounded-lg px-3 py-1.5 text-xs outline-none transition-colors"
            style={{
              background: 'var(--surface-container, rgba(127,127,127,0.06))',
              border: '1px solid var(--hairline)',
              color: 'var(--on-surface)',
            }}
          />
        </div>
        <nav className="flex-1 overflow-y-auto py-2 px-2">
          {filteredNav.map(item => {
            const isActive = activeSection === item.id
            return (
              <button
                key={item.id}
                onClick={() => setActiveSection(item.id)}
                className="w-full text-left rounded-lg mb-0.5 flex items-center justify-between gap-2 transition-all text-xs"
                style={{
                  padding: '7px 10px',
                  background: isActive ? 'rgba(var(--primary-rgb,198,198,199),0.12)' : 'transparent',
                  color: isActive ? 'var(--primary)' : 'var(--on-surface-variant)',
                  border: isActive ? '1px solid rgba(var(--primary-rgb,198,198,199),0.30)' : '1px solid transparent',
                }}
              >
                <span className="truncate">{item.label}</span>
                {item.badge && (
                  <span className={`text-[9px] px-1.5 py-0.5 rounded flex-shrink-0 ${BADGE[item.badgeColor ?? 'amber'] ?? BADGE.amber}`}>
                    {item.badge}
                  </span>
                )}
              </button>
            )
          })}
        </nav>
        <div className="px-3 py-3" style={{ borderTop: '1px solid var(--hairline)' }}>
          <div className="text-[9px] text-center font-mono" style={{ color: 'var(--on-surface-dim)' }}>NEXUS v0.3 · OBSIDIAN</div>
        </div>
      </div>

      {/* ── Content ── */}
      <div ref={contentRef} className="flex-1 overflow-y-auto min-w-0">
        <div className="sysdocs-content w-full px-6 py-8">
          {renderSection()}
        </div>
      </div>

    </div>
  )
}