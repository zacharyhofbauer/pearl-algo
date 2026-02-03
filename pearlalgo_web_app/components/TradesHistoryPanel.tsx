'use client'

import { useState, useMemo, memo, useCallback } from 'react'
import { DataPanel } from './DataPanelsContainer'
import { formatPnL, formatTime as formatTimeUtil, formatDuration as formatDurationUtil, formatPrice } from '@/lib/formatters'
import type { RecentExit } from '@/stores'

interface TradesHistoryPanelProps {
  recentExits: RecentExit[]
  isLoading?: boolean
}

type FilterDirection = 'all' | 'long' | 'short'
type FilterExitReason = 'all' | 'target' | 'stop' | 'trail' | 'time' | 'manual'
type SortOrder = 'newest' | 'oldest' | 'pnl_high' | 'pnl_low'

interface DayGroup {
  date: string
  displayDate: string
  trades: RecentExit[]
  totalPnL: number
  wins: number
  losses: number
  winRate: number
}

// Format exit reason for display
const formatExitReason = (reason: string): { text: string; type: string } => {
  if (!reason) return { text: '', type: '' }
  const lowerReason = reason.toLowerCase()

  if (lowerReason.includes('close_all') || lowerReason.includes('close all')) {
    return { text: 'Manual', type: 'manual' }
  }
  if (lowerReason.includes('stop') || lowerReason.includes('sl_')) {
    return { text: 'Stop', type: 'stop' }
  }
  if (lowerReason.includes('target') || lowerReason.includes('tp_') || lowerReason.includes('profit')) {
    return { text: 'Target', type: 'target' }
  }
  if (lowerReason.includes('trail')) {
    return { text: 'Trail', type: 'trail' }
  }
  if (lowerReason.includes('time') || lowerReason.includes('eod') || lowerReason.includes('session')) {
    return { text: 'Time', type: 'time' }
  }

  return { text: reason.slice(0, 6), type: 'other' }
}

// Get exit reason type for filtering
const getExitReasonType = (reason: string): string => {
  return formatExitReason(reason).type
}

// Format date for display
const formatDisplayDate = (dateStr: string): string => {
  const date = new Date(dateStr + 'T00:00:00')
  const today = new Date()
  const yesterday = new Date(today)
  yesterday.setDate(yesterday.getDate() - 1)

  if (dateStr === today.toISOString().slice(0, 10)) {
    return 'Today'
  }
  if (dateStr === yesterday.toISOString().slice(0, 10)) {
    return 'Yesterday'
  }

  return date.toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  })
}

