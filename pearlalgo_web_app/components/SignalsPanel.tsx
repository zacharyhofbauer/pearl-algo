'use client'

import { useEffect, useState, useCallback, useRef } from 'react'
import { apiFetchJson } from '@/lib/api'

interface PanelSignal {
  signal_id: string
  timestamp: string | null
  direction: string | null
  signal_type: string
  confidence: number | null
  status: 'TAKEN' | 'BLOCKED' | 'VIRTUAL'
  block_reason: string | null
  pnl: number | null
  exit_reason: string | null
  entry_price: number | null
}

interface RegimeInfo {
  regime: string
  confidence: number
  allowed_direction: string
}

interface OpeningRange {
  high: number
  low: number
}

interface SignalsPanelData {
  signals: PanelSignal[]
  regime: RegimeInfo
  opening_range: OpeningRange | null
}

export default function SignalsPanel() {
  const [data, setData] = useState<SignalsPanelData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchData = useCallback(async () => {
    try {
      const result = await apiFetchJson<SignalsPanelData>('/api/signals-panel?limit=20')
      setData(result)
      setError(null)
    } catch (e) {
      setError('Failed to load signals')
    }
  }, [])

  useEffect(() => {
    fetchData()
    intervalRef.current = setInterval(fetchData, 15000)
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [fetchData])

  const formatTime = (ts: string | null) => {
    if (!ts) return '--:--'
    try {
      const d = new Date(ts)
      return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
    } catch {
      return ts.slice(11, 16) || '--:--'
    }
  }

  const formatSignalType = (t: string) => {
    if (!t || t === 'unknown') return '—'
    return t
      .replace('pearlbot_pinescript', 'pine')
      .replace('ema_cross', 'EMA×')
      .replace('vwap_cross', 'VWAP×')
      .replace('_', ' ')
  }

  const formatBlockReason = (r: string | null) => {
    if (!r) return ''
    return r
      .replace('circuit_breaker:', '')
      .replace('_', ' ')
  }

  const regimeColor = (regime: string) => {
    if (regime.includes('up')) return 'var(--color-profit)'
    if (regime.includes('down')) return 'var(--color-loss)'
    return 'var(--text-secondary)'
  }

  if (error && !data) {
    return <div className="signals-panel-empty">{error}</div>
  }

  const signals = data?.signals || []
  const regime = data?.regime || { regime: 'unknown', confidence: 0, allowed_direction: 'both' }
  const openingRange = data?.opening_range

  return (
    <div className="signals-panel">
      {/* Regime header */}
      <div className="signals-regime-header">
        <div className="signals-regime-row">
          <span className="signals-regime-label">Regime</span>
          <span className="signals-regime-value" style={{ color: regimeColor(regime.regime) }}>
            {regime.regime.replace('_', ' ')}
          </span>
          <span className="signals-regime-conf">{(regime.confidence * 100).toFixed(0)}%</span>
        </div>
        <div className="signals-regime-row">
          <span className="signals-regime-label">Direction</span>
          <span className="signals-regime-value">{regime.allowed_direction}</span>
        </div>
        {openingRange && (
          <div className="signals-regime-row">
            <span className="signals-regime-label">OR Range</span>
            <span className="signals-or-range">
              {openingRange.low.toFixed(2)} — {openingRange.high.toFixed(2)}
            </span>
          </div>
        )}
      </div>

      {/* Signals list */}
      <div className="signals-list">
        {signals.length === 0 ? (
          <div className="signals-panel-empty">No recent signals</div>
        ) : (
          signals.map((sig) => (
            <div key={sig.signal_id} className="signals-row">
              <span className="signals-time">{formatTime(sig.timestamp)}</span>
              <span className={`signals-dir ${(sig.direction || '').toLowerCase()}`}>
                {sig.direction ? sig.direction.toUpperCase().slice(0, 1) : '?'}
              </span>
              <span className="signals-type">{formatSignalType(sig.signal_type)}</span>
              <span className="signals-conf">
                {sig.confidence != null ? (sig.confidence * 100).toFixed(0) + '%' : '—'}
              </span>
              <span className={`signals-status-badge ${sig.status.toLowerCase()}`}>
                {sig.status}
              </span>
              {sig.status === 'BLOCKED' && sig.block_reason && (
                <span className="signals-block-reason" title={sig.block_reason}>
                  {formatBlockReason(sig.block_reason)}
                </span>
              )}
              {sig.status === 'TAKEN' && sig.pnl != null && (
                <span className={`signals-pnl ${sig.pnl >= 0 ? 'positive' : 'negative'}`}>
                  {sig.pnl >= 0 ? '+' : ''}{sig.pnl.toFixed(2)}
                </span>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
