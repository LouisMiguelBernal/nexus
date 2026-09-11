import { create } from 'zustand'

export interface StoredBrief {
  brief?: string | null
  news_synthesis?: string | null
  news_sentiment?: string | null
  news_count?: number
  generated_at?: string
  symbol?: string
  fng_score?: number | null
  fng_label?: string | null
  sm_signal?: string | null
  sm_score?: number | null
  error?: string | null
}

export interface StoredFngComponents {
  volatility: number
  momentum: number
  funding: number
  ls_position: number
  oi_momentum: number
  [k: string]: number
}

export interface StoredFngInputs {
  price_change_24h_pct: number
  funding_rate_pct: number
  oi_change_24h_pct: number
  ls_ratio: number
  [k: string]: number
}

export interface StoredFng {
  score: number
  label: string
  color: string
  ai_interpretation?: string
  components?: StoredFngComponents
  inputs?: StoredFngInputs
  computed_at?: string
  stale?: boolean
  error?: string
}

export interface StoredSmSignal {
  score: number
  label: string
  color: string
  confidence: number
  type: string
  timeframe: string
  ai_insight: string
}

export interface StoredSmTopTrader {
  ratio: number
  bias: string
  trend: string
  long_pct: number
  delta_6h: number
  delta_24h: number
}

export interface StoredSmDivergence {
  type: string
  strength: number
  signal: boolean
  bias: 'bullish' | 'bearish' | string
}

export interface StoredSmOi {
  velocity_6h_pct: number
  acceleration_pct: number
}

export interface StoredSmFunding {
  rate_pct: number
  label: string
}

export interface StoredSmHistoryPoint {
  ts: number
  ratio: number
  long: number
  short: number
}

export interface StoredSm {
  symbol: string
  signal?: StoredSmSignal
  top_trader?: StoredSmTopTrader
  divergence?: StoredSmDivergence
  oi?: StoredSmOi
  funding?: StoredSmFunding
  history?: {
    top_trader: StoredSmHistoryPoint[]
    retail: StoredSmHistoryPoint[]
  }
  computed_at?: string
  stale?: boolean
  error?: string
}

interface BriefState {
  brief: StoredBrief | null
  isGenerating: boolean
  fng: StoredFng | null
  fngLoading: boolean
  smartMoney: StoredSm | null
  smartMoneyLoading: boolean

  setBrief:        (b: StoredBrief | null) => void
  clearBrief:      () => void
  setGenerating:   (v: boolean) => void
  setFng:          (f: StoredFng) => void
  setFngLoading:   (v: boolean) => void
  setSmartMoney:   (s: StoredSm) => void
  setSmLoading:    (v: boolean) => void
}

export const useBriefStore = create<BriefState>((set) => ({
  brief:              null,
  isGenerating:       false,
  fng:                null,
  fngLoading:         true,
  smartMoney:         null,
  smartMoneyLoading:  true,

  setBrief:       (b) => set({ brief: b }),
  clearBrief:     ()  => set({ brief: null }),
  setGenerating:  (v) => set({ isGenerating: v }),
  setFng:         (f) => set({ fng: f, fngLoading: false }),
  setFngLoading:  (v) => set({ fngLoading: v }),
  setSmartMoney:  (s) => set({ smartMoney: s, smartMoneyLoading: false }),
  setSmLoading:   (v) => set({ smartMoneyLoading: v }),
}))

export const fngStale = (fng: StoredFng | null | undefined): boolean => {
  if (!fng?.computed_at) return true
  return Date.now() - new Date(fng.computed_at).getTime() > 5 * 60 * 1000
}

export const smStale = (sm: StoredSm | null | undefined): boolean => {
  if (!sm?.computed_at) return true
  return Date.now() - new Date(sm.computed_at).getTime() > 2 * 60 * 1000
}
