/**
 * Lightweight markdown-ish renderer used across AI brief / journal outputs.
 *
 * Handles: headings (#, ##, ###), bold (**), italics (*), inline code (`),
 * bullet lists (-, *, •, 1.), horizontal rules (---), blockquotes (>).
 *
 * Strips stray markdown tokens from the visible output so the paste to
 * operators reads like clean prose, not raw Gemma text.
 */
import React from 'react'

type Opts = {
  /** Optional muted / secondary color for meta lines (dim). */
  dim?: string
  /** Color for strong/bold text. */
  bold?: string
  /** Color for headings. */
  heading?: string
  /** Color for inline code chips background hint. */
  codeBg?: string
  /** Color for bullet marker (default: primary accent). */
  bullet?: string
}

function renderInline(text: string, o: Opts, keySeed: string): React.ReactNode[] {
  const out: React.ReactNode[] = []
  let i = 0
  let buf = ''
  const flush = () => {
    if (buf) { out.push(buf); buf = '' }
  }
  const pat = /(\*\*([^*\n]+)\*\*)|(\*([^*\n]+)\*)|(`([^`\n]+)`)/g
  let m: RegExpExecArray | null
  while ((m = pat.exec(text)) !== null) {
    if (m.index > i) buf += text.slice(i, m.index)
    flush()
    if (m[2] !== undefined) {
      out.push(<strong key={`${keySeed}-b-${m.index}`} style={{ color: o.bold ?? 'var(--on-surface)', fontWeight: 600 }}>{m[2]}</strong>)
    } else if (m[4] !== undefined) {
      out.push(<em key={`${keySeed}-i-${m.index}`} style={{ color: o.bold ?? 'var(--on-surface)', fontStyle: 'italic' }}>{m[4]}</em>)
    } else if (m[6] !== undefined) {
      out.push(
        <code key={`${keySeed}-c-${m.index}`} style={{
          padding: '1px 6px', borderRadius: 3,
          background: o.codeBg ?? 'rgba(127,127,127,0.12)',
          fontSize: '0.92em', fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace',
        }}>{m[6]}</code>
      )
    }
    i = m.index + m[0].length
  }
  if (i < text.length) buf += text.slice(i)
  flush()
  return out
}

/**
 * Render the LLM output as clean React nodes.
 * Wraps in a fragment - caller controls containing element / scroll.
 */
export function renderBriefBody(raw: string | null | undefined, o: Opts = {}): React.ReactNode {
  if (!raw) return null
  const heading = o.heading ?? 'var(--primary)'
  const dim = o.dim ?? 'var(--on-surface-dim)'
  const bullet = o.bullet ?? heading

  const lines = String(raw).replace(/\r\n/g, '\n').trim().split('\n')
  const nodes: React.ReactNode[] = []

  for (let i = 0; i < lines.length; i++) {
    const rawLine = lines[i]
    const line = rawLine.trim()

    // Blank line → spacer (collapse consecutive)
    if (!line) {
      if (nodes.length && (nodes[nodes.length - 1] as React.ReactElement)?.key !== `sp-${i - 1}`) {
        nodes.push(<div key={`sp-${i}`} style={{ height: 6 }} />)
      }
      continue
    }

    // Horizontal rule
    if (/^[-_*]{3,}$/.test(line)) {
      nodes.push(<div key={`hr-${i}`} style={{ margin: '10px 0', borderTop: '1px solid var(--hairline)' }} />)
      continue
    }

    // Heading ###, ##, #
    const h = line.match(/^(#{1,6})\s+(.*)$/)
    if (h) {
      const level = h[1].length
      const size = level <= 1 ? 15 : level === 2 ? 13 : 11.5
      const weight = level <= 2 ? 700 : 600
      const letter = level <= 2 ? '0.06em' : '0.08em'
      const topMargin = nodes.length ? 10 : 0
      nodes.push(
        <div key={`h-${i}`} style={{
          fontSize: size, fontWeight: weight, color: heading,
          letterSpacing: letter, textTransform: level <= 2 ? 'none' : 'uppercase',
          margin: `${topMargin}px 0 5px`,
        }}>
          {renderInline(stripEmoji(h[2].replace(/:+$/, '')), o, `h-${i}`)}
        </div>
      )
      continue
    }

    // Blockquote
    const bq = line.match(/^>\s*(.*)$/)
    if (bq) {
      nodes.push(
        <div key={`bq-${i}`} style={{
          borderLeft: '2px solid var(--hairline)', padding: '2px 0 2px 10px',
          margin: '4px 0', color: dim, fontStyle: 'italic',
        }}>
          {renderInline(bq[1], o, `bq-${i}`)}
        </div>
      )
      continue
    }

    // Bulleted list (* / - / • / 1.)
    const bullMatch = line.match(/^(?:[*\-•]|\d+\.)\s+(.*)$/)
    if (bullMatch) {
      nodes.push(
        <div key={`li-${i}`} style={{ display: 'flex', gap: 8, marginBottom: 3, lineHeight: 1.7 }}>
          <span aria-hidden style={{ color: bullet, flexShrink: 0, lineHeight: 1.7 }}>›</span>
          <span style={{ flex: 1 }}>{renderInline(bullMatch[1], o, `li-${i}`)}</span>
        </div>
      )
      continue
    }

    // Default paragraph
    nodes.push(
      <div key={`p-${i}`} style={{ marginBottom: 3, lineHeight: 1.7 }}>
        {renderInline(line, o, `p-${i}`)}
      </div>
    )
  }

  return <>{nodes}</>
}

/** Strip leading emoji + stray separators that Gemma likes to prefix. */
function stripEmoji(s: string): string {
  return s
    .replace(/^([\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]\s+)/u, '')
    .replace(/^[•·>\--]+\s*/, '')
    .trim()
}

/**
 * Normalise a backend `generated_at` field (which may arrive as unix seconds,
 * unix millis, or an ISO string) to a JS Date.
 */
export function parseGeneratedAt(ga: unknown): Date | null {
  if (ga == null) return null
  if (typeof ga === 'number') {
    // seconds vs ms: a timestamp smaller than 10^12 is seconds
    const ms = ga < 1e12 ? ga * 1000 : ga
    const d = new Date(ms)
    return isNaN(d.getTime()) ? null : d
  }
  if (typeof ga === 'string') {
    const d = new Date(ga)
    return isNaN(d.getTime()) ? null : d
  }
  return null
}

export function fmtBriefStamp(ga: unknown): string {
  const d = parseGeneratedAt(ga)
  if (!d) return ''
  return d.toLocaleString(undefined, { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}
