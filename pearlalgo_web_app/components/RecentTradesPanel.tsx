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

interface DirectionBreakdown {
  long: { count: number; pnl: number }
  short: { count: number; pnl: number }
}

interface StatusBreakdown {
  generated: number
  entered: number
  exited: number
  cancelled: number
}

interface RecentTradesPanelProps {
  recentExits: RecentExit[]
  maxItems?: number // Optional limit for compact display (e.g., ultrawide mode)
  directionBreakdown?: DirectionBreakdown | null
  statusBreakdown?: StatusBreakdown | null
}

export default function RecentTradesPanel({
  recentExits,
  maxItems,
  directionBreakdown,
  statusBreakdown
}: RecentTradesPanelProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [showSummary, setShowSummary] = useState(true)

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

  const formatExitReason = (reason: string): { text: string; type: string } => {
    if (!reason) return { text: '', type: '' }
    const lowerReason = reason.toLowerCase()

    // Categorize exit reasons for styling
    if (lowerReason.includes('close_all') || lowerReason.includes('close all')) {
      return { text: 'Manual Close', type: 'manual' }
    }
    if (lowerReason.includes('stop') || lowerReason.includes('sl_')) {
      return { text: 'Stop Loss', type: 'stop' }
    }
    if (lowerReason.includes('target') || lowerReason.includes('tp_') || lowerReason.includes('profit')) {
      return { text: 'Target Hit', type: 'target' }
    }
    if (lowerReason.includes('trail')) {
      return { text: 'Trailing Stop', type: 'trail' }
    }
    if (lowerReason.includes('time') || lowerReason.includes('eod') || lowerReason.includes('session')) {
      return { text: 'Time Exit', type: 'time' }
    }

    return {
      text: reason.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
      type: 'other'
    }
  }

  const formatPrice = (price?: number) => {
    if (!price) return '—'
    return price.toFixed(2)
  }

  const toggleExpand = (id: string) => {
    setExpandedId(expandedId === id ? null : id)
  }

  // Apply maxItems limit if specified (for compact ultrawide display)
  const displayExits = maxItems ? recentExits.slice(0, maxItems) : recentExits

  const formatSummaryPnL = (pnl: number) => {
    const sign = pnl >= 0 ? '+' : ''
    return `${sign}$${pnl.toFixed(0)}`
  }

  const hasSummaryData = directionBreakdown || statusBreakdown

  return (
    <DataPanel title="Recent Trades" icon="📋">
      {/* Trade Stats Summary */}
      {hasSummaryData && (
        <div className="trade-stats-summary-wrapper">
          <button
            className="trade-stats-summary-toggle"
            onClick={() => setShowSummary(!showSummary)}
          >
            <span className="trade-stats-summary-label">Trade Stats</span>
            <span className="trade-stats-summary-icon">{showSummary ? '▲' : '▼'}</span>
          </button>

          {showSummary && (
            <div className="trade-stats-summary">
              {/* Direction Breakdown */}
              {directionBreakdown && (
                <div className="trade-stats-row">
                  <span className="trade-stats-label">Direction:</span>
                  <div className="trade-stats-values">
                    <span className="direction-long">
                      LONG: {directionBreakdown.long.count} ({formatSummaryPnL(directionBreakdown.long.pnl)})
                    </span>
                    <span className="direction-short">
                      SHORT: {directionBreakdown.short.count} ({formatSummaryPnL(directionBreakdown.short.pnl)})
                    </span>
                  </div>
                </div>
              )}

              {/* Status Breakdown */}
              {statusBreakdown && (
                <div className="trade-stats-row">
                  <span className="trade-stats-label">Status:</span>
                  <div className="trade-stats-values">
                    <span className="badge-entered">{statusBreakdown.entered} Active</span>
                    <span className="badge-exited">{statusBreakdown.exited} Closed</span>
                    {statusBreakdown.cancelled > 0 && (
                      <span className="badge-cancelled">{statusBreakdown.cancelled} Cancelled</span>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <div className="recent-trades-list">
        {displayExits.map((exit, index) => {
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
                  <div className="trade-info">
                    <span className="trade-time">{formatTime(exit.exit_time)}</span>
                    {exit.entry_price && exit.exit_price && (
                      <span className="trade-prices">
                        {formatPrice(exit.entry_price)} → {formatPrice(exit.exit_price)}
                      </span>
                    )}
                  </div>
                </div>
                <div className="trade-right">
                  <span className={`trade-pnl ${exit.pnl >= 0 ? 'positive' : 'negative'}`}>
                    {formatPnL(exit.pnl)}
                  </span>
                  {exit.exit_reason && (
                    <span className={`trade-reason-badge reason-${formatExitReason(exit.exit_reason).type}`}>
                      {formatExitReason(exit.exit_reason).text}
                    </span>
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
