'use client'

import { useEffect, useState, useCallback, useRef } from 'react'
import { renderBriefBody, fmtBriefStamp } from '@/lib/mdRender'

interface Trade {
  id: string; symbol: string; direction: 'LONG' | 'SHORT'
  entry_price: number; exit_price: number; qty: number
  realized_pnl: number; entry_time: number; exit_time: number
  entry_date: string; exit_date: string; duration_min: number
  commission: number; winner: boolean; note: string
}

interface JournalStats {
  total: number; wins: number; losses: number; win_rate: number
  total_pnl: number; total_commission?: number; net_pnl?: number
  long_count?: number; short_count?: number
  long_win_rate?: number; short_win_rate?: number
  avg_win: number; avg_loss: number; rr_ratio: number
  best_pair: string; worst_pair: string
  current_streak: number; current_streak_type: 'win' | 'loss' | 'none'
  max_drawdown: number; avg_duration_min: number
  by_symbol: Record<string, number>
}

interface Analysis {
  analysis: string | null; trade_count?: number
  generated_at?: string; model?: string; message?: string
}

interface OpenPosition {
  symbol: string; side: 'LONG' | 'SHORT'; qty: number
  entry_price: number; notional_usd: number
  unrealized_pnl: number; leverage: number; margin_used: number
}

interface Portfolio {
  futures_wallet: number; futures_unrealized: number
  futures_available: number; futures_margin_used: number; futures_margin_pct: number
  spot_balance: number; funding_balance: number
  total_balance: number; total_unrealized: number
  open_positions: OpenPosition[]; open_position_count: number; fetched_at: string
}

interface Props { api: string }

const fmt = (n: number, d = 2) => Number(n ?? 0).toFixed(d)
const fmtPnl = (n: number) => `${n >= 0 ? '+' : ''}${fmt(n, 4)}`
const pnlColor = (n: number) => n > 0 ? '#16c784' : n < 0 ? '#ea3943' : 'var(--on-surface-dim)'

function renderMarkdownBody(raw: string): React.ReactNode {
  // Delegate to shared renderer - strips #, **, --- and normalises bullets.
  return renderBriefBody(raw)
}

function parseSections(text: string): { title: string; body: string }[] {
  if (!text) return []
  const sections: { title: string; body: string }[] = []
  const lines = text.split('\n')
  let cur: { title: string; body: string } | null = null
  for (const line of lines) {
    const m = line.match(/^\*{1,2}([A-Z][A-Z0-9\s\/]+(?::)?)\*{0,2}$/) ||
              line.match(/^#{1,3}\s+(.+)$/) ||
              line.match(/^([A-Z][A-Z\s]+):$/)
    const title = m?.[1]?.replace(/[:*#]/g, '').trim()
    if (title && title.length > 3 && title.length < 70 && title === title.toUpperCase()) {
      if (cur) sections.push(cur)
      cur = { title, body: '' }
    } else if (cur) {
      cur.body += line + '\n'
    }
  }
  if (cur?.body.trim()) sections.push(cur)
  if (!sections.length && text.trim()) return [{ title: 'ANALYSIS', body: text }]
  return sections.filter(s => s.body.trim())
}

interface DayData { pnl: number; trades: number; wins: number; tradeList: Trade[] }

function buildCalData(trades: Trade[]): Record<string, DayData> {
  const map: Record<string, DayData> = {}
  for (const t of trades) {
    // exit_time is UTC ms. Convert to local calendar day so PH trades on Apr 28
    // (PHT = UTC+8) don't fall on Apr 27 due to UTC date slicing.
    const localDate = new Date(t.exit_time)
    const d = `${localDate.getFullYear()}-${String(localDate.getMonth() + 1).padStart(2, '0')}-${String(localDate.getDate()).padStart(2, '0')}`
    if (!map[d]) map[d] = { pnl: 0, trades: 0, wins: 0, tradeList: [] }
    map[d].pnl += t.realized_pnl; map[d].trades++
    if (t.winner) map[d].wins++; map[d].tradeList.push(t)
  }
  return map
}

function KpiCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div style={{ background: 'var(--surface-container, rgba(127,127,127,0.04))', border: '1px solid var(--hairline)', borderRadius: 10, padding: '14px 16px' }}>
      <div style={{ fontSize: 10, color: 'var(--on-surface-dim)', letterSpacing: '0.07em', textTransform: 'uppercase', marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 600, color: color || 'var(--on-surface)', lineHeight: 1.1, fontFamily: 'monospace' }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: 'var(--on-surface-dim)', marginTop: 4 }}>{sub}</div>}
    </div>
  )
}

function EquityCurve({ trades }: { trades: Trade[] }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const c = ref.current; if (!c || !trades.length) return
    const ctx = c.getContext('2d'); if (!ctx) return
    const pts: number[] = []; let eq = 0
    for (const t of [...trades].sort((a, b) => a.exit_time - b.exit_time)) { eq += t.realized_pnl; pts.push(eq) }
    const W = c.width, H = c.height, mn = Math.min(0, ...pts), mx = Math.max(0, ...pts)
    const rng = mx - mn || 1, pad = 12
    const toY = (v: number) => H - pad - ((v - mn) / rng) * (H - 2 * pad)
    ctx.clearRect(0, 0, W, H)
    ctx.strokeStyle = 'var(--surface-container-high, rgba(127,127,127,0.10))'; ctx.lineWidth = 1; ctx.setLineDash([3, 4])
    ctx.beginPath(); ctx.moveTo(pad, toY(0)); ctx.lineTo(W - pad, toY(0)); ctx.stroke()
    ctx.setLineDash([])
    const fin = pts[pts.length - 1] ?? 0, lc = fin >= 0 ? '#16c784' : '#ea3943'
    ctx.strokeStyle = lc; ctx.lineWidth = 1.5; ctx.beginPath()
    pts.forEach((v, i) => {
      const x = pad + (i / Math.max(pts.length - 1, 1)) * (W - 2 * pad)
      if (i === 0) ctx.moveTo(x, toY(v)); else ctx.lineTo(x, toY(v))
    })
    ctx.stroke()
    ctx.lineTo(pad + (W - 2 * pad), toY(0)); ctx.lineTo(pad, toY(0)); ctx.closePath()
    ctx.fillStyle = fin >= 0 ? 'rgba(22,199,132,0.08)' : 'rgba(234,57,67,0.08)'; ctx.fill()
  }, [trades])
  return <canvas ref={ref} width={480} height={90} style={{ width: '100%', height: 90, display: 'block' }} />
}

