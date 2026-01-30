'use client'

import { useState } from 'react'
import { DataPanel } from './DataPanelsContainer'

interface RecentExit {
  signal_id: string
  direction: string
  pnl: number
  exit_reason: string
  exit_time: string
  entry_time?: string
  entry_price?: number
  exit_price?: number
  entry_reason?: string
  duration_seconds?: number
  // NEW: ML and regime data
  ml_probability?: number
  regime_at_entry?: string
  target_points?: number
}

interface RecentTradesPanelProps {
  recentExits: RecentExit[]
}

export default function RecentTradesPanel({ recentExits }: RecentTradesPanelProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null)

  if (!recentExits || recentExits.length === 0) {
    return (
      <DataPanel title="Recent Trades" icon="📋">
        <div className="no-trades">No recent trades</div>
      </DataPanel>
    )
  }

  const formatPnL = (pnl: number) => {
    const sign = pnl >= 0 ? '+' : ''
    return `${sign}$${pnl.toFixed(2)}`
  }

  const formatTime = (timeStr: string) => {
    try {
      const date = new Date(timeStr)
      return date.toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      })
    } catch {
      return '--:--'
    }
  }

  const formatDuration = (seconds?: number) => {
    if (!seconds) return '—'
    if (seconds < 60) return `${seconds}s`
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
    const hours = Math.floor(seconds / 3600)
    const mins = Math.floor((seconds % 3600) / 60)
    return `${hours}h ${mins}m`
  }

  const formatExitReason = (reason: string) => {
    if (!reason) return ''
    return reason
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase())
  }

  const formatPrice = (price?: number) => {
    if (!price) return '—'
    return price.toFixed(2)
  }

  const toggleExpand = (id: string) => {
    setExpandedId(expandedId === id ? null : id)
  }

  return (
    <DataPanel title="Recent Trades" icon="📋">
      <div className="recent-trades-list">
        {recentExits.map((exit, index) => {
          const isExpanded = expandedId === exit.signal_id
          return (
            <div key={exit.signal_id || index} className="recent-trade-wrapper">
              <div
                className={`recent-trade ${isExpanded ? 'expanded' : ''}`}
                onClick={() => toggleExpand(exit.signal_id)}
              >
                <div className="trade-left">
                  <span className={`trade-direction-badge ${exit.direction}`}>
                    {exit.direction.toUpperCase()}
                  </span>
                  <span className="trade-time">{formatTime(exit.exit_time)}</span>
                </div>
                <div className="trade-right">
                  <span className={`trade-pnl ${exit.pnl >= 0 ? 'positive' : 'negative'}`}>
                    {formatPnL(exit.pnl)}
                  </span>
                  {exit.exit_reason && (
                    <span className="trade-reason">{formatExitReason(exit.exit_reason)}</span>
                  )}
                </div>
                <span className="trade-expand-icon">{isExpanded ? '▲' : '▼'}</span>
              </div>

              {isExpanded && (
                <div className="trade-details">
                  <div className="trade-detail-row">
                    <span className="trade-detail-label">Entry</span>
                    <span className="trade-detail-value">
                      {formatPrice(exit.entry_price)} @ {formatTime(exit.entry_time || '')}
                    </span>
                  </div>
                  <div className="trade-detail-row">
                    <span className="trade-detail-label">Exit</span>
                    <span className="trade-detail-value">
                      {formatPrice(exit.exit_price)} @ {formatTime(exit.exit_time)}
                    </span>
                  </div>
                  <div className="trade-detail-row">
                    <span className="trade-detail-label">Duration</span>
                    <span className="trade-detail-value">{formatDuration(exit.duration_seconds)}</span>
                  </div>
                  {exit.entry_reason && (
                    <div className="trade-detail-row">
                      <span className="trade-detail-label">Signal</span>
                      <span className="trade-detail-value trade-signal">{exit.entry_reason}</span>
                    </div>
                  )}
                  {exit.entry_price && exit.exit_price && (
                    <div className="trade-detail-row">
                      <span className="trade-detail-label">Points</span>
                      <span className={`trade-detail-value ${exit.pnl >= 0 ? 'positive' : 'negative'}`}>
                        {exit.direction === 'long'
                          ? (exit.exit_price - exit.entry_price).toFixed(2)
                          : (exit.entry_price - exit.exit_price).toFixed(2)
                        }
                        {exit.target_points && (
                          <span className="trade-detail-sub"> / {exit.target_points} target</span>
                        )}
                      </span>
                    </div>
                  )}
                  {exit.ml_probability !== undefined && (
                    <div className="trade-detail-row">
                      <span className="trade-detail-label">ML Prob</span>
                      <span className={`trade-detail-value ${exit.ml_probability >= 0.6 ? 'positive' : exit.ml_probability < 0.4 ? 'negative' : ''}`}>
                        {(exit.ml_probability * 100).toFixed(0)}%
                      </span>
                    </div>
                  )}
                  {exit.regime_at_entry && (
                    <div className="trade-detail-row">
                      <span className="trade-detail-label">Regime</span>
                      <span className="trade-detail-value trade-regime">
                        {exit.regime_at_entry.replace(/_/g, ' ')}
                      </span>
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </DataPanel>
  )
}
