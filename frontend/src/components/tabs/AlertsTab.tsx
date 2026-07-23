'use client'

import { useEffect, useCallback, useRef, useState } from 'react'
import { useBriefStore, fngStale, smStale, type StoredBrief } from '@/lib/briefStore'
import { renderBriefBody, fmtBriefStamp } from '@/lib/mdRender'

interface Props { symbol: string; api: string }

// ── Old API shapes (macro + news) ─────────────────────────────────────────────
interface MacroRelease {
  name: string
  tier: string
  datetime_utc: string
  days_until: number
  hours_until: number
  description: string
}

interface NewsItem {
  title?: string
  source?: string
  url?: string
  published?: string
  sentiment?: string
}

// ── Helpers ───────────────────────────────────────────────────────────────────
const pColor = (n: number) => n > 0 ? '#16c784' : n < 0 ? '#ea3943' : 'var(--on-surface-dim)'

// Delegate to the shared clean-markdown renderer in @/lib/mdRender
const renderMd = (text: string): React.ReactNode => renderBriefBody(text)

function tierTone(tier: string): string {
  if (tier.startsWith('Tier1')) return 'var(--chart-bear)'
  if (tier.startsWith('Tier2')) return 'var(--primary)'
  if (tier.startsWith('Tier3')) return '#b5c945'
  return 'var(--on-surface-variant)'
}

// ── Canvas-based Fear & Greed gauge (new, correct) ───────────────────────────
function FngGauge({ score, label, color }: { score: number; label: string; color: string }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const c = ref.current; if (!c) return
    const ctx = c.getContext('2d'); if (!ctx) return
    const W = c.width, H = c.height, cx = W / 2, cy = H * 0.78, r = W * 0.38
    ctx.clearRect(0, 0, W, H)
    const segs = [
      { from: Math.PI, to: Math.PI * 1.2, fill: '#c0392b' },
      { from: Math.PI * 1.2, to: Math.PI * 1.4, fill: '#e67e22' },
      { from: Math.PI * 1.4, to: Math.PI * 1.6, fill: '#f1c40f' },
      { from: Math.PI * 1.6, to: Math.PI * 1.8, fill: '#2ecc71' },
      { from: Math.PI * 1.8, to: Math.PI * 2, fill: '#27ae60' },
    ]
    const thick = r * 0.28
    ctx.beginPath(); ctx.arc(cx, cy, r, Math.PI, Math.PI * 2)
    ctx.lineWidth = thick + 4; ctx.strokeStyle = 'rgba(0,0,0,0.3)'; ctx.stroke()
    segs.forEach(s => {
      ctx.beginPath(); ctx.arc(cx, cy, r, s.from, s.to)
      ctx.lineWidth = thick; ctx.strokeStyle = s.fill; ctx.lineCap = 'butt'; ctx.stroke()
    })
    // Sample current theme text color so needle + labels track light/dark.
    const root = getComputedStyle(document.documentElement)
    const onSurface = root.getPropertyValue('--on-surface').trim() || '#e8e8ea'
    const onSurfaceDim = root.getPropertyValue('--on-surface-dim').trim() || 'rgba(255,255,255,0.3)'
    const ang = Math.PI + (score / 100) * Math.PI
    const nx = cx + Math.cos(ang) * r * 0.8, ny = cy + Math.sin(ang) * r * 0.8
    ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(nx, ny)
    ctx.lineWidth = 2.5; ctx.strokeStyle = onSurface; ctx.lineCap = 'round'; ctx.stroke()
    ctx.beginPath(); ctx.arc(cx, cy, 6, 0, Math.PI * 2)
    ctx.fillStyle = onSurface; ctx.fill()
    ctx.font = '8px monospace'; ctx.textAlign = 'center'; ctx.fillStyle = onSurfaceDim
    const lblR = r + thick * 0.5 + 13
    ;[{ t: 'E.FEAR', a: Math.PI * 1.1 }, { t: 'FEAR', a: Math.PI * 1.3 },
      { t: 'NEUT', a: Math.PI * 1.5 }, { t: 'GREED', a: Math.PI * 1.7 },
      { t: 'E.GRD', a: Math.PI * 1.9 },
    ].forEach(l => ctx.fillText(l.t, cx + Math.cos(l.a) * lblR, cy + Math.sin(l.a) * lblR))
  }, [score])
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', paddingTop: 8 }}>
      <canvas ref={ref} width={220} height={126} style={{ width: 220, height: 126 }} />
      <div style={{ marginTop: -6, textAlign: 'center' }}>
        <div style={{ fontSize: 42, fontWeight: 800, color, lineHeight: 1, fontFamily: 'monospace', letterSpacing: '-2px' }}>{score}</div>
        <div style={{ fontSize: 11, color: 'var(--on-surface-dim)', letterSpacing: '0.09em', textTransform: 'uppercase', marginTop: 3 }}>{label}</div>
      </div>
    </div>
  )
}