function TradeCalendar({ trades }: { trades: Trade[] }) {
  const today = new Date()
  const [year, setYear] = useState(today.getFullYear())
  const [month, setMonth] = useState(today.getMonth())
  const [hovered, setHovered] = useState<string | null>(null)
  const calData = buildCalData(trades)
  const dim = new Date(year, month + 1, 0).getDate()
  const fdow = new Date(year, month, 1).getDay()
  const mName = new Date(year, month, 1).toLocaleString('default', { month: 'long' })
  const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
  const mKeys = Object.keys(calData).filter(k => { const d = new Date(k); return d.getFullYear() === year && d.getMonth() === month })
  const mPnl = mKeys.reduce((s, k) => s + calData[k].pnl, 0)
  const mTrades = mKeys.reduce((s, k) => s + calData[k].trades, 0)
  const mWins = mKeys.reduce((s, k) => s + calData[k].wins, 0)
  const activeDays = mKeys.filter(k => calData[k].trades > 0).length
  const weeks: number[][] = []; let wk: number[] = Array(fdow).fill(0)
  for (let d = 1; d <= dim; d++) { wk.push(d); if (wk.length === 7) { weeks.push(wk); wk = [] } }
  if (wk.length) { while (wk.length < 7) wk.push(0); weeks.push(wk) }
  const prevM = () => { let m = month - 1, y = year; if (m < 0) { m = 11; y-- } setMonth(m); setYear(y) }
  const nextM = () => { let m = month + 1, y = year; if (m > 11) { m = 0; y++ } setMonth(m); setYear(y) }
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <button onClick={prevM} style={{ background: 'none', border: '1px solid var(--hairline)', borderRadius: 6, color: 'var(--on-surface-dim)', padding: '4px 12px', cursor: 'pointer', fontSize: 14 }}>‹</button>
          <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--on-surface)', minWidth: 140, textAlign: 'center' }}>{mName} {year}</span>
          <button onClick={nextM} style={{ background: 'none', border: '1px solid var(--hairline)', borderRadius: 6, color: 'var(--on-surface-dim)', padding: '4px 12px', cursor: 'pointer', fontSize: 14 }}>›</button>
        </div>
        <div style={{ display: 'flex', gap: 8, fontSize: 11 }}>
          <span style={{ padding: '3px 12px', borderRadius: 20, background: mPnl >= 0 ? 'rgba(22,199,132,0.15)' : 'rgba(234,57,67,0.15)', color: mPnl >= 0 ? '#16c784' : '#ea3943', fontWeight: 700, fontFamily: 'monospace' }}>
            {mPnl >= 0 ? '+' : ''}{fmt(mPnl, 2)} USDT
          </span>
          <span style={{ padding: '3px 12px', borderRadius: 20, background: 'var(--surface-container, rgba(127,127,127,0.08))', color: 'var(--on-surface-dim)' }}>
            {mTrades} trades · {activeDays}d · {mTrades > 0 ? Math.round(mWins / mTrades * 100) : 0}% WR
          </span>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr) 76px', gap: 3, marginBottom: 3 }}>
        {DOW.map(d => <div key={d} style={{ fontSize: 10, color: 'var(--on-surface-dim)', textAlign: 'center', padding: '4px 0', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{d}</div>)}
        <div style={{ fontSize: 10, color: 'var(--on-surface-dim)', textAlign: 'center', padding: '4px 0', letterSpacing: '0.06em' }}>WK</div>
      </div>
      {weeks.map((wk, wi) => {
        const wPnl = wk.filter(d => d > 0).reduce((s, d) => {
          const k = `${year}-${String(month + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`
          return s + (calData[k]?.pnl ?? 0)
        }, 0)
        const wTrades = wk.filter(d => d > 0).reduce((s, d) => {
          const k = `${year}-${String(month + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`
          return s + (calData[k]?.trades ?? 0)
        }, 0)
        return (
          <div key={wi} style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr) 76px', gap: 3, marginBottom: 3 }}>
            {wk.map((day, di) => {
              if (!day) return <div key={di} style={{ minHeight: 72, borderRadius: 7, background: 'var(--surface-container, rgba(127,127,127,0.02))' }} />
              const k = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
              const data = calData[k]
              const isToday = k === today.toISOString().slice(0, 10)
              const isHov = hovered === k
              return (
                <div key={di} onMouseEnter={() => setHovered(k)} onMouseLeave={() => setHovered(null)}
                  style={{ minHeight: 72, borderRadius: 7, padding: '6px 8px', position: 'relative', cursor: data ? 'pointer' : 'default', transition: 'border 0.12s',
                    background: data ? data.pnl >= 0 ? `rgba(22,199,132,${Math.min(0.04 + Math.abs(data.pnl) * 0.004, 0.2)})` : `rgba(234,57,67,${Math.min(0.04 + Math.abs(data.pnl) * 0.004, 0.2)})` : 'var(--surface-container, rgba(127,127,127,0.04))',
                    border: isToday ? '1.5px solid var(--on-surface-dim)' : isHov && data ? '1px solid var(--on-surface-variant)' : '1px solid var(--hairline)',
                  }}>
                  <div style={{ fontSize: 11, color: isToday ? 'var(--primary)' : 'var(--on-surface-dim)', fontWeight: isToday ? 700 : 400, marginBottom: 4 }}>{day}</div>
                  {data && <>
                    <div style={{ fontSize: 13, fontWeight: 700, color: pnlColor(data.pnl), fontFamily: 'monospace', lineHeight: 1.1 }}>
                      {data.pnl >= 0 ? '+' : ''}{fmt(data.pnl, 2)}
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--on-surface-dim)', marginTop: 3 }}>{data.trades}t · {data.wins}W</div>
                  </>}
                  {isHov && data && (
                    <div style={{ position: 'absolute', top: 'calc(100% + 4px)', left: '50%', transform: 'translateX(-50%)', zIndex: 100,
                      background: 'var(--surface-container-high, #1a1a1e)', border: '1px solid var(--hairline)', borderRadius: 9, padding: '10px 13px',
                      minWidth: 176, pointerEvents: 'none', boxShadow: '0 8px 32px rgba(0,0,0,0.35)' }}>
                      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--on-surface)', marginBottom: 7 }}>{mName} {day}</div>
                      {data.tradeList.slice(0, 6).map((t, i) => (
                        <div key={i} style={{ display: 'flex', justifyContent: 'space-between', gap: 14, fontSize: 11, marginBottom: 4 }}>
                          <span style={{ color: 'var(--on-surface-dim)' }}>{t.symbol.replace('USDT', '')}</span>
                          <span style={{ color: pnlColor(t.realized_pnl), fontFamily: 'monospace', fontWeight: 600 }}>{fmtPnl(t.realized_pnl)}</span>
                        </div>
                      ))}
                      {data.tradeList.length > 6 && <div style={{ fontSize: 10, color: 'var(--on-surface-dim)', marginTop: 3, opacity: 0.6 }}>+{data.tradeList.length - 6} more</div>}
                    </div>
                  )}
                </div>
              )
            })}
            <div style={{ minHeight: 72, borderRadius: 7, padding: '6px 8px', background: 'var(--surface-container, rgba(127,127,127,0.03))', border: '1px solid var(--hairline)', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: pnlColor(wPnl), fontFamily: 'monospace' }}>{wPnl >= 0 ? '+' : ''}{fmt(wPnl, 2)}</div>
              {wTrades > 0 && <div style={{ fontSize: 10, color: 'var(--on-surface-dim)', marginTop: 2 }}>{wTrades}t</div>}
            </div>
          </div>
        )
      })}
    </div>
  )
}

