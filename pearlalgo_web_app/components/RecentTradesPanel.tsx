'use client'

import { useState } from 'react'
import { DataPanel } from './DataPanelsContainer'
import { formatPnL, formatTime as formatTimeUtil, formatDuration as formatDurationUtil, formatPrice } from '@/lib/formatters'
import type { RecentExit, DirectionBreakdown, StatusBreakdown } from '@/stores'

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

  // Use centralized formatters with appropriate options
  const formatTime = (timeStr: string) => formatTimeUtil(timeStr, false) // no seconds
  const formatDuration = (seconds?: number) => formatDurationUtil(seconds)

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

  const toggleExpand = (id: string) => {
    setExpandedId(expandedId === id ? null : id)
  }

  // Apply maxItems limit if specified (for compact ultrawide display)
  const displayExits = maxItems ? recentExits.slice(0, maxItems) : recentExits

  // Use centralized formatPnL with 0 decimals for summary
  const formatSummaryPnL = (pnl: number) => formatPnL(pnl, 0)

  const hasSummaryData = directionBreakdown || statusBreakdown

  // Calculate win rate by exit reason
  const exitReasonStats = recentExits.reduce((acc, exit) => {
    if (!exit.exit_reason) return acc
    const { text } = formatExitReason(exit.exit_reason)
    if (!acc[text]) {
      acc[text] = { wins: 0, total: 0, pnl: 0 }
    }
    acc[text].total++
    if (exit.pnl > 0) acc[text].wins++
    acc[text].pnl += exit.pnl
    return acc
  }, {} as Record<string, { wins: number; total: number; pnl: number }>)

  // Sort by total trades descending
  const sortedExitReasons = Object.entries(exitReasonStats)
    .filter(([_, stats]) => stats.total >= 2) // Only show reasons with 2+ trades
    .sort((a, b) => b[1].total - a[1].total)

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

              {/* Exit Reason Win Rates */}
              {sortedExitReasons.length > 0 && (
                <div className="exit-reason-stats">
                  <span className="trade-stats-label">Win% by Exit:</span>
                  <div className="exit-reason-grid">
                    {sortedExitReasons.map(([reason, stats]) => {
                      const winRate = (stats.wins / stats.total * 100)
                      return (
                        <div key={reason} className="exit-reason-stat">
                          <span className="exit-reason-name">{reason}</span>
                          <span className={`exit-reason-winrate ${winRate >= 50 ? 'positive' : 'negative'}`}>
                            {winRate.toFixed(0)}%
                          </span>
                          <span className="exit-reason-count">({stats.total})</span>
                        </div>
                      )
                    })}
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