function Bar({ label, score, tip }: { label: string; score: number; tip?: string }) {
  const c = score < 35 ? '#ea3943' : score > 65 ? '#16c784' : 'var(--primary)'
  return (
    <div style={{ marginBottom: 7 }} title={tip}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3, fontSize: 10 }}>
        <span style={{ color: 'var(--on-surface-dim)' }}>{label}</span>
        <span style={{ color: c, fontFamily: 'monospace', fontWeight: 600 }}>{Math.round(score)}</span>
      </div>
      <div style={{ height: 4, background: 'var(--surface-container-high, rgba(127,127,127,0.10))', borderRadius: 2, overflow: 'hidden' }}>
        <div style={{ width: `${score}%`, height: '100%', background: c, borderRadius: 2, transition: 'width 0.7s ease' }} />
      </div>
    </div>
  )
}

function SmSparkline({ top, retail }: { top: { ratio: number }[]; retail: { ratio: number }[] }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const c = ref.current; if (!c) return
    const ctx = c.getContext('2d'); if (!ctx) return
    const W = c.width, H = c.height, pad = 6
    ctx.clearRect(0, 0, W, H)
    const all = [...top, ...retail].map(d => d.ratio)
    if (!all.length) return
    const mn = Math.min(...all) * 0.98, mx = Math.max(...all) * 1.02, rng = mx - mn || 0.01
    const toX = (i: number, n: number) => pad + (i / Math.max(n - 1, 1)) * (W - 2 * pad)
    const toY = (v: number) => H - pad - ((v - mn) / rng) * (H - 2 * pad)
    ctx.setLineDash([3, 4]); ctx.strokeStyle = 'var(--hairline)'; ctx.lineWidth = 1
    ctx.beginPath(); ctx.moveTo(pad, toY(1.0)); ctx.lineTo(W - pad, toY(1.0)); ctx.stroke()
    ctx.setLineDash([])
    const draw = (data: { ratio: number }[], col: string, w: number) => {
      if (!data.length) return
      ctx.beginPath(); ctx.strokeStyle = col; ctx.lineWidth = w
      data.forEach((d, i) => i === 0 ? ctx.moveTo(toX(i, data.length), toY(d.ratio)) : ctx.lineTo(toX(i, data.length), toY(d.ratio)))
      ctx.stroke()
    }
    draw(retail, 'rgba(234,57,67,0.45)', 1)
    draw(top, '#16c784', 1.8)
  }, [top, retail])
  return (
    <div>
      <canvas ref={ref} width={280} height={56} style={{ width: '100%', height: 56, display: 'block' }} />
      <div style={{ display: 'flex', gap: 14, marginTop: 4, fontSize: 10, color: 'var(--on-surface-dim)' }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 14, height: 2, background: '#16c784', display: 'inline-block', borderRadius: 1 }} />Top traders
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 14, height: 2, background: 'rgba(234,57,67,0.6)', display: 'inline-block', borderRadius: 1 }} />Retail
        </span>
      </div>
    </div>
  )
}