const SMETA: Record<string, { color: string; icon: string }> = {
  'TRADING STYLE ASSESSMENT': { color: '#60a5fa', icon: '◈' },
  'EDGE ANALYSIS':            { color: '#34d399', icon: '◎' },
  'EDGE BREAKDOWN':           { color: '#34d399', icon: '◎' },
  'RISK MANAGEMENT':          { color: '#c6c6c7', icon: '⬡' },
  'RISK MANAGEMENT REVIEW':   { color: '#c6c6c7', icon: '⬡' },
  'RISK MANAGEMENT SCORE':    { color: '#c6c6c7', icon: '⬡' },
  'BEHAVIOURAL PATTERNS':     { color: '#f472b6', icon: '◉' },
  'TOP 3 IMPROVEMENTS':       { color: '#a78bfa', icon: '▲' },
  'SUMMARY VERDICT':          { color: '#16c784', icon: '◆' },
  'OVERALL ASSESSMENT':       { color: '#16c784', icon: '◆' },
  'ANALYSIS':                 { color: 'var(--primary)', icon: '◈' },
}

function AnalysisPanel({ analysis, loading, onGenerate }: { analysis: Analysis | null; loading: boolean; onGenerate: () => void }) {
  if (loading) return (
    <div style={{ padding: '60px 0', textAlign: 'center' }}>
      <div style={{ fontSize: 13, color: 'var(--on-surface)', fontWeight: 500, marginBottom: 8 }}>Synthesizing trade history…</div>
      <div style={{ fontSize: 11, color: 'var(--on-surface-dim)', marginBottom: 4 }}>Auto-detecting Ollama model · same pipeline as AI Brief</div>
      <div style={{ fontSize: 10, color: 'var(--on-surface-dim)', opacity: 0.45, marginBottom: 24 }}>30-90s · ensure ollama serve is running</div>
      <div style={{ display: 'flex', justifyContent: 'center', gap: 6 }}>
        {[0, 1, 2].map(i => <div key={i} style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--primary)', animation: `pulse 1.2s ease-in-out ${i * 0.22}s infinite` }} />)}
      </div>
      <style>{`@keyframes pulse{0%,100%{opacity:.12}50%{opacity:1}}`}</style>
    </div>
  )
  if (!analysis?.analysis) return (
    <div style={{ padding: '60px 24px', textAlign: 'center', maxWidth: 440, margin: '0 auto' }}>
      <div style={{ width: 44, height: 44, borderRadius: '50%', background: 'var(--surface-container, rgba(127,127,127,0.06))', border: '1px solid var(--hairline)', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 14px', fontSize: 18, color: 'var(--on-surface-variant)' }}>◈</div>
      <div style={{ fontSize: 14, color: 'var(--on-surface)', fontWeight: 500, marginBottom: 8 }}>AI Journal Analysis</div>
      <div style={{ fontSize: 12, color: 'var(--on-surface-dim)', lineHeight: 1.7, marginBottom: 26 }}>
        Local Gemma analysis of your trading history. Covers: trading style · edge by pair &amp; direction · risk management score · behavioural patterns · top 3 improvements.
      </div>
      <button onClick={onGenerate} style={{ padding: '10px 28px', background: 'var(--primary)', color: 'var(--on-primary, #000)', border: 'none', borderRadius: 8, fontSize: 11, fontWeight: 700, cursor: 'pointer', letterSpacing: '0.07em', fontFamily: 'inherit' }}>
        ANALYZE WITH LOCAL AI
      </button>
    </div>
  )
  const sections = parseSections(analysis.analysis)
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 18 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 11 }}>
          <span style={{ background: 'var(--surface-container, rgba(127,127,127,0.08))', border: '1px solid var(--hairline)', borderRadius: 5, padding: '3px 9px', color: 'var(--primary)', fontWeight: 600 }}>{analysis.model?.toUpperCase() || 'LOCAL AI'}</span>
          <span style={{ color: 'var(--on-surface-dim)' }}>· {analysis.trade_count} trades · {fmtBriefStamp(analysis.generated_at)}</span>
        </div>
        <button onClick={onGenerate} style={{ padding: '5px 14px', background: 'transparent', color: 'var(--on-surface-variant)', border: '1px solid var(--hairline)', borderRadius: 5, fontSize: 10, cursor: 'pointer', letterSpacing: '0.05em', fontFamily: 'inherit' }}>REFRESH</button>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {sections.map((sec, i) => {
          const meta = SMETA[sec.title] || SMETA['ANALYSIS']
          return (
            <div key={i} style={{ background: 'var(--surface-container, rgba(127,127,127,0.04))', border: '1px solid var(--hairline)', borderLeft: `3px solid ${meta.color}`, borderRadius: '0 10px 10px 0', padding: '14px 16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 10 }}>
                <span style={{ color: meta.color, fontSize: 12 }}>{meta.icon}</span>
                <span style={{ fontSize: 10, fontWeight: 700, color: meta.color, letterSpacing: '0.09em', textTransform: 'uppercase' }}>{sec.title}</span>
              </div>
              <div style={{ fontSize: 12, color: 'var(--on-surface)', lineHeight: 1.75 }}>
                {renderMarkdownBody(sec.body)}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

type Panel = 'calendar' | 'trades' | 'stats' | 'portfolio' | 'analysis'

export default function TradingJournalTab({ api }: Props) {
  const [trades, setTrades]   = useState<Trade[]>([])
  const [stats, setStats]     = useState<JournalStats | null>(null)
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null)
  const [loading, setLoading] = useState(true)
  const [analysisLoading, setAnalysisLoading] = useState(false)
  const [portfolioLoading, setPortfolioLoading] = useState(false)
  const [error, setError]     = useState<string | null>(null)
  const [noKeys, setNoKeys]   = useState(false)
  const [panel, setPanel]     = useState<Panel>('calendar')
  const [filter, setFilter]   = useState<'all' | 'win' | 'loss'>('all')
  const [sortBy, setSortBy]   = useState<'date' | 'pnl' | 'duration'>('date')
  const [symFilter, setSymFilter] = useState('ALL')
  const [editNote, setEditNote] = useState<{ id: string; text: string } | null>(null)
  const [page, setPage]       = useState(0)
  const PAGE_SIZE = 30

  const [fetchedAt, setFetchedAt] = useState<Date | null>(null)
  const [dataSource, setDataSource] = useState<string>('')

  const fetchTrades = useCallback(async (force = false) => {
    setLoading(true); setError(null)
    try {
      const [tRes, sRes] = await Promise.all([
        fetch(`${api}/api/journal/trades${force ? '?force_refresh=true' : ''}`),
        fetch(`${api}/api/journal/stats`),
      ])
      const td = await tRes.json(); const sd = await sRes.json()
      if (td.source === 'no_keys') { setNoKeys(true); setTrades([]) }
      else if (td.source === 'auth_error') { setError(td.error || 'Auth failed'); setTrades([]) }
      else if (td.error) { setError(td.error); setTrades(td.trades || []) }
      else { setNoKeys(false); setTrades(td.trades || []) }
      if (sd.stats?.total > 0) setStats(sd.stats)
      // Track freshness so user can see when data is stale
      if (td.fetched_at) setFetchedAt(new Date(td.fetched_at))
      else setFetchedAt(new Date())
      setDataSource(td.source || '')
    } catch { setError('Cannot reach backend on port 8001') }
    finally { setLoading(false) }
  }, [api])

  const fetchAnalysis = useCallback(async () => {
    try { const r = await fetch(`${api}/api/journal/last-analysis`); const d = await r.json(); if (d.analysis) setAnalysis(d) } catch {}
  }, [api])

  const fetchPortfolio = useCallback(async () => {
    setPortfolioLoading(true)
    try { const r = await fetch(`${api}/api/journal/portfolio`); const d = await r.json(); if (d.portfolio) setPortfolio(d.portfolio) } catch {}
    finally { setPortfolioLoading(false) }
  }, [api])

  useEffect(() => {
    void fetchTrades(); void fetchAnalysis(); void fetchPortfolio()
    // Trades: auto-refresh every 2 min so fills from new sessions appear without manual refresh
    const tradeIv = setInterval(() => void fetchTrades(), 2 * 60 * 1000)
    // Portfolio: every 30s (live balance / open positions)
    const portIv  = setInterval(() => void fetchPortfolio(), 30_000)
    return () => { clearInterval(tradeIv); clearInterval(portIv) }
  }, [fetchTrades, fetchAnalysis, fetchPortfolio])

  const runAnalysis = async () => {
    setAnalysisLoading(true); setPanel('analysis')
    try { const r = await fetch(`${api}/api/journal/analyze`, { method: 'POST' }); setAnalysis(await r.json()) }
    catch { setAnalysis({ analysis: '[Analysis failed - is Ollama running?]' }) }
    finally { setAnalysisLoading(false) }
  }

  const saveNote = async (id: string, note: string) => {
    try {
      await fetch(`${api}/api/journal/note/${id}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ note }) })
      setTrades(p => p.map(t => t.id === id ? { ...t, note } : t))
    } catch {}
    setEditNote(null)
  }

  const symbols = ['ALL', ...Array.from(new Set(trades.map(t => t.symbol)))]
  const filtered = trades
    .filter(t => filter === 'all' || (filter === 'win' ? t.winner : !t.winner))
    .filter(t => symFilter === 'ALL' || t.symbol === symFilter)
    .sort((a, b) => sortBy === 'pnl' ? b.realized_pnl - a.realized_pnl : sortBy === 'duration' ? b.duration_min - a.duration_min : b.exit_time - a.exit_time)
  const paginated = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
  const totalPages = Math.ceil(filtered.length / PAGE_SIZE)
  const PANELS: { id: Panel; label: string }[] = [
    { id: 'calendar', label: 'CALENDAR' }, { id: 'trades', label: 'TRADES' },
    { id: 'stats', label: 'STATS' }, { id: 'portfolio', label: 'PORTFOLIO' },
    { id: 'analysis', label: 'ANALYSIS' },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--surface, #0d0d0f)' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 20px', borderBottom: '1px solid var(--hairline)', flexShrink: 0, gap: 16 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--on-surface)', letterSpacing: '0.05em' }}>TRADING JOURNAL</div>
          <div style={{ fontSize: 11, color: 'var(--on-surface-dim)', marginTop: 2 }}>Binance USDT-M Futures · from 2026-04-18</div>
        </div>
        {/* Portfolio strip */}
        <div style={{ flex: 1, display: 'flex', gap: 20, justifyContent: 'center', alignItems: 'center' }}>
          {portfolio ? (
            <>
              {[
                { label: 'Total Balance', val: `${fmt(portfolio.total_balance, 2)} USDT`, color: undefined as string | undefined },
                { label: 'Futures Wallet', val: fmt(portfolio.futures_wallet, 2), color: undefined },
                ...(portfolio.spot_balance > 0 ? [{ label: 'Spot', val: fmt(portfolio.spot_balance, 2), color: undefined }] : []),
                ...(portfolio.funding_balance > 0 ? [{ label: 'Funding', val: fmt(portfolio.funding_balance, 2), color: undefined }] : []),
                { label: 'Unrealized', val: `${portfolio.total_unrealized >= 0 ? '+' : ''}${fmt(portfolio.total_unrealized, 4)}`, color: pnlColor(portfolio.total_unrealized) },
                { label: 'Net PnL', val: `${(stats?.net_pnl ?? stats?.total_pnl ?? 0) >= 0 ? '+' : ''}${fmt(stats?.net_pnl ?? stats?.total_pnl ?? 0, 2)}`, color: pnlColor(stats?.net_pnl ?? stats?.total_pnl ?? 0) },
              ].map((item, i, arr) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: 9, color: 'var(--on-surface-dim)', letterSpacing: '0.07em', textTransform: 'uppercase' }}>{item.label}</div>
                    <div style={{ fontSize: i === 0 ? 15 : 13, fontWeight: i === 0 ? 700 : 600, color: item.color || 'var(--on-surface)', fontFamily: 'monospace' }}>{item.val}</div>
                  </div>
                  {i < arr.length - 1 && <div style={{ width: 1, height: 26, background: 'var(--hairline)' }} />}
                </div>
              ))}
            </>
          ) : (
            <span style={{ fontSize: 11, color: 'var(--on-surface-dim)', opacity: 0.4 }}>
              {portfolioLoading ? 'Loading portfolio…' : noKeys ? 'Add API keys to see portfolio' : '-'}
            </span>
          )}
        </div>
        <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
          <button onClick={() => void runAnalysis()} disabled={analysisLoading || trades.length === 0}
            style={{ padding: '7px 16px', background: 'var(--primary)', color: '#000', border: 'none', borderRadius: 7, fontSize: 10, fontWeight: 700, cursor: trades.length === 0 ? 'not-allowed' : 'pointer', letterSpacing: '0.06em', opacity: trades.length === 0 ? 0.4 : 1 }}>
            {analysisLoading ? 'ANALYZING…' : 'AI ANALYSE'}
          </button>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2 }}>
            <button onClick={() => void fetchTrades(true)} title="Force-refresh from Binance"
              style={{ padding: '7px 11px', background: 'transparent', color: 'var(--on-surface-dim)', border: '1px solid var(--hairline)', borderRadius: 7, fontSize: 16, cursor: 'pointer', lineHeight: 1 }}>
              {loading ? '⟳' : '↻'}
            </button>
            {fetchedAt && (
              <span style={{ fontSize: 9, color: (() => { const ageMin = (Date.now() - fetchedAt.getTime()) / 60000; return ageMin > 5 ? '#c6c6c7' : 'var(--on-surface-muted)' })(), letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>
                {dataSource === 'cache' ? 'cached · ' : ''}
                {(() => { const ageMin = Math.floor((Date.now() - fetchedAt.getTime()) / 60000); return ageMin < 1 ? 'just now' : `${ageMin}m ago` })()}
              </span>
            )}
          </div>
        </div>
      </div>
      {/* Tabs */}
      <div style={{ display: 'flex', borderBottom: '1px solid var(--hairline)', padding: '0 20px', flexShrink: 0 }}>
        {PANELS.map(p => (
          <button key={p.id} onClick={() => setPanel(p.id)} style={{ padding: '10px 18px', background: 'transparent', border: 'none', borderBottom: `2px solid ${panel === p.id ? 'var(--primary)' : 'transparent'}`, color: panel === p.id ? 'var(--primary)' : 'var(--on-surface-dim)', fontSize: 10, fontWeight: panel === p.id ? 700 : 400, cursor: 'pointer', letterSpacing: '0.07em', marginBottom: -1, display: 'flex', alignItems: 'center', gap: 5 }}>
            {p.label}
            {p.id === 'analysis' && analysis?.analysis && <span style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--primary)' }} />}
            {p.id === 'portfolio' && portfolio && <span style={{ width: 5, height: 5, borderRadius: '50%', background: pnlColor(portfolio.total_unrealized) }} />}
          </button>
        ))}
      </div>
      {/* Body */}
      <div style={{ flex: 1, overflow: 'auto', padding: 20 }}>
        {loading && <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--on-surface-dim)', fontSize: 12 }}>Loading trade history…</div>}
        {!loading && error && (
          <div style={{ padding: 16, background: 'rgba(234,57,67,0.07)', border: '1px solid rgba(234,57,67,0.2)', borderRadius: 9 }}>
            <div style={{ fontSize: 12, color: '#ea3943', marginBottom: 8 }}>{error}</div>
            <a href={`${api}/api/journal/debug`} target="_blank" rel="noreferrer" style={{ fontSize: 11, color: 'var(--primary)' }}>/api/journal/debug ↗</a>
          </div>
        )}
        {!loading && noKeys && (
          <div style={{ background: 'var(--surface-container, rgba(127,127,127,0.04))', border: '1px solid var(--hairline)', borderRadius: 12, padding: '32px 28px', maxWidth: 500, margin: '0 auto' }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--on-surface)', marginBottom: 10 }}>Connect Binance API</div>
            <div style={{ fontSize: 12, color: 'var(--on-surface-dim)', lineHeight: 1.7, marginBottom: 16 }}>Add a read-only Futures API key to <code style={{ background: 'var(--surface-container-high, rgba(127,127,127,0.10))', padding: '1px 5px', borderRadius: 3 }}>backend/.env</code></div>
            <div style={{ background: 'rgba(0,0,0,0.3)', borderRadius: 8, padding: '12px 16px', fontFamily: 'monospace', fontSize: 12, color: '#a6e3a1', lineHeight: 1.9 }}>
              BINANCE_API_KEY=your_read_only_key<br />BINANCE_API_SECRET=your_read_only_secret
            </div>
          </div>
        )}
        {!loading && !error && !noKeys && panel === 'calendar' && <TradeCalendar trades={trades} />}
        {!loading && !error && !noKeys && panel === 'trades' && (
          <div>
            <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap', alignItems: 'center' }}>
              <div style={{ display: 'flex', background: 'var(--hairline)', borderRadius: 7, overflow: 'hidden', border: '1px solid var(--hairline)' }}>
                {(['all', 'win', 'loss'] as const).map(f => (
                  <button key={f} onClick={() => { setFilter(f); setPage(0) }} style={{ padding: '5px 14px', background: filter === f ? 'var(--primary)' : 'transparent', color: filter === f ? '#000' : 'var(--on-surface-dim)', border: 'none', fontSize: 10, fontWeight: filter === f ? 700 : 400, cursor: 'pointer', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{f}</button>
                ))}
              </div>
              <select value={symFilter} onChange={e => { setSymFilter(e.target.value); setPage(0) }} style={{ padding: '5px 10px', background: 'var(--hairline)', border: '1px solid var(--hairline)', borderRadius: 7, color: 'var(--on-surface-dim)', fontSize: 11, cursor: 'pointer' }}>
                {symbols.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
              <select value={sortBy} onChange={e => setSortBy(e.target.value as typeof sortBy)} style={{ padding: '5px 10px', background: 'var(--hairline)', border: '1px solid var(--hairline)', borderRadius: 7, color: 'var(--on-surface-dim)', fontSize: 11, cursor: 'pointer' }}>
                <option value="date">Sort: Date</option><option value="pnl">Sort: PnL</option><option value="duration">Sort: Duration</option>
              </select>
              <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--on-surface-dim)' }}>{filtered.length} trades</span>
            </div>
            {trades.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '48px 0', color: 'var(--on-surface-dim)', fontSize: 12 }}>No closed trades since 2026-04-18.</div>
            ) : (
              <>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                    <thead>
                      <tr style={{ background: 'var(--surface-container, rgba(127,127,127,0.04))', borderBottom: '1px solid var(--hairline)' }}>
                        {['Symbol', 'Dir', 'Entry', 'Exit', 'PnL', 'Qty', 'Duration', 'Commission', 'Date', 'Note'].map(h => (
                          <th key={h} style={{ padding: '9px 10px', textAlign: 'left', color: 'var(--on-surface-dim)', fontSize: 10, fontWeight: 500, letterSpacing: '0.06em', textTransform: 'uppercase', whiteSpace: 'nowrap' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {paginated.map(t => (
                        <tr key={t.id} style={{ borderBottom: '1px solid var(--hairline)', background: t.winner ? 'rgba(22,199,132,0.025)' : 'rgba(234,57,67,0.025)' }}>
                          <td style={{ padding: '9px 10px', fontWeight: 600, fontFamily: 'monospace', fontSize: 11 }}>{t.symbol.replace('USDT', '')}</td>
                          <td style={{ padding: '9px 10px' }}><span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 600, background: t.direction === 'LONG' ? 'rgba(22,199,132,0.18)' : 'rgba(234,57,67,0.18)', color: t.direction === 'LONG' ? '#16c784' : '#ea3943' }}>{t.direction}</span></td>
                          <td style={{ padding: '9px 10px', fontFamily: 'monospace', fontSize: 11 }}>{fmt(t.entry_price, 4)}</td>
                          <td style={{ padding: '9px 10px', fontFamily: 'monospace', fontSize: 11 }}>{fmt(t.exit_price, 4)}</td>
                          <td style={{ padding: '9px 10px', fontFamily: 'monospace', fontSize: 11, color: pnlColor(t.realized_pnl), fontWeight: 600 }}>{fmtPnl(t.realized_pnl)}</td>
                          <td style={{ padding: '9px 10px', fontFamily: 'monospace', fontSize: 11, color: 'var(--on-surface-dim)' }}>{t.qty}</td>
                          <td style={{ padding: '9px 10px', fontSize: 11, color: 'var(--on-surface-dim)' }}>{t.duration_min < 60 ? `${t.duration_min}m` : `${(t.duration_min / 60).toFixed(1)}h`}</td>
                          <td style={{ padding: '9px 10px', fontFamily: 'monospace', fontSize: 11, color: 'var(--on-surface-dim)' }}>-{fmt(t.commission, 4)}</td>
                          <td style={{ padding: '9px 10px', fontSize: 11, color: 'var(--on-surface-dim)', whiteSpace: 'nowrap' }}>{t.exit_date}</td>
                          <td style={{ padding: '9px 10px', maxWidth: 180 }}>
                            {editNote?.id === t.id ? (
                              <input autoFocus value={editNote.text} onChange={e => setEditNote({ id: t.id, text: e.target.value })}
                                onKeyDown={e => { if (e.key === 'Enter') void saveNote(t.id, editNote.text); if (e.key === 'Escape') setEditNote(null) }}
                                style={{ width: '100%', background: 'var(--surface-container, rgba(127,127,127,0.08))', border: '1px solid var(--primary)', borderRadius: 4, padding: '3px 7px', color: 'var(--on-surface)', fontSize: 11, outline: 'none' }} placeholder="Enter · Esc" />
                            ) : (
                              <button onClick={() => setEditNote({ id: t.id, text: t.note || '' })} style={{ background: 'transparent', border: 'none', color: t.note ? 'var(--on-surface)' : 'var(--on-surface-dim)', fontSize: 11, cursor: 'pointer', padding: 0, opacity: t.note ? 1 : 0.35, maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block', textAlign: 'left' }} title="Click to add note">{t.note || '+ note'}</button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {totalPages > 1 && (
                  <div style={{ display: 'flex', justifyContent: 'center', gap: 8, marginTop: 16 }}>
                    <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0} style={{ padding: '5px 14px', background: 'var(--hairline)', border: '1px solid var(--hairline)', borderRadius: 6, color: 'var(--on-surface-dim)', fontSize: 11, cursor: page === 0 ? 'not-allowed' : 'pointer' }}>← Prev</button>
                    <span style={{ padding: '5px 12px', fontSize: 11, color: 'var(--on-surface-dim)' }}>{page + 1} / {totalPages}</span>
                    <button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1} style={{ padding: '5px 14px', background: 'var(--hairline)', border: '1px solid var(--hairline)', borderRadius: 6, color: 'var(--on-surface-dim)', fontSize: 11, cursor: page >= totalPages - 1 ? 'not-allowed' : 'pointer' }}>Next →</button>
                  </div>
                )}
              </>
            )}
          </div>
        )}
        {!loading && !error && !noKeys && panel === 'stats' && stats && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
              <KpiCard label="Total Trades" value={String(stats.total)} />
              <KpiCard label="Win Rate" value={`${stats.win_rate}%`} sub={`${stats.wins}W / ${stats.losses}L`} color={stats.win_rate >= 50 ? '#16c784' : '#ea3943'} />
              <KpiCard label="Gross PnL" value={`${stats.total_pnl >= 0 ? '+' : ''}${fmt(stats.total_pnl, 2)}`} sub="USDT" color={pnlColor(stats.total_pnl)} />
              <KpiCard label="Net PnL" value={`${(stats.net_pnl ?? stats.total_pnl) >= 0 ? '+' : ''}${fmt(stats.net_pnl ?? stats.total_pnl, 2)}`} sub={`-${fmt(stats.total_commission ?? 0, 4)} fees`} color={pnlColor(stats.net_pnl ?? stats.total_pnl)} />
              <KpiCard label="Reward/Risk" value={`${fmt(stats.rr_ratio, 2)}×`} color={stats.rr_ratio >= 1.5 ? '#16c784' : stats.rr_ratio >= 1 ? 'var(--primary)' : '#ea3943'} />
              <KpiCard label="Avg Win" value={`+${fmt(stats.avg_win, 4)}`} color="#16c784" />
              <KpiCard label="Avg Loss" value={fmt(stats.avg_loss, 4)} color="#ea3943" />
              <KpiCard label="Max Drawdown" value={`-${fmt(stats.max_drawdown, 4)}`} color="#ea3943" />
              <KpiCard label="Long Trades" value={String(stats.long_count ?? 0)} sub={`${stats.long_win_rate ?? 0}% WR`} color={(stats.long_win_rate ?? 0) >= 50 ? '#16c784' : '#ea3943'} />
              <KpiCard label="Short Trades" value={String(stats.short_count ?? 0)} sub={`${stats.short_win_rate ?? 0}% WR`} color={(stats.short_win_rate ?? 0) >= 50 ? '#16c784' : '#ea3943'} />
              <KpiCard label="Avg Duration" value={stats.avg_duration_min < 60 ? `${fmt(stats.avg_duration_min, 0)}m` : `${(stats.avg_duration_min / 60).toFixed(1)}h`} />
              <KpiCard label="Streak" value={`${stats.current_streak} ${stats.current_streak_type.toUpperCase()}`} color={stats.current_streak_type === 'win' ? '#16c784' : stats.current_streak_type === 'loss' ? '#ea3943' : undefined} />
            </div>
            <div style={{ background: 'var(--surface-container, rgba(127,127,127,0.04))', border: '1px solid var(--hairline)', borderRadius: 10, padding: 16 }}>
              <div style={{ fontSize: 10, color: 'var(--on-surface-dim)', letterSpacing: '0.07em', textTransform: 'uppercase', marginBottom: 10 }}>Equity curve</div>
              <EquityCurve trades={trades} />
            </div>
            {Object.keys(stats.by_symbol).length > 0 && (
              <div style={{ background: 'var(--surface-container, rgba(127,127,127,0.04))', border: '1px solid var(--hairline)', borderRadius: 10, padding: 16 }}>
                <div style={{ fontSize: 10, color: 'var(--on-surface-dim)', letterSpacing: '0.07em', textTransform: 'uppercase', marginBottom: 12 }}>PnL by pair</div>
                {Object.entries(stats.by_symbol).slice(0, 10).map(([sym, pnl]) => {
                  const mx = Math.max(...Object.values(stats.by_symbol).map(Math.abs))
                  return (
                    <div key={sym} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 7 }}>
                      <span style={{ fontSize: 11, color: 'var(--on-surface-dim)', minWidth: 90, fontFamily: 'monospace' }}>{sym.replace('USDT', '')}</span>
                      <div style={{ flex: 1, height: 5, background: 'var(--surface-container-high, rgba(127,127,127,0.10))', borderRadius: 3, overflow: 'hidden' }}>
                        <div style={{ width: `${(Math.abs(pnl) / mx) * 100}%`, height: '100%', background: pnlColor(pnl), borderRadius: 3 }} />
                      </div>
                      <span style={{ fontSize: 11, color: pnlColor(pnl), minWidth: 80, textAlign: 'right', fontFamily: 'monospace', fontWeight: 600 }}>{pnl >= 0 ? '+' : ''}{fmt(pnl, 4)}</span>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}
        {!loading && !error && !noKeys && panel === 'portfolio' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {portfolioLoading && !portfolio && <div style={{ textAlign: 'center', padding: '48px 0', color: 'var(--on-surface-dim)', fontSize: 12 }}>Loading portfolio…</div>}
            {portfolio && <>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
                <div style={{ gridColumn: '1/-1', fontSize: 10, color: 'var(--on-surface-dim)', letterSpacing: '0.07em', textTransform: 'uppercase', marginBottom: 2 }}>
                  Portfolio · {new Date(portfolio.fetched_at + 'Z').toLocaleTimeString()}
                  <button onClick={() => void fetchPortfolio()} style={{ marginLeft: 10, fontSize: 10, color: 'var(--primary)', background: 'none', border: 'none', cursor: 'pointer' }}>Refresh</button>
                </div>
                <KpiCard label="Total Balance" value={`${fmt(portfolio.total_balance, 2)} USDT`} sub="Futures + Spot + Funding" />
                <KpiCard label="Futures Wallet" value={`${fmt(portfolio.futures_wallet, 2)} USDT`} sub={`Available: ${fmt(portfolio.futures_available, 2)}`} />
                <KpiCard label="Unrealized PnL" value={`${portfolio.futures_unrealized >= 0 ? '+' : ''}${fmt(portfolio.futures_unrealized, 4)}`} sub="USDT" color={pnlColor(portfolio.futures_unrealized)} />
                {portfolio.spot_balance > 0 && <KpiCard label="Spot Balance" value={`${fmt(portfolio.spot_balance, 2)} USDT`} />}
                {portfolio.funding_balance > 0 && <KpiCard label="Funding Balance" value={`${fmt(portfolio.funding_balance, 2)} USDT`} />}
                <KpiCard label="Margin Used" value={`${fmt(portfolio.futures_margin_pct, 1)}%`} sub={`${fmt(portfolio.futures_margin_used, 2)} USDT`} color={portfolio.futures_margin_pct > 80 ? '#ea3943' : portfolio.futures_margin_pct > 50 ? 'var(--primary)' : '#16c784'} />
              </div>
              <div style={{ background: 'var(--surface-container, rgba(127,127,127,0.04))', border: '1px solid var(--hairline)', borderRadius: 10, padding: 16 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8, fontSize: 11 }}>
                  <span style={{ color: 'var(--on-surface-dim)', fontSize: 10, letterSpacing: '0.07em', textTransform: 'uppercase' }}>Margin utilisation</span>
                  <span style={{ color: portfolio.futures_margin_pct > 80 ? '#ea3943' : portfolio.futures_margin_pct > 50 ? 'var(--primary)' : '#16c784', fontWeight: 700, fontFamily: 'monospace' }}>{fmt(portfolio.futures_margin_pct, 1)}%</span>
                </div>
                <div style={{ height: 7, background: 'var(--surface-container-high, rgba(127,127,127,0.10))', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${Math.min(portfolio.futures_margin_pct, 100)}%`, background: portfolio.futures_margin_pct > 80 ? '#ea3943' : portfolio.futures_margin_pct > 50 ? 'var(--primary)' : '#16c784', borderRadius: 4, transition: 'width 0.4s' }} />
                </div>
              </div>
              {portfolio.open_positions.length > 0 && (
                <div style={{ background: 'var(--surface-container, rgba(127,127,127,0.04))', border: '1px solid var(--hairline)', borderRadius: 10, overflow: 'hidden' }}>
                  <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--hairline)', fontSize: 10, color: 'var(--on-surface-dim)', letterSpacing: '0.07em', textTransform: 'uppercase' }}>Open positions ({portfolio.open_position_count})</div>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                    <thead><tr style={{ background: 'var(--surface-container, rgba(127,127,127,0.04))' }}>{['Symbol', 'Side', 'Size', 'Entry', 'Notional', 'uPnL', 'Leverage', 'Margin'].map(h => <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 10, color: 'var(--on-surface-dim)', fontWeight: 500, letterSpacing: '0.06em', textTransform: 'uppercase' }}>{h}</th>)}</tr></thead>
                    <tbody>
                      {portfolio.open_positions.map((pos, i) => (
                        <tr key={i} style={{ borderTop: '1px solid var(--hairline)', background: pos.unrealized_pnl >= 0 ? 'rgba(22,199,132,0.025)' : 'rgba(234,57,67,0.025)' }}>
                          <td style={{ padding: '10px 12px', fontWeight: 600, fontFamily: 'monospace', fontSize: 11 }}>{pos.symbol.replace('USDT', '')}</td>
                          <td style={{ padding: '10px 12px' }}><span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 600, background: pos.side === 'LONG' ? 'rgba(22,199,132,0.18)' : 'rgba(234,57,67,0.18)', color: pos.side === 'LONG' ? '#16c784' : '#ea3943' }}>{pos.side}</span></td>
                          <td style={{ padding: '10px 12px', fontFamily: 'monospace', fontSize: 11, color: 'var(--on-surface-dim)' }}>{pos.qty}</td>
                          <td style={{ padding: '10px 12px', fontFamily: 'monospace', fontSize: 11 }}>{fmt(pos.entry_price, 4)}</td>
                          <td style={{ padding: '10px 12px', fontFamily: 'monospace', fontSize: 11, color: 'var(--on-surface-dim)' }}>${fmt(pos.notional_usd, 2)}</td>
                          <td style={{ padding: '10px 12px', fontFamily: 'monospace', fontSize: 11, fontWeight: 700, color: pnlColor(pos.unrealized_pnl) }}>{pos.unrealized_pnl >= 0 ? '+' : ''}{fmt(pos.unrealized_pnl, 4)}</td>
                          <td style={{ padding: '10px 12px', fontSize: 11, color: 'var(--on-surface-dim)' }}>{pos.leverage}×</td>
                          <td style={{ padding: '10px 12px', fontFamily: 'monospace', fontSize: 11, color: 'var(--on-surface-dim)' }}>${fmt(pos.margin_used, 2)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>}
          </div>
        )}
        {!loading && !error && !noKeys && panel === 'analysis' && (
          <AnalysisPanel analysis={analysis} loading={analysisLoading} onGenerate={() => void runAnalysis()} />
        )}
      </div>
    </div>
  )
}