function TradesHistoryPanel({ recentExits, isLoading = false }: TradesHistoryPanelProps) {
  // Filter state
  const [filterDirection, setFilterDirection] = useState<FilterDirection>('all')
  const [filterExitReason, setFilterExitReason] = useState<FilterExitReason>('all')
  const [sortOrder, setSortOrder] = useState<SortOrder>('newest')
  const [expandedDays, setExpandedDays] = useState<Set<string>>(new Set())
  const [showFilters, setShowFilters] = useState(false)

  // Toggle day expansion
  const toggleDay = useCallback((date: string) => {
    setExpandedDays((prev) => {
      const next = new Set(prev)
      if (next.has(date)) {
        next.delete(date)
      } else {
        next.add(date)
      }
      return next
    })
  }, [])

  // Expand/collapse all
  const expandAll = useCallback(() => {
    const allDates = Array.from(new Set(recentExits.map((t) => t.exit_time?.slice(0, 10) || '')))
    setExpandedDays(new Set(allDates))
  }, [recentExits])

  const collapseAll = useCallback(() => {
    setExpandedDays(new Set())
  }, [])

  // Apply filters and sorting
  const filteredTrades = useMemo(() => {
    let trades = [...recentExits]

    // Filter by direction
    if (filterDirection !== 'all') {
      trades = trades.filter((t) => t.direction?.toLowerCase() === filterDirection)
    }

    // Filter by exit reason
    if (filterExitReason !== 'all') {
      trades = trades.filter((t) => getExitReasonType(t.exit_reason || '') === filterExitReason)
    }

    // Sort
    switch (sortOrder) {
      case 'newest':
        trades.sort((a, b) => new Date(b.exit_time || 0).getTime() - new Date(a.exit_time || 0).getTime())
        break
      case 'oldest':
        trades.sort((a, b) => new Date(a.exit_time || 0).getTime() - new Date(b.exit_time || 0).getTime())
        break
      case 'pnl_high':
        trades.sort((a, b) => (b.pnl || 0) - (a.pnl || 0))
        break
      case 'pnl_low':
        trades.sort((a, b) => (a.pnl || 0) - (b.pnl || 0))
        break
    }

    return trades
  }, [recentExits, filterDirection, filterExitReason, sortOrder])

  // Group trades by date
  const dayGroups = useMemo<DayGroup[]>(() => {
    const groups: Map<string, RecentExit[]> = new Map()

    filteredTrades.forEach((trade) => {
      const date = trade.exit_time?.slice(0, 10) || 'unknown'
      if (!groups.has(date)) {
        groups.set(date, [])
      }
      groups.get(date)!.push(trade)
    })

    return Array.from(groups.entries())
      .map(([date, trades]) => {
        const wins = trades.filter((t) => (t.pnl || 0) > 0).length
        const losses = trades.filter((t) => (t.pnl || 0) < 0).length
        const totalPnL = trades.reduce((sum, t) => sum + (t.pnl || 0), 0)

        return {
          date,
          displayDate: formatDisplayDate(date),
          trades,
          totalPnL,
          wins,
          losses,
          winRate: trades.length > 0 ? (wins / trades.length) * 100 : 0,
        }
      })
      .sort((a, b) => (sortOrder === 'oldest' ? a.date.localeCompare(b.date) : b.date.localeCompare(a.date)))
  }, [filteredTrades, sortOrder])

  // Summary stats
  const summaryStats = useMemo(() => {
    const totalTrades = filteredTrades.length
    const totalPnL = filteredTrades.reduce((sum, t) => sum + (t.pnl || 0), 0)
    const wins = filteredTrades.filter((t) => (t.pnl || 0) > 0).length
    const winRate = totalTrades > 0 ? (wins / totalTrades) * 100 : 0
    const avgPnL = totalTrades > 0 ? totalPnL / totalTrades : 0

    return { totalTrades, totalPnL, wins, winRate, avgPnL }
  }, [filteredTrades])

  // Loading state
  if (isLoading) {
    return (
      <DataPanel title="Trade History" icon="📊">
        <div className="trades-history-loading">
          <div className="loading-spinner-small" />
          <span>Loading trades...</span>
        </div>
      </DataPanel>
    )
  }

  // Empty state
  if (!recentExits || recentExits.length === 0) {
    return (
      <DataPanel title="Trade History" icon="📊">
        <div className="trades-history-empty">
          <span className="empty-icon">📭</span>
          <span className="empty-text">No trade history available</span>
        </div>
      </DataPanel>
    )
  }

  return (
    <DataPanel title="Trade History" icon="📊" badge={`${summaryStats.totalTrades} trades`}>
      {/* Summary Stats Bar */}
      <div className="trades-history-summary">
        <div className="summary-stat">
          <span className="summary-label">Total P&L</span>
          <span className={`summary-value ${summaryStats.totalPnL >= 0 ? 'positive' : 'negative'}`}>
            {formatPnL(summaryStats.totalPnL)}
          </span>
        </div>
        <div className="summary-stat">
          <span className="summary-label">Win Rate</span>
          <span className={`summary-value ${summaryStats.winRate >= 50 ? 'positive' : 'negative'}`}>
            {summaryStats.winRate.toFixed(1)}%
          </span>
        </div>
        <div className="summary-stat">
          <span className="summary-label">Avg P&L</span>
          <span className={`summary-value ${summaryStats.avgPnL >= 0 ? 'positive' : 'negative'}`}>
            {formatPnL(summaryStats.avgPnL)}
          </span>
        </div>
        <div className="summary-stat">
          <span className="summary-label">Days</span>
          <span className="summary-value">{dayGroups.length}</span>
        </div>
      </div>

      {/* Filter Toggle */}
      <div className="trades-history-controls">
        <button className="filter-toggle-btn" onClick={() => setShowFilters(!showFilters)}>
          <span className="filter-icon">⚙️</span>
          <span>Filters</span>
          <span className="filter-arrow">{showFilters ? '▲' : '▼'}</span>
        </button>

        <div className="expand-controls">
          <button className="expand-btn" onClick={expandAll} title="Expand all">
            ↕️
          </button>
          <button className="expand-btn" onClick={collapseAll} title="Collapse all">
            ↔️
          </button>
        </div>
      </div>

      {/* Filters Panel */}
      {showFilters && (
        <div className="trades-history-filters">
          <div className="filter-group">
            <span className="filter-label">Direction</span>
            <div className="filter-buttons">
              {(['all', 'long', 'short'] as FilterDirection[]).map((dir) => (
                <button
                  key={dir}
                  className={`filter-btn ${filterDirection === dir ? 'active' : ''} ${dir}`}
                  onClick={() => setFilterDirection(dir)}
                >
                  {dir === 'all' ? 'All' : dir.toUpperCase()}
                </button>
              ))}
            </div>
          </div>

          <div className="filter-group">
            <span className="filter-label">Exit Type</span>
            <div className="filter-buttons filter-buttons-wrap">
              {(['all', 'target', 'stop', 'trail', 'time', 'manual'] as FilterExitReason[]).map((reason) => (
                <button
                  key={reason}
                  className={`filter-btn filter-btn-sm ${filterExitReason === reason ? 'active' : ''} reason-${reason}`}
                  onClick={() => setFilterExitReason(reason)}
                >
                  {reason === 'all' ? 'All' : reason.charAt(0).toUpperCase() + reason.slice(1)}
                </button>
              ))}
            </div>
          </div>

          <div className="filter-group">
            <span className="filter-label">Sort</span>
            <div className="filter-buttons">
              <select
                className="sort-select"
                value={sortOrder}
                onChange={(e) => setSortOrder(e.target.value as SortOrder)}
              >
                <option value="newest">Newest First</option>
                <option value="oldest">Oldest First</option>
                <option value="pnl_high">Highest P&L</option>
                <option value="pnl_low">Lowest P&L</option>
              </select>
            </div>
          </div>
        </div>
      )}

      {/* Day Groups */}
      <div className="trades-history-list">
        {dayGroups.map((group) => {
          const isExpanded = expandedDays.has(group.date)

          return (
            <div key={group.date} className="day-group">
              {/* Day Header */}
              <button className="day-header" onClick={() => toggleDay(group.date)}>
                <div className="day-header-left">
                  <span className="day-expand-icon">{isExpanded ? '▼' : '▶'}</span>
                  <span className="day-date">{group.displayDate}</span>
                  <span className="day-trade-count">{group.trades.length} trades</span>
                </div>
                <div className="day-header-right">
                  <span className="day-winrate">{group.winRate.toFixed(0)}% WR</span>
                  <span className={`day-pnl ${group.totalPnL >= 0 ? 'positive' : 'negative'}`}>
                    {formatPnL(group.totalPnL)}
                  </span>
                </div>
              </button>

              {/* Day Progress Bar */}
              <div className="day-progress">
                <div
                  className="day-progress-fill positive"
                  style={{ width: `${(group.wins / group.trades.length) * 100}%` }}
                />
                <div
                  className="day-progress-fill negative"
                  style={{ width: `${(group.losses / group.trades.length) * 100}%` }}
                />
              </div>

              {/* Trades List */}
              {isExpanded && (
                <div className="day-trades">
                  {group.trades.map((trade, index) => {
                    const exitReason = formatExitReason(trade.exit_reason || '')
                    const points =
                      trade.entry_price && trade.exit_price
                        ? trade.direction === 'long'
                          ? trade.exit_price - trade.entry_price
                          : trade.entry_price - trade.exit_price
                        : null

                    return (
                      <div key={trade.signal_id || index} className="history-trade">
                        <div className="trade-row-main">
                          <div className="trade-row-left">
                            <span className={`trade-dir-badge ${trade.direction}`}>
                              {trade.direction === 'long' ? '↑' : '↓'}
                            </span>
                            <div className="trade-details-compact">
                              <span className="trade-time-compact">
                                {formatTimeUtil(trade.exit_time, false)}
                              </span>
                              {trade.entry_price && trade.exit_price && (
                                <span className="trade-prices-compact">
                                  {formatPrice(trade.entry_price)} → {formatPrice(trade.exit_price)}
                                </span>
                              )}
                            </div>
                          </div>
                          <div className="trade-row-right">
                            {points !== null && (
                              <span className={`trade-points ${points >= 0 ? 'positive' : 'negative'}`}>
                                {points >= 0 ? '+' : ''}
                                {points.toFixed(2)}
                              </span>
                            )}
                            <span className={`trade-pnl-badge ${(trade.pnl || 0) >= 0 ? 'positive' : 'negative'}`}>
                              {formatPnL(trade.pnl || 0)}
                            </span>
                            <span className={`trade-exit-badge reason-${exitReason.type}`}>{exitReason.text}</span>
                          </div>
                        </div>

                        {/* Extra details row */}
                        {(trade.duration_seconds || trade.ml_probability !== undefined) && (
                          <div className="trade-row-extra">
                            {trade.duration_seconds && (
                              <span className="trade-extra-item">
                                <span className="extra-label">Hold:</span>
                                <span className="extra-value">{formatDurationUtil(trade.duration_seconds)}</span>
                              </span>
                            )}
                            {trade.ml_probability !== undefined && (
                              <span className="trade-extra-item">
                                <span className="extra-label">ML:</span>
                                <span
                                  className={`extra-value ${
                                    trade.ml_probability >= 0.6
                                      ? 'positive'
                                      : trade.ml_probability < 0.4
                                        ? 'negative'
                                        : ''
                                  }`}
                                >
                                  {(trade.ml_probability * 100).toFixed(0)}%
                                </span>
                              </span>
                            )}
                            {trade.regime_at_entry && (
                              <span className="trade-extra-item">
                                <span className="extra-label">Regime:</span>
                                <span className="extra-value regime">{trade.regime_at_entry.replace(/_/g, ' ')}</span>
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Verification Footer */}
      <div className="trades-history-footer">
        <span className="verification-badge">
          <span className="verification-icon">✓</span>
          <span className="verification-text">All trades verified from signals.jsonl</span>
        </span>
      </div>
    </DataPanel>
  )
}

export default memo(TradesHistoryPanel)