function ConfRing({ value, color }: { value: number; color: string }) {
  const r = 22, stroke = 5, circ = 2 * Math.PI * r, dash = (value / 100) * circ
  return (
    <svg width={60} height={60}>
      <circle cx={30} cy={30} r={r} fill="none" stroke="var(--hairline)" strokeWidth={stroke} transform="rotate(-90 30 30)" />
      <circle cx={30} cy={30} r={r} fill="none" stroke={color} strokeWidth={stroke}
        strokeDasharray={`${dash} ${circ - dash}`} strokeLinecap="round" transform="rotate(-90 30 30)"
        style={{ transition: 'stroke-dasharray 0.8s ease' }} />
      <text x={30} y={35} textAnchor="middle" fill={color} fontSize={13} fontWeight={700} fontFamily="monospace">{value}</text>
    </svg>
  )
}

// ── Old-style Macro Release Calendar ─────────────────────────────────────────
function MacroReleasesCard({ releases }: { releases: MacroRelease[] }) {
  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div className="card-header">
        <span>MACRO RELEASE CALENDAR</span>
        <span style={{ color: 'var(--on-surface-dim)', fontSize: 10, letterSpacing: '0.1em' }}>
          NEXT {releases.length}
        </span>
      </div>
      <div className="card-body" style={{ flex: 1, overflow: 'auto', padding: 6 }}>
        <div className="flex flex-col gap-1">
          {releases.length === 0 ? (
            <div style={{ padding: 14, color: 'var(--on-surface-dim)' }}>Loading release calendar…</div>
          ) : releases.map((r) => {
            const tone = tierTone(r.tier)
            const days = r.days_until
            const countdown =
              days >= 1
                ? `${Math.floor(days)}d ${Math.round((days % 1) * 24)}h`
                : `${Math.round(r.hours_until)}h`
            return (
              <div
                key={`${r.name}-${r.datetime_utc}`}
                style={{
                  padding: '8px 10px',
                  background: 'var(--surface-container-low)',
                  border: '1px solid var(--hairline)',
                  borderLeft: `2px solid ${tone}`,
                  borderRadius: 2,
                  fontSize: 11,
                }}
              >
                <div className="flex justify-between items-center">
                  <span style={{ color: 'var(--on-surface)', fontWeight: 700, letterSpacing: '0.02em' }}>
                    {r.name}
                  </span>
                  <span
                    className="text-mono"
                    style={{
                      color: days < 2 ? 'var(--chart-bear)' : 'var(--primary)',
                      fontWeight: 700,
                      fontSize: 12,
                    }}
                  >
                    T-{countdown}
                  </span>
                </div>
                <div style={{ color: 'var(--on-surface-variant)', marginTop: 2, lineHeight: 1.35 }}>
                  {r.description}
                </div>
                <div
                  className="flex justify-between"
                  style={{ marginTop: 3, color: 'var(--on-surface-dim)', fontSize: 10, letterSpacing: '0.04em' }}
                >
                  <span style={{ color: tone, letterSpacing: '0.12em', fontWeight: 600 }}>
                    {r.tier.replace('_', ' ').toUpperCase()}
                  </span>
                  <span className="text-mono">
                    {new Date(r.datetime_utc).toUTCString().replace('GMT', 'UTC')}
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ── Old-style News Feed ───────────────────────────────────────────────────────
function NewsFeedCard({ news }: { news: NewsItem[] }) {
  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div className="card-header">NEWS FEED ({news.length})</div>
      <div className="card-body" style={{ flex: 1, overflow: 'auto', padding: 6 }}>
        <div className="flex flex-col gap-1">
          {news.length === 0 ? (
            <div style={{ padding: 14, color: 'var(--on-surface-dim)' }}>Loading news feeds…</div>
          ) : news.map((n, i) => {
            const s = String(n.sentiment || 'neutral')
            const badgeClass =
              s === 'positive' ? 'badge-bullish' : s === 'negative' ? 'badge-bearish' : 'badge-neutral'
            return (
              <a
                key={i}
                href={String(n.url || '#')}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  display: 'block',
                  padding: '7px 10px',
                  background: 'var(--surface-container-low)',
                  border: '1px solid var(--hairline)',
                  borderRadius: 2,
                  fontSize: 11,
                  textDecoration: 'none',
                  transition: 'border-color 0.15s',
                }}
              >
                <div className="flex justify-between items-start gap-2">
                  <span style={{ color: 'var(--on-surface)', fontWeight: 600, lineHeight: 1.3 }}>
                    {String(n.title || '')}
                  </span>
                  <span className={`badge ${badgeClass}`} style={{ flexShrink: 0 }}>
                    {s === 'positive' ? 'BULL' : s === 'negative' ? 'BEAR' : 'NTRL'}
                  </span>
                </div>
                <div
                  className="flex justify-between"
                  style={{ marginTop: 3, color: 'var(--on-surface-dim)', fontSize: 10 }}
                >
                  <span>{String(n.source || '')}</span>
                  <span>{String(n.published || '').slice(0, 16)}</span>
                </div>
              </a>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────
export default function AlertsTab({ symbol, api }: Props) {
  const {
    fng, fngLoading, smartMoney, smartMoneyLoading, brief, isGenerating,
    setFng, setFngLoading, setSmartMoney, setSmLoading,
    setBrief, clearBrief, setGenerating,
  } = useBriefStore()

  // Old-style state for macro + news (fetched directly like the old component)
  const [newsItems,  setNewsItems]  = useState<NewsItem[]>([])
  const [releases,   setReleases]   = useState<MacroRelease[]>([])

  // ── F&G + Smart Money sync ────────────────────────────────────────────────
  // Read fresh store state inside callback - never close over a snapshot.
  const fetchSync = useCallback(async () => {
    const s = useBriefStore.getState()
    if (!fngStale(s.fng) && s.fng && !smStale(s.smartMoney) && s.smartMoney) return
    try {
      if (!s.fng)        setFngLoading(true)
      if (!s.smartMoney) setSmLoading(true)
      const r = await fetch(`${api}/api/sentiment/sync?symbol=${symbol}`)
      const d = await r.json()
      if (d.fng && !d.fng.error)               setFng({ ...d.fng, stale: false })
      if (d.smartmoney && !d.smartmoney.error) setSmartMoney({ ...d.smartmoney, stale: false })
    } catch {
      setFngLoading(false); setSmLoading(false)
    }
  }, [api, symbol, setFng, setFngLoading, setSmartMoney, setSmLoading])

  // ── Brief loader ──────────────────────────────────────────────────────────
  const loadBrief = useCallback(async () => {
    if (brief) return
    try {
      const r = await fetch(`${api}/api/sentiment/brief-load`)
      const d = await r.json()
      if (d.brief || d.news_synthesis) setBrief(d as StoredBrief)
    } catch {}
  }, [api, brief, setBrief])

  // ── Old-style news + macro releases ──────────────────────────────────────
  const fetchNewsAndMacro = useCallback(async () => {
    try {
      const [nRes, rRes] = await Promise.all([
        fetch(`${api}/api/news`),
        fetch(`${api}/api/macro/releases`),
      ])
      const nd = await nRes.json()
      const rd = await rRes.json()
      setNewsItems((nd?.news ?? nd ?? []).slice(0, 40))
      setReleases(rd?.releases ?? rd ?? [])
    } catch {}
  }, [api])

  useEffect(() => {
    void fetchSync(); void loadBrief(); void fetchNewsAndMacro()
    const i1 = setInterval(() => void fetchSync(), 60_000)
    const i2 = setInterval(() => void fetchNewsAndMacro(), 60_000)
    return () => { clearInterval(i1); clearInterval(i2) }
  }, []) // eslint-disable-line

  // ── Generate brief ────────────────────────────────────────────────────────
  const generateBrief = async () => {
    clearBrief()
    setGenerating(true)
    try { await fetch(`${api}/api/sentiment/brief-clear`, { method: 'DELETE' }) } catch {}
    try {
      const r = await fetch(`${api}/api/ai/brief`, {
        method: 'POST',
        signal: AbortSignal.timeout(150_000),
      })
      const d = await r.json()
      const curFng = useBriefStore.getState().fng
      const curSm  = useBriefStore.getState().smartMoney
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
      }
      setBrief(stored)
      fetch(`${api}/api/sentiment/brief-save`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(stored),
      }).catch(() => {})
    } catch (e) {
      setBrief({
        brief: null, news_synthesis: null, news_sentiment: null, news_count: 0,
        generated_at: new Date().toISOString(), symbol,
        fng_score: null, fng_label: null, sm_signal: null, sm_score: null,
        error: e instanceof Error ? e.message : 'Brief failed',
      })
    } finally { setGenerating(false) }
  }

  const copyBrief = () => {
    if (!brief) return
    const txt = [
      `NEXUS AI BRIEF - ${brief.symbol} - ${fmtBriefStamp(brief.generated_at)}`,
      '', brief.news_synthesis ?? '', '', brief.brief ?? '',
    ].filter(Boolean).join('\n')
    navigator.clipboard.writeText(txt).catch(() => {})
  }

  // ── Styles ────────────────────────────────────────────────────────────────
  const card: React.CSSProperties = {
    background: 'var(--surface-container, var(--surface-container, rgba(127,127,127,0.06)))',
    border: '1px solid var(--hairline)', borderRadius: 12, padding: 16,
  }
  const lbl: React.CSSProperties = {
    fontSize: 10, fontWeight: 600, letterSpacing: '0.08em',
    textTransform: 'uppercase', color: 'var(--on-surface-dim)', marginBottom: 12,
  }
  const pill = (c: string): React.CSSProperties => ({
    display: 'inline-block', padding: '2px 8px', borderRadius: 20,
    fontSize: 9, fontWeight: 700, letterSpacing: '0.06em',
    background: `${c}18`, color: c, border: `1px solid ${c}30`,
  })

  const smSig = smartMoney?.signal
  const smTop = smartMoney?.top_trader
  const smDiv = smartMoney?.divergence

  return (
    <div style={{ padding: '14px 18px', height: '100%', overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 12 }}>
      <style>{`@keyframes pulse{0%,100%{opacity:.12}50%{opacity:1}}`}</style>

      {/* ── AI Brief header ─────────────────────────────────────────────── */}
      <div style={{ ...card, padding: '13px 16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
              <span style={{ ...lbl, marginBottom: 0 }}>AI NEWS SYNTHESIS - GEMMA 4</span>
              {brief && !isGenerating && (
                <span style={{ ...pill('#16c784'), fontSize: 8 }}>ACTIVE</span>
              )}
            </div>
            {!brief && !isGenerating && (
              <div style={{ fontSize: 12, color: 'var(--on-surface-dim)', opacity: 0.65 }}>
                {newsItems.length > 0 ? `${newsItems.length} headlines queued - click Generate when ready` : 'Loading headlines…'}
              </div>
            )}
            {brief && !isGenerating && (
              <div style={{ fontSize: 10, color: 'var(--on-surface-dim)', opacity: 0.55 }}>
                Generated {fmtBriefStamp(brief.generated_at)}
                {brief.fng_score != null && ` · F&G ${brief.fng_score} ${brief.fng_label ?? ''}`}
                {brief.sm_signal && ` · SM: ${brief.sm_signal}`}
              </div>
            )}
          </div>
          <div style={{ display: 'flex', gap: 7, flexShrink: 0 }}>
            {brief && !isGenerating && (
              <button onClick={copyBrief} style={{ padding: '7px 12px', background: 'transparent', color: 'var(--on-surface-dim)', border: '1px solid var(--hairline)', borderRadius: 7, fontSize: 11, cursor: 'pointer' }}>
                ⎘ Copy
              </button>
            )}
            <button
              onClick={() => void generateBrief()} disabled={isGenerating}
              style={{ padding: '8px 18px', background: isGenerating ? 'var(--surface-container-high, rgba(127,127,127,0.10))' : 'var(--primary)', color: isGenerating ? 'var(--on-surface-dim)' : '#000', border: 'none', borderRadius: 7, fontSize: 10, fontWeight: 700, cursor: isGenerating ? 'not-allowed' : 'pointer', letterSpacing: '0.07em' }}
            >
              {isGenerating ? 'GENERATING…' : 'GENERATE AI BRIEF'}
            </button>
          </div>
        </div>
        {isGenerating && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 10, padding: '10px 12px', background: 'var(--surface-container, rgba(127,127,127,0.04))', borderRadius: 8 }}>
            <div style={{ display: 'flex', gap: 4 }}>
              {[0, 1, 2].map(i => (
                <div key={i} style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--primary)', animation: `pulse 1.2s ${i * 0.2}s infinite ease-in-out` }} />
              ))}
            </div>
            <span style={{ fontSize: 12, color: 'var(--on-surface-dim)' }}>
              Synthesizing {newsItems.length} headlines with local AI - 30-90s…
            </span>
          </div>
        )}
        {brief?.news_synthesis && !isGenerating && (
          <div
            style={{
              marginTop: 11,
              fontSize: 13,
              color: 'var(--on-surface)',
              maxHeight: 'min(320px, 38vh)',
              overflowY: 'auto',
              overflowX: 'hidden',
              paddingRight: 6,
              scrollbarGutter: 'stable',
            }}
          >
            {renderMd(brief.news_synthesis)}
          </div>
        )}
        {brief?.error && !isGenerating && (
          <div style={{ marginTop: 8, fontSize: 12, color: '#ea3943', opacity: 0.8 }}>{brief.error}</div>
        )}
      </div>

      {/* ── 3-col grid ──────────────────────────────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr 1fr', gap: 12, minHeight: 520 }}>

        {/* Col 1: F&G (new canvas gauge) */}
        <div style={{ ...card, overflow: 'auto' }}>
          <div style={lbl}>BITCOIN FEAR &amp; GREED</div>
          {fngLoading && !fng && (
            <div style={{ textAlign: 'center', padding: '32px 0', color: 'var(--on-surface-dim)', fontSize: 12 }}>Computing…</div>
          )}
          {fng && (
            <>
              <FngGauge score={fng.score} label={fng.label} color={fng.color} />
              {fng.ai_interpretation && (
                <div style={{ margin: '12px 0 10px', padding: '9px 11px', background: 'var(--surface-container, rgba(127,127,127,0.06))', borderRadius: 8, borderLeft: `3px solid ${fng.color}`, fontSize: 12, color: 'var(--on-surface)', lineHeight: 1.6 }}>
                  {fng.ai_interpretation}
                </div>
              )}
              {fng.components && (
                <div style={{ marginTop: 4 }}>
                  <div style={{ fontSize: 9, color: 'var(--on-surface-dim)', letterSpacing: '0.07em', textTransform: 'uppercase', marginBottom: 8 }}>Component breakdown</div>
                  <Bar label="Volatility"        score={fng.components.volatility}   tip="High swing = Fear" />
                  <Bar label="Momentum"          score={fng.components.momentum}     tip="Price × volume direction" />
                  <Bar label="Funding"           score={fng.components.funding}      tip="+ve = crowded long = Greed" />
                  <Bar label="L/S (contrarian)"  score={fng.components.ls_position}  tip="Retail crowded long = contrarian Fear" />
                  <Bar label="OI momentum"       score={fng.components.oi_momentum}  tip="Rising OI = new interest" />
                </div>
              )}
              {fng.inputs && (
                <div style={{ marginTop: 10, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                  {[
                    { l: '24h Δ',      v: `${fng.inputs.price_change_24h_pct >= 0 ? '+' : ''}${fng.inputs.price_change_24h_pct.toFixed(2)}%`, c: pColor(fng.inputs.price_change_24h_pct) },
                    { l: 'Funding/8h', v: `${fng.inputs.funding_rate_pct.toFixed(4)}%`,  c: undefined as string | undefined },
                    { l: 'OI Δ 24h',   v: `${fng.inputs.oi_change_24h_pct >= 0 ? '+' : ''}${fng.inputs.oi_change_24h_pct.toFixed(2)}%`, c: pColor(fng.inputs.oi_change_24h_pct) },
                    { l: 'Retail L/S', v: fng.inputs.ls_ratio.toFixed(3), c: fng.inputs.ls_ratio > 1.5 ? '#ea3943' : fng.inputs.ls_ratio < 0.8 ? '#16c784' : undefined },
                  ].map(item => (
                    <div key={item.l} style={{ background: 'var(--surface-container, rgba(127,127,127,0.06))', borderRadius: 6, padding: '6px 9px' }}>
                      <div style={{ fontSize: 9, color: 'var(--on-surface-dim)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{item.l}</div>
                      <div style={{ fontSize: 12, fontWeight: 600, fontFamily: 'monospace', color: item.c || 'var(--on-surface)', marginTop: 2 }}>{item.v}</div>
                    </div>
                  ))}
                </div>
              )}
              {fng.computed_at && (
                <div style={{ marginTop: 6, fontSize: 9, color: 'var(--on-surface-dim)', opacity: 0.4 }}>
                  Updated {new Date(fng.computed_at).toLocaleTimeString()}
                </div>
              )}
            </>
          )}
        </div>

        {/* Col 2: Smart Money (new) + Macro Calendar (old) */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, overflow: 'auto', minHeight: 0 }}>
          {/* Smart Money */}
          <div style={{ ...card }}>
            <div style={lbl}>SMART MONEY SIGNAL - {symbol}</div>
            {smartMoneyLoading && !smartMoney && (
              <div style={{ textAlign: 'center', padding: '20px 0', color: 'var(--on-surface-dim)', fontSize: 12 }}>Computing…</div>
            )}
            {smartMoney && !smartMoney.error && smSig && smTop && (
              <>
                <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 14 }}>
                  <ConfRing value={smSig.confidence} color={smSig.color} />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 18, fontWeight: 800, color: smSig.color, lineHeight: 1 }}>{smSig.label}</div>
                    <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
                      <span style={pill(smSig.color)}>{smSig.type.replace(/_/g, ' ')}</span>
                      <span style={pill('#60a5fa')}>{smSig.timeframe}</span>
                      <span style={{ fontSize: 10, color: 'var(--on-surface-dim)', alignSelf: 'center' }}>
                        score {smSig.score > 0 ? '+' : ''}{smSig.score.toFixed(1)}
                      </span>
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: 20, fontWeight: 700, color: smTop.long_pct >= 50 ? '#16c784' : '#ea3943', fontFamily: 'monospace' }}>
                      {smTop.long_pct.toFixed(1)}%
                    </div>
                    <div style={{ fontSize: 9, color: 'var(--on-surface-dim)', letterSpacing: '0.06em' }}>TOP LONG</div>
                    <div style={{ marginTop: 3, height: 4, width: 70, background: 'var(--surface-container-high, rgba(127,127,127,0.10))', borderRadius: 2, overflow: 'hidden' }}>
                      <div style={{ width: `${smTop.long_pct}%`, height: '100%', background: '#16c784', borderRadius: 2 }} />
                    </div>
                  </div>
                </div>
                <div style={{ padding: '9px 12px', background: 'var(--surface-container, rgba(127,127,127,0.05))', borderRadius: 8, marginBottom: 12, borderLeft: `3px solid ${smSig.color}` }}>
                  <div style={{ fontSize: 9, color: 'var(--on-surface-dim)', letterSpacing: '0.07em', textTransform: 'uppercase', marginBottom: 5 }}>AI INSIGHT</div>
                  <div style={{ fontSize: 12, color: 'var(--on-surface)', lineHeight: 1.65 }}>{smSig.ai_insight}</div>
                </div>
                {smDiv?.signal && (
                  <div style={{ padding: '8px 12px', borderRadius: 8, marginBottom: 12, background: smDiv.bias === 'bullish' ? 'rgba(38,166,154,0.08)' : 'rgba(234,57,67,0.08)', border: `1px solid ${smDiv.bias === 'bullish' ? 'rgba(38,166,154,0.25)' : 'rgba(234,57,67,0.25)'}` }}>
                    <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.07em', color: smDiv.bias === 'bullish' ? '#16c784' : '#ea3943', marginBottom: 4 }}>DIVERGENCE SIGNAL</div>
                    <div style={{ fontSize: 11, color: 'var(--on-surface-dim)' }}>
                      {smDiv.type === 'smart_money_long_retail_short'
                        ? 'Smart money LONG / Retail SHORT → historically bullish'
                        : 'Smart money SHORT / Retail LONG → historically bearish'}
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--on-surface-dim)', marginTop: 2, opacity: 0.6 }}>
                      Strength: {smDiv.strength.toFixed(3)}
                    </div>
                  </div>
                )}
                {smartMoney.history && (smartMoney.history.top_trader?.length ?? 0) > 0 && (
                  <div style={{ marginBottom: 12 }}>
                    <div style={{ fontSize: 9, color: 'var(--on-surface-dim)', letterSpacing: '0.07em', textTransform: 'uppercase', marginBottom: 6 }}>L/S RATIO - 24H HISTORY</div>
                    <SmSparkline top={smartMoney.history.top_trader ?? []} retail={smartMoney.history.retail ?? []} />
                  </div>
                )}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 7 }}>
                  {[
                    { l: 'OI vel 6h', v: `${(smartMoney.oi?.velocity_6h_pct ?? 0) >= 0 ? '+' : ''}${(smartMoney.oi?.velocity_6h_pct ?? 0).toFixed(2)}%`, c: pColor(smartMoney.oi?.velocity_6h_pct ?? 0) },
                    { l: 'OI accel',  v: `${(smartMoney.oi?.acceleration_pct ?? 0) >= 0 ? '+' : ''}${(smartMoney.oi?.acceleration_pct ?? 0).toFixed(2)}%`, c: undefined as string | undefined },
                    { l: 'Funding',   v: `${((smartMoney.funding?.rate_pct ?? 0) * 100).toFixed(4)}%`, c: ((smartMoney.funding?.rate_pct ?? 0) > 0 ? '#16c784' : '#ea3943') },
                    { l: 'Top Δ6h',  v: `${smTop.delta_6h >= 0 ? '+' : ''}${smTop.delta_6h.toFixed(3)}`, c: pColor(smTop.delta_6h) },
                  ].map(item => (
                    <div key={item.l} style={{ background: 'var(--surface-container, rgba(127,127,127,0.06))', borderRadius: 6, padding: '6px 9px' }}>
                      <div style={{ fontSize: 9, color: 'var(--on-surface-dim)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{item.l}</div>
                      <div style={{ fontSize: 11, fontWeight: 600, fontFamily: 'monospace', color: item.c || 'var(--on-surface)', marginTop: 2 }}>{item.v}</div>
                    </div>
                  ))}
                </div>
                {smartMoney.computed_at && (
                  <div style={{ marginTop: 8, fontSize: 9, color: 'var(--on-surface-dim)', opacity: 0.4 }}>
                    Updated {new Date(smartMoney.computed_at).toLocaleTimeString()}
                  </div>
                )}
              </>
            )}
            {smartMoney?.error && (
              <div style={{ fontSize: 12, color: '#ea3943', opacity: 0.7 }}>{smartMoney.error}</div>
            )}
          </div>

          {/* Old-style Macro Releases */}
          <div style={{ flex: 1, minHeight: 0 }}>
            <MacroReleasesCard releases={releases} />
          </div>
        </div>

        {/* Col 3: Old-style News Feed */}
        <NewsFeedCard news={newsItems} />
      </div>

      {/* Full brief (if available) */}
      {brief?.brief && !isGenerating && (
        <div style={{ ...card }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <div style={lbl}>AI MARKET BRIEF - {symbol}</div>
            <span style={{ fontSize: 10, color: 'var(--on-surface-dim)', opacity: 0.55 }}>
              {fmtBriefStamp(brief.generated_at)}
            </span>
          </div>
          <div
            style={{
              fontSize: 13,
              color: 'var(--on-surface)',
              maxHeight: 'min(420px, 48vh)',
              overflowY: 'auto',
              overflowX: 'hidden',
              paddingRight: 6,
              scrollbarGutter: 'stable',
            }}
          >
            {renderMd(brief.brief)}
          </div>
        </div>
      )}
    </div>
  )
